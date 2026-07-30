# Deterministic layout contribution in an RO-PUF: pre-silicon results

This note records the nominal post-layout simulations behind the SILICON
project's numbers. Inputs, generated decks, raw ngspice logs, and analysis
scripts live under `sim/spice/gono/`. The scientific argument and the
limitations discussion are in the paper; this file keeps the run detail.

## Summary

An earlier build routed 32 logically identical ring oscillators separately.
With transistors held at the nominal corner, a lumped-capacitance model from
the routed SPEF produced an 8.8% peak-to-peak frequency spread, and
frequency tracked extracted ring capacitance with Pearson *r* = -0.997.
Arm A of the archived dual-arm layout shows the same mechanism at 5.4%
peak-to-peak and *r* = -0.999. Arm B's comparison point is one nominal
simulation of the hardened macro's extracted internal parasitics, 569.5 MHz,
drawn as a reference line because all sixteen instances share that internal
GDS.

## Design under test

The top module, `tt_um_nikodemetrashvili20_ro_puf`, contains two
16-oscillator arms and one shared counter. Each oscillator has an enable
NAND, 30 inverters, and a buffered tap at the middle of the ring. Arm A is
built from standard cells placed and routed with the surrounding logic.
Arm B instantiates the hardened `ro_macro_hard` block sixteen times.

The earlier 32-oscillator baseline is retained because it provides a second
routed layout on which to check whether the capacitance association was
peculiar to one flow run. It was not.

## Method

### Routed inputs

The generator reads the nominal-corner routed netlist, SPEF, and DEF emitted
by the flow. The netlist identifies every Arm A ring node, the SPEF gives
each net's total capacitance, and the DEF supplies placement centroids. The
analysis scripts perform no new RC extraction.

### SPICE model

For each Arm A oscillator, the generator reproduces the ring topology and
places the SPEF `*D_NET` total capacitance on each ring node as a grounded
lumped load. Two combined decks come out: a control deck with no extracted
capacitance, and a nominal post-layout deck with it.

On the chip only one oscillator is enabled at a time. In the generated deck
all 16 reconstructed oscillators run concurrently; under this reduced model
that changes nothing, since they share only an ideal 1.8 V source and no
coupling elements are carried over. Series wire resistance is dropped
entirely, and I have not quantified its effect yet, which is one of the jobs
of the planned distributed-RC comparison. Transistors stay at nominal values to isolate
implementation differences. Each oscillator starts with enable low and is
released with an enable pulse, and frequency is measured over twenty periods
after startup.

## Earlier 32-oscillator build

All 32 no-parasitic instances read 633.640 MHz in the generated control
deck, which checks that the generator gave them the same topology and
stimulus.

With extracted capacitance the mean is 567.6 MHz. The population standard
deviation across the 32 routed instances is 10.8 MHz, 1.90% of the mean.
Frequencies run from about 539.1 MHz (RO10) to 589.2 MHz (RO4), a 50.2 MHz
or 8.8% peak-to-peak spread. Extracted ring capacitance runs from 7.4 to
17.8 fF. Frequency and capacitance have Pearson *r* = -0.997 with a fitted
slope of -4.93 MHz/fF. That extracted capacitance is the only thing the model
varies, so a correlation this strong is expected; the slope and the 8.8%
spread are the parts that carry physical meaning. Correlation with placement
centroid is weak (absolute *r* below 0.27 for the tested coordinates), so the
spread behaves like a per-instance routing fingerprint rather than a die-wide
gradient.

![frequency association and spatial map](../sim/spice/gono/ro_gono.png)

## Hardened Arm B macro

The `ro_macro_hard` layout passes the checked-in DRC, LVS, and antenna
checks, and its standalone 16-copy array passes DRC, LVS, antenna, and
power-connectivity checks. Reusing the macro gives each instance the same
internal ring geometry.

The macro's own nominal SPEF is simulated with the same startup and
lumped-capacitance method. The no-parasitic control reads 633.15 MHz, within
0.08% of the earlier control. The extracted result is 569.5 MHz, 10.1% below
its control, with 11.01 fF of extracted ring capacitance. Applying the
earlier Arm A capacitance fit to that load predicts 570.2 MHz, 0.12% above
the macro simulation, and the macro lands within 0.35% of the earlier Arm A
mean. A 5 ps versus 1 ps timestep comparison moves the result by about 0.2%,
which bounds the numerical error well below the layout effect. The matched arm
removes the internal-layout term by construction. It does not show that Arm B
has a smaller total spread than Arm A; that comparison needs fabricated
chips.

