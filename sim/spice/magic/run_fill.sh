#!/bin/sh
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
# The whole fill and second-extractor check, the sequence that ran on
# 20 October 2026. Run it in a copy of this folder with the archived
# decks_* folders taken out: run_decks.sh skips every deck that already has
# a log, so in place it would run nothing.
#
# Needs magic (8.3.685 here) on PATH, ngspice (42 here) and python3 with
# klayout, and five environment variables:
#   TECH_GDS  sky130A-GDS.tech  } both preprocessed from open_pdks 8afc8346,
#   TECH      sky130A.tech      } see README
#   LIB       sky130_fd_pr models/sky130.lib.spice at 1232782c
#   CELLS     a file holding sky130_fd_sc_hd nand2_1, inv_1 and buf_1 at
#             892688b, the cells' own .spice files run together
#   REPO      the top of this repository
# spiceinit here is sky130_fd_pr's models/.spiceinit with one thread. And
# in/, two layouts as GDS: base.gds, the shuttle's copy of the design, and
# swapped.gds, the same after the shuttle's replace_decap.py -p 0.1.
# About two hours on two cores, most of it ngspice.
set -e
TOP=tt_um_nikodemetrashvili20_ro_puf
B=$REPO/dualarm/build_armc/$TOP
G=$REPO/sim/spice/gono
if [ -e decks_base/A00.log ]; then
  echo "decks_base already has logs, run this in a clean copy"
  exit 1
fi

# 1. extractions with no fill: as submitted, and as swapped
sh extract.sh in/base.gds base
sh extract.sh in/swapped.gds swapped

# 2. fill at four grid phases (dx dy in um), each merged and extracted
for ph in "0 0 0" "1 1.37 0.91" "2 0.53 2.17" "3 2.29 1.61"; do
  set -- $ph
  python3 make_fill.py in/base.gds $TOP fill_$1.gds $2 $3 $TECH_GDS
  python3 merge_fill.py in/base.gds fill_$1.gds filled_$1.gds
  sh extract.sh filled_$1.gds filled_$1
done

# 3. loads per ring and per node
for n in base swapped filled_0 filled_1 filled_2 filled_3; do
  python3 ring_loads.py $n.spice loads_$n.csv
done
python3 node_caps.py base.spice nodes_base.json
python3 node_caps.py filled_0.spice nodes_filled_0.json

# 4. ring decks with those loads, and the pairs
python3 gen_decks.py nodes_base.json grounded decks_base $LIB $CELLS
python3 gen_decks.py nodes_filled_0.json floating decks_fill0 $LIB $CELLS
cp spiceinit decks_base/.spiceinit
cp spiceinit decks_fill0/.spiceinit
sh run_decks.sh decks_base decks_fill0
python3 compare_bits.py $G/rc_validation_3arm.csv $G/rc_validation_armc.csv \
    decks_base decks_fill0
python3 phase_bits.py loads_base.csv decks_base decks_fill0 \
    loads_filled_0.csv loads_filled_1.csv loads_filled_2.csv \
    loads_filled_3.csv
python3 tabulate.py --csv magic_rings.csv

# 5. magic against the SPEF on the layout with no fill, and four rings with
#    their own couplings kept as couplings
python3 crosscheck.py base.spice loads_base.csv $B.def $B.nom.spef \
    $G/rc_validation_3arm.csv $G/rc_validation_armc.csv
python3 coupled_decks.py base.spice grounded decks_cpl_base $LIB $CELLS \
    A00 A01 C12 C13
python3 coupled_decks.py filled_0.spice floating decks_cpl_fill0 \
    $LIB $CELLS A00 A01 C12 C13
cp spiceinit decks_cpl_base/.spiceinit
cp spiceinit decks_cpl_fill0/.spiceinit
sh run_decks.sh decks_cpl_base decks_cpl_fill0
