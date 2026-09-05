#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""G.5: what Phase E published, what produced it, and whether it still holds.

G.5 wants a reproducibility release where the source, GDS, DEF, SPEF and
netlist hashes, the resolved action SHAs, the tool versions and the paper
numbers all agree. `sim/make_release_manifest.py` already does that for the
work that existed in July. This is the Phase E half, and it is a different
shape, because Phase E's outputs are archived JSONs rather than a build.

The question it answers is narrow and worth stating plainly: **for every
number this phase published, which file holds it, which script wrote it, and
which raw inputs did that script read.** If any link in that chain cannot be
named, the number is unsupported no matter how many checks passed when it was
written.

Three things it insists on.

Every archived artefact records the hashes of the files it was derived from,
and those hashes must still match the files on disk. That is what catches an
input being edited after the fact, which no amount of re-running the producer
would notice because the producer would simply agree with the new input.

Every producer must be in the evidence gate, and every gate command that
regenerates an artefact must be followed by a diff against the committed
copy. A producer nobody runs is a producer nobody checks.

Every artefact must have exactly one producer. Two scripts writing the same
file is how two answers end up under one name.

It also reports what it cannot vouch for, which on this repository is the
CI actions. They are pinned to a moving tag rather than to a commit, and a
release manifest that stayed quiet about that would be worth less than one
that says so.

Usage:
    python3 release_manifest.py --selftest
    python3 release_manifest.py
    python3 release_manifest.py --json /tmp/release.json
"""

import argparse
import collections
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# The workflow is at ci/gds.yaml in the working tree and at
# .github/workflows/gds.yaml in the clone, because that is where GitHub
# looks. Same file, two homes, so look in both rather than assume one.
GATE_CANDIDATES = (os.path.join(ROOT, "ci", "gds.yaml"),
                   os.path.join(ROOT, ".github", "workflows", "gds.yaml"))


def find_gate():
    for p in GATE_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


GATE = find_gate() or GATE_CANDIDATES[0]
BUILD = os.path.join(ROOT, "dualarm", "build_current")
DESIGN = "tt_um_nikodemetrashvili20_ro_puf"

# Which script writes which archived artefact. One producer each; the check
# below refuses a second.
PRODUCERS = {
    "TILE_BUDGET.json": "tile_budget.py",
    "ARMC_COST.json": "armc_cost.py",
    "G2_DECISION.json": "g2_decision.py",
    "OBSERVABILITY.json": "observability_spec.py",
    "e2_acceptance.csv": "observability_spec.py",
    "ARMC_REGIONS.json": "gen_armc.py",
    "armc_place.tcl": "gen_armc.py",
    "ro_armc.v": "gen_armc.py",
    "e2_ro_puf_core.v": "gen_e2_rtl.py",
    "e2_ro_puf.v": "gen_e2_rtl.py",
    "e2_tt_um_ro_puf.v": "gen_e2_rtl.py",
    "e2_tb_plan.csv": "gen_e2_rtl.py",
    "G3_RUNBOOK_CHECK.json": "g3_runbook.py",
    "RTL_LINT.json": "lint_rtl.py",
    "RELEASE_MANIFEST.json": "release_manifest.py",
}

# Written by hand and checked by a script, but not gated on a hash. The
# runbook belongs here rather than under FROZEN: a plan that cannot be
# revised when a step turns out to be wrong is only a way of being wrong on
# schedule, so what is required of it is a checker, not a hash.
AUTHORED = {"G3_RUNBOOK.json": "g3_runbook.py"}

# This script's own output. See the note where produced records are built.
SELF = "RELEASE_MANIFEST.json"

# Frozen by hand and gated on a hash rather than regenerated. These have no
# producer on purpose and the check knows it.
FROZEN = ("G2_CRITERIA.json", "PREREGISTRATION.json")

# The raw build files Phase E reads. Nothing else in the phase touches the
# build.
RAW = (DESIGN + ".def", DESIGN + ".nl.v", DESIGN + ".nom.spef",
       "metrics.json", "dualarm_positions.csv",
       "dualarm_par_out.txt", "dualarm_par_ss_out.txt",
       "dualarm_par_ff_out.txt")

ACTION_RE = re.compile(r"uses:\s*([\w.-]+/[\w./-]+)@([\w.-]+)")


def sha256_file(path):
    """The bytes a checkout produces, not the bytes on this disk.

    `.gitattributes` opens with `* text=auto`, so git stores a text file
    with LF endings whatever the machine that wrote it used. Hash the raw
    bytes of a CRLF file and the number recorded is one CI can never
    reproduce. That is what put TILE_BUDGET.json's macro_lef entry wrong
    on 31 August and held the evidence gate red for five pushes.

    The test below is git's own and both halves of it matter: a NUL in
    the first 8000 bytes, or a carriage return with no line feed behind
    it, and git leaves the file alone. It reads no attributes, which is
    safe only while no explicit rule contradicts the heuristic, and that
    is what chip/hash_stability.py H03 and H04 are there to require."""
    with open(path, "rb") as fh:
        blob = fh.read()
    if b"\x00" in blob[:8000] or blob.count(b"\r") != blob.count(b"\r\n"):
        return hashlib.sha256(blob).hexdigest()
    return hashlib.sha256(blob.replace(b"\r\n", b"\n")).hexdigest()


class Results(object):
    def __init__(self):
        self.rows = []

    def add(self, cid, name, ok, detail=""):
        self.rows.append({"id": cid, "name": name, "pass": bool(ok),
                          "detail": detail})
        return ok

    def failed(self):
        return [r["id"] for r in self.rows if not r["pass"]]


# ------------------------------------------------------------------ reading

def gate_commands(text):
    """The archived-evidence job's command list, in order."""
    m = re.search(r"^  archived-evidence:(.*?)^  \w+:", text, re.S | re.M)
    body = m.group(1) if m else ""
    out = []
    for line in body.split("\n"):
        s = line.strip()
        if s.startswith(("python3 ", "diff ", "test ", "bash ")):
            out.append(s)
    return out


