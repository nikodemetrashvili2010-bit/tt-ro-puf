# The selector at the typical and slow corners

5 October, finished 10 October.

The timed run of the night before left one margin thin: the low half of the
first counter flop's clock, at tt and ss, in the more pessimistic of two
models. The decks that would settle it are the 48 selector paths in SPICE,
and since 18 September they had only been run at the fast corner.

They are run at tt now, all 48, and at ss as far as the evening went,
narrowest first. The margin is not thin.

## The setup, and how I know it is the old one

ngspice 42 out of Ubuntu's archive and a `sky130A` tree put together by
hand, as `docs/phaseG_spice_rerun.md` describes it: device models from
`fossi-foundation/skywater-pdk-libs-sky130_fd_pr` at `403964d`, standard
cells from `efabless/skywater-pdk-libs-sky130_fd_sc_hd` at `5a42fd0`, the
437 cell files strung into one.

A setup made a second time is a different setup until something says it is
not, so three things first.

`gen_mux_sweep.py --build dualarm/build_armc --corner ff --control` writes
the 96 fast corner decks again, and all 96 are byte for byte the ones in
`sim/spice/gono/mux3/`.

I ran one of them, B11, the widest gap of the 48. Its row comes back as the
archive has it, 240 ps up, 449 down, a 377 ps low, 30 edges, 15 flop rises.

And its waveform, cut down by `reduce_raw.py` the way the archive's were, is
the archived file to the last byte, md5 `814b17fa`.

One thing in that older note does not hold at this commit. It says a stray
`include` in the 5 V device's file had to be commented out. At `403964d`
upstream has already corrected it (`8ed2664`), and nothing here was patched.

## What ran

The same generator with `--corner tt` and `--corner ss`: 27 C and 1.80 V,
100 C and 1.60 V. The decks differ from the fast corner's in the corner, the
temperature and the supply and in nothing else, and they come out the same
when made twice.

The window is the fast corner's 42 ns, which is all the generator knows. A
slower ring puts fewer edges in it: 30 at ff, 19 at tt, 9 at ss.

At tt all 48 open paths ran. At ss 35 did: all of Arm A, all of Arm B but
B01, and four of Arm C. After the first ten they were taken narrowest first
by the fast corner's figures. So the 13 left over, B01 and twelve of Arm C,
all have a low of 425 ps or more at ff and 654 or more at tt, where the
narrowest are 377 and 573.

The queue stopped at a quarter to ten, when the machine went down for the
second time in two days. This time it could have been picked up where it
stopped. I left it: the narrowest paths were in and the evening was gone.

The blocked controls, which show that a path held shut passes nothing, were
run at neither corner. They were silent on all 48 at ff, on decks that
differ from these in the corner and nothing else.

A deck took 2.3 minutes when the evening started and anything up to nine
after that, two at a time on a machine with two cores that was not mine
alone. The 18 September note says two minutes and I had planned on that.

## What came back

Every path that ran passes. Every edge that left the ring arrived at the
counter's clock, and the flop, a real `dfrtp_2`, toggled on every one.

    corner  arm  paths  rise delay   fall less rise  high at sel_ro  low
    tt      A    16     321-464 ps   269-305         1108-1144       608-645
    tt      B    16     392-562      260-341         1099-1179       573-654
    tt      C    16     292-523      140-264         979-1102        650-773
    ss      A    16     684-970      492-541         2139-2188       1247-1296
    ss      B    15     849-1176     458-582         2105-2230       1205-1330
    ss      C    4      619-1051     275-497         1922-2145       1290-1513
    ff      A    16     197-288      161-186         697-722         400-425
    ff      B    16     240-349      159-209         695-745         377-427
    ff      C    16     174-319      90-163          626-699         423-496

The last three rows are the archive's, for the eye. The tap is the same ring
in every deck of a corner: 839 ps high and 914 low at tt, 536 and 586 at ff.
At ss it is 1647 or 1648 and 1787 to 1789, with the period the same in all
35 decks, 3435.4 ps. The picosecond follows the pin the path starts on, of
which there are four, so it is the load on the tap and not the ring.

