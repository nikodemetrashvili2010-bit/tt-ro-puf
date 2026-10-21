#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""magic's extraction against the SPEF the predictions were made from.

Two comparisons on the layout with no fill:
  1. ring loads: magic's loop load per ring against the SPEF's
     (ring_cap_fF of rc_validation_3arm.csv and _armc.csv), as Pearson
     and Spearman correlations and the offset between them
  2. ordinary routed nets: magic's total against the SPEF's *D_NET total,
     for every net magic names after a cell pin that is not a ring net,
     so the two extractors are compared where neither sees anything new

Usage: python3 crosscheck.py base.spice loads_base.csv RELEASE.def
           RELEASE.nom.spef rc_validation_3arm.csv rc_validation_armc.csv
"""
import csv
import re
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from ring_loads import read  # noqa: E402


def pearson(x, y):
    mx, my = statistics.mean(x), statistics.mean(y)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    return sxy / (sum((a - mx) ** 2 for a in x) ** 0.5
                  * sum((b - my) ** 2 for b in y) ** 0.5)


def ranks(v):
    """Ranks from 0, tied values sharing the mean of their places."""
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    k = 0
    while k < len(order):
        j = k
        while j + 1 < len(order) and v[order[j + 1]] == v[order[k]]:
            j += 1
        for m in range(k, j + 1):
            r[order[m]] = (k + j) / 2.0
        k = j + 1
    return r


def main(spice, loads_csv, defpath, spefpath, a_csv, c_csv):
    mag = {r["ring"]: float(r["grounded_fF"])
           for r in csv.DictReader(open(loads_csv))}
    print("1. ring loads, magic against the SPEF")
    for arm, path in (("A", a_csv), ("C", c_csv)):
        rows = list(csv.DictReader(open(path)))
        sp = [float(r["ring_cap_fF"]) for r in rows]
        mg = [mag["%s%02d" % (arm, int(r["ro"]))] for r in rows]
        off = [m - s for m, s in zip(mg, sp)]
        print("   Arm %s: Pearson %.3f, Spearman %.3f, magic above SPEF by "
              "%.2f to %.2f fF" % (arm, pearson(mg, sp),
                                   pearson(ranks(mg), ranks(sp)),
                                   min(off), max(off)))

    text = open(defpath).read().split("\nNETS")[1].split("END NETS")[0]
    pin2net = {}
    for blk in text.split(";\n"):
        blk = blk.strip()
        if not blk.startswith("-"):
            continue
        name = blk.split()[1]
        for inst, pin in re.findall(r"\(\s*(\S+)\s+(\S+)\s*\)",
                                    blk.split("+")[0]):
            pin2net[(inst, pin)] = name
    spef = open(spefpath).read()
    names = {}
    for m in re.finditer(r"^\*(\d+)\s+(\S+)$",
                         spef.split("*NAME_MAP")[1].split("*PORTS")[0],
                         re.M):
        names["*" + m.group(1)] = m.group(2)
    unit = re.search(r"\*C_UNIT\s+([\d.]+)\s+(\w+)", spef)
    scale = float(unit.group(1)) * {"FF": 1.0, "PF": 1e3}[
        unit.group(2).upper()]
    dnet = {}
    for m in re.finditer(r"^\*D_NET\s+(\S+)\s+([\d.eE+-]+)", spef, re.M):
        dnet[names.get(m.group(1), m.group(1))] = float(m.group(2)) * scale
    total = defaultdict(float)
    for a, b, v in read(spice):
        total[a] += v
        total[b] += v
    pairs = []
    for node, c in total.items():
        if "/" not in node or "#" in node or node.startswith("u_rob"):
            continue
        inst, pin = node.rsplit("/", 1)
        net = pin2net.get((inst, pin))
        if net is None or ".u_ro." in net or ".u_roc." in net:
            continue
        if net in dnet:
            pairs.append((net, c, dnet[net]))
    big = [m / s for _, m, s in pairs if s > 5]
    q = statistics.quantiles(big, n=4)
    print("2. routed nets: %d compared; %d with a SPEF total above 5 fF,"
          " magic over SPEF median %.3f, quartiles %.3f and %.3f"
          % (len(pairs), len(big), statistics.median(big), q[0], q[2]))


if __name__ == "__main__":
    main(*sys.argv[1:7])
