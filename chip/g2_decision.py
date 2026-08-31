#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""The G.2 gate: Arm C or the load ladder, against a rule frozen first.

G.2's acceptance condition is that research value, area, cost and schedule
are documented. This script does the part of that a script can do honestly.

It does not score research value. A weighted total where the same person
picks both the weights and the scores is an opinion in a table, and the
argument between the two options is written out in
`docs/phaseE_g2_decision.md` where a reader can disagree with it. What lives
here is the filter: six hard constraints, every one of them evaluated against
a number measured in E.1a or E.1b, applied to every size and density of both
options. An option that fails a hard constraint is out and no amount of
research value brings it back.

`G2_CRITERIA.json` is the rule and it was written on 27 August, before either
option had been put through it. Its SHA-256 is recorded here, in the writeup
and in `PLAN_TO_DECEMBER.md`, and `--freeze-check` requires every one of
those it can see to agree. In CI it sees two: the plan is not mirrored to the
public clone, so it is reported as absent there rather than silently passing.
That is the same discipline `check_tolerances.py` applies to the A.5
tolerances and for the same reason: a threshold written after seeing the
answer is a description of the answer.

Two of the criteria inputs are estimates rather than measurements, the
working days each option takes to build and the risk that the flow cannot
deliver it. Both live in the criteria file rather than in this script, so
they were frozen with the rule instead of chosen next to the result, and both
carry the reasoning they rest on.

Usage:
    python3 g2_decision.py --selftest
    python3 g2_decision.py --freeze-check
    python3 g2_decision.py
    python3 g2_decision.py --json /tmp/g2.json
