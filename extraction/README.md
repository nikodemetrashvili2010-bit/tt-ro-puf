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
| `inputs/` | The downloaded bytes. Not committed — the manifest reproduces them |

## Running it

    python3 fetch_inputs.py                                    # needs network
    python3 verify_inputs.py --inputs inputs                   # full check
    python3 verify_inputs.py                                   # manifest only
    python3 ring_census.py --json RING_CENSUS.json inputs/*/projects/*/*.v

    python3 fetch_inputs.py  --selftest
    python3 verify_inputs.py --selftest
    python3 ring_census.py   --selftest

The three selftests plant the faults each script exists to catch and need
neither network nor inputs, which is why they are the versions CI runs.

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
structure only. Nothing in this directory compares one ring against another;
that starts at A.5 and only after the tolerances are frozen.
