# Phase A — foreign layout extraction

Everything the attacker is allowed to read about somebody else's chip, and the
machinery that keeps that list honest.

The rule this directory exists to enforce: the attacker has public artifacts and
nothing else. No victim device, no measured responses, no private correspondence.
If a file is not in `INPUT_MANIFEST.json`, Phase A does not get to use it.

## Files

| file | what it is |
|---|---|
| `sources.json` | Every input, declared by hand, with why each target was chosen |
| `fetch_inputs.py` | Downloads them and writes the manifest. Needs network |
| `INPUT_MANIFEST.json` | URL, retrieval date, byte size and SHA-256 for each input |
| `verify_inputs.py` | Checks the manifest against the source list and the bytes |
| `ring_census.py` | Counts the ring oscillators actually present in a netlist |
| `RING_CENSUS.json` | That count, tied to the netlist hash it was taken from |
| `gds_census.py` | Reads the published GDS and reconciles it with the LEF, the netlist and the flow metrics |
| `GDS_CENSUS.json` | That reconciliation, tied to the GDS and netlist hashes |
| `TOLERANCES.json` | The A.5 acceptance thresholds, frozen 2026-08-18 before the pipeline existed |
| `check_tolerances.py` | The only thing that reads them. Refuses to pass if the file's hash moved |
| `spef_census.py` | Counts how much of the author's own module hierarchy survives in the published SPEF |
| `SPEF_CENSUS.json` | That count, tied to the SPEF and netlist hashes |
| `library_sources.json` | The 43 sky130_fd_sc_hd functional views A.4 reads, pinned by URL and SHA-256 |
| `ring_topology.py` | Recovers the rings from a netlist using the cell library and no names |
| `RING_TOPOLOGY.json` | What it recovered, with every library hash it read |
| `inputs/` | The downloaded bytes. Not committed — the manifest reproduces them |

## Running it

    python3 fetch_inputs.py                                    # needs network
    python3 verify_inputs.py --inputs inputs                   # full check
    python3 verify_inputs.py                                   # manifest only
    python3 ring_census.py --json RING_CENSUS.json inputs/*/projects/*/*.v
    python3 gds_census.py --json GDS_CENSUS.json inputs/*/projects/tt_um_*
    python3 spef_census.py --json SPEF_CENSUS.json inputs/*/projects/tt_um_*
    python3 ring_topology.py --fetch-library                   # needs network
    python3 ring_topology.py --json RING_TOPOLOGY.json inputs/*/projects/tt_um_*

    python3 check_tolerances.py                                # print the frozen numbers
    python3 check_tolerances.py --freeze-check
    python3 check_tolerances.py --reference spef.csv --candidate pipeline.csv

    python3 spef_census.py --verify-archive        # the JSONs against each other
    python3 ring_topology.py --verify-archive      # the same, for the topology

    python3 fetch_inputs.py      --selftest
    python3 verify_inputs.py     --selftest
    python3 ring_census.py       --selftest
    python3 gds_census.py        --selftest
    python3 check_tolerances.py  --selftest
    python3 spef_census.py       --selftest
    python3 ring_topology.py     --selftest

The seven selftests plant the faults each script exists to catch and need
neither network nor inputs, which is why they are the versions CI runs. The two
`--verify-archive` modes run there too, and they are the only Phase A commands
that check a real recorded number without the inputs present: they re-read the
archived JSONs and re-derive every claim that lives between them.

`gds_census.py` takes project directories, not files — it needs the GDS, the
LEF, the netlist and `stats/metrics.csv` together, because the whole point is
that they have to agree. `spef_census.py` takes the same directories and reads
two of them.

## Why the inputs are not committed

They are 13 MB of somebody else's build products. The manifest pins the repo
commit for every one of them, so `fetch_inputs.py` reproduces the exact bytes
and `verify_inputs.py --inputs` proves it did. Committing the blobs would add
weight and a redistribution question without adding evidence.

`inputs/` is in `.gitignore` for that reason. If it ever appears in
`git status`, something copied it into the tree by hand.

## What the manifest is worth, and what it is not

Two checks, deliberately not the same strength:

- **With the files present**, every size and every hash is re-derived from the
  bytes. That is the real check.
- **Without them** — in CI, on the folder bridge — only `manifest_digest` can
  be recomputed. It catches a manifest edited after the fact. It cannot catch a
  file that changed underneath a manifest nobody touched.

`verify_inputs.py` prints which of the two it ran. Do not read the weaker line
as the stronger one.

## Pinning

Every URL carries a 40-character commit, and the verifier fails an input whose
URL does not. A raw URL on `main` is not an input, it is a subscription.

For the two authors' repositories the pin is not `HEAD` — it is the commit the
shuttle actually hardened, read out of each project's own `commit_id.json`. The
RTL those authors have pushed since is not what was manufactured.

## Scope

A.1 is the manifest and nothing else. `ring_census.py` is here because target
selection has to be justified before any response is predicted, and "does this
design contain ring oscillators at all" is a selection question. It reports
structure only.

A.2 is `gds_census.py`, and it is bookkeeping of the same kind: it establishes
that the four published files describe one die, so that later phases can quote
any of them without saying which. It reads placements, not parasitics.

A.3 begins with `spef_census.py`, which answers the question A.2 left open:
whether `tt_um_PUF`'s SPEF carries RTL paths its GDS does not. It does — 82 of
358 nets, 64 of them one per ring. The script counts names and only names; the
control in its selftest scales every capacitance in the fixture by a thousand
and requires the census to come out identical. See `docs/phaseA_spef.md`.

A.4 begins with `ring_topology.py`, which recovers the rings from the netlist
without reading a net or instance name: the cell library gives pin directions
and, from each cell's own truth table, which inputs arrive inverted, and a ring
is a feedback loop with an odd number of inversions. Names are read afterwards
in a labelled step, and the author's path families come out one to one with the
recovered loops on both targets. The control re-runs the whole recovery on the
same netlist with every name replaced by a hash and requires the same answer.
See `docs/phaseA_topology.md`.

The 43 cell views live in `inputs/sky130_fd_sc_hd/` and are pinned in their own
`library_sources.json` rather than in `INPUT_MANIFEST.json`, which records
target selection on 16 August and is not reopened. All three attacker tiers
grant the public PDK and cell library, so these are inputs and not recovered
knowledge.

A.5's tolerances are `TOLERANCES.json`, written on 2026-08-18. They are frozen
in the sense that matters: the file's SHA-256 is recorded in
`docs/phaseA_tolerances.md`, in `PLAN_TO_DECEMBER.md` and inside
`check_tolerances.py`, and the `archived-evidence` job checks all of it, so a
threshold cannot be widened after a failing run without the change being
obvious. They were written before the pipeline of A.3 and A.4 existed.

Nothing in this directory compares one ring against another yet. That starts
when the pipeline does, and it is scored against the file above.