![earlier Arm A distribution and the matched-macro reference line](../sim/spice/gono/armB_prediction.png)

## Coherent dual-arm build

The current design is built in one coherent flow run on a TinyTapeout 2x2
block, and `gen_dualarm_decks.py` reads that run's nominal SPEF and DEF. The
build passes Magic DRC, KLayout DRC, XOR, LVS, antenna, and power grid with
zero violations, so these numbers and the manufacturable GDS come from the
same place. The no-parasitic control gives all 16 instances 633.64 MHz. With
extracted capacitance, Arm A runs from 540.0 to 570.7 MHz: 30.7 MHz or 5.53%
peak-to-peak, mean 554.7 MHz, population standard deviation 1.65%, and
*r* = -0.9997 against ring capacitance with a fitted slope of -4.94 MHz/fF.
Ring loads span 10.9 to 17.0 fF and form a smooth band; the two heaviest
differ by 0.34 fF, so no single instance drives the range here.

The top-level SPEF does not expand the sealed macro internals (the extractor
cannot tell the sixteen copies apart), so Arm B is represented by the single
569.5 MHz macro result as a reference line. That reference sits above the Arm A
mean but not above every instance: RO7 reaches 570.7 MHz on a 10.9 fF load,
about 0.2% past the macro, which is finer than this model resolves.

Two things are worth recording beyond the single build. The 32-oscillator
build's fitted capacitance relation predicts this build's mean to about 0.1%,
so the mechanism carries across independent runs, and this build's own slope of
-4.94 MHz/fF is within a fraction of a percent of that earlier fit. The
peak-to-peak figure is much less stable than the mechanism: across nine builds
that vary only placement density it moves between 4.19% and 6.99%, median 5.75%
(`dualarm/placement_sweep/`). An older build reported 10.5%, above that band,
with most of its range coming from one oscillator loaded at 24.4 fF. The
archived `dualarm/build_debug/` snapshot (5.4%, older RTL, KLayout checks off)
is kept for contrast; this coherent build supersedes it.

![Arm A of the coherent dual-arm build with the matched-macro reference line](../sim/spice/gono/dualarm_gono.png)

## Preliminary mismatch scale

The study under `sim/spice/mc/` runs the matched macro with the PDK's
mismatch switch enabled and process variation disabled. The parameters used
by ngspice are global draws per device class, so 40 runs measure a
common-draw frequency standard deviation of 0.345%, not independent
mismatch inside one ring.

Dividing by `sqrt(31)` gives a first-order 0.062% per-ring estimate under
equal, independent stage sensitivities. The NAND's structure and unequal
device sensitivities make that scaling approximate, and 40 draws leave real
sampling uncertainty: the analyzer reports a sampling-only interval of
0.051% to 0.080% at roughly 95% coverage. The implied layout-to-mismatch
ratios (about 21.6 by standard deviation, 87 by peak-to-peak against the
archived Arm A build) are scale estimates that inherit these assumptions,
which is why the paper quotes them only as motivation for the silicon
measurement.

## Predicting the layout term and subtracting it

Deterministic ought to mean predictable. If I can work out each ring's share of
the dispersion in advance and take it back out, the layout term stops being a
wall and becomes a correction that costs nothing on the die.

The RO-PUF papers already have a correction for systematic variation and it
works on position. Die gradients are spatially correlated, so you fit a surface
in x and y and subtract it. That is the thing to beat.

It does not work here. Cross validated against the shipped build's full RC
frequencies, a quadratic surface in x and y comes out worse than leaving the
data alone. On the 32-oscillator first build it reaches 27.8%, and that is
in-sample with six free parameters, so it is a generous number. The plain
correlations agree, and it is worth saying which frequencies they belong to.
Against the full RC frequencies used for the scoring above, x gives +0.32, y
gives -0.14, and radius from the centroid gives -0.05. Against the lumped
frequencies of the same build the same three are +0.35, -0.17 and -0.07. Weak
either way, and now the two models agree, which they did not while the RC decks
were double counting coupling. A per-instance routing fingerprint
has no smooth surface under it. Fitting one adds noise instead of removing bias.