The widest gap is on B11 at every corner, 209 ps at ff, 341 at tt and
582 at ss, and the narrowest on C07, 90, 140 and 275. The five
narrowest lows are the same five paths in the same order at ff and at tt:
B11, B08, B15, B07, B12. All five are Arm B's, four cells each, in through
an `a221o_2` and on through the `o21ba_2`.

At tt 19 edges go in and 19 come out on every path, with 9 or 10 flop
rises. At ss it is 9 and 9, with 5.

## Against the SDF

The timed run had the same 48 paths out of run 83's SDF, so the two can be
put side by side path by path. The SDF's delay over SPICE's:

    corner   rising             falling            fall minus rise
    tt       1.30 to 1.59       1.48 to 1.88       1.54 to 2.55
    ss       1.27 to 1.56       1.44 to 1.82       1.71 to 2.46   (35 paths)
    ff       1.28 to 1.53       1.36 to 1.47       1.34 to 1.69

These are from the csv files. For the fast corner's gap the timed run's log
has 1.33 where this has 1.34: it subtracts the rounded rise from the rounded
fall, and this takes the csv's own column.

At the fast corner the SDF is the slower model by a steady four tenths, up
and down alike. At the other two the rising edge is off by about as much
and the falling edge by a good deal more, and the gap between them, which is
what shortens the low half, comes out about twice SPICE's.

## Why the two part

I did not know when the decks came back, and it mattered: the same tables
time everything else at those corners. So I took A05 at tt apart.

SPICE again with every node on the path saved, next to the SDF's five
cells, delays rising and falling in ps:

    cell        SPICE        SDF          SDF over SPICE
    a22o_2       99   127    152   235    1.54   1.85
    a221o_2      75   131    115   314    1.54   2.39
    a22o_2      105   143    148   268    1.41   1.87
    o21a_2       88   149    120   198    1.36   1.33
    a211o_2      68   165     92   298    1.35   1.81
                435   716    627  1313

The bottom row is the path measured end to end. The rows above it are
rounded, which is why SPICE's falling column adds to one less.

It is not slew. The edges in SPICE are quick at every node, 22 to 41 ps
from 20 to 80 percent. And the SDF's figures are the liberty table's own:
`a221o_2` from C1 at a 50 ps slew into that load reads 116 and 317 ps.

Two things multiply.

The library's cells are slower than these SPICE netlists by about 1.3, up
and down alike. The rings have always shown much the same, 1.18 to 1.23 at
tt. The cell netlists the decks include are transistors with none of the
wiring inside the cell, and I take that to be it without having shown it.

And the library has one figure for each arc of an AND-OR cell, whatever the
other inputs are doing. I ran three of those cells alone at tt, same slew
and load, once with the other inputs as the decks tie them and once with
one input of each pair held high:

    arc            others low    one of each pair high    liberty
    a221o_2 C1      81   143      89   245                116   317
    a211o_2 B1      74   177      77   232                 96   307
    a22o_2 A1       99   134      97   170                132   234

There are two ways to hold one of each pair high and the table has the
slower. The other way the falling edge comes out between the two columns,
188, 205 and 152 ps.

With one of each pair high SPICE sits 1.24 to 1.38 under the liberty on
both edges, which is the factor above and nothing more. An `o21a_2` from
A2, which has only the one setting, sits 1.26 to 1.28 under. So the
liberty's figure is the slow setting's. With the others all low the falling
edge is 1.3 to 1.7 times quicker.

Which setting is the chip in? That is a fact about the netlist and the
decks only assume it, so I put a probe on the timed model and read every
input of all 37 selector cells while each of the 48 rings ran. On 44 paths
every side input is at the level its deck ties it to. A ring that is not
selected idles low and so does its select, so every AND that is not passing
a ring has both inputs low.

