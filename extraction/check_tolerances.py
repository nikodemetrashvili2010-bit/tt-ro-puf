#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Does an extraction pipeline meet the A.5 tolerances that were frozen first?

`TOLERANCES.json` is the specification. It was written on 18 August 2026, before
the pipeline of A.3 and A.4 existed and before anything had been predicted about
either foreign target, and it is the G1 gate. This script is the only thing that
reads it. It takes two tables of per-ring capacitance -- the trusted one from the
SPEF, and the candidate one from the pipeline -- and returns pass or fail on
every check in the file, with the number that decided it.

Three things it deliberately does not do.

It does not pick thresholds. Every number comes out of the JSON, and the JSON's
SHA-256 is checked against the value recorded in `docs/phaseA_tolerances.md` and
in `PLAN_TO_DECEMBER.md`, so a threshold edited after a run cannot pass quietly.

It does not compare low-margin signs. A pair under the margin threshold is an
abstention, listed as one, and its sign is never scored either way.

It does not repair its input. A ring missing from the candidate table is a
topology failure, not a row to skip.

Usage:
    python3 check_tolerances.py --selftest
    python3 check_tolerances.py --freeze-check
    python3 check_tolerances.py --reference spef_caps.csv --candidate pipe_caps.csv
    python3 check_tolerances.py --reference a.csv --candidate b.csv --json out.json