The design database is a different story. Every ring has a total capacitance and
a total series resistance sitting in the SPEF long before a wafer exists. Scored
the same cross-validated way against the full RC frequencies:

    corrector                        residual spread   removed
    nothing                                   1.739%         -
    position, quadratic in x and y            2.086%    -20.0%
    position, linear in x and y               1.970%    -13.3%
    ring resistance alone                     1.238%    +28.8%
    sum of per-net R times C                  0.516%    +70.3%
    ring capacitance alone                    0.190%    +89.1%
    capacitance and resistance                0.183%    +89.5%

Almost nine tenths of it, then. Against the mismatch estimate from the previous
section, 0.062% with a sampling interval of 0.051% to 0.080%, the uncorrected
dispersion is somewhere around 22 to 34 times the random term and the corrected
one is 2 to 4 times. That is a much better corrector than the version of this
table I had before the coupling fix, and it still does not get down to where
mismatch would be readable.

One caveat belongs on the record. Against the lumped decks a capacitance model
removes 97.6% and lands under the mismatch floor. I do not count that. The
lumped deck is handed one capacitance per net and nothing else varies, so the
fit is recovering its own input, and the full RC run is the honest test. What
the lumped runs are good for is transfer. The first build's fit, a different RTL
on a different placement, reproduces the shipped build's pattern without being
refitted.

Why the scalar correctors stop where they do is not mysterious. Two numbers
cannot stand in for 33 resistors and 65 capacitors per ring. Getting closer
means predicting from the network rather than from summaries of it, and
`gen_rc_decks.py` already runs that simulation.

What I cannot settle here is whether any of this survives fabrication. Comparing
two parasitic models of one layout bounds a pre-fab prediction from below, and
says nothing about how either model compares to a real die. The per-ring numbers
are frozen before the chips arrive, so at least the comparison will be a test
and not a fit.

Whether the residual is worth chasing at all depends on what a single reading
can resolve, and until now nothing in this project answered that. The section
below answers it in simulation. The short version is that the residual sits
about 141 times above the floor, so it is not buried.

The script is `sim/spice/gono/compensation.py`. It recomputes ring capacitance
from both SPEFs and refuses to run if it disagrees with the checked-in tables by
more than 0.01 fF.

## How many bits does the design database already decide?

Everything above is frequencies, and what the chip hands out is bits. The two
are not the same thing, so it is worth converting one into the other.

The core compares neighbouring rings, 0 against 1 and so on up, which makes
eight bits out of Arm A. Each pair's frequency difference has two parts.
Routing sets one of them and the mask freezes it, so it is the same on every die
and it can be read out of the SPEF before anything is fabricated. Mismatch sets
the other, and that one is different on every die. The bit is the sign of the
sum. So if the routing part is much larger than the mismatch part, the sign was
settled at layout time and every chip returns the same bit.

Writing the per-die difference as a fixed offset plus noise, with the mismatch
estimate of 0.062% per ring giving 0.088% per pair across two independent rings,
the across-die probability and its entropy follow directly:

    pair    routing offset   offset/sigma   entropy   guessed
     0/1           -1.864%           21.3     0.000    100.0%
     2/3           +0.116%            1.3     0.444     90.8%
     4/5           +0.267%            3.0     0.013     99.9%
     6/7           -3.265%           37.2     0.000    100.0%
     8/9           +1.156%           13.2     0.000    100.0%
    10/11          -2.504%           28.6     0.000    100.0%
    12/13          -0.690%            7.9     0.000    100.0%
    14/15          -3.668%           41.8     0.000    100.0%