So the SDF's wide gap is the library's slow setting, which this chip is
never in, on top of a library that is slower all round. The decks have the
setting right on 44 paths, and nothing had checked that before either.

Which of the two is right about plain speed I cannot say from here. It does
not change this: if the cells are as slow as the library has them the rings
are slower by the same factor, and the low half gets longer, not shorter.

## The other four

On C00 to C03 one gate is tied wrong. `_447_` is an `o21a_2` that the path
enters at B1. The generator ties A1 high and A2 low, and the chip holds them
the other way round.

I had this down as the same gate either way. It is the same logic and not
the same transistors, so I ran it: C00 again with the two swapped, at tt and
at ff, nothing else in the deck touched.

    C00                   rise   fall   gap   low at sel_ro
    tt, as generated      523    738    215   699 ps
    tt, as the chip is    515    736    221   692
    ff, as archived       319    456    137   449
    ff, as the chip is    314    455    141   445

Every edge still arrives and the flop still counts them all. The low is 7 ps
shorter at tt and 4 at ff. On its own ring's period C00 is still 107 ps
clear of the narrowest path at tt and 60 at ff, and the other three start
higher, so nothing above moves. The tables in this note are the decks as
generated.

But four rows of the fast corner archive are a few picoseconds kind. It
comes from one line of the generator's table, the one for an `o21a_2`
entered at B1, and these four paths are the only ones that use it. On the
chip A2 is the high one because the gate that drives it has its own C1
held high for this group, and the table has no way to know that.

## The low half

This is the figure the timed run asked for. The low half of the counter's
clock is the ring's own low at the tap less the gap above. With each ring at
its own SPICE speed and through its own path:

    corner   narrowest low    on     the SDF's limit   times over
    tt       573 ps           B11    260 to 262        2.2
    ss       1205             B11    574 to 578        2.1
    ff       377              B11    136 to 138        2.7

By arm the narrowest at tt are A04 at 624 ps, B11 at 573 and C10 at 630,
and at ff the same three, 409, 377 and 410.
At ss, of the paths that ran, A04 at 1275, B11 at 1205 and C10 at 1252.

Arm B's ring is the stimulus itself, so its lows are measured. For the
other two arms the tap is rescaled to each ring's own period out of
`sim/spice/gono/rc3/`, which is good to a picosecond or so.

The limit is the library's figure for that flop at the slew the timing tool
gave its clock, and `phaseG_timed.md` says why it is a soft one. The flop in
the deck is not looked up at all. It is 30 transistors, and it counted.

So the thin margin was the model's. With SPICE's rings through the SDF's
selector the low half came to 238 ps at tt and 579 at ss. With SPICE's rings
through SPICE's selector it is 573 ps and 1205.

## What this does not settle

The last pulse before a stop. When the window closes the ring is cut off at
whatever phase it is in, and the pulse that leaves can be any width. That
was swept at the fast corner on this build, through B13, down to 0.2 ps. At
tt and ss it has only been swept on the two-arm layout.

Wire resistance. The decks load each net of a path with its whole
capacitance at one point. The SDF has the wires' own delays, and on the
paths I looked at they add up to a picosecond or none, so that is not where
the two models part.

One ring's edge stands in for all 48. The stimulus is the hard macro's ring
with its extracted wiring, and the rings of the other two arms differ from
it by a few percent in speed and not in shape. The table of lows above
rescales the tap by each ring's period and that is arithmetic.

The generator's line for C00 to C03. Changing it changes four archived
decks and their rows, by the 4 ps above, and that is a decision about the
archive and not something to slip in with this.

And the rest of this sweep: 13 paths at ss, and the controls at both
corners.

## Mistakes

- I planned the evening on two minutes a deck, from the 18 September note.
  It was 2.3 at the start, four on the whole and nine at the worst, so what
  was meant to be both corners with their controls is one corner and part
  of the other.
