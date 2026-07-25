#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Build the enable-fall phase-sweep decks for the gating redesign.

The measurement core no longer gates the counter clock with `en_window`; the
window is enforced through the oscillator enable alone. The claim behind that
change is physical: when the enable falls at an arbitrary phase of the running
ring, the tap output settles through at most a couple of final edges, every
one of them full-swing and full-width, so the first ripple flop never sees a
runt. This script turns that claim into something ngspice can check.

It reads the checked-in matched-macro deck (real extracted parasitics, real
cells), and writes one deck per phase step. Each deck starts the ring at 2 ns
and drops EN at 30 ns plus k times 100 ps, with k covering more than one full
ring period. Each deck writes the parasitic tap waveform with wrdata.
`analyze_gate_sweep.py` then reports, for every phase, the minimum pulse width
seen at the tap after the enable falls and the number of settle edges.

Run (WSL, after the usual PDK_ROOT/PDK exports):
    python3 gen_gate_sweep.py --output-dir /tmp/gatesweep
    for f in /tmp/gatesweep/sweep_*.spice; do
        python3 ../run_ngspice.py "$f" --log "${f%.spice}.log"
    done
    python3 analyze_gate_sweep.py /tmp/gatesweep
"""

import argparse
import os

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "ro_macro_matched.spice")

T_BASE_NS = 30.0     # earliest enable-fall time
STEP_PS = 100        # phase step
N_STEPS = 19         # 19 x 100 ps = 1.9 ns, > one ring period (~1.76 ns)
T_TAIL_NS = 6.0      # simulated settle time after the latest fall


def build(k, template):
    t_fall_ns = T_BASE_NS + k * STEP_PS * 1e-3
    t_end_ns = T_BASE_NS + (N_STEPS - 1) * STEP_PS * 1e-3 + T_TAIL_NS
    out = []
    for line in template.splitlines():
        if line.startswith("Ven "):
            # rise at 2 ns as before, fall at the swept time
            out.append("Ven EN 0 PULSE(0 1.8 2n 50p 50p %.4fn 1)" % (t_fall_ns - 2.0))
        elif line.startswith(".tran "):
            out.append(".tran 1p %.1fn" % t_end_ns)
        elif line.startswith(".control"):
            out.append(".control")
            out.append("run")
            out.append("set wr_vecnames")
            out.append("wrdata sweep_%02d.raw.txt v(b_out)" % k)
            out.append("quit")
            out.append(".endc")
            out.append(".END")
            break
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", default="/tmp/gatesweep")
    args = ap.parse_args()
    template = open(TEMPLATE, encoding="utf-8").read()
    os.makedirs(args.output_dir, exist_ok=True)
    for k in range(N_STEPS):
        path = os.path.join(args.output_dir, "sweep_%02d.spice" % k)
        open(path, "w", newline="\n").write(build(k, template))
    print("wrote %d decks to %s (EN falls %.1f ns .. %.1f ns in %d ps steps)"
          % (N_STEPS, args.output_dir, T_BASE_NS,
             T_BASE_NS + (N_STEPS - 1) * STEP_PS * 1e-3, STEP_PS))
    print("note: ngspice writes each sweep_XX.raw.txt into the directory it"
          " runs in; run it from the output directory.")


if __name__ == "__main__":
    main()
