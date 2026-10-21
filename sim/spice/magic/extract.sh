#!/bin/sh
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
# Flat parasitic extraction of one layout with magic and sky130A.tech:
# capacitance and coupling, no resistance, every capacitor kept.
# Usage: sh extract.sh LAYOUT.gds NAME   ->  NAME.spice, NAME.log
set -e
GDS=$1
NAME=$2
TECH=${TECH:-../pdk/sky130A/libs.tech/magic/sky130A.tech}
mkdir -p ext_$NAME
cat > ext_$NAME/run.tcl <<EOF
drc off
crashbackups stop
locking disable
gds rescale false
gds read $GDS
load tt_um_nikodemetrashvili20_ro_puf
select top cell
extract path ext_$NAME
extract do capacitance
extract do coupling
extract no resistance
extract all
ext2spice hierarchy off
ext2spice cthresh 0
ext2spice format ngspice
ext2spice -p ext_$NAME -o $NAME.spice
quit -noprompt
EOF
magic -dnull -noconsole -T $TECH ext_$NAME/run.tcl > $NAME.log 2>&1
grep -q "exttospice finished" $NAME.log
echo "$NAME done"
