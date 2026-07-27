#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Check that an archived build folder holds one flow run, not a mixture.

Every physical number I quote comes out of a folder like dualarm/build_current:
a DEF, a gate-level netlist, a nominal SPEF, and a metrics file that reports the
sign-off checks. Nothing in my copying routine forces those four to come from
the same run, and I got caught by that. After the counter-gating change I
re-hardened, copied the new GDS, DEF, SPEF and netlist over, and left the old
metrics.json sitting there. The file that says DRC is clean was describing a
build with 123 fewer instances than the one I was about to tape out.

File timestamps cannot settle it, because copying rewrites them. So the files
have to agree with each other instead:

    design name     DEF, SPEF and the netlist top module
    instances       DEF COMPONENTS against the netlist, count and names
    metrics         the instance count and die box the metrics file recorded
    macros          sixteen ro_macro_hard, seen from both sides
    parasitics      every SPEF net is a net the DEF actually has

A bundle that passes is one run. That is all this proves: it says nothing about
whether the run was good, which is what the metrics and the other verifiers are
for.

Usage:
    python3 verify_build_bundle.py [--dir dualarm/build_current]
    python3 verify_build_bundle.py --def A.def --netlist A.nl.v --spef A.spef
"""

import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
DEFAULT_DIR = os.path.join(PROJ, "dualarm", "build_current")

NOT_A_CELL = {
    "module", "endmodule", "input", "output", "inout", "wire", "reg",
    "assign", "parameter", "localparam", "specify", "always", "initial",
    "generate", "endgenerate", "function", "task",
}
INST_RE = re.compile(r"^\s*([A-Za-z_][\w$]*)\s+(\\\S+|[A-Za-z_][\w$\[\]]*)\s*\(")
MODULE_RE = re.compile(r"^\s*module\s+([\w$]+)")


def plain(name):
    """DEF and SPEF escape dots and brackets; the netlist escapes the whole name."""
    return name.replace("\\", "").strip()


def read_def(path):
    design, diearea, comps, nets = None, None, {}, set()
    section = None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if section is None:
                if s.startswith("DESIGN "):
                    design = s.split()[1]
                elif s.startswith("DIEAREA"):
                    nums = re.findall(r"-?\d+", s)
                    if len(nums) >= 4:
                        diearea = tuple(int(v) for v in nums[:4])
            if s.startswith("COMPONENTS "):
                section = "comp"
                continue
            if s.startswith("NETS "):
                section = "nets"
                continue
            if s.startswith("END COMPONENTS") or s.startswith("END NETS"):
                section = None
                continue
            if s.startswith("SPECIALNETS ") or s.startswith("PINS "):
                section = None
                continue
            if section == "comp" and s.startswith("- "):
                parts = s.split()
                comps[plain(parts[1])] = parts[2]
            elif section == "nets" and s.startswith("- "):
                nets.add(plain(s.split()[1]))
    return {"design": design, "diearea": diearea, "components": comps, "nets": nets}


def read_netlist(path):
    top, insts = None, {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if top is None:
                m = MODULE_RE.match(line)
                if m:
                    top = m.group(1)
                    continue
            m = INST_RE.match(line)
            if not m:
                continue
            cell, inst = m.group(1), m.group(2).strip()
            if cell in NOT_A_CELL or inst in ("", "("):
                continue
            insts[plain(inst)] = cell
    return {"top": top, "instances": insts}


def read_spef(path):
    design, names, nets = None, {}, set()
    in_map = False
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if s.startswith("*DESIGN "):
                design = s.split('"')[1] if '"' in s else s.split()[1]
            elif s.startswith("*NAME_MAP"):
                in_map = True
            elif in_map and s.startswith("*") and not s[1].isdigit():
                in_map = False
            elif in_map and s.startswith("*"):
                bits = s.split(None, 1)
                if len(bits) == 2:
                    names[bits[0]] = plain(bits[1])
            elif s.startswith("*D_NET"):
                token = s.split()[1]
                nets.add(names.get(token, plain(token)))
    return {"design": design, "nets": nets, "map_size": len(names)}


def pick(pattern, folder, given):
    if given:
        return given
    hits = sorted(glob.glob(os.path.join(folder, pattern)))
    return hits[0] if hits else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default=DEFAULT_DIR)
    ap.add_argument("--def", dest="def_path")
    ap.add_argument("--netlist")
    ap.add_argument("--spef")
    ap.add_argument("--metrics")
    ap.add_argument("--macro-cell", default="ro_macro_hard")
    ap.add_argument("--macro-count", type=int, default=16)
    args = ap.parse_args(argv)

    def_path = pick("*.def", args.dir, args.def_path)
    nl_path = pick("*.nl.v", args.dir, args.netlist)
    spef_path = pick("*.spef", args.dir, args.spef)
    met_path = pick("metrics.json", args.dir, args.metrics)

    missing = [n for n, p in (("DEF", def_path), ("netlist", nl_path),
                              ("SPEF", spef_path), ("metrics", met_path))
               if not p or not os.path.exists(p)]
    if missing:
        print("error: %s not found in %s" % (", ".join(missing), args.dir),
              file=sys.stderr)
        return 2

    print("bundle: %s" % os.path.relpath(args.dir, PROJ))
    dsn = read_def(def_path)
    nl = read_netlist(nl_path)
    spef = read_spef(spef_path)
    with open(met_path, encoding="utf-8") as fh:
        met = json.load(fh)

    results = []

    def check(ok, label, detail):
        results.append(bool(ok))
        print("[%s] %s: %s" % ("ok  " if ok else "FAIL", label, detail))

    names = {dsn["design"], nl["top"], spef["design"]}
    check(len(names) == 1, "design name",
          "%s in all three" % dsn["design"] if len(names) == 1
          else "DEF %s, netlist %s, SPEF %s" % (dsn["design"], nl["top"], spef["design"]))

    n_def, n_nl = len(dsn["components"]), len(nl["instances"])
    check(n_def == n_nl, "instance count, DEF against netlist",
          "%d each" % n_def if n_def == n_nl else "DEF %d, netlist %d" % (n_def, n_nl))

    n_met = met.get("design__instance__count")
    check(n_met == n_def, "instance count, metrics against DEF",
          "metrics %s, DEF %d%s" % (n_met, n_def,
          "" if n_met == n_def else "  <- the metrics file is from another run"))

    only_def = set(dsn["components"]) - set(nl["instances"])
    only_nl = set(nl["instances"]) - set(dsn["components"])
    sample = sorted(only_def | only_nl)[:3]
    check(not only_def and not only_nl, "instance names",
          "every name matches" if not sample
          else "%d only in DEF, %d only in netlist, e.g. %s"
               % (len(only_def), len(only_nl), ", ".join(sample)))

    retyped = [k for k, v in nl["instances"].items()
               if k in dsn["components"] and dsn["components"][k] != v]
    check(not retyped, "cell types",
          "no instance changed cell" if not retyped
          else "%d disagree, e.g. %s" % (len(retyped), retyped[0]))

    # DEF holds the die box in database units, metrics in microns.
    box = met.get("design__die__bbox", "")
    want = [v / 1000.0 for v in dsn["diearea"]] if dsn["diearea"] else None
    try:
        got = [float(v) for v in box.split()]
    except ValueError:
        got = None
    check(want is not None and got == want, "die area",
          "DEF %s, metrics %s" % (want, box or "absent"))

    m_def = sum(1 for c in dsn["components"].values() if c == args.macro_cell)
    m_nl = sum(1 for c in nl["instances"].values() if c == args.macro_cell)
    check(m_def == m_nl == args.macro_count, "macro instances",
          "%d in DEF, %d in netlist" % (m_def, m_nl))

    orphan = spef["nets"] - dsn["nets"]
    covered = len(spef["nets"] & dsn["nets"])
    check(not orphan, "SPEF nets exist in the DEF",
          "%d of %d DEF nets carry parasitics" % (covered, len(dsn["nets"]))
          if not orphan else "%d SPEF nets are not in this DEF, e.g. %s"
          % (len(orphan), sorted(orphan)[0]))

    passed = sum(1 for r in results if r)
    print("== SUMMARY == %d/%d agree" % (passed, len(results)))
    if passed != len(results):
        print("The files in this folder are not one run. Recopy the whole set "
              "from runs/<tag>/final/ before quoting anything from it.")
        return 1
    print("One run. Reported by its metrics: %s instances, DRC %s, LVS %s, "
          "antenna %s." % (n_met, met.get("magic__drc_error__count", "?"),
                           met.get("design__lvs_error__count", "?"),
                           met.get("route__antenna_violation__count", "?")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
