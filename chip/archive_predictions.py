#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""The per-pair sign predictions, written down before any die is read.

The preregistration ends on a promise it cannot keep by itself. Its
analysis_freeze says the per-pair sign predictions from the public design
database are archived and hashed before any die is read. The frozen file
fixed how a prediction is judged, the first amendment which arm and which
test carry the claim, the second which pairs are scored. None of the
three ever wrote a prediction down. Each one is implied by four tables the
second amendment records by hash, and that is a long way from a file
someone outside the project can hold a die against.

This writes the file, chip/PREDICTIONS.json. All twenty-four pairs, the
separation each table gives them, whether each is scored as frozen and as
amended, and for the scored ones the sign the die is expected to show. It
reads only the tables chip/PREREG_AMENDMENT_2.json names, at the paths and
columns it names, and it stops if one of them no longer hashes to what the
amendment recorded. An archive built from a table nobody amended against
would look exactly like this one and mean nothing.

The second sentence of that analysis_freeze was not kept, and the archive
says so in its own field instead of leaving it to this docstring. Arm A's
eight SPEF signs went public in docs/phaseG_g3_extract.md on 19 September
and in README.md the next day, beside Arm C's. A git commit is history a
force push can rewrite, so it is not the archive the preregistration
meant. C04 holds the strings already published to the tables, so the two
cannot part from here on.

Checks, each with a planted fault in --selftest that trips it and nothing
else:

  C01  the tables are the ones the second amendment recorded, byte for byte
  C02  the pairs scored as amended, worked from those tables here, are the
       amendment's own lists, arm by arm
  C03  the pairs over the line in the SPEF's table alone are the
       amendment's scored_as_frozen lists
  C04  the SPEF signs of Arms A and C are the strings README.md published
  C05  every prediction in the archive on disk is the sign both tables give,
       and no abstention carries one

C04 counts what its patterns matched before it says anything about them. A
README that lost the sentence would otherwise pass for one that agrees.

The archive is gated on its own hash as well, the way the preregistration
is: --freeze-check compares chip/PREDICTIONS.json with FROZEN_SHA256 below
and looks for the same hash in the write-up. The gate also diffs a fresh
rendering against the file on disk, so it cannot drift from its tables, and
chip/hash_stability.py holds every hash the archive records, which is what
stops a table changing under it.

What it does not do. It does not move the archive off GitHub. That deposit,
a release with Zenodo's copy and DOI, is a step for me to take by hand with
my own accounts, and docs/phaseG_predictions_archive.md says how. It does
not predict anything new either. Every number in the archive is one of the
second amendment's, carried to the sign.

Usage:
    python3 archive_predictions.py --selftest
    python3 archive_predictions.py
    python3 archive_predictions.py --json /tmp/predictions.json
    python3 archive_predictions.py --freeze-check
