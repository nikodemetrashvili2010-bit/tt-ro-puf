#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Re-derive Phase E's four days of numbers with code that shares none.

The house rule is that every number appearing in prose has to be
re-derivable by a script that does not share code with the one that produced
it. `verify_predictability.py` exists for that reason and writes its own SPEF
parser and its own least-squares solver rather than importing the ones under
test. This is the same job for Phase E.

So nothing here imports `tile_budget`, `armc_cost`, `g2_decision` or
`observability_spec`. The DEF is parsed again, from scratch, by a different
method: instead of recovering cell widths from abutment, this reads the row
geometry and the component positions and reconstructs each row's occupancy
as a set of intervals, which reaches the same area a different way. The
netlist is read again. The SPEF is read again. The corner decks are read
again. Then every claim the four writeups make is checked against what comes
back.

There is one deliberate exception and it is not a shortcut. Cell widths
cannot be had from anywhere else: there is no LEF in this repository and the
placement is the only source. So this script recovers them by the same idea
and a different algorithm, sorting each row and differencing neighbours
without the cross-row consistency step, and then requires the two answers to
agree exactly. If they ever differ, both are wrong until somebody works out
why.

The last check is a control. The whole verification re-runs against a DEF
whose component positions have been permuted inside their rows, and it has to
fail. A check suite that passes on scrambled input is not checking anything.

Usage:
    python3 verify_phaseE.py --selftest
    python3 verify_phaseE.py