def declared_sources(obj):
    """Every {name: sha256} a produced artefact recorded about its inputs."""
    out = {}
    src = obj.get("source") if isinstance(obj, dict) else None
    if isinstance(src, dict):
        h = src.get("sha256")
        if isinstance(h, dict):
            out.update(h)
        elif isinstance(h, str):
            out["def"] = h
        for k, v in src.items():
            if k != "sha256" and isinstance(v, str) and len(v) == 64:
                out[k] = v
    return out


def actions(text):
    return [{"action": a, "ref": r, "pinned_to_commit": len(r) == 40
             and all(c in "0123456789abcdef" for c in r.lower())}
            for a, r in ACTION_RE.findall(text)]


def named_producers(decl):
    """The scripts an artefact record names. One is the healthy case; the
    record is allowed to carry a list so that a clash can be seen rather
    than silently resolved."""
    p = decl.get("producer") if isinstance(decl, dict) else None
    if isinstance(p, str):
        return [p]
    if isinstance(p, (list, tuple)):
        return [x for x in p if isinstance(x, str)]
    return []


# ------------------------------------------------------------------- checks

def run_checks(files, produced, frozen, cmds, acts, raw_hashes, chip_dir):
    res = Results()

    missing = [n for n in PRODUCERS if n not in files]
    res.add("S01", "every artefact with a producer is on disk",
            not missing, ", ".join(sorted(missing)) or "none")

    missing_f = [n for n in FROZEN if n not in files]
    res.add("S02", "every frozen file is on disk", not missing_f,
            ", ".join(sorted(missing_f)) or "none")

    twice = [n for n, d in produced.items()
             if len(set(named_producers(d))) > 1]
    res.add("S03", "no artefact has more than one producer", not twice,
            ", ".join(sorted(twice)) or "none")

    scripts = sorted(n for n in files if n.endswith(".py"))
    orphan = [n for n in files
              if n not in PRODUCERS and n not in FROZEN
              and n not in AUTHORED and not n.endswith(".py")]
    res.add("S04", "every file in chip/ is a script, a producer's output, "
                   "authored or frozen", not orphan,
            ", ".join(sorted(orphan)) or "none")

    # Every script must appear in the gate, and every artefact regenerated in
    # the gate must be diffed against the committed copy afterwards.
    joined = "\n".join(cmds)
    absent = [s for s in scripts if "chip/%s" % s not in joined]
    res.add("S05", "every script in chip/ runs in the evidence gate",
            not absent, ", ".join(absent) or "none")

    undiffed = []
    for i, c in enumerate(cmds):
        m = re.match(r"python3 chip/(\S+\.py).*--(?:json|csv|emit)\s+(\S+)", c)
        if not m:
            continue
        later = "\n".join(cmds[i:i + 6])
        if "diff " not in later:
            undiffed.append(c.split()[1])
    res.add("S06", "every regenerated artefact is diffed against the archive",
            not undiffed, ", ".join(sorted(set(undiffed))) or "none")

    # The declared input hashes must still match the files on disk.
    stale = []
    for name, decl in sorted(produced.items()):
        for key, want in sorted(decl.get("sources", {}).items()):
            got = raw_hashes.get(key)
            if got is None:
                continue
            if got != want:
                stale.append("%s.%s" % (name, key))
    res.add("S07", "every recorded input hash still matches the file",
            not stale, ", ".join(stale) or "none")

    recorded = set()
    for decl in produced.values():
        recorded |= set(decl.get("sources", {}))
    res.add("S08", "at least one artefact records where the build came from",
            bool(recorded & {"def", "netlist", "spef", "metrics",
                             "positions", "macro_lef", "cost"}),
            ", ".join(sorted(recorded)) or "none")

    freezes = [c for c in cmds if "--freeze-check" in c]
    res.add("S09", "every frozen file has a freeze check in the gate",
            len(freezes) >= len(FROZEN) + 1,
            "%d freeze checks for %d frozen files plus the A.5 one"
            % (len(freezes), len(FROZEN)))

    unpinned = [a["action"] for a in acts if not a["pinned_to_commit"]]
    res.add("S10", "the release says whether the CI actions are pinned",
            True, "%d of %d actions pinned to a commit: %s"
            % (len(acts) - len(unpinned), len(acts),
               ", ".join(sorted(set(unpinned))) or "all pinned"))

    unchecked = [n for n, c in sorted(AUTHORED.items())
                 if c not in files]
    res.add("S12", "every authored file names a checker that is in chip/",
            not unchecked, ", ".join(unchecked) or
            "%d authored" % len(AUTHORED))

    res.add("S11", "every raw build file Phase E reads was found and hashed",
            all(k in raw_hashes for k in
                ("def", "netlist", "spef", "metrics", "positions")),
            "%d of %d found" % (len(raw_hashes), len(RAW)))
    return res


