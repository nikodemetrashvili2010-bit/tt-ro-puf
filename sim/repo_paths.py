#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Find a file in either the working folder or the published repository.

These are not the same tree. The mirror script copies `dualarm/src` to `src` and
everything in `ci/` to `.github/workflows/`, so a checker that hardcodes the
working-folder path runs here and crashes in CI, where only the published layout
exists. That is the same working-tree against clone divergence that cost a week
in August, arriving from the other direction.

I wrote this after nearly shipping two checkers with the working-folder paths
baked in. Neither could ever have gone green in the action.

Every path below is given in working-folder form. `resolve` returns whichever of
the two layouts is actually on disk.
"""

import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# Working-folder prefix, published prefix. Longest first, so dualarm/src is
# tried before dualarm.
# This was ci/gds.yaml alone until 2026-08-11, when docs.yaml, fpga.yaml and
# test.yaml came under the mirror script too. A prefix covers all four and
# whatever lands in ci/ next, which is better than four near-identical lines
# and one more place to forget.
ALIASES = (
    ("dualarm/src/", "src/"),
    ("ci/", ".github/workflows/"),
)


def candidates(rel):
    """Every place a file given in working-folder form might actually live."""
    rel = rel.replace(os.sep, "/")
    out = [rel]
    for here, there in ALIASES:
        if rel.startswith(here):
            out.append(there + rel[len(here):])
    return out


def resolve(rel, required=True):
    """Absolute path to `rel` in whichever layout exists.

    With required False this returns None instead of raising, which is what you
    want for a file that is deliberately absent in one of the two trees.
    """
    for candidate in candidates(rel):
        path = os.path.join(ROOT, candidate.replace("/", os.sep))
        if os.path.exists(path):
            return path
    if not required:
        return None
    raise SystemExit(
        "cannot find %s. Looked for %s under %s. If this is a new file, check "
        "that backup_to_repo.sh has a rule for it, because a file with no rule "
        "never reaches the published repository and every check that reads it "
        "then fails in CI and passes here."
        % (rel, " or ".join(candidates(rel)), ROOT))


def published(rel):
    """The name this file has in the published repository."""
    rel = rel.replace(os.sep, "/")
    for here, there in ALIASES:
        if rel.startswith(here):
            return there + rel[len(here):]
    return rel


def selftest():
    ok = True
    cases = [
        ("dualarm/src/ro_puf.v", "src/ro_puf.v"),
        ("dualarm/src/pdn_cfg.tcl", "src/pdn_cfg.tcl"),
        ("ci/gds.yaml", ".github/workflows/gds.yaml"),
        ("ci/docs.yaml", ".github/workflows/docs.yaml"),
        ("ci/fpga.yaml", ".github/workflows/fpga.yaml"),
        ("ci/test.yaml", ".github/workflows/test.yaml"),
        ("dualarm/pdn_cfg.tcl", "dualarm/pdn_cfg.tcl"),
        ("info.yaml", "info.yaml"),
        ("sim/spice/gono/verify.py", "sim/spice/gono/verify.py"),
    ]
    for here, there in cases:
        got = published(here)
        mark = "ok  " if got == there else "WRONG"
        ok = ok and got == there
        print("  %s %-30s published as %s" % (mark, here, got))
    # dualarm/src must win over dualarm, or every file under it lands in the
    # wrong place. This is the same longest-prefix rule the mirror script needs.
    deep = candidates("dualarm/src/x.v")
    mark = "ok  " if deep == ["dualarm/src/x.v", "src/x.v"] else "WRONG"
    ok = ok and mark == "ok  "
    print("  %s the deeper rule is tried, not the shallower one: %s" % (mark, deep))
    missing = resolve("no/such/file", required=False)
    mark = "ok  " if missing is None else "WRONG"
    ok = ok and missing is None
    print("  %s a missing optional file returns None rather than raising" % mark)
    print("selftest: %s" % ("all cases behaved" if ok else "SOMETHING IS WRONG"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
