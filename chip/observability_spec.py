#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""E.2's observability additions, as a spec a script can check, not as RTL.

`src/` is not touched here. The build has been proven unchanged at the
geometry-record level since 7 August and every edit there costs a full
re-verify, which is what G.3 is for. So this day produces the specification
and the acceptance tests, and the RTL happens inside the Arm C build with
one re-verify covering both.

What E.2 asks for: a selectable measurement window with at least two
lengths, a sticky counter-overflow indication, a measurement-active
indication if it earns its pin beside `done`, a protocol and build version
the collector can read, and explicit tests proving reset, overflow, byte
readout and every mode.

What this script settles, and how:

- **The pin map.** Free pins are not assumed free. Every pin the spec calls
  free has to be absent from the gate-level netlist of the current build, and
  every pin it calls occupied has to be present. `info.yaml`'s pinout is
  checked against both.

- **The window lengths.** These are the interesting part and the corner data
  moves them. A window is only safe if the counter cannot wrap at any corner,
  and the counter is 16 bits. The three corner decks in
  `dualarm/build_current` give Arm A's frequency span from slow to fast, and
  the safe window follows from the fastest ring rather than from the nominal
  one. A window chosen at nominal wraps at the fast corner, silently, and a
  wrapped count looks exactly like a slow oscillator. That is the failure
  E.3's note calls out and it is cheaper to design out than to detect.

- **One window that always overflows.** The sticky flag cannot be tested on
  silicon without a mode that sets it, so one mode is chosen to overflow at
  every corner rather than at some of them.

- **The acceptance table.** Generated, not written by hand, so that every
  mode is covered by construction rather than by somebody remembering.

Usage:
    python3 observability_spec.py --selftest
    python3 observability_spec.py
    python3 observability_spec.py --json /tmp/obs.json --csv /tmp/tests.csv
