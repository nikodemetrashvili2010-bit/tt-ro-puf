#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Did Arm A end up where it was told to go.

Run 74 on 8 September settled that the 512 Arm A cells cannot be pinned
FIRM at step 17. OpenROAD's cutRows refuses to cut any row that holds a
fixed standard cell (ODB-0386, "contains N placed instances and will not be
cut"), Arm A shares 37 rows with the Arm B macro block, so those rows ran
whole through the macros and the endcaps landed inside them. Three runs,
same three macros.

So the cells go in at step 33 instead, through MANUAL_GLOBAL_PLACEMENTS,
and step 33 sets PLACED rather than FIRM. PLACED means detailed placement
at step 34 is allowed to move them, and it will if global placement has
put something else on the same sites. The flow reports the displacement
afterwards, in a log nobody can read from here.

This reads the DEF the build wrote and says, per cell, whether it is where
config.json told the flow to put it. It does not fail the job: a moved
cell is a result about the mechanism and the rest of the run (gate-level
test, precheck) is worth having either way. --strict turns that around for
use outside CI.

Checks:

  F01  every instance config.json places is in the DEF
  F02  every one stands at its coordinate, to the dbu
  F03  every one carries its orientation
  F04  none is UNPLACED
  F05  the intent has every Arm A ring cell and nothing else

F05 is the guard against the intent itself: 16 rings of 32 cells, named as
the RTL names them, and no macro, no Arm C cell, nothing hand-added.

The real-input control is the frozen two-arm DEF. The coordinates came out
of it, so it has to pass 512 of 512, and it is run in the gate for that
reason: if the checker and the intent ever disagree on the source, the
gate goes red before a build is spent finding out.

DEF names are escaped per bracket, g_ro_bank\\[0\\], and config.json names
are not. That is LibreLane's own escape_verilog_name and the same rule
gen_placement_cfg.py's P08 round-trips.

    python3 chip/placement_fidelity.py --selftest
    python3 chip/placement_fidelity.py \\
        --def dualarm/build_current/tt_um_nikodemetrashvili20_ro_puf.def
    python3 chip/placement_fidelity.py --def runs/wokwi/final/def/*.def \\
        --annotate

"""

import argparse
import glob
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIG = os.path.join(ROOT, "dualarm", "src", "config.json")
FROZEN_DEF = os.path.join(ROOT, "dualarm", "build_current",
                          "tt_um_nikodemetrashvili20_ro_puf.def")
KEY = "MANUAL_GLOBAL_PLACEMENTS"
RING_RX = re.compile(r"^u_puf\.u_core\.g_ro_bank\[(\d+)\]\.u_ro\.")
RINGS, CELLS_PER_RING = 16, 32
ANNOTATION_LIMIT = 3600


def escape(name):
    """LibreLane's escape_verilog_name: a backslash before each bracket."""
    return name.replace("[", "\\[").replace("]", "\\]")


# ------------------------------------------------------------------ inputs


def read_intent(config_path):
    """The placements config.json asks for, as {name: (x_dbu, y_dbu, orient)}.

    Microns to dbu by Decimal, the way LibreLane's reader does it, so
    261.28 comes out 261280 and not 261279. That trap was checked on 8
    September and does not fire, because the flow parses config floats
    as Decimal end to end; this mirrors it rather than assuming it.
    """
    from decimal import Decimal
    with io.open(config_path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh, parse_float=Decimal)
    body = cfg.get(KEY) or {}
    out = {}
    for name, info in body.items():
        x, y = info["location"]
        out[name] = (int(Decimal(x) * 1000), int(Decimal(y) * 1000),
                     str(info["orientation"]))
    return out


def read_def(path):
    """COMPONENTS of a DEF, as {name: (status, x, y, orient)}.

    An entry can wrap onto several lines and ends at a semicolon, so lines
    are joined until one does. An UNPLACED component has no coordinate.
    """
    comps = {}
    incomp = False
    buf = ""
    with io.open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if s.startswith("COMPONENTS "):
                incomp = True
                continue
            if s.startswith("END COMPONENTS"):
                break
            if not incomp:
                continue
            buf = (buf + " " + s).strip() if buf else s
            if not buf.endswith(";"):
                continue
            entry, buf = buf, ""
            if not entry.startswith("- "):
                continue
            head = entry.split()
            name = head[1]
            m = re.search(r"\+ (PLACED|FIXED|COVER|FIRM|LOCKED)\s*"
                          r"\( (-?\d+) (-?\d+) \) (\w+)", entry)
            if m:
                comps[name] = (m.group(1), int(m.group(2)), int(m.group(3)),
                               m.group(4))
            else:
                comps[name] = ("UNPLACED", None, None, None)
    return comps


# ----------------------------------------------------------------- compare


def compare(intent, comps):
    rep = {"intended": len(intent), "found": 0, "in_place": 0,
           "missing": [], "moved": [], "rotated": [], "unplaced": [],
           "max_disp_dbu": 0}
    for name in sorted(intent):
        x, y, o = intent[name]
        c = comps.get(escape(name))
        if c is None:
            rep["missing"].append(name)
            continue
        rep["found"] += 1
        st, cx, cy, co = c
        if st == "UNPLACED":
            rep["unplaced"].append(name)
            continue
        ok = True
        if (cx, cy) != (x, y):
            d = max(abs(cx - x), abs(cy - y))
            rep["moved"].append((name, x, y, cx, cy, d))
            rep["max_disp_dbu"] = max(rep["max_disp_dbu"], d)
            ok = False
        if co != o:
            rep["rotated"].append((name, o, co))
            ok = False
        if ok:
            rep["in_place"] += 1
    return rep


class Results(object):
    def __init__(self):
        self.rows = []

    def add(self, cid, name, ok, detail=""):
        self.rows.append({"id": cid, "name": name, "pass": bool(ok),
                          "detail": detail})

    def failed(self):
        return [r["id"] for r in self.rows if not r["pass"]]


def run_checks(intent, rep):
    res = Results()
    res.add("F01", "every instance config.json places is in the DEF",
            not rep["missing"],
            "%d missing" % len(rep["missing"]) if rep["missing"]
            else "%d of %d found" % (rep["found"], rep["intended"]))
    res.add("F02", "every one stands at its coordinate, to the dbu",
            not rep["moved"],
            "%d moved, max %.3f um" % (len(rep["moved"]),
                                       rep["max_disp_dbu"] / 1000.0)
            if rep["moved"] else "none moved")
    res.add("F03", "every one carries its orientation",
            not rep["rotated"],
            "%d rotated" % len(rep["rotated"]) if rep["rotated"]
            else "none rotated")
    res.add("F04", "none is UNPLACED",
            not rep["unplaced"],
            "%d unplaced" % len(rep["unplaced"]) if rep["unplaced"]
            else "all placed")
    # The intent itself: sixteen rings of thirty-two, nothing else.
    per = {}
    stray = []
    for name in intent:
        m = RING_RX.match(name)
        if m:
            per[int(m.group(1))] = per.get(int(m.group(1)), 0) + 1
        else:
            stray.append(name)
    shape_ok = (not stray and sorted(per) == list(range(RINGS))
                and all(v == CELLS_PER_RING for v in per.values()))
    res.add("F05", "the intent is every Arm A ring cell and nothing else",
            shape_ok,
            "%d rings, %s cells each, %d stray"
            % (len(per), sorted(set(per.values())) or "-", len(stray)))
    return res


# ------------------------------------------------------------------ report


def headline(rep):
    if rep["intended"] == 0:
        return "config.json places nothing through %s" % KEY
    if rep["in_place"] == rep["intended"]:
        return ("Arm A: %d of %d at their coordinate and orientation"
                % (rep["in_place"], rep["intended"]))
    return ("Arm A: %d of %d in place, %d moved (max %.3f um), "
            "%d rotated, %d missing, %d unplaced"
            % (rep["in_place"], rep["intended"], len(rep["moved"]),
               rep["max_disp_dbu"] / 1000.0, len(rep["rotated"]),
               len(rep["missing"]), len(rep["unplaced"])))


def body_lines(rep, limit=12):
    out = []
    for name, x, y, cx, cy, d in rep["moved"][:limit]:
        out.append("  moved   %s  %d,%d -> %d,%d  (%.3f um)"
                   % (name, x, y, cx, cy, d / 1000.0))
    for name, o, co in rep["rotated"][:limit]:
        out.append("  rotated %s  %s -> %s" % (name, o, co))
    for name in rep["missing"][:limit]:
        out.append("  missing %s" % name)
    for name in rep["unplaced"][:limit]:
        out.append("  unplaced %s" % name)
    n = (len(rep["moved"]) + len(rep["rotated"]) + len(rep["missing"])
         + len(rep["unplaced"]))
    if n > len(out):
        out.append("  ... and %d more" % (n - len(out)))
    return out


def encode(text):
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def render_annotation(rep):
    """A notice when all is well, an error when it is not. Neither fails
    the job on its own; only the exit code does that."""
    kind = "notice" if rep["in_place"] == rep["intended"] else "error"
    body = "\n".join(body_lines(rep))
    enc = encode(body)
    while len(enc) > ANNOTATION_LIMIT:
        body = body[:len(body) * 2 // 3]
        enc = encode(body)
    return "::%s title=%s::%s" % (kind, headline(rep).replace("::", " "),
                                  enc)


# ----------------------------------------------------------------- fixture


def fixture_intent():
    """Six cells of ring 0 and ring 1 - enough for every fault - plus a
    full-shape intent for F05, built rather than typed."""
    full = {}
    for r in range(RINGS):
        for i in range(CELLS_PER_RING):
            nm = "u_puf.u_core.g_ro_bank[%d].u_ro.g_inv[%d].u_inv" % (r, i)
            full[nm] = (247480 + 1380 * i, 70720 + 2720 * r,
                        "N" if r % 2 == 0 else "FS")
    return full


def fixture_def(intent, move=None, rotate=None, drop=None, unplace=None,
                extra=True):
    lines = ["VERSION 5.8 ;", "DESIGN fixture ;",
             "UNITS DISTANCE MICRONS 1000 ;",
             "COMPONENTS %d ;" % (len(intent) + (1 if extra else 0))]
    for name in sorted(intent):
        x, y, o = intent[name]
        if name == drop:
            continue
        if name == unplace:
            lines.append("    - %s sky130_fd_sc_hd__inv_1 ;" % escape(name))
            continue
        if name == move:
            x += 460
        if name == rotate:
            o = "FN" if o == "N" else "S"
        # wrap one entry to prove the joiner works
        lines.append("    - %s sky130_fd_sc_hd__inv_1" % escape(name))
        lines.append("      + PLACED ( %d %d ) %s ;" % (x, y, o))
    if extra:
        lines.append("    - _999_ sky130_fd_sc_hd__buf_1 + PLACED "
                     "( 1000 1000 ) N ;")
    lines += ["END COMPONENTS", "END DESIGN", ""]
    return "\n".join(lines)


FAULTS = (
    ("F01", "a cell missing from the DEF", dict(drop=0)),
    ("F02", "a cell one site to the right", dict(move=0)),
    ("F03", "a cell mirrored", dict(rotate=0)),
    ("F04", "a cell the flow never placed", dict(unplace=0)),
)


def selftest():
    import tempfile
    import shutil
    ok = True
    print("placement_fidelity selftest")
    tmp = tempfile.mkdtemp(prefix="pfix")
    intent = fixture_intent()
    names = sorted(intent)

    def bad(msg):
        print("  FAIL  %s" % msg)

    def run(text):
        p = os.path.join(tmp, "x.def")
        with io.open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        rep = compare(intent, read_def(p))
        return rep, run_checks(intent, rep)

    try:
        rep, res = run(fixture_def(intent))
        if res.failed() or rep["in_place"] != len(intent):
            bad("clean fixture: failed %s, %d of %d in place"
                % (", ".join(res.failed()) or "nothing", rep["in_place"],
                   len(intent)))
            ok = False
        else:
            print("  clean fixture passes all %d checks, %d of %d in place, "
                  "and the stray instance is ignored"
                  % (len(res.rows), rep["in_place"], len(intent)))
        ann = render_annotation(rep)
        if not ann.startswith("::notice"):
            bad("clean fixture should annotate as a notice")
            ok = False

        for want, label, kw in FAULTS:
            kw = {k: names[v] for k, v in kw.items()}
            rep, res = run(fixture_def(intent, **kw))
            tripped = set(res.failed())
            if tripped == {want}:
                print("  ok    %-4s %s" % (want, label))
            else:
                bad("%-4s %s -- tripped %s"
                    % (want, label, ", ".join(sorted(tripped)) or "nothing"))
                ok = False
            if want != "F05" and not render_annotation(rep).startswith(
                    "::error"):
                bad("%-4s should annotate as an error" % want)
                ok = False

        # F05 is about the intent, not the DEF: a stray name, a short ring
        for label, mut in (("a macro in the intent",
                            lambda d: d.update(
                                {"u_rob0": (3220, 20000, "N")})),
                           ("a ring one cell short",
                            lambda d: d.pop(names[0]))):
            d2 = dict(intent)
            mut(d2)
            res = run_checks(d2, compare(d2, {}))
            if "F05" in res.failed():
                print("  ok    F05  %s" % label)
            else:
                bad("F05  %s -- not caught" % label)
                ok = False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n  %s" % ("selftest passed" if ok else "SELFTEST FAILED"))
    return 0 if ok else 1


# -------------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--def", dest="def_path", default=None,
                    help="the DEF to check; a glob is accepted")
    ap.add_argument("--config", default=CONFIG)
    ap.add_argument("--annotate", action="store_true",
                    help="emit a ::notice:: or ::error:: workflow command")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero if any check fails")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.def_path:
        ap.error("--def is required")
    paths = sorted(glob.glob(a.def_path)) or [a.def_path]
    if not os.path.exists(paths[0]):
        print("no DEF at %s" % a.def_path)
        if a.annotate:
            print("::error title=Arm A placement::no DEF at %s" % a.def_path)
        return 1 if a.strict else 0
    intent = read_intent(a.config)
    rep = compare(intent, read_def(paths[0]))
    res = run_checks(intent, rep)
    print(headline(rep))
    for line in body_lines(rep):
        print(line)
    for r in res.rows:
        print("  %s  %-58s %s" % (r["id"], r["name"],
                                  "pass" if r["pass"] else "FAIL"))
        if r["detail"]:
            print("        %s" % r["detail"])
    if a.annotate:
        print(render_annotation(rep))
    if a.json:
        with io.open(a.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"def": paths[0], "report": rep,
                       "checks": res.rows}, fh, indent=2, sort_keys=True)
            fh.write("\n")
    bad = res.failed()
    return 1 if (bad and a.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
