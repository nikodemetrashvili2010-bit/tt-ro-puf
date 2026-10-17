#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""G.4: the acquisition protocol and the 2027 analysis, frozen before silicon.

G.4's acceptance condition is that pair definitions, exclusions, conditions
and primary metrics are timestamped before silicon. The parts are in
`PREREGISTRATION.json`; this checks them against the design they describe and
against the two files they lean on, and gates the whole thing on a hash.

The point of freezing now is not paperwork. The chip arrives in June 2027,
and between now and then there is every opportunity to notice that a
different pairing, a different exclusion or a different metric would make the
result look better. Writing them down while no data exists is the only way
the eventual numbers mean anything.

Three things it refuses to do.

It does not restate a number that lives somewhere else. The abstention rule
is `TOLERANCES.json`'s, referenced by that file's SHA-256, and the window
lengths are `OBSERVABILITY.json`'s. Copying either would create a second
place for them to disagree.

It does not invent a pairing. Sixteen rings split into eight pairs
2,027,025 ways, and the one this preregisters is the one the RTL already
builds and the one Section 7's result is quoted at. Scoring the alternatives
is `sim/spice/gono/pairing_policy.py`'s job and a different study.

It does not leave the multiplicity open. Seven tests are declared, the
correction is Holm, and both are in the frozen file rather than chosen once
the spread is known.

Since 18 October it also holds `PREREG_AMENDMENT.json` to the frozen file.
The amendment changes nothing in `PREREGISTRATION.json`. It records it by
hash, and every one of its items quotes the frozen text it amends, so
`--amendment` can say whether each quote is still what the frozen file says.
It also holds the amended box inside the library's corners, the M4 method
to the implementation recorded beside it, the amended order and reading to
what the bench firmware does, and the two halves of the M4 secondary to
where the placement hook puts Arm C's rings.

Usage:
    python3 preregister.py --selftest
    python3 preregister.py --freeze-check
    python3 preregister.py
    python3 preregister.py --amendment
    python3 preregister.py --json /tmp/prereg.json
