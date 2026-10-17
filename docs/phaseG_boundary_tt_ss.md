# The last pulse before a stop, at tt and ss

18 October 2026. The boundary sweep asks what the first counter flop does
with the ring's last pulse when the window closes in the middle of it. On the
release build it had run at ff only, through B13, the slowest rise of the 48
selector paths, on four grids down to 0.2 ps on 22 September. At tt and ss it
existed for the two-arm layout and its B15, and nowhere else. That was the
last selector item on the list before the shuttle closes.

It is run now at both, through B13 on the release build: the coarse grid at
each corner, then a 5 ps grid across the step. Every phase resolves the flop
to a rail and the count moves by one edge at most.

## The setup, and how I know it is the old one

ngspice 42 from Ubuntu's archive and a `sky130A` tree put together the way
`docs/phaseG_spice_rerun.md` describes, fd_pr at `403964d` and fd_sc_hd at
`5a42fd0`, in a fresh container.

`gen_boundary_sweep.py --build dualarm/build_armc --osc B13 --corner ff`
wrote all 38 decks of `bnd3/B13` again, byte for byte. Then phase 24, the
4 ps bump, ran again, and its reduced waveform came out the archive's own,
md5 `72826716`, with the log the same apart from the run's dates.

The library's minimum clock high for `dfrtp_2` was read again with
`check_pulse_width.py`: 77.5 ps at ff_n40C_1v95, 169.8 at tt_025C_1v80 and
353.8 at ss_100C_1v60, as on 4 August.

## What came back

    corner  phases  grid    step at the tap     narrowest at sel_ro  library
    ff        38    50 ps    68 to 104 ps        253 ps               77.5
    ff        13     5 ps    75 to 82 ps         202 ps
    tt        38    50 ps   108 to 170 ps        422 ps              169.8
    tt        13     5 ps   115 to 122 ps        231 ps
    ss        76    50 ps   230 to 295 ps        686 ps              353.8
    ss        13     5 ps   258 to 264 ps        507 ps

The ff rows are the 22 September archive, for comparison. A step written
"115 to 122" means the 115 ps pulse at the tap was lost and the 122 ps one
reached the flop.

    corner  rise    fall    asymmetry   fixed time   period
    ff      350     521     171 ps      +170 ps      1122.0 ps
    tt      563     846     283         +281         1752.5
    ss      1177    1666    489         +483         3435.4

At every corner the selector adds a fixed time to a high level rather than
scaling it. On the coarse grids that leaves 6 ps unexplained at tt and 14 at
ss, where a fixed fraction leaves 95 and 202, and the fixed time is the
asymmetry to within a few picoseconds, which is what the asymmetry argument
says it should be.

The 5 ps grids say nothing either way. They sit on the threshold, where the
chain squeezes the pulse and neither model holds: at tt the fraction fits
there, 27 ps against 42, at ff the fixed time does, 12 against 14, and at ss
the analyser will not call it.

At ff the step is 76 ps of a 1122 ps period, 6.8 percent. At tt it is between
115 and 122 of 1752.5, 6.6 to 7.0 percent, much the same. At ss it is between
258 and 264 of 3435.4, 7.5 to 7.7 percent, which is not, so the share is not
fixed either and at ss the step grows by more than the ring slows. On the
baseline's B15 it was nearer a tenth. The path matters as well as the ring.

## Against the library

The narrowest pulse at `sel_ro` is a property of the grid and not of the
circuit, as at ff. Each finer grid finds a narrower survivor, because right
at the threshold the chain thins the pulse, and the closer the window closes
to that point the thinner it gets. At tt the 5 ps grid already found 231 ps
where the coarse one found 422.

So the coarse figures are not floors, and the 5 ps ones are not either. One
grid step from the edge the flop still got 231 ps at tt and 507 at ss, over
the library's 169.8 and 353.8, but at ff the same 5 ps grid found 202 and the
0.2 ps one found 80, against 77.5. A finer grid would find narrower pulses at
tt and ss too.

That is the same answer ff gave in September. The last pulse cannot be kept
above a minimum width and it does not need to be. It is the last pulse before
a stop, the flop was simulated at transistor level, and whichever way it
resolves the count moves by one, which the three-sample handshake already
absorbs.

## Against the baseline

The two-arm layout's B15 at tt lost a 172 ps pulse and kept 224, at ss lost
353 and kept 404, on the same 50 ps grids. B13 on the release build keeps
narrower pulses at both corners, 170 ps at tt and 295 at ss on those grids.
Its step sits earlier, as it did at ff, where B15 gave up near 100 ps and
B13 near 76.

Those B15 decks carry the old `o21a_2` tie. Put right on the release build on
10 October it moved four paths by 4 to 9 ps, which is small next to a 50 ps
grid, so the comparison stands as it is.

## The archive

`sim/spice/gono/bnd3/` gains four folders, each with every deck, its log and
its waveform reduced by `reduce_raw.py --kind bnd`, which checks the reduced
waveform against the full one field by field before it keeps it:

    B13_tt        38 decks   boundary_validation_B13_3arm_tt.csv
    B13_tt_5ps    13 decks   boundary_validation_B13_3arm_tt_5ps.csv
    B13_ss        76 decks   boundary_validation_B13_3arm_ss.csv
    B13_ss_5ps    13 decks   boundary_validation_B13_3arm_ss_5ps.csv

The gate rebuilds all four csvs from the reduced waveforms and diffs them, so
eight more lines and the manifest's count with them. A second reader written
for the purpose, its own parser and its own crossings, agrees with the
analyser on the phases either side of each step: which pulse arrives, how wide
it is at the tap and at `sel_ro`, how many times the flop toggles and where it
ends up.

## Mistakes on the way

The first run had both cores taking a deck each, which is what the 10 October
sweep did. Here that came to 100 s a deck where one deck alone takes 33 s, so
two at a time was three times slower, not twice as fast. I lost two half-run
decks twice finding that out. The first time I stopped the workers to give
each ngspice one thread, which was slower again. The second time I put the
threads back and went to one deck at a time. All four were run again from the
start, and the queue skips a deck only when its log ends the way a finished
ngspice run ends.

## Not settled

The boundary through the other 47 paths at any corner. B13 is the slowest
rise of the 48 and every one carries all its edges in the steady sweep, but
none of them has been swept at the boundary.

At tt and ss there are no 1 ps or 0.2 ps grids. They would find narrower
pulses than the 5 ps ones did, as at ff. How narrow is not known.
