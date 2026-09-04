#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""G.3: the order the Arm C build happens in, checked before it starts.

G.3 is the expensive gate. It re-hardens the design with a third arm and
repeats the whole evidence suite, and the plan gives it three to five days
plus machine time. Everything Phase E has produced so far exists so that
those days are spent building rather than deciding.

What is left is the order. `chip/G3_RUNBOOK.json` holds it: twelve steps,
each naming what it reads, what it writes, what makes you stop, and whether
it can be undone. This script checks that plan against the things that
already exist, which is the only kind of checking a plan can get before it
is executed.

Three things it is deliberately not.

It is not frozen by hash. `G2_CRITERIA.json` and `PREREGISTRATION.json` are,
because changing either after the fact would change what the result means. A
runbook is different. A plan that cannot be revised when a step turns out to
be wrong is only a way of being wrong on schedule. What gets checked is that
the plan is complete and consistent, not that it never moves.

It is not a script that runs the build. Nothing here invokes OpenLane,
touches `src/` or writes anything into the build tree. The build is done by
hand with this open beside it.

It is not a promise that the build works. Every step here can be
well-formed and the harden can still come back with a timing violation. What
the checks buy is that no step reads a file that does not exist yet, that
nothing overwrites a file that was never archived, and that the re-run at
the end covers everything the gate covers now.

Usage:
    python3 g3_runbook.py --selftest
    python3 g3_runbook.py
    python3 g3_runbook.py --json /tmp/g3.json
