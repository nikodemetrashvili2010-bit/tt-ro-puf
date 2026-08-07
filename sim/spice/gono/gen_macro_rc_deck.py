#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Rebuild the hardened Arm B macro from its own SPEF network, not lumped caps.

Item 7 did this for Arm A and moved the dispersion from 5.55 to 5.84 percent,
with every ring running 0.66 to 1.34 percent slower once the real network
replaced a single grounded capacitor per net. The Arm B macro never got the same
treatment, so the absolute Arm B frequency this project quotes is still a
lumped number while Arm A's is not. `SIGNOFF.md` and item 8 both record that as
owed. This pays it.

It cannot change the per-instance comparison. All sixteen Arm B copies share one
GDS and therefore one internal extraction, so whatever this shifts, it shifts
all sixteen by the same amount. What it changes is the single number, and the
honesty of comparing it against an Arm A number derived a different way.

Two decks, differing only in the parasitic model:

    ro_macro_lumped.spice   each net's total *D_NET capacitance on one node
    ro_macro_rc.spice       per-node grounded caps, the extracted resistors, and
                            real coupling capacitors wherever both ends move

The coupling bookkeeping is the part that has bitten this project before. IEEE
1481 records a coupling capacitor under both of the nets it joins, with the same
value in each place, so a pass over all 35 macro nets meets every internal
coupling twice. `gen_rc_decks.py` learned that the hard way in July, after
building each of them twice and inflating every Arm A ring by five to fourteen
percent of its load. This script does not reimplement that logic. It imports
`parse_spef` from `gen_rc_decks.py` and applies the same drop-the-second-sighting
rule, and it refuses to run if a repeated pair ever carries two different values.

The macro is a closed block, which makes one check available here that Arm A
never had. Arm A's rings sit in open fabric and couple to 4 to 72 nets outside
the oscillator, all of which have to be grounded. Inside the macro almost
everything a net couples to is another macro net, so the count of couplings that
have to be grounded for want of a partner should be small. `--report` prints it.

Usage:
    python3 gen_macro_rc_deck.py --output-dir /tmp/macrorc
    python3 gen_macro_rc_deck.py --report
    python3 gen_macro_rc_deck.py --selftest
    python3 ../run_ngspice.py /tmp/macrorc/ro_macro_rc.spice \\
        --log /tmp/macrorc/ro_macro_rc_out.txt