"""

import argparse
import collections
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(ROOT, "dualarm", "build_current")

DESIGN = "tt_um_nikodemetrashvili20_ro_puf"
COUNTER_BITS = 16
COUNTER_MAX = (1 << COUNTER_BITS) - 1
CLOCK_HZ = 50000000                      # info.yaml clock_hz

# The corner decks. Names are the ones gen_dualarm_decks.py writes.
CORNER_FILES = {"ss": "dualarm_par_ss_out.txt",
                "tt": "dualarm_par_out.txt",
                "ff": "dualarm_par_ff_out.txt"}

FREQ_RE = re.compile(r"^f(\d+)\s*=\s*([0-9.eE+-]+)", re.M)

PROTOCOL_VERSION = 2      # 1 is the unversioned readout the current build has
BUILD_ID = 0x1A           # set by hand per tapeout, recorded in the writeup


# The map. Pins already in use come from info.yaml and are listed so the
# script can check them rather than to restate them. `ui[7]` is spent by the
# third arm's select bit, which E.1b settled, so everything E.2 adds has to
# come out of uio[1:7].
PIN_MAP = [
    # (port, bit, direction, owner, name)
    ("ui", 0, "in", "existing", "start"),
    ("ui", 1, "in", "existing", "arm select bit 0"),
    ("ui", 2, "in", "existing", "ro_idx[0]"),
    ("ui", 3, "in", "existing", "ro_idx[1]"),
    ("ui", 4, "in", "existing", "ro_idx[2]"),
    ("ui", 5, "in", "existing", "ro_idx[3]"),
    ("ui", 6, "in", "existing", "readout byte select"),
    ("ui", 7, "in", "armc", "arm select bit 1"),
    ("uio", 0, "out", "existing", "done"),
    ("uio", 1, "in", "e2", "window select bit 0"),
    ("uio", 2, "in", "e2", "window select bit 1"),
    ("uio", 3, "in", "e2", "read version instead of count"),
    ("uio", 4, "out", "e2", "counter overflowed, sticky"),
    ("uio", 5, "out", "e2", "measurement active"),
    ("uio", 6, "in", "spare", "reserved"),
    ("uio", 7, "in", "spare", "reserved"),
]

# Pins that must be unconnected in the current build. Anything the spec
# claims for E.2 or for Arm C has to be genuinely free today.
CLAIMED = tuple((p, b) for p, b, _d, owner, _n in PIN_MAP
                if owner in ("armc", "e2", "spare"))


# ------------------------------------------------------------------ helpers

class Results(object):
    def __init__(self):
        self.rows = []

    def add(self, cid, name, ok, detail=""):
        self.rows.append({"id": cid, "name": name, "pass": bool(ok),
                          "detail": detail})
        return ok

    def failed(self):
        return [r["id"] for r in self.rows if not r["pass"]]


def read_corner(text):
    return dict((int(i), float(v)) for i, v in FREQ_RE.findall(text))


def counts_for(freq_hz, window_cycles, clock_hz=CLOCK_HZ):
    """Edges counted in one window, before the counter is applied.

    The counter increments on ring edges while the window is open, and the
    window is `window_cycles` periods of the reference clock. Nothing here
    models the half-cycle start and stop uncertainty; the acceptance tests
    are written as ratios and bounds for that reason.
    """
    return freq_hz * window_cycles / float(clock_hz)


def counter_reading(raw):
    """What the 16-bit ripple counter shows, and whether it wrapped."""
    n = int(raw)
    return n & COUNTER_MAX, n > COUNTER_MAX


TIE_RE = re.compile(r"^\s*sky130_fd_sc_hd__conb_1\s+\S+\s*\(([^;]*)\)\s*;",
                    re.M)
ASSIGN_RE = re.compile(r"^\s*assign\s+(uo_out|uio_out|uio_oe)\[(\d)\]\s*=\s*"
                       r"(\S+?)\s*;", re.M)
CONN_RE = re.compile(r"\.\w+\s*\(\s*([^)]*?)\s*\)")
INST_RE = re.compile(
    r"^\s*(?:sky130_fd_sc_hd__\w+|ro_macro_hard)\s+\S+?\s*\((.*?)\)\s*;",
    re.S | re.M)


def busy_pins(text):
    """Which package pins carry a real signal in this build.

    A pin is not free just because its name is missing from the netlist, and
    it is not busy just because its name is present. `uio_out[7:1]` are all
    there, every one of them driven by a `conb_1` tie cell holding it at zero,
    which is what an unused output looks like after synthesis. `ui_in[7]` is
    the opposite case: the source ties it into an unused reduction, the
    optimiser deletes that, and the name is gone entirely.

    So an output is busy when the net driving it comes from something other
    than a tie cell, and an input is busy when it reaches some instance.
    """
    tied = set()
    for body in TIE_RE.findall(text):
        for net in CONN_RE.findall(body):
            tied.add(net.strip())
    connected = set()
    for body in INST_RE.findall(text):
        for net in CONN_RE.findall(body):
            connected.add(net.strip())
    busy = set()
    # An output can be busy two ways. Usually there is an `assign` from a
    # named net, and the net tells you whether real logic or a tie cell is
    # behind it. But a cell can also drive the port directly, which is what
    # `.X(uio_out[0])` is, and no assign exists for that bit at all.
    for port, bit, net in ASSIGN_RE.findall(text):
        if port == "uio_oe":
            continue
        if net.strip() not in tied:
            busy.add(("uo" if port == "uo_out" else "uio", int(bit)))
    for port, name in (("uo", "uo_out"), ("uio", "uio_out")):
        for bit in range(8):
            if "%s[%d]" % (name, bit) in connected:
                busy.add((port, bit))
    for port, name in (("ui", "ui_in"), ("uio", "uio_in")):
        for bit in range(8):
            if "%s[%d]" % (name, bit) in connected:
                busy.add((port, bit))
    return busy


# ------------------------------------------------------------ window choice

def choose_windows(fmin, fmax, clock_hz=CLOCK_HZ, bits=COUNTER_BITS):
    """Three safe windows and one that always overflows, all powers of two.

    Safe means the count cannot reach the counter's limit at the fastest
    corner. Always-overflowing means it passes the limit even at the slowest,
    so the sticky flag is provable on any die rather than only on a fast one.
    """
    limit = (1 << bits) - 1
    safe_max = int(math.floor(limit * clock_hz / float(fmax)))
    over_min = int(math.ceil(limit * clock_hz / float(fmin)))
    top_safe = 1
    while top_safe * 2 <= safe_max:
        top_safe *= 2
    overflow = 1
    while overflow <= over_min:
        overflow *= 2
    # 1:2:8 rather than 1:2:4. The widest safe window is the one with the
    # best quantisation and it should be as long as it can be; the shortest
    # is there so a linearity test has a lever arm worth measuring.
    safe = [top_safe // 8, top_safe // 4, top_safe]
    return {"safe": safe, "overflow": overflow,
            "safe_max_cycles": safe_max, "overflow_min_cycles": over_min}


# --------------------------------------------------------------- the checks

def run_checks(pinmap, busy_pins, yaml_pins, corners, windows, tests):
    res = Results()

    seen = collections.Counter((p, b) for p, b, _d, _o, _n in pinmap)
    dupes = [k for k, v in seen.items() if v > 1]
    res.add("O01", "no pin is assigned twice", not dupes,
            "duplicated: %s" % (", ".join("%s[%d]" % k for k in dupes)
                                or "none"))

    ui_bits = set(b for p, b, _d, _o, _n in pinmap if p == "ui")
    uio_bits = set(b for p, b, _d, _o, _n in pinmap if p == "uio")
    res.add("O02", "the map covers all eight ui and all eight uio bits",
            ui_bits == set(range(8)) and uio_bits == set(range(8)),
            "ui %d, uio %d" % (len(ui_bits), len(uio_bits)))

    wrong_free = [k for k in CLAIMED if k in busy_pins]
    res.add("O03", "every pin the spec claims carries no signal today",
            not wrong_free,
            "in use already: %s" % (", ".join("%s[%d]" % k for k in wrong_free)
                                    or "none"))

    existing = [(p, b) for p, b, _d, o, _n in pinmap if o == "existing"]
    missing = [k for k in existing if k not in busy_pins]
    res.add("O04", "every pin the spec calls occupied really carries one",
            not missing, "carries nothing: %s"
            % (", ".join("%s[%d]" % k for k in missing) or "none"))

    named = set()
    for port, bits in (("ui", 8), ("uo", 8), ("uio", 8)):
        for b in range(bits):
            if yaml_pins.get("%s[%d]" % (port, b)):
                named.add((port, b))
    yaml_free = set(("ui", b) for b in range(8)
                    if not yaml_pins.get("ui[%d]" % b))
    yaml_free |= set(("uio", b) for b in range(8)
                     if not yaml_pins.get("uio[%d]" % b))
    res.add("O05", "the two-arm info.yaml and the spec agree on which pins "
                   "were free",
            set(CLAIMED) == yaml_free,
            "yaml free %d, spec claims %d, differ %s"
            % (len(yaml_free), len(CLAIMED),
               ", ".join("%s[%d]" % k for k in
                         sorted(set(CLAIMED) ^ yaml_free)) or "none"))

    oe = 0
    for p, b, d, _o, _n in pinmap:
        if p == "uio" and d == "out":
            oe |= 1 << b
    res.add("O06", "uio_oe follows from the directions the map declares",
            oe == 0x31, "0x%02X" % oe)

    # ---- windows
    safe = windows["safe"]
    ok_order = safe == sorted(safe) and len(set(safe)) == 3
    powers = all(w and (w & (w - 1)) == 0
                 for w in safe + [windows["overflow"]])
    res.add("O07", "four windows, powers of two, the safe three increasing",
            ok_order and powers,
            "%s and %d" % (safe, windows["overflow"]))

    fmax = max(max(c.values()) for c in corners.values())
    fmin = min(min(c.values()) for c in corners.values())
    over_at_fast = [w for w in safe
                    if counter_reading(counts_for(fmax, w))[1]]
    res.add("O08", "no safe window can wrap, even at the fastest corner",
            not over_at_fast, "would wrap: %s" % (over_at_fast or "none"))

    safe_at_slow = not counter_reading(
        counts_for(fmin, windows["overflow"]))[1]
    res.add("O09", "the overflow window wraps even at the slowest corner",
            not safe_at_slow,
            "%.0f counts at %.1f MHz" % (counts_for(fmin,
                                                    windows["overflow"]),
                                         fmin / 1e6))

    ratios = [safe[1] / float(safe[0]), safe[2] / float(safe[0])]
    res.add("O10", "the safe windows are exact power-of-two multiples",
            ratios == [2.0, 8.0], "ratios %s" % ratios)

    # ---- version
    word = (PROTOCOL_VERSION << 8) | BUILD_ID
    res.add("O11", "the version bytes round-trip through the readout",
            (word >> 8) == PROTOCOL_VERSION and (word & 0xFF) == BUILD_ID
            and PROTOCOL_VERSION <= 0xFF and BUILD_ID <= 0xFF,
            "protocol %d, build 0x%02X" % (PROTOCOL_VERSION, BUILD_ID))

    # ---- the acceptance table
    kinds = set(t["kind"] for t in tests)
    want_kinds = {"reset", "mode", "linearity", "overflow", "readout",
                  "version", "state"}
    covered_windows = set(t["window"] for t in tests if t["kind"] == "mode")
    res.add("O12", "the acceptance table covers every kind and every mode",
            want_kinds <= kinds
            and covered_windows == set(safe + [windows["overflow"]]),
            "kinds %s, windows %s"
            % (",".join(sorted(kinds)), sorted(covered_windows)))
    return res


# ------------------------------------------------------- acceptance vectors

def build_tests(windows, corners):
    """Every acceptance test E.2 owes, generated from the spec.

    Absolute counts are deliberately absent from the expectations except
    where overflow is the point. A count depends on the die and the corner;
    a ratio between two windows on the same die does not, and that is what
    makes linearity the useful test.
    """
    safe = windows["safe"]
    allw = safe + [windows["overflow"]]
    sel = dict((w, i) for i, w in enumerate(allw))
    t = []

    def add(kind, name, setup, expect, window=None):
        t.append({"id": "E2-%02d" % (len(t) + 1), "kind": kind, "name": name,
                  "setup": setup, "expect": expect, "window": window})

    add("reset", "reset clears everything",
        "hold rst_n low for 3 clocks, release",
        "done=0, active=0, overflow=0, count reads 0")
    add("reset", "reset clears a sticky overflow",
        "run the overflow window to completion, then reset",
        "overflow=0 after reset", windows["overflow"])

    for w in allw:
        add("mode", "window select %d selects %d cycles" % (sel[w], w),
            "uio[2:1]=%d, arm A, ro_idx=0, pulse start"
            % sel[w],
            "done rises within %d clocks; count is nonzero" % (w + 8),
            window=w)

    add("state", "active is high only while the window is open",
        "uio[2:1]=0, pulse start, sample uio[5] every clock",
        "active high for %d clocks then low; done rises as active falls"
        % safe[0], window=safe[0])
    add("state", "done and active tell a fresh result from a stale one",
        "after reset, before any start",
        "done=0 and active=0, which no completed run can show")

    add("linearity", "double the window, double the count",
        "same ring, window %d then window %d" % (safe[0], safe[1]),
        "ratio in [1.98, 2.02]", window=safe[1])
    add("linearity", "eight times the window, eight times the count",
        "same ring, window %d then window %d" % (safe[0], safe[2]),
        "ratio in [7.92, 8.08]", window=safe[2])

    add("overflow", "the overflow window sets the sticky flag",
        "uio[2:1]=%d, any ring, pulse start" % sel[windows["overflow"]],
        "overflow=1 on every die and every corner", window=windows["overflow"])
    add("overflow", "the sticky flag survives the next measurement",
        "run the overflow window, then a safe window, without reset",
        "overflow stays 1", window=windows["overflow"])
    add("overflow", "a safe window never sets it",
        "reset, then every safe window on every oscillator",
        "overflow stays 0")

    add("readout", "both bytes reassemble the count",
        "after done, read ui[6]=0 then ui[6]=1",
        "high<<8 | low equals the count, and repeats stably")
    add("readout", "the count does not move between the two byte reads",
        "read low, wait 100 clocks, read low again",
        "identical")

    add("version", "the protocol byte reads back",
        "uio[3]=1, ui[6]=0", "uo_out = %d" % PROTOCOL_VERSION)
    add("version", "the build byte reads back",
        "uio[3]=1, ui[6]=1", "uo_out = 0x%02X" % BUILD_ID)
    add("version", "the version select does not disturb a stored count",
        "after done, set uio[3]=1, read, clear uio[3], read the count",
        "count unchanged")

    for arm, label in ((0, "A, automated"), (1, "B, hardened"),
                       (2, "C, constrained")):
        add("mode", "every oscillator in arm %s answers" % label,
            "arm=%d, ro_idx 0..15, window %d" % (arm, safe[1]),
            "16 distinct done pulses, every count in range",
            window=safe[1])
    return t


# ------------------------------------------------------------------ selftest

FIX_CORNERS = {
    "ss": "\n".join("f%d = %.6e" % (i, 3.0e8 + i * 1e6) for i in range(16)),
    "tt": "\n".join("f%d = %.6e" % (i, 5.5e8 + i * 1e6) for i in range(16)),
    "ff": "\n".join("f%d = %.6e" % (i, 8.0e8 + i * 1e6) for i in range(16)),
}
FIX_BUSY = (set(("ui", b) for b in range(7))
            | set(("uo", b) for b in range(8)) | set([("uio", 0)]))
FIX_YAML = dict([("ui[%d]" % b, "used") for b in range(7)]
                + [("uo[%d]" % b, "count") for b in range(8)]
                + [("uio[0]", "done")])


def run_fixture(pinmap=None, busy=None, yaml_pins=None, corners=None,
                windows=None, tests=None):
    corners = corners or dict((k, read_corner(v))
                              for k, v in FIX_CORNERS.items())
    fmin = min(min(c.values()) for c in corners.values())
    fmax = max(max(c.values()) for c in corners.values())
    windows = windows or choose_windows(fmin, fmax)
    tests = tests if tests is not None else build_tests(windows, corners)
    return run_checks(pinmap or PIN_MAP,
                      busy if busy is not None else FIX_BUSY,
                      yaml_pins if yaml_pins is not None else FIX_YAML,
                      corners, windows, tests)


def selftest():
    print("observability_spec selftest")
    ok = True
    res = run_fixture()
    if res.failed():
        print("  FAIL: clean fixture fails %s" % ", ".join(res.failed()))
        for r in res.rows:
            if not r["pass"]:
                print("        %s %s" % (r["id"], r["detail"]))
        ok = False
    else:
        print("  clean fixture passes all %d checks" % len(res.rows))

    def dup_pin():
        # Appended, not substituted. Overwriting an entry would also leave a
        # pin uncovered, and that is O02's fault, not this one.
        return {"pinmap": list(PIN_MAP)
                + [("uio", 1, "in", "e2", "a second job for uio[1]")]}

    def short_map():
        return {"pinmap": [p for p in PIN_MAP if p[:2] != ("uio", 7)]}

    def pin_in_use():
        return {"busy": FIX_BUSY | set([("uio", 4)])}

    def pin_not_in_use():
        return {"busy": FIX_BUSY - set([("ui", 3)])}

    def yaml_disagrees():
        y = dict(FIX_YAML)
        y["uio[6]"] = "somebody wrote a name here"
        return {"yaml_pins": y}

    def bad_direction():
        m = [(p, b, ("in" if d == "out" and (p, b) == ("uio", 4) else d),
              o, n) for p, b, d, o, n in PIN_MAP]
        return {"pinmap": m}

    def not_powers():
        return {"windows": {"safe": [300, 600, 2400], "overflow": 16384,
                            "safe_max_cycles": 3688,
                            "overflow_min_cycles": 11000}}

    def unsafe_window():
        # Every safe window doubled, so the ratios still read 1:2:8 and only
        # the widest one crosses the wrap line. Stretching the top window
        # alone would break the ratio check as well.
        w = choose_windows(3.0e8, 8.15e8)
        w["safe"] = [x * 2 for x in w["safe"]]
        return {"windows": w}

    def weak_overflow():
        w = choose_windows(3.0e8, 8.15e8)
        w["overflow"] = w["safe"][2]
        return {"windows": w}

    def bad_ratio():
        w = choose_windows(3.0e8, 8.15e8)
        w["safe"] = [w["safe"][0], w["safe"][0] * 2, w["safe"][0] * 4]
        return {"windows": w}

    def thin_tests():
        corners = dict((k, read_corner(v)) for k, v in FIX_CORNERS.items())
        fmin = min(min(c.values()) for c in corners.values())
        fmax = max(max(c.values()) for c in corners.values())
        w = choose_windows(fmin, fmax)
        return {"windows": w,
                "tests": [t for t in build_tests(w, corners)
                          if t["kind"] != "version"]}

    faults = [
        ("O01", "one pin assigned to two jobs", dup_pin),
        ("O02", "a map that forgets a pin", short_map),
        ("O03", "claiming a pin the build already drives", pin_in_use),
        ("O04", "calling a pin occupied that nothing uses", pin_not_in_use),
        ("O05", "info.yaml naming a pin the spec calls free", yaml_disagrees),
        ("O06", "an output pin declared as an input", bad_direction),
        ("O07", "windows that are not powers of two", not_powers),
        ("O08", "a window that wraps at the fast corner", unsafe_window),
        ("O09", "an overflow window that is safe at the slow corner",
         weak_overflow),
        ("O10", "safe windows in the wrong ratio", bad_ratio),
        ("O12", "an acceptance table missing a kind", thin_tests),
    ]
    for want, label, fn in faults:
        r2 = run_fixture(**fn())
        tripped = set(r2.failed())
        if tripped == {want}:
            print("  ok    %-4s %s" % (want, label))
        elif want in tripped:
            print("  FAIL  %-4s %s -- also tripped %s"
                  % (want, label, ", ".join(sorted(tripped - {want}))))
            ok = False
        else:
            print("  FAIL  %-4s %s -- tripped %s"
                  % (want, label, ", ".join(sorted(tripped)) or "nothing"))
            ok = False

    # O11 guards two constants in this file, so no input can reach it. The
    # fault comes from the constants themselves.
    global PROTOCOL_VERSION
    keep = PROTOCOL_VERSION
    PROTOCOL_VERSION = 0x1FF
    r3 = run_fixture()
    PROTOCOL_VERSION = keep
    if set(r3.failed()) == {"O11"}:
        print("  ok    O11  a version that does not fit in a byte")
    else:
        print("  FAIL  O11  tripped %s" % (", ".join(r3.failed()) or "nothing"))
        ok = False

    # The window chooser, against hand arithmetic that does not use it.
    limit = COUNTER_MAX
    for fmin, fmax in ((3.0e8, 8.0e8), (2.7e8, 8.9e8), (1.0e8, 2.0e8)):
        w = choose_windows(fmin, fmax)
        top = w["safe"][2]
        assert top * fmax / CLOCK_HZ <= limit, (fmin, fmax, top)
        assert top * 2 * fmax / CLOCK_HZ > limit, (fmin, fmax, top)
        assert w["overflow"] * fmin / CLOCK_HZ > limit, (fmin, fmax)
        # The chooser takes the smallest power of two past the threshold, so
        # halving it must land on or below the threshold. Comparing the half
        # against the count instead would fail at a power-of-two boundary,
        # where the threshold itself was rounded up.
        assert w["overflow"] // 2 <= w["overflow_min_cycles"], (fmin, fmax)
    print("  ok    choose_windows is tight at both ends on three spans")

    # busy_pins is the subtle one and the fixtures above hand it a ready-made
    # answer, so it gets its own case: an output held by a tie cell, an
    # output a cell drives straight, an output assigned from real logic, an
    # input something reads, and an input nothing reads.
    probe = """
 sky130_fd_sc_hd__conb_1 tie0 (.LO(netz));
 sky130_fd_sc_hd__buf_1 b0 (.A(ui_in[2]), .X(uio_out[0]));
 sky130_fd_sc_hd__buf_1 b1 (.A(uio_in[3]), .X(live));
 assign uio_out[1] = netz;
 assign uio_out[2] = live;
