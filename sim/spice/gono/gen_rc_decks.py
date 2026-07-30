#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Rebuild one Arm A oscillator with the SPEF's actual RC network, not a lumped cap.

The go/no-go deck takes each ring net's total `*D_NET` capacitance and hangs it on
one node. That is a deliberate simplification and it throws away three things the
extraction actually recorded:

  the series resistance between driver and receiver, dropped entirely;
  the split of capacitance between the two ends of a net, collapsed to one point;
  the coupling capacitance, which gets grounded as if the neighbour were quiet.

The third one is the interesting one. A ring here carries 23 to 39 coupling
capacitors whose far end is another node of the same ring, mostly the immediately
neighbouring inverter, and 4 to 72 more whose far end belongs to something else.
Neighbouring inverters swing in antiphase, so grounding the coupling understates
the load it presents, while a real coupling capacitor between the two moving nodes
reproduces it.

Counting those internal ones takes care. The SPEF records each of them under both
of the nets it joins, with the same value in each place, so a pass over all 31
ring nets meets every internal coupling twice. The second sighting is dropped
here. An earlier version of this script did not drop it and built each of those
capacitors twice.

This script emits, for one oscillator index, two decks that differ only in the
parasitic model:

  <tag>_lumped.spice        total D_NET capacitance per net, grounded, one node
  <tag>_rc.spice            per-node grounded caps, series resistors, and real
                            coupling caps wherever both endpoints are inside the
                            simulated ring

Running both and comparing the frequency isolates the model change from every
other difference, because the cells, the corner and the startup are identical. If
the two agree closely, the lumped result the paper leans on earns real credibility.
If they do not, the gap is the size of the error the simplification introduced.

Nodes are named after the SPEF's own pins, so no topology has to be guessed: the
ring is instantiated with each cell pin wired to its own pin node, and the SPEF's
resistors then join those nodes exactly as extracted.

Usage:
    python3 gen_rc_decks.py --ro 7 --output-dir /tmp/rc
    python3 ../run_ngspice.py /tmp/rc/ro07_rc.spice --log /tmp/rc/ro07_rc_out.txt
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
DEFAULT_SPEF = os.path.join(
    PROJ, "dualarm", "build_current", "tt_um_nikodemetrashvili20_ro_puf.nom.spef")
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))
from pdk_paths import atomic_write_text, sky130_spice_paths, spice_path

NINV, TAP = 30, 15
CORNERS = {
    "tt": dict(section="tt", temp=27,  supply=1.80),
    "ss": dict(section="ss", temp=100, supply=1.60),
    "ff": dict(section="ff", temp=-40, supply=1.95),
}


def parse_spef(path):
    """Return (name_map, {netnum: {'total':pf, 'conn':[(inst,pin,dir)],
    'caps':[(a,b,pf)] with b None for grounded, 'res':[(a,b,ohm)]})."""
    txt = open(path).read()
    names = {k: v.replace("\\", "")
             for k, v in re.findall(r'^\*(\d+)\s+(\S+)\s*$', txt, re.M)}
    nets = {}
    for m in re.finditer(r'^\*D_NET \*(\d+)\s+([0-9.eE+-]+)\s*\n(.*?)^\*END',
                         txt, re.S | re.M):
        num, total, body = m.group(1), float(m.group(2)), m.group(3)
        conn = re.findall(r'^\*I \*(\d+):(\S+)\s+([IO])\s', body, re.M)
        caps, res = [], []
        cs = re.search(r'^\*CAP\n(.*?)(?=^\*RES|\Z)', body, re.S | re.M)
        rs = re.search(r'^\*RES\n(.*?)\Z', body, re.S | re.M)
        for line in (cs.group(1).splitlines() if cs else []):
            p = line.split()
            if len(p) == 3:
                caps.append((p[1], None, float(p[2])))
            elif len(p) == 4:
                caps.append((p[1], p[2], float(p[3])))
        for line in (rs.group(1).splitlines() if rs else []):
            p = line.split()
            if len(p) == 4:
                res.append((p[1], p[2], float(p[3])))
        nets[num] = dict(total=total, conn=conn, caps=caps, res=res)
    return names, nets


