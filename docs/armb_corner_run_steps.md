# Item D, Arm B at ss and ff

*One of the run notes indexed in [`run_steps.md`](run_steps.md), which says what
they are and what they are not evidence of. Paths are left as they were run.*

Written 2026-08-09. Nothing below the command list is a result yet. The two runs
have not happened.

## What item D asks

The corner table in `SIGNOFF.md` and in section 5.4 of the paper is Arm A. I
relabelled it on 08-08 so it stops claiming to be the whole chip, and added a row
saying plainly that Arm B has no corner sweep. That is honest but it is thin. Arm
B is half the experiment, and what exists for it at corners is one instance,
B15, at ss and tt, plus the sixteen nominal per-instance runs from item 8.

So this is the last piece of new evidence on the open list. Run all sixteen Arm B
instances at the slow and fast corners, with their real enable and output routes,
and the corner table covers both arms.

## The estimate was wrong and I want to say why

I put item D at one and a half days, half of it writing a new generator, because
`gen_dualarm_decks.py` is Arm A only and says so in its sixth line. That is true
and it is also beside the point. The Arm B decks do not come from that file. They
come from `gen_instance_decks.py`, which I wrote for item 8 on 08-03, and which
has taken a `--corner` argument since the day it was written. So has
`analyze_instance.py`, which already carries the control frequency for all three
corners.

I estimated from the file I had been staring at rather than the file that does
the work. The lesson is the same one from 08-07, when I summarised a corner row
without opening the generator behind it. Before estimating the cost of building
something, open the thing that would build it.

What is actually left is two simulator runs and the writing. Call it half a day
of mine plus a few hours of machine time.

## What I checked before believing that

The corner argument existing is not the same as the corner argument working, and
only tt was ever run. `test_instance_corners.py` is new today and answers that
offline. Twenty-five checks, no PDK, no ngspice, nothing to install.

The important one is the third from last. It builds all three decks through the
real code path with the two SKY130 paths stubbed out, and compares them. The
circuit is byte for byte the same at all three corners, all 73755 characters of
it. Every line that differs between tt and ss is one of six things: the library
section, the temperature, the supply, the enable pulse amplitude, the transient
window, and the measurement thresholds, which follow the supply to 0.9, 0.8 and
0.975 volts. Nothing else moves. That is what a corner is supposed to change, and
it is now a test rather than my opinion.

The checks also confirm that the two constant tables are the archived numbers.
`CONTROL_MHZ` matches the Arm A control logs in `dualarm/build_current` at all
three corners, and the Arm A dispersion figures the report compares against match
the parasitic logs.

## Two things I fixed on the way

The Arm A spread the report compared against was one number, 5.84%, the
distributed-RC result from item 7 at tt. Reading an ss run against a tt number is
sloppy, so it is a table now. There is no distributed Arm A run at ss or ff, so
those two entries come from the lumped corner decks, 5.459% and 5.559%. Both are
smaller than 5.84, which means the corner comparisons are the stricter ones, not
the easier ones. Worth knowing on its own: Arm A's spread barely moves with
corner. 5.534, 5.459, 5.559 across tt, ss and ff. Layout dispersion is a property
of the layout, which is what you would hope, and now I can show it.

The analyzer computed one period as `tp / 20`, twenty being how many periods a
full run measures over. A smoke run measures over five. On a smoke log that made
the period come out four times too short and could fail a deck that is fine. It
reads the period from the frequency the deck itself computed now, which is right
for both. I checked this the only way worth checking: I put the old line back in
a scratch copy, and the new test case fails on it.

The generator has a `--tstop-ns` argument now, and it refuses a window too short
to hold the last edge it measures. This matters at ss, where the default window
is 300 ns and the run time follows the window. If the window is short ngspice
does not complain. It runs the whole transient, leaves the measurement out of the
log, and the report reads the ring as dead. At ss that mistake costs hours.

## What I expect, written down before the run

The control ring. Both corners should land within half a percent of the archived
Arm A control, which is 323.1405 MHz at ss and 987.9480 at ff. The deck steps at
1 ps and those archived runs stepped at 5 ps, and at tt that difference read
+0.171%. A fixed timestep is a smaller slice of a longer period, so the shift
should be smallest at ss and largest at ff. Taking it as a square law gives
+0.044% at ss and +0.414% at ff, so 323.28 and 992.04 MHz. The sign is the
prediction I care about. If either corner comes back below its archived value,
the timestep story is wrong and I want to know that.

The reference ring. Arm B's loaded-to-control ratio is 0.8990 at tt. Arm A's own
ratio moved +0.26% at ss and -0.21% at ff, so scaling by that gives 291.4 MHz at
ss and 890.0 at ff. I would accept anything within a percent of those.

