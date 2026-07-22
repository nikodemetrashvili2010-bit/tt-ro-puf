#!/usr/bin/env python3
# Generate the matched Arm B array: 16 identical ro_macro_hard copies on a
# uniform 4x4 grid, plus the LibreLane config that places AND powers them.
#
# GEOMETRY (v3, 2026-07-09, after run pdnfix2):
# Columns ABUT (pitch 60 = macro width) and the grid starts one site from the
# core edge. Why: pdnfix2 completed, but Magic flagged 4124 well-tap
# violations (nwell.4 / LU.2 / LU.3) - the 10um column gaps and 14um edge
# strips fragmented the rows into slivers the tap placer left untapped (58
# taps total). Abutting the columns deletes those slivers entirely; the only
# std-cell area left is full-width horizontal bands (between macro rows and
# at top/bottom) plus one wide right strip - long segments where tap insertion
# behaves normally. The macro keeps >5um internal clearance on its left/right
# edges (from its LEF), so abutment creates no shape interactions; en (bottom
# edge) and out (top edge) pins stay reachable from the horizontal bands.
#
# POWER (unchanged logic, recomputed numbers):
# - Vertical met4: strap pair centered on every macro column's pins.
#   pdngen: first VPWR stripe centerline = core_x0 + FP_PDN_VOFFSET.
#   Pin VPWR centerline inside macro = 21.84 (LEF). core_x0 = 12*0.46 = 5.52.
#   VOFFSET = X0 + 21.84 - 5.52; VPITCH = column pitch (60).
# - Horizontal met5: pair centered on every pin row AND between rows.
#   Pin y-center inside macro = 19.04; core_y0 = 4*2.72 = 10.88.
#   HOFFSET = Y0 + 19.04 - 10.88 = 28.16 with HPITCH 25 (rows at 50).
# - Default VWIDTH/VSPACING (1.6/1.7) put VGND on VGND; all instances stay
#   orientation N (mirroring would swap VPWR/VGND).
# After floorplan, verify: grep "ROW ROW_0" <def> -> x = 5520.
import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
N, COLS = 16, 4
MACRO_W, MACRO_H = 60, 40
PITCH_X, PITCH_Y = MACRO_W, 50          # columns abut; 10um bands between rows
CORE_X0, CORE_Y0 = 12 * 0.46, 4 * 2.72  # default LibreLane margins
X0, Y0 = round(CORE_X0 + 0.46, 2), 20   # one site in from the core edge
insts, vlines = {}, []
for i in range(N):
    c, r = i % COLS, i // COLS
    x, y = round(X0 + c * PITCH_X, 2), Y0 + r * PITCH_Y
    insts[f"u_rob{i}"] = {"location": [x, y], "orientation": "N"}
    vlines.append(f"  ro_macro_hard u_rob{i} (.en(en), .out(out[{i}]));")
rows = (N + COLS - 1) // COLS
die = [0, 0, round(X0 + (COLS-1)*PITCH_X + MACRO_W + 30, 0), Y0 + (rows-1)*PITCH_Y + MACRO_H + 30]
verilog = ("// Arm B matched array: 16 bit-identical hardened oscillator macros.\n"
           "`default_nettype none\n"
           "module ro_array (\n    input  wire        en,\n    output wire [15:0] out\n);\n"
           + "\n".join(vlines) + "\nendmodule\n`default_nettype wire\n")
open(os.path.join(HERE, "ro_array.v"), "w").write(verilog)
config = {
    "DESIGN_NAME": "ro_array",
    "VERILOG_FILES": ["dir::ro_array.v"],
    "VERILOG_FILES_BLACKBOX": ["dir::ro_macro_hard_bb.v"],
    "DESIGN_IS_CORE": True,
    "CLOCK_PORT": "",
    "CLOCK_PERIOD": 20,
    "RUN_CTS": False,
    "RUN_LINTER": False,
    "FP_SIZING": "absolute",
    "DIE_AREA": die,
    "PL_TARGET_DENSITY_PCT": 35,
    "MACROS": {"ro_macro_hard": {"gds": ["dir::ro_macro_hard.gds"],
                                 "lef": ["dir::ro_macro_hard.lef"],
                                 "nl": ["dir::ro_macro_hard.nl.v"],
                                 "instances": insts}},
    "PDN_MACRO_CONNECTIONS": [f"u_rob{i} VPWR VGND VPWR VGND" for i in range(N)],
    "FP_PDN_MULTILAYER": True,
    "FP_PDN_VPITCH": PITCH_X,
    "FP_PDN_VOFFSET": round(X0 + 21.84 - CORE_X0, 2),
    "FP_PDN_HPITCH": 25,
    "FP_PDN_HOFFSET": round(Y0 + (10.64 + 27.44) / 2 - CORE_Y0, 2),
    # Tap-insertion fix (found in librelane 3.0.3 source, run pdnfix3):
    # cut_rows and tapcell both exclude a halo around macros, DEFAULT 10um.
    # Our 10um inter-row bands sit entirely inside that halo -> zero taps
    # (proof: first tap row in pdnfix3 DEF is y=220.32 = macro top 210 + 10).
    # 2um keeps pin-access room while letting taps into bands and strips.
    "FP_MACRO_HORIZONTAL_HALO": 2,
    "FP_MACRO_VERTICAL_HALO": 2,
    "MAGIC_WRITE_LEF_PINONLY": True,
    "MAGIC_DEF_LABELS": False,
    "GRT_ALLOW_CONGESTION": True,
}
open(os.path.join(HERE, "config.json"), "w").write(json.dumps(config, indent=2))
print(f"DIE_AREA={die} macros={len(insts)} cols_abut_at={sorted(set(v['location'][0] for v in insts.values()))}")
print(f"Vpitch={config['FP_PDN_VPITCH']} Voffset={config['FP_PDN_VOFFSET']} "
      f"Hpitch={config['FP_PDN_HPITCH']} Hoffset={config['FP_PDN_HOFFSET']}")