"""

import argparse
import copy
import hashlib
import itertools
import json
import os
import re
import sys
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

PREREG = os.path.join(HERE, "PREREGISTRATION.json")
OBS = os.path.join(HERE, "OBSERVABILITY.json")
REGIONS = os.path.join(HERE, "ARMC_REGIONS.json")
TOLERANCES = os.path.join(ROOT, "extraction", "TOLERANCES.json")

AMENDMENT = os.path.join(HERE, "PREREG_AMENDMENT.json")
IMPL = os.path.join(HERE, "primary_tests.py")
FIRMWARE = os.path.join(ROOT, "firmware", "measure_puf.py")
TEMPLATE = os.path.join(HERE, "ARMC_TEMPLATE.json")
# The Arm C hook, at its working-tree path and at the clone's.
HOOKS = (os.path.join(ROOT, "dualarm", "src", "armc_fix.tcl"),
         os.path.join(ROOT, "src", "armc_fix.tcl"))

# The fast and slow library corners, ff_n40C_1v95 and ss_100C_1v60. Every
# corner the SPICE decks and the timing run used sits inside these two.
LIBRARY_VOLTS = (1.60, 1.95)

METHOD_KEYS = ("statistic", "centring", "test", "shuffles", "seed",
               "generator", "sided", "level", "interval", "decision")

# SHA-256 of PREREGISTRATION.json as frozen on 2026-08-31. Also in
# docs/phaseE_preregistration.md and PLAN_TO_DECEMBER.md.
FROZEN_SHA256 = \
    "81b697b4904dd406586df06d8ff411fdcd50b331420eba62c840bc4bfec58b8f"

RECORDED_IN = (("docs/phaseE_preregistration.md", True),
               ("PLAN_TO_DECEMBER.md", False))

N_PER_ARM = 16


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


def build_pairs(arms, n_per_arm=N_PER_ARM):
    """The declared pairing, built rather than listed.

    Adjacent within an arm: ring 2j against ring 2j+1. Listing 24 pairs by
    hand would put a typo one keystroke away from a different experiment.
    """
    out = []
    for arm in arms:
        for j in range(n_per_arm // 2):
            out.append({"arm": arm, "a": 2 * j, "b": 2 * j + 1,
                        "id": "%s%d" % (arm, j)})
    return out


def condition_cells(cond):
    return list(itertools.product(cond["voltage_v"],
                                  cond["temperature_c"],
                                  cond["window_selects"]))


def run_checks(pre, obs, regions, tol, tol_hash, prereg_path=PREREG,
               frozen=None):
    res = Results()
    frozen = FROZEN_SHA256 if frozen is None else frozen
    got = sha256_file(prereg_path)
    res.add("P01", "the preregistration is the one that was frozen",
            got == frozen, "sha256 %s" % got[:16])

    dep = pre["depends_on"]["tolerances"]
    res.add("P02", "the A.5 tolerances it leans on are the frozen ones",
            dep["sha256"] == tol_hash,
            "declared %s, actual %s" % (dep["sha256"][:12], tol_hash[:12]))

    # The abstention rule must be read from TOLERANCES.json, not copied
    # here. Only the distinctive values are searched for: a bare small
    # integer like k cannot be told apart from any other number in the file,
    # so it is looked for in a labelled form instead of on its own.
    txt = json.dumps(pre)
    leaked = []
    for v in (tol["margin_rule"]["high_margin_threshold_fF"],
              tol["margin_rule"]["sigma_pair_fF"]):
        if len(str(v)) >= 4 and str(v) in txt:
            leaked.append(str(v))
    kv = tol["margin_rule"]["k"]
    for form in ('"k": %d' % kv, "k = %d" % kv, "k=%d" % kv,
                 "k is %d" % kv):
        if form in txt:
            leaked.append(form)
    res.add("P03", "no threshold from the tolerances file is copied into this",
            not leaked, "copied: %s" % (", ".join(leaked) or "none"))

    pairs = build_pairs(pre["pairing"]["arms"])
    per_arm = pre["pairing"]["pairs_per_arm"]
    res.add("P04", "the pairing covers every ring once, in every arm",
            len(pairs) == pre["pairing"]["pairs_total"]
            and all(sorted([p["a"] for p in pairs if p["arm"] == arm]
                           + [p["b"] for p in pairs if p["arm"] == arm])
                    == list(range(N_PER_ARM))
                    for arm in pre["pairing"]["arms"])
            and per_arm * len(pre["pairing"]["arms"])
            == pre["pairing"]["pairs_total"],
            "%d pairs over %d arms" % (len(pairs),
                                       len(pre["pairing"]["arms"])))

    res.add("P05", "the arms are the three the chip will carry",
            pre["pairing"]["arms"] == ["A", "B", "C"]
            and regions["select"]["oscillators"]
            == N_PER_ARM * len(pre["pairing"]["arms"]),
            "%s, %d oscillators" % (pre["pairing"]["arms"],
                                    regions["select"]["oscillators"]))

    res.add("P06", "the bit convention is the tolerances file's, word for word",
            tol["margin_rule"]["sign_convention"].startswith("sign of f_a - f_b")
            and pre["pairing"]["bit_convention"].startswith(
                "sign of f_a minus f_b"),
            "both read on f_a minus f_b")

    cond = pre["conditions"]
    safe = obs["windows"]["safe"]
    bad_win = [w for w in cond["window_selects"] if w >= len(safe)]
    res.add("P07", "every window the protocol uses is a safe one in the spec",
            not bad_win
            and cond["overflow_window_select"] == len(safe),
            "safe selects %s, overflow select %d"
            % (cond["window_selects"], cond["overflow_window_select"]))

    res.add("P08", "the reference clock is the one the spec sized windows on",
            cond["reference_clock_hz"] == obs["clock_hz"],
            "%d against %d" % (cond["reference_clock_hz"], obs["clock_hz"]))

    cells = condition_cells(cond)
    stated = cond["cell_count_note"]
    res.add("P09", "the condition grid is complete and its size is stated",
            len(cells) == 27 and "27 cells" in stated
            and cond["repeats_per_cell"] > 1,
            "%d cells, %d repeats" % (len(cells), cond["repeats_per_cell"]))

    res.add("P10", "the corner box the protocol sweeps is the one simulated",
            min(cond["voltage_v"]) <= 1.62 and max(cond["voltage_v"]) >= 1.98
            and min(cond["temperature_c"]) <= -40
            and max(cond["temperature_c"]) >= 125,
            "%s V, %s C" % (cond["voltage_v"], cond["temperature_c"]))

    res.add("P11", "the overflow flag and the version bytes must be recorded",
            any("overflow" in m for m in cond["must_record"])
            and any("protocol version" in m for m in cond["must_record"]),
            "%d recorded fields" % len(cond["must_record"]))

    mets = pre["primary_metrics"]
    ids = [m["id"] for m in mets]
    res.add("P12", "every metric has an id, a definition and a direction",
            len(set(ids)) == len(ids) and len(ids) >= 4
            and all(m.get("definition") and m.get("direction") for m in mets),
            "%s" % ", ".join(ids))

    fal = pre["falsification"]
    res.add("P13", "the metrics the claim rests on can be falsified",
            set(fal) and set(fal) <= set(ids) and {"M1", "M4"} <= set(fal),
            "falsifiable: %s" % ", ".join(sorted(fal)))

    mult = pre["multiplicity"]
    declared = 3 + 3 + 1
    res.add("P14", "the test family is counted and the correction is declared",
            "%d tests" % declared in mult["family"].replace("Seven", "7")
            or "Seven tests" in mult["family"],
            mult["family"])
    res.add("P15", "the correction is Holm and it is named here, not later",
            mult["correction"].lower().startswith("holm"),
            mult["correction"][:40])

    res.add("P16", "predictions are archived before any die is read",
            pre["analysis_freeze"]["predictions_archived_before_measurement"]
            is True, "declared")

    res.add("P17", "no exclusion drops a reading for being inconvenient",
            "No reading is dropped for being an outlier"
            in pre["exclusions"]["no_other_exclusion"],
            "outlier rule present")
    return res


# ---------------------------------------------------------------- amendment

def frozen_value(pre, key):
    """The value at a dotted key, a list of metrics found by its id."""
    cur = pre
    for part in key.split("."):
        if isinstance(cur, list):
            hit = [m for m in cur if m.get("id") == part]
            if len(hit) != 1:
                raise KeyError(key)
            cur = hit[0]
        else:
            cur = cur[part]
    return cur


def nand_y_um(hook_text):
    """Ring index -> y of its NAND in the Arm C hook, in um."""
    out = {}
    for m in re.finditer(r"g_armc\\\[(\d+)\\\]\.u_roc\.u_nand\} (\d+) (\d+)",
                         hook_text):
        out[int(m.group(1))] = int(m.group(3)) / 1000.0
    return out


def amendment_checks(pre, am, ctx):
    """ctx holds the hashes and texts the checks read besides the two JSON
    files, so the selftest can hand each one a fault."""
    res = Results()
    items = {it.get("id"): it for it in am.get("amends", [])}

    rec = am.get("frozen_record", {}).get("chip/PREREGISTRATION.json")
    res.add("A01", "the amendment records the frozen preregistration by hash",
            rec == FROZEN_SHA256 == ctx["prereg_hash"],
            "recorded %s, frozen %s, on disk %s"
            % (str(rec)[:12], FROZEN_SHA256[:12], ctx["prereg_hash"][:12]))

    why = " ".join(am.get("not_a_preregistration_why", []))
    res.add("A02", "it says on its face it is not a preregistration",
            am.get("kind") == "amendment"
            and am.get("not_a_preregistration") is True
            and am.get("supersedes_nothing") is True
            and "never be cited" in why
            and am.get("dies_read_when_written") == 0,
            "dies read when written: %s" % am.get("dies_read_when_written"))

    unquoted = []
    for iid, it in sorted(items.items()):
        try:
            v = frozen_value(pre, it["frozen_key"])
        except (KeyError, TypeError):
            unquoted.append("%s names no key %s" % (iid, it.get("frozen_key")))
            continue
        if "frozen_text" in it:
            if not (isinstance(v, str) and it["frozen_text"]
                    and it["frozen_text"] in v):
                unquoted.append("%s misquotes %s" % (iid, it["frozen_key"]))
        elif it.get("frozen_value") != v:
            unquoted.append("%s has %s as %s, frozen %s"
                            % (iid, it["frozen_key"], it.get("frozen_value"),
                               v))
    res.add("A03", "every item quotes the frozen text it amends, as frozen",
            items and not unquoted,
            "; ".join(unquoted) or "%d items" % len(items))

    late = []
    for iid, it in sorted(items.items()):
        d = it.get("decided", "")
        if not (pre["frozen"] < d <= am.get("written", "")
                and d[:7] < pre["silicon_expected"]):
            late.append("%s dated %s" % (iid, d))
        for k in ("by", "now", "why", "gives_up"):
            if not it.get(k):
                late.append("%s has no %s" % (iid, k))
    ids = [it.get("id") for it in am.get("amends", [])]
    if len(set(ids)) != len(ids):
        late.append("two items share an id")
    res.add("A04", "every item is dated between the freeze and silicon, and "
                   "says who, what, why and what it gives up",
            not late, "; ".join(late) or "%d items" % len(items))

    fam = items.get("family", {})
    six = Fraction(1, 2) ** 6
    levels = fam.get("holm_levels")
    res.add("A05", "two primaries, Holm over two, and a perfect six of six "
                   "passes the first level where the frozen family failed it",
            fam.get("primaries") == ["M1 on Arm A", "M4"]
            and levels == [0.05 / 2, 0.05 / 1]
            and six < Fraction(1, 40) and six > Fraction(1, 140),
            "levels %s, six of six %s" % (levels, float(six)))

    volt = items.get("voltage", {})
    now = volt.get("now_value") or []
    res.add("A06", "the amended voltages lie inside the library's corners",
            len(now) == 3 and now[:2] == (volt.get("frozen_value") or [])[:2]
            and all(LIBRARY_VOLTS[0] <= v <= LIBRARY_VOLTS[1] for v in now),
            "%s V against %s" % (now, list(LIBRARY_VOLTS)))

    meth = items.get("m4_interval", {}).get("method", {})
    gaps = [k for k in METHOD_KEYS if meth.get(k) in (None, "")]
    impl = ctx["impl_text"]
    shf = re.search(r"(?m)^SHUFFLES = (\d+)$", impl)
    sed = re.search(r"(?m)^SEED = (\d+)$", impl)
    rimpl = am.get("reference_implementation", {}).get("chip/primary_tests.py")
    res.add("A07", "the M4 method is complete and is the implementation "
                   "recorded beside it",
            not gaps and rimpl == ctx["impl_hash"] and shf and sed
            and int(shf.group(1)) == meth.get("shuffles")
            and int(sed.group(1)) == meth.get("seed"),
            ", ".join(gaps) or "%s shuffles, seed %s, implementation %s"
            % (meth.get("shuffles"), meth.get("seed"), str(rimpl)[:12]))

    fw = ctx["fw_text"]
    wants = {"a seeded generator": r"random\.seed\(seed\)",
             "all 48 shuffled every round": r"_shuffled\(pairs, random\)",
             "the seed in the header": r'"seed": seed',
             "a time stamp on every row": r"count_first,t_ms",
             "count_first beside the count": r'"count_is": "second start"'}
    missing = [w for w, rx in sorted(wants.items()) if not re.search(rx, fw)]
    order = " ".join(items.get("order", {}).get("now", []))
    reading = " ".join(items.get("reading", {}).get("now", []))
    if "seeded" not in order:
        missing.append("the order item does not say seeded")
    if "second of two starts" not in reading or "count_first" not in reading:
        missing.append("the reading item does not name the second start")
    res.add("A08", "the order and the reading are what the bench firmware "
                   "does", not missing, ", ".join(missing) or
            "%d of %d found in firmware/measure_puf.py" % (len(wants),
                                                          len(wants)))

    ys = nand_y_um(ctx["hook_text"])
    lo, hi = ctx["arm_a_box"][1], ctx["arm_a_box"][3]
    below = sorted(i for i, y in ys.items() if y < lo)
    above = sorted(i for i, y in ys.items() if y > hi)
    halves = items.get("m4_secondary", {}).get("halves", {})
    res.add("A09", "the M4 secondary's halves are the rings the hook puts "
                   "below and above Arm A",
            len(ys) == 16 and len(below) == 8 and len(above) == 8
            and halves.get("below_arm_a") == below
            and halves.get("above_arm_a") == above,
            "%d rings in the hook, below %s, above %s"
            % (len(ys), below, above))
    return res


def amendment_context():
    with open(IMPL, "r", encoding="utf-8") as fh:
        impl = fh.read()
    with open(FIRMWARE, "r", encoding="utf-8") as fh:
        fw = fh.read()
    hook = [h for h in HOOKS if os.path.exists(h)]
    if not hook:
        raise SystemExit("missing input: armc_fix.tcl in dualarm/src or src")
    with open(hook[0], "r", encoding="utf-8") as fh:
        hook_text = fh.read()
    with open(TEMPLATE, "r", encoding="utf-8") as fh:
        box = json.load(fh)["arm_a"]["box_um"]
    return {"prereg_hash": sha256_file(PREREG), "impl_text": impl,
            "impl_hash": sha256_file(IMPL), "fw_text": fw,
            "hook_text": hook_text, "arm_a_box": box}


def load_amendment():
    with open(PREREG, "r", encoding="utf-8") as fh:
        pre = json.load(fh)
    with open(AMENDMENT, "r", encoding="utf-8") as fh:
        am = json.load(fh)
    return pre, am, amendment_context()


def amendment_main():
    pre, am, ctx = load_amendment()
    res = amendment_checks(pre, am, ctx)
    print("G.4 amendment, written %s, %d items, recording %s"
          % (am["written"], len(am["amends"]), FROZEN_SHA256[:16]))
    for it in am["amends"]:
        print("  %-13s %s  %s" % (it["id"], it["decided"], it["frozen_key"]))
    print()
    for r in res.rows:
        print("  %-4s %-58s %s" % (r["id"], r["name"][:58],
                                   "pass" if r["pass"] else "FAIL"))
    bad = res.failed()
    print("\n  %s" % ("all %d checks pass" % len(res.rows) if not bad
                      else "FAILED: " + ", ".join(bad)))
    for r in res.rows:
        if not r["pass"]:
            print("       %s: %s" % (r["id"], r["detail"]))
    return 1 if bad else 0


def amendment_selftest():
    """Each fault on a copy of the real files, and only its check may fire."""
    pre, am, ctx = load_amendment()
    ok = True
    clean = amendment_checks(pre, am, ctx)
    if clean.failed():
        print("  FAIL: the amendment as it stands fails %s"
              % ", ".join(clean.failed()))
        return False
    print("  the amendment as it stands passes all %d checks"
          % len(clean.rows))

    def item(a, iid):
        return [it for it in a["amends"] if it["id"] == iid][0]

    def f_a03(a, c):
        item(a, "order")["frozen_text"] = item(a, "order")[
            "frozen_text"].replace("ABBA", "ABAB")

    def f_a07(a, c):
        c["impl_text"] = c["impl_text"].replace("SEED = 20261018",
                                                "SEED = 20261019")

    def f_a09(a, c):
        h = item(a, "m4_secondary")["halves"]
        h["below_arm_a"], h["above_arm_a"] = (
            sorted(h["below_arm_a"][1:] + [h["above_arm_a"][0]]),
            sorted(h["above_arm_a"][1:] + [h["below_arm_a"][0]]))

    faults = [
        ("A01", "the frozen file recorded by another hash",
         lambda a, c: a["frozen_record"].update(
             {"chip/PREREGISTRATION.json": "0" * 64})),
        ("A02", "an amendment that calls itself a preregistration",
         lambda a, c: a.update(not_a_preregistration=False)),
        ("A03", "a quote of the frozen order that is not what it says", f_a03),
        ("A04", "an item that does not say what it gives up",
         lambda a, c: item(a, "die").pop("gives_up")),
        ("A05", "Holm levels that are not the two-test ones",
         lambda a, c: item(a, "family").update(holm_levels=[0.05, 0.05])),
        ("A06", "a top voltage past the fast corner",
         lambda a, c: item(a, "voltage").update(
             now_value=[1.62, 1.8, 1.98])),
        ("A07", "an implementation seeded differently from the method",
         f_a07),
        ("A08", "a bench firmware that reads in a fixed order",
         lambda a, c: c.update(fw_text=c["fw_text"].replace(
             "_shuffled(pairs, random)", "list(pairs)"))),
        ("A09", "a ring swapped between the two halves", f_a09),
    ]
    for want, label, fault in faults:
        a2, c2 = copy.deepcopy(am), dict(ctx)
        fault(a2, c2)
        tripped = set(amendment_checks(pre, a2, c2).failed())
        if tripped == {want}:
            print("  ok    %-4s %s" % (want, label))
        else:
            print("  FAIL  %-4s %s -- tripped %s"
                  % (want, label, ", ".join(sorted(tripped)) or "nothing"))
            ok = False
    return ok


# ------------------------------------------------------------------ fixture

def fixture_files(tmp, mutate=None):
    tol = {"margin_rule": {"k": 5, "high_margin_threshold_fF": 0.6622,
                           "sigma_pair_fF": 0.1324,
                           "sign_convention": "sign of f_a - f_b."}}
    obs = {"windows": {"safe": [256, 512, 2048], "overflow": 16384},
           "clock_hz": 50000000}
    regions = {"select": {"oscillators": 48}}
    pre = {
        "frozen": "2026-01-01", "gate": "G.4",
        "depends_on": {"tolerances": {"path": "extraction/TOLERANCES.json",
                                      "sha256": "", "used_for": "x"},
                       "observability": {"path": "chip/OBSERVABILITY.json",
                                         "used_for": "y"}},
        "pairing": {"rule": "adjacent", "why": "z", "pairs_per_arm": 8,
                    "arms": ["A", "B", "C"], "pairs_total": 24,
                    "bit_convention": "sign of f_a minus f_b, lower index "
                                      "first."},
        "conditions": {"voltage_v": [1.62, 1.80, 1.98],
                       "temperature_c": [-40, 25, 125],
                       "window_selects": [0, 1, 2],
                       "overflow_window_select": 3, "repeats_per_cell": 20,
                       "order": "ABBA", "reference_clock_hz": 50000000,
                       "cell_count_note": "27 cells",
                       "must_record": ["protocol version byte",
                                       "the sticky overflow flag"]},
        "exclusions": {"before_any_analysis": ["a"], "abstention": "b",
                       "no_other_exclusion":
                           "No reading is dropped for being an outlier."},
        "primary_metrics": [
            {"id": "M1", "name": "a", "definition": "d", "direction": "u"},
            {"id": "M2", "name": "b", "definition": "d", "direction": "u"},
            {"id": "M3", "name": "c", "definition": "d", "direction": "u"},
            {"id": "M4", "name": "e", "definition": "d", "direction": "u"}],
        "falsification": {"M1": "x", "M4": "y"},
        "multiplicity": {"family": "Seven tests.", "correction": "Holm",
                         "no_subgroup_hunting": "n"},
        "analysis_freeze": {"predictions_archived_before_measurement": True,
                            "note": "n"},
    }
    if mutate:
        mutate(pre, obs, regions, tol)
    p = os.path.join(tmp, "prereg.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(pre, fh, indent=2, sort_keys=True)
        fh.write("\n")
    th = hashlib.sha256(json.dumps(tol, sort_keys=True).encode()).hexdigest()
    if not pre["depends_on"]["tolerances"]["sha256"]:
        pre["depends_on"]["tolerances"]["sha256"] = th
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(pre, fh, indent=2, sort_keys=True)
            fh.write("\n")
    return pre, obs, regions, tol, th, p


def run_fixture(tmp, mutate=None, frozen=None):
    pre, obs, regions, tol, th, p = fixture_files(tmp, mutate)
    with open(p, "r", encoding="utf-8") as fh:
        pre = json.load(fh)
    return run_checks(pre, obs, regions, tol, th, prereg_path=p,
                      frozen=frozen if frozen else sha256_file(p))


def selftest():
    import tempfile
    tmp = tempfile.mkdtemp(prefix="prereg")
    print("preregister selftest")
    ok = True
    res = run_fixture(tmp)
    if res.failed():
        print("  FAIL: clean fixture fails %s" % ", ".join(res.failed()))
        for r in res.rows:
            if not r["pass"]:
                print("        %s %s" % (r["id"], r["detail"]))
        ok = False
    else:
        print("  clean fixture passes all %d checks" % len(res.rows))

    faults = [
        ("P01", "a preregistration edited after freezing",
         dict(frozen="f" * 64)),
        ("P02", "leaning on a tolerances file that is not the frozen one",
         dict(mutate=lambda p, o, g, t: p["depends_on"]["tolerances"].update(
             sha256="a" * 64))),
        ("P03", "the abstention threshold copied in instead of referenced",
         dict(mutate=lambda p, o, g, t: p["exclusions"].update(
             abstention="abstain below 0.6622 fF"))),
        ("P04", "a pairing that leaves a ring out",
         dict(mutate=lambda p, o, g, t: p["pairing"].update(pairs_total=23))),
        ("P05", "two arms preregistered for a three-arm chip",
         dict(mutate=lambda p, o, g, t: p["pairing"].update(
             arms=["A", "B"], pairs_total=16))),
        ("P07", "a protocol window the spec calls unsafe",
         dict(mutate=lambda p, o, g, t: p["conditions"].update(
             window_selects=[0, 1, 3]))),
        ("P08", "a reference clock the windows were not sized on",
         dict(mutate=lambda p, o, g, t: p["conditions"].update(
             reference_clock_hz=25000000))),
        ("P09", "a condition grid that does not match its own stated size",
         dict(mutate=lambda p, o, g, t: p["conditions"].update(
             cell_count_note="24 cells"))),
        ("P10", "a corner box narrower than the one that was simulated",
         dict(mutate=lambda p, o, g, t: p["conditions"].update(
             voltage_v=[1.70, 1.80, 1.90]))),
        ("P11", "a protocol that does not record the overflow flag",
         dict(mutate=lambda p, o, g, t: p["conditions"].update(
             must_record=["protocol version byte"]))),
        ("P12", "a metric with no direction declared",
         dict(mutate=lambda p, o, g, t: p["primary_metrics"][2].update(
             direction=""))),
        ("P13", "a headline metric nothing could falsify",
         dict(mutate=lambda p, o, g, t: p["falsification"].pop("M4"))),
        ("P15", "a correction chosen later instead of named now",
         dict(mutate=lambda p, o, g, t: p["multiplicity"].update(
             correction="decide once the spread is known"))),
        ("P16", "predictions not archived before measurement",
         dict(mutate=lambda p, o, g, t: p["analysis_freeze"].update(
             predictions_archived_before_measurement=False))),
        ("P17", "an outlier filter smuggled into the exclusions",
         dict(mutate=lambda p, o, g, t: p["exclusions"].update(
             no_other_exclusion="Outliers beyond 3 sigma are dropped."))),
    ]
    for want, label, kwargs in faults:
        r2 = run_fixture(tmp, **kwargs)
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

    # P06 and P14 read wording that the fixture supplies, so they get their
    # faults from the other side.
    r3 = run_fixture(tmp, mutate=lambda p, o, g, t: t["margin_rule"].update(
        sign_convention="sign of f_b - f_a."))
    if set(r3.failed()) == {"P06"}:
        print("  ok    P06  the two files disagreeing about the bit's sign")
    else:
        print("  FAIL  P06  tripped %s" % (", ".join(r3.failed()) or "nothing"))
        ok = False
    r4 = run_fixture(tmp, mutate=lambda p, o, g, t: p["multiplicity"].update(
        family="some tests"))
    if set(r4.failed()) == {"P14"}:
        print("  ok    P14  a family that is never counted")
    else:
        print("  FAIL  P14  tripped %s" % (", ".join(r4.failed()) or "nothing"))
        ok = False

    # The pair builder, against arithmetic that does not call it.
    pairs = build_pairs(["A", "B", "C"])
    good = (len(pairs) == 24
            and all(p["b"] == p["a"] + 1 for p in pairs)
            and sorted(set((p["arm"], p["a"]) for p in pairs)) ==
            sorted((arm, 2 * j) for arm in "ABC" for j in range(8)))
    print("  %-5s pairs  24 adjacent pairs, eight an arm, none repeated"
          % ("ok" if good else "FAIL"))
    ok = ok and good

    print("\n  the amendment, faults on copies of the real files")
    ok = amendment_selftest() and ok

    print("\n  %s" % ("all faults isolated" if ok else "SELFTEST FAILED"))
    return 0 if ok else 1


# ---------------------------------------------------------------------- main

def freeze_check():
    got = sha256_file(PREREG)
    print("PREREGISTRATION.json sha256 %s" % got)
    ok = got == FROZEN_SHA256
    print("  %s preregister.py" % ("ok  " if ok else "FAIL"))
    if not ok:
        print("       has %s" % FROZEN_SHA256)
        print("       The plan was frozen before silicon. If it had to")
        print("       change, that belongs in a new dated file with a reason.")
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
    ap.add_argument("--amendment", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.freeze_check:
        return freeze_check()
    if a.amendment:
        return amendment_main()

    for p in (PREREG, OBS, REGIONS, TOLERANCES):
        if not os.path.exists(p):
            raise SystemExit("missing input: %s" % p)
    with open(PREREG, "r", encoding="utf-8") as fh:
        pre = json.load(fh)
    with open(OBS, "r", encoding="utf-8") as fh:
        obs = json.load(fh)
    with open(REGIONS, "r", encoding="utf-8") as fh:
        regions = json.load(fh)
    with open(TOLERANCES, "r", encoding="utf-8") as fh:
        tol = json.load(fh)

    res = run_checks(pre, obs, regions, tol, sha256_file(TOLERANCES))
    pairs = build_pairs(pre["pairing"]["arms"])
    cells = condition_cells(pre["conditions"])
    reps = pre["conditions"]["repeats_per_cell"]
    osc = regions["select"]["oscillators"]

    print("G.4 preregistration, frozen %s, sha256 %s"
          % (pre["frozen"], sha256_file(PREREG)[:16]))
    print("  pairing     %s, %d pairs over %d arms"
          % (pre["pairing"]["rule"].split(":")[0], len(pairs),
             len(pre["pairing"]["arms"])))
    print("  conditions  %d cells, %d repeats, %d oscillators"
          % (len(cells), reps, osc))
    print("              %d readings a die, order %s"
          % (len(cells) * reps * osc, pre["conditions"]["order"].split(":")[0]))
    print("  metrics     %s" % ", ".join("%s %s" % (m["id"], m["name"])
                                         for m in pre["primary_metrics"]))
    print("  family      %s corrected %s" % (pre["multiplicity"]["family"],
                                             pre["multiplicity"]["correction"]))
    print("  abstention  read from extraction/TOLERANCES.json, not copied")
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
        out = {"gate": "G.4", "frozen": pre["frozen"],
               "prereg_sha256": sha256_file(PREREG),
               "tolerances_sha256": sha256_file(TOLERANCES),
               "pairs": pairs, "condition_cells": len(cells),
               "readings_per_die": len(cells) * reps * osc,
               "metrics": [m["id"] for m in pre["primary_metrics"]],
               "checks": res.rows}
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print("  wrote %s" % a.json)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
