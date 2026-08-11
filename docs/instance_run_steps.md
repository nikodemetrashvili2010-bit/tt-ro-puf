# Item 8, the per-instance Arm B run

*One of the run notes indexed in [`run_steps.md`](run_steps.md), which says what
they are and what they are not evidence of. Paths are left as they were run.*

Written 2026-08-03. The decks are built and checked. The simulation itself is
still to run, so nothing below the command list is a result yet.

## What item 8 asks

Arm B is sixteen copies of one hardened macro. Everything I have said about it so
far comes from simulating that macro once, and for the inside of the ring that is
fine, because the sixteen copies are the same GDS stamped down sixteen times. The
top extraction proves it in the bluntest way possible: it contains no net that
lives inside a macro at all. The extractor cannot tell the copies apart.

The outside is a different story and I have never checked it. Each copy sits
somewhere different on the tile, with its own enable route arriving and its own
output route leaving. Those thirty-two nets are in the top SPEF. On the enable
side they run from 1.00 to 12.81 fF, on the output side from 2.89 to 29.46 fF. A
factor of ten either way. So "Arm B is one number" is currently an assumption
about the part of the layout the extraction can actually see, and this is the
test of it.

## The deck

One file, eighteen rings, one ngspice run.

The control has the macro topology and no capacitance anywhere. Its frequency has
to land on the same value every other control deck in this project returns at the
same corner. That is the thing that says the deck was built right, rather than
merely built consistently with itself.

The reference has the macro plus its own internal extraction and nothing
external. This is the existing Arm B model, the one behind the number in the
paper.

Then the sixteen. Each one carries the reference model unchanged, and I checked
that: the internal cells and all thirty-five internal capacitors are identical
across all sixteen and identical to the reference, element for element. On top of
that each gets its real enable driver from the netlist, its real enable route,
its real output route, and the real selector cell the route ends at. Both routes
are built as the extraction wrote them, with the series resistors and the
per-node capacitance, not lumped onto one node.

Because the reference sits in the same file as the sixteen, none of this depends
on the absolute frequency. That number moves by about 0.2% with the transient
timestep, which is why I stopped quoting it to four digits. Every ring in one
deck sees the same timestep, so a difference between one instance and the
reference is a difference in the circuit and not in the solver.

One modelling choice worth defending. Coupling that leaves a route is grounded,
and here that is not a simplification, it is the right answer. The RTL drives one
Arm B enable at a time:

    assign armb_en[i] = en_window & (active_sel == SB[SEL_W-1:0]);

so while ring i is measured the other fifteen are stopped and their outputs sit
static, and every enable except one is static too. A quiet neighbour is exactly
what a grounded capacitor represents. There are 29 coupling capacitors joining
two Arm B boundary nets and this is why all of them are grounded.

## What I expect, written down before the run

I expect the frequency to be flat. Both boundary nets sit outside the oscillator
loop. The loop is the enable NAND plus thirty inverters, and the only cell
capacitance that touches it from outside is the tap buffer's input on n[15].
The output route cannot reach that except through two buffers in series, each
passing a little of its output loading back to its own input through the
gate-drain overlap. That is a second-order path twice over.

Putting a number on it: I would be surprised if the sixteen spread more than
0.01%. Arm A's own regression says frequency moves 0.890% per fF of ring load, so
0.01% needs about 0.011 fF of change on n[15], and I do not believe two stages of
overlap capacitance move it that far when the load behind them changes by 27 fF.

Which means the result probably sits close to the simulator's own noise floor,
and that is the interesting part, because there is a clean way to tell the two
apart and the analyzer already computes it. If the scatter is numerical, it will
not correlate with the output route capacitance. If the Miller path is real, it
will, and the sign has to be negative: a heavier route means a slower ring. A
strong positive correlation would mean something is wired the wrong way round and
I should stop and read the deck rather than write up the number.

What would genuinely surprise me is anything above 0.62%. That is ten times the
per-ring mismatch sigma from the Monte Carlo work, and above it the integration
spread stops being a footnote and becomes a limitation the paper has to carry.
Above 5.84%, Arm A's own dispersion on this build, the experiment would be in
trouble. Both thresholds are in the analyzer as constants so I cannot quietly
move them after seeing the data.

The second thing this run gives me is not about frequency at all. Item 3 found
that Arm B drives about seventeen times the output load Arm A does, and said any
reliability comparison between the arms has to account for it. The deck measures
the route delay and the edge rate at the selector input for all sixteen, so after
this I have that spread as a measured number instead of an argument.

## Running it

All of this is WSL. Nothing here is PowerShell.

### 1. The environment, every new terminal

    source ~/ttsetup/venv312/bin/activate

    export PDK_ROOT=/home/pc/pdks

