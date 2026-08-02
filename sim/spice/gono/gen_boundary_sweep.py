#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""The ring-stop boundary measured through the selector, which is the gap items 1 and 2 left.

Item 1 dropped the enable across a ring period and watched the first counter
flop, but that flop was clocked straight from the ring tap. Item 2 pushed a
steady ring through all 32 selector paths into the same flop, but the enable
never fell. Each half is checked. The combination is not, and the combination is
what the chip does.

Item 2 predicted the combination was safe, and when I first wrote this file I
thought its arithmetic was wrong in the dangerous direction. We were both wrong,
for the same reason. Item 2's level shortening compared the narrowest level at
the tap against the narrowest at sel_ro, and those turn out to be opposite
polarities. Rise and fall cross the path at different speeds, and the difference
moves each trailing edge without moving the leading one, so every path lengthens
its high level and shortens its low by the same amount. On B15 the high grows by
181 ps, 539 ps at the tap arriving as 721 ps at sel_ro, with the period preserved
to the picosecond. The counter's first stage is a rising-edge flop, so the
selector hands it more margin than the tap did rather than less.

That is a steady-state argument, and the boundary is exactly where it stops
applying, because the last high is cut short by the enable falling inside it.
Below some width a pulse stops being a narrow rectangle and becomes a bump that
never reaches the rail. Measured on B15, that width sits between 97 and 102 ps at
the tap, and the step is sharp enough that nothing lands in between. No amount of
arithmetic about delays was going to find that number, which is the whole reason
this file exists.

The two outcomes are not equally bad. A swallowed last pulse costs the counter
one edge, which is the same one-count error item 1 already accepted and the
settle handshake already tolerates. What would matter is a pulse landing near
the flop's resolving threshold and leaving q at mid-rail. So the test here is
item 1's test, run through item 2's worst path.

The deck is not a new circuit. It is what gen_mux_sweep.py builds for one
oscillator, real cells out of the routed netlist, every intermediate net loaded
from that build's SPEF, pin order read from the PDK, with two lines rewritten:
the enable falls at the swept phase, and the transient runs long enough for q to
settle after it. Keeping the selector half identical to the decks item 2 already
validated is deliberate. If this sweep finds something, the enable timing found
it, not a second copy of the path builder that drifted.

B15 is the default because it has the deepest and slowest chain in the set, five
cells through a mux4_2 with a 360 ps rise, and the measurements say chain depth
decides the threshold rather than asymmetry does. A05 adds the least width of any
path, 102 ps against B15's 182, and still passes a narrower pulse, 69 ps against
102. The one path I have not swept is B00, which is slower again at 375 ps and
helps slightly less at 166 ps.

Run (WSL, after the usual PDK_ROOT and PDK exports):
    python3 gen_boundary_sweep.py --output-dir /tmp/bndsweep --corner ff
    cd /tmp/bndsweep
    for f in bnd_*.spice; do python3 ../../run_ngspice.py "$f" --log "${f%.spice}.log"; done
    python3 analyze_boundary_sweep.py /tmp/bndsweep --vdd 1.95

The default grid is item 1's, 38 phases of 50 ps. Use --base-ns, --step-ps and
--steps to walk slowly through the width where the pulse stops surviving, which
is what found the 97 to 102 ps step on B15:
    python3 gen_boundary_sweep.py --osc B15 --base-ns 30.10 --step-ps 5 --steps 13
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

import gen_mux_sweep as mux                                  # noqa: E402
from pdk_paths import atomic_write_text, sky130_spice_paths  # noqa: E402

# Defaults are the phase grid gen_flop_sweep.py used. Holding the grid fixed is
# what lets the two sweeps be read against each other step by step instead of
# roughly. The three of them are arguments as well, because a coarse sweep can
# only report that a pulse survived at one width and died at another, and the
# interesting question is what happens in between.
T_BASE_NS = 30.0     # earliest enable fall, well after the ring is steady
STEP_PS = 50         # phase step
N_STEPS = 38         # 38 x 50 ps = 1.9 ns, longer than a ring period at any corner
T_TAIL_NS = 12.0     # settle window after the latest fall, so q can resolve


