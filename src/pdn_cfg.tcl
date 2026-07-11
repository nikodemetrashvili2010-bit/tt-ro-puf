# Custom PDN config for the dual-arm TT block (met4-only, macro-friendly).
# Copied from the tt06-dffram-example recipe, updated to LibreLane 3 variable
# names (FP_PDN_* became PDN_*).
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
# spacing 3.3 um = default VWIDTH 1.6 + VSPACING 1.7 -- never change these),
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