"""
    got = busy_pins(probe)
    want = set([("uio", 0), ("uio", 2), ("ui", 2), ("uio", 3)])
    if got == want:
        print("  ok    busy  tie-held, cell-driven, assigned, read and unread")
    else:
        print("  FAIL  busy  got %s, wanted %s"
              % (sorted(got), sorted(want)))
        ok = False

    print("\n  %s" % ("all faults isolated" if ok else "SELFTEST FAILED"))
    return 0 if ok else 1


# ---------------------------------------------------------------------- main

YAML_PIN_RE = re.compile(r"^\s{2}(ui|uo|uio)\[(\d)\]:\s*\"(.*)\"\s*$", re.M)


# O05 asks which pins were free when E.2 claimed them, which is a question
# about the two-arm design and stops being answerable off the live file the
# moment G.3 step 3 fills those pins in. The frozen copy chip/
# archive_baseline.py took in step 1 is the two-arm info.yaml, so read that
# where it exists. Widening O05 to accept a named pin would have been
# loosening a check to let an edit through, which is the thing freezing is
# for.
FROZEN_INFO = os.path.join(ROOT, "dualarm", "build_2arm_frozen",
                           "dualarm_info.yaml")


def info_path():
    if os.path.exists(FROZEN_INFO):
        return FROZEN_INFO
    return os.path.join(ROOT, "dualarm", "info.yaml")


def load():
    paths = {"netlist": os.path.join(BUILD, DESIGN + ".nl.v"),
             "info": info_path()}
    for k, v in CORNER_FILES.items():
        paths["corner_" + k] = os.path.join(BUILD, v)
    for p in paths.values():
        if not os.path.exists(p):
            raise SystemExit("missing input: %s" % p)
    with open(paths["netlist"], "r", encoding="utf-8") as fh:
        text = fh.read()
    pins = busy_pins(text)
    with open(paths["info"], "r", encoding="utf-8") as fh:
        yaml_pins = dict(("%s[%s]" % (p, b), n)
                         for p, b, n in YAML_PIN_RE.findall(fh.read()))
    corners = {}
    for k in CORNER_FILES:
        with open(paths["corner_" + k], "r", encoding="utf-8") as fh:
            corners[k] = read_corner(fh.read())
    return pins, yaml_pins, corners, paths


def report(corners, windows, tests, res):
    fmin = min(min(c.values()) for c in corners.values())
    fmax = max(max(c.values()) for c in corners.values())
    print("E.2 observability spec")
    print("  Arm A across corners: %.2f MHz slow to %.2f MHz fast, %d rings"
          % (fmin / 1e6, fmax / 1e6, len(corners["tt"])))
    print("  counter %d bits, reference clock %.0f MHz"
          % (COUNTER_BITS, CLOCK_HZ / 1e6))
    print("  a window may not exceed %d cycles or the fast corner wraps it"
          % windows["safe_max_cycles"])
    print("  a window must exceed %d cycles to wrap at the slow corner"
          % windows["overflow_min_cycles"])
    print()
    print("  %-4s %8s %12s %12s %12s  %s"
          % ("sel", "cycles", "slow count", "fast count", "us at 50MHz",
             "role"))
    allw = windows["safe"] + [windows["overflow"]]
    for i, w in enumerate(allw):
        lo = counts_for(fmin, w)
        hi = counts_for(fmax, w)
        role = ("safe on every corner" if w in windows["safe"]
                else "overflows on every corner, tests the sticky flag")
        print("  %-4d %8d %12.0f %12.0f %12.2f  %s"
              % (i, w, lo, hi, w / (CLOCK_HZ / 1e6), role))
    print()
    print("  pin map")
    for port, bit, d, owner, name in PIN_MAP:
        tag = {"existing": "", "e2": "  <- E.2", "armc": "  <- Arm C",
               "spare": "  (spare)"}[owner]
        print("    %-3s[%d] %-3s %-38s%s" % (port, bit, d, name, tag))
    oe = 0
    for p, b, d, _o, _n in PIN_MAP:
        if p == "uio" and d == "out":
            oe |= 1 << b
    print("    uio_oe = 0x%02X" % oe)
    print()
    print("  version: protocol %d, build 0x%02X, read on uo_out with "
          "uio[3]=1" % (PROTOCOL_VERSION, BUILD_ID))
    print("  acceptance tests: %d, covering %s"
          % (len(tests), ", ".join(sorted(set(t["kind"] for t in tests)))))
    print()
    for r in res.rows:
        print("  %-4s %-58s %s" % (r["id"], r["name"],
                                   "pass" if r["pass"] else "FAIL"))
    bad = res.failed()
    print("\n  %s" % ("all %d checks pass" % len(res.rows) if not bad
                      else "FAILED: " + ", ".join(bad)))
    for r in res.rows:
        if not r["pass"]:
            print("       %s: %s" % (r["id"], r["detail"]))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json")
    ap.add_argument("--csv", help="write the acceptance table here")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    pins, yaml_pins, corners, paths = load()
    fmin = min(min(c.values()) for c in corners.values())
    fmax = max(max(c.values()) for c in corners.values())
    windows = choose_windows(fmin, fmax)
    tests = build_tests(windows, corners)
    res = run_checks(PIN_MAP, pins, yaml_pins, corners, windows, tests)
    report(corners, windows, tests, res)

    if a.csv:
        with open(a.csv, "w", encoding="utf-8", newline="") as fh:
            fh.write("id,kind,name,setup,expect,window\n")
            for t in tests:
                fh.write("%s,%s,\"%s\",\"%s\",\"%s\",%s\n"
                         % (t["id"], t["kind"], t["name"], t["setup"],
                            t["expect"], t["window"] if t["window"] else ""))
        print("  wrote %s" % a.csv)
    if a.json:
        oe = 0
        for p, b, d, _o, _n in PIN_MAP:
            if p == "uio" and d == "out":
                oe |= 1 << b
        out = {
            "counter_bits": COUNTER_BITS, "clock_hz": CLOCK_HZ,
            "corner_span_hz": {"min": fmin, "max": fmax},
            "windows": windows,
            "window_counts": dict(
                (str(w), {"slow": round(counts_for(fmin, w), 1),
                          "fast": round(counts_for(fmax, w), 1),
                          "wraps_at_slow": counter_reading(
                              counts_for(fmin, w))[1],
                          "wraps_at_fast": counter_reading(
                              counts_for(fmax, w))[1]})
                for w in windows["safe"] + [windows["overflow"]]),
            "pin_map": [{"port": p, "bit": b, "direction": d, "owner": o,
                         "name": n} for p, b, d, o, n in PIN_MAP],
            "uio_oe": oe,
            "protocol_version": PROTOCOL_VERSION, "build_id": BUILD_ID,
            "tests": tests,
            "checks": res.rows,
            "source": dict((k, os.path.relpath(v, ROOT).replace(os.sep, "/"))
                           for k, v in sorted(paths.items())),
        }
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print("  wrote %s" % a.json)
    return 1 if res.failed() else 0


if __name__ == "__main__":
    sys.exit(main())
