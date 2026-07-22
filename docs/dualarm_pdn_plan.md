# How the dual-arm macros get power with met4 only

On a TinyTapeout tile the user project can only route up to met4. met5 belongs
to the TinyTapeout top level. My Arm B oscillators are hardened macros with
met4 power pins, and two met4 shapes on the same layer only connect where they
physically overlap. There is no met4-to-met4 via. On the standalone test array
I had bridged the macro pins with met5 straps, but that cannot ship inside a
TinyTapeout block. This note is how I power the macros with met4 alone.

## Why met4-only is hard

met5 is forbidden in the user area, with no exceptions. TinyTapeout's precheck
lists it directly (`tt-support-tools/precheck/tech_data.py`):
`forbidden_layers["sky130A"] = ["met5.drawing", "met5.pin", "met5.label"]`, and
the forbidden-layer check fails the whole precheck if any met5 shape exists in
the GDS. So the met5 bridge from the standalone array is dead for the real chip.

The block's power pins are met4 with a minimum width of 1.2 um (same file:
`power_pins_layer["sky130A"] = "met4"`, `power_pins_min_width = 1200`), and a
default 1.6 um stripe clears that.

The reason my array kept failing is the default PDN script itself. LibreLane's
stock `pdn_cfg.tcl` ends with `define_pdn_grid -macro -default -halo ...` and
`add_pdn_connect -layers "met4 met5"`. In met4-only mode that macro grid still
cuts the power stripes around every macro with its halo, but its one connect
statement needs met5, which does not exist, so nothing ever reconnects the
pieces. The macros come out power-isolated by construction of the default
script. That is the PSM-0069 and PDN-0233 wall I kept hitting.

## The recipe

The fix is the one the tt06-dffram-example uses, and that block has taped out.
Use a custom PDN script that defines only the standard-cell grid and no macro
grid at all. The met4 stripes then run uncut straight through the macro areas.
Set the vertical pitch to the macro column pitch and the offset so each stripe
lands on the macro's internal met4 power strap. Same layer plus direct overlap
means connected. No met5, no halo, no macro grid.

I validated this on the standalone 16-macro array with met5 fully disabled.
Every stripe came out as one continuous column through all four macro rows, and
the checks were clean: Magic DRC 0, KLayout DRC 0, LVS clean, antenna 0,
power-grid violations 0 on both VPWR and VGND, flow errors 0. The debug
artifacts are in `array/met4only_debug/`.

One thing the plain DFFRAM recipe does not tell you. On current OpenROAD a macro
pin that belongs to no grid is treated as an obstruction, and it gets bloated
outward by the met4 spacing rule, 0.3 um a side. pdngen will let a stripe cross
a same-net obstruction, but only if the stripe fully contains it side to side
(the `Shape::cut` logic in `src/pdn/src/shape.cpp`). A stripe the same width as
the pin can never contain the bloated version, so my first met4-only run cut
every stripe 0.6 um short of the pins, which I could see in the DEF. This is
also why the tt06-era recipe worked at width 1.6 on older OpenROAD and does not
today. The fix is to make the stripe wider than the pin plus twice the bloat:
`FP_PDN_VWIDTH 2.4` and `FP_PDN_VSPACING 0.9`. Their sum stays 3.3 um, which is
the macro's VPWR-to-VGND pin pitch, so the pair still lands centered on both
pins, and the 0.9 um gap is DRC-legal.

## Alignment math

The macros sit on a 4x4 grid at x = X0 + 60k, all in orientation N and never
flipped. A mirrored macro would swap VPWR and VGND. Inside the macro the VPWR
strap centerline is at x = 21.84 and VGND at 25.14 (from the LEF), a pitch of
3.3 um.

pdngen puts its first VPWR stripe centerline at core_x0 plus the vertical
offset, which I confirmed from the macro's own DEF. So the offset is
`PDN_VOFFSET = macro_X0 + 21.84 - core_x0` and the vertical pitch
`PDN_VPITCH = 60`, the macro column pitch. Read core_x0 from ROW_0 in the
floorplan DEF of the actual run rather than assuming it. `dualarm/gen_dualarm.py`
computes VOFFSET 22.3 for X0 3.22 with the TinyTapeout 2x2 core_x0 of 2.76, but
check it against the real DEF.

`dualarm/pdn_cfg.tcl` holds all of this, written with the LibreLane 3 names
(`PDN_*` in place of the older `FP_PDN_*`): standard-cell met4 stripes with
`-pins met4`, met1 rails, and deliberately no macro grid. Keep
`PDN_MACRO_CONNECTIONS` in the config. It drives the logical net tie for the
macro power pins (`add_global_connection`), not the macro grid. This recipe
does not alter the hardened macro GDS, so the 569.5 MHz macro-level nominal
simulation remains the relevant pre-silicon reference. Top-level supply and
fabrication effects are not included in that number.

## The precondition that makes it safe

A stripe running over the macro is only safe because `ro_macro_hard` has zero
met4 or met3 signal shapes, which I checked in its DEF. The only met4 in the
macro is the two power straps, and the aligned stripe pair lands on them on the
same net, so there is nothing to short.

That is a real precondition, not a detail. The recipe only works for a macro
that keeps met4 clear of signal routing. If your macro routes signals on met4,
the uncut stripes cannot pass over it, and you need a different scheme, for
example bringing the power pins out to the macro edge so cut stripes can abut
them. Check your macro's DEF before you copy these numbers.

## To apply it

Point the config at `pdn_cfg.tcl` through `PDN_CFG` (the LibreLane 3 variable,
older alias `FP_PDN_CFG`) and keep `PDN_VPITCH` at the column pitch. Run the
floorplan, read core_x0 from ROW_0 in the DEF, set
`PDN_VOFFSET = macro_X0 + 21.84 - core_x0`, and re-run. After the PDN step, open
the DEF and confirm the stripes are continuous over the macros at the pin x
positions. The power connectivity check (PSM) has to be clean, which was the
array's final gate, and then a full green flow followed by a local precheck,
whose forbidden-layer check confirms no met5 anywhere.

## Fallback

If the recipe ever fails in practice with the untouched macro, stretch the
macro's met4 power straps to the full macro height in the GDS and LEF (a gdstk
edit; met4 is drawing 71/20, pin 71/16), which gives the stripes more overlap
area. That changes the macro GDS, so the matched-frequency SPICE would need a
re-check. Only do this if the connectivity check fails with the macro left
alone.