def node_name(spef_node, names, ro):
    """Turn a SPEF node like *7501:A into a short deck node name.

    Instance pins become <cellshort>_<pin>; a SPEF-internal Steiner point
    (*netnum:index) becomes s<netnum>_<index>. Returns None when the node belongs
    to an instance outside this oscillator, which is how external coupling is
    detected.
    """
    num, _, pin = spef_node.lstrip("*").partition(":")
    full = names.get(num)
    if full is None:
        return None
    prefix = f"u_puf.u_core.g_ro_bank[{ro}].u_ro."
    if full.startswith(prefix):
        leaf = full[len(prefix):]
        m = re.fullmatch(r'g_inv\[(\d+)\]\.u_inv', leaf)
        if m:
            return f"i{m.group(1)}_{pin}"
        if leaf == "u_nand":
            # The NAND's A pin is the enable, driven by the source in this deck, so
            # anything the extraction couples into it lands on EN. That is the
            # physical situation during a measurement: the enable is held high by a
            # stiff driver, so the coupling behaves as grounded.
            return "EN" if pin == "A" else f"nand_{pin}"
        if leaf == "u_buf":
            return f"buf_{pin}"
        # a ring net of this oscillator: an internal Steiner point on it
        if re.fullmatch(r'n\[\d+\]|out', leaf) and pin.isdigit():
            return f"s{num}_{pin}"
        return None
    return None


def ring_nets(names, ro):
    """netnum for each of n[0..30] plus out, for one oscillator."""
    want = {f"u_puf.u_core.g_ro_bank[{ro}].u_ro.n[{k}]": f"n{k}" for k in range(NINV + 1)}
    want[f"u_puf.u_core.g_ro_bank[{ro}].u_ro.out"] = "out"
    inv = {v: k for k, v in names.items()}
    return {lbl: inv[nm] for nm, lbl in want.items() if nm in inv}


def cells(ro, lumped):
    """The reconstructed ring.

    With lumped=True every pin of a net shares one node, which is what the
    existing go/no-go deck does. With lumped=False each pin gets its own node so
    the SPEF's resistors can sit between them.

    nand2_1 pins A B VGND VNB VPB VPWR Y; inv_1 A VGND VNB VPB VPWR Y;
    buf_1 A VGND VNB VPB VPWR X. Verified against the PDK cell SPICE and against
    the pin names the SPEF itself reports.
    """
    out = [f"* --- Arm A oscillator {ro}: nand + {NINV} inverters + tap buffer ---"]
    if lumped:
        out.append(f"Xnand EN n{NINV} 0 0 VPWR VPWR n0 sky130_fd_sc_hd__nand2_1")
        for k in range(1, NINV + 1):
            out.append(f"Xi{k} n{k-1} 0 0 VPWR VPWR n{k} sky130_fd_sc_hd__inv_1")
        out.append(f"Xbuf n{TAP} 0 0 VPWR VPWR out sky130_fd_sc_hd__buf_1")
    else:
        out.append("Xnand EN nand_B 0 0 VPWR VPWR nand_Y sky130_fd_sc_hd__nand2_1")
        for k in range(1, NINV + 1):
            out.append(f"Xi{k} i{k}_A 0 0 VPWR VPWR i{k}_Y sky130_fd_sc_hd__inv_1")
        out.append("Xbuf buf_A 0 0 VPWR VPWR buf_X sky130_fd_sc_hd__buf_1")
    return out


def shared_node(lbl):
    """The single node a net collapses to in the lumped model."""
    return "out" if lbl == "out" else lbl