- The first deck I ran took ten minutes, and I cut the plan to twenty decks
  on the strength of it. It had been sharing the machine with the timed
  run's last corner. The next ones took 2.3 and the plan went back up.
- I picked the first ten off the SDF's ranking, Arm A first. SPICE's own
  narrowest are Arm B's, at every corner. B11 and B08 were among the ten
  only because they had the widest gaps at ff.
- I wrote that the gate on C00 to C03 was the same gate with its inputs
  swapped, before running it. It is 7 ps at tt.

## Where it is, and landing

`mux3_tt/` is laid out like `sim/spice/gono/mux3/` without the controls: 48
decks, 48 ngspice logs, 48 reduced waveforms and `mux3_tt_validation.csv`,
145 files. `mux3_ss/` is the same for the 35 paths that ran.
`reduce_raw.py --verify` passed on both, every field of every deck the same
from the reduced file as from the full one.

`analyze_mux_sweep.py` printed "fast corner" over whatever it was given. The
copy here reads the corner off the decks. On `mux3/` it prints what it
printed before, character for character, and its csv is the archived one.

`selector_diag/` has what the middle of this note stands on: the probe and
the 1776 lines it printed, A05 with every node saved, the single cells, and
C00 both ways round.

It is not something the gate can hold yet. `verify_mux_archive.py` wants a
control beside every path, and the slow corner wants its other 13.
`README.txt` has the commands. On the PC's own install, the one the decks'
paths name, it is a few hours of machine time for all that is missing.

## 10 October: the line, and the rest of the sweep

The line the 5th left open is decided, and the generator ties that `o21a_2` the
way the chip does now. The sweep is finished too: the 13 paths at ss, the
blocked controls at tt and ss, and C00 to C03 again at all three corners.

Every path passes at all three corners and every control is silent, 96 of 96 at
tt and ss. The low half of the counter's clock is where the 5th left it, 573 ps
at tt and 1205 at ss, B11 both times.

### The line was not one line

On the 5th I wrote that C00 to C03 are the only four paths that use the table's
line for an `o21a_2` entered at B1. On the release build that is true. The
two-arm build sends all sixteen of Arm B through one, `_356_`, and it holds A2
high there as well.

I found that before anything ran, by writing every family of decks twice, once
with the old line and once with the new, and comparing them file by file:

    decks                                 written   changed
    mux3 at ff, tt and ss, release build  96 each   8 each, C00 to C03
                                                    open and blocked
    mux at ff, tt and ss, two-arm         64 each   16 each, B00 to B15
                                                    open
    boundary B00 at ff, two-arm           38        38
    boundary B15 at ff, tt, ss, two-arm   38 each   38 each
    boundary A05 two-arm, B13 release     38 each   none
    Arm B instance decks, tt, ff, ss      2 each    none

Every changed deck differs in one line, the `o21a_2`'s, with its first two pins
swapped.

So the line is right now, and what it costs is the baseline's archive. `mux/`
holds sixteen Arm B decks the generator no longer writes, and the B00 and B15
boundary csv files in `sim/spice/gono/` came from decks like them.

I did not run those again. The baseline is not the chip being made, and on the
release build the same swap moved four paths by 4 or 5 ps at ff, so I expect
about that on the baseline without having measured it.

They stay as they ran.

### Which input is high, three ways

The 5th's probe read every input of the 37 selector cells off the timed model
while each ring ran. That covers the release build only.

The second way is a throwaway that works the decode out of the netlist itself,
with every cell's function read from the PDK's own functional Verilog at
`ac7fb61`, the mux tables included. On the release build it agrees with the
probe on all 6938 levels it can compare; the other 214 are the running ring's
own nets, which it leaves unknown on purpose.

Against the decks it finds 612 ties on 48 open paths and 8 that disagree, A1
and A2 of `_447_` on C00 to C03. On the two-arm build it finds 388 on 32 and 32
that disagree, the same two pins of `_356_` on all of Arm B. Nothing else, on
either build.

