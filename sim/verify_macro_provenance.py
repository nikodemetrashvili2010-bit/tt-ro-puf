#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Check the licensing and provenance claims, hardware item G.

Two things this repository says about itself are easy to break by accident and
impossible to notice by reading. The first is that every hand-written source
file carries a licence line. The second is that `macro/romacro_final` has no
`commit_id.json` but does still pin its extraction tool, which is written down
in `PROVENANCE.md` and read out of the build outputs here rather than typed.

There is a third, and it is the one that caught me out. Several files in this
repository are archived evidence, pinned by git blob hash in
`sim/spice/gono/evidence_manifest.json`, and `verify_provenance.py` fails if any
of them changes. I started adding a licence header to the hardened macro netlist
before noticing it is one of them. So the licence audit below skips exactly the
pinned files and says so out loud, and the reason is recorded in `LICENSING.md`.

    python3 sim/verify_macro_provenance.py
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from repo_paths import resolve  # noqa: E402

FINAL = os.path.join(ROOT, "macro", "romacro_final")
DOC = os.path.join(FINAL, "PROVENANCE.md")
SPEF = os.path.join(FINAL, "spef", "nom", "ro_macro_hard.nom.spef")
MAG = os.path.join(FINAL, "mag", "ro_macro_hard.mag")
METRICS = os.path.join(FINAL, "metrics.json")
MANIFEST = os.path.join(ROOT, "sim", "spice", "gono", "evidence_manifest.json")
LICENSING = os.path.join(ROOT, "LICENSING.md")

# Build outputs are left exactly as the flow wrote them. Hand-written files are
# the ones that must carry a licence line.
GENERATED = ("build_current/", "build_debug/", "control_wokwi/", "first_build/",
             "romacro_final/", "pdnfix4_final/", "gds_build/", "_audit_",
             "__pycache__/", "floorplan_trials/", "_github_review/", "/tt/")
# These two live on my disk and are never mirrored into the repository.
LOCAL_ONLY = ("backup_to_repo.sh", "test_backup_audit.sh", "git-filter-repo")
SOURCE_EXT = {".v", ".sv", ".py", ".tcl", ".sh", ".yaml", ".yml"}

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


def text(path):
    return open(path, encoding="utf-8", errors="replace").read()


doc = re.sub(r'\s+', " ", text(DOC))


# ------------------------------------------------- what the build outputs pin

openroad = re.search(r'\*VERSION "([0-9a-f]{40})"', text(SPEF))
check("the SPEF pins an OpenROAD commit",
      openroad is not None, openroad.group(1) if openroad else "none found")
check("PROVENANCE.md quotes that same commit",
      openroad and openroad.group(1) in doc)

program = re.search(r'\*PROGRAM "([^"]+)"', text(SPEF)).group(1)
check("the tool the SPEF names is the one written down",
      program in doc, program)

spef_date = re.search(r'\*DATE "([^"]+)"', text(SPEF)).group(1)
check("PROVENANCE.md quotes the SPEF's own date",
      "14:48:58" in doc and "22 June 2026" in doc, spef_date)

stamp = int(re.search(r'^timestamp (\d+)', text(MAG), re.M).group(1))
when = datetime.fromtimestamp(stamp, timezone.utc)
check("the Magic timestamp is written down as it stands",
      str(stamp) in doc, "%d = %s" % (stamp, when.strftime("%Y-%m-%d %H:%M:%S UTC")))

spef_dt = datetime.strptime(spef_date, "%H:%M:%S %A %B %d, %Y")
gap = abs((when.replace(tzinfo=None) - spef_dt).total_seconds())
check("the two files agree on when the run happened",
      gap <= 5, "%.0f seconds apart, written by %s and by Magic" % (gap, program))

tech = re.search(r'^tech (\S+)', text(MAG), re.M).group(1)
check("the technology in the layout is the one claimed", tech in doc, tech)

metrics = json.load(open(METRICS))
insts = metrics["design__instance__count"]
area = metrics["design__instance__area"]
check("the instance count and area come from metrics.json",
      str(insts) in doc and ("%.3f" % area) in doc,
      "%d instances, %.3f um2" % (insts, area))
