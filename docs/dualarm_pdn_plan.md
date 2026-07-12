# How the dual-arm macros get power with met4 only

Date: 2026-07-09. Status: DECIDED, verified against sources. Build is the next step.

## The question

The TT user project may only route up to met4 (met5 belongs to the TT top
level). Our Arm B macros have met4 power pins, and same-layer met4 connects
only by direct overlap - there is no met4-to-met4 via. On the standalone
array we bridged the pins with met5 straps, but can that ship in a TT block?

## Verified facts (with sources)

1. **met5 is forbidden in the user area. Hard no.** TT precheck,
   `tt-support-tools/precheck/tech_data.py`:
   `forbidden_layers["sky130A"] = ["met5.drawing", "met5.pin", "met5.label"]`.
   The forbidden-layer check fails the whole precheck if any met5 shape
   exists in the GDS. So the met5 fix from the standalone array (pdnfix4) is
   dead for the TT block. Confirmed, not assumed.

2. **The block's power pins are met4, min width 1.2 um.** Same file:
   `power_pins_layer["sky130A"] = "met4"`, `power_pins_min_width = 1200`.
   Default stripe width 1.6 um passes.

3. **Why our array kept failing:** LibreLane's default `pdn_cfg.tcl` ends
   with `define_pdn_grid -macro -default -halo ...` plus
   `add_pdn_connect -layers "met4 met5"`. In met4-only mode that macro grid
   still cuts the stripes around every macro (halo), but its only connect
   statement needs met5 - which doesn't exist - so nothing ever reconnects
   them. Macros end up power-isolated *by construction of the default
   script*. That is exactly the PSM-0069 / PDN-0233 wall.

4. **The blessed recipe (tt06-dffram-example, taped out, works):** a custom
   PDN script (`FP_PDN_CFG` in their OpenLane 2 config) that defines ONLY the
   stdcell grid and NO macro grid at all. Result: the met4 stripes run uncut
   through the macro areas. Their README requires VPITCH = macro strap pitch
   and VOFFSET = macro x + strap offset, so each stripe lands exactly on the
   macro's internal met4 power strap. Same layer + direct overlap =
   connected. No met5, no halo, no macro grid.

## VALIDATED 2026-07-09 - smoke test green

The recipe below was proven on the standalone 16-macro array (run
`met4only2`, met5 fully disabled): every stripe is one continuous column
through all four macro rows, and the metrics are all clean - Magic DRC 0,
KLayout DRC 0, LVS clean, antenna 0, power_grid_violation 0 on VPWR and
VGND, flow errors 0. Debug artifacts in `array/met4only_debug/`.

One refinement was needed beyond the plain DFFRAM recipe. On current
OpenROAD, a macro pin that belongs to no grid becomes an obstruction
BLOATED by the met4 spacing rule (0.3 um/side), and pdngen's same-net
exemption (`Shape::cut` in src/pdn/src/shape.cpp: a stripe may overlap a
same-net obstruction only if it fully CONTAINS it side-to-side) then can
never fire for a stripe the same width as the pin. That is why the first
met4-only run cut every stripe 0.6 um short of the pins (seen in the DEF),
and it is why the tt06-era recipe worked at width 1.6 on older OpenROAD but
does not today. Fix: make the stripe wider than pin + 2 x bloat:
**FP_PDN_VWIDTH 2.4, FP_PDN_VSPACING 0.9** (sum stays 3.3 = the macro's
VPWR-to-VGND pin pitch, so the pair still lands centered on both pins; the
0.9 gap is DRC-legal).

## The decision

Copy the DFFRAM recipe plus the width fix. `dualarm/pdn_cfg.tcl` is written
and ready (LibreLane 3 names: PDN_* instead of FP_PDN_*): stdcell met4
stripes with `-pins met4`, met1 rails, and deliberately no macro grid.

Alignment math for our 4x4 macro grid (macros at x = X0 + 64k, all
orientation N, never flipped):

- macro internal VPWR strap centerline: x = 21.84 (from LEF); VGND at 25.14.
  Pair spacing 3.3 = default VWIDTH 1.6 + VSPACING 1.7. NEVER change VWIDTH
  or VSPACING.
- pdngen convention (verified empirically from the macro's own DEF): first
  VPWR stripe centerline = core_x0 + PDN_VOFFSET.
- so: PDN_VOFFSET = (macro_X0 + 21.84) - core_x0, and PDN_VPITCH = 64 (the
  macro column pitch). Read core_x0 from ROW_0 in the floorplan DEF of the
  actual run - do not assume it.

Because there is no macro grid, halos and abutment tricks stop mattering.
The macro GDS is NOT touched - no pin stretching, no re-harden - so the
measured matched frequency (569.5 MHz) stays exactly valid.

Why a stripe over the macro is safe: ro_macro_hard contains zero met4/met3
signal shapes (verified in its DEF). The only met4 in the macro is the two
power straps themselves, and the aligned stripe pair lands on them same-net.
Nothing to short.

That is a real precondition, not a detail. The recipe only works for macros
that keep met4 clear of signal routing. If your macro routes signals on met4,
the uncut stripes cannot pass over it, and you need a different scheme, for
example power pins brought out to the macro edge so cut stripes can abut
them. Check your macro's DEF before copying these numbers.

## Build checklist (next session)

1. Verify the LibreLane 3 variable name for a custom PDN script (expected
   `PDN_CFG`; grep the installed librelane source in WSL:
   `grep -rn "PDN_CFG" ~/ttsetup/venv312/lib/*/site-packages/librelane/steps/`).
2. Update `dualarm/gen_dualarm.py` / `config.json`: point at `pdn_cfg.tcl`
   (PDN_CFG, verified in librelane 3.0.3 source, old alias FP_PDN_CFG), keep
   PDN_VPITCH = column pitch, KEEP PDN_MACRO_CONNECTIONS - it drives
   add_global_connection (the logical net tie for the macro power pins), not
   the macro grid - and keep macros orientation N. DONE 2026-07-09.
3. Run the floorplan, read core_x0 from ROW_0 in the DEF, set PDN_VOFFSET =
   macro_X0 + 21.84 - core_x0, re-run. (gen_dualarm.py already computes
   this: VOFFSET 22.3 for X0 3.22 with TT 2x2 core_x0 2.76 - verify against
   the actual DEF anyway.)
4. After the PDN step, open the def/odb and confirm the stripes are
   continuous over the macros at the pin x positions.
5. PSM power connectivity must be clean (this was the array's final gate).
6. Full flow green, then TT precheck locally (forbidden-layer check will
   confirm no met5 anywhere).

## Fallback (only if the recipe fails in practice)

Stretch the macro's met4 power pin straps to the full macro height in
GDS+LEF (gdstk edit; met4 drawing 71/20, pin 71/16), giving the stripes more
overlap area. This changes the macro GDS, so the matched-frequency SPICE
would need a re-check. Only do this if step 5 fails with the untouched macro.