"""

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

ARCHIVE_REL = "chip/PREDICTIONS.json"
AMENDMENT2_REL = "chip/PREREG_AMENDMENT_2.json"
TOLERANCES_REL = "extraction/TOLERANCES.json"
README_REL = "README.md"

# Recorded by hash in the archive, read for nothing else. The preregistration
# and both amendments are what the predictions answer to; the three layout
# files are run 83's, the build Tiny Tapeout holds for SKY 26d.
RECORDED = ("chip/PREREGISTRATION.json",
            "chip/PREREG_AMENDMENT.json",
            "chip/PREREG_AMENDMENT_2.json")
LAYOUT = ("dualarm/build_armc/tt_um_nikodemetrashvili20_ro_puf.def",
          "dualarm/build_armc/tt_um_nikodemetrashvili20_ro_puf.nom.spef",
          "dualarm/build_armc/tt_um_nikodemetrashvili20_ro_puf.gds")

ARMS = ("A", "B", "C")
N_RING = 16
N_PAIR = N_RING // 2

# Where README.md states each arm's eight signs on the release build. Each
# pattern has to match exactly once. Arm B's signs were never published.
PUBLISHED = {
    "A": r"`[01]{8}` on the baseline, `([01]{8})` on the release build",
    "C": r"Its bits, `([01]{8})`, come out the same",
}

WRITTEN = "2026-10-26"

# SHA-256 of chip/PREDICTIONS.json as written on 2026-10-26. Also in
# docs/phaseG_predictions_archive.md.
FROZEN_SHA256 = \
    "8a7bf09522d1539eaa768340042a9d2ccbe72538b5b4a1b56338623b7bc3af23"
RECORDED_IN = ("docs/phaseG_predictions_archive.md",)


def sha256_file(path):
    """The bytes a checkout produces, the rule chip/release_manifest.py
    states in full: LF for text, the raw bytes when git would leave the
    file alone (a NUL early on, or a carriage return on its own)."""
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


# --------------------------------------------------------------- reading

def load_json(root, rel):
    with open(os.path.join(root, rel), "r", encoding="utf-8") as fh:
        return json.load(fh)


def pair_name(j):
    return "%d/%d" % (2 * j, 2 * j + 1)


def ring_mhz(root, rel, column, arm):
    """One arm's sixteen frequencies in MHz, ring 0 first.

    Three shapes of table, told apart by what they hold rather than by
    their names: ngspice's own f_kNN lines for Arm B's instance decks, a
    ring column like A00 in magic's table, a plain ro column in the RC
    tables. Anything short of sixteen rings once each stops the run."""
    with open(os.path.join(root, rel), "r", encoding="utf-8") as fh:
        text = fh.read()
    got = []
    if column == "f_kNN":
        for m in re.finditer(r"(?m)^f_k(\d\d)\s*=\s*(\S+)\s*$", text):
            got.append((int(m.group(1)), float(m.group(2)) / 1e6))
    else:
        rows = list(csv.DictReader(text.splitlines()))
        for r in rows:
            if "ring" in r:
                tag = r["ring"]
                if tag[:1] == arm and tag[1:].isdigit():
                    got.append((int(tag[1:]), float(r[column])))
            else:
                got.append((int(r["ro"]), float(r[column])))
    idx = sorted(i for i, _ in got)
    if idx != list(range(N_RING)):
        raise ValueError("%s: Arm %s has rings %s, not 0 to 15 once each"
                         % (rel, arm, idx))
    return [f for _, f in sorted(got)]


def pair_seps(freqs):
    """f_a minus f_b for each adjacent pair, as a percent of the mean of
    the same table's sixteen, the convention the second amendment states."""
    mean = sum(freqs) / float(len(freqs))
    return [100.0 * (freqs[2 * j] - freqs[2 * j + 1]) / mean
            for j in range(N_PAIR)]


def sign_bit(x):
    """1 when the lower ring is faster. A pair the table calls exactly
    level has no sign, and the archive must not invent one."""
    if x == 0:
        raise ValueError("a pair with no separation at all")
    return 1 if x > 0 else 0


def tables(root, am2):
    """The four tables, read where the amendment says they are."""
    t = am2["tables"]
    first = {}
    for arm in ARMS:
        first[arm] = ring_mhz(root, t["first"][arm]["path"],
                              t["first"][arm]["column"], arm)
    second = {}
    for arm in ARMS:
        second[arm] = ring_mhz(root, t["second"]["path"],
                               t["second"]["column"], arm)
    tol = load_json(root, t["line"]["path"])
    line = tol
    for key in t["line"]["key"].split("."):
        line = line[key]
    return first, second, float(line)


def table_files(am2):
    """Every file the amendment records a hash for, with that hash."""
    t = am2["tables"]
    out = [(t["line"]["path"], t["line"]["sha256"])]
    for arm in ARMS:
        out.append((t["first"][arm]["path"], t["first"][arm]["sha256"]))
    out.append((t["second"]["path"], t["second"]["sha256"]))
    return out


# ---------------------------------------------------------------- the rule

def classify(spef, magic, line):
    """One arm, both rules. As frozen a pair is scored when the SPEF's
    separation clears the line. As amended it has to clear it in magic's
    table too, with the same sign, and that sign is the prediction."""
    s1, s2 = pair_seps(spef), pair_seps(magic)
    rows = []
    for j in range(N_PAIR):
        frozen = abs(s1[j]) >= line
        both = (frozen and abs(s2[j]) >= line
                and (s1[j] > 0) == (s2[j] > 0))
        rows.append({"pair": pair_name(j),
                     "spef_pct": s1[j], "magic_pct": s2[j],
                     "as_frozen": "scored" if frozen else "abstains",
                     "as_amended": "scored" if both else "abstains",
                     "spef_sign": sign_bit(s1[j]),
                     "magic_sign": sign_bit(s2[j]),
                     "prediction": sign_bit(s1[j]) if both else None})
    return rows


def sd(xs):
    m = sum(xs) / float(len(xs))
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


# --------------------------------------------------------------- archive