The sixteen instances, which is the actual question. I expect them flat again.
At tt they spread 0.0025% peak to peak, 2330 times below Arm A. The reason is
structural rather than numerical: both routes sit outside the oscillator loop,
the loop is the same extracted macro in all sixteen copies, and a corner changes
every device in the deck by the same factor. So I predict below 0.01% at both
corners. Anything above 0.62%, ten times the per-ring mismatch sigma, would mean
integration is doing something the tt run could not see, and would have to go in
the paper as a limitation.

Route delay and receiver slew should scale with the period. From tt's 0.1 to
4.5 ps of route delay, ss should give roughly 0.2 to 8.8 ps and ff 0.06 to
2.9 ps. Receiver edges from 62.6 to 318.2 ps should become 123 to 624 at ss and
40 to 204 at ff.

One more, and this one is a trap I am setting for myself. At tt the correlation
between output route capacitance and frequency came out -0.160. On sixteen points
that is nothing, and I have been treating it as nothing. If it is really nothing,
its sign should wander between corners. If it keeps its sign at both and grows at
ss where the delays are larger, then it is a real effect I dismissed, and the
flat-frequency claim needs qualifying. The correlation with receiver edge, +0.999
at tt, is geometry and should stay above +0.99 everywhere.

## The commands

All of this is WSL Ubuntu, not PowerShell. Do the exports first, in the same
window, or the generator will stop and tell you `PDK_ROOT` is not set.

The path below is the one every run on this machine has used, including the tt
run of these same decks in `instance_run_steps.md`. I first wrote `$HOME/.volare`
here from memory and it does not exist. If it ever moves, find it with
`find /home/pc -maxdepth 6 -name sky130.lib.spice` and set `PDK_ROOT` to the
directory two levels above `libs.tech`.

Step 1. Open WSL and set the environment.

    export PDK_ROOT=/home/pc/pdks && export PDK=sky130A

Step 2. Go to the deck folder.

    cd "/mnt/d/silicon/silicon chip/sim/spice/gono"

Step 3. Run the offline checks first. This needs no PDK and takes a second. All
25 should say ok.

    python3 test_instance_corners.py

Step 4. The analyzer's own selftest, also offline. Fourteen planted faults.

    python3 analyze_instance.py --selftest

Step 5. Now the slow corner, and start with the smoke deck. It measures over five
periods instead of twenty in a 60 ns window, so it finishes quickly and tells you
whether every ring starts at 1.6 volts and 100 degrees.

    python3 gen_instance_decks.py --corner ss --smoke --output-dir /tmp/inst

Step 6. Run it. This one should be minutes, not hours.

    python3 ../run_ngspice.py /tmp/inst/armb_instances_ss_smoke.spice --log /tmp/inst/armb_ss_smoke_out.txt

Step 7. Read the smoke frequencies. Send me this output before going on.

    grep -E "^f_(c|r)" /tmp/inst/armb_ss_smoke_out.txt

If `f_r` comes back near 2.9e+08 the prediction is holding and the real window
can be 140 ns instead of 300, which roughly halves the run. If it comes back
lower, tell me and I will size the window from your number instead of mine.

Step 8. The real ss deck. Change 140 only if I tell you to after step 7.

    python3 gen_instance_decks.py --corner ss --tstop-ns 140 --output-dir /tmp/inst

It prints a line saying how much margin the window carries. It should say about
1.5x. If it refuses outright, the frequency is far off the prediction and that is
itself the news.

Step 9. The long one. Expect a couple of hours. It is finished when the shell
gives you the prompt back.

    python3 ../run_ngspice.py /tmp/inst/armb_instances_ss.spice --log /tmp/inst/armb_instances_ss_out.txt

Step 10. Read it.

    python3 analyze_instance.py --log /tmp/inst/armb_instances_ss_out.txt --csv /tmp/inst/instance_parasitics.csv --corner ss

Step 11. The fast corner. The default 80 ns window is already 2.5 times what it
needs, so no smoke run and no `--tstop-ns` here.

    python3 gen_instance_decks.py --corner ff --output-dir /tmp/inst

Step 12. Run it. This one should take about as long as the tt run did.

    python3 ../run_ngspice.py /tmp/inst/armb_instances_ff.spice --log /tmp/inst/armb_instances_ff_out.txt

Step 13. Read it.

    python3 analyze_instance.py --log /tmp/inst/armb_instances_ff_out.txt --csv /tmp/inst/instance_parasitics.csv --corner ff

## What to send back

The whole output of steps 10 and 13, not the summary line. The per-instance table
is where the answer is, and I want the route delays and slews as well as the
frequencies.

Do not copy anything into the repository yet. The logs go in
`sim/spice/gono/armbcorner/` and get reduced first, the same way the selector
sweep did, but I want to see the numbers before deciding what is worth keeping.

If a ring is missing from the report, send me the log anyway. A missing ring at
ss means the window was short, and the fix is one number.
