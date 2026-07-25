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
import argparse, json, math, os
HERE = os.path.dirname(os.path.abspath(__file__))
N = 16

# Column x positions. The default four abut into one block on the left of the
# tile, which is what the signed-off build uses. Any column list works as long as
# every entry sits on the 60 um PDN grid (see the POWER note above), because one
# FP_PDN_VOFFSET has to serve every column at once.
#
# The interleaved variant skips the middle grid column so a 60 um standard-cell
# channel runs down the centre of the macro field. That matters because in the
# default floorplan the macros tile x=3.22..243.22 and every Arm A oscillator
# ends up crammed into the remaining strip on the right, inside a box about
# 44 x 78 um. Arm A therefore samples one small region of the die while Arm B
# samples nearly all of it, which confounds a hypothesis about spatial pattern,
# and it is also why Arm A output nets carry about 0.84 fF against Arm B\'s
# 14.46 fF. See docs/hardware_todo.md items 3 and 4.
COLUMNS_ABUTTED = [3.22, 63.22, 123.22, 183.22]
COLUMNS_INTERLEAVED = [3.22, 63.22, 183.22, 243.22]
# Columns ABUT (pitch 60 = macro width) - proven by array run pdnfix4
# (full DRC/LVS/antenna/PSM pass): no row slivers between columns, so no
# untappable well fragments. 8um horizontal bands between macro rows hold
# 1 std-cell row each (8 - 2*2um halo = 4 > 2.72).
PITCH_X, PITCH_Y = 60, 48
CORE_X0 = 6 * 0.46          # LEFT_MARGIN_MULT 6 (TT green config)
X0, Y0 = round(CORE_X0 + 0.46, 2), 20   # one site in from core edge
PIN_VPWR_X = 21.84          # VPWR centerline inside the macro (from LEF)
MACRO_W, MACRO_H = 60, 40   # ro_macro_hard.lef SIZE
CORE_X1, CORE_Y1 = 332.12, 223.04   # core far edge (die 334.88 x 225.76)

def build_instances(columns):
    """One instance per macro, filling columns left to right, row by row."""
    insts = {}
    for i in range(N):
        c, r = i % len(columns), i // len(columns)
        insts[f"u_rob{i}"] = {"location": [columns[c], Y0 + r * PITCH_Y],
                              "orientation": "N"}
    return insts


def check_columns(columns):
    """Refuse a layout the power grid cannot serve, or one that leaves the die."""
    for x in columns:
        k = (x - X0) / PITCH_X
        if abs(k - round(k)) > 1e-9:
            raise SystemExit(
                f"column x={x} is off the {PITCH_X} um PDN grid; the met4 stripe "
                f"would miss the macro power pins (x must be {X0} + {PITCH_X}k)")
    right = max(columns) + MACRO_W
    if right > CORE_X1:
        raise SystemExit(f"rightmost macro ends at {right}, past the core edge {CORE_X1}")
    rows = math.ceil(N / len(columns))
    top = Y0 + (rows - 1) * PITCH_Y + MACRO_H
    if top > CORE_Y1:
        raise SystemExit(f"top macro row ends at {top}, past the core edge {CORE_Y1}")


ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--interleaved", action="store_true",
                help="skip the middle PDN column so a standard-cell channel runs "
                     "through the macro field (see COLUMNS_INTERLEAVED)")
ap.add_argument("--columns", help="explicit comma-separated column x positions")
ap.add_argument("--out", help="output path (default: src/config.json)")
ap.add_argument("--pitch-y", type=float, default=PITCH_Y,
                help="macro row pitch (default %(default)s). The gap between rows "
                     "is pitch minus the 40 um macro height, and 2 um of that is "
                     "halo at each side, so pitch 48 leaves a single 2.72 um "
                     "standard-cell row per band. That single row is a trap: with "
                     "the interleaved columns the placer strung one whole "
                     "oscillator along it, 125.6 x 2.7 um, tripling that ring's "
                     "routing load. Pitch 52 gives two rows per band instead.")
args = ap.parse_args()
PITCH_Y = args.pitch_y

if args.columns:
    columns = [float(v) for v in args.columns.split(",")]
elif args.interleaved:
    columns = list(COLUMNS_INTERLEAVED)
else:
    columns = list(COLUMNS_ABUTTED)
check_columns(columns)
insts = build_instances(columns)

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
    "FP_PDN_VOFFSET": round(min(columns) + PIN_VPWR_X - CORE_X0, 2),
}
out_path = args.out or os.path.join(HERE, "src", "config.json")
open(out_path, "w", newline="\n").write(json.dumps(config, indent=2))
right_edge = max(columns) + MACRO_W
print(f"columns={columns}")
print(f"wrote {out_path}")
print(f"macros={len(insts)} Vpitch={config['FP_PDN_VPITCH']} "
      f"Voffset={config['FP_PDN_VOFFSET']} macro_right_edge={right_edge} "
      f"(die 334.88 x 225.76, core x 2.76..332.12 y 2.72..223.04)")
for k in ("u_rob0", "u_rob5", "u_rob15"):
    print(k, insts[k])
