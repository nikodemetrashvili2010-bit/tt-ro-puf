#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Flop-level check of the ring-stop boundary for the gating redesign.

The tap-only phase sweep (gen_gate_sweep.py) showed what stopping a free-running
ring must produce: the final pulse width depends on the enable-fall phase and can
be short. That is inherent to gating any free ring. The real question is not the
pulse width at the tap, it is what the first ripple-counter flop does with it.

This deck answers that directly. It takes the checked-in matched-macro ring (real
extracted parasitics) and clocks a real sky130 dfrtp_2, wired as a toggle stage
(D = Q-bar), from the ring tap b_out, exactly as the measurement core's first
ripple bit is clocked by the selected oscillator. RESET_B is asserted low for the
first nanosecond and then released, matching cnt_rst_n going high before a
measurement. The enable is dropped across a fine phase grid, and each deck records
the flop output q through a long settle tail.

analyze_flop_sweep.py then checks the property that actually matters: at every
enable-fall phase q resolves to a clean logic level within the settle tail (no
metastable plateau), and the number of counted toggles moves by at most one edge
across all phases. That is the design claim: a short boundary pulse costs at most
one count, never a corrupt word, because the ring is stopped and the core waits
for the counter to settle before latching.

Run (WSL, after the usual PDK_ROOT/PDK exports):
    python3 gen_flop_sweep.py --output-dir /tmp/flopsweep
    for f in /tmp/flopsweep/flop_*.spice; do
        python3 ../run_ngspice.py "$f" --log "${f%.spice}.log"
    done
    python3 analyze_flop_sweep.py /tmp/flopsweep
"""

import argparse
import os

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "ro_macro_matched.spice")

T_BASE_NS = 30.0     # earliest enable-fall time
STEP_PS = 50         # fine phase step, to resolve the short-pulse window
N_STEPS = 38         # 38 x 50 ps = 1.9 ns, > one ring period (~1.7 ns)
T_TAIL_NS = 12.0     # long settle after the latest fall, so q can resolve

# First ripple-counter stage: a real dfrtp_2 as a toggle flop (D = Q-bar),
# clocked by the parasitic ring tap b_out. dfrtp_2 pins: CLK D RESET_B VGND VNB
# VPB VPWR Q. inv_1 pins: A VGND VNB VPB VPWR Y.
FLOP = [
    "* --- first ripple stage: dfrtp_2 toggle flop clocked by the ring tap ---",
    "Vrstn RSTN 0 PULSE(0 1.8 1n 50p 50p 500n 1000n)",   # reset low to 1 ns, then released
    "Xff_inv q 0 0 VPWR VPWR qbar sky130_fd_sc_hd__inv_1",
    "Xff b_out qbar RSTN 0 0 VPWR VPWR q sky130_fd_sc_hd__dfrtp_2",
]


def build(k, template):
    t_fall_ns = T_BASE_NS + k * STEP_PS * 1e-3
    t_end_ns = T_BASE_NS + (N_STEPS - 1) * STEP_PS * 1e-3 + T_TAIL_NS
    out = []
    for line in template.splitlines():
        if line.startswith("Ven "):
            out.append("Ven EN 0 PULSE(0 1.8 2n 50p 50p %.4fn 1)" % (t_fall_ns - 2.0))
        elif line.startswith(".save") or line.startswith(".tran ") or line.startswith(".control"):
            out += FLOP
            out.append(".save v(q) v(b_out)")
            out.append(".tran 1p %.1fn" % t_end_ns)
            out.append(".control")
            out.append("run")
            out.append("set wr_vecnames")
            out.append("wrdata flop_%02d.raw.txt v(q)" % k)
            out.append("quit")
            out.append(".endc")
            out.append(".END")
            break
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", default="/tmp/flopsweep")
    args = ap.parse_args()
    template = open(TEMPLATE, encoding="utf-8").read()
    os.makedirs(args.output_dir, exist_ok=True)
    for k in range(N_STEPS):
        path = os.path.join(args.output_dir, "flop_%02d.spice" % k)
        open(path, "w", newline="\n").write(build(k, template))
    print("wrote %d decks to %s (EN falls %.1f ns .. %.1f ns in %d ps steps)"
          % (N_STEPS, args.output_dir, T_BASE_NS,
             T_BASE_NS + (N_STEPS - 1) * STEP_PS * 1e-3, STEP_PS))
    print("note: ngspice writes each flop_XX.raw.txt into the directory it runs in;"
          " run it from the output directory.")


if __name__ == "__main__":
    main()
