# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
#
# What PDN_CFG points to, since 11 September 2026. Two sources, in order:
# the PDN recipe, unchanged and still the same recipe as
# array/pdn_cfg.tcl (sim/verify_macro_provenance.py holds the two equal
# directive for directive, which is why the second line is not in that
# file), and then Arm A, set FIRM.
#
# This is the one Tcl file the flow sources after the rows are cut (step
# 18) and the taps and endcaps are in (19), and before any placement
# step, and OpenROAD.GeneratePDN writes the ODB it leaves behind. FIRM at
# step 17 stopped the rows being cut (ODB-0386, run 74); PLACED at step
# 33 let legalization move five cells (run 77). Set at step 21 they
# survive both. arma_place.tcl is generated from the frozen two-arm DEF
# by chip/gen_placement_cfg.py and held to it by P15; P16 holds these
# two lines; P13 keeps config.json clear of the two older mechanisms and
# pointed here. Paths are relative to this file, because the flow
# resolves dir:: to an absolute path and sources that from wherever it
# is running. See docs/phaseG_run77.md.
source [file join [file dirname [info script]] pdn_cfg.tcl]
source [file join [file dirname [info script]] arma_place.tcl]
