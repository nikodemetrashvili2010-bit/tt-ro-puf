# Amending G.2 after the chosen arm turned out unbuildable

7 September 2026. `chip/G2_AMENDMENT.json` is the machine readable record.
This is the argument behind it.

## What G.2 chose, and what killed it

G.2 was frozen on 27 August, before either option was scored, and it chose
sixteen Arm C rings as standard cells under placement and routing
equalization constraints. The load ladder was the declared fallback.

On 6 September, step 7 read the flow's own sources and found that LibreLane
has no region, no fence and no cell group among its 413 variables, and that
none of the four variables taking a Tcl file is read by a placement step. The
chosen treatment has no implementation here. Not a hard one. None.

The criteria file saw it coming and said so in writing:

    "delivery_risk": "high",
    "delivery_risk_basis": "The open flow has no supported way to force
    sixteen identical placements. It is the point of the experiment and it
    is also the thing that might not work."

That was written on 27 August as a worry, before anything was built. It is
the risk firing on schedule, which is a better outcome than a surprise, and
it is the reason the fallback exists.

## The three ways out

Take the ladder. Nothing gets rewritten, the freeze holds untouched, and the
third arm becomes a load-versus-frequency calibration curve. That is a
useful thing and it is not a countermeasure test.

Place all 512 Arm C cells by hand from one template. Every ring then gets an
identical bounding box, an identical row span and an identical density, which
is word for word G.2's build criterion, met perfectly and measuring nothing,
because the criterion exists to ask whether the tool held the constraint and
I would have answered it by not using the tool.

Drop back to two arms.

There is a fourth reading that is not on that list and should not be. Leave
Arm C to the placer, and it is sixteen rings under exactly Arm A's
treatment: three arms, two treatments. `gen_placement_cfg.py` emits no Arm C
line and its P11 fails if one turns up, which is that door held shut.

## What was decided, and what it costs

Nikoloz decided on 7 September: keep the third arm, take the stronger
result, do not downgrade the project. So it is the hand placed arm.

The honest version of that option is not the one on G.2's list. Placement
fixed by hand and routing left free is a different experiment: it sits
between Arm A, where placement and routing are both free, and Arm B, where
both are fixed inside one hardened macro. Three points on what has been a two
point line, and the thing it isolates is routing as the remaining source of
ring to ring difference. I would want that experiment. It is worth building.

It is also not the experiment G.2 scored, and swapping one in because the
first turned out unbuildable is exactly the move that freezing a decision
exists to prevent. So the amendment is written as an amendment. It does not
replace `G2_CRITERIA.json`, it does not touch `G2_DECISION.json`, both stay
on disk as frozen and both are recorded in the amendment by SHA-256, and the
amendment says on its face that it is not a preregistration and must never be
cited as one. The paper carries the same sentence.

What is actually lost is the first line of G.2's preference order: whether an
open automated flow can suppress layout leakage with constraints, or whether
it needs a hard macro. Hand placing answers that in the negative by
construction, because the flow has no constraint to hold. That is a real
finding about open flows and it belongs in the paper as one, but it is a
finding about the tooling and not a measurement on silicon, and the arm no
longer tests it.

## What is not amended

H1 to H6 stand. The hand placed option has to be scored against them before
it is built and not after. Its cell count is the same sixteen rings of thirty
two cells that was scored on 27 August, so I expect H1 to H6 to land where
they landed then, and an expectation is not a score. Tiles stay four unless
that re-scoring says otherwise.

## The part that is not settled

Hand placing Arm C means 512 more standard cells pinned FIRM through
`MACRO_PLACEMENT_CFG`, on top of the 512 Arm A cells step 7 already pinned.

Run 72 is the first and only evidence about whether this flow accepts
standard cells pinned FIRM at step 17, and run 72's `gds` job failed. Its
reason is not yet readable; see `docs/phaseG_run72.md`.

So this amendment is contingent, and I would rather say that than write it
as settled. If pinning standard cells FIRM is what broke run 72, then hand
placing Arm C is unavailable for the same reason the original Arm C was, and
the choice collapses to the ladder or to two arms. The next push carries
`chip/ci_failure_report.py` and will say which. Deciding before it reports
would be guessing twice about the same thing.