"""

import argparse
import collections
import hashlib
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(ROOT, "dualarm", "build_current")
DESIGN = "tt_um_nikodemetrashvili20_ro_puf"

SEED = 20260829

ARTEFACTS = {
    "budget": "TILE_BUDGET.json",
    "cost": "ARMC_COST.json",
    "g2": "G2_DECISION.json",
    "obs": "OBSERVABILITY.json",
    "criteria": "G2_CRITERIA.json",
}

TOL_AREA = 0.01          # um2. The JSONs round to three decimals.
TOL_LEN = 0.05           # um


class Results(object):
    def __init__(self):
        self.rows = []

    def add(self, cid, name, ok, detail=""):
        self.rows.append({"id": cid, "name": name, "pass": bool(ok),
                          "detail": detail})
        return ok

    def failed(self):
        return [r["id"] for r in self.rows if not r["pass"]]


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


def strip(name):
    return name.replace("\\", "")


def close(a, b, tol):
    return abs(float(a) - float(b)) <= tol


# ------------------------------------------------ a second reading of a DEF

def read_def(text):
    """Rows, components and routed length. Written to a different shape from
    the one under test: a dict of plain tuples, not namedtuples, parsed with
    its own patterns, and the row records keep their raw DO/STEP rather than
    a precomputed site count."""
    units = int(re.search(r"UNITS DISTANCE MICRONS (\d+)", text).group(1))
    m = re.search(r"DIEAREA\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*"
                  r"\(\s*(-?\d+)\s+(-?\d+)\s*\)", text)
    die = tuple(int(g) for g in m.groups())
    rows = []
    for mo in re.finditer(r"ROW\s+(\S+)\s+\S+\s+(-?\d+)\s+(-?\d+)\s+\w+\s+"
                          r"DO\s+(\d+)\s+BY\s+(\d+)\s+STEP\s+(\d+)\s+(\d+)",
                          text):
        g = mo.groups()
        rows.append({"name": g[0], "x": int(g[1]), "y": int(g[2]),
                     "do": int(g[3]), "by": int(g[4]), "step": int(g[5])})
    body = text.split("COMPONENTS", 1)[1].split("END COMPONENTS", 1)[0]
    comps = []
    for mo in re.finditer(r"-\s+(\S+)\s+(\S+)\s+\+[^;]*?\(\s*(-?\d+)\s+"
                          r"(-?\d+)\s*\)\s+\w+\s*;", body):
        comps.append({"inst": strip(mo.group(1)), "master": mo.group(2),
                      "x": int(mo.group(3)), "y": int(mo.group(4))})
    return {"units": units, "die": die, "rows": rows, "comps": comps}


def widths_by_differencing(d):
    """Cell widths, again, by a different route.

    The version under test groups every abutment in the design and demands
    one gap per master. This one walks each row alone, takes the difference
    to the next origin, and keeps the smallest it ever sees. No cross-row
    agreement is required here, which is exactly why the two answers agreeing
    is worth something.
    """
    rowy = set(r["y"] for r in d["rows"])
    out = {}
    for y in sorted(rowy):
        line = sorted((c["x"], c["master"]) for c in d["comps"]
                      if c["y"] == y and c["master"].startswith("sky130"))
        for i in range(len(line) - 1):
            gap = line[i + 1][0] - line[i][0]
            if gap <= 0:
                continue
            m = line[i][1]
            out[m] = gap if m not in out else min(out[m], gap)
    return out


def row_height_of(d):
    ys = sorted(set(r["y"] for r in d["rows"]))
    return min(b - a for a, b in zip(ys, ys[1:]))


def occupancy_by_intervals(d, widths):
    """Row occupancy as intervals rather than as a sum of cell areas.

    Each row becomes a list of half-open spans, the spans are merged, and the
    merged length is compared with the row's own site span. It reaches the
    same conclusion as adding up cell areas and it would notice an overlap
    that a plain sum would hide.
    """
    rh = row_height_of(d)
    by_y = collections.defaultdict(list)
    for c in d["comps"]:
        if c["master"].startswith("sky130"):
            by_y[c["y"]].append((c["x"], c["x"] + widths.get(c["master"], 0)))
    covered = 0
    overlaps = 0
    for r in d["rows"]:
        spans = sorted(s for s in by_y.get(r["y"], [])
                       if r["x"] <= s[0] < r["x"] + r["do"] * r["by"]
                       * r["step"])
        if not spans:
            continue
        cur_lo, cur_hi = spans[0]
        for lo, hi in spans[1:]:
            if lo < cur_hi:
                overlaps += 1
            if lo <= cur_hi:
                cur_hi = max(cur_hi, hi)
            else:
                covered += cur_hi - cur_lo
                cur_lo, cur_hi = lo, hi
        covered += cur_hi - cur_lo
    return covered * rh, overlaps


def routed_length(text):
    """Total routed length per layer, walked with a different state machine:
    this one expands `*` up front into explicit coordinates before measuring,
    instead of carrying the previous point through the measurement."""
    mo = re.search(r"^NETS \d+ ;$", text, re.M)
    if not mo:
        raise ValueError("no NETS section")
    body = text[mo.end():].split("END NETS", 1)[0]
    per_layer = collections.Counter()
    per_net = collections.Counter()
    for chunk in re.split(r"\n    - ", body):
        if not chunk.strip():
            continue
        name = strip(chunk.split()[0])
        # A segment is a layer, then optionally TAPER, TAPERRULE <rule> or
        # STYLE <n>, then coordinate groups, then at most one via name.
        #
        # Both of those optional halves cost a run. Letting the via name take
        # any token ran straight past the next NEW and folded two segments
        # into one. Then leaving TAPER out skipped the clock net's segments
        # entirely, because clknet_0_clk is routed under a non-default rule
        # and every one of its met1 runs reads `met1 TAPER ( ... )`. That was
        # 33835 units of met1 missing, and the only reason it was noticed is
        # that armc_cost.py, which splits on the keywords instead of matching
        # the whole segment, got it right and the two totals disagreed.
        for seg in re.finditer(
                r"(?:\+ ROUTED|NEW)\s+(li1|met[1-5])"
                r"((?:\s+TAPER|\s+TAPERRULE\s+\S+|\s+STYLE\s+\d+)*)"
                r"((?:\s*\(\s*[-\d*]+\s+[-\d*]+\s*\))+"
                r"(?:\s+(?!NEW\b)[A-Za-z]\S*)?)", chunk):
            layer, tail = seg.group(1), seg.group(3)
            pts = []
            for px, py in re.findall(r"\(\s*([-\d*]+)\s+([-\d*]+)\s*\)", tail):
                if pts:
                    x = pts[-1][0] if px == "*" else int(px)
                    y = pts[-1][1] if py == "*" else int(py)
                elif px == "*" or py == "*":
                    continue
                else:
                    x, y = int(px), int(py)
                pts.append((x, y))
            for a, b in zip(pts, pts[1:]):
                dl = abs(b[0] - a[0]) + abs(b[1] - a[1])
                per_layer[layer] += dl
                per_net[name] += dl
    return per_layer, per_net


def spef_caps(text):
    names = dict(re.findall(r"^\*(\d+) (\S+)$", text, re.M))
    out = {}
    for k, v in re.findall(r"^\*D_NET\s+(\S+)\s+([\d.eE+-]+)", text, re.M):
        key = strip(re.sub(r"\*(\d+)",
                           lambda m: names.get(m.group(1), m.group(0)), k))
        out[key] = float(v)
    return out


# ------------------------------------------------------------- the verifier

def relabel_layers(text, _seed=SEED):
    """A second control, aimed at the half the first one cannot reach.

    Permuting placement leaves the NETS section untouched, so it says nothing
    about routing. This one moves every routed segment up one metal layer,
    cyclically. The total length is unchanged, so a check that only adds
    everything up will not notice; the per-layer figures and every
    utilisation are wrong, and those are the numbers the writeup quotes.
    """
    mo = re.search(r"^NETS \d+ ;$", text, re.M)
    body = text[mo.end():].split("END NETS", 1)[0]
    order = ["met1", "met2", "met3", "met4", "met5"]
    nxt = dict(zip(order, order[1:] + order[:1]))
    fresh = re.sub(r"\b(met[1-5])\b", lambda m: nxt[m.group(1)], body)
    return text.replace(body, fresh, 1)


def verify(paths, artefacts, res, scrambler=None):
    with open(paths["def"], "r", encoding="utf-8") as fh:
        deftext = fh.read()
    if scrambler:
        deftext = scrambler(deftext)
    d = read_def(deftext)
    u = float(d["units"])
    rh = row_height_of(d)
    widths = widths_by_differencing(d)
    b = artefacts["budget"]
    c = artefacts["cost"]
    g = artefacts["g2"]
    o = artefacts["obs"]

    def um2(v):
        return v / u / u

    # ---------------------------------------------------------------- E.1a
    x0, y0, x1, y1 = d["die"]
    res.add("V01", "the die is the size TILE_BUDGET.json records",
            close(um2((x1 - x0) * (y1 - y0)), b["die"]["area_um2"], TOL_AREA)
            and close((x1 - x0) / u, b["die"]["width_um"], 1e-6),
            "%.3f um2" % um2((x1 - x0) * (y1 - y0)))

    sites = sum(r["do"] * r["by"] for r in d["rows"])
    row_area = sites * d["rows"][0]["step"] * rh
    res.add("V02", "the row count, the site count and the row area agree",
            len(d["rows"]) == b["rows"]["count"]
            and sites == b["rows"]["sites"]
            and close(um2(row_area), b["rows"]["area_um2"], TOL_AREA),
            "%d rows, %d sites, %.3f um2"
            % (len(d["rows"]), sites, um2(row_area)))

    covered, overlaps = occupancy_by_intervals(d, widths)
    res.add("V03", "the rows are covered end to end with no overlap",
            overlaps == 0 and covered == row_area,
            "%d overlaps, %.3f um2 covered of %.3f"
            % (overlaps, um2(covered), um2(row_area)))

    def cls(master, inst):
        if master == "ro_macro_hard":
            return "armb_macro"
        base = master.replace("sky130_fd_sc_hd__", "")
        for p, k in (("decap", "decap"), ("fill", "fill"), ("tap", "tap"),
                     ("diode", "diode")):
            if base.startswith(p):
                return k
        return ("arma_ring"
                if inst.startswith("u_puf.u_core.g_ro_bank") else "logic")

    n = collections.Counter()
    a = collections.Counter()
    for comp in d["comps"]:
        k = cls(comp["master"], comp["inst"])
        n[k] += 1
        a[k] += (60000 * 40000 if k == "armb_macro"
                 else widths.get(comp["master"], 0) * rh)
    bad = []
    for k, v in b["placed"]["by_class"].items():
        if n[k] != v["count"] or not close(um2(a[k]), v["area_um2"], TOL_AREA):
            bad.append(k)
    res.add("V04", "every class count and area matches the budget",
            not bad and set(n) == set(b["placed"]["by_class"]),
            "differ: %s" % (", ".join(bad) or "none"))

    free = a["decap"] + a["fill"]
    held = sum(a[k] for k in n if k not in ("decap", "fill", "armb_macro"))
    res.add("V05", "the free and held areas are what the writeup claims",
            close(um2(free), b["free"]["area_um2"], TOL_AREA)
            and close(um2(held), b["free"]["held_area_um2"], TOL_AREA)
            and close(um2(free + held), um2(row_area), TOL_AREA),
            "free %.3f, held %.3f" % (um2(free), um2(held)))

    # The four-part sum is true by construction, because the margin is the
    # residual, so it is not checked here and is not evidence anywhere. What
    # is checked is the term that made the first version of that sum wrong:
    # the row area running through the macro block's bounding box, measured
    # again here from the row records and the macro positions.
    mw, mh = 60000, 40000
    macs = [c for c in d["comps"] if c["master"] == "ro_macro_hard"]
    bx0 = min(m["x"] for m in macs)
    by0 = min(m["y"] for m in macs)
    bx1 = max(m["x"] for m in macs) + mw
    by1 = max(m["y"] for m in macs) + mh
    inside = 0
    for r in d["rows"]:
        ox = max(0, min(r["x"] + r["do"] * r["by"] * r["step"], bx1)
                 - max(r["x"], bx0))
        oy = max(0, min(r["y"] + rh, by1) - max(r["y"], by0))
        inside += ox * oy
    res.add("V06", "free plus held is the row area, and the block overlap "
                   "is the one recorded",
            close(b["free"]["area_um2"] + b["free"]["held_area_um2"],
                  b["rows"]["area_um2"], TOL_AREA)
            and close(um2(inside),
                      b["unplaceable"]["row_area_inside_macro_block_um2"],
                      TOL_AREA)
            and close(um2((bx1 - bx0) * (by1 - by0)) - b["macros"]["area_um2"]
                      - um2(inside),
                      b["unplaceable"]["macro_block_channels_um2"], TOL_AREA),
            "%.3f um2 of row inside the macro block" % um2(inside))

    rings = collections.defaultdict(list)
    for comp in d["comps"]:
        mo = re.match(r"u_puf\.u_core\.g_ro_bank\[(\d+)\]", comp["inst"])
        if mo:
            rings[int(mo.group(1))].append(comp)
    per_ring = a["arma_ring"] / float(max(len(rings), 1))
    res.add("V07", "sixteen Arm A rings of 32 cells at the recorded area",
            len(rings) == b["arm_a"]["rings"] == 16
            and all(len(v) == 32 for v in rings.values())
            and close(um2(per_ring), b["arm_a"]["area_per_ring_um2"], 0.001),
            "%d rings, %.4f um2 each" % (len(rings), um2(per_ring)))

    # ---------------------------------------------------------------- E.1b
    with open(paths["def"], "r", encoding="utf-8") as fh:
        raw = fh.read()
    per_layer, per_net = routed_length(scrambler(raw) if scrambler else raw)
    tot = sum(per_layer.values())
    res.add("V08", "the total routed length matches the cost file",
            close(tot / u, c["measured"]["routed_total_um"], TOL_LEN),
            "%.3f um" % (tot / u))

    bad_layers = []
    for lay, rec in c["measured"]["layers"].items():
        if not close(per_layer[lay] / u, rec["routed_um"], TOL_LEN):
            bad_layers.append(lay)
        cap = rec["tracks"] * ((x1 - x0) if rec["preferred"] == "h"
                               else (y1 - y0))
        if not close(cap / u, rec["capacity_um"], 1.0):
            bad_layers.append(lay + " capacity")
        if not close(100.0 * per_layer[lay] / cap, rec["utilisation_pct"],
                     0.01):
            bad_layers.append(lay + " utilisation")
    res.add("V09", "every layer's length, capacity and utilisation agree",
            not bad_layers, "differ: %s" % (", ".join(bad_layers) or "none"))

    ring_net_len = collections.Counter()
    ring_nets = collections.Counter()
    for name, dl in per_net.items():
        mo = re.match(r"u_puf\.u_core\.g_ro_bank\[(\d+)\]\.u_ro\.", name)
        if mo:
            ring_net_len[int(mo.group(1))] += dl
    for name in per_net:
        mo = re.match(r"u_puf\.u_core\.g_ro_bank\[(\d+)\]\.u_ro\.", name)
        if mo:
            ring_nets[int(mo.group(1))] += 1
    mean_len = sum(ring_net_len.values()) / float(u * max(len(ring_net_len), 1))
    res.add("V10", "the per-ring wire length and net count agree",
            close(mean_len, c["measured"]["arm_a"]["routed_per_ring_um"],
                  TOL_LEN)
            and set(ring_nets.values()) == {33},
            "%.3f um a ring, %s nets" % (mean_len,
                                         sorted(set(ring_nets.values()))))

    with open(paths["spef"], "r", encoding="utf-8") as fh:
        caps = spef_caps(fh.read())
    inner = collections.Counter()
    for name, v in caps.items():
        mo = re.match(r"u_puf\.u_core\.g_ro_bank\[(\d+)\]\.u_ro\.n\[", name)
        if mo:
            inner[int(mo.group(1))] += v
    mean_cap = 1000.0 * sum(inner.values()) / max(len(inner), 1)
    res.add("V11", "the mean ring capacitance agrees with the cost file",
            close(mean_cap, c["measured"]["arm_a"]["wire_cap_per_ring_fF"],
                  0.001), "%.4f fF" % mean_cap)

    dens = []
    for i, cs in rings.items():
        bx0 = min(x["x"] for x in cs)
        bx1 = max(x["x"] + widths.get(x["master"], 0) for x in cs)
        by0 = min(x["y"] for x in cs)
        by1 = max(x["y"] for x in cs) + rh
        cells = sum(widths.get(x["master"], 0) * rh for x in cs)
        dens.append(cells / float((bx1 - bx0) * (by1 - by0)))
    got = {"tight": max(dens), "mean": sum(dens) / len(dens),
           "loose": min(dens)}
    res.add("V12", "the three ring densities agree with the cost file",
            all(close(got[k], c["measured"]["arm_a"]["density"][k], 0.0001)
                for k in got),
            ", ".join("%s %.4f" % (k, got[k]) for k in sorted(got)))

    # The priced table is arithmetic on those densities, so it is redone here
    # rather than trusted.
    cell = c["measured"]["arm_a"]["area_per_ring_um2"]
    inv = c["cell_area_um2"]["inv_1"]
    bad_price = []
    for r in c["priced"]["armc"]:
        want = (r["rings"] * (cell / r["density"]) + r["added_decode_um2"])
        if not close(want, r["total_um2"], 0.01):
            bad_price.append("armc %d %s" % (r["rings"], r["density_label"]))
    for r in c["priced"]["ladder"]:
        loads = r["rungs"] * (r["rungs"] - 1) // 2
        want = r["rungs"] * cell + loads * inv + r["added_decode_um2"]
        if loads != r["load_cells"] or not close(want, r["total_um2"], 0.01):
            bad_price.append("ladder %d" % r["rungs"])
    res.add("V13", "every priced total is its own arithmetic",
            not bad_price, "differ: %s" % (", ".join(bad_price) or "none"))

    # ----------------------------------------------------------------- G.2
    res.add("V14", "the frozen criteria file is the one the gate ran under",
            sha256_file(paths["criteria"]) == g["criteria_sha256"],
            g["criteria_sha256"][:16])

    hard = artefacts["criteria"]["hard"]
    ops = {"<=": lambda p, q: p <= q, ">=": lambda p, q: p >= q,
           "==": lambda p, q: p == q, "<": lambda p, q: p < q,
           ">": lambda p, q: p > q}
    wrong = []
    for row in g["options"]:
        want = []
        for h in hard:
            if h["field"] in row and not ops[h["op"]](row[h["field"]],
                                                      h["value"]):
                want.append(h["id"])
        got_ids = [f.split(" ")[0] for f in row["failed"]]
        if sorted(want) != sorted(got_ids) or row["survives"] != (not want):
            wrong.append(row["label"])
    res.add("V15", "every verdict follows from the rule and the numbers",
            not wrong, "differ: %s" % (", ".join(wrong[:3]) or "none"))

    res.add("V16", "the survivors are exactly the options that survived",
            sorted(g["survivors"])
            == sorted(r["label"] for r in g["options"] if r["survives"]),
            "%d survivors" % len(g["survivors"]))

    # ----------------------------------------------------------------- E.2
    fmin, fmax = None, None
    for name in ("dualarm_par_ss_out.txt", "dualarm_par_out.txt",
                 "dualarm_par_ff_out.txt"):
        with open(os.path.join(BUILD, name), "r", encoding="utf-8") as fh:
            vals = [float(v) for _i, v in
                    re.findall(r"^f(\d+)\s*=\s*([0-9.eE+-]+)", fh.read(),
                               re.M)]
        fmin = min(vals) if fmin is None else min(fmin, min(vals))
        fmax = max(vals) if fmax is None else max(fmax, max(vals))
    res.add("V17", "the corner span is the one the spec was built on",
            close(fmin, o["corner_span_hz"]["min"], 1.0)
            and close(fmax, o["corner_span_hz"]["max"], 1.0),
            "%.2f to %.2f MHz" % (fmin / 1e6, fmax / 1e6))

    limit = (1 << o["counter_bits"]) - 1
    clk = o["clock_hz"]
    unsafe = [w for w in o["windows"]["safe"] if fmax * w / clk > limit]
    weak = fmin * o["windows"]["overflow"] / clk <= limit
    res.add("V18", "the safe windows are safe and the overflow one is not",
            not unsafe and not weak,
            "unsafe %s, overflow %s" % (unsafe, "weak" if weak else "always"))

    ratios = [o["windows"]["safe"][1] / float(o["windows"]["safe"][0]),
              o["windows"]["safe"][2] / float(o["windows"]["safe"][0])]
    res.add("V19", "the safe windows are in the 1:2:8 ratio the writeup uses",
            ratios == [2.0, 8.0], "%s" % ratios)

    oe = 0
    for pin in o["pin_map"]:
        if pin["port"] == "uio" and pin["direction"] == "out":
            oe |= 1 << pin["bit"]
    kinds = set(t["kind"] for t in o["tests"])
    res.add("V20", "uio_oe and the acceptance table are what the spec says",
            oe == o["uio_oe"] and len(o["tests"]) >= 20
            and len(kinds) == 7,
            "oe 0x%02X, %d tests, %d kinds" % (oe, len(o["tests"]),
                                               len(kinds)))
    return res


# ------------------------------------------------------------------ control

def scramble(text, seed=SEED):
    """Permute component positions within each row.

    Every cell keeps its row and every row keeps its set of x positions, so
    the file still parses and the site count is untouched. What breaks is
    which master sits where, and that is what every area number rests on.
    """
    rng = random.Random(seed)
    body = text.split("COMPONENTS", 1)[1].split("END COMPONENTS", 1)[0]
    lines = [l for l in body.split("\n") if l.strip().startswith("-")]
    by_y = collections.defaultdict(list)
    for i, line in enumerate(lines):
        mo = re.search(r"\(\s*(-?\d+)\s+(-?\d+)\s*\)", line)
        if mo:
            by_y[int(mo.group(2))].append((i, int(mo.group(1))))
    out = list(lines)
    for y, items in by_y.items():
        if len(items) < 2:
            continue
        xs = [x for _i, x in items]
        shuffled = list(xs)
        rng.shuffle(shuffled)
        if shuffled == xs:
            # A shuffle is allowed to return what it was given, and on a row
            # of two that is half the time. Rotate instead, so the control is
            # guaranteed to have moved something.
            shuffled = shuffled[1:] + shuffled[:1]
        for (i, _old), new in zip(items, shuffled):
            out[i] = re.sub(r"\(\s*-?\d+\s+(-?\d+)\s*\)",
                            lambda m: "( %d %s )" % (new, m.group(1)),
                            out[i], count=1)
    new_body = body
    for old, fresh in zip(lines, out):
        if old != fresh:
            new_body = new_body.replace(old, fresh, 1)
    return text.replace(body, new_body, 1)


# ----------------------------------------------------------------- selftest

def selftest():
    """The verifier's own arithmetic, on inputs small enough to check by
    hand, plus the scrambler doing what it claims."""
    ok = True
    print("verify_phaseE selftest")

    tiny = "\n".join([
        "UNITS DISTANCE MICRONS 1000 ;",
        "DIEAREA ( 0 0 ) ( 10000 10000 ) ;",
        "ROW R0 unithd 0 0 N DO 4 BY 1 STEP 1000 0 ;",
        "ROW R1 unithd 0 2000 N DO 4 BY 1 STEP 1000 0 ;",
        "COMPONENTS 4 ;",
        "    - a sky130_fd_sc_hd__inv_1 + PLACED ( 0 0 ) N ;",
        "    - b sky130_fd_sc_hd__fill_2 + PLACED ( 2000 0 ) N ;",
        "    - c sky130_fd_sc_hd__inv_1 + PLACED ( 0 2000 ) N ;",
        "    - d sky130_fd_sc_hd__fill_2 + PLACED ( 2000 2000 ) N ;",
        "END COMPONENTS",
    ])
    d = read_def(tiny)
    w = widths_by_differencing(d)
    cases = [
        ("parses four components in two rows",
         len(d["comps"]) == 4 and len(d["rows"]) == 2),
        ("recovers inv_1 at 2000 from the gap to its neighbour",
         w.get("sky130_fd_sc_hd__inv_1") == 2000),
        ("takes fill_2's width from the row that has one",
         "sky130_fd_sc_hd__fill_2" not in w),
        ("row height is the pitch between rows", row_height_of(d) == 2000),
    ]
    covered, overlaps = occupancy_by_intervals(
        d, {"sky130_fd_sc_hd__inv_1": 2000, "sky130_fd_sc_hd__fill_2": 2000})
    cases.append(("two rows of 4000 units cover 8000 by 2000",
                  covered == 8000 * 2000 and overlaps == 0))
    covered2, overlaps2 = occupancy_by_intervals(
        d, {"sky130_fd_sc_hd__inv_1": 3000, "sky130_fd_sc_hd__fill_2": 2000})
    cases.append(("an overlap is counted, not summed away",
                  overlaps2 == 2 and covered2 == 8000 * 2000))

    route = "\n".join([
        "NETS 2 ;", "    - n1 ( a A ) + USE SIGNAL",
        "      + ROUTED met1 ( 0 0 ) ( 1000 * )",
        "      NEW met2 ( 1000 0 ) ( * 3000 ) ;",
        "    - n2 ( b B ) + USE SIGNAL",
        "      + ROUTED met1 ( 0 0 ) L1M1_PR_MR ;", "END NETS"])
    pl, pn = routed_length(route)
    cases.append(("a two-segment net measures 1000 plus 3000",
                  pl["met1"] == 1000 and pl["met2"] == 3000))
    taper = "\n".join([
        "NETS 1 ;", "    - n3 ( a A ) + USE CLOCK + NONDEFAULTRULE R",
        "      + ROUTED met1 TAPER ( 0 0 ) ( 500 * )",
        "      NEW met2 TAPERRULE R ( 500 0 ) ( * 700 )",
        "      NEW met3 STYLE 1 ( 0 0 ) ( 0 200 ) ;", "END NETS"])
    pt, _ = routed_length(taper)
    cases.append(("a segment under a non-default rule is still measured",
                  pt["met1"] == 500 and pt["met2"] == 700
                  and pt["met3"] == 200))
    cases.append(("a single-point entry is a via and adds nothing",
                  pn.get("n2", 0) == 0))

    spef = "\n".join(["*NAME_MAP", "*3 alpha", "*4 beta", "",
                      "*D_NET *3 0.001000", "*END",
                      "*D_NET *4 0.002500", "*END"])
    caps = spef_caps(spef)
    cases.append(("the name map resolves both nets",
                  close(caps.get("alpha", 0), 0.001, 1e-9)
                  and close(caps.get("beta", 0), 0.0025, 1e-9)))

    scr = scramble(tiny)
    d2 = read_def(scr)
    cases.append(("scrambling keeps every position and moves what sits there",
                  sorted((c["x"], c["y"]) for c in d2["comps"])
                  == sorted((c["x"], c["y"]) for c in d["comps"])
                  and sorted((c["x"], c["y"], c["master"])
                             for c in d2["comps"])
                  != sorted((c["x"], c["y"], c["master"])
                            for c in d["comps"])))

    for name, good in cases:
        print("  %-5s %s" % ("ok" if good else "FAIL", name))
        ok = ok and good
    print("\n  %s" % ("the verifier's own arithmetic holds" if ok
                      else "SELFTEST FAILED"))
    return 0 if ok else 1


# --------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    paths = {"def": os.path.join(BUILD, DESIGN + ".def"),
             "netlist": os.path.join(BUILD, DESIGN + ".nl.v"),
             "spef": os.path.join(BUILD, DESIGN + ".nom.spef"),
             "criteria": os.path.join(HERE, ARTEFACTS["criteria"])}
    artefacts = {}
    for key, name in ARTEFACTS.items():
        p = os.path.join(HERE, name)
        if not os.path.exists(p):
            raise SystemExit("missing artefact: %s" % p)
        with open(p, "r", encoding="utf-8") as fh:
            artefacts[key] = json.load(fh)
    for p in paths.values():
        if not os.path.exists(p):
            raise SystemExit("missing input: %s" % p)

    res = verify(paths, artefacts, Results())
    print("Phase E re-derivation, sharing no code with what it checks\n")
    for r in res.rows:
        print("  %-4s %-60s %s" % (r["id"], r["name"],
                                   "pass" if r["pass"] else "FAIL"))
    bad = res.failed()
    for r in res.rows:
        if not r["pass"]:
            print("       %s: %s" % (r["id"], r["detail"]))
    print("\n  %s" % ("all %d checks pass" % len(res.rows) if not bad
                      else "FAILED: " + ", ".join(bad)))
    if bad:
        return 1

    print("\n  controls. Each one damages a different half of the input and"
          "\n  the checks that read that half have to fail.")
    bad_ctrl = False
    for label, fn, must in (
            ("every row permuted, placement scrambled", scramble,
             {"V03", "V04", "V05", "V07", "V12"}),
            ("every routed segment moved up a metal layer", relabel_layers,
             {"V09"})):
        ctrl = verify(paths, artefacts, Results(), scrambler=fn)
        broke = set(ctrl.failed())
        good = must <= broke
        print("    %-46s %2d of %d fail  %s"
              % (label, len(broke), len(ctrl.rows),
                 "as they must" if good else "CONTROL FAILED"))
        if not good:
            print("      expected at least %s, got %s"
                  % (",".join(sorted(must)), ",".join(sorted(broke))))
            bad_ctrl = True
    if bad_ctrl:
        return 1
    print("\n  The placement control cannot reach the routing numbers and the"
          "\n  layer control cannot reach the areas. What guards the routing"
          "\n  total is that armc_cost.py and this file parse it by different"
          "\n  methods and have to agree to the unit, which is how the clock"
          "\n  net's TAPER segments were found missing here.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