COMMENT = [
    "The per-pair sign predictions for SKY 26d, written before any die",
    "was read. chip/archive_predictions.py renders this file from the",
    "four tables chip/PREREG_AMENDMENT_2.json names and stops if one of",
    "them has changed since the amendment recorded it.",
    "",
    "A pair is ring 2j against ring 2j+1 in one arm. Its bit is 1 when",
    "the lower ring runs faster. A separation is f_a minus f_b as a",
    "percent of the arm's mean in the same table. Strings run pair 0/1",
    "first and 14/15 last, and x marks an abstention, which is counted",
    "and published and never scored either way.",
    "",
    "Scored means scored by the second amendment's rule, the one that",
    "holds: over the line, with the same sign, in both tables.",
    "as_frozen is kept beside it so the frozen rule's answer stays",
    "visible. The scored pairs of Arm A carry M1, which is tested at",
    "0.05 only after M4 has cleared 0.025. Arm C's are secondary, and",
    "Arm B scores none.",
]

NOT_IN_THE_MODEL = [
    "Ring mismatch. Every separation here is the layout's alone. A die",
    "adds about 0.062 percent a ring of its own, which the line in",
    "extraction/TOLERANCES.json is built to allow for.",
    "Metal fill. Whether SKY 26d fills inside the tile is not known.",
    "With open_pdks' fill at four grid positions the five Arm A pairs",
    "scored here keep their sign and stay over the line. Arm C's three",
    "do not: 12/13 turns round, 4/5 and 14/15 fall under the line",
    "(sim/spice/magic/, chip/PREREG_AMENDMENT_2.json).",
    "Tiny Tapeout's decap swap, a tenth of the top-level decap_3 cells",
    "drawn again at every submission. Bounded on 20 October over 20000",
    "draws, and no pair over the line could turn.",
    "Voltage and temperature. The tables are the typical corner. The",
    "SPEF's signs for Arms A and C come out the same at ss, tt and ff",
    "(README.md). The preregistration names no cell for M1, and the",
    "nominal cell M2 and M4 use names no window. Both are open.",
]

WENT_PUBLIC = [
    "PREREGISTRATION.json says nothing about a prediction goes public",
    "before it is archived. That was not kept. Arm A's eight SPEF signs",
    "were in docs/phaseG_g3_extract.md in 796b776 on 2026-09-19, and",
    "README.md carried them with Arm C's in 1987e6c on 2026-09-20, both",
    "pushed. They are the spef_signs strings of Arms A and C in this",
    "file, unchanged, and C04 holds the README to them. Both commits came",
    "after the layout was final and before any die existed, so nothing",
    "could have been fitted, but a commit is not an archive in the",
    "preregistration's sense.",
]


def build(root):
    """The archive as a dict, in the order it is written."""
    am2 = load_json(root, AMENDMENT2_REL)
    first, second, line = tables(root, am2)
    source = {}
    for rel, _ in table_files(am2):
        source[rel] = sha256_file(os.path.join(root, rel))
    for rel in RECORDED:
        source[rel] = sha256_file(os.path.join(root, rel))
    layout = {}
    for rel in LAYOUT:
        layout[rel] = sha256_file(os.path.join(root, rel))

    arms = {}
    for arm in ARMS:
        rows = classify(first[arm], second[arm], line)
        scored = [r["pair"] for r in rows if r["as_amended"] == "scored"]
        frozen = [r["pair"] for r in rows if r["as_frozen"] == "scored"]
        arms[arm] = {
            "scored": scored,
            "scored_as_frozen": frozen,
            "predicted": "".join("x" if r["prediction"] is None
                                 else str(r["prediction"]) for r in rows),
            "spef_signs": "".join(str(r["spef_sign"]) for r in rows),
            "magic_signs": "".join(str(r["magic_sign"]) for r in rows),
            "pairs": [{"pair": r["pair"],
                       "spef_pct": round(r["spef_pct"], 3),
                       "magic_pct": round(r["magic_pct"], 3),
                       "as_frozen": r["as_frozen"],
                       "as_amended": r["as_amended"],
                       "prediction": r["prediction"]} for r in rows],
        }

    m4 = {"spef": round(sd(first["C"]) / sd(first["A"]), 3),
          "magic": round(sd(second["C"]) / sd(second["A"]), 3),
          "what": ["Arm C's standard deviation over Arm A's, sixteen rings",
                   "each, at the nominal corner. M4 wants the die's to be",
                   "under 1 with its interval clear of 1."]}

    return {
        "_comment": COMMENT,
        "written": WRITTEN,
        "producer": "archive_predictions.py",
        "dies_read_when_written": 0,
        "line_pct_f": line,
        "source": {"sha256": source},
        "layout": {"what": "run 83, the release build, dualarm/build_armc/",
                   "sha256": layout},
        "arms": arms,
        "m4_model": m4,
        "not_in_the_model": NOT_IN_THE_MODEL,
        "went_public_before_this_archive": WENT_PUBLIC,
    }