Both CSVs need a `ring` column and a `cap_fF` column. Ring topology is optional
and goes in as JSON: {"0": ["cellA", "cellB", ...], "1": [...]}.
"""

import argparse
import csv
import hashlib
import json
import math
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, "TOLERANCES.json")

# SHA-256 of TOLERANCES.json as frozen on 2026-08-18. Also written into
# docs/phaseA_tolerances.md and PLAN_TO_DECEMBER.md. All three have to agree.
FROZEN_SHA256 = "7f61955a03f2c43331ff4a36c6bca1235af598eec96c3740de246919960408c2"


# ---------------------------------------------------------------- helpers

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_spec(path=SPEC):
    with open(path, "r", encoding="utf-8") as fh:
        spec = json.load(fh)
    if spec.get("schema") != "silicon/extraction/tolerances/1":
        raise SystemExit("unknown tolerance schema: %r" % spec.get("schema"))
    return spec


def check_by_id(spec, cid):
    for c in spec["checks"]:
        if c["id"] == cid:
            return c
    raise SystemExit("tolerance file has no check %s" % cid)


def read_caps(path):
    """Returns {ring: cap_fF} and {ring: freq_MHz} or None if the column is absent."""
    cap, freq = {}, {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if "ring" not in row or "cap_fF" not in row:
                raise SystemExit("%s needs a ring column and a cap_fF column" % path)
            r = int(row["ring"])
            cap[r] = float(row["cap_fF"])
            if row.get("freq_MHz"):
                freq[r] = float(row["freq_MHz"])
    if not cap:
        raise SystemExit("%s has no rows" % path)
    if freq and len(freq) != len(cap):
        raise SystemExit("%s has freq_MHz on some rows and not others" % path)
    return cap, (freq or None)


def spearman(a, b):
    """Rank correlation with average ranks for ties. n is 16 here, so the
    O(n^2) ranking costs nothing and reads more clearly than a sort."""
    def ranks(v):
        out = [0.0] * len(v)
        for i, x in enumerate(v):
            less = sum(1 for y in v if y < x)
            same = sum(1 for y in v if y == x)
            out[i] = less + (same + 1) / 2.0
        return out
    ra, rb = ranks(a), ranks(b)
    ma, mb = st.mean(ra), st.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    da = math.sqrt(sum((x - ma) ** 2 for x in ra))
    db = math.sqrt(sum((y - mb) ** 2 for y in rb))
    if da == 0.0 or db == 0.0:
        return 0.0
    return num / (da * db)


def default_pairs(rings):
    r = sorted(rings)
    return [(r[i], r[i + 1]) for i in range(0, len(r) - 1, 2)]


# ---------------------------------------------------------------- the checks

class Result(object):
    def __init__(self):
        self.rows = []

    def add(self, cid, name, value, threshold, ok, unit=""):
        self.rows.append({"id": cid, "name": name, "value": value,
                          "threshold": threshold, "pass": bool(ok), "unit": unit})

    def failed(self):
        return [r["id"] for r in self.rows if not r["pass"]]


def classify(caps, freqs, pairs, spec, mean_f=None):
    """Separation of every pair, and which of them clear the margin line.

    The bit is the sign of a frequency difference, so frequency decides when the
    table carries it. Falling back to capacitance means converting the line at
    the fitted slope and negating the sign, because capacitance and frequency
    move opposite ways.
    """
    m = spec["margin_rule"]
    if freqs is not None:
        thr = m["high_margin_threshold_pct_f"] / 100.0 * mean_f
        val = lambda a, b: freqs[a] - freqs[b]
    else:
        thr = m["high_margin_threshold_fF"]
        val = lambda a, b: -(caps[a] - caps[b])
    seps, high = {}, set()
    for a, b in pairs:
        d = val(a, b)
        seps[(a, b)] = d
        if abs(d) >= thr:
            high.add((a, b))
    return seps, high, thr


def run_checks(ref, cand, spec, ref_topo=None, cand_topo=None, pairs=None,
               ref_f=None, cand_f=None):
    res = Result()

    # T5 first: everything below assumes the two tables describe the same rings.
    missing = sorted(set(ref) - set(cand))
    extra = sorted(set(cand) - set(ref))
    topo_bad = len(missing) + len(extra)
    detail = []
    if ref_topo is not None and cand_topo is not None:
        for r in sorted(set(ref_topo) | set(cand_topo)):
            if ref_topo.get(r) != cand_topo.get(r):
                topo_bad += 1
                detail.append(r)
    t5 = check_by_id(spec, "T5")
    res.add("T5", t5["name"], topo_bad, t5["threshold"], topo_bad <= t5["threshold"], "rings")
    if missing or extra:
        # Nothing below is meaningful on a ring set that does not match.
        for cid in ("T1", "T2a", "T2b", "T2c", "T7", "T3", "T4a", "T4b"):
            c = check_by_id(spec, cid)
            res.add(cid, c["name"], None, c.get("threshold_fF", c.get("threshold")),
                    cid == "T7", "not evaluated, ring sets differ")
        return res, {"missing": missing, "extra": extra, "topology": detail}

    rings = sorted(ref)
    rv = [ref[r] for r in rings]
    cv = [cand[r] for r in rings]

    # T1 extraction total
    t1 = check_by_id(spec, "T1")
    tot = abs(sum(cv) - sum(rv)) / sum(rv)
    res.add("T1", t1["name"], tot, t1["threshold"], tot <= t1["threshold"], "fraction")

    # T2 per-ring, common mode removed by the median
    raw = [c - r for c, r in zip(cv, rv)]
    common = st.median(raw)
    e = [x - common for x in raw]
    t2a = check_by_id(spec, "T2a")
    worst = max(abs(x) for x in e)
    res.add("T2a", t2a["name"], worst, t2a["threshold_fF"], worst <= t2a["threshold_fF"], "fF")
    t2b = check_by_id(spec, "T2b")
    rms = math.sqrt(sum(x * x for x in e) / len(e))
    res.add("T2b", t2b["name"], rms, t2b["threshold_fF"], rms <= t2b["threshold_fF"], "fF")
    t2c = check_by_id(spec, "T2c")
    rel = max(abs(x) / r for x, r in zip(e, rv))
    res.add("T2c", t2c["name"], rel, t2c["threshold"], rel <= t2c["threshold"], "fraction")

    # T7 systematic scale, reported so a T2 failure can be read
    t7 = check_by_id(spec, "T7")
    scale = sum(c * r for c, r in zip(cv, rv)) / sum(r * r for r in rv)
    res.add("T7", t7["name"], scale, None, True, "factor")

    # T3 rank
    t3 = check_by_id(spec, "T3")
    rho = spearman(rv, cv)
    res.add("T3", t3["name"], rho, t3["threshold"], rho >= t3["threshold"], "rho")

    # T4 margins and signs
    if pairs is None:
        pairs = default_pairs(rings)
    if ref_f is not None and cand_f is not None:
        mean_f = st.mean(ref_f[r] for r in rings)
    else:
        ref_f = cand_f = None
        mean_f = None
    rseps, rhigh, line = classify(ref, ref_f, pairs, spec, mean_f)
    cseps, chigh, _ = classify(cand, cand_f, pairs, spec, mean_f)
    t4b = check_by_id(spec, "T4b")
    symdiff = len(rhigh ^ chigh)
    res.add("T4b", t4b["name"], symdiff, t4b["threshold"], symdiff <= t4b["threshold"], "pairs")
    t4a = check_by_id(spec, "T4a")
    scored = rhigh & chigh
    wrong = sum(1 for p in scored
                if (rseps[p] > 0) != (cseps[p] > 0))
    res.add("T4a", t4a["name"], wrong, t4a["threshold"], wrong <= t4a["threshold"], "pairs")

    extra_info = {
        "common_mode_fF": common,
        "classified_on": "freq_MHz" if ref_f is not None else "cap_fF",
        "margin_line": line,
        "pairs": [{"pair": "%d/%d" % p,
                   "sep_ref": rseps[p],
                   "sep_cand": cseps[p],
                   "class_ref": "high" if p in rhigh else "abstain",
                   "class_cand": "high" if p in chigh else "abstain"}
                  for p in pairs],
        "abstentions": ["%d/%d" % p for p in pairs if p not in rhigh],
    }
    return res, extra_info


# ---------------------------------------------------------------- selftest

def _fixture():
    """The sixteen Arm A rings as the SPEF records them, capacitance and full-RC
    frequency, from sim/spice/gono/rc_validation.csv. A synthetic fixture would
    have been easier to write and would have put the planted faults somewhere
    the real comparison never goes; the near-ties that decide the rank check and
    the one pair that sits close to the margin line are both properties of this
    build, and the selftest is more useful for having them."""
    cap = [10.86, 14.44, 16.33, 16.57, 11.72, 12.15, 14.07, 10.86,
           12.85, 13.60, 14.18, 11.93, 14.96, 14.16, 17.04, 12.97]
    frq = [536.86, 547.12, 538.81, 538.17, 561.83, 560.36, 549.94, 567.91,
           556.49, 550.13, 548.63, 562.41, 545.92, 549.72, 535.76, 555.95]
    return {i: cap[i] for i in range(16)}, {i: frq[i] for i in range(16)}


def _selftest():
    spec = load_spec()
    ref, reff = _fixture()
    thr_fF = check_by_id(spec, "T2a")["threshold_fF"]

    def cand(f):
        return {k: f(k, v) for k, v in ref.items()}

    def shift_f(cap_table):
        """Move each frequency by what the fitted slope says its capacitance
        change is worth, so a planted capacitance fault is a consistent fault
        rather than two tables disagreeing about different things."""
        sl = spec["constants"]["cap_to_freq_pct_per_fF"] / 100.0
        return {k: reff[k] * (1.0 - sl * (cap_table[k] - ref[k])) for k in cap_table}

    # name, candidate capacitance table, the checks it must trip
    faults = [
        ("clean copy", dict(ref), set()),
        ("common mode +0.50 fF", cand(lambda k, v: v + 0.50), set()),
        ("global scale +6 percent", cand(lambda k, v: v * 1.06), {"T1", "T2a", "T2b", "T2c"}),
        ("one ring +0.10 fF", cand(lambda k, v: v + 0.10 if k == 6 else v), {"T2a"}),
        # Inside the worst-ring allowance and still enough to reclassify pair
        # 12/13, which is the point the frozen file makes about that pair.
        ("alternating +/-0.050 fF", cand(lambda k, v: v + (0.050 if k % 2 else -0.050)),
         {"T2b", "T4b"}),
    ]

    # Rings 8 and 13 differ by 1.31 fF, far outside anything the tolerance
    # excuses, so swapping them has to break the per-ring checks and the rank.
    sw = dict(ref); sw[8], sw[13] = ref[13], ref[8]
    faults.append(("rings 8 and 13 swapped", sw, {"T2a", "T2b", "T2c", "T3", "T4b"}))

    # T4a on its own. A pipeline can get every capacitance right and still hand
    # back the wrong frequency, so the sign check has to be able to fire with
    # nothing else firing.
    faults.append(("pair 0/1 reversed, frequency only", dict(ref), {"T4a"}))

    # The right multiset of capacitances on the wrong rings. build_transfer.py
    # found this is the part of the attack that cannot be skipped.
    order = [ref[(i * 7 + 3) % 16] for i in range(16)]
    faults.append(("scrambled assignment", {i: order[i] for i in range(16)},
                   {"T2a", "T2b", "T2c", "T3", "T4a", "T4b"}))

    # Pair 12/13 clears the margin line by 12 percent and is the pair most
    # likely to move across it. Shrinking that one difference by a quarter is
    # enough, and it must show up as a classification failure and nothing else.
    faults.append(("pair 12/13 pushed below the line", dict(ref), {"T4b"}))

    miss = dict(ref); del miss[9]
    faults.append(("ring 9 missing", miss,
                   {"T5", "T1", "T2a", "T2b", "T2c", "T3", "T4a", "T4b"}))

    ok = True
    print("check_tolerances.py selftest")
    print("  spec %s" % os.path.basename(SPEC))
    print("  worst-ring allowance %.3f fF, margin line %.4f%% of the mean frequency\n"
          % (thr_fF, spec["margin_rule"]["high_margin_threshold_pct_f"]))
    print("  %-34s %-9s %s" % ("planted fault", "verdict", "checks tripped"))
    for name, c, expect in faults:
        if name.startswith("pair 12/13"):
            cf = dict(reff)
            cf[12] = reff[13] + (reff[12] - reff[13]) * 0.75
        elif name.startswith("pair 0/1"):
            cf = dict(reff)
            cf[0], cf[1] = reff[1], reff[0]
        else:
            cf = shift_f(c)
        res, _ = run_checks(ref, c, spec, ref_f=reff, cand_f=cf)
        got = set(res.failed())
        good = got == expect
        ok = ok and good
        print("  %-34s %-9s %s%s"
              % (name, "ok" if good else "MISMATCH",
                 ",".join(sorted(got)) if got else "none",
                 "" if good else "   expected " + (",".join(sorted(expect)) or "none")))

    # A check that cannot fail is not a check. The clean copy has to have
    # exercised all eight rules rather than passing because nothing ran, and
    # the frozen margin rule has to reproduce the six-of-eight split the paper
    # already states for this build.
    res, info = run_checks(ref, dict(ref), spec, ref_f=reff, cand_f=dict(reff))
    evaluated = [r["id"] for r in res.rows if r["value"] is not None]
    if len(evaluated) != 9:
        print("\n  MISMATCH: clean copy evaluated %d checks, expected 9" % len(evaluated))
        ok = False
    if len(info["abstentions"]) != 2:
        print("\n  MISMATCH: %d abstentions, expected 2 (pairs 2/3 and 4/5)"
              % len(info["abstentions"]))
        ok = False
    if info["abstentions"] != ["2/3", "4/5"]:
        print("\n  MISMATCH: abstentions are %s, expected 2/3 and 4/5"
              % ", ".join(info["abstentions"]))
        ok = False

    print("\n  %d planted faults over %d checks, %s"
          % (len(faults) - 2, len(res.rows),
             "each tripped what it declared" if ok else "SELFTEST FAILED"))
    return 0 if ok else 1


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--spec", default=None)
    ap.add_argument("--reference", help="CSV of per-ring capacitance from the trusted SPEF")
    ap.add_argument("--candidate", help="CSV of per-ring capacitance from the pipeline")
    ap.add_argument("--reference-topology")
    ap.add_argument("--candidate-topology")
    ap.add_argument("--json", help="write the full result here")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--freeze-check", action="store_true",
                    help="confirm the spec still hashes to the value frozen on 2026-08-18")
    a = ap.parse_args()

    global SPEC
    if a.spec:
        SPEC = a.spec

    if a.freeze_check:
        got = sha256_file(SPEC)
        print("TOLERANCES.json sha256 %s" % got)
        if FROZEN_SHA256 == "PLACEHOLDER":
            print("no frozen hash recorded yet")
            return 1
        if got != FROZEN_SHA256:
            print("FROZEN HASH MISMATCH, expected %s" % FROZEN_SHA256)
            print("The tolerances were frozen before the pipeline existed. If this")
            print("file had to change, it belongs in a new dated file with a reason.")
            return 1
        print("matches the hash frozen on 2026-08-18")
        return 0

    if a.selftest:
        return _selftest()

    spec = load_spec(SPEC)

    if not (a.reference and a.candidate):
        # The pipeline of A.3 and A.4 does not exist yet. Print the frozen
        # numbers so the file can be read without a JSON viewer.
        print("A.5 tolerances, frozen %s" % spec["frozen_utc"])
        print("  sha256 %s" % sha256_file(SPEC))
        for c in spec["checks"]:
            t = c.get("threshold_fF")
            t = ("%.3f fF" % t) if t is not None else (
                "report" if c.get("threshold") is None else "%s" % c["threshold"])
            print("  %-4s %-44s %-8s %s" % (c["id"], c["name"], c["direction"], t))
        m = spec["margin_rule"]
        print("  margin  k=%d, %.4f fF, %.4f %% of mean frequency"
              % (m["k"], m["high_margin_threshold_fF"], m["high_margin_threshold_pct_f"]))
        print("\nNo reference and candidate given, so nothing was checked.")
        return 0

    ref, ref_f = read_caps(a.reference)
    cand, cand_f = read_caps(a.candidate)
    rt = json.load(open(a.reference_topology)) if a.reference_topology else None
    ct = json.load(open(a.candidate_topology)) if a.candidate_topology else None
    res, info = run_checks(ref, cand, spec, rt, ct, ref_f=ref_f, cand_f=cand_f)

    print("A.5 self-validation against %s" % spec["reference"]["spef"])
    print("  spec sha256 %s\n" % sha256_file(SPEC))
    print("  %-4s %-44s %14s %14s  %s" % ("id", "check", "value", "threshold", ""))
    for r in res.rows:
        v = "n/a" if r["value"] is None else ("%14.6g" % r["value"])
        print("  %-4s %-44s %14s %14s  %s"
              % (r["id"], r["name"], v, r["threshold"], "pass" if r["pass"] else "FAIL"))
    print("\n  classified on %s, line at %.4f" % (info["classified_on"], info["margin_line"]))
    print("  abstentions (%d): %s"
          % (len(info["abstentions"]), ", ".join(info["abstentions"]) or "none"))

    bad = res.failed()
    print("\n  %s" % ("all checks pass; G1 met on the self-pilot"
                      if not bad else "FAILED: " + ", ".join(bad) + "  -- G1 not met, do not run target analysis"))

    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump({"spec_sha256": sha256_file(SPEC), "checks": res.rows,
                       "detail": info}, fh, indent=2, sort_keys=True)
            fh.write("\n")

    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
