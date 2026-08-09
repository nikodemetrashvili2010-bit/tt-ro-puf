# Copyright 2020-2022 Efabless Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# SPDX-License-Identifier: Apache-2.0
# Modifications copyright 2026 Nikoloz Demetrashvili, same licence.
#
# Custom PDN config, met4-only and macro-friendly. Same recipe as
# dualarm/src/pdn_cfg.tcl; the two differ only in comments, every directive is
# the same. See that file for the full note on what I changed and why.
#
# Modified copy of pdn_cfg.tcl from
# https://github.com/TinyTapeout/tt06-dffram-example, which carries the Efabless
# header above because the recipe comes from OpenLane's own default. Checked
# again upstream on 2026-08-09.
#
# Changed here: FP_PDN_* renamed to PDN_* for LibreLane 3, io.tcl sourced and
# the voltage domain set explicitly, -spacing added to the vertical stripe,
# -starts_with POWER dropped from the rail stripe, and the explanation below.
#
# Why this file exists: LibreLane's default pdn_cfg.tcl defines a default
# macro grid (define_pdn_grid -macro -halo ...) whose only connect statement
# is PDN_VERTICAL_LAYER <-> PDN_HORIZONTAL_LAYER (met4 <-> met5). In a TT user
# project met5 is FORBIDDEN (precheck tech_data.py: forbidden_layers sky130A =
# met5.drawing/pin/label), so that connect can never fire and the halo cuts
# the met4 stripes around every macro -> all macros end up power-isolated
# (this is exactly the PSM-0069/PDN-0233 wall we hit on the standalone array).
#
# The fix (same as tt06-dffram-example): define NO macro grid at all. The
# stdcell met4 stripes then run uncut through the macro areas. With
# PDN_VPITCH equal to the macro column pitch and PDN_VOFFSET aligned so a
# VPWR/VGND stripe pair lands exactly on each macro's internal met4 power
# straps (VPWR centerline x=21.84, VGND x=25.14 inside ro_macro_hard; pair
# pitch 3.3 um = VWIDTH 2.4 + VSPACING 0.9 in the current config),
# the stripe and the pin overlap on the same layer and are connected.
# ro_macro_hard has NO other met4 shapes (verified in its DEF), so a stripe
# crossing the macro cannot short anything.

source $::env(SCRIPTS_DIR)/openroad/common/io.tcl
source $::env(SCRIPTS_DIR)/openroad/common/set_global_connections.tcl
set_global_connections

set_voltage_domain -name CORE -power $::env(VDD_NET) -ground $::env(GND_NET)

# met4 vertical stripes are the grid AND the block's power pins (TT contract:
# user-block power pins are met4, min width 1.2 um).
define_pdn_grid \
    -name stdcell_grid \
    -starts_with POWER \
    -voltage_domain CORE \
    -pins $::env(PDN_VERTICAL_LAYER)

add_pdn_stripe \
    -grid stdcell_grid \
    -layer $::env(PDN_VERTICAL_LAYER) \
    -width $::env(PDN_VWIDTH) \
    -pitch $::env(PDN_VPITCH) \
    -offset $::env(PDN_VOFFSET) \
    -spacing $::env(PDN_VSPACING) \
    -starts_with POWER

# met1 rails for the standard cells (Arm A + control logic), tied to the
# met4 stripes.
if { $::env(PDN_ENABLE_RAILS) == 1 } {
    add_pdn_stripe \
        -grid stdcell_grid \
        -layer $::env(PDN_RAIL_LAYER) \
        -width $::env(PDN_RAIL_WIDTH) \
        -followpins

    add_pdn_connect \
        -grid stdcell_grid \
        -layers "$::env(PDN_RAIL_LAYER) $::env(PDN_VERTICAL_LAYER)"
}

# NOTE: intentionally NO define_pdn_grid -macro section. That is the point.