def render(obj):
    return json.dumps(obj, indent=2, ensure_ascii=True) + "\n"


# ---------------------------------------------------------------- checks

def published_strings(root):
    """arm -> list of every match its pattern found in README.md."""
    with open(os.path.join(root, README_REL), "r", encoding="utf-8") as fh:
        text = re.sub(r"\s+", " ", fh.read())
    return dict((arm, re.findall(pat, text))
                for arm, pat in sorted(PUBLISHED.items()))


def run_checks(root):
    res = Results()
    am2 = load_json(root, AMENDMENT2_REL)

    stale = []
    for rel, want in table_files(am2):
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            stale.append(rel + " (missing)")
        elif sha256_file(path) != want:
            stale.append(rel)
    res.add("C01", "the tables are the ones the second amendment recorded",
            not stale, ", ".join(stale) or "%d files" % len(table_files(am2)))
    if stale:
        # Nothing below means anything on tables the amendment never saw.
        return res

    first, second, line = tables(root, am2)
    rows = dict((arm, classify(first[arm], second[arm], line))
                for arm in ARMS)
    rule = am2["amends"][0]

    wrong = []
    for arm in ARMS:
        got = [r["pair"] for r in rows[arm] if r["as_amended"] == "scored"]
        if got != rule["scored"][arm]:
            wrong.append("%s %s against %s" % (arm, got, rule["scored"][arm]))
    res.add("C02", "the pairs scored as amended are the amendment's lists",
            not wrong, "; ".join(wrong) or "A %d, B %d, C %d"
            % tuple(len(rule["scored"][a]) for a in ARMS))

    wrong = []
    for arm in ARMS:
        got = [r["pair"] for r in rows[arm] if r["as_frozen"] == "scored"]
        if got != rule["scored_as_frozen"][arm]:
            wrong.append("%s %s against %s"
                         % (arm, got, rule["scored_as_frozen"][arm]))
    res.add("C03", "the pairs over the line in the SPEF's table are the "
                   "amendment's scored_as_frozen lists",
            not wrong, "; ".join(wrong) or "A %d, B %d, C %d"
            % tuple(len(rule["scored_as_frozen"][a]) for a in ARMS))

    found = published_strings(root)
    wrong = []
    for arm in sorted(PUBLISHED):
        mine = "".join(str(r["spef_sign"]) for r in rows[arm])
        if len(found[arm]) != 1:
            wrong.append("%s: the README sentence matched %d times"
                         % (arm, len(found[arm])))
        elif found[arm][0] != mine:
            wrong.append("%s: README %s, tables %s"
                         % (arm, found[arm][0], mine))
    res.add("C04", "the SPEF signs are the strings README.md published",
            not wrong, "; ".join(wrong) or ", ".join(
                "%s %s" % (a, found[a][0]) for a in sorted(PUBLISHED)))

    wrong = []
    path = os.path.join(root, ARCHIVE_REL)
    if not os.path.exists(path):
        wrong.append("no archive on disk")
    else:
        disk = load_json(root, ARCHIVE_REL)
        for arm in ARMS:
            held = dict((p["pair"], p.get("prediction"))
                        for p in disk.get("arms", {}).get(arm, {})
                        .get("pairs", []))
            if len(held) != N_PAIR:
                wrong.append("%s: %d pairs on disk" % (arm, len(held)))
                continue
            for r in rows[arm]:
                want = r["prediction"]
                if held.get(r["pair"]) != want:
                    wrong.append("%s %s: disk %s, tables %s"
                                 % (arm, r["pair"], held.get(r["pair"]),
                                    want))
    res.add("C05", "every prediction on disk is the sign both tables give",
            not wrong, "; ".join(wrong[:4]) or "24 pairs, %d predictions"
            % sum(1 for a in ARMS for r in rows[a]
                  if r["prediction"] is not None))
    return res


def show(res):
    for r in res.rows:
        print("  %s %s  %s" % ("ok  " if r["pass"] else "FAIL", r["id"],
                               r["name"]))
        print("            %s" % r["detail"])


