#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""What switches beside each ring while it runs, in the release build.

Only one ring runs at a time, so another ring is never the problem. What
does switch during a run is the 50 MHz clock tree and the registers that
change on its edges: the window timer and the two stages that sample the
counter. A ring close to a multiple of the clock with one of those beside
it can be pulled toward that multiple, and every extraction in this
directory grounds the neighbours of a ring, so no simulation has had them
toggling. The 17 September review called the clock's pull the same for all
48 rings. It is not, it depends on what runs next to each one, and this
says what does.

Two readings of run 83 (dualarm/build_armc), each with its own parser:

  routed  Arms A and C. The SPEF's coupling capacitance from each ring's
          31 loop nets to every other net, wire only (PIN_CAP NONE), in
          four groups: the clock tree (clk and every clknet_ net), the
          clocked nets (wtimer, cnt_meta and cnt_sync, which change on
          clock edges while a ring runs), other rings, and the rest. A
          ring's coupling between its own nets is left out.
  macros  Arm B. Inside the hardened macro the flow saw a box and the SPEF
          has nothing, so this reads the DEF: the length of every top-level
          wire over the ring area, which is the box the macro's LEF
          obstructs on li1, in the same groups. Only li1, met1, a strip of
          met2 and a small piece of met3 are obstructed there, so the
          router was free to cross the rest, and it did.

The lengths are not capacitance. Nothing here extracts the macro's ring
together with the wires above it.

Checks, each with a planted fault in --selftest that trips it and nothing
else:

  K01  32 routed rings of 31 loop nets, every coupling node on a net
  K02  each loop net's caps add up to the total on its D_NET line
  K03  the clock tree's own D_NETs carry the same coupling to each ring
  K04  16 macros in the DEF, each where config.json puts it, all N
  K05  no top-level li1 or met1 shape over a ring area, as the LEF says

K03 is the clock's side of the coupling read again: the SPEF lists every
coupling capacitor under both of its nets, so the two sums have to agree.

Run:
  python3 clock_neighbours.py [--csv OUT]   (exit 1 if a check fails)
  python3 clock_neighbours.py --selftest
"""

import argparse
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
REL = os.path.join(PROJ, "dualarm", "build_armc")
TOP = "tt_um_nikodemetrashvili20_ro_puf"
SPEF = os.path.join(REL, TOP + ".nom.spef")
DEF = os.path.join(REL, TOP + ".def")
LEF = os.path.join(PROJ, "src", "ro_macro_hard.lef")
CONFIG = os.path.join(PROJ, "src", "config.json")

LOOP_NETS = 31
RING_RE = re.compile(r"^u_puf\.u_core\.(g_ro_bank|g_armc)\[(\d+)\]\."
                     r"(u_ro|u_roc)\.n\[\d+\]$")
CLOCKED_RE = re.compile(r"^u_puf\.u_core\.(wtimer|cnt_meta|cnt_sync)\[\d+\]$")
SAME_TOTAL_PF = 1e-6     # K02, a thousandth of a fF
SAME_SIDES_PF = 1e-9     # K03, the same numbers summed in another order


def unescape(name):
    return name.replace("\\", "")


def group(name):
    """clock, clocked, ring or other, for an unescaped net name."""
    if name == "clk" or name.startswith("clknet_"):
        return "clock"
    if CLOCKED_RE.match(name):
        return "clocked"
    if RING_RE.match(name):
        return "ring"
    return "other"


def short(name):
    """A clocked net without the core's prefix, which all of them carry."""
    return name.replace("u_puf.u_core.", "")


def ring_of(name):
    m = RING_RE.match(name)
    if not m:
        return None
    return ("A" if m.group(1) == "g_ro_bank" else "C") + "%02d" % int(
        m.group(2))