# ----------------------------------------------------------------- fixture

def fixture(mutate=None):
    files = dict((n, "h" + n) for n in
                 list(PRODUCERS) + list(FROZEN) + list(AUTHORED))
    for s in set(PRODUCERS.values()) | set(AUTHORED.values()) | {
            "verify_phaseE.py", "preregister.py", "release_manifest.py"}:
        files[s] = "h" + s
    produced = dict((n, {"producer": p,
                         "sources": {"def": "abc"} if n.endswith(".json")
                         else {}})
                    for n, p in PRODUCERS.items())
    cmds = []
    for s in sorted(set(PRODUCERS.values()) | set(AUTHORED.values()) | {
            "verify_phaseE.py", "preregister.py", "release_manifest.py"}):
        cmds.append("python3 chip/%s --selftest" % s)
        if s in set(PRODUCERS.values()):
            cmds.append("python3 chip/%s --json /tmp/x.json" % s)
            cmds.append("diff /tmp/x.json chip/out.json")
    cmds += ["python3 chip/g2_decision.py --freeze-check",
             "python3 chip/preregister.py --freeze-check",
             "python3 extraction/check_tolerances.py --freeze-check"]
    acts = [{"action": "actions/checkout", "ref": "v6",
             "pinned_to_commit": False}]
    raw = {"def": "abc", "netlist": "n", "spef": "s", "metrics": "m",
           "positions": "p"}
    if mutate:
        mutate(files, produced, cmds, acts, raw)
    return files, produced, cmds, acts, raw


