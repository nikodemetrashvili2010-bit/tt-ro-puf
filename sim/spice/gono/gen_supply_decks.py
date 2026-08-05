#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""
Hardware item 5: what a resistive supply does to a ring, in both arms.

Item 5 is the one confound I had only argued about. Arm B carries its own decap,
filler and met4 power straps, while Arm A sits in the ordinary cell fabric on
met1 rails, so the two arms do not see the same supply impedance. The supply
pushing figure is 105.9 percent per volt, measured on 2026-07-29, so ten
millivolts of difference between the arms is a whole percent of frequency. That
is large next to Arm A's 5.84 percent dispersion, and it is why an argument was
never going to be enough.

The honest way to answer it is not to guess one resistance. I do not know the
real PDN path resistance to better than a factor of a few, and if the whole
result rested on my estimate then the result would only be as good as the
estimate. So this sweeps the series resistance across four decades, from
essentially ideal to a kilohm, and measures three things at each point: the
average current the ring draws, the average supply that actually arrives at the
cells, and the frequency. The conclusion then survives my geometry being wrong
by a factor of ten in either direction, which it might be.

Both arms are built by the generators that already produce the results this
project quotes, so the rings here are not new models. Arm A comes from
gen_rc_decks with its distributed SPEF network, which is item 7's treatment. Arm
B comes from gen_instance_decks' own macro builder, which is item 8's reference
ring. The only thing this file adds is the resistor, the two extra measurements
and, for Arm A, a textual patch of exactly three lines that refuses to write
anything if any one of them is not found exactly once. A deck that quietly kept
an ideal supply would report a flat sweep and look like a pass.

One caveat kept in the open. The current is averaged over a hundred nanoseconds,
which is about 55 ring periods, so the window is not a whole number of periods
and the average carries roughly two percent of the ripple. That is far finer than
the factor of ten this is trying to bracket.

Run (WSL, PDK_ROOT and PDK set):
    python3 gen_supply_decks.py --output-dir /tmp/supply
    cd /tmp/supply
    for f in supply_*.spice; do python3 ../../run_ngspice.py $f --log ${f%.spice}_out.txt; done
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))
sys.path.insert(0, HERE)

from pdk_paths import atomic_write_text, sky130_spice_paths, spice_path  # noqa: E402
import gen_rc_decks as rc      # noqa: E402  Arm A, distributed RC, item 7
import gen_instance_decks as gi  # noqa: E402  Arm B macro ring, item 8

# four decades, so the answer does not depend on my PDN arithmetic being right
OHMS = (0.000001, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0, 1000.0)
TSTOP_NS = 140
AVG_FROM_NS, AVG_TO_NS = 40, 140


def probe_lines(v, probe):
    """The two measurements this file exists to add, plus the frequency."""
    return ["meas tran tp TRIG v(%s) VAL=%g RISE=5 TARG v(%s) VAL=%g RISE=25"
            % (probe, v / 2.0, probe, v / 2.0),
            # Two versions of this file failed to measure the current and I
            # blamed the spelling both times. The spelling was not the problem.
            # A deck carrying a .save line keeps only the vectors that line
            # names, and neither save line named a current, so vdd#branch was
            # never in the plot for any spelling to find. i(Vdd) is on both save
            # lines below now, which is what creates vdd#branch, and one
            # spelling is enough once the vector exists.
            "meas tran idd AVG vdd#branch FROM=%dn TO=%dn" % (AVG_FROM_NS, AVG_TO_NS),
            "meas tran vlocal AVG v(VPWR) FROM=%dn TO=%dn" % (AVG_FROM_NS, AVG_TO_NS),
            "let f = 20 / tp",
            "print f"]


def replace_once(text, old, new, what):
    """Substitute, and refuse if the target is not there exactly once."""
    n = text.count(old)
    if n != 1:
        raise SystemExit("expected %s exactly once in the deck, found %d: %r"
                         % (what, n, old))
    return text.replace(old, new)