# ---------------------------------------------------------------- SPEF
def read_spef(text):
    """{net id: {"name", "total", "gnd", "cpl": [(a, b, pF)]}} and the
    owner of every instance-pin and port node, from the *CONN lists."""
    names, nets, pin_net = {}, {}, {}
    cur, sec = None, None
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            if sec == "map":
                sec = None
            continue
        if s == "*NAME_MAP":
            sec = "map"
            continue
        if sec == "map":
            m = re.match(r"^(\*\d+) (\S+)$", s)
            if m:
                names[m.group(1)] = unescape(m.group(2))
                continue
            sec = None
        if s.startswith("*D_NET "):
            f = s.split()
            cur = f[1]
            nets[cur] = {"name": names.get(cur, cur), "total": float(f[2]),
                         "gnd": 0.0, "cpl": []}
            sec = None
            continue
        if cur is None:
            continue
        if s in ("*CONN", "*CAP", "*RES"):
            sec = s[1:].lower()
            continue
        if s == "*END":
            cur, sec = None, None
            continue
        f = s.split()
        if sec == "conn" and f[0] in ("*I", "*P"):
            pin_net[f[1]] = cur
        elif sec == "cap" and len(f) == 3:
            nets[cur]["gnd"] += float(f[2])
        elif sec == "cap" and len(f) == 4:
            nets[cur]["cpl"].append((f[1], f[2], float(f[3])))
    return nets, pin_net


def owner(node, nets, pin_net):
    """The net a node belongs to, or None."""
    if node in pin_net:
        return pin_net[node]
    base = node.split(":")[0]
    return base if base in nets and ":" in node else None


def routed(nets, pin_net):
    """Per ring: loop nets, total pF, and coupling pF by group, read from
    the ring's own nets, with the clock and clocked nets it couples to; and
    the clock to each ring read from the clock's side, and unresolved
    nodes."""
    rings = {}
    unresolved = []
    for nid, n in nets.items():
        r = ring_of(n["name"])
        if not r:
            continue
        e = rings.setdefault(r, {"nets": 0, "total": 0.0, "clock": 0.0,
                                 "clocked": 0.0, "rings": 0.0, "other": 0.0,
                                 "named": set(), "sums": []})
        e["nets"] += 1
        e["total"] += n["total"]
        e["sums"].append((n["name"], n["total"], n["gnd"]
                          + sum(v for _, _, v in n["cpl"])))
        for a, b, v in n["cpl"]:
            oa, ob = owner(a, nets, pin_net), owner(b, nets, pin_net)
            if oa == nid:
                other = ob
            elif ob == nid:
                other = oa
            else:
                other = None
            if other is None:
                unresolved.append((n["name"], a, b))
                continue
            name = nets[other]["name"]
            g = group(name)
            if g == "ring":
                if ring_of(name) == r:
                    continue
                e["rings"] += v
            else:
                e[g] += v
                if g in ("clock", "clocked") and v > 0:
                    e["named"].add(short(name))
    from_clock = {}
    for nid, n in nets.items():
        if group(n["name"]) != "clock":
            continue
        for a, b, v in n["cpl"]:
            oa, ob = owner(a, nets, pin_net), owner(b, nets, pin_net)
            other = ob if oa == nid else oa if ob == nid else None
            if other is None:
                continue
            r = ring_of(nets[other]["name"])
            if r:
                from_clock[r] = from_clock.get(r, 0.0) + v
    return rings, from_clock, unresolved


# ---------------------------------------------------------- DEF and LEF
def ring_box(lef_text):
    """The li1 obstruction box of ro_macro_hard, um, and the macro size."""
    body = re.search(r"MACRO ro_macro_hard\b(.*?)END ro_macro_hard",
                     lef_text, re.S).group(1)
    size = tuple(float(v) for v in re.search(
        r"SIZE ([\d.]+) BY ([\d.]+) ;", body).groups())
    obs = re.search(r"\bOBS\b(.*?)\bEND\b", body, re.S).group(1)
    m = re.search(r"LAYER li1 ;\s+RECT ([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) ;",
                  obs)
    return tuple(float(v) for v in m.groups()), size