def patch(text, k, n_steps, t_fall_ns, t_end_ns, supply):
    """Rewrite the enable, the transient length and the output file name.

    Every substitution is counted and a miss stops the run. A deck that quietly
    kept item 2's enable would leave the ring running forever, produce a clean
    settled q at every phase, and report a pass for a sweep that never swept.
    That is the failure this function exists to make impossible.
    """
    counts = []

    text, n = re.subn(
        r'(?m)^Ven EN 0 PULSE\(.*\)$',
        "Ven EN 0 PULSE(0 %g 2n 50p 50p %.4fn 1)" % (supply, t_fall_ns - 2.0),
        text)
    counts.append(("enable source", n))

    text, n = re.subn(r'(?m)^\.tran .*$',
                      ".tran %dp %.2fn" % (mux.T_STEP_PS, t_end_ns), text)
    counts.append(("transient command", n))

    text, n = re.subn(r'(?m)^wrdata mux_\S+\.raw\.txt ',
                      "wrdata bnd_%02d.raw.txt " % k, text)
    counts.append(("wrdata line", n))

    text, n = re.subn(
        r'(?m)^(\* chain: .*)$',
        (r"\1" + "\n* boundary sweep: enable falls at %.4f ns, phase %d of %d"
         % (t_fall_ns, k, n_steps - 1)),
        text)
    counts.append(("chain comment", n))

    wrong = ["%s (%d)" % (name, n) for name, n in counts if n != 1]
    if wrong:
        raise SystemExit(
            "gen_boundary_sweep: expected exactly one of each line to rewrite, got "
            + ", ".join(wrong)
            + ". gen_mux_sweep.py's deck format has changed and this script has "
              "not been updated to match.")
    return text


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--output-dir", default="/tmp/bndsweep")
    ap.add_argument("--corner", default="ff", choices=sorted(mux.CORNERS),
                    help="PVT corner (default ff, where the ring is fastest and "
                         "the boundary pulse is shortest)")
    ap.add_argument("--osc", default="B15",
                    help="which selector path to sweep through (default B15, the "
                         "worst path on both the percentage and the absolute "
                         "shortening)")
    ap.add_argument("--lib", default=None,
                    help="sky130_fd_sc_hd.spice; default is the usual PDK resolution")
    ap.add_argument("--base-ns", type=float, default=T_BASE_NS,
                    help="time of the earliest enable fall (default %g)" % T_BASE_NS)
    ap.add_argument("--step-ps", type=float, default=STEP_PS,
                    help="phase step (default %g). Drop it to walk slowly through "
                         "the width where a pulse stops surviving." % STEP_PS)
    ap.add_argument("--steps", type=int, default=N_STEPS,
                    help="number of phases (default %d)" % N_STEPS)
    args = ap.parse_args()
    if args.steps < 1 or args.step_ps <= 0:
        raise SystemExit("--steps must be at least 1 and --step-ps must be positive")

    corner = mux.CORNERS[args.corner]
    lib = args.lib if args.lib else str(sky130_spice_paths()[1])
    order = mux.read_pin_order(lib)

    insts, loads = mux.read_netlist(mux.NETLIST)
    caps = mux.read_spef_caps(mux.SPEF)
    paths = mux.find_paths(insts, loads)

    picked = [p for p in paths if p[0] == args.osc]
    if not picked:
        raise SystemExit("no oscillator called %s; the tags are %s"
                         % (args.osc, ", ".join(t for t, _, _ in paths)))
    tag, src, path = picked[0]
    if not path:
        raise SystemExit("no selector path was found for %s" % tag)

    os.makedirs(args.output_dir, exist_ok=True)
    t_last_ns = args.base_ns + (args.steps - 1) * args.step_ps * 1e-3
    t_end_ns = t_last_ns + T_TAIL_NS

    absent = []
    for k in range(args.steps):
        text, missing = mux.build(tag, src, path, caps, corner, order)
        absent += missing
        text = patch(text, k, args.steps,
                     args.base_ns + k * args.step_ps * 1e-3, t_end_ns,
                     corner["supply"])
        atomic_write_text(os.path.join(args.output_dir, "bnd_%02d.spice" % k), text)

    chain = " ".join(c.replace("sky130_fd_sc_hd__", "") + "." + pin
                     for _, c, pin, _, _ in path)
    print("corner %s: %g C, %g V" % (args.corner, corner["temp"], corner["supply"]))
    print("oscillator %s through %d cells: %s" % (tag, len(path), chain))
    print("wrote %d decks to %s" % (args.steps, args.output_dir))
    print("enable falls from %.3f ns to %.3f ns in %g ps steps, then %.0f ns to settle"
          % (args.base_ns, t_last_ns, args.step_ps, T_TAIL_NS))
    if absent:
        print("WARNING: %d intermediate net(s) had no SPEF entry and carry no load: %s"
              % (len(set(absent)), ", ".join(sorted(set(absent)))))
    else:
        print("every intermediate net carries its own SPEF capacitance")
    print("pin order for %d cells read from %s" % (len(order), lib))
    print("note: ngspice writes each bnd_XX.raw.txt into the directory it runs in,"
          " so run the decks from the output directory.")


if __name__ == "__main__":
    main()
