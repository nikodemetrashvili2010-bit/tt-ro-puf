#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Prove every ring in a final netlist is still the ring that was designed.

The go/no-go generator reconstructs each oscillator as one enable NAND,
thirty inverters and a tap buffer, and reads the ring-net capacitances from
the SPEF. That is only valid if the placed-and-routed netlist still has that
ring with nothing added to the loop. Gate-level simulation cannot check it:
an Arm A or Arm C ring is a zero-delay loop in the functional models, so
the gate-level job never enables one. This file is the only check there is.

Until 10 September 2026 it counted the cells under each ring's hierarchy by
name and cell type, and the docstring said an inserted buffer would fail it.
That was wrong, and it was found by planting one. The flow names a cell it
inserts `fanout12` or `hold79` or `wire3` at the top level, not under the
ring, so a buffer spliced into a loop never appeared in the census and the
ring still counted 1 + 30 + 1. The check had passed in the gate on every
push since it was written and would have passed on a broken ring. The
two-arm netlist it was run on turns out to be clean, by the walk below, so
nothing was lost; the check was.

Now it follows the wires. From each ring's NAND output it walks net to
next input to next output until it arrives back at the NAND, and looks at
every load on every net it crosses. Names find the NAND and the tap; the
loop itself is whatever is actually wired.

Per ring:

  T01  the ring is in the netlist (its u_nand exists)
  T02  u_nand is a nand2_1
  T03  the loop closes on u_nand.B after exactly thirty inverters
  T04  every one of those inverters is an inv_1, none resized
  T05  no instance outside the ring touches any loop net, in the loop or
       hanging off it
  T06  exactly one tap, u_buf, a buf_1, on a loop net

