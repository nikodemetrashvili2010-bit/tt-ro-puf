# Phase A inputs — what the attacker is allowed to read

Task A.1, 16 August 2026. This fixes the input set for the foreign-layout work
and records where every file came from, so that nothing can quietly join the
list later.

## The two targets

Both are ring-oscillator PUFs on Tiny Tapeout 07, both hardened by the same
automated flow on the same PDK as ours — OpenLane `337ffbf4`, open_pdks
`cd1748bb`, sky130A. Each project's own `commit_id.json` says so, and both files
are in the manifest.

**`tt_um_litneet64_ro_puf`**, chip position 142, by Pablo Aravena. This is the
A.6 blind target. It compares two ring oscillators and calls a bit on which one
runs faster, which is the comparison our attack claims to settle at layout time,
and its author has asked board owners to send in their full CRP sets.

**`tt_um_PUF`**, chip position 899, by Syed Farah Naz, Shivam Bhardwaj and
Ambika Prasad Shah. This is the A.7 generalization target. Same shuttle, same
flow, different RTL style — it is there to test whether an adapter fitted to one
author's coding habits survives contact with another's.

Both were chosen on 16 August, before anything was predicted about either.

## What is in the manifest

25 files, 13,400,620 bytes. For each one: the URL, the retrieval time, the byte
size and the SHA-256. Per target the shuttle publishes the GDS, the LEF, the
gate-level netlist, the SPEF, the flow metrics and the build provenance; on top
of that the manifest carries each author's RTL, taken at the commit the shuttle
actually hardened rather than at whatever their repository holds today.

Every URL is pinned to a 40-character commit and `verify_inputs.py` fails an
input whose URL is not. A raw URL on a branch is not an input.

One thing the pinning does not fix, and it is worth knowing before A.5 leans on
any of it. A shuttle project folder is not all from one commit. Its `commit_id.json`
names the commit the layout was built from, and the hardened artifacts do come
from there — but the datasheet beside them does not have to. For the first target
the datasheet in the shuttle folder carries the full architecture description,
while the same file in the author's repository at the hardened commit was still
the unedited Tiny Tapeout template; the description was written later and picked
up by a later docs build. Treat the GDS, LEF, netlist and SPEF as one artefact
set pinned by `commit_id.json`, and the prose beside them as separately dated.

The bytes are not committed. The manifest reproduces them, and
`verify_inputs.py --inputs` re-derives every size and hash to prove it. Where
the bytes are absent — in CI, on the folder bridge — only the manifest's own
digest can be checked, which catches a manifest edited by hand and nothing more.
The script prints which of the two checks it ran.

## The tiers do not describe availability, and I had assumed they did

`PLAN_TO_DECEMBER.md` splits the attacker three ways: Tier 1 with the author's
published SPEF and netlist, Tier 2 with public GDS plus a synthesized netlist,
Tier 3 with GDS and PDK alone and connectivity recovered without the author's
net names. That ordering reads as though Tier 1 is a lucky case and Tier 2 is
the realistic one.

It is not. Tiny Tapeout publishes the gate-level netlist **and** the SPEF for
every project on the shuttle, as a matter of course. Both are in this manifest
for both targets. So Tier 1 inputs are not a lucky case — they are the default
for every design on the platform.

Worse for the defender, the SPEF keeps the author's RTL hierarchy in its net
names. A net in the first ring of the first block is published under the name
`genblk1[0].puf_buffer.ro_array_1[0].inter_wire[0]`. There is nothing to
recover: which net belongs to which ring, and which ring belongs to which
comparison, is written on the file.

Read next to D.2 — which found that the target's extraction is load bearing and
its simulation is not — this says the cheapest useful attack on any Tiny Tapeout
RO-PUF needs no extraction step at all. That belongs in C.1 when the adversary
gets written down.

What survives is Tier 3, and it is now the only tier that requires the hard
part. A.3 and A.4 were priced on the assumption that connectivity had to be
recovered before anything could be recognised. For Tiers 1 and 2 it does not.
The estimate should be revisited at G1 rather than quietly kept.

## Do the oscillators exist

Documentation is not evidence that a ring was fabricated. Synthesis is free to
collapse a chain of inverting stages, and a synthesis attribute written for a
different tool will not stop it. So `ring_census.py` reads each hardened netlist
and finds the combinational cycles itself, without trusting either the RTL or
the datasheet.

| target | rings | shape of each |
|---|---:|---|
| `tt_um_litneet64_ro_puf` | 256 | 7 inverters, an AND, and one buffer |
| `tt_um_PUF` | 62 | one inverting AND and one buffer |
| `tt_um_PUF` | 2 | an AND, an inverter and one buffer |

The first target came through intact. Its RTL asks for eight blocks of
thirty-two seven-inverter rings, and the census finds 256 rings each holding
seven inverters — arrived at from the netlist alone, and agreeing with 8 × 32.
The flow did insert one buffer inside every ring, so the manufactured
oscillator is nine cells and not eight. That is small, and A.5 has to model it
rather than the RTL's eight.

The second target did not. Its RTL builds each oscillator from five cascaded
reversible-logic gates; every one of the 64 rings in the hardened netlist has a
single inverting stage. The rings are there and they will oscillate, but not in
the shape the design describes. The likely mechanism is that an XOR against a
constant reduces to an inverter and the chain of them then collapses — that is
inference from the cell types, not something I measured, and the design carries
`ALLOW_COMBINATORIAL_LOOPS` and `KEEP` attributes that belong to a different
tool chain and would not have stopped it here.

I am not treating this as a reason to drop the target. A one-stage ring's period
is set almost entirely by one cell delay and its local wire load, which is the
quantity this project predicts, so if anything it is a cleaner test of the
mechanism than a seven-stage ring. It does mean any comparison against that
design's own published metrics has to be made against what was built.

## A correction

`PLAN_TO_DECEMBER.md` described the first target on 11 August as 256
seven-inverter oscillators in eight parallel 32-oscillator blocks. On 12 August
I struck that out, on the grounds that I could not find a public source for it
and that 256 challenges looked like it had been misread as 256 oscillators.

The strike-out was wrong and the original sentence was right. Three independent
places say so: the datasheet the shuttle carries for the manufactured design says
one block contains 32 ROs and the challenge is shared across 8 blocks; the RTL at
the commit that was hardened sets `n_bits = 8` and `n_ro = 32`; and the census
finds 256 rings in the netlist. Both readings of 256 happen to be true at once —
8 challenge bits give 256 challenges, 8 blocks of 32 rings give 256 oscillators —
and that coincidence is what made the correction look safe.

The lesson is the cheaper one: I corrected a claim by failing to find a source
rather than by looking in the repository, which was public the whole time. The
note at the top of `EMAIL_PABLO.md` repeated the same error and has been fixed,
which matters more than the plan did — it was about to go to the author.

## Scope

This is the input list and nothing else. Nothing here compares one ring against
another, and no response has been predicted for either design. The census
reports structure only; it says which cycles exist, not which of them is faster.
Tolerances for the A.5 self-pilot are not frozen yet, and until they are, no
foreign analysis runs.