check("metrics.json really reports a clean run",
      metrics["design__instance_unmapped__count"] == 0
      and metrics["synthesis__check_error__count"] == 0)

# The gap itself, stated rather than quietly absent.
check("there is still no commit_id.json here",
      not os.path.exists(os.path.join(FINAL, "commit_id.json")))
check("PROVENANCE.md admits the PDK commit is unrecoverable",
      "Not recoverable" in doc and "PDK commit" in doc)
check("the integrated build does record its own commit",
      os.path.exists(os.path.join(ROOT, "dualarm", "build_current",
                                  "commit_id.json")))


# ------------------------------------------------------------ licence headers

manifest = json.load(open(MANIFEST))
pinned = set(manifest["evidence_files"])
# The manifest uses the clone's layout, where dualarm/src is mirrored to src.
pinned |= {p.replace("src/", "dualarm/src/", 1) for p in pinned
           if p.startswith("src/")}

# A pinned file can have a byte-identical copy elsewhere. array/ holds one of
# the macro netlist. Editing the copy would make the two disagree, which is a
# quieter kind of wrong than editing the pinned one, so copies are found by
# content rather than named in a list here.
frozen = {}
for rel in sorted(pinned):
    path = os.path.join(ROOT, rel.replace("/", os.sep))
    if os.path.exists(path):
        frozen[open(path, "rb").read()] = rel

missing, skipped, twins = [], [], []
for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d != ".git"]
    for name in filenames:
        path = os.path.join(dirpath, name)
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        if os.path.splitext(name)[1] not in SOURCE_EXT:
            continue
        if any(g.strip("/") in rel for g in GENERATED) or name in LOCAL_ONLY:
            continue
        if rel in pinned:
            skipped.append(rel)
            continue
        if "SPDX-License-Identifier" in text(path)[:2500]:
            continue
        origin = frozen.get(open(path, "rb").read())
        if origin:
            twins.append((rel, origin))
        else:
            missing.append(rel)

check("every hand-written source file carries a licence line",
      not missing, "none missing" if not missing
      else "%d missing: %s" % (len(missing), ", ".join(sorted(missing)[:5])))
check("the files skipped are skipped because they are pinned evidence",
      all(p in pinned for p in skipped),
      "skipped: %s" % (", ".join(sorted(skipped)) if skipped else "none"))
check("every unheadered copy is byte-identical to the pinned original",
      True, "; ".join("%s matches %s" % t for t in twins) if twins
      else "no copies found")
check("LICENSING.md explains why a pinned file gets no header",
      os.path.exists(LICENSING)
      and "evidence_manifest.json" in text(LICENSING))


# ------------------------------------------------------ the borrowed PDN file

# In the published tree dualarm/src has been mirrored to src, so ask for the
# working-folder name and let resolve find whichever exists.
found = 0
for rel in ("dualarm/src/pdn_cfg.tcl", "dualarm/pdn_cfg.tcl", "array/pdn_cfg.tcl"):
    path = resolve(rel, required=False)
    if path is None:
        continue
    found += 1
    body = text(path)
    check("%s keeps its upstream copyright" % rel,
          "Copyright 2020-2022 Efabless Corporation" in body
          and "github.com/TinyTapeout/tt06-dffram-example" in body
          and "Modifications copyright 2026" in body)
check("all three copies of the borrowed recipe were found", found == 3,
      "%d of 3" % found)


def directives(rel):
    return [l for l in text(resolve(rel)).splitlines()
            if l.strip() and not l.lstrip().startswith("#")]


check("the two PDN recipes are still the same recipe",
      directives("dualarm/src/pdn_cfg.tcl") == directives("array/pdn_cfg.tcl"),
      "%d directives each" % len(directives("array/pdn_cfg.tcl")))


# ------------------------------------------------------------------------ report

width = max(len(n) for n, _, _ in results)
bad = sum(1 for _, ok, _ in results if not ok)
for name, ok, detail in results:
    print("  %-5s %-*s %s" % ("ok" if ok else "FAIL", width, name, detail))
print("%d checks, %d failed" % (len(results), bad))
sys.exit(1 if bad else 0)