def run_fixture(mutate=None):
    files, produced, cmds, acts, raw = fixture(mutate)
    return run_checks(files, produced, list(FROZEN), cmds, acts, raw, "chip")


def selftest():
    print("release_manifest selftest")
    ok = True
    res = run_fixture()
    if res.failed():
        print("  FAIL: clean fixture fails %s" % ", ".join(res.failed()))
        for r in res.rows:
            if not r["pass"]:
                print("        %s %s" % (r["id"], r["detail"]))
        ok = False
    else:
        print("  clean fixture passes all %d checks" % len(res.rows))

    faults = [
        ("S01", "an artefact its producer never wrote",
         lambda f, p, c, a, r: f.pop("TILE_BUDGET.json")),
        ("S02", "a frozen file that is gone",
         lambda f, p, c, a, r: f.pop("G2_CRITERIA.json")),
        ("S03", "two scripts claiming the same artefact",
         lambda f, p, c, a, r: p["TILE_BUDGET.json"].update(
             producer=["tile_budget.py", "armc_cost.py"])),
        ("S04", "a file in chip/ nothing accounts for",
         lambda f, p, c, a, r: f.update({"stray.txt": "x"})),
        ("S05", "a script the gate never runs",
         lambda f, p, c, a, r: c.__setitem__(
             slice(None), [x for x in c
                           if "chip/verify_phaseE.py" not in x])),
        ("S06", "an artefact regenerated and never diffed",
         lambda f, p, c, a, r: c.__setitem__(
             slice(None), [x for x in c if not x.startswith("diff ")])),
        ("S07", "an input edited after the artefact recorded its hash",
         lambda f, p, c, a, r: r.update(**{"def": "changed"})),
        ("S09", "a frozen file with no freeze check in the gate",
         lambda f, p, c, a, r: c.__setitem__(
             slice(None), [x for x in c if "--freeze-check" not in x])),
        ("S11", "a raw build file that was never found",
         lambda f, p, c, a, r: r.pop("spef")),
        ("S12", "an authored file whose checker is not in chip/",
         lambda f, p, c, a, r: f.pop("g3_runbook.py")),
    ]
    for want, label, fn in faults:
        r2 = run_fixture(lambda f, p, c, a, r, _fn=fn: _fn(f, p, c, a, r))
        tripped = set(r2.failed())
        if tripped == {want}:
            print("  ok    %-4s %s" % (want, label))
        elif want in tripped:
            print("  FAIL  %-4s %s -- also tripped %s"
                  % (want, label, ", ".join(sorted(tripped - {want}))))
            ok = False
        else:
            print("  FAIL  %-4s %s -- tripped %s"
                  % (want, label, ", ".join(sorted(tripped)) or "nothing"))
            ok = False

    # S08 and S10 report rather than gate on the fixture's own shape, so they
    # get their faults from the other side.
    r3 = run_fixture(lambda f, p, c, a, r: [d.update(sources={})
                                            for d in p.values()])
    if set(r3.failed()) == {"S08"}:
        print("  ok    S08  nothing recording which build it came from")
    else:
        print("  FAIL  S08  tripped %s" % (", ".join(r3.failed()) or "nothing"))
        ok = False

    pinned = actions("      uses: a/b@" + "0" * 40 + "\n"
                     "      uses: c/d@v3\n")
    good = (len(pinned) == 2 and pinned[0]["pinned_to_commit"]
            and not pinned[1]["pinned_to_commit"])
    print("  %-5s S10   a forty-character ref is a commit, a tag is not"
          % ("ok" if good else "FAIL"))
    ok = ok and good

    cmds = gate_commands("  archived-evidence:\n    steps:\n"
                         "      - run: |\n"
                         "          python3 a.py\n"
                         "          diff x y\n"
                         "          echo skip\n"
                         "  gds:\n")
    good2 = cmds == ["python3 a.py", "diff x y"]
    print("  %-5s parse the gate list takes commands and drops prose"
          % ("ok" if good2 else "FAIL"))
    ok = ok and good2

    print("\n  %s" % ("all faults isolated" if ok else "SELFTEST FAILED"))
    return 0 if ok else 1