def report(root):
    obj = build(root)
    print("line %.4f percent of the arm's mean, from %s"
          % (obj["line_pct_f"], TOLERANCES_REL))
    print()
    print("  arm  predicted  spef signs  magic signs  scored")
    for arm in ARMS:
        a = obj["arms"][arm]
        print("   %s   %s   %s    %s     %s"
              % (arm, a["predicted"], a["spef_signs"], a["magic_signs"],
                 " ".join(a["scored"]) or "none"))
    print()
    print("  M4 in the models: %.3f from the SPEF, %.3f from magic"
          % (obj["m4_model"]["spef"], obj["m4_model"]["magic"]))
    print()
    res = run_checks(root)
    show(res)
    bad = res.failed()
    print()
    print("FAIL: %s" % ", ".join(bad) if bad else
          "PASS: the archive is the second amendment's predictions")
    return 1 if bad else 0


def freeze_check(root=ROOT, want=None):
    want = want or FROZEN_SHA256
    got = sha256_file(os.path.join(root, ARCHIVE_REL))
    print("PREDICTIONS.json sha256 %s" % got)
    ok = got == want
    print("  %s archive_predictions.py" % ("ok  " if ok else "FAIL"))
    if not ok:
        print("       has %s" % want)
        print("       The archive was written before any die was read.")
        print("       A change to it is a new dated file with a reason.")
    for rel in RECORDED_IN:
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            print("  FAIL %s is missing" % rel)
            ok = False
            continue
        with open(path, "r", encoding="utf-8") as fh:
            carried = got in fh.read()
        print("  %s %s" % ("ok  " if carried else "FAIL", rel))
        ok = ok and carried
    return 0 if ok else 1


# -------------------------------------------------------------- selftest

def make_fixture(tmp):
    """A small tree holding copies of the real inputs. The three layout
    files are stood in for by short text, since the archive only hashes
    them and the selftest has no business reading a GDS."""
    am2 = load_json(ROOT, AMENDMENT2_REL)
    rels = [rel for rel, _ in table_files(am2)]
    rels += list(RECORDED) + [README_REL]
    for rel in rels:
        dst = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(os.path.join(ROOT, rel), dst)
    for rel in LAYOUT:
        dst = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8") as fh:
            fh.write("stand-in for %s\n" % rel)
    write_archive(tmp)


def write_archive(root):
    path = os.path.join(root, ARCHIVE_REL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render(build(root)))


def edit(root, rel, old, new):
    path = os.path.join(root, rel)
    with open(path, "r", encoding="utf-8", newline="") as fh:
        text = fh.read()
    if text.count(old) != 1:
        raise AssertionError("%s: %r found %d times"
                             % (rel, old, text.count(old)))
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text.replace(old, new))


