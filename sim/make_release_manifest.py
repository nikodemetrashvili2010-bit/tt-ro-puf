#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Build the body of a release, from the files rather than from memory.

Item G wants a tagged release carrying hashes of the shipped views and the
versions behind them. Typing sixteen hex digests by hand is how a release ends
up with one that does not match, so this prints them, and prints the version
information next to a blank where the build outputs do not record it.

The blanks are the point. A release note that silently omits the PDK version
reads as though nobody thought about it. One that names the field and leaves it
empty says the build did not record it, which is the true state.

Two things this cannot know, both marked TODO in the output, because they live
in the GitHub run and not in any file here: the SHA that `@ttsky26c` resolved to
on the day, and the LibreLane version the action used. Read them off the run log
of the build that produced the shipped GDS and paste them in.

    python3 sim/make_release_manifest.py > /tmp/release_body.md
"""

import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from repo_paths import resolve  # noqa: E402
BUILD = os.path.join(ROOT, "dualarm", "build_current")
MACRO = os.path.join(ROOT, "macro", "romacro_final")

SHIPPED = [
    ("integrated GDS", os.path.join(BUILD, "tt_um_nikodemetrashvili20_ro_puf.gds")),
    ("integrated netlist", os.path.join(BUILD, "tt_um_nikodemetrashvili20_ro_puf.nl.v")),
    ("integrated DEF", os.path.join(BUILD, "tt_um_nikodemetrashvili20_ro_puf.def")),
    ("integrated SPEF, nominal",
     os.path.join(BUILD, "tt_um_nikodemetrashvili20_ro_puf.nom.spef")),
    ("integrated metrics", os.path.join(BUILD, "metrics.json")),
    ("macro GDS", resolve("dualarm/src/ro_macro_hard.gds")),
    ("macro LEF", resolve("dualarm/src/ro_macro_hard.lef")),
    ("macro netlist", resolve("dualarm/src/ro_macro_hard.nl.v")),
    ("macro SPEF, nominal",
     os.path.join(MACRO, "spef", "nom", "ro_macro_hard.nom.spef")),
    ("macro metrics", os.path.join(MACRO, "metrics.json")),
]


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def spef_field(path, name):
    with open(path, encoding="utf-8", errors="replace") as fh:
        for _ in range(40):
            line = fh.readline()
            if line.startswith("*" + name):
                return line.split('"')[1]
    return None


def main():
    out = []
    w = out.append

    w("Files in this release, sha256 of the bytes in the repository at this tag.")
    w("")
    missing = []
    for label, path in SHIPPED:
        if os.path.exists(path):
            w("    %-24s %s  %s" % (label, digest(path), os.path.basename(path)))
        else:
            missing.append(label)
            w("    %-24s MISSING from the working tree" % label)
    w("")

    commit = os.path.join(BUILD, "commit_id.json")
    w("What the integrated build recorded about itself.")
    w("")
    if os.path.exists(commit):
        rec = json.load(open(commit))
        w("    Tiny Tapeout tooling   %s" % rec.get("app", "not recorded"))
        w("    design repository      %s" % rec.get("repo", "not recorded"))
        w("    design commit          %s" % rec.get("commit", "not recorded"))
    else:
        w("    commit_id.json is absent")
    spef = os.path.join(BUILD, "tt_um_nikodemetrashvili20_ro_puf.nom.spef")
    if os.path.exists(spef):
        w("    OpenROAD commit        %s" % spef_field(spef, "VERSION"))
        w("    extraction written     %s" % spef_field(spef, "DATE"))
    w("    PDK version            not recorded by this build; the workflow asks")
    w("                           for sky130A, which names the process only")
    w("    tt-gds-action           TODO paste the SHA that @ttsky26c resolved to")
    w("    LibreLane version       TODO read it off the run log")
    w("")

    msp = os.path.join(MACRO, "spef", "nom", "ro_macro_hard.nom.spef")
    w("What the hardened macro build recorded about itself. The full account,")
    w("including what is not recoverable, is in macro/romacro_final/PROVENANCE.md.")
    w("")
    w("    commit_id.json         absent, so no tooling or design commit")
    if os.path.exists(msp):
        w("    OpenROAD commit        %s" % spef_field(msp, "VERSION"))
        w("    extraction written     %s" % spef_field(msp, "DATE"))
    w("    PDK version            not recorded and not reconstructable")
    w("")

    action = re.findall(r'uses:\s*(TinyTapeout/[^\s]+)',
                        open(resolve("ci/gds.yaml"), encoding="utf-8").read())
    if action:
        w("The workflow references %s." % ", ".join(sorted(set(action))))
        w("Those are branch names, so they move. That is deliberate, Tiny Tapeout")
        w("expects the shuttle branch, and it is why the resolved SHA belongs")
        w("here rather than in the workflow file.")
        w("")

    print("\n".join(out))
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
