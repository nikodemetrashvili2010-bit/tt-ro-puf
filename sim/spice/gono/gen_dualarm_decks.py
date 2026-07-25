#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
Pre-silicon Stage 3: nominal lumped-C decks for dual-arm Arm A (16 ROs).
Derived mechanically from gen_decks.py (32-RO version); only NRO, the input
paths, and the output names differ. Arm B is not in these decks: its 16 copies
are one sealed macro, simulated separately in ro_macro_matched.spice.

Two combined decks, each with the archived dual-arm build's 16 Arm A logical
oscillator topologies (enable NAND -> 30 inverters -> feedback, buffer on n[15]):

  dualarm_ctrl.spice : NO parasitics.  All 16 ROs are topologically identical,
                       so they MUST read the same frequency -> control.
  dualarm_par.spice  : OpenROAD *D_NET total capacitance lumped to ground on
                       each ring node. Spread is a nominal layout prediction.

Startup: each RO uses the chip's enable topology -- the shared enable EN is
held low (ring forced to a defined rest state), then pulsed high at t=2 ns. This
injects an edge and favors the intended oscillation mode. (A naive
"tie enable high + .ic kick" start lets uneven loading excite spurious higher-
order modes that read as impossibly high frequencies, so we avoid it.)

Model: the deck instantiates all 16 reconstructed oscillators and enables
them together. They are uncoupled here (ideal shared supply, no coupling
elements carried over), so this matches the one-at-a-time hardware protocol
under this reduced model. Each SPEF *D_NET total is represented
by one capacitor to ground. Distributed resistance, explicit coupling topology,
PVT variation, mismatch, and noise are outside this experiment. This is a
pre-silicon nominal prediction, not a measurement of fabricated silicon.