def read_def(text):
    """(dbu, {macro: (x, y, orient)}, segments, points). Segments are
    (net, layer, x0, y0, x1, y1) in dbu; points are (net, layer, x, y) for
    every li1 or met1 shape a route statement puts down at one place: a
    patch, or a via whose bottom is li1 or met1."""
    dbu = int(re.search(r"UNITS DISTANCE MICRONS (\d+)", text).group(1))
    comps = {}
    for m in re.finditer(r"- (u_rob\d+) ro_macro_hard \+ (?:FIXED|PLACED) "
                         r"\( (-?\d+) (-?\d+) \) (\w+)", text):
        comps[m.group(1)] = (int(m.group(2)), int(m.group(3)), m.group(4))
    sec = text[text.index("\nNETS "):text.index("\nEND NETS")]
    segs, points = [], []
    for nm in re.finditer(r"\n\s*- (\S+)(.*?);\s*(?=\n\s*-|\Z)", sec, re.S):
        net = unescape(nm.group(1))
        for st in re.finditer(r"(?:ROUTED|NEW) (li1|met\d) \( (\d+) (\d+)"
                              r"(?: \d+)? \)(?: \( (\S+) (\S+)(?: \d+)? \))?"
                              r"(?: (RECT|\w+))?", nm.group(2)):
            layer, x0, y0, x1, y1, tail = st.groups()
            x0, y0 = int(x0), int(y0)
            if x1 is not None:
                x1 = x0 if x1 == "*" else int(x1)
                y1 = y0 if y1 == "*" else int(y1)
                segs.append((net, layer, x0, y0, x1, y1))
            elif tail == "RECT" and layer in ("li1", "met1"):
                points.append((net, layer, x0, y0))
            elif tail and re.match(r"(L1M1|M1M2)", tail):
                points.append((net, "li1" if tail.startswith("L1M1")
                               else "met1", x0, y0))
    return dbu, comps, segs, points


def overlap(a0, a1, b0, b1):
    lo, hi = max(min(a0, a1), b0), min(max(a0, a1), b1)
    return max(0.0, hi - lo)


def macros(dbu, comps, segs, points, box):
    """Per macro: um of wire over the ring area by group, the clock and
    clocked nets among them, and the li1 or met1 shapes found there."""
    out = {}
    for inst, (x, y, orient) in comps.items():
        bx0, by0 = x + box[0] * dbu, y + box[1] * dbu
        bx1, by1 = x + box[2] * dbu, y + box[3] * dbu
        e = {"clock": 0.0, "clocked": 0.0, "other": 0.0, "named": set(),
             "low": []}
        for net, layer, x0, y0, x1, y1 in segs:
            if y0 == y1 and by0 <= y0 <= by1:
                length = overlap(x0, x1, bx0, bx1)
            elif x0 == x1 and bx0 <= x0 <= bx1:
                length = overlap(y0, y1, by0, by1)
            else:
                length = 0.0
            if length <= 0:
                continue
            if layer in ("li1", "met1"):
                e["low"].append((net, layer))
                continue
            g = group(net)
            g = "other" if g == "ring" else g
            e[g] += length / dbu
            if g in ("clock", "clocked"):
                e["named"].add(short(net))
        for net, layer, px, py in points:
            if bx0 <= px <= bx1 and by0 <= py <= by1:
                e["low"].append((net, layer))
        out["B%02d" % int(inst[5:])] = e
    return out


# --------------------------------------------------------------- checks
def run_checks(spef_text, def_text, lef_text, config):
    nets, pin_net = read_spef(spef_text)
    rings, from_clock, unresolved = routed(nets, pin_net)
    box, size = ring_box(lef_text)
    dbu, comps, segs, points = read_def(def_text)
    arm_b = macros(dbu, comps, segs, points, box)
    res = []

    def add(cid, what, ok, detail):
        res.append((cid, what, bool(ok), detail))

    counts = sorted(set(e["nets"] for e in rings.values()))
    add("K01", "32 routed rings of %d loop nets, every coupling node on a"
        " net" % LOOP_NETS,
        len(rings) == 32 and counts == [LOOP_NETS] and not unresolved,
        "%d rings, loop nets per ring %s, %d unresolved"
        % (len(rings), counts, len(unresolved)))
    worst = max((abs(t - s), name) for e in rings.values()
                for name, t, s in e["sums"])
    add("K02", "each loop net's caps add up to the total on its D_NET line",
        worst[0] <= SAME_TOTAL_PF,
        "worst %.2g pF on %s" % worst)
    gap = max([(abs(rings[r]["clock"] - from_clock.get(r, 0.0)), r)
               for r in rings] + [(0.0, "-")])
    add("K03", "the clock tree's own D_NETs carry the same coupling to each"
        " ring", gap[0] <= SAME_SIDES_PF
        and set(r for r in from_clock if from_clock[r] > 0)
        <= set(r for r in rings if rings[r]["clock"] > 0),
        "largest difference %.2g pF, %s" % gap)
    want = config["MACROS"]["ro_macro_hard"]["instances"]
    placed = {k: (x / float(dbu), y / float(dbu), o)
              for k, (x, y, o) in comps.items()}
    wrong = sorted(k for k in set(want) | set(placed)
                   if k not in placed or k not in want
                   or abs(placed[k][0] - want[k]["location"][0]) > 1e-6
                   or abs(placed[k][1] - want[k]["location"][1]) > 1e-6
                   or placed[k][2] != want[k]["orientation"]
                   or placed[k][2] != "N")
    add("K04", "16 macros in the DEF, each where config.json puts it, all N",
        len(placed) == 16 and not wrong,
        "%d placed, %s" % (len(placed), ", ".join(wrong) or "none off"))
    low = sorted((m, n, l) for m, e in arm_b.items() for n, l in e["low"])
    inside = (0 <= box[0] < box[2] <= size[0]
              and 0 <= box[1] < box[3] <= size[1])
    add("K05", "no top-level li1 or met1 shape over a ring area, as the LEF"
        " says", not low and inside,
        "%d found, ring area %.3f to %.3f by %.3f to %.3f um in a %g by %g"
        " macro" % (len(low), box[0], box[2], box[1], box[3], size[0],
                    size[1]))
    return res, rings, arm_b