Arm A rings live under u_puf.u_core.g_ro_bank[N].u_ro and Arm C rings
under u_puf.u_core.g_armc[N].u_roc. That last name was wrong in the first
version of this file, u_ro for both, and nothing here could have said so:
the fixture is built from the same constant, and the only real netlist on
disk has no Arm C. Run 76's box report happened to print an Arm C instance
name and that is how it was caught. So the selftest now reads the two
instance names out of ro_puf_core.v and fails if the constants drift from
the RTL. Arm B is a sealed hardened macro and is checked by the physical
flow, not here. --arms says which to expect: the
frozen two-arm netlist has no Arm C and is run with A; the three-arm build
is run with AC and a missing Arm C fails T01.

    python3 verify_ring_topology.py --selftest
    python3 verify_ring_topology.py                       # frozen, Arm A
    python3 verify_ring_topology.py --arms AC \\
        --netlist runs/wokwi/final/nl/*.nl.v --annotate   # in the gds job

--annotate prints a workflow command and exits 0 either way, the same
arrangement as placement_fidelity.py: the rest of the run is worth having.
Without it a broken ring is exit 1, which is what the gate wants.
"""

import argparse
import glob
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
DEFAULT_NL = os.path.join(
    PROJ, "dualarm", "build_current", "tt_um_nikodemetrashvili20_ro_puf.nl.v")

N_INV = 30
ARMS = {"A": ("Arm A", "u_puf.u_core.g_ro_bank[%d].u_ro."),
        "C": ("Arm C", "u_puf.u_core.g_armc[%d].u_roc.")}
CORE_RTL = os.path.join(PROJ, "dualarm", "src", "ro_puf_core.v")
OUT_PINS = ("X", "Y", "Q", "Q_N", "out")
INST_RX = re.compile(r"^\s*(sky130_fd_sc_hd__\w+|ro_macro_hard)\s+(\\?\S+)"
                     r"\s*\((.*?)\);", re.M | re.S)
PIN_RX = re.compile(r"\.(\w+)\(\s*(\\?[^\s)]+)\s*\)")
ANNOTATION_LIMIT = 3600

CHECKS = (
    ("T01", "the ring is in the netlist"),
    ("T02", "u_nand is a nand2_1"),
    ("T03", "the loop closes on u_nand.B after exactly %d inverters" % N_INV),
    ("T04", "every inverter in the loop is an inv_1"),
    ("T05", "nothing outside the ring touches a loop net"),
    ("T06", "exactly one tap, u_buf, a buf_1, on a loop net"),
)


# ---------------------------------------------------------------- netlist


def parse(path):
    """{instance: (cell, {pin: net})} and {net: [(instance, pin)]}."""
    with io.open(path, "r", encoding="utf-8", errors="replace") as fh:
        txt = re.sub(r"//.*", "", fh.read())
    insts, conns = {}, {}
    for m in INST_RX.finditer(txt):
        cell = m.group(1).replace("sky130_fd_sc_hd__", "")
        name = m.group(2).lstrip("\\")
        pins = {p: n.lstrip("\\") for p, n in PIN_RX.findall(m.group(3))}
        insts[name] = (cell, pins)
        for p, n in pins.items():
            conns.setdefault(n, []).append((name, p))
    return insts, conns


# ------------------------------------------------------------------- walk


def walk(prefix, insts, conns):
    """Follow one ring round. Returns {check_id: [problem, ...]}."""
    probs = {cid: [] for cid, _ in CHECKS}
    nand = prefix + "u_nand"
    tapname = prefix + "u_buf"
    if nand not in insts:
        probs["T01"].append("no u_nand")
        return probs
    cell, pins = insts[nand]
    if cell != "nand2_1":
        probs["T02"].append("u_nand is %s" % cell)
    if "Y" not in pins:
        probs["T02"].append("u_nand has no Y")
        return probs

    cur = pins["Y"]
    inverters = []
    taps = []
    closed_on = None
    for _ in range(2 * N_INV + 8):
        loads = [(i, p) for i, p in conns.get(cur, []) if p not in OUT_PINS]
        ring_next = [(i, p) for i, p in loads
                     if i.startswith(prefix) and i not in (nand, tapname)]
        back = [(i, p) for i, p in loads if i == nand]
        tap = [(i, p) for i, p in loads if i == tapname]
        foreign = [(i, p) for i, p in loads if not i.startswith(prefix)]
        taps.extend(tap)
        if back:
            closed_on = back[0][1]
            for i, p in foreign:
                probs["T05"].append("%s.%s hangs off %s" % (i, p, cur))
            break
        if len(ring_next) == 1:
            for i, p in foreign:
                probs["T05"].append("%s (%s) hangs off %s"
                                    % (i, insts[i][0], cur))
            inst, _ = ring_next[0]
            inverters.append(inst)
            cur = insts[inst][1].get("Y")
        elif not ring_next and len(foreign) == 1 and any(
                o in insts[foreign[0][0]][1] for o in OUT_PINS):
            # something was spliced into the loop: step through it
            inst = foreign[0][0]
            probs["T05"].append("%s (%s) is in the loop on %s"
                                % (inst, insts[inst][0], cur))
            fp = insts[inst][1]
            cur = next(fp[o] for o in OUT_PINS if o in fp)
        else:
            probs["T03"].append("loop does not continue past %s (%d ring "
                                "loads, %d foreign)"
                                % (cur, len(ring_next), len(foreign)))
            break
        if cur is None:
            probs["T03"].append("a loop cell has no output pin")
            break
    else:
        probs["T03"].append("loop never returns to u_nand")

    if closed_on is not None and closed_on != "B":
        probs["T03"].append("loop closes on u_nand.%s" % closed_on)
    if closed_on is not None and len(inverters) != N_INV:
        probs["T03"].append("%d inverters in the loop, expected %d"
                            % (len(inverters), N_INV))
    for inst in inverters:
        c = insts[inst][0]
        if c != "inv_1":
            probs["T04"].append("%s is %s" % (inst[len(prefix):], c))
    if len(taps) != 1:
        probs["T06"].append("%d taps on the loop, expected 1" % len(taps))
    elif insts[tapname][0] != "buf_1":
        probs["T06"].append("u_buf is %s" % insts[tapname][0])
    return probs


def check_netlist(path, arms, n_ro):
    insts, conns = parse(path)
    report = {"netlist": path, "instances": len(insts), "rings": []}
    for key in arms:
        label, fmt = ARMS[key]
        for k in range(n_ro):
            probs = walk(fmt % k, insts, conns)
            report["rings"].append((label, k, probs))
    return report


def failed_checks(report):
    out = {}
    for label, k, probs in report["rings"]:
        for cid, lst in probs.items():
            if lst:
                out.setdefault(cid, []).append((label, k, lst))
    return out


# ----------------------------------------------------------------- report


def print_report(report, arms):
    bad = failed_checks(report)
    for label, k, probs in report["rings"]:
        flat = [p for lst in probs.values() for p in lst]
        if flat:
            print("[FAIL] %s ring %2d: %s" % (label, k, "; ".join(flat)))
        else:
            print("[ok]   %s ring %2d: 1 nand + %d inv + 1 buf, nothing on "
                  "the loop that is not the ring" % (label, k, N_INV))
    for cid, name in CHECKS:
        print("  %s  %-58s %s" % (cid, name, "FAIL" if cid in bad else "pass"))
    n = len(report["rings"])
    clean = sum(1 for _, _, p in report["rings"]
                if not any(p.values()))
    print("== SUMMARY == %d/%d rings intact (%s) in %s, %d instances"
          % (clean, n, ", ".join(ARMS[a][0] for a in arms),
             os.path.basename(report["netlist"]), report["instances"]))
    if bad:
        print("A failing ring means the flow changed the oscillator, and the "
              "lumped-C go/no-go assumption no longer holds for it.")
    return clean, n


def encode(text):
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def annotation(report, arms):
    bad = failed_checks(report)
    n = len(report["rings"])
    clean = sum(1 for _, _, p in report["rings"] if not any(p.values()))
    names = " and ".join(ARMS[a][0] for a in arms)
    if not bad:
        title = "Rings: %d of %d intact, %s" % (clean, n, names)
        kind = "notice"
        body = "every loop is 1 nand + %d inv + 1 buf with nothing else " \
               "on it" % N_INV
    else:
        title = "RING BROKEN: %d of %d intact, %s" % (clean, n, names)
        kind = "error"
        lines = []
        for label, k, probs in report["rings"]:
            for lst in probs.values():
                for p in lst:
                    lines.append("  %s %d: %s" % (label, k, p))
        body = "\n".join(lines[:24])
        if len(lines) > 24:
            body += "\n  ... and %d more" % (len(lines) - 24)
    enc = encode(body)
    while len(enc) > ANNOTATION_LIMIT:
        body = body[:len(body) * 2 // 3]
        enc = encode(body)
    return "::%s title=%s::%s" % (kind, title.replace("::", " "), enc)


# ---------------------------------------------------------------- fixture


def fixture(arms=("A", "C"), n_ro=2, fault=None):
    """A netlist in the real file's shape: rings, a tap sink each, and a
    few unrelated cells, then one planted fault."""
    L = ["module tt_um_fixture ();"]

    def inst(cell, name, **pins):
        body = ", ".join(".%s(%s )" % (p, n) for p, n in pins.items())
        L.append(" sky130_fd_sc_hd__%s \\%s  (%s);" % (cell, name, body))

    for key in arms:
        fmt = ARMS[key][1]
        for k in range(n_ro):
            P = fmt % k
            net = lambda i: P + "n[%d]" % i
            hit = fault and fault.get("arm") == key and fault.get("ring") == k
            nand_cell = "nand2_1"
            if hit and fault["kind"] == "nand":
                nand_cell = "nand2_2"
            nb, na = "B", "A"
            if hit and fault["kind"] == "closes_on_A":
                nb, na = "A", "B"
            inst(nand_cell, P + "u_nand", **{na: P + "en", nb: net(N_INV),
                                             "Y": net(0)})
            for i in range(1, N_INV + 1):
                if hit and fault["kind"] == "missing" and i == 12:
                    continue
                a = net(i - 1)
                if hit and fault["kind"] == "missing" and i == 13:
                    a = net(11)
                if hit and fault["kind"] == "spliced" and i == 8:
                    inst("buf_2", "wire99", A=net(7), X="planted")
                    a = "planted"
                y = net(i)
                if hit and fault["kind"] == "open" and i == N_INV:
                    y = "deadend"
                cell = "inv_1"
                if hit and fault["kind"] == "resized" and i == 5:
                    cell = "inv_2"
                inst(cell, P + "g_inv[%d].u_inv" % i, A=a, Y=y)
            if hit and fault["kind"] == "sideload":
                inst("clkdlybuf4s25_1", "fanout77", A=net(7), X="fan_out")
            if not (hit and fault["kind"] == "tap_missing"):
                tcell = "buf_1"
                if hit and fault["kind"] == "tap_type":
                    tcell = "buf_2"
                inst(tcell, P + "u_buf", A=net(N_INV // 2), X=P + "out")
            inst("and2_1", "_%d%d_" % (ord(key), k), A=P + "out", B="sel",
                 X="ro_out%s%d" % (key, k))
    if fault and fault["kind"] == "bank_missing":
        drop = ARMS[fault["arm"]][1] % fault["ring"]
        L = [l for l in L if drop not in l]
    L += [" sky130_fd_sc_hd__dfrtp_1 \\u_puf.u_core.en_q  (.D(d ), .Q(sel ), "
          ".CLK(clk ), .RESET_B(rst ));",
          " sky130_fd_sc_hd__buf_1 input3 (.A(ui_in[3] ), .X(net3 ));",
          "endmodule", ""]
    return "\n".join(L)


FAULTS = (
    ("T01", "a whole ring missing from the netlist",
     dict(arm="C", ring=1, kind="bank_missing")),
    ("T02", "the enable NAND resized",
     dict(arm="A", ring=0, kind="nand")),
    ("T03", "an inverter dropped, 29 in the loop",
     dict(arm="A", ring=1, kind="missing")),
    ("T03", "the loop left open at the last inverter",
     dict(arm="C", ring=0, kind="open")),
    ("T03", "the loop closing on u_nand.A instead of B",
     dict(arm="A", ring=0, kind="closes_on_A")),
    ("T04", "an inverter resized to inv_2",
     dict(arm="C", ring=1, kind="resized")),
    ("T05", "a buffer spliced into the loop, the fault the old check missed",
     dict(arm="A", ring=1, kind="spliced")),
    ("T05", "a fanout buffer hung off a loop net",
     dict(arm="C", ring=0, kind="sideload")),
    ("T06", "the tap buffer resized",
     dict(arm="A", ring=0, kind="tap_type")),
    ("T06", "the tap buffer missing",
     dict(arm="C", ring=1, kind="tap_missing")),
)


def selftest():
    import shutil
    import tempfile
    ok = True
    print("verify_ring_topology selftest")
    tmp = tempfile.mkdtemp(prefix="vrt")

    def run(text):
        p = os.path.join(tmp, "f.nl.v")
        with io.open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        return check_netlist(p, ("A", "C"), 2)

    try:
        rep = run(fixture())
        bad = failed_checks(rep)
        if bad:
            print("  FAIL  clean fixture tripped %s" % ", ".join(sorted(bad)))
            ok = False
        else:
            print("  clean fixture: 4 rings, all %d checks pass, and the "
                  "annotation is a notice" % len(CHECKS))
        if not annotation(rep, ("A", "C")).startswith("::notice"):
            print("  FAIL  clean fixture should annotate as a notice")
            ok = False
        for want, label, f in FAULTS:
            rep = run(fixture(fault=f))
            tripped = set(failed_checks(rep))
            if tripped == {want}:
                print("  ok    %s  %s" % (want, label))
            else:
                print("  FAIL  %s  %s -- tripped %s"
                      % (want, label, ", ".join(sorted(tripped)) or "nothing"))
                ok = False
            if not annotation(rep, ("A", "C")).startswith("::error"):
                print("  FAIL  %s should annotate as an error" % want)
                ok = False
        # The names in ARMS against the RTL that makes them. This is the
        # control that would have caught u_ro versus u_roc.
        rtl_ok = True
        if os.path.exists(CORE_RTL):
            with io.open(CORE_RTL, "r", encoding="utf-8",
                         errors="replace") as fh:
                rtl = fh.read()
            for key, (label, fmt) in sorted(ARMS.items()):
                block, inst = re.match(r"u_puf\.u_core\.(\w+)\[%d\]\.(\w+)\.$",
                                       fmt).groups()
                # the parameter list nests parentheses, #(.IDX(i)), so
                # match to the end of the line rather than to the first )
                pat = (r"begin\s*:\s*" + block + r"\b[\s\S]{0,400}?\bro_\w+\s*"
                       r"#\([^\n]*?\)\s*" + inst + r"\s*\(")
                if re.search(pat, rtl):
                    print("  ok    %s is %s[N].%s in ro_puf_core.v"
                          % (label, block, inst))
                else:
                    print("  FAIL  %s: ro_puf_core.v has no %s[N].%s"
                          % (label, block, inst))
                    rtl_ok = False
        else:
            print("  FAIL  ro_puf_core.v not found, names unchecked")
            rtl_ok = False
        ok = ok and rtl_ok

        # The real-input control: the frozen two-arm netlist, Arm A only.
        if os.path.exists(DEFAULT_NL):
            rep = check_netlist(DEFAULT_NL, ("A",), 16)
            clean = sum(1 for _, _, p in rep["rings"] if not any(p.values()))
            if clean == 16 and not failed_checks(rep):
                print("  control  frozen two-arm netlist: 16 of 16 Arm A "
                      "rings intact by the walk")
            else:
                print("  FAIL  frozen two-arm netlist: %d of 16" % clean)
                ok = False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n  %s" % ("selftest passed" if ok else "SELFTEST FAILED"))
    return 0 if ok else 1


# ------------------------------------------------------------------- main


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--netlist", default=DEFAULT_NL,
                    help="the final netlist; a glob is accepted")
    ap.add_argument("--arms", default="A",
                    help="which arms to expect: A, C or AC (default A, "
                         "which is what the frozen two-arm netlist has)")
    ap.add_argument("--n-ro", type=int, default=16)
    ap.add_argument("--annotate", action="store_true",
                    help="print a ::notice:: or ::error:: workflow command "
                         "and exit 0 either way")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    arms = tuple(a for a in "AC" if a in args.arms.upper())
    if not arms:
        ap.error("--arms must name A, C or both")
    paths = sorted(glob.glob(args.netlist)) or [args.netlist]
    if not os.path.exists(paths[0]):
        print("error: netlist not found: %s" % args.netlist, file=sys.stderr)
        if args.annotate:
            print("::error title=Rings::no netlist at %s" % args.netlist)
            return 0
        return 2
    report = check_netlist(paths[0], arms, args.n_ro)
    clean, n = print_report(report, arms)
    if args.annotate:
        print(annotation(report, arms))
        return 0
    return 0 if clean == n else 1


if __name__ == "__main__":
    raise SystemExit(main())