Outputs (in `--output-dir`, which defaults to this script's directory):
dualarm_ctrl.spice, dualarm_par.spice, dualarm_positions.csv
"""
import argparse
import csv
import io
import os
import re
import sys

HERE  = os.path.dirname(os.path.abspath(__file__))
PROJ  = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
FINAL = os.path.join(PROJ, "dualarm", "build_current")
SPEF  = os.path.join(FINAL, "tt_um_nikodemetrashvili20_ro_puf.nom.spef")
DEFF  = os.path.join(FINAL, "tt_um_nikodemetrashvili20_ro_puf.def")
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))
from pdk_paths import atomic_write_text, sky130_spice_paths, spice_path

NRO, NINV, TAP = 16, 30, 15

# PVT corners. Device corner is the SKY130 library section; temperature and supply
# are the other two axes. The measurement threshold has to follow the supply, and
# the transient window has to be long enough for 25 rising edges at the slowest
# corner, or the meas statement silently returns nothing.
#
# These pair a device corner with nominal interconnect. Pairing ss with the max
# SPEF and ff with the min SPEF would be the fuller job; device spread dominates
# the frequency bound, so this establishes the bound and the RC pairing refines it.
CORNERS = {
    "tt": dict(section="tt", temp=27,  supply=1.80, tstop_ns=80),
    "ss": dict(section="ss", temp=100, supply=1.60, tstop_ns=300),
    "ff": dict(section="ff", temp=-40, supply=1.95, tstop_ns=80),
}

def net(i, k):  return f"u_puf.u_core.g_ro_bank[{i}].u_ro.n[{k}]"
def outnet(i):  return f"u_puf.u_core.g_ro_bank[{i}].u_ro.out"

def parse_spef(path):
    num2name, name2cap = {}, {}
    with open(path) as f:
        for line in f:
            m = re.match(r'^\*(\d+)\s+(\S+)\s*$', line)
            if m:
                num2name[m.group(1)] = m.group(2).replace("\\", "")
                continue
            if line.startswith("*D_NET"):
                p = line.split()
                nm = num2name.get(p[1].lstrip("*"))
                if nm:
                    name2cap[nm] = float(p[2])               # picofarads
    return name2cap

def parse_def(path):
    txt = open(path).read()
    um = 1000.0
    mu = re.search(r'UNITS DISTANCE MICRONS\s+(\d+)', txt)
    if mu: um = float(mu.group(1))
    block = re.search(r'^COMPONENTS.*?^END COMPONENTS', txt, re.S | re.M)
    pts = {i: [] for i in range(NRO)}
    if block:
        for chunk in block.group(0).split(";"):
            m = re.search(r'-\s+(\S+)\s+\S+.*?\(\s*(-?\d+)\s+(-?\d+)\s*\)', chunk, re.S)
            if not m:
                continue
            inst = m.group(1).replace("\\", "")
            x, y = int(m.group(2)), int(m.group(3))
            for i in range(NRO):
                if f"g_ro_bank[{i}].u_ro." in inst:
                    pts[i].append((x / um, y / um)); break
    cent = {}
    for i, lst in pts.items():
        if lst:
            cent[i] = (sum(p[0] for p in lst) / len(lst),
                       sum(p[1] for p in lst) / len(lst), len(lst))
    return cent

def cap_f(pf):
    return f"{pf*1e-12:.6e}"

def emit_ro(i, caps):
    p = f"x{i}_"
    L = [f"* --- RO {i} ---",
         # nand2_1 pin order A B VGND VNB VPB VPWR Y ; A=EN(shared), B=n30, Y=n0
         f"X{i}_nand EN {p}n30 0 0 VPWR VPWR {p}n0 sky130_fd_sc_hd__nand2_1"]
    for k in range(1, NINV + 1):
        L.append(f"X{i}_inv{k} {p}n{k-1} 0 0 VPWR VPWR {p}n{k} sky130_fd_sc_hd__inv_1")
    L.append(f"X{i}_buf {p}n{TAP} 0 0 VPWR VPWR {p}out sky130_fd_sc_hd__buf_1")
    if caps:
        for k in range(0, NINV + 1):
            c = caps.get(net(i, k), 0.0)
            if c > 0:
                L.append(f"C{i}_n{k} {p}n{k} 0 {cap_f(c)}")
        co = caps.get(outnet(i), 0.0)
        if co > 0:
            L.append(f"C{i}_out {p}out 0 {cap_f(co)}")
    return L

def header(title, cn):
    corner, cells = sky130_spice_paths()
    v = cn["supply"]
    lines = [
        f"* Pre-silicon lumped-C go/no-go: {title}",
        "* auto-generated by gen_dualarm_decks.py -- 16 Arm A ROs, enable-started",
        f".lib {spice_path(corner)} {cn['section']}",
        f".include {spice_path(cells)}",
    ]
    if cn["temp"] != 27:
        lines.append(f".temp {cn['temp']}")
    lines += [
        f".param SUPPLY={v:g}",
        "Vdd VPWR 0 {SUPPLY}",
        f"Ven EN 0 PULSE(0 {v:g} 2n 50p 50p 1 2)",
        "",
    ]
    return "\n".join(lines)

def build_deck(title, caps, cn):
    out = [header(title, cn)]
    for i in range(NRO):
        out += emit_ro(i, caps)
    out.append("")
    out.append(".save " + " ".join(f"v(x{i}_out)" for i in range(NRO)))
    out.append(f".tran 5p {cn['tstop_ns']:g}n")
    out.append(".control")
    out.append("run")
    for i in range(NRO):
        th = cn["supply"] / 2.0
        out.append(f"meas tran tp{i} TRIG v(x{i}_out) VAL={th:g} RISE=5 "
                   f"TARG v(x{i}_out) VAL={th:g} RISE=25")
    for i in range(NRO):
        out.append(f"let f{i} = 20 / tp{i}")
    for i in range(NRO):
        out.append(f"print f{i}")
    out.append(".endc")
    out.append(".end")
    return "\n".join(out) + "\n"

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Generate dual-arm Arm A control/parasitic decks from one coherent "
            "final SPEF and DEF export."
        )
    )
    parser.add_argument(
        "--spef",
        default=SPEF,
        help="final nominal SPEF (default: archived dual-arm snapshot)",
    )
    parser.add_argument(
        "--def",
        dest="def_file",
        default=DEFF,
        help="matching final DEF (default: archived dual-arm snapshot)",
    )
    parser.add_argument(
        "--corner",
        default="tt",
        choices=sorted(CORNERS),
        help="PVT corner: tt (27C/1.8V), ss (100C/1.6V), ff (-40C/1.95V)",
    )
    parser.add_argument(
        "--suffix",
        default=None,
        help="filename suffix (default: none for tt, _<corner> otherwise)",
    )
    parser.add_argument(
        "--output-dir",
        default=HERE,
        help="directory for the two decks and positions CSV (default: script directory)",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    spef_path = os.path.abspath(os.path.expanduser(args.spef))
    def_path = os.path.abspath(os.path.expanduser(args.def_file))
    output_dir = os.path.abspath(os.path.expanduser(args.output_dir))

    caps = parse_spef(spef_path)
    cent = parse_def(def_path)
    missing_ring_nets = [
        net(i, k)
        for i in range(NRO)
        for k in range(NINV + 1)
        if net(i, k) not in caps
    ]
    if missing_ring_nets:
        raise RuntimeError(
            "the SPEF is not a complete final Arm A extraction; refusing to "
            "write decks with missing ring loads: "
            + ", ".join(missing_ring_nets[:8])
            + (" ..." if len(missing_ring_nets) > 8 else "")
        )
    missing_centroids = [i for i in range(NRO) if i not in cent]
    if missing_centroids:
        raise RuntimeError(
            "the DEF is an incompatible checkpoint, not a complete final "
            "placement export; refusing to write nan coordinates for ROs: "
            + ", ".join(map(str, missing_centroids))
        )

    cn = CORNERS[args.corner]
    sfx = args.suffix if args.suffix is not None else ("" if args.corner == "tt" else f"_{args.corner}")
    tag = f"{args.corner} {cn['temp']}C {cn['supply']:g}V"
    ctrl_text = build_deck(f"CONTROL (no parasitics), {tag}", None, cn)
    par_text = build_deck(f"PARASITIC (nom SPEF), {tag}", caps, cn)
    positions = io.StringIO(newline="")
    w = csv.writer(positions, lineterminator="\n")
    w.writerow(["ro", "x_um", "y_um", "ncells", "ring_cap_fF"])
    for i in range(NRO):
        ring = sum(caps.get(net(i, k), 0.0) for k in range(NINV + 1)) * 1000.0
        x, y, n = cent[i]
        w.writerow([i, f"{x:.3f}", f"{y:.3f}", n, f"{ring:.2f}"])

    os.makedirs(output_dir, exist_ok=True)
    atomic_write_text(os.path.join(output_dir, f"dualarm_ctrl{sfx}.spice"), ctrl_text)
    atomic_write_text(os.path.join(output_dir, f"dualarm_par{sfx}.spice"), par_text)
    if not sfx:
        atomic_write_text(os.path.join(output_dir, "dualarm_positions.csv"), positions.getvalue())

    rings = [sum(caps.get(net(i, k), 0.0) for k in range(NINV + 1)) * 1000.0 for i in range(NRO)]
    mn, mx, av = min(rings), max(rings), sum(rings) / len(rings)
    print(f"SPEF nets parsed: {len(caps)}")
    print(f"SPEF: {spef_path}")
    print(f"DEF: {def_path}")
    print(f"Output directory: {output_dir}")
    print("per-RO total RING capacitance (n0..n30), fF: "
          f"min={mn:.1f} max={mx:.1f} mean={av:.1f} spread={mx-mn:.1f} ({100*(mx-mn)/av:.0f}%)")
    print(f"RO placement centroids parsed from DEF: {sum(1 for i in range(NRO) if i in cent)}/{NRO}")
    print(f"corner: {tag}  (transient {cn['tstop_ns']:g} ns, meas threshold {cn['supply']/2:g} V)")
    print(f"decks: dualarm_ctrl{sfx}.spice, dualarm_par{sfx}.spice")

if __name__ == "__main__":
    main()