The third is by hand, for `_447_`. A2 is `_196_`, the output of an `a221o_2`
whose C1 is `_115_`, which is an inverter on a buffered `~s2 & s3`. For indices
0 to 3 that is high whatever the arm.

A1 is `_195_`, an `a22o_2` of two Arm C rings that are stopped, and a stopped
ring's tap is low: its NAND holds `n[0]` high and fifteen inverters bring
`n[15]` down.

### A check, so it cannot happen quietly again

No control could have caught this. An `o21a_2` entered at B1 opens with either
input high, and a tie that opens the path the wrong way passes a control
exactly as the right one does.

`gen_mux_sweep.py --check-sides` does in the repo what the throwaway did. It
sets the selection register, leaves every other flop and the running ring
unknown, works out the level of each side input on each path and holds the
table to it.

612 ties on the release build and 388 on the two-arm one, and none disagree
now. It reads the netlist and nothing else, no PDK, so the gate runs it on both
builds.

Its cell logic is written by hand, 30 functions, the hold buffers among them.
The throwaway held all 30 to the PDK's models on every input, unknowns
included, 1404 cases, and none differ.

The selftest puts the old line back and wants exactly C00 to C03 flagged on the
release build and B00 to B15 on the two-arm one. It makes an `a22o_2`'s partner
input low and wants only that tie flagged. And it takes away one cell's logic
and wants the check to stop, not pass.

### What ran

The container was new, so the SPICE setup was made again the way the 5th made
it, ngspice 42 from Ubuntu with `fd_pr` at `403964d` and the cells at
`5a42fd0`. B11 at ff came back as the archived waveform to the last byte,
`814b17fa`.

Then 122 decks, two at a time on the container's two cores, from 13:51 to
16:36: B11 as the check, the eight changed decks at ff, C00 to C03 at tt, the
13 at ss, and the 96 controls. An open deck took 2.4 to 6.7 minutes and a
control 1.1 to 3.1, slower whenever anything else ran beside them.

The machine stayed up this time. The queue skips any deck whose log has
finished, so it would have picked up where it stopped.

The corrected C00 deck is the one the 5th wrote by hand with the two pins
swapped, byte for byte at tt and at ff, and its waveform at tt reduced is the
5th's to the byte. So the 5th's 7 ps is the archive's now.

One trap on the way.

`reduce_raw.py` copied a deck into the archive only when no deck of that name
was already there. Folding the eight new fast corner runs into `mux3/` left the
old decks beside the new logs and waveforms, and `verify_mux_archive.py` passed
it, because nothing compares an archived deck with anything.

I caught it by holding all 96 decks in the folder to what the generator writes
now, and copied the eight in by hand.

So `reduce_raw.py` replaces a deck now when the one already there differs, and
its selftest has a case for that which fails on the old rule. Folding the tt
runs in, it replaced the four C00 to C03 decks on its own. All 288 decks in the
three folders are what the generator writes now, every one checked.

### What came back

Every path passes at every corner, all 48 at each now. Every edge that left the
ring reached the counter's clock and the flop toggled on every one: 30 of 30 at
ff, 19 of 19 at tt, 9 of 9 at ss. All 96 blocked controls at tt and ss are
silent, as the 48 at ff were.

The 5th's table again, complete, with C00 to C03 tied as the chip has them:

    corner  arm  paths  rise delay   fall less rise  high at sel_ro  low
    ff      A    16     197-288 ps   161-186         697-722         400-425
    ff      B    16     240-349      159-209         695-745         377-427
    ff      C    16     174-316      90-163          626-699         423-496
    tt      A    16     321-464      269-305         1108-1144       608-645
    tt      B    16     392-562      260-341         1099-1179       573-654
    tt      C    16     292-515      140-264         979-1102        650-773
    ss      A    16     684-970      492-541         2139-2188       1247-1296
    ss      B    16     849-1176     451-582         2098-2230       1205-1337
    ss      C    16     619-1070     275-512         1922-2159       1276-1513