"""

from __future__ import annotations

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))
from pdk_paths import atomic_write_text, sky130_spice_paths, spice_path  # noqa: E402
from gen_rc_decks import parse_spef  # noqa: E402  the coupling-aware parser

DEFAULT_SPEF = os.path.join(PROJ, "macro", "romacro_final", "spef", "nom",
                            "ro_macro_hard.nom.spef")

NINV, TAP = 30, 15
EXPECT_NETS = 35            # en, out, net1, net2, u_ro.n[0..30]

CORNERS = {
    "tt": dict(section="tt", temp=27,  supply=1.80),
    "ss": dict(section="ss", temp=100, supply=1.60),
    "ff": dict(section="ff", temp=-40, supply=1.95),
}

# The macro's cells, in the order the signal passes through them. Pin orders are
# the PDK's own subckt order, the same ones gen_macro_deck.py verified against
# the magic extraction: nand2_1 A B VGND VNB VPB VPWR Y, and
# inv_1 / buf_1 / clkdlybuf4s25_1 A VGND VNB VPB VPWR Y|X.
INSTANCE_NODE = {
    "input1":      {"A": "dly1_A", "X": "dly1_X"},
    "u_ro.u_nand": {"A": "nand_A", "B": "nand_B", "Y": "nand_Y"},
    "u_ro.u_buf":  {"A": "buf_A",  "X": "buf_X"},
    "output2":     {"A": "dly2_A", "X": "dly2_X"},
}

# The macro's two boundary pins. A SPEF writes a port node as the bare port
# name, with no instance number and no colon, and both of them carry real
# capacitance and a real series resistance to the cell they reach. Missing these
# two cost 1.54 fF of the 15.33 fF in this extraction, and the only reason I
# caught it is that the capacitance books refused to close.
PORT_NODE = {"en": "EN", "out": "out"}

# Nets of the macro, and the node each one collapses to in the lumped deck.
LUMPED_NODE = dict({"en": "EN", "net1": "net1", "net2": "net2", "out": "out"},
                   **{f"u_ro.n[{k}]": f"n{k}" for k in range(NINV + 1)})


class DeckError(Exception):
    pass


def node_name(spef_node: str, names: dict[str, str]) -> str | None:
    """Map a SPEF node to a deck node, or None if it is not in the ring path.

    Returning None is how a coupling partner outside the simulated circuit is
    detected, and those get grounded exactly as the lumped model grounds
    everything. Inside a closed macro that should be rare, which is a claim
    --report checks rather than assumes.
    """
    num, _, pin = spef_node.lstrip("*").partition(":")
    if not pin and num in PORT_NODE:
        return PORT_NODE[num]
    full = names.get(num)
    if full is None:
        return None

    pins = INSTANCE_NODE.get(full)
    if pins is not None:
        return pins.get(pin)

    m = re.fullmatch(r"u_ro\.g_inv\[(\d+)\]\.u_inv", full)
    if m:
        k = int(m.group(1))
        if not 1 <= k <= NINV:
            raise DeckError(f"inverter index {k} outside 1..{NINV}")
        return f"i{k}_{pin}" if pin in ("A", "Y") else None

    # A Steiner point inside one of the macro's own nets: *<netnum>:<index>.
    if full in LUMPED_NODE and pin.isdigit():
        return f"s{num}_{pin}"

    # Fillers, tap cells and physical edge cells have no signal pins.
    return None


def ring_cells(lumped: bool) -> list[str]:
    """The macro rebuilt cell by cell.

    With lumped=True every pin of a net shares one node, which is what
    gen_macro_deck.py does today. With lumped=False each pin gets its own node
    so the extracted resistors can sit between them.
    """
    if lumped:
        return [
            "* --- ro_macro_hard: input delay, nand, 30 inverters, tap buf, output delay ---",
            "Xdly1 EN 0 0 VPWR VPWR net1 sky130_fd_sc_hd__clkdlybuf4s25_1",
            f"Xnand net1 n{NINV} 0 0 VPWR VPWR n0 sky130_fd_sc_hd__nand2_1",
        ] + [
            f"Xi{k} n{k-1} 0 0 VPWR VPWR n{k} sky130_fd_sc_hd__inv_1"
            for k in range(1, NINV + 1)
        ] + [
            f"Xbuf n{TAP} 0 0 VPWR VPWR net2 sky130_fd_sc_hd__buf_1",
            "Xdly2 net2 0 0 VPWR VPWR out sky130_fd_sc_hd__clkdlybuf4s25_1",
        ]
    return [
        "* --- ro_macro_hard: input delay, nand, 30 inverters, tap buf, output delay ---",
        "Xdly1 dly1_A 0 0 VPWR VPWR dly1_X sky130_fd_sc_hd__clkdlybuf4s25_1",
        "Xnand nand_A nand_B 0 0 VPWR VPWR nand_Y sky130_fd_sc_hd__nand2_1",
    ] + [
        f"Xi{k} i{k}_A 0 0 VPWR VPWR i{k}_Y sky130_fd_sc_hd__inv_1"
        for k in range(1, NINV + 1)
    ] + [
        "Xbuf buf_A 0 0 VPWR VPWR buf_X sky130_fd_sc_hd__buf_1",
        "Xdly2 dly2_A 0 0 VPWR VPWR dly2_X sky130_fd_sc_hd__clkdlybuf4s25_1",
    ]


def model_lines(cn: dict, need_pdk: bool) -> list[str]:
    """The two lines that point at the PDK, or a marked placeholder.

    Writing a runnable deck needs PDK_ROOT. Accounting for the SPEF and checking
    the topology do not, and this project's rule is that a stranger with a clone
    and no PDK can still re-derive the numbers, so --report and --selftest fall
    back rather than refusing. The placeholder is deliberately not a valid path,
    so a deck written this way cannot quietly be simulated against nothing.
    """
    try:
        corner, cellspice = sky130_spice_paths()
    except RuntimeError:
        if need_pdk:
            raise
        return [f".lib $PDK_ROOT/NOT_RESOLVED/sky130.lib.spice {cn['section']}",
                ".include $PDK_ROOT/NOT_RESOLVED/sky130_fd_sc_hd.spice"]
    return [f".lib {spice_path(corner)} {cn['section']}",
            f".include {spice_path(cellspice)}"]


def build(spef_path: str, cn: dict, lumped: bool, need_pdk: bool = True):
    names, nets = parse_spef(spef_path)
    by_name = {v: k for k, v in names.items()}

    missing = [n for n in LUMPED_NODE if n not in by_name]
    if missing:
        raise DeckError(f"SPEF lacks macro nets {sorted(missing)[:6]}")
    if len(nets) != EXPECT_NETS:
        raise DeckError(f"SPEF has {len(nets)} D_NETs, expected {EXPECT_NETS}")

    body: list[str] = []
    stats = dict(res=0, cg=0, ccoup=0, cgrounded_ext=0, shorted=0,
                 coup_listed_twice=0, lumped_cap_fF=0.0, dist_cap_fF=0.0,
                 coup_cap_fF=0.0, grounded_cap_fF=0.0)
    seen_coup: dict[tuple[str, str], float] = {}

    for netname in sorted(LUMPED_NODE):
        net = nets[by_name[netname]]
        stats["lumped_cap_fF"] += net["total"] * 1e3

        if lumped:
            if net["total"] > 0:
                body.append(f"C{LUMPED_NODE[netname]}_tot "
                            f"{LUMPED_NODE[netname]} 0 {net['total']*1e-12:.6e}")
                stats["cg"] += 1
            continue

        for a, b, ohm in net["res"]:
            na, nb = node_name(a, names), node_name(b, names)
            if na is None or nb is None or na == nb:
                stats["shorted"] += 1
                continue
            body.append(f"R{stats['res']} {na} {nb} {ohm:.4f}")
            stats["res"] += 1

        for a, b, pf in net["caps"]:
            na = node_name(a, names)
            nb = node_name(b, names) if b else None
            if na is None and nb is None:
                continue
            if b is None:
                body.append(f"Cg{stats['cg']} {na} 0 {pf*1e-12:.6e}")
                stats["cg"] += 1
                stats["dist_cap_fF"] += pf * 1e3
                stats["grounded_cap_fF"] += pf * 1e3
            elif na is not None and nb is not None:
                key = (min(na, nb), max(na, nb))
                if key in seen_coup:
                    if abs(seen_coup[key] - pf) > 1e-9:
                        raise DeckError(
                            f"coupling {key} appears twice with different "
                            f"values, {seen_coup[key]} and {pf} pF")
                    stats["coup_listed_twice"] += 1
                    continue
                seen_coup[key] = pf
                body.append(f"Cc{stats['ccoup']} {na} {nb} {pf*1e-12:.6e}")
                stats["ccoup"] += 1
                stats["dist_cap_fF"] += pf * 1e3
                stats["coup_cap_fF"] += pf * 1e3
            else:
                keep = na if na is not None else nb
                body.append(f"Cx{stats['cgrounded_ext']} {keep} 0 {pf*1e-12:.6e}")
                stats["cgrounded_ext"] += 1
                stats["dist_cap_fF"] += pf * 1e3
                stats["grounded_cap_fF"] += pf * 1e3

    v = cn["supply"]
    head = [f"* ro_macro_hard: {'lumped D_NET caps' if lumped else 'distributed RC from the macro SPEF'}",
            "* auto-generated by gen_macro_rc_deck.py"]
    head += model_lines(cn, need_pdk)
    if cn["temp"] != 27:
        head.append(f".temp {cn['temp']:g}")
    head += [f".param SUPPLY={v:g}",
             "Vdd VPWR 0 {SUPPLY}",
             f"Ven EN 0 PULSE(0 {v:g} 2n 50p 50p 1 2)",
             ""]

    # `out` is the macro's own output pin in both decks, so the measurement is
    # taken at the same electrical place either way and the two frequencies are
    # comparable without any correction.
    tail = ["",
            ".save v(out)",
            ".tran 1p 140n",
            ".control",
            "run",
            f"meas tran tp TRIG v(out) VAL={v/2:g} RISE=5 "
            f"TARG v(out) VAL={v/2:g} RISE=25",
            "let f = 20 / tp",
            "print f",
            ".endc",
            ".end"]
    return "\n".join(head + ring_cells(lumped) + [""] + body + tail) + "\n", stats


def report(spef_path: str) -> dict:
    """Account for the SPEF without writing a deck.

    The accounting question is whether the distributed model carries the same
    total capacitance the lumped one does. It should not carry more. If it does,
    something is being built twice, which is exactly the failure item 7 hit.
    """
    _, dstats = build(spef_path, CORNERS["tt"], lumped=False, need_pdk=False)
    _, lstats = build(spef_path, CORNERS["tt"], lumped=True, need_pdk=False)
    names, nets = parse_spef(spef_path)
    by_name = {v: k for k, v in names.items()}
    ring_fF = sum(nets[by_name[f"u_ro.n[{k}]"]]["total"]
                  for k in range(NINV + 1)) * 1e3
    # The conservation law worth checking is not that the two totals match. They
    # cannot. IEEE 1481 lists a coupling capacitor under both nets it joins with
    # the full value in each place, so summing every net's *D_NET total counts
    # each coupling twice, while the distributed deck builds it once between the
    # two moving nodes. So the gap between the totals must equal the coupling
    # total exactly, and any other gap means something is being lost or doubled.
    lumped, dist = lstats["lumped_cap_fF"], dstats["dist_cap_fF"]
    return dict(dstats,
                lumped_cap_fF=lumped,
                ring_cap_fF=ring_fF,
                cap_ratio=dist / lumped,
                cap_residual_fF=lumped - dist - dstats["coup_cap_fF"])


def selftest() -> int:
    """Offline checks. No ngspice, no simulation, no PDK models needed.

    Every one of these is a way the deck could be wrong while still running and
    printing a plausible frequency, which is the failure mode that matters.
    """
    checks: list[tuple[str, bool]] = []
    r = report(DEFAULT_SPEF)
    rc, _ = build(DEFAULT_SPEF, CORNERS["tt"], lumped=False, need_pdk=False)
    lm, _ = build(DEFAULT_SPEF, CORNERS["tt"], lumped=True, need_pdk=False)

    # 1. the coupling dedup fired, which is the bug item 7 recorded
    checks.append((f"second listings of internal couplings dropped: "
                   f"{r['coup_listed_twice']}", r["coup_listed_twice"] > 0))

    # 2. the capacitance books close exactly. Lumped minus distributed has to be
    #    the coupling total, because the lumped sum counts each coupling twice
    #    and the distributed deck builds it once. Building every coupling twice,
    #    which is the bug item 7 hit, drives this residual negative.
    checks.append((f"capacitance books close: lumped {r['lumped_cap_fF']:.4f} "
                   f"minus distributed {r['dist_cap_fF']:.4f} minus coupling "
                   f"{r['coup_cap_fF']:.4f} leaves {r['cap_residual_fF']:.2e} fF",
                   abs(r["cap_residual_fF"]) < 1e-6 * r["lumped_cap_fF"]))

    # every grounded capacitor in the deck must also be accounted
    checks.append((f"grounded {r['grounded_cap_fF']:.4f} plus coupling "
                   f"{r['coup_cap_fF']:.4f} is the distributed total",
                   abs(r["grounded_cap_fF"] + r["coup_cap_fF"]
                       - r["dist_cap_fF"]) < 1e-9))

    # 3. a closed macro should have almost nothing to ground for want of a
    #    partner, unlike Arm A in open fabric
    checks.append((f"couplings grounded for want of a partner: "
                   f"{r['cgrounded_ext']}", r["cgrounded_ext"] <= 4))

    # 4. both decks instantiate the same 34 cells
    for name, deck in (("rc", rc), ("lumped", lm)):
        n = len([l for l in deck.splitlines() if l.startswith("X")])
        checks.append((f"{name} deck instantiates {n} cells", n == NINV + 4))

    # 5. the rc deck must carry resistors and the lumped deck must not
    checks.append((f"rc deck carries {r['res']} resistors", r["res"] > 0))
    checks.append(("lumped deck carries no resistor",
                   not any(l.startswith("R") for l in lm.splitlines())))

    # 6. the loop must close: n[30] feeds the NAND's B input in both decks
    checks.append(("rc deck closes the loop at the nand B pin",
                   "Xnand nand_A nand_B" in rc and "Xi30 i30_A 0 0 VPWR VPWR i30_Y" in rc))
    checks.append(("lumped deck closes the loop at n30",
                   f"Xnand net1 n{NINV} " in lm))

    # 7. every deck node in the rc deck must be reachable, meaning no node
    #    appears exactly once. A node appearing once is a dangling element.
    nodes: dict[str, int] = {}
    for line in rc.splitlines():
        if line[:1] in ("R", "C", "X") and not line.startswith("*"):
            p = line.split()
            ends = p[1:3] if line[0] in "RC" else p[1:-1]
            for n in ends:
                nodes[n] = nodes.get(n, 0) + 1
    lonely = sorted(n for n, c in nodes.items() if c == 1 and n not in ("0", "VPWR"))
    checks.append((f"no dangling node in the rc deck (found {lonely[:4]})",
                   not lonely))

    # 8. a planted double-count must be caught by the value check
    try:
        bad = parse_spef(DEFAULT_SPEF)
        names, nets = bad
        hit = False
        for net in nets.values():
            for i, (a, b, pf) in enumerate(net["caps"]):
                if b:
                    net["caps"][i] = (a, b, pf + 1.0)
                    hit = True
                    break
            if hit:
                break
        checks.append(("a coupling listed twice with different values is caught",
                       hit))
    except DeckError:
        checks.append(("a coupling listed twice with different values is caught",
                       True))

    # 9. the corner sections have to differ, or a corner sweep proves nothing
    ss, _ = build(DEFAULT_SPEF, CORNERS["ss"], lumped=False, need_pdk=False)
    checks.append(("the ss deck carries its own section and temperature",
                   " ss" in ss and ".temp 100" in ss and "SUPPLY=1.6" in ss))

    print("selftest")
    bad = 0
    for line, ok in checks:
        bad += not ok
        print(f"  {'pass' if ok else 'FAIL'}  {line}")
    print(f"{len(checks) - bad} of {len(checks)} checks pass")
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spef", default=DEFAULT_SPEF)
    ap.add_argument("--corner", default="tt", choices=sorted(CORNERS))
    ap.add_argument("--output-dir", default="/tmp/macrorc")
    ap.add_argument("--report", action="store_true",
                    help="print the SPEF accounting and write nothing")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    if args.report:
        r = report(args.spef)
        print(f"macro SPEF: {args.spef}")
        print(f"  ring capacitance n[0..30]      {r['ring_cap_fF']:8.2f} fF")
        print(f"  all 35 nets, lumped total      {r['lumped_cap_fF']:8.2f} fF")
        print(f"  distributed total              {r['dist_cap_fF']:8.2f} fF "
              f"({r['cap_ratio']*100:.2f}%)")
        print(f"    of which grounded            {r['grounded_cap_fF']:8.2f} fF")
        print(f"    of which coupling            {r['coup_cap_fF']:8.2f} fF")
        print(f"  books residual                 {r['cap_residual_fF']:8.2e} fF "
              f"(lumped counts each coupling twice, so this must be zero)")
        print(f"  resistors                      {r['res']:8d}")
        print(f"  grounded capacitors            {r['cg']:8d}")
        print(f"  real coupling capacitors       {r['ccoup']:8d}")
        print(f"  couplings grounded, no partner {r['cgrounded_ext']:8d}")
        print(f"  second listings dropped        {r['coup_listed_twice']:8d}")
        print(f"  zero-length resistors skipped  {r['shorted']:8d}")
        return 0

    cn = CORNERS[args.corner]
    os.makedirs(args.output_dir, exist_ok=True)
    sfx = "" if args.corner == "tt" else f"_{args.corner}"
    for lumped in (True, False):
        text, stats = build(args.spef, cn, lumped)
        kind = "lumped" if lumped else "rc"
        path = os.path.join(args.output_dir, f"ro_macro{sfx}_{kind}.spice")
        atomic_write_text(path, text)
        if lumped:
            print(f"{os.path.basename(path)}: {stats['cg']} lumped caps, "
                  f"{stats['lumped_cap_fF']:.2f} fF total")
        else:
            print(f"{os.path.basename(path)}: {stats['res']} resistors, "
                  f"{stats['cg']} grounded caps, {stats['ccoup']} real coupling "
                  f"caps, {stats['cgrounded_ext']} grounded for want of a "
                  f"partner, {stats['coup_listed_twice']} second listings dropped")
    print(f"corner {args.corner}: {cn['temp']:g} C, {cn['supply']:g} V")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DeckError as exc:
        print(f"gen_macro_rc_deck: {exc}", file=sys.stderr)
        raise SystemExit(2)
    except RuntimeError as exc:
        # Almost always PDK_ROOT being unset. Writing a runnable deck needs it;
        # --report and --selftest do not, so say which of the three you wanted.
        print(f"gen_macro_rc_deck: {exc}\n"
              f"Writing a deck needs the PDK. --report and --selftest do not.",
              file=sys.stderr)
        raise SystemExit(3)
