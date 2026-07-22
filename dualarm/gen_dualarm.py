#!/usr/bin/env python3
# Generate dualarm/src/config.json: the green TinyTapeout project config plus
# the Arm B hardened-macro block (placement + power alignment).
#
# GEOMETRY (2x2 tile, die 334.88 x 225.76, template tt_block_2x2_pg.def):
#   TT margins (from the green config): LEFT/RIGHT_MARGIN_MULT 6, TOP/BOTTOM 1
#   -> core origin x = 6 sites * 0.46 = 2.76, y = 1 row * 2.72 = 2.72.
#   Macro grid: 4x4, columns x = 3.22/63.22/123.22/183.22 (pitch 60), rows y =
#   20/68/116/164 (pitch 48). The macro block ends at x=243.22; the remaining
#   core area to x=332.12 holds Arm A and integration standard cells.
#
# POWER (the PSM-0069 lesson from the standalone array):
#   The macro's power pins are two vertical met4 straps: VPWR centerline at
#   x = 21.84 inside the macro, VGND at 25.14 (ro_macro_hard.lef). Parallel
#   met4 can only connect by DIRECT OVERLAP, so the block's met4 stripes must
#   land exactly on the macro pins of every column:
#     FP_PDN_VPITCH  = 60  (the macro column pitch)
#     FP_PDN_VOFFSET = X0 + 21.84 - core_x0 = 3.22 + 21.84 - 2.76 = 22.30
#   (pdngen convention, verified from the macro's own DEF: first VPWR stripe
#   centerline = core_x0 + FP_PDN_VOFFSET; VGND follows at +3.3 with the
#   VWIDTH/VSPACING of 2.4/0.9, matching the macro's 3.3 um pin pitch.)
#   After floorplan, verify core_x0: grep "ROW ROW_0" in the DEF -> x=2760.
import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
N, COLS = 16, 4
# Columns ABUT (pitch 60 = macro width) - proven by array run pdnfix4
# (full DRC/LVS/antenna/PSM pass): no row slivers between columns, so no
# untappable well fragments. 8um horizontal bands between macro rows hold
# 1 std-cell row each (8 - 2*2um halo = 4 > 2.72).
PITCH_X, PITCH_Y = 60, 48
CORE_X0 = 6 * 0.46          # LEFT_MARGIN_MULT 6 (TT green config)
X0, Y0 = round(CORE_X0 + 0.46, 2), 20   # one site in from core edge
PIN_VPWR_X = 21.84          # VPWR centerline inside the macro (from LEF)

insts = {}
for i in range(N):
    c, r = i % COLS, i // COLS
    insts[f"u_rob{i}"] = {"location": [X0 + c * PITCH_X, Y0 + r * PITCH_Y],
                          "orientation": "N"}

config = {
    "//": "TinyTapeout green config + Arm B macro block. Comments: gen_dualarm.py",
    "PL_TARGET_DENSITY_PCT": 60,
    "CLOCK_PERIOD": 20,
    "PL_RESIZER_HOLD_SLACK_MARGIN": 0.1,
    "GRT_RESIZER_HOLD_SLACK_MARGIN": 0.05,
    "RUN_LINTER": 1,
    "LINTER_INCLUDE_PDK_MODELS": 1,
    "CLOCK_PORT": "clk",
    "RUN_KLAYOUT_XOR": 1,
    "RUN_KLAYOUT_DRC": 1,
    "DESIGN_REPAIR_BUFFER_OUTPUT_PORTS": 0,
    "TOP_MARGIN_MULT": 1,
    "BOTTOM_MARGIN_MULT": 1,
    "LEFT_MARGIN_MULT": 6,
    "RIGHT_MARGIN_MULT": 6,
    "FP_SIZING": "absolute",
    "GRT_ALLOW_CONGESTION": 1,
    "FP_IO_HLENGTH": 2,
    "FP_IO_VLENGTH": 2,
    "RUN_CTS": 1,
    "FP_PDN_MULTILAYER": 0,
    "MAGIC_DEF_LABELS": 0,
    "FP_MACRO_HORIZONTAL_HALO": 2,
    "FP_MACRO_VERTICAL_HALO": 2,
    "MAGIC_WRITE_LEF_PINONLY": 1,
    "VERILOG_FILES_BLACKBOX": ["dir::ro_macro_hard_bb.v"],
    "MACROS": {"ro_macro_hard": {"gds": ["dir::ro_macro_hard.gds"],
                                 "lef": ["dir::ro_macro_hard.lef"],
                                 "nl": ["dir::ro_macro_hard.nl.v"],
                                 "instances": insts}},
    # KEEP PDN_MACRO_CONNECTIONS: it drives add_global_connection (the LOGICAL
    # tie of each macro's VPWR/VGND pins to the power nets) and guards that all
    # 16 instances exist. It does NOT create the default macro grid.
    "PDN_MACRO_CONNECTIONS": [f"u_rob{i} VPWR VGND VPWR VGND" for i in range(N)],
    # Custom PDN script (dffram recipe): stdcell met4 grid only, NO macro grid,
    # so stripes run uncut over the macros and connect to their met4 power
    # straps by exact-overlap alignment. See docs/dualarm_pdn_plan.md.
    "PDN_CFG": "dir::pdn_cfg.tcl",
    # VALIDATED 2026-07-09 (array run met4only2, all green incl. PSM): stripes
    # connect to macro met4 pins via pdngen's same-net containment exemption
    # (Shape::cut). The stripe must fully CONTAIN the pin footprint bloated by
    # the met4 spacing rule (1.6 + 2x0.3 = 2.2), so width 2.4. width+spacing
    # must stay 3.3 = the macro's VPWR->VGND pin pitch.
    "FP_PDN_VWIDTH": 2.4,
    "FP_PDN_VSPACING": 0.9,
    "FP_PDN_VPITCH": PITCH_X,
    "FP_PDN_VOFFSET": round(X0 + PIN_VPWR_X - CORE_X0, 2),
}
open(os.path.join(HERE, "src", "config.json"), "w").write(json.dumps(config, indent=2))
right_edge = X0 + (COLS - 1) * PITCH_X + 60
print(f"macros={len(insts)} Vpitch={config['FP_PDN_VPITCH']} "
      f"Voffset={config['FP_PDN_VOFFSET']} macro_right_edge={right_edge} "
      f"(die 334.88 x 225.76, core x 2.76..332.12 y 2.72..223.04)")
for k in ("u_rob0", "u_rob5", "u_rob15"):
    print(k, insts[k])
