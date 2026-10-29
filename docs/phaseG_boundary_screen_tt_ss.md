# The last pulse before a stop, every path at tt and ss

29 October 2026. The boundary sweep asks what the first counter flop does
with a ring's last pulse when the window closes in the middle of it. On 26
October all 48 selector paths were screened at ff. At tt and ss two had
been run, B13 since 18 October and B00 since the 27th, and the other 46 had
only the steady sweep behind them there.

All 48 have both now. Every phase on every path leaves the flop on a rail,
and the count moves by one edge at most.

## How

The same way as at ff (`docs/phaseG_boundary_screen.md`). The first eighty
lines of every boundary deck are the same bytes, the macro ring, the enable
and the tap, so at one enable phase every deck hands its chain nearly the
same last pulse. The screen holds the phases and moves the path.

The phases come off B13's own grids at each corner:

    corner  enable falls             last high at the tap, on B13
    tt      30.120 to 30.180 ns,     63, 88, 108, 129, 148 ps
            15 ps apart
    ss      33.125 to 33.275 ns,     93, 177, 210, 251, 289, 323 ps
            30 ps apart

Finding the bottom took five probe decks on B13, and a first ss list 35 ps
apart that started at 148 ps, too high, and was thrown away. At tt the
enable falling at 30.105, 30.110 or 30.115 ns stops the ring before it rises
again, and the last pulse is then its previous full one, 842 ps. 30.120 is
the first fall on a 5 ps grid that cuts a pulse at all. At ss 33.115 does
the same, 1654 ps, and 33.125 gives 93. None of those decks is archived.

At the top, each list reaches the first pulse B00 keeps on its own 5 ps
grid, since B00 needed the widest pulse of the 48 at ff.

Two paths are held to their archives this time, B13 and B00, since both
have 5 ps sweeps at tt and ss. S05 wants their shared rows back field for
field: three each at tt, two of B13's and one of B00's at ss. All nine came
back.

`boundary_screen.py` takes `--corner` now, for the supply, the phase count
and those rows, and `--control` as often as there are controls. Its ff
output is what it was, line for line, and the selftest has three more
cases, two controls at once. 10 of 10.

## tt

    arrived  paths  step at the tap      which
    01111     24    between 63 and 90    A02, A03, A05 to A15, B11, C01 to
                                         C03, C06, C09 to C12, C14, C15
    00111     11    between 88 and 110   A00, A01, A04, B04, B07, B08, B15,
                                         C05, C07, C08, C13
    00011      9    between 108 and 130  B02, B03, B06, B10, B12, B13, B14,
                                         C00, C04
    00001      4    between 129 and 148  B00, B01, B05, B09

No path passes the 63 ps pulse and every path keeps the 148 ps one, so every
step is bracketed. 240 phases, every one at 0.000 or 1.800 V at the end.
The pulse at the tap agrees across the 48 to 2 ps at every phase.

The narrowest high that reached `sel_ro` is 178 ps, on C12 at the 89 ps
phase, over the library's 169.8 for `dfrtp_2` at tt_025C_1v80. The widest
first arrival is 393 ps, on B09.

The order holds from ff. Every path sits in the class it had at ff or the
next one up, and no two paths swap: the 28 that kept the 54 ps pulse at ff
are the 24 that keep 89 at tt plus A00, B07, C07 and C13, and the ten Arm B
paths that needed 82 at ff are B13 and six others needing 129 at tt, with
B01, B05 and B09 joining B00 at 148.

## ss

    arrived  paths  step at the tap      which
    011111     9    between 92 and 180   A06, A10, A11, A14, A15, C03, C10,
                                         C14, C15
    001111    20    between 176 and 214  A00, A02, A03, A05, A07 to A09,
                                         A12, A13, B07, B08, B11, C01, C02,
                                         C06, C07, C09, C11 to C13
    000111     8    between 210 and 254  A01, A04, B04, B14, B15, C00, C05,
                                         C08
    000011    10    between 251 and 292  B01 to B03, B05, B06, B09, B10,
                                         B12, B13, C04
    000001     1    between 289 and 323  B00

Again every step is bracketed, nothing passing the 93 ps pulse and
everything keeping the 323. 288 phases, every one at 0.000 or 1.600 V at
the end, and the pulse at the tap agrees across the 48 to 4.0 ps at every
phase, inside the 5 ps S06 allows.

B00 needs the widest pulse here on its own; B01, B05 and B09, which
joined it at tt, drop back to B13's class. Between ff and tt, and between
tt and ss, no two paths swap places. Between ff and ss one pair does: B14
needed more than C04 at ff, and at ss C04 needs more than B14. Neighbouring
corners keep the order and the ends of the range do not quite, which says
again that the path counts as well as the ring, and differently at each
corner.

The narrowest high that reached `sel_ro` is 226 ps, on C07 at the 211 ps
phase. C07 is the shortest chain of the 48, three cells, and that pulse is
under the 353.8 ps the library gives `dfrtp_2` at ss_100C_1v60. The flop
resolved it, to a rail, with the count moving by one. Next narrowest is
B03's 365. The widest first arrival is 707 ps, on B11.

## Against the library, and the baseline

At tt the narrowest pulse that reached `sel_ro` on the screen, C12's 178
ps, is narrower than anything B13's or B00's 5 ps grids found there, 231
and 290, and still over the library's 169.8 for `dfrtp_2`. At ss C07's 226
is under the library's 353.8, and the flop took it, as it took B00's 69 ps
at ff under 77.5. None of that is a margin either way. Each finer grid
finds a narrower survivor, and the flop has resolved every one of them so
far. The last pulse is the last before a stop and either answer costs one
count, which the three-sample handshake takes.

## The archive

`sim/spice/gono/bnd3/screen_tt/` and `screen_ss/`, one folder a path, each
deck with its log and its waveform reduced by `reduce_raw.py --kind bnd`,
which reads both copies through the analyzer and keeps the reduced one only
if every field matches. All 48 at each corner verified that way. The gate
rebuilds `boundary_screen_tt.csv` and `boundary_screen_ss.csv` from them
and diffs both, four more lines.

16 MB at tt and 14 MB at ss. Every deck ran one at a time, about 30 s
each on its own and 26 at the quickest, 528 in all.

## Mistakes

- The background job holding the queue hit its two-hour limit at 01:47
  with 39 of the 48 tt paths done, and nothing restarted it until 07:50.
- Waiting for the tt queue to end, I grepped for "queue done: tt" and it
  matched the line the B13-only probe had left the night before, so the
  wait returned at once.
- A one-ring Arm B deck run beside the queue made both about three times
  slower, 69 to 213 s a deck instead of 30, the same thing 18 October's
  note already says about two decks at once.

## Not settled

- Finer grids at tt and ss for any path but B13 and B00. Nothing below 5 ps
  has run at either corner on any path.
- The pulse sitting exactly on a path's threshold, which no grid this
  coarse lands on, at any corner.