# --------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    files = {}
    for n in sorted(os.listdir(HERE)):
        p = os.path.join(HERE, n)
        if os.path.isfile(p):
            files[n] = sha256_file(p)

    raw_hashes = {}
    keymap = {DESIGN + ".def": "def", DESIGN + ".nl.v": "netlist",
              DESIGN + ".nom.spef": "spef", "metrics.json": "metrics",
              "dualarm_positions.csv": "positions"}
    for n in RAW:
        p = os.path.join(BUILD, n)
        if os.path.exists(p):
            raw_hashes[keymap.get(n, n)] = sha256_file(p)
    lef = os.path.join(ROOT, "dualarm", "src", "ro_macro_hard.lef")
    if os.path.exists(lef):
        raw_hashes["macro_lef"] = sha256_file(lef)
    cost = os.path.join(HERE, "ARMC_COST.json")
    if os.path.exists(cost):
        raw_hashes["cost"] = sha256_file(cost)

    produced = {}
    for name, prod in sorted(PRODUCERS.items()):
        p = os.path.join(HERE, name)
        # A file cannot carry its own hash. Recording one for this manifest
        # would mean every run disagreed with the last, and the diff in the
        # gate would fail forever for a reason that has nothing to do with
        # the design. Its integrity comes from the gate regenerating it and
        # diffing, which is the same thing one level up.
        own = name == os.path.basename(a.json or "") or name == SELF
        rec = {"producer": prod,
               "sha256": None if own else files.get(name),
               "sources": {}}
        if name.endswith(".json") and os.path.exists(p):
            with open(p, "r", encoding="utf-8") as fh:
                try:
                    rec["sources"] = declared_sources(json.load(fh))
                except ValueError:
                    rec["sources"] = {}
        produced[name] = rec

    with open(GATE, "r", encoding="utf-8") as fh:
        gate_text = fh.read()
    cmds = gate_commands(gate_text)
    acts = actions(gate_text)

    res = run_checks(files, produced, list(FROZEN), cmds, acts, raw_hashes,
                     HERE)

    print("Phase E release manifest")
    print("  chip/      %d files, %d scripts, %d produced, %d frozen"
          % (len(files), len([n for n in files if n.endswith(".py")]),
             len(PRODUCERS), len(FROZEN)))
    print("  gate       %d commands, %d freeze checks"
          % (len(cmds), len([c for c in cmds if "--freeze-check" in c])))
    print("  raw inputs %d hashed from dualarm/build_current" % len(raw_hashes))
    print("  actions    %d, %d pinned to a commit"
          % (len(acts), len([x for x in acts if x["pinned_to_commit"]])))
    print()
    print("  %-24s %-22s %s" % ("artefact", "producer", "sha256"))
    for n in sorted(PRODUCERS):
        print("  %-24s %-22s %s" % (n, PRODUCERS[n],
                                    (files.get(n) or "MISSING")[:16]))
    for n in FROZEN:
        print("  %-24s %-22s %s" % (n, "frozen by hand",
                                    (files.get(n) or "MISSING")[:16]))
    print()
    for r in res.rows:
        print("  %-4s %-58s %s" % (r["id"], r["name"],
                                   "pass" if r["pass"] else "FAIL"))
    bad = res.failed()
    print("\n  %s" % ("all %d checks pass" % len(res.rows) if not bad
                      else "FAILED: " + ", ".join(bad)))
    for r in res.rows:
        if not r["pass"]:
            print("       %s: %s" % (r["id"], r["detail"]))
    for r in res.rows:
        if r["id"] == "S10":
            print("\n  note: %s" % r["detail"])

    if a.json:
        out = {"gate": "G.5", "phase": "E",
               # Same reason as the produced record: a file cannot hold
               # its own hash and still regenerate to itself.
               "chip_files": dict((k, None if k == SELF else v)
                                  for k, v in files.items()),
               "produced": produced,
               "frozen": dict((n, files.get(n)) for n in FROZEN),
               "raw_inputs": raw_hashes,
               "gate_commands": len(cmds),
               "actions": acts,
               "checks": res.rows}
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print("  wrote %s" % a.json)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