At ff and tt one number moved, the top of Arm C's rise delay, 319 to 316 and
523 to 515. C00 had the slowest Arm C rise at both and is quicker now. At ss
the thirteen new paths widen Arm C's ranges, the rise to 1070 ps on C00 and the
gap to 512 on C14, and B01 brings Arm B's gap down to 451.

The widest gap is still B11's at every corner, 209, 341 and 582 ps, and the
narrowest still C07's, 90, 140 and 275. With all 48 in at ss the five narrowest
lows are B11, B08, B15, A03 and B07. At ff and tt they are B11, B08, B15, B07
and B12, as on the 5th.

C00 to C03, the old tie against the new, in ps:

    path  corner   rise        fall        gap         low at sel_ro
    C00   ff       319   314   456   455   137   141   449   445
    C01   ff       274   269   403   402   129   133   457   452
    C02   ff       229   224   362   362   133   137   453   448
    C03   ff       266   262   397   397   131   135   455   451
    C00   tt       523   515   738   736   215   221   699   692
    C01   tt       453   445   657   656   204   211   710   703
    C02   tt       384   375   591   590   207   214   706   700
    C03   tt       438   430   647   646   209   216   704   698

All four go the same way. The rising edge gets quicker by 4 or 5 ps at ff and 8
or 9 at tt, the falling edge hardly moves, so the gap opens and the low shrinks
by 4 or 5 at ff and 6 or 7 at tt. At ss the four never ran with the old tie, so
there is nothing to set beside them.

### The low half, all 48

With each ring at its own SPICE speed, worked the way the 5th did it, the
narrowest at ss with all 48 in is still B11 at 1205 ps. So the 5th's table
stands as it was: 573 ps at tt, 1205 at ss and 377 at ff, 2.2, 2.1 and 2.7
times the library's limit, B11 each time.

By arm at ss the narrowest are A04 at 1274, B11 at 1205 and C10 at 1251. The
first and last are a picosecond under the 5th's 1275 and 1252, because I
rescaled from the csv's rounded tap columns and the 5th from the decks' period.
Of the new paths C14 comes closest, 1264 ps at its own speed, second in Arm C
after C10.

### Still not settled

The last pulse before a stop, at tt and ss, on this build. Only ff has been
swept, through B13. (Swept at both on 18 October, on 50 and 5 ps grids:
`docs/phaseG_boundary_tt_ss.md`.)

The baseline's sixteen Arm B rows of `mux_validation.csv`, and the B00 and B15
boundary csv files, made with the other input high.

Nothing in the gate holds an archived deck to the generator. Writing a deck
needs the cell library's pin order and CI has no PDK, so the trap above was
caught by hand and would be again.

### Mistakes, 10 October

- I took the 5th's "the only four paths that use it" as true of the repo when
  it was true of one build, and was one regeneration away from calling the fix
  one line. Writing every deck family both ways first is what showed the other
  sixteen.
- The first fold of the fast corner runs kept the old decks, and the archive
  check passed it.
- My throwaway stopped on the two-arm build at first. The PDK's `mux4` is a
  table, not gates, and I had only read gates; then it ran a cell's statements
  out of order. Neither reached a result.
- My first `--check-sides` took every cell whose name starts `dl` for a latch,
  and the hold buffers start that way too. Fixed before anything relied on it;
  no hold buffer sits in either build's decode today.

### Where it is

`sim/spice/gono/mux3/` with eight decks, logs and waveforms replaced and four
rows of its csv. `mux3_tt/` and `mux3_ss/`, 289 files each, laid out the same
way. `gen_mux_sweep.py` with the line, `--check-sides` and `--selftest`;
`reduce_raw.py` replacing a stale deck; `analyze_mux_sweep.py` reading the
corner off the decks. Two rows in `SIGNOFF.md`, a paragraph each in
`REPRODUCIBILITY.md` and the gono README, and ten lines in the gate.