That is the volare PDK, not the ciel one LibreLane uses. The ciel tree at
`~/ttsetup/pdk` has no `libs.tech/ngspice`, so every deck generator in this
project points at `/home/pc/pdks` instead. I got this wrong once and the
generator stopped with a missing-file error, which is the right way for it to
fail.

    export PDK=sky130A

### 2. Build the decks

    cd "/mnt/d/silicon/silicon chip/sim/spice/gono" && python3 gen_instance_decks.py --output-dir /tmp/inst

It should print the ring capacitance as 11.01 fF, the enable routes as 1.00 to
12.81, the output routes as 2.89 to 29.46 with a mean of 14.46. Those three
numbers come from files I did not write and match what item 3 recorded
independently, so if any of them is different the build snapshot has changed
under me and the rest of the run is meaningless.

### 3. The short run first

Twenty nanoseconds instead of eighty, five periods measured instead of twenty.
This is only to prove the deck elaborates and that all eighteen rings start.

    cd "/mnt/d/silicon/silicon chip/sim/spice/gono" && python3 gen_instance_decks.py --output-dir /tmp/inst --smoke

    cd /tmp/inst && python3 "/mnt/d/silicon/silicon chip/sim/spice/run_ngspice.py" armb_instances_smoke.spice --log smoke_out.txt

Time this one. Eighteen rings at a one picosecond step is more than any deck in
this project so far, and the real run is four times longer, so the smoke run is
what tells me whether to leave the long one going and walk away.

    grep -c "^f_" /tmp/inst/smoke_out.txt

Should be 18. If it is less, some ring did not produce a frequency and I want to
know that now rather than after an hour.

### 4. The real run

    cd /tmp/inst && python3 "/mnt/d/silicon/silicon chip/sim/spice/run_ngspice.py" armb_instances.spice --log armb_instances_out.txt

### 5. Read it

    cd "/mnt/d/silicon/silicon chip/sim/spice/gono" && python3 analyze_instance.py --log /tmp/inst/armb_instances_out.txt --csv /tmp/inst/instance_parasitics.csv

Four things have to hold before the spread means anything, and the analyzer
checks all four rather than trusting them. The control has to land on 633.640
MHz within one percent. Every one of the eighteen rings has to have produced a
result, since a measurement ngspice could not make is absent from the log and not
zero. Every output route has to show the same period at both ends, because a
resistor and capacitor network cannot change a period. And the widths have to
close: the high level gained along the route has to equal the fall delay minus
the rise delay, which is arithmetic rather than physics.

That last one is there because of item 2. It shipped a wrong number for two days
by comparing a high level against a low one, and every synthetic check it had
passed while the mistake sat in the middle of the analysis. This time the
identity is checked directly and one of the eight planted faults in
`analyze_instance.py --selftest` is exactly that failure.

### 6. Keep the outputs

    cp /tmp/inst/instance_parasitics.csv /tmp/inst/armb_instances_out.txt "/mnt/d/silicon/silicon chip/sim/spice/gono/"

## What this does not cover

Nominal corner only. Nothing here says what the routes do at the fast corner,
though the deck takes `--corner ff` and it is one more run if the nominal result
turns out to be interesting.

Lumped internals. The macro's own extraction is still net totals hung on single
nodes, the way it has always been. Item 7 rebuilt Arm A from the real network and
found the dispersion moved from 5.55% to 5.84%, so the same treatment of the
macro is still owed. It cannot change this comparison, since all sixteen carry
the identical internal model, but it does mean the absolute Arm B frequency is
still a lumped number.

The enable route is in the deck but its real job is untested. Enable is static
through the whole measurement window, so it cannot touch the frequency. What it
does touch is how the ring starts and stops, and that is item 1's boundary sweep,
which was run against Arm A's tap and not through a real Arm B enable route. Not
a gap I think matters, but it is a gap.

Supply is ideal here, as everywhere else in this flow. That is item 5.

## Pushing it

Nothing goes up until the run is read. When it does:

1. `cd "/mnt/d/silicon/silicon chip" && bash backup_to_repo.sh`

2. Two commits in GitHub Desktop. First the tools, which are
   `sim/spice/gono/gen_instance_decks.py`, `analyze_instance.py`, the results the
   run produced, and `.github/workflows/gds.yaml` for the new selftest line.
   Then the writing, which is item 8 in `docs/hardware_todo.md` plus whatever
   `SIGNOFF.md` and `sim/spice/gono/README.md` need.

3. One push, then check the gds action is green. The `archived-evidence` job runs
   the new `--selftest` now, so a red there is real and not the usual `gl_test`
   noise.