def set_ring(root, rel, ring, column, value):
    """Rewrite one ring's frequency in a csv table, through the csv
    module so the other rows keep their bytes."""
    path = os.path.join(root, rel)
    with open(path, "r", encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    head = rows[0]
    key = 0
    hit = 0
    for r in rows[1:]:
        if r[key] == ring:
            r[head.index(column)] = value
            hit += 1
    if hit != 1:
        raise AssertionError("%s: ring %s found %d times" % (rel, ring, hit))
    with open(path, "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh, lineterminator="\n").writerows(rows)


def rehash(root, rel):
    """What a careless edit would do next: put the table's new hash into
    the amendment, so C01 passes and the next check has to catch it."""
    am2 = load_json(root, AMENDMENT2_REL)
    old = [h for r, h in table_files(am2) if r == rel][0]
    edit(root, AMENDMENT2_REL, old, sha256_file(os.path.join(root, rel)))


def fault_table_bytes(root):
    path = os.path.join(root, "sim/spice/magic/magic_rings.csv")
    with open(path, "a", encoding="utf-8", newline="") as fh:
        fh.write("\n")


def fault_magic_drops_45(root):
    rel = "sim/spice/magic/magic_rings.csv"
    f = ring_mhz(root, rel, "magic_MHz", "A")
    set_ring(root, rel, "A04", "magic_MHz", "%.4f" % (f[5] + 1.5))
    rehash(root, rel)
    write_archive(root)


def fault_spef_lifts_23(root):
    rel = "sim/spice/gono/rc_validation_3arm.csv"
    f = ring_mhz(root, rel, "rc_MHz", "A")
    set_ring(root, rel, "2", "rc_MHz", "%.2f" % (f[3] + 3.9))
    rehash(root, rel)
    write_archive(root)


def fault_spef_turns_23(root):
    rel = "sim/spice/gono/rc_validation_3arm.csv"
    f = ring_mhz(root, rel, "rc_MHz", "A")
    set_ring(root, rel, "2", "rc_MHz", "%.2f" % (f[3] - 0.5))
    rehash(root, rel)
    write_archive(root)


def fault_disk_flipped(root):
    obj = load_json(root, ARCHIVE_REL)
    for p in obj["arms"]["A"]["pairs"]:
        if p["pair"] == "6/7":
            p["prediction"] = 1 - p["prediction"]
    with open(os.path.join(root, ARCHIVE_REL), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write(render(obj))


def fault_readme_silent(root):
    edit(root, README_REL, "`, come out the same", "`, are the same")


FAULTS = (
    ("a table rewritten, every number the same", fault_table_bytes, "C01"),
    ("magic moves pair 4/5 under the line, hash re-recorded",
     fault_magic_drops_45, "C02"),
    ("the SPEF lifts pair 2/3 over the line, hash re-recorded",
     fault_spef_lifts_23, "C03"),
    ("the SPEF turns pair 2/3 round under the line, hash re-recorded",
     fault_spef_turns_23, "C04"),
    ("a prediction flipped in the archive on disk", fault_disk_flipped,
     "C05"),
    ("the README loses Arm C's sentence", fault_readme_silent, "C04"),
)


def quiet(fn, *args):
    """Run fn with its printing thrown away, return what it returns."""
    saved = sys.stdout
    sys.stdout = open(os.devnull, "w")
    try:
        return fn(*args)
    finally:
        sys.stdout.close()
        sys.stdout = saved


def selftest():
    print("self-test of archive_predictions")
    ok = True
    tmp = tempfile.mkdtemp(prefix="predictions_")
    try:
        base = os.path.join(tmp, "control")
        make_fixture(base)
        fails = run_checks(base).failed()
        good = not fails
        ok = ok and good
        print("  %-62s %s" % ("control, the real inputs",
                              "ok" if good else "FAILED " + ", ".join(fails)))
        a = load_json(base, ARCHIVE_REL)["arms"]
        want = {"A": "xx10x000", "B": "xxxxxxxx", "C": "xx0xxx10"}
        good = dict((k, a[k]["predicted"]) for k in ARMS) == want
        ok = ok and good
        print("  %-62s %s" % ("the control's predictions by hand",
                              "ok" if good else "WRONG"))
        for i, (label, fault, expect) in enumerate(FAULTS):
            d = os.path.join(tmp, "f%d" % i)
            make_fixture(d)
            fault(d)
            fails = run_checks(d).failed()
            good = fails == [expect]
            ok = ok and good
            print("  %-62s %s" % (label, ("trips %s" % expect) if good
                                  else "MISSED, tripped %s" % fails))

        d = os.path.join(tmp, "freeze")
        make_fixture(d)
        doc = os.path.join(d, RECORDED_IN[0])
        os.makedirs(os.path.dirname(doc), exist_ok=True)
        h = sha256_file(os.path.join(d, ARCHIVE_REL))
        with open(doc, "w", encoding="utf-8") as fh:
            fh.write("sha256 %s\n" % h)
        good = quiet(freeze_check, d, h) == 0
        print("  %-62s %s" % ("freeze check, archive and write-up agree",
                              "ok" if good else "FAILED"))
        ok = ok and good
        fault_disk_flipped(d)
        good = quiet(freeze_check, d, h) == 1
        print("  %-62s %s" % ("freeze check, one prediction changed",
                              "caught" if good else "MISSED"))
        ok = ok and good
        write_archive(d)
        with open(doc, "w", encoding="utf-8") as fh:
            fh.write("no hash here\n")
        good = quiet(freeze_check, d, h) == 1
        print("  %-62s %s" % ("freeze check, write-up without the hash",
                              "caught" if good else "MISSED"))
        ok = ok and good
    finally:
        shutil.rmtree(tmp)
    print("self-test %s" % ("passed" if ok else "FAILED"))
    return 0 if ok else 1


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", help="write a fresh rendering here")
    ap.add_argument("--freeze-check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.freeze_check:
        return freeze_check()
    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(render(build(ROOT)))
        print("wrote %s" % args.json)
        return 0
    return report(ROOT)


if __name__ == "__main__":
    sys.exit(main())