def build(ro, spef_path, cn, lumped):
    names, nets = parse_spef(spef_path)
    labels = ring_nets(names, ro)
    missing = [l for l in [f"n{k}" for k in range(NINV + 1)] if l not in labels]
    if missing:
        raise SystemExit(f"oscillator {ro}: SPEF lacks ring nets {missing[:5]}")

    body, stats = [], dict(res=0, cg=0, ccoup=0, cgrounded_ext=0, shorted=0,
                           coup_listed_twice=0)
    # A coupling capacitor between two nets of this ring is one component, but
    # IEEE 1481 records it in the *CAP block of both nets with the same value.
    # Walking all 31 nets therefore reaches every internal coupling twice, so the
    # second sighting has to be dropped or the capacitor is built twice over.
    seen_coup = {}

    for lbl, num in sorted(labels.items()):
        net = nets[num]
        if lumped:
            # the whole net's extracted capacitance, coupling included, grounded
            # on the one node the net collapses to
            if net["total"] > 0:
                body.append(f"C{lbl}_tot {shared_node(lbl)} 0 {net['total']*1e-12:.6e}")
                stats["cg"] += 1
            continue
        # --- distributed: resistors as extracted ---
        for a, b, ohm in net["res"]:
            na, nb = node_name(a, names, ro), node_name(b, names, ro)
            if na is None or nb is None or na == nb:
                stats["shorted"] += 1
                continue
            body.append(f"R{lbl}_{stats['res']} {na} {nb} {ohm:.4f}")
            stats["res"] += 1
        for a, b, pf in net["caps"]:
            na = node_name(a, names, ro)
            nb = node_name(b, names, ro) if b else None
            if na is None and nb is None:
                continue
            if b is None:
                body.append(f"Cg{stats['cg']} {na} 0 {pf*1e-12:.6e}")
                stats["cg"] += 1
            elif na is not None and nb is not None:
                # both ends move: model the coupling as it really is
                key = (min(na, nb), max(na, nb))
                if key in seen_coup:
                    if abs(seen_coup[key] - pf) > 1e-9:
                        raise SystemExit(
                            f"oscillator {ro}: coupling {key} appears twice with "
                            f"different values, {seen_coup[key]} and {pf} pF")
                    stats["coup_listed_twice"] += 1
                    continue
                seen_coup[key] = pf
                body.append(f"Cc{stats['ccoup']} {na} {nb} {pf*1e-12:.6e}")
                stats["ccoup"] += 1
            else:
                # partner is outside this oscillator: ground it, as the lumped
                # model does for everything
                keep = na if na is not None else nb
                body.append(f"Cx{stats['cgrounded_ext']} {keep} 0 {pf*1e-12:.6e}")
                stats["cgrounded_ext"] += 1

    corner, cellspice = sky130_spice_paths()
    v = cn["supply"]
    head = [f"* Arm A oscillator {ro}: {'lumped D_NET caps' if lumped else 'distributed RC from SPEF'}",
            "* auto-generated by gen_rc_decks.py",
            f".lib {spice_path(corner)} {cn['section']}",
            f".include {spice_path(cellspice)}"]
    if cn["temp"] != 27:
        head.append(f".temp {cn['temp']:g}")
    head += [f".param SUPPLY={v:g}",
             "Vdd VPWR 0 {SUPPLY}",
             f"Ven EN 0 PULSE(0 {v:g} 2n 50p 50p 1 2)",
             ""]
    probe = "out" if lumped else "buf_X"
    tail = ["",
            f".save v({probe})",
            ".tran 1p 140n",
            ".control",
            "run",
            f"meas tran tp TRIG v({probe}) VAL={v/2:g} RISE=5 "
            f"TARG v({probe}) VAL={v/2:g} RISE=25",
            "let f = 20 / tp",
            "print f",
            ".endc",
            ".end"]
    return "\n".join(head + cells(ro, lumped) + [""] + body + tail) + "\n", stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ro", type=int, required=True, help="Arm A oscillator index 0..15")
    ap.add_argument("--spef", default=DEFAULT_SPEF)
    ap.add_argument("--corner", default="tt", choices=sorted(CORNERS))
    ap.add_argument("--output-dir", default="/tmp/rc")
    args = ap.parse_args(argv)

    cn = CORNERS[args.corner]
    os.makedirs(args.output_dir, exist_ok=True)
    sfx = "" if args.corner == "tt" else f"_{args.corner}"
    for lumped in (True, False):
        text, stats = build(args.ro, args.spef, cn, lumped)
        kind = "lumped" if lumped else "rc"
        path = os.path.join(args.output_dir, f"ro{args.ro:02d}{sfx}_{kind}.spice")
        atomic_write_text(path, text)
        if lumped:
            print(f"{os.path.basename(path)}: {stats['cg']} lumped caps")
        else:
            print(f"{os.path.basename(path)}: {stats['res']} resistors, "
                  f"{stats['cg']} grounded caps, {stats['ccoup']} real coupling caps, "
                  f"{stats['cgrounded_ext']} external couplings grounded, "
                  f"{stats['coup_listed_twice']} second listings dropped")
    print(f"corner {args.corner}: {cn['temp']:g} C, {cn['supply']:g} V")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