def arm_a(ro, corner_name, ohms):
    """Take gen_rc_decks' validated Arm A deck and put a resistor in its supply."""
    cn = rc.CORNERS[corner_name]
    text, stats = rc.build(ro, rc.DEFAULT_SPEF, cn, lumped=False)
    v = cn["supply"]

    text = replace_once(text, "Vdd VPWR 0 {SUPPLY}",
                        "Vdd VSRC 0 {SUPPLY}\nRpdn VSRC VPWR %.6g" % ohms,
                        "the ideal supply source")
    text = replace_once(text, ".save v(buf_X)",
                        ".save v(buf_X) v(VPWR) i(Vdd)", "the save line")
    old_meas = ("meas tran tp TRIG v(buf_X) VAL=%g RISE=5 "
                "TARG v(buf_X) VAL=%g RISE=25" % (v / 2.0, v / 2.0))
    text = replace_once(text, old_meas, "\n".join(probe_lines(v, "buf_X")[:-2]),
                        "the period measurement")
    text = replace_once(text, "* Arm A oscillator %d:" % ro,
                        "* Arm A oscillator %d on a %.6g ohm supply, item 5;" % (ro, ohms),
                        "the title line")
    return text, stats


_MACRO_CACHE = {}


def macro_inputs():
    """Pin order and macro capacitances, read once. The cell SPICE is large."""
    if not _MACRO_CACHE:
        lib, cells = sky130_spice_paths()
        _MACRO_CACHE["lib"] = lib
        _MACRO_CACHE["cells"] = cells
        _MACRO_CACHE["order"] = gi.read_pin_order(str(cells), set(gi.MACRO_CELLS))
        mcaps = gi.parse_spef_total(gi.MACRO_SPEF)
        missing = [k for k in range(gi.NINV + 1) if "u_ro.n[%d]" % k not in mcaps]
        if missing:
            raise SystemExit("the macro SPEF is missing ring nets %s" % missing[:5])
        _MACRO_CACHE["mcaps"] = mcaps
    return _MACRO_CACHE


def arm_b(corner_name, ohms):
    """Arm B's reference macro ring, built by gen_instance_decks' own builder."""
    cn = rc.CORNERS[corner_name]
    v = cn["supply"]
    c = macro_inputs()
    lib, cells, order, mcaps = c["lib"], c["cells"], c["order"], c["mcaps"]

    head = ["* Arm B macro ring on a %.6g ohm supply, item 5" % ohms,
            "* auto-generated by gen_supply_decks.py",
            "* ring built by gen_instance_decks.emit_macro, the item 8 reference",
            ".lib %s %s" % (spice_path(lib), cn["section"])]
    head.append(".include %s" % spice_path(cells))
    if cn["temp"] != 27:
        head.append(".temp %g" % cn["temp"])
    head += [".param SUPPLY=%g" % v,
             "Vdd VSRC 0 {SUPPLY}",
             "Rpdn VSRC VPWR %.6g" % ohms,
             "Ven EN 0 PULSE(0 %g 2n 50p 50p 1 2)" % v,
             ""]
    body = gi.emit_macro("b", "EN", "b_out", mcaps, order)
    tail = ["", ".save v(b_out) v(VPWR) i(Vdd)",
            ".tran 1p %dn" % TSTOP_NS,
            ".control", "run"] + probe_lines(v, "b_out") + ["quit", ".endc", ".end"]
    return "\n".join(head + body + tail) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--output-dir", default="/tmp/supply")
    ap.add_argument("--corner", default="tt", choices=sorted(rc.CORNERS))
    ap.add_argument("--ro", type=int, default=0,
                    help="which Arm A oscillator to use (default 0)")
    args = ap.parse_args(argv)

    os.makedirs(args.output_dir, exist_ok=True)
    written = []
    for k, ohms in enumerate(OHMS):
        ta, stats = arm_a(args.ro, args.corner, ohms)
        pa = os.path.join(args.output_dir, "supply_arma_r%d.spice" % k)
        atomic_write_text(pa, ta)
        pb = os.path.join(args.output_dir, "supply_armb_r%d.spice" % k)
        atomic_write_text(pb, arm_b(args.corner, ohms))
        written += [pa, pb]

    cn = rc.CORNERS[args.corner]
    print("corner %s: %g C, %g V" % (args.corner, cn["temp"], cn["supply"]))
    print("series resistances: " + ", ".join("%g" % o for o in OHMS) + " ohm")
    print("Arm A oscillator %d, distributed RC: %d resistors, %d grounded caps, "
          "%d couplings kept" % (args.ro, stats["res"], stats["cg"], stats["ccoup"]))
    print("Arm B reference macro ring, %d internal capacitors"
          % sum(1 for line in arm_b(args.corner, 1.0).splitlines()
                if line.startswith("Cb_")))
    print("wrote %d decks to %s" % (len(written), args.output_dir))
    print("each deck measures the period, the average supply current, and the "
          "average supply that actually reaches the cells")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