"""

import argparse
import copy
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

RUNBOOK = os.path.join(HERE, "G3_RUNBOOK.json")
MANIFEST = os.path.join(HERE, "RELEASE_MANIFEST.json")
ACCEPT = os.path.join(HERE, "e2_acceptance.csv")
TB_PLAN = os.path.join(HERE, "e2_tb_plan.csv")
# The acceptance testbench, which step 6 writes. Two homes, the same way the
# workflow has two: dualarm/test is what backup_to_repo.sh mirrors and test/
# is where it lands in the clone. Look in both rather than assume one.
TB_CANDIDATES = (os.path.join(ROOT, "test", "test_e2.py"),
                 os.path.join(ROOT, "dualarm", "test", "test_e2.py"))
# ci/gds.yaml here, .github/workflows/gds.yaml in the clone. Both.
GATE_CANDIDATES = (os.path.join(ROOT, "ci", "gds.yaml"),
                   os.path.join(ROOT, ".github", "workflows", "gds.yaml"))


def find_gate():
    for p in GATE_CANDIDATES:
        if os.path.exists(p):
            return p
    return None

# The two files that are frozen by hash. No step of the build may write
# either of them; that is the whole point of freezing them.
FROZEN = ("chip/G2_CRITERIA.json", "chip/PREREGISTRATION.json")

# Which producers in the release manifest emit RTL and placement input. The
# runbook installs what they emit; it does not get to name its own list.
GENERATORS = ("gen_armc.py", "gen_e2_rtl.py")


class Results(object):
    def __init__(self):
        self.rows = []

    def add(self, cid, name, ok, detail=""):
        self.rows.append({"id": cid, "name": name, "pass": bool(ok),
                          "detail": detail})
        return ok

    def failed(self):
        return [r["id"] for r in self.rows if not r["pass"]]


# ------------------------------------------------------------------ loading

def step_reads(step):
    """Everything a step consumes, with the install sources folded in.

    The installs are written once, in one place, and the read and the write
    are derived from them. Listing a file both as an install source and again
    under reads would let the two drift, and the drift would be invisible.
    """
    out = list(step.get("reads", []))
    for pair in step.get("installs", []):
        out.append(pair["from"])
    return out


def step_writes(step):
    out = list(step.get("writes", []))
    for pair in step.get("installs", []):
        out.append(pair["to"])
    return out


def first_writer(steps, path):
    """Index of the earliest step that writes path, or None."""
    for i, s in enumerate(steps):
        if path in step_writes(s):
            return i
    return None


def topo_violations(steps, pre_existing):
    """Reads of a file that does not exist yet and is written later.

    A file that is pre-existing is fine to read at any point, including
    before a step rewrites it: the archive reads the current release
    manifest and the last step writes a new one, and that is the intended
    order rather than a mistake.

    A read of something no step writes at all is not an ordering problem and
    is not reported here. That is B01's, and having both fire on it turned
    one mistake into two failing checks.
    """
    bad = []
    pre = set(pre_existing)
    for i, s in enumerate(steps):
        for path in step_reads(s):
            if path in pre:
                continue
            j = first_writer(steps, path)
            if j is not None and j > i:
                bad.append((s["id"], path))
    return bad


def unaccounted_reads(steps, pre_existing):
    """Reads that are neither pre-existing nor written by any step at all."""
    pre = set(pre_existing)
    out = []
    for s in steps:
        for path in step_reads(s):
            if path in pre:
                continue
            if first_writer(steps, path) is None:
                out.append((s["id"], path))
    return out


def gate_commands(text):
    """The shell lines of the archived-evidence job, prose dropped.

    Same shape as the release manifest's reader, and deliberately a separate
    copy: if the two ever disagree about what the gate runs, that is worth
    seeing rather than sharing a bug.
    """
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- ") or line.endswith(":") or ": " in line:
            if not line.startswith(("python3", "diff", "test", "grep")):
                continue
        if line.startswith(("python3", "diff ", "test ", "grep ")):
            out.append(line)
    return out


def tb_tests():
    """The row ids the acceptance testbench has a test for.

    test_e2_07 covers E2-07. Nothing clever: the naming is the contract, and
    B16 below is what makes it one.
    """
    for path in TB_CANDIDATES:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                names = re.findall(r"^(?:async )?def (test_e2_(\d+))\(",
                                   fh.read(), re.M)
            return sorted("E2-%s" % n for _, n in names)
    return None


def csv_rows(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return [r for r in csv.reader(fh) if r and r[0].strip()][1:]


# ------------------------------------------------------------------- checks

def run_checks(book, emitted, gate_scripts, produced, raw_keys,
               accept_n, plan_n, plan_ids=None, tb_ids=None):
    res = Results()
    steps = book["steps"]
    pre = book.get("pre_existing", [])
    ids = [s["id"] for s in steps]
    index = dict((sid, i) for i, sid in enumerate(ids))

    orphan = unaccounted_reads(steps, pre)
    res.add("B01", "every file a step reads is pre-existing or written by "
                   "some step", not orphan,
            ", ".join("%s:%s" % o for o in orphan) or "none")

    seen = {}
    twice = []
    for s in steps:
        for path in step_writes(s):
            if path in seen:
                twice.append("%s (%s, %s)" % (path, seen[path], s["id"]))
            else:
                seen[path] = s["id"]
    res.add("B02", "no file is written by two steps", not twice,
            ", ".join(sorted(twice)) or "none")

    installs = {}
    for s in steps:
        for pair in s.get("installs", []):
            installs[pair["from"]] = pair["to"]
    want_rtl = set(n for n in emitted if n.endswith(".v"))
    got_rtl = set(os.path.basename(p) for p in installs
                  if p.endswith(".v"))
    other = set(n for n in emitted if not n.endswith(".v"))
    read_any = set()
    for s in steps:
        for path in step_reads(s):
            read_any.add(os.path.basename(path))
    miss_rtl = sorted((want_rtl - got_rtl) | (got_rtl - want_rtl))
    miss_other = sorted(n for n in other if n not in read_any)
    res.add("B03", "the runbook installs exactly the RTL the generators "
                   "emit, and reads the rest of what they emit",
            not miss_rtl and not miss_other,
            ", ".join(miss_rtl + miss_other) or
            "%d installed, %d fed to a step" % (len(got_rtl), len(other)))

    late = topo_violations(steps, pre)
    res.add("B04", "no step reads a file a later step is the first to write",
            not late, ", ".join("%s:%s" % o for o in late) or "none")

    stops = [s.get("stop", "").strip() for s in steps]
    empty = [s["id"] for s in steps if not s.get("stop", "").strip()]
    dupes = sorted(set(x for x in stops if x and stops.count(x) > 1))
    res.add("B05", "every step has a stop condition and no two share one",
            not empty and not dupes,
            ", ".join(empty) or (", ".join(d[:40] for d in dupes) or "none"))

    arch = book.get("archive_step")
    arch_at = index.get(arch)
    early = [s["id"] for i, s in enumerate(steps)
             if s.get("irreversible") and (arch_at is None or i < arch_at)]
    res.add("B06", "every irreversible step comes after the archive",
            arch_at is not None and not early,
            ", ".join(early) or "archive at step %s" % (arch_at + 1))

    rerun = None
    for s in steps:
        if s.get("covers"):
            rerun = s
    covered = set(rerun.get("covers", [])) if rerun else set()
    uncovered = sorted(set(gate_scripts) - covered)
    res.add("B07", "the re-run step covers every script the gate runs",
            bool(rerun) and bool(gate_scripts) and not uncovered,
            ", ".join(uncovered) or
            ("the gate was not found, so this proved nothing"
             if not gate_scripts else "%d of %d scripts"
             % (len(gate_scripts), len(covered))))

    sim = None
    for s in steps:
        if "test_count" in s:
            sim = s
    declared = sim.get("test_count") if sim else None
    res.add("B08", "the acceptance table, the stimulus plan and the sim "
                   "step agree on how many tests there are",
            declared is not None and declared == accept_n == plan_n,
            "step %s, table %s, plan %s" % (declared, accept_n, plan_n))

    # B08 counts the rows. B16 asks whether anything runs them. A plan and a
    # table that agree on 21 while the testbench covers 19 is exactly the
    # shape B07 was caught in on 31 August: green, and proving nothing.
    want = sorted(plan_ids or [])
    have = tb_ids
    if have is None:
        missing = ["no test_e2.py found in either tree"]
    else:
        missing = sorted(set(want) - set(have)) + \
            ["%s has no row" % x for x in sorted(set(have) - set(want))]
    res.add("B16", "every row of the stimulus plan has a test in the "
                   "acceptance testbench",
            bool(want) and not missing,
            ", ".join(missing) or "%d rows, %d tests" % (len(want), len(have)))

    total = sum(float(s.get("days", 0)) for s in steps)
    lo, hi = book["budget_days"]
    res.add("B09", "the steps sum to something inside the plan's budget",
            lo <= total <= hi, "%.2f days against %s to %s" % (total, lo, hi))

    # The path moved to dualarm/info.yaml on 2026-09-01, and the root
    # copy is a resync of it rather than a second thing to edit, so
    # match on the basename and not on the whole path.
    yaml_steps = [s for s in steps
                  if any(os.path.basename(w) == "info.yaml"
                         for w in step_writes(s))]
    inv = set(yaml_steps[0].get("invariants", [])) if yaml_steps else set()
    res.add("B10", "info.yaml is edited by one step and that step holds the "
                   "tile count and top module fixed",
            len(yaml_steps) == 1 and {"tiles", "top_module"} <= inv,
            "%d steps write it, invariants %s"
            % (len(yaml_steps), ", ".join(sorted(inv)) or "none"))

    regen = set(rerun.get("regenerates", [])) if rerun else set()
    missing = sorted(set(produced) - regen)
    res.add("B11", "every artefact the manifest attributes to a producer is "
                   "regenerated after the build", not missing,
            ", ".join(missing) or "%d artefacts" % len(regen))

    archived = set()
    for s in steps:
        archived |= set(s.get("archives", []))
    unsafe = []
    for s in steps:
        if not s.get("irreversible"):
            continue
        for path in step_writes(s):
            if path in book.get("pre_existing", []) and path not in archived:
                unsafe.append("%s:%s" % (s["id"], path))
    res.add("B12", "no irreversible step overwrites a file the archive step "
                   "did not take a copy of", not unsafe,
            ", ".join(sorted(unsafe)) or "%d archived" % len(archived))

    frozen_writes = []
    for s in steps:
        for path in step_writes(s):
            if path in FROZEN:
                frozen_writes.append("%s:%s" % (s["id"], path))
    res.add("B13", "no step writes a file that is frozen by hash",
            not frozen_writes, ", ".join(sorted(frozen_writes)) or "none")

    unresolved = []
    for i, s in enumerate(steps):
        for ef in s.get("expected_failures", []):
            j = index.get(ef.get("resolved_by"))
            if j is None or j <= i or ef.get("file") not in step_writes(
                    steps[j]):
                unresolved.append("%s:%s" % (s["id"], ef.get("file")))
    res.add("B15", "every failure the run is expected to produce names a "
                   "later step that writes the file it is about",
            not unresolved, ", ".join(sorted(unresolved)) or
            "%d declared" % sum(len(s.get("expected_failures", []))
                                for s in steps))

    made = set()
    for s in steps:
        made |= set(s.get("produces_raw", []))
    carried = set(book.get("raw_carried_forward", {}))
    short = sorted(set(raw_keys) - made - carried)
    both = sorted(made & carried)
    res.add("B14", "every raw input the manifest hashes is either remade by "
                   "the build or carried forward with a reason",
            not short and not both,
            ", ".join(short + both) or
            "%d remade, %d carried" % (len(made), len(carried)))

    return res


# ------------------------------------------------------------------ fixture

FIX_EMITTED = ("armc_place.tcl", "ro_armc.v", "e2_ro_puf_core.v",
               "e2_ro_puf.v", "e2_tt_um_ro_puf.v")
FIX_GATE = ("tile_budget.py", "armc_cost.py", "g2_decision.py",
            "observability_spec.py", "gen_armc.py", "gen_e2_rtl.py",
            "verify_phaseE.py", "preregister.py", "release_manifest.py",
            "g3_runbook.py")
FIX_PRODUCED = ("TILE_BUDGET.json", "ARMC_COST.json", "G2_DECISION.json",
                "OBSERVABILITY.json", "e2_acceptance.csv",
                "ARMC_REGIONS.json", "armc_place.tcl", "ro_armc.v",
                "e2_ro_puf_core.v", "e2_ro_puf.v", "e2_tt_um_ro_puf.v",
                "e2_tb_plan.csv")
FIX_RAW = ("def", "netlist", "spef", "metrics", "positions")


FIX_ROWS = tuple("E2-%02d" % i for i in range(1, 22))


def fixture(book, mutate=None):
    """The committed runbook plus a stand-in for everything around it.

    The plan itself is the real one rather than a synthetic. A fault planted
    in a made-up runbook would only prove the checks can read a made-up
    runbook, and the clean pass at the top of the selftest is then a
    statement about the file that actually ships.
    """
    ctx = {"book": copy.deepcopy(book),
           "emitted": list(FIX_EMITTED),
           "gate": list(FIX_GATE),
           "produced": list(FIX_PRODUCED),
           "raw": list(FIX_RAW),
           "accept_n": 21,
           "plan_n": 21,
           "plan_ids": list(FIX_ROWS),
           "tb_ids": list(FIX_ROWS)}
    if mutate:
        mutate(ctx)
    return ctx


def run_fixture(book, mutate=None):
    c = fixture(book, mutate)
    return run_checks(c["book"], c["emitted"], c["gate"], c["produced"],
                      c["raw"], c["accept_n"], c["plan_n"],
                      c["plan_ids"], c["tb_ids"])


def find_step(book, sid):
    for s in book["steps"]:
        if s["id"] == sid:
            return s
    raise KeyError(sid)


def f_b01(c):
    find_step(c["book"], "lint")["reads"].append("dualarm/src/ro_armd.v")


def f_b16(c):
    c["tb_ids"] = [x for x in c["tb_ids"] if x != "E2-21"]


def f_b02(c):
    find_step(c["book"], "recut-release")["writes"].append(
        "dualarm/build_2arm_frozen/MANIFEST.txt")


def f_b03(c):
    # Drop the core install, not the Arm C one. dualarm/src/ro_puf_core.v
    # already exists, so removing its install leaves no dangling read;
    # removing dualarm/src/ro_armc.v would, and B01 would fire on that
    # instead.
    s = find_step(c["book"], "install-rtl")
    s["installs"] = [p for p in s["installs"]
                     if p["from"] != "chip/e2_ro_puf_core.v"]


def f_b04(c):
    find_step(c["book"], "lint")["reads"].append(
        "dualarm/build_armc/metrics.json")


def f_b05(c):
    a = find_step(c["book"], "lint")
    find_step(c["book"], "sim-two-arm-regression")["stop"] = a["stop"]


def f_b06(c):
    steps = c["book"]["steps"]
    moved = find_step(c["book"], "update-infoyaml")
    steps.remove(moved)
    steps.insert(0, moved)


def f_b07(c):
    s = find_step(c["book"], "rerun-evidence")
    s["covers"] = [x for x in s["covers"] if x != "verify_phaseE.py"]


def f_b08(c):
    find_step(c["book"], "sim-e2-acceptance")["test_count"] = 20


def f_b09(c):
    find_step(c["book"], "harden")["days"] = 4.0


def f_b10(c):
    s = find_step(c["book"], "update-infoyaml")
    s["invariants"] = [x for x in s["invariants"] if x != "tiles"]


def f_b11(c):
    s = find_step(c["book"], "rerun-evidence")
    s["regenerates"] = [x for x in s["regenerates"]
                        if x != "TILE_BUDGET.json"]


def f_b12(c):
    s = find_step(c["book"], "archive-baseline")
    s["archives"] = [x for x in s["archives"]
                     if x != "dualarm/src/ro_puf.v"]


def f_b13(c):
    find_step(c["book"], "archive-baseline")["writes"].append(
        "chip/G2_CRITERIA.json")


def f_b15(c):
    s = find_step(c["book"], "rerun-evidence")
    s["expected_failures"][0]["resolved_by"] = "archive-baseline"


def f_b14(c):
    s = find_step(c["book"], "extract")
    s["produces_raw"] = [x for x in s["produces_raw"] if x != "spef"]


FAULTS = (
    ("B01", "a step reading a file nothing on the plan produces", f_b01),
    ("B02", "two steps writing the same file", f_b02),
    ("B03", "an emitted module the build never installs", f_b03),
    ("B04", "a step reading what a later step is the first to write", f_b04),
    ("B05", "two steps sharing one stop condition", f_b05),
    ("B06", "an irreversible edit before anything is archived", f_b06),
    ("B07", "a gate script the re-run does not cover", f_b07),
    ("B08", "a sim step that has lost count of its own tests", f_b08),
    ("B09", "a build that no longer fits the budget it was given", f_b09),
    ("B10", "an info.yaml edit with the tile count no longer held", f_b10),
    ("B11", "an artefact never regenerated against the new build", f_b11),
    ("B12", "an overwrite of a file the archive step forgot", f_b12),
    ("B13", "a step writing a file that is frozen by hash", f_b13),
    ("B14", "a raw input the build never remakes", f_b14),
    ("B15", "a known failure pointed at a step that cannot fix it", f_b15),
    ("B16", "a plan row with no test behind it", f_b16),
)


def selftest(book):
    print("g3_runbook selftest")
    ok = True
    res = run_fixture(book)
    if res.failed():
        print("  FAIL: the committed runbook fails %s"
              % ", ".join(res.failed()))
        for r in res.rows:
            if not r["pass"]:
                print("        %s %s" % (r["id"], r["detail"]))
        ok = False
    else:
        print("  the committed runbook passes all %d checks" % len(res.rows))

    for cid, name, fn in FAULTS:
        got = run_fixture(book, fn).failed()
        if got == [cid]:
            print("  ok    %s  %s" % (cid, name))
        else:
            print("  FAIL  %s  %s -- tripped %s"
                  % (cid, name, ", ".join(got) or "nothing"))
            ok = False

    # The order walk, against arithmetic that does not call it.
    # x is written before it is read, y after, z never. Only y is an
    # ordering fault.
    toy = [{"id": "a", "reads": [], "writes": ["x"]},
           {"id": "b", "reads": ["x", "y", "z"], "writes": []},
           {"id": "c", "reads": [], "writes": ["y"]}]
    got = topo_violations(toy, [])
    if got == [("b", "y")]:
        print("  ok    the order walk catches a read of a later write only")
    else:
        print("  FAIL  the order walk said %s" % (got,))
        ok = False

    print("")
    print("  all faults isolated" if ok else "  SELFTEST FAILED")
    return 0 if ok else 1


# --------------------------------------------------------------------- main

def gather():
    book = json.load(open(RUNBOOK, encoding="utf-8"))
    man = json.load(open(MANIFEST, encoding="utf-8"))

    produced = sorted(man.get("produced", {}))
    emitted = sorted(n for n, rec in man.get("produced", {}).items()
                     if rec.get("producer") in GENERATORS)
    raw_keys = sorted(man.get("raw_inputs", {}))

    gate_scripts = []
    gate = find_gate()
    if gate:
        text = open(gate, encoding="utf-8").read()
        for c in gate_commands(text):
            m = re.match(r"python3 chip/(\S+\.py)", c)
            if m and m.group(1) not in gate_scripts:
                gate_scripts.append(m.group(1))

    accept_rows = csv_rows(ACCEPT)
    plan_rows = csv_rows(TB_PLAN)
    return (book, emitted, gate_scripts, produced, raw_keys,
            len(accept_rows), len(plan_rows),
            [r[0].strip() for r in plan_rows], tb_tests())


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--json", help="write the checked runbook here")
    a = ap.parse_args()

    book = json.load(open(RUNBOOK, encoding="utf-8"))
    if a.selftest:
        return selftest(book)

    (book, emitted, gate, produced, raw, accept_n, plan_n,
     plan_ids, tb_ids) = gather()
    steps = book["steps"]
    res = run_checks(book, emitted, gate, produced, raw, accept_n, plan_n,
                     plan_ids, tb_ids)

    total = sum(float(s.get("days", 0)) for s in steps)
    print("Phase G.3 build runbook")
    print("  %d steps, %.2f days, budget %s to %s"
          % (len(steps), total, book["budget_days"][0],
             book["budget_days"][1]))
    print("  %d scripts in the gate, %d artefacts, %d raw inputs"
          % (len(gate), len(produced), len(raw)))

    found = sum(1 for p in book.get("pre_existing", [])
                if os.path.exists(os.path.join(ROOT, p)))
    print("  %d of %d pre-existing inputs are present in this tree"
          % (found, len(book.get("pre_existing", []))))
    print("")

    print("  %-4s %-28s %5s  %s" % ("", "step", "days", "undo"))
    for i, s in enumerate(steps):
        print("  %-4s %-28s %5.2f  %s"
              % ("%d." % (i + 1), s["id"], s.get("days", 0),
                 "no" if s.get("irreversible") else "yes"))
    print("")

    for r in res.rows:
        print("  %s  %-62s %s"
              % (r["id"], r["name"], "pass" if r["pass"] else "FAIL"))
    bad = res.failed()
    if bad:
        print("")
        print("  FAILED: %s" % ", ".join(bad))
        for r in res.rows:
            if not r["pass"]:
                print("       %s: %s" % (r["id"], r["detail"]))
    else:
        print("")
        print("  all %d checks pass" % len(res.rows))

    if a.json:
        out = {"gate": "G.3",
               "written": book["written"],
               "steps": [{"id": s["id"], "title": s["title"],
                          "days": s.get("days", 0),
                          "irreversible": bool(s.get("irreversible")),
                          "reads": sorted(step_reads(s)),
                          "writes": sorted(step_writes(s)),
                          "stop": s["stop"]} for s in steps],
               "total_days": total,
               "budget_days": book["budget_days"],
               "checks": res.rows}
        with open(a.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(out, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print("  wrote %s" % a.json)

    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
