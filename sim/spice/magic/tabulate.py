#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""magic's 48 ring frequencies, as the one table the amendment reads.

chip/PREREG_AMENDMENT_2.json scores a pair only when the SPEF and magic
both put it over the abstention line with the same sign. Its magic side is
magic_rings.csv, and this writes that table from the deck logs that ran:
decks_base, the layout as submitted, and decks_fill0, the same layout with
open_pdks fill at the first grid position. The gate writes it again and
diffs it, so the table cannot drift away from the logs.

A log counts when ngspice printed f and every f it printed agrees. A folder
counts when it holds the 48 rings, A00 to A15, B00 to B15 and C00 to C15,
each with its deck and its log, and nothing else that ends in .spice or
.log. Anything short of that stops the run, because a table quietly
missing one ring would still read like a table.

    python3 tabulate.py --selftest
    python3 tabulate.py --csv OUT.csv
"""

import argparse
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
COLUMNS = (("magic_MHz", "decks_base"), ("fill0_MHz", "decks_fill0"))
RINGS = ["%s%02d" % (arm, i) for arm in "ABC" for i in range(16)]
# ngspice prints "f = 4.730740e+08". Its progress lines end in a bare
# carriage return, so those are turned into line ends before reading.
F_LINE = re.compile(r"^f = ([0-9]\.[0-9]+e[+-][0-9]+)[ \t]*$", re.M)


def ring_f(log_path):
    """f in Hz from one ngspice log. Stops if there is none, or two."""
    with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read().replace("\r\n", "\n").replace("\r", "\n")
    vals = set(F_LINE.findall(text))
    if not vals:
        raise SystemExit("%s: ngspice printed no f" % log_path)
    if len(vals) != 1:
        raise SystemExit("%s: f printed two ways, %s"
                         % (log_path, " and ".join(sorted(vals))))
    return float(vals.pop())


def folder(path):
    """ring -> f in Hz, for the 48 rings and no other deck."""
    names = os.listdir(path)
    decks = {n[:-len(".spice")] for n in names if n.endswith(".spice")}
    logs = {n[:-len(".log")] for n in names if n.endswith(".log")}
    want = set(RINGS)
    if decks != want or logs != want:
        odd = sorted((decks ^ want) | (logs ^ want))
        raise SystemExit("%s: not the 48 rings with a deck and a log each,"
                         " look at %s" % (path, ", ".join(odd)))
    return {r: ring_f(os.path.join(path, r + ".log")) for r in RINGS}


def table(root):
    cols = [(name, folder(os.path.join(root, sub))) for name, sub in COLUMNS]
    lines = ["ring," + ",".join(name for name, _ in cols)]
    for r in RINGS:
        lines.append(r + "," + ",".join("%.4f" % (f[r] / 1e6)
                                        for _, f in cols))
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ selftest

def fake_log(f_text, noise=True):
    head = "Circuit: * ring\n"
    if noise:
        head += "Reference value :  1.0e-09\rReference value :  2.0e-09\r"
    return head + "\ntp = 2.1e-08\nf = %s\nNote: done\n" % f_text


def fake_tree(tmp, mutate=None):
    for _, sub in COLUMNS:
        d = os.path.join(tmp, sub)
        os.makedirs(d)
        for i, r in enumerate(RINGS):
            with open(os.path.join(d, r + ".spice"), "w") as fh:
                fh.write("* %s\n.end\n" % r)
            with open(os.path.join(d, r + ".log"), "w", newline="") as fh:
                fh.write(fake_log("4.%06de+08" % (730740 + i)))
    if mutate:
        mutate(tmp)


def selftest():
    bad = []

    def check(cid, what, ok, detail=""):
        print("  %-5s %-4s %s%s" % ("ok" if ok else "FAIL", cid, what,
                                    "  (%s)" % detail if detail else ""))
        if not ok:
            bad.append(cid)

    def refused(mutate):
        tmp = tempfile.mkdtemp()
        try:
            fake_tree(tmp, mutate)
            table(tmp)
            return False, "accepted"
        except SystemExit as e:
            return True, str(e).replace(tmp, "TMP")
        finally:
            shutil.rmtree(tmp)

    print("tabulate selftest")
    tmp = tempfile.mkdtemp()
    try:
        fake_tree(tmp)
        t = table(tmp).splitlines()
    finally:
        shutil.rmtree(tmp)
    check("T01", "a clean pair of folders gives 48 rows under the header",
          len(t) == 49 and t[0] == "ring,magic_MHz,fill0_MHz",
          "%d lines" % len(t))
    check("T02", "4.730740e+08 is written 473.0740, read past bare CRs",
          t[1] == "A00,473.0740,473.0740", t[1])
    check("T03", "the rows run A00 to C15 in order",
          [l.split(",")[0] for l in t[1:]] == RINGS)

    def no_f(tmp):
        with open(os.path.join(tmp, "decks_base", "B07.log"), "w") as fh:
            fh.write("Error: no convergence\n")
    ok, why = refused(no_f)
    check("T04", "a log with no f stops it", ok, why)

    def two_f(tmp):
        with open(os.path.join(tmp, "decks_fill0", "C03.log"), "a") as fh:
            fh.write("f = 4.000000e+08\n")
    ok, why = refused(two_f)
    check("T05", "a log that prints f two ways stops it", ok, why)

    def lost(tmp):
        os.remove(os.path.join(tmp, "decks_base", "A11.log"))
    ok, why = refused(lost)
    check("T06", "a ring without its log stops it", ok, why)

    def extra(tmp):
        for ext in (".spice", ".log"):
            shutil.copy(os.path.join(tmp, "decks_fill0", "A15" + ext),
                        os.path.join(tmp, "decks_fill0", "A16" + ext))
    ok, why = refused(extra)
    check("T07", "a deck that is not one of the 48 stops it", ok, why)

    print("\n  %s" % ("all 7 checks pass" if not bad
                      else "FAILED: " + ", ".join(bad)))
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--csv", metavar="OUT")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.csv:
        text = table(HERE)
        with open(a.csv, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        print("wrote %s, %d rings" % (a.csv, len(text.splitlines()) - 1))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