def table_rows(rings, arm_b):
    rows = []
    for r in sorted(rings):
        e = rings[r]
        rows.append([r, "routed", "%.3f" % (e["total"] * 1e3),
                     "%.3f" % (e["clock"] * 1e3),
                     "%.3f" % (e["clocked"] * 1e3),
                     "%.3f" % (e["rings"] * 1e3),
                     "%.3f" % (e["other"] * 1e3), "", "", "",
                     " ".join(sorted(e["named"]))])
    for m in sorted(arm_b):
        e = arm_b[m]
        rows.append([m, "macro", "", "", "", "", "", "%.1f" % e["clock"],
                     "%.1f" % e["clocked"], "%.1f" % e["other"],
                     " ".join(sorted(e["named"]))])
    return rows


HEADER = ["ring", "kind", "loop_fF", "clock_fF", "clocked_fF", "rings_fF",
          "other_fF", "clock_um", "clocked_um", "other_um", "nets"]


def write_csv(rows, path):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(HEADER)
        w.writerows(rows)


def report(res, rings, arm_b):
    print("routed rings, coupling in fF (wire only), largest clock first")
    print("  ring   loop   clock  clocked  rings   other   clock share")
    for r in sorted(rings, key=lambda k: (-rings[k]["clock"], k)):
        e = rings[r]
        if e["clock"] <= 0 and e["clocked"] <= 0:
            continue
        print("  %s  %6.2f  %6.3f  %6.3f  %6.3f  %6.2f   %5.2f%%  %s"
              % (r, e["total"] * 1e3, e["clock"] * 1e3, e["clocked"] * 1e3,
                 e["rings"] * 1e3, e["other"] * 1e3,
                 100.0 * e["clock"] / e["total"],
                 " ".join(sorted(e["named"]))))
    quiet = [r for r in sorted(rings)
             if rings[r]["clock"] <= 0 and rings[r]["clocked"] <= 0]
    print("  no clock or clocked coupling: %s" % " ".join(quiet))
    print("\nArm B macros, top-level wire over the ring area in um")
    print("  macro  clock  clocked  other")
    for m in sorted(arm_b):
        e = arm_b[m]
        print("  %s   %5.1f  %6.1f  %6.1f  %s"
              % (m, e["clock"], e["clocked"], e["other"],
                 " ".join(sorted(e["named"]))))
    with_clock = [r for r in rings if rings[r]["clock"] > 0]
    print("\nclock coupling on %d of %d routed rings, %d of them in Arm C,"
          " clocked nets on %d; clock wire over %d of %d macros, clocked"
          " nets over %d"
          % (len(with_clock), len(rings),
             sum(1 for r in with_clock if r[0] == "C"),
             sum(1 for e in rings.values() if e["clocked"] > 0),
             sum(1 for e in arm_b.values() if e["clock"] > 0), len(arm_b),
             sum(1 for e in arm_b.values() if e["clocked"] > 0)))
    print()
    for cid, what, ok, detail in res:
        print("  %s  %-64s %s" % (cid, what, "pass" if ok else "FAIL"))
        print("       %s" % detail)
    bad = [r for r in res if not r[2]]
    print("\n%s" % ("FAIL: %d of %d checks" % (len(bad), len(res)) if bad
                    else "all %d checks pass" % len(res)))
    return 1 if bad else 0


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ------------------------------------------------------------- selftest
def selftest(spef, deff, lef, config):
    """Each fault changes one input and must trip its own check only."""
    nets, pin_net = read_spef(spef)
    # A coupling line in a clock net's section whose other end is a ring.
    target = None
    for nid, n in nets.items():
        if group(n["name"]) != "clock":
            continue
        for a, b, v in n["cpl"]:
            other = owner(b, nets, pin_net)
            if v > 0 and other and ring_of(nets[other]["name"]):
                target = (nid, a, b, v)
                break
        if target:
            break
    nid, a, b, v = target
    head = "*D_NET %s " % nid
    start = spef.index(head)
    end = spef.index("*END", start)
    line = re.search(r"\n(\d+) %s %s (\S+)\n" % (re.escape(a), re.escape(b)),
                     spef[start:end])
    old_line = line.group(0)
    clock_side = (spef[:start] + spef[start:end].replace(
        old_line, old_line.replace(line.group(2), "%g" % (v * 2))) +
        spef[end:])
    loop = re.search(r"\n(\*\d+) u_puf\\\.u_core\\\.g_armc\\\[8\\\]\\\."
                     r"u_roc\\\.n\\\[3\\\]\n", spef)
    renamed = spef.replace(loop.group(0), loop.group(0).replace(
        "\\.n\\[3\\]", "\\.m\\[3\\]"))
    dnet = re.search(r"\n\*D_NET %s (\S+)\n" % re.escape(loop.group(1)),
                     spef)
    retotal = spef.replace(dnet.group(0), dnet.group(0).replace(
        dnet.group(1), "%g" % (float(dnet.group(1)) * 1.01)))
    m = re.search(r"- u_rob5 ro_macro_hard \+ FIXED \( (\d+) (\d+) \) N ;",
                  deff)
    moved = deff.replace(m.group(0), m.group(0).replace(
        "( %s %s )" % m.groups(), "( %d %s )" % (int(m.group(1)) + 1000,
                                                 m.group(2))))
    flipped = deff.replace(m.group(0), m.group(0)[:-3] + "FS ;")
    # The DEF escapes the brackets of a name and not its dots.
    x0, y0 = int(m.group(1)), int(m.group(2))
    entry = deff.index("- u_puf.u_core.wtimer\\[0\\] (")
    at = deff.index("\n      NEW ", entry) + 1
    low_wire = (deff[:at] + "      NEW met1 ( %d %d ) ( %d * )\n"
                % (x0 + 10000, y0 + 20000, x0 + 30000) + deff[at:])
    faults = [
        ("a ring net renamed in the SPEF's name map", "K01",
         (renamed, deff, lef, config)),
        ("a loop net's total one percent high", "K02",
         (retotal, deff, lef, config)),
        ("the clock's copy of a coupling to a ring doubled", "K03",
         (clock_side, deff, lef, config)),
        ("B05 one um off its place", "K04", (spef, moved, lef, config)),
        ("B05 flipped", "K04", (spef, flipped, lef, config)),
        ("a met1 wire of wtimer[0] across B05", "K05",
         (spef, low_wire, lef, config)),
    ]
    base, _, _ = run_checks(spef, deff, lef, config)
    bad = 0
    if not all(ok for _, _, ok, _ in base):
        print("FAIL  the unchanged inputs do not pass")
        bad += 1
    for what, cid, args in faults:
        res, _, _ = run_checks(*args)
        tripped = [c for c, _, ok, _ in res if not ok]
        good = tripped == [cid]
        bad += 0 if good else 1
        print("%s  %s: %s" % ("ok  " if good else "FAIL", cid, what)
              + ("" if good else ", tripped %s" % (tripped or "nothing")))
    print("\n%s" % ("all %d faults isolated" % len(faults) if not bad
                    else "FAIL: %d of %d" % (bad, len(faults))))
    return 1 if bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--spef", default=SPEF)
    ap.add_argument("--def", dest="deff", default=DEF)
    ap.add_argument("--lef", default=LEF)
    ap.add_argument("--config", default=CONFIG)
    ap.add_argument("--csv", help="write one row per ring here")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    spef, deff, lef = read(a.spef), read(a.deff), read(a.lef)
    config = json.loads(read(a.config))
    if a.selftest:
        return selftest(spef, deff, lef, config)
    res, rings, arm_b = run_checks(spef, deff, lef, config)
    if a.csv:
        write_csv(table_rows(rings, arm_b), a.csv)
    return report(res, rings, arm_b)


if __name__ == "__main__":
    sys.exit(main())