![Arm A's eight pair bits, in mismatch standard deviations and in bits](../sim/spice/gono/predictable_bits.png)

Six of the eight bits land under a hundredth of a bit of entropy. Those are
fixed. Arm A's response carries about 0.5 bits of device-specific entropy rather
than 8, and someone holding nothing but the public design files would call 7.9
of the 8 correctly on average. Pushing the mismatch estimate to the ends of its
sampling interval moves that to 0.3 to 0.7 bits and 7.8 to 8.0 correct, so the
conclusion does not hinge on the exact mismatch figure.

Almost all of what is left sits in pair 2/3, at 0.44 bits. Pair 4/5 is the next
closest and it is already down to 0.013 bits, right on the line. That the
surviving entropy sits in the closest pair is what the argument predicts, since
the routing term and the mismatch term compete and only a small routing term
leaves the die a say. The lumped decks and the full RC network agree on the sign
of all eight pairs, so a cheap model is enough to read them. An earlier version of
this file said the two closest pairs were the two the models disagreed about. That
was an artefact of the RC decks building each internal coupling capacitor twice,
and once that is fixed nothing disagrees.

Arm B needs no arithmetic here. Sixteen instances of one macro have identical
internal routing, so the offset is zero, every bit is a coin flip decided by
mismatch, and the design files predict none of them.

This is the part I think matters most for an open shuttle. My GDS, netlist and
extracted parasitics are all on GitHub. For a proprietary chip an attacker would
have to obtain the design database first. Here it is a download.

The obvious limit is that eight bits is a small response and both arms are still
simulations. The offsets in that table are model output, not measurement, and a
die that disagrees with them refutes the whole argument. That is what the
tapeout is for. Script is `sim/spice/gono/predictable_bits.py`.

## What a reading can resolve

A residual of 0.18 percent and a mismatch scale of 0.062 percent are only
interesting if a measurement can see numbers that small. Three things decide
that. The operating point can drift between readings, the oscillator has thermal
noise of its own, and the counter returns an integer. I looked at all three. The
last one turned out to be the limit, which I did not expect.

The decks come from `gen_noise_decks.py`. They read the same shipped netlist and
SPEF as everything else here and they call `gen_dualarm_decks.py`'s own ring
builder, so the topology cannot drift between the two scripts. The 1.80 V deck
is the shipped nominal deck with a different title line. `analyze_noise.py`
refuses to report anything unless that deck returns the archived nominal
frequencies, and it checks the temperature ngspice printed in each log against
the temperature the deck asked for.

### Supply

The ring is very sensitive to its supply. Across 1.62 to 1.98 V the fitted
pushing figure is 105.9 percent per volt, so ten millivolts move a ring by about
one percent. That is seventeen times the mismatch scale. If the PUF read
absolute frequencies this would sink it.

It does not read absolute frequencies. A bit is the sign of a difference between
two rings on one die sharing one supply, so the part of the shift that hits all
sixteen equally cancels. The question is how nearly it does. The sixteen pushing
figures span 105.57 to 106.17 percent per volt, a spread of about half a percent
of the value. Taking out a single common scaling at each point, the rings depart
from each other by 0.027 percent standard deviation at 1.62 V, worst ring 0.048,
and 0.034 percent at 1.98 V, worst ring 0.063. Those are ten percent supply
excursions, well past what a regulator does, and the differential term still
lands under the mismatch scale.

### Temperature

This one surprised me and I nearly deleted it. At 1.80 V the arm mean runs
549.7 MHz at -40 C, 553.4 at 0, 554.7 at 27, 555.1 at 85, then back down to
553.9 at 125. The whole 165 degree range moves it by 0.97 percent and the
fastest point sits in the middle. My first thought was that the temperature card
never reached the models, because a ring oscillator that ignores temperature is
not a ring oscillator.

Two checks said otherwise. Every ngspice log states the temperature it ran at,
and all five matched their decks. Then four tiny decks asked for 125 C in four
different ways, using a resistor with a known temperature coefficient as the
readback, and every one of them came back at 125 C.

So I went after the physical explanation instead. A CMOS stage has two competing
temperature effects. Threshold voltage falls with heat, which speeds the stage
up, and carrier mobility falls with heat, which slows it down. Near a particular
gate overdrive the two cancel. If that is what is happening at 1.80 V, the
cancellation belongs to the overdrive and not to the circuit, so moving the
supply has to move it. Less overdrive should give a positive coefficient and
more should give a negative one. That prediction can fail.

It did not. Over the same -40 to 125 C span the coefficient is +0.053 percent
per degree at 1.62 V, +0.005 at 1.80 V, and -0.024 at 1.98 V. The sign crosses
zero close to the supply the chip actually runs at. The flat response is the
circuit.

For my measurement plan that is convenient. I have no temperature chamber and
the chips will be read in a room, so a design whose frequency barely moves
between 0 and 85 C is the one I want. The dispersion is steadier than the mean:
across those five temperatures it goes 5.66, 5.58, 5.53, 5.43, 5.36 percent. The
routing signature is close to temperature independent.

### The eight bits

Eleven operating points now exist. Both supply extremes, both temperature
extremes, and the four combinations of them. All eight Arm A pair bits keep the
same sign at every one.

That is less comfortable than it sounds. The tightest pair is separated by 0.270
percent of the arm mean, and the largest ring-to-ring departure anywhere in the
box is 0.150 percent, at 1.98 V and 125 C. The margin on that pair is a factor
of 1.8, not orders of magnitude. A pair sitting twice as close would flip
somewhere in the box, and on a real die mismatch will shift every separation.
Eight bits from one simulated layout is not a reliability result.

### Thermal noise

The oscillator's own noise needs a different deck. `noise_jitter.spice` runs
three rings, the lightest, the median and the heaviest by ring capacitance, and
measures dV/dt at the switching threshold on all 31 nodes of each, rising and
falling. It runs at a 0.5 ps step rather than 5 ps, because the band it times is
crossed in about four picoseconds and a coarse step would return the
interpolation instead of the circuit.

Noise on a node moves the crossing time by roughly the noise voltage divided by
that slope, and the noise voltage on a capacitance is about the square root of
gamma k T over C. One period contains 62 transitions and I add them as
independent. That gives period jitter of 0.94, 0.78 and 0.78 ps for rings 7, 13
and 14. The scaling follows Weigandt, Kim and Gray, and the single-ended ring
case is treated by Hajimiri, Limotyrakis and Lee.

Both assumptions push the answer upward on purpose. I set the excess noise
factor gamma to 2, the short-channel end. The capacitance is the extracted wire
capacitance alone, which is smaller than the real node capacitance once the
driven gate is counted, and a smaller capacitance means more noise. This is a
first-order estimate with a known direction of error, not a transient noise
simulation.

Counting flattens it. The window is 1000 reference cycles at 25 MHz, so 40
microseconds, which is about 22000 ring periods. Independent period jitter
averages down as the square root of that count, and 0.94 ps becomes 0.00036
percent of the frequency.

### The counter is the floor

Twenty-two thousand counts means one count is 0.0045 percent and the rounding
error is 0.0013 percent rms. That is roughly four times the thermal figure. The
oscillator is quieter than the thing reading it, which is the opposite of what I
assumed when I started.

Taking the larger of the two, the floor is 0.0013 percent. The mismatch scale
sits 48 times above it. The tightest pair separation sits 207 times above it.
The compensation residual sits 141 times above it. So the residual is not hiding
under noise, and neither is the device-specific entropy the whole design depends
on.

What this does not cover. The supply points are static offsets, not a ripple
that moves during a reading and catches different rings at different phases.
Ageing, package and the measurement instrument are absent. Every number is
nominal process on one layout. It is a simulated floor, and the silicon phase is
what turns it into a measured one. Scripts are
`sim/spice/gono/gen_noise_decks.py` and `analyze_noise.py`.

## The silicon test

The prediction: under matched measurement conditions, Arm A will show greater
centred-pattern correlation across chips than Arm B. Multiple
chips and repeated voltage and temperature measurements are needed to test
it, and a weak or negative result would force a revision of the
interpretation above. The model limitations behind all of these numbers are
collected in the paper's limitations section rather than repeated here.

## Reproducibility map

- `gen_decks.py`, `ro_all_*.spice`, `ctrl2.txt`, `par2.txt`, `verify.py`:
  earlier 32-oscillator build.
- `gen_dualarm_decks.py`, `dualarm_*.spice`, `dualarm_*_out.txt`,
  `verify_dualarm.py`: Arm A in the archived dual-arm layout.
- `gen_macro_deck.py`, `ro_macro_matched*.spice`, `macro*_out.txt`,
  `verify_macro.py`: the hardened-macro reference.
- `gen_noise_decks.py`, `noise_*.spice`, `noise_*_out.txt`, `tprobe_*`,
  `analyze_noise.py`, `verify_noise.py`: supply, temperature and the
  resolution floor.
- `analyze.py` plus the figure scripts: descriptive statistics and plots.
- `first_build/` and `dualarm/build_debug/`: routed inputs for the two Arm A
  analyses.

The verify scripts recompute the headline quantities from the archived logs
and exit nonzero on any mismatch. The portable runner resolves local PDK
paths in a temporary deck without editing the checked-in files.