"""

import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

CRITERIA = os.path.join(HERE, "G2_CRITERIA.json")
BUDGET = os.path.join(HERE, "TILE_BUDGET.json")
COST = os.path.join(HERE, "ARMC_COST.json")

# SHA-256 of G2_CRITERIA.json as frozen on 2026-08-27. Also written into
# docs/phaseE_g2_decision.md and PLAN_TO_DECEMBER.md. All four have to agree.
FROZEN_SHA256 = \
    "c4e3d3049d0e99b21974bf77413c83a7da90a3a5c18a61bafad5079757a62c77"

OPS = {
    "<=": lambda a, b: a <= b,
    ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b,
    "<": lambda a, b: a < b,
    ">": lambda a, b: a > b,
}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class Results(object):
    def __init__(self):
        self.rows = []

    def add(self, cid, name, ok, detail=""):
        self.rows.append({"id": cid, "name": name, "pass": bool(ok),
                          "detail": detail})
        return ok

    def failed(self):
        return [r["id"] for r in self.rows if not r["pass"]]


# ------------------------------------------------------------- the options

def build_options(budget, cost, criteria):
    """One row per priced configuration, carrying every field the criteria
    name. Nothing here decides anything; it only puts the numbers measured on
    the two previous days into the shape the rule expects."""
    inputs = criteria["declared_inputs"]
    existing = criteria["existing_oscillators"]
    committed = criteria["committed"]["tiles"]
    free = budget["free"]["area_um2"]
    rows = []

    for r in cost["priced"]["armc"]:
        rows.append({
            "option": "armc",
            "label": "Arm C, %d rings, %s density"
                     % (r["rings"], r["density_label"]),
            "new_oscillators": r["rings"],
            "existing_oscillators": existing,
            "area_um2": r["total_um2"],
            "pct_of_free": r["pct_of_free"],
            # Nothing is added to the die, so the tile count only changes if
            # the option does not fit in the free row area.
            "tiles_required": committed if r["total_um2"] <= free
            else committed + 1,
            "extra_input_pins": r["extra_select_bits"],
            "build_days": inputs["armc"]["build_days"],
            "delivery_risk": inputs["armc"]["delivery_risk"],
            "routed_um": r["routed_um"],
        })

    for r in cost["priced"]["ladder"]:
        rows.append({
            "option": "ladder",
            "label": "load ladder, %d rungs" % r["rungs"],
            "new_oscillators": r["rungs"],
            "existing_oscillators": existing,
            "area_um2": r["total_um2"],
            "pct_of_free": r["pct_of_free"],
            "tiles_required": committed if r["total_um2"] <= free
            else committed + 1,
            "extra_input_pins": r["extra_select_bits"],
            "build_days": inputs["ladder"]["build_days"],
            "delivery_risk": inputs["ladder"]["delivery_risk"],
            "routed_um": r["routed_um"],
        })

    # Building both. The plan says not to force both into a compromised
    # floorplan, and that is a judgement, so rather than assert it the
    # combination goes on the table and the frozen rule gets to answer. Its
    # area is the two added, its days are the two builds one after the other,
    # and its oscillator count is both new arms.
    big = max(cost["priced"]["ladder"], key=lambda r: r["rungs"])
    for r in cost["priced"]["armc"]:
        if r["rings"] != max(x["rings"] for x in cost["priced"]["armc"]):
            continue
        total = r["total_um2"] + big["total_um2"]
        rows.append({
            "option": "both",
            "label": "both, %d rings %s + %d rungs"
                     % (r["rings"], r["density_label"], big["rungs"]),
            "new_oscillators": r["rings"] + big["rungs"],
            "existing_oscillators": existing,
            "area_um2": total,
            "pct_of_free": round(100.0 * total / free, 2),
            "tiles_required": committed if total <= free else committed + 1,
            "extra_input_pins": max(r["extra_select_bits"],
                                    big["extra_select_bits"]),
            "build_days": (inputs["armc"]["build_days"]
                           + inputs["ladder"]["build_days"]),
            "delivery_risk": inputs["armc"]["delivery_risk"],
            "routed_um": r["routed_um"] + big["routed_um"],
        })
    return rows


def apply_rule(rows, criteria):
    """Every well-formed hard constraint against every option, no partial
    credit.

    A constraint naming a field the options do not carry, or using an
    operator this script has no code for, is malformed and is skipped rather
    than counted as a failure. That is deliberate. A malformed rule is a
    wiring mistake in the gate, not a verdict on an option, and if it were
    scored as a failure it would knock every option out at once and the
    "nothing survives" check would fire instead of the one that can say what
    is actually wrong. G02 and G03 are the checks that catch it.
    """
    for row in rows:
        failed = []
        for h in criteria["hard"]:
            if h["field"] not in row or h["op"] not in OPS:
                continue
            if not OPS[h["op"]](row[h["field"]], h["value"]):
                failed.append("%s (%s %s %s is false)"
                              % (h["id"], row[h["field"]], h["op"],
                                 h["value"]))
        row["failed"] = failed
        row["survives"] = not failed
    return rows


def recommend(rows, criteria):
    """The preference order, applied to whatever survived.

    The first two entries in the order are about research value and this
    script does not judge them, so it stops at the point where judgement
    starts and hands back every survivor grouped by option. What it does
    settle is the size: within an option, the largest surviving ring count,
    because more independent oscillators is strictly better for every
    comparison the paper wants to make and nothing in the rule penalises it.
    """
    survivors = [r for r in rows if r["survives"]]
    best = {}
    for r in survivors:
        cur = best.get(r["option"])
        if cur is None or r["new_oscillators"] > cur["new_oscillators"] or (
                r["new_oscillators"] == cur["new_oscillators"]
                and r["area_um2"] > cur["area_um2"]):
            best[r["option"]] = r
    return survivors, best


# -------------------------------------------------------------- the checks

def run_checks(budget, cost, criteria, rows, survivors, best,
               criteria_path=CRITERIA, frozen=None):
    res = Results()
    frozen = FROZEN_SHA256 if frozen is None else frozen
    got = sha256_file(criteria_path)
    res.add("G01", "the criteria file is the one that was frozen",
            got == frozen, "sha256 %s" % got)

    fields = set(h["field"] for h in criteria["hard"])
    missing = sorted(f for f in fields for r in rows if f not in r)
    res.add("G02", "every option carries every field the rule names",
            not missing, "missing: %s" % (", ".join(sorted(set(missing)))
                                          or "none"))

    bad_ops = sorted(set(h["op"] for h in criteria["hard"])
                     - set(OPS))
    res.add("G03", "the rule uses only operators this script implements",
            not bad_ops, "unknown: %s" % (", ".join(bad_ops) or "none"))

    bh = budget.get("source", {}).get("sha256", {}).get("def")
    ch = cost.get("source", {}).get("sha256", {}).get("def")
    res.add("G04", "both input files describe the same placed DEF",
            bh is not None and bh == ch,
            "budget %s, cost %s" % (str(bh)[:12], str(ch)[:12]))

    free = budget["free"]["area_um2"]
    res.add("G05", "the cost file was priced against this free area",
            abs(cost.get("free_area_um2", -1) - free) < 0.001,
            "%s in cost, %s in budget" % (cost.get("free_area_um2"), free))

    off = []
    for r in cost["priced"]["armc"] + cost["priced"]["ladder"]:
        want = 100.0 * r["total_um2"] / free
        if abs(want - r["pct_of_free"]) > 0.01:
            off.append(r.get("density_label", "") + str(r.get("rings")
                                                        or r.get("rungs")))
    res.add("G06", "each option's share of the free area is its own arithmetic",
            not off, "%d rows off: %s" % (len(off), ", ".join(off[:3])))

    tiles = criteria["committed"]["tiles"]
    tw, th = criteria["committed"]["standard_tile_um"]
    ratio = (budget["die"]["width_um"] / tw, budget["die"]["height_um"] / th)
    res.add("G07", "the die is about two standard tiles on each side",
            1.9 <= ratio[0] <= 2.3 and 1.9 <= ratio[1] <= 2.3,
            "%.2f x %.2f tiles, committed %s" % (ratio + (tiles,)))

    res.add("G08", "at least one option clears every hard constraint",
            bool(survivors), "%d of %d survive" % (len(survivors), len(rows)))

    res.add("G09", "every recommended option is one that survived",
            all(b in survivors for b in best.values()),
            "%d recommendations" % len(best))

    # A rule that passes everything put to it is decorative. The first
    # version of this check tested that by requiring some real option to be
    # rejected, and it failed on the first real run: all twelve survive,
    # because the die has enough spare room that nothing on the table is
    # close to any limit. That is a fact about the floorplan, not a fault, so
    # the check was wrong rather than the data. See the writeup.
    #
    # What replaces it is a control. A probe that is unacceptable on every
    # axis is run through the same rule, and every constraint has to reject
    # it. The probe is built here and is never an option; it cannot pass by
    # the space happening to be roomy.
    probe = {"option": "probe", "label": "control probe",
             "new_oscillators": 0, "existing_oscillators": 0,
             "area_um2": 1e9, "pct_of_free": 1e6, "tiles_required": 99,
             "extra_input_pins": 9, "build_days": 999,
             "delivery_risk": "n/a", "routed_um": 0.0}
    apply_rule([probe], criteria)
    want = set(h["id"] for h in criteria["hard"]
               if h["field"] in probe and h["op"] in OPS)
    got = set(f.split(" ")[0] for f in probe["failed"])
    res.add("G10", "every constraint rejects a deliberately hopeless probe",
            got == want and bool(want),
            "rejected by %s, expected %s"
            % (",".join(sorted(got)) or "nothing", ",".join(sorted(want))))
    return res


# ------------------------------------------------------------------ report

def report(rows, survivors, best, criteria, budget):
    print("G.2 gate, rule frozen %s, sha256 %s"
          % (criteria["frozen"], sha256_file(CRITERIA)[:16]))
    print("Free row area from E.1a: %.3f um2. Committed tiles: %s (%d).\n"
          % (budget["free"]["area_um2"], criteria["committed"]["tiles_string"],
             criteria["committed"]["tiles"]))
    print("Hard constraints")
    for h in criteria["hard"]:
        print("  %-4s %-56s %s %s" % (h["id"], h["name"], h["op"],
                                      h["value"]))
    print()
    print("  %-34s %10s %8s %6s %5s %5s  %s"
          % ("option", "area um2", "of free", "tiles", "pins", "days",
             "verdict"))
    for r in rows:
        print("  %-34s %10.1f %7.2f%% %6d %5d %5d  %s"
              % (r["label"], r["area_um2"], r["pct_of_free"],
                 r["tiles_required"], r["extra_input_pins"], r["build_days"],
                 "survives" if r["survives"]
                 else "out: " + ", ".join(r["failed"])))
    print()
    rejected = len(rows) - len(survivors)
    print("Survivors: %d of %d." % (len(survivors), len(rows)))
    if not rejected:
        print("  No option was rejected. The constraints do not discriminate")
        print("  here, which is a fact about how much room the die has left")
        print("  rather than a fault in the rule. The decision is therefore")
        print("  entirely on the preference order below.")
    for opt in sorted(best):
        r = best[opt]
        print("  largest surviving %-8s %s, %.1f um2, %.2f%% of free, "
              "%s risk, %d days"
              % (opt, r["label"], r["area_um2"], r["pct_of_free"],
                 r["delivery_risk"], r["build_days"]))
    print()
    print("The rule stops here. The order it declares puts research value")
    print("first and this script does not judge that, so the argument")
    print("between the survivors is in docs/phaseE_g2_decision.md.")
    print("Tile count: unchanged at %d. Nothing on this table needs a fifth."
          % criteria["committed"]["tiles"])


# ---------------------------------------------------------------- selftest

def fixture_criteria(tmpdir, mutate=None):
    base = {
        "frozen": "2026-01-01",
        "gate": "G.2",
        "committed": {"tiles_string": "2x2", "tiles": 4, "source": "info.yaml",
                      "standard_tile_um": [160.0, 100.0]},
        "hard": [
            {"id": "H1", "name": "fits with a reserve", "field": "pct_of_free",
             "op": "<=", "value": 75.0},
            {"id": "H2", "name": "no extra tile", "field": "tiles_required",
             "op": "<=", "value": 4},
            {"id": "H4", "name": "eight oscillators at least",
             "field": "new_oscillators", "op": ">=", "value": 8},
        ],
        "preference_order": ["research value"],
        "declared_inputs": {
            "armc": {"build_days": 4, "delivery_risk": "high"},
            "ladder": {"build_days": 2, "delivery_risk": "low"},
        },
        "sizes_considered": [4, 16],
        "existing_oscillators": 32,
    }
    if mutate:
        mutate(base)
    path = os.path.join(tmpdir, "crit.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(base, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return base, path


def fixture_inputs(free=10000.0, def_hash="abc", mutate_cost=None):
    budget = {"free": {"area_um2": free, "held_area_um2": 1.0},
              "rows": {"area_um2": free + 1.0},
              "die": {"width_um": 334.88, "height_um": 225.76},
              "source": {"sha256": {"def": def_hash}}}
    priced = {"armc": [], "ladder": []}
    # One size under the line, one over it, and one too small to qualify, so
    # the fixture space contains a survivor and two different rejections.
    for rings, total in ((4, 1000.0), (16, 3000.0), (16, 9000.0)):
        priced["armc"].append({
            "rings": rings, "density_label": "d%d" % int(total),
            "total_um2": total, "pct_of_free": 100.0 * total / free,
            "extra_select_bits": 1, "routed_um": 10.0 * rings})
    for rungs, total in ((16, 2000.0),):
        priced["ladder"].append({
            "rungs": rungs, "total_um2": total,
            "pct_of_free": 100.0 * total / free,
            "extra_select_bits": 1, "routed_um": 10.0 * rungs})
    cost = {"priced": priced, "free_area_um2": free,
            "source": {"sha256": {"def": def_hash}}}
    if mutate_cost:
        mutate_cost(cost)
    return budget, cost


def run_fixture(tmpdir, mutate_crit=None, mutate_cost=None, free=10000.0,
                budget_hash="abc", cost_hash="abc", frozen=None):
    criteria, path = fixture_criteria(tmpdir, mutate_crit)
    budget, cost = fixture_inputs(free, budget_hash, mutate_cost)
    cost["source"]["sha256"]["def"] = cost_hash
    rows = apply_rule(build_options(budget, cost, criteria), criteria)
    survivors, best = recommend(rows, criteria)
    res = run_checks(budget, cost, criteria, rows, survivors, best,
                     criteria_path=path,
                     frozen=frozen if frozen else sha256_file(path))
    return res, rows, survivors, best


def selftest():
    import tempfile
    ok = True
    print("g2_decision selftest")
    tmp = tempfile.mkdtemp(prefix="g2fix")
    res, rows, survivors, best = run_fixture(tmp)
    if res.failed():
        print("  FAIL: clean fixture fails %s" % ", ".join(res.failed()))
        for r in res.rows:
            if not r["pass"]:
                print("        %s %s" % (r["id"], r["detail"]))
        ok = False
    else:
        print("  clean fixture passes all %d checks, %d of %d options survive"
              % (len(res.rows), len(survivors), len(rows)))

    faults = [
        ("G01", "a criteria file edited after freezing",
         dict(frozen="f" * 64)),
        ("G02", "a rule naming a field no option carries",
         dict(mutate_crit=lambda c: c["hard"].append(
             {"id": "HX", "name": "invented", "field": "nonesuch",
              "op": "<=", "value": 1}))),
        ("G03", "a rule using an operator this script has no code for",
         dict(mutate_crit=lambda c: c["hard"].append(
             {"id": "HY", "name": "odd", "field": "pct_of_free",
              "op": "~=", "value": 1}))),
        ("G04", "two input files from different builds",
         dict(cost_hash="different")),
        ("G05", "a cost file priced against another free area",
         dict(mutate_cost=lambda c: c.update(free_area_um2=1.0))),
        ("G06", "a share of the free area that is not its own arithmetic",
         dict(mutate_cost=lambda c: c["priced"]["ladder"][0].update(
             pct_of_free=99.0))),
        ("G07", "a committed tile that is not the tile the die is built on",
         dict(mutate_crit=lambda c: c["committed"].update(
             standard_tile_um=[40.0, 25.0]))),
        ("G08", "constraints no option can meet",
         dict(mutate_crit=lambda c: c["hard"].append(
             {"id": "HZ", "name": "impossible", "field": "new_oscillators",
              "op": ">=", "value": 999}))),
        ("G10", "a constraint so loose even the probe clears it",
         dict(mutate_crit=lambda c: c["hard"].append(
             {"id": "HL", "name": "always true", "field": "new_oscillators",
              "op": ">=", "value": 0}))),
    ]
    for want, label, kwargs in faults:
        r2, rows2, surv2, best2 = run_fixture(tmp, **kwargs)
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

    # G09 cannot be reached from a criteria or cost file: recommend() picks
    # only from survivors, so the check guards the recommender. The fault
    # comes from the other side, by handing run_checks a recommendation that
    # was never in the survivor list.
    res3, rows3, surv3, best3 = run_fixture(tmp)
    stranger = dict(rows3[0])
    stranger["label"] = "never survived"
    criteria3, path3 = fixture_criteria(tmp)
    budget3, cost3 = fixture_inputs()
    r4 = run_checks(budget3, cost3, criteria3, rows3, surv3,
                    {"armc": stranger}, criteria_path=path3,
                    frozen=sha256_file(path3))
    if set(r4.failed()) == {"G09"}:
        print("  ok    G09  a recommendation that was never a survivor")
    else:
        print("  FAIL  G09  tripped %s" % (", ".join(r4.failed()) or "nothing"))
        ok = False

    # And the ordering rule itself: the largest surviving size wins.
    if best3 and best3.get("armc", {}).get("new_oscillators") == 16:
        print("  ok    order  the largest surviving ring count is chosen")
    else:
        print("  FAIL  order  chose %s"
              % (best3.get("armc", {}).get("new_oscillators")))
        ok = False

    print("\n  %s" % ("all faults isolated" if ok else "SELFTEST FAILED"))
    return 0 if ok else 1


# ---------------------------------------------------------------------- main

# Where the hash is written down. The writeup is mirrored to the public
# clone and the plan is not, so CI only ever sees the first of these. Both
# are checked wherever they exist and a file that is absent is reported as
# absent rather than counted as agreement.
RECORDED_IN = (("docs/phaseE_g2_decision.md", True),
               ("PLAN_TO_DECEMBER.md", False))


def freeze_check():
    got = sha256_file(CRITERIA)
    print("G2_CRITERIA.json sha256 %s" % got)
    ok = True
    if got != FROZEN_SHA256:
        print("  FAIL g2_decision.py has %s" % FROZEN_SHA256)
        print("  The rule was frozen before either option was scored. If it")
        print("  had to change, it belongs in a new dated file with a reason.")
        ok = False
    else:
        print("  ok   g2_decision.py")
    for rel, required in RECORDED_IN:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            if required:
                print("  FAIL %s is missing" % rel)
                ok = False
            else:
                print("  --   %s is not in this tree, so not checked here"
                      % rel)
            continue
        with open(path, "r", encoding="utf-8") as fh:
            if got in fh.read():
                print("  ok   %s" % rel)
            else:
                print("  FAIL %s does not carry the hash" % rel)
                ok = False
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--freeze-check", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.freeze_check:
        return freeze_check()

    for p in (CRITERIA, BUDGET, COST):
        if not os.path.exists(p):
            raise SystemExit("missing input: %s" % p)
    with open(CRITERIA, "r", encoding="utf-8") as fh:
        criteria = json.load(fh)
    with open(BUDGET, "r", encoding="utf-8") as fh:
        budget = json.load(fh)
    with open(COST, "r", encoding="utf-8") as fh:
        cost = json.load(fh)

    rows = apply_rule(build_options(budget, cost, criteria), criteria)
    survivors, best = recommend(rows, criteria)
    res = run_checks(budget, cost, criteria, rows, survivors, best)
    report(rows, survivors, best, criteria, budget)
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

    if a.json:
        out = {"gate": "G.2", "criteria_sha256": sha256_file(CRITERIA),
               "frozen": criteria["frozen"], "options": rows,
               "survivors": [r["label"] for r in survivors],
               "largest_surviving": dict(
                   (k, v["label"]) for k, v in best.items()),
               "tiles_required": criteria["committed"]["tiles"],
               "checks": res.rows}
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print("  wrote %s" % a.json)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
