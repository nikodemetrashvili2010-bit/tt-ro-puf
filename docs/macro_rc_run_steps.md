# Running the Arm B macro distributed-RC comparison

*One of the run notes indexed in [`run_steps.md`](run_steps.md), which says what
they are and what they are not evidence of. Paths are left as they were run.*

Item 7 rebuilt all sixteen Arm A oscillators from the SPEF's real network and
the answer moved: every ring ran slower, and the dispersion went from 5.55 to
5.84 percent. The Arm B macro never got that treatment, so the 569.5 MHz this
project quotes for Arm B is a lumped number sitting next to Arm A numbers that
are not. `SIGNOFF.md`, item 7 and item 8 all record it as owed. These are the
steps to close it.

Everything except the two ngspice runs is already done and checked. The
generator is `sim/spice/gono/gen_macro_rc_deck.py` and its thirteen offline
checks pass with no PDK and no simulator.

## What I expect to get, written down first

I am writing this before running anything, the same as item 8, because a
prediction made afterwards is worth nothing.

**The lumped deck should reproduce 569.5 MHz.** That is the number
`gen_macro_deck.py` produced and it is the same model on the same SPEF, so if my
rebuild disagrees by more than about two tenths of a percent then the rebuild is
wrong and nothing else in the run means anything. This is the check I care about
most. One difference is deliberate: my decks step at 1 ps over 140 ns where
`gen_macro_deck.py` stepped at 5 ps over 80 ns, so a small gap is expected and a
large one is not.

**The distributed deck should come out near 564 MHz.** Two ways of guessing put
it in the same place. Fitting the Arm A shift against ring load over the sixteen
oscillators gives shift = -0.4147 - 0.03961 x cap, and the macro's ring carries
11.01 fF, which predicts -0.85 percent. Taking Arm A's plain mean shift instead
gives -0.97 percent. So 564.0 to 564.7 MHz, and I will call the prediction 564.3.

Worth saying that the macro is not an extrapolation. At 11.01 fF it sits inside
Arm A's range of 10.86 to 17.04 fF, near the light end, so the fit is being used
where it was fitted. What is an extrapolation is the layout: the macro is
hardened and compact and Arm A is placed in open fabric, so the relationship
between load and shift does not have to carry across. The Arm A fit is weak
anyway, r = -0.430.

**The direction is not in doubt.** Both changes slow the ring. The series
resistance is new load the lumped model dropped, and a coupling capacitor
between two nodes swinging in antiphase presents about twice its value to each
side, where the lumped model grounds it and presents one times. If the
distributed deck comes out faster than the lumped one, something is wired
backwards and I should not write the result up.

**What this cannot do.** It cannot move item 8's per-instance comparison by even
a little. All sixteen Arm B copies carry the identical internal model by
construction, so any shift here shifts all sixteen together and the 0.0025
percent spread between them is untouched. It also cannot touch Arm A. This
changes one number and the honesty of putting it next to Arm A's.

## The accounting, which is already checked

`python3 sim/spice/gono/gen_macro_rc_deck.py --report` gives the extraction, and
these numbers are already verified offline:

    ring capacitance n[0..30]         11.01 fF
    all 35 nets, lumped total         15.33 fF
    distributed total                 14.27 fF
      of which grounded               13.21 fF
      of which coupling                1.06 fF
    resistors                            37
    grounded capacitors                  72
    real coupling capacitors             25
    couplings grounded, no partner        0
    second listings dropped              25

The two totals are not supposed to match, and the reason is the trap item 7 fell
into. IEEE 1481 records a coupling capacitor under both of the nets it joins,
with the full value in each place, so adding up every net's `*D_NET` total
counts each coupling twice while the distributed deck builds it once between the
two moving nodes. The gap between the totals therefore has to equal the coupling
total exactly, and it does, to within two parts in ten million. That identity is
the check, not a ratio near one.

Finding it cost me a real mistake in this script. The books first came out 1.54
fF short, which is ten percent of the extraction. The cause was that a SPEF
writes a top-level port as a bare name with no instance number and no colon, so
`en` and `out` were not being recognised as nodes at all, and both their
capacitance and their series resistance to the cell they reach were being
dropped. The books refusing to close is the only reason I looked. A ratio test
with a one percent tolerance would have passed a ninety percent-correct deck.

Two other things the report already settles. Nothing had to be grounded for want
of a partner, which is the payoff of the macro being a closed block: Arm A had to
ground coupling to between 4 and 72 outside nets per ring, and here there are
none. And no resistor was dropped for having both ends on the same node, which
was 2 before the port fix and is 0 now.

## Steps

Run these in the container, from the repo root, with `PDK_ROOT` set.

1. Confirm the generator still passes offline. This needs no PDK, so it works
   anywhere.

        python3 sim/spice/gono/gen_macro_rc_deck.py --selftest
        python3 sim/spice/gono/gen_macro_rc_deck.py --report

   Thirteen of thirteen, and the report should print the numbers above. If it
   does not, stop, because the SPEF has changed underneath this.

2. Write the two decks.

        python3 sim/spice/gono/gen_macro_rc_deck.py --output-dir /tmp/macrorc

   It prints the element counts for each. Expect 72 grounded caps, 25 real
   couplings and 37 resistors in the rc deck, and 35 lumped caps in the other.

3. Run both. They take a couple of minutes each.

        python3 sim/spice/run_ngspice.py /tmp/macrorc/ro_macro_lumped.spice \
            --log /tmp/macrorc/ro_macro_lumped_out.txt
        python3 sim/spice/run_ngspice.py /tmp/macrorc/ro_macro_rc.spice \
            --log /tmp/macrorc/ro_macro_rc_out.txt

4. Read the two frequencies off the tail of each log, on the `f = ` line.

        tail -n 5 /tmp/macrorc/ro_macro_lumped_out.txt
        tail -n 5 /tmp/macrorc/ro_macro_rc_out.txt

5. Check the lumped number against 569.5 MHz before believing anything else.

6. Archive both logs and both decks in the repository, unlike the RC, mux and
   boundary sweeps, whose logs only ever lived in `/tmp`.

        mkdir -p sim/spice/gono/macrorc
        cp /tmp/macrorc/ro_macro_*.spice /tmp/macrorc/ro_macro_*_out.txt \
            sim/spice/gono/macrorc/

   The decks regenerate byte for byte from the SPEF, so the logs are the part
   worth keeping, but keeping both makes the folder self-contained.

## Optional, if the nominal run behaves

The corners are already wired in. `--corner ss` and `--corner ff` write their own
decks with the right section, temperature and supply. Item 7 only ever did Arm A
at nominal, so doing the macro at three corners would go further than the debt
requires. Worth it only if the nominal result is clean and there is time before
the 2026-09-07 deadline.

## What to write up afterwards

Done 2026-08-07, and the write-up landed the same day. The result went into item
7 of `docs/hardware_todo.md`, and the paragraph that used to say the macro had
its own SPEF and had not been redone this way was cleared on 2026-08-08, a day
later than it should have been. It also changed the Arm B frequency in
`docs/gono_results_writeup.md` and in the README, both of which said 569.5 MHz
in several places, and those had to say which model each number comes from
rather than being silently replaced.

Say plainly that the per-instance comparison is untouched and why. And if the
lumped deck fails to reproduce 569.5, write that down too rather than tuning
the deck until it agrees.
