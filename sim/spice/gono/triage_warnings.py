#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0

"""Per-net triage of the warning classes the dual-arm flow reports.

SIGNOFF.md carries six warning classes from `dualarm/build_current/` and says
each one needs triage against the design before I order silicon. Counting them
is what metrics.json already does. This script names them instead: it reads the
DEF, the SPEF and the gate netlist, re-derives each count from the layout
itself, and fails if a number it derives disagrees with the number the flow
recorded.

The point is the disagreement. metrics.json says nine disconnected pins; that
is a number I can neither act on nor defend. This says the nine are ui_in[7]
and uio_in[7:0], every one an unused chip input, and that no internal net is
among them. The second statement can be wrong, which is why it is worth making.

Nothing here needs ngspice, a PDK or a network. Point it at an archived build
bundle and it re-derives from the four files in that folder.

Usage
    python3 triage_warnings.py --build ../../../dualarm/build_current
    python3 triage_warnings.py --build ... --all-builds ../../.. --json out.json
    python3 triage_warnings.py --selftest
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

# Output pins of every cell this design instantiates. Anything not in here is
# read as an input. The set is closed over the 48 cell types in the shipped
# netlist plus the Arm B macro, and check_cell_coverage() below refuses to run
# on a netlist carrying a cell whose pins this does not cover.
OUT_PINS = {"X", "Y", "Q", "Q_N", "HI", "LO", "COUT", "SUM", "out"}

# Cells with no signal pins at all: they are placed, they draw no timing arc.
PHYSICAL_ONLY = ("__decap_", "__fill_", "__tapvpwrvgnd_", "__tap_")

# Every input pin name that appears across the five archived netlists, plus the
# rest of the sky130 hd sequential and scan pins so a re-harden that picks a
# different flop does not trip the guard for no reason. DIODE belongs here: an
# antenna diode is a sink by construction.
KNOWN_INPUT_PINS = {
    "A", "A0", "A1", "A1_N", "A2", "A2_N", "A3", "A4", "A_N",
    "B", "B1", "B1_N", "B2", "B_N",
    "C", "C1", "C_N", "D", "D1", "D_N",
    "S", "S0", "S1", "CLK", "CLK_N", "RESET_B", "SET_B",
    "SCD", "SCE", "TE", "TE_B", "GATE", "GATE_N", "SLEEP", "NOTIFIER",
    "DIODE", "en",
}

# LibreLane's sky130 default, which src/config.json does not override.
MAX_FANOUT = 10


class TriageError(Exception):
    pass


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------

def unescape(name: str) -> str:
    r"""DEF writes bus nets as u_core.active_sel\[0\]; SPEF and Verilog do not.

    Every cross-file join in this script goes through here. Getting it wrong
    does not raise, it silently makes two files look like they share no nets,
    which is why the joins are asserted against a floor further down.
    """
    return name.replace("\\", "").strip()


def read_def_nets(path: str) -> tuple[dict[str, list[tuple[str, str]]], list[str]]:
    """Return {net: [(instance, pin), ...]} plus the SPECIALNETS names.

    A DEF net entry carries its connections first and its routing after the
    first `+` option. Routing segments are also parenthesised coordinate pairs,
    so a regex over the whole entry reads them as connections and inflates
    every fanout. Splitting on the option marker first is the whole trick.
    """
    txt = open(path).read()
    m = re.search(r"^NETS\s+\d+\s*;(.*?)^END NETS", txt, re.S | re.M)
    if not m:
        raise TriageError(f"{path}: no NETS section")

    nets: dict[str, list[tuple[str, str]]] = {}
    for block in re.split(r"\n\s*-\s+", m.group(1))[1:]:
        name = unescape(block.split(None, 1)[0])
        head = re.split(r"\n\s*\+\s", block)[0]
        conns = re.findall(r"\(\s*([^\s()]+)\s+([^\s()]+)\s*\)", head)
        nets[name] = conns

    special: list[str] = []
    sm = re.search(r"^SPECIALNETS.*?^END SPECIALNETS", txt, re.S | re.M)
    if sm:
        special = [unescape(s) for s in re.findall(r"\n\s*-\s+(\S+)", sm.group(0))]

    # A routing coordinate that survived the split would show up as a
    # connection whose "instance" is all digits. There should be none.
    stray = [(n, c) for n, cs in nets.items() for c in cs if c[0].isdigit()]
    if stray:
        raise TriageError(
            f"{path}: {len(stray)} routing coordinates parsed as connections, "
            f"first {stray[0]}. The NETS option split failed.")
    return nets, special


def read_spef_caps(path: str) -> dict[str, float]:
    """Return {net: total capacitance in fF}.

    C_UNIT is asserted rather than assumed. A deck that reads PF as FF is off
    by a thousand and still looks like a plausible number, which is the kind of
    error that survives review.
    """
    txt = open(path).read()
    unit = re.search(r"^\*C_UNIT\s+([0-9.]+)\s+(\w+)", txt, re.M)
    if not unit:
        raise TriageError(f"{path}: no *C_UNIT line")
    scale = {"FF": 1.0, "PF": 1e3, "NF": 1e6}.get(unit.group(2).upper())
    if scale is None:
        raise TriageError(f"{path}: unknown C_UNIT {unit.group(2)}")
    scale *= float(unit.group(1))

    namemap = {k: unescape(v) for k, v in re.findall(r"^\*(\d+)\s+(\S+)\s*$", txt, re.M)}
    caps: dict[str, float] = {}
    for m in re.finditer(r"^\*D_NET\s+(\S+)\s+([0-9.eE+-]+)", txt, re.M):
        key = m.group(1).lstrip("*")
        caps[namemap.get(key, unescape(key))] = float(m.group(2)) * scale
    if not caps:
        raise TriageError(f"{path}: no *D_NET entries")
    return caps


def read_netlist(path: str):
    """Return (instances, drivers, assigns, ports).

    instances: [(cell, name, {pin: net})]
    drivers:   {net: (cell, instance, pin)}
    assigns:   [(lhs, rhs)]
    ports:     {port: direction}
    """
    src = re.sub(r"//[^\n]*", "", open(path).read())

    inst_re = re.compile(
        r"^\s*([A-Za-z_][A-Za-z0-9_$]*)\s+([A-Za-z_\\][^\s(]*)\s*\((.*?)\)\s*;",
        re.S | re.M)
    pin_re = re.compile(r"\.([A-Za-z0-9_$]+)\s*\(\s*([^)]*?)\s*\)")
    keywords = {"module", "input", "output", "inout", "wire", "endmodule", "assign"}

    instances = []
    drivers: dict[str, tuple[str, str, str]] = {}
    for m in inst_re.finditer(src):
        cell, name, body = m.groups()
        if cell in keywords:
            continue
        pins = {p: unescape(n) for p, n in pin_re.findall(body)}
        instances.append((cell, unescape(name), pins))
        for pin, net in pins.items():
            if pin in OUT_PINS and net:
                drivers[net] = (cell, unescape(name), pin)

    assigns = [(unescape(a), unescape(b)) for a, b in
               re.findall(r"^\s*assign\s+(\S+)\s*=\s*(\S+)\s*;", src, re.M)]

    ports: dict[str, str] = {}
    for kind in ("input", "output", "inout"):
        for m in re.finditer(rf"^\s*{kind}\s+(?:\[(\d+):(\d+)\]\s+)?(\w+)\s*;", src, re.M):
            hi, lo, nm = m.groups()
            if hi is None:
                ports[nm] = kind
            else:
                for i in range(int(lo), int(hi) + 1):
                    ports[f"{nm}[{i}]"] = kind
    return instances, drivers, assigns, ports


def check_cell_coverage(instances) -> list[tuple[str, str]]:
    """Refuse to judge a netlist carrying a pin name this script cannot classify.

    The failure this guards is a driver going unseen: a pin that is really an
    output, read as an input, makes the net it drives look undriven and
    produces a false finding shaped exactly like a real one.

    Testing it per cell type does not work. In the wokwi build the only
    clkbuf_4 in the netlist is `clkload0`, a CTS load-balancing buffer with its
    output deliberately left unconnected, so that type never exposes an output
    and a per-type rule calls it unknown. The pin name is what matters, so
    that is what gets checked. Every pin name across the five archived
    netlists is in one of the two sets below.

    An instance that omits its output is legitimate and is returned, not
    raised on: CTS leaves load buffers dangling on purpose, and a conb_1 tie
    cell connects only the polarity it is being used for.
    """
    unknown_pins: dict[str, tuple[str, str]] = {}
    dangling: list[tuple[str, str]] = []
    for cell, name, pins in instances:
        if any(tag in cell for tag in PHYSICAL_ONLY) or not pins:
            continue
        for p in pins:
            if p not in OUT_PINS and p not in KNOWN_INPUT_PINS:
                unknown_pins.setdefault(p, (cell, name))
        if not (set(pins) & OUT_PINS):
            dangling.append((cell, name))

    if unknown_pins:
        first = sorted(unknown_pins)[0]
        raise TriageError(
            f"{len(unknown_pins)} pin name(s) are neither a known output nor a "
            f"known input, first {first!r} on {unknown_pins[first]}. Classify "
            f"it before trusting any result.")
    return dangling


# ---------------------------------------------------------------------------
# the six classes
# ---------------------------------------------------------------------------

def triage(build: str) -> dict:
    def one(pattern, prefer=None):
        """Find the single file matching pattern under the build folder.

        My archived bundles are flat. A LibreLane final/ folder is not: it
        keeps views in per-format subfolders and writes one SPEF per corner
        under spef/{min,nom,max}/. Walk both shapes, then use `prefer` to pick
        the corner. Anything still ambiguous is refused rather than guessed,
        because silently reading the max-corner SPEF while the metrics describe
        nom is the kind of mismatch that produces a clean wrong answer.
        """
        hits = []
        for dirpath, dirnames, filenames in os.walk(build):
            if dirpath.count(os.sep) - build.count(os.sep) > 2:
                dirnames[:] = []
                continue
            hits += [os.path.join(dirpath, f) for f in filenames
                     if re.search(pattern, f)]
        if len(hits) > 1 and prefer:
            narrowed = [h for h in hits
                        if prefer in h.split(os.sep)]
            if narrowed:
                hits = narrowed
        if len(hits) != 1:
            raise TriageError(
                f"{build}: expected one {pattern}"
                f"{f' under {prefer}/' if prefer else ''}, found {sorted(hits)}")
        return hits[0]

    def_path = one(r"\.def$")
    spef_path = one(r"\.spef$", prefer="nom")
    nl_path = one(r"\.nl\.v$")
    metrics_path = os.path.join(build, "metrics.json")
    metrics = json.load(open(metrics_path))

    def_nets, special = read_def_nets(def_path)
    caps = read_spef_caps(spef_path)
    instances, drivers, assigns, ports = read_netlist(nl_path)
    dangling_outputs = check_cell_coverage(instances)

    # The three files must actually describe the same build. A join that
    # silently matches nothing would make every count come out clean.
    shared = set(def_nets) & set(caps)
    if len(shared) < 0.5 * len(caps):
        raise TriageError(
            f"DEF and SPEF share only {len(shared)} of {len(caps)} net names. "
            f"Name unescaping is broken or these are different builds.")

    out: dict = {"build": build, "metrics": metrics_path}

    # --- 1. disconnected pins ---------------------------------------------
    # A DEF net whose only connection is a top-level PIN reaches no instance.
    orphan_ports = sorted(n for n, c in def_nets.items()
                          if len(c) == 1 and c[0][0] == "PIN")
    out["disconnected"] = {
        "derived": len(orphan_ports),
        "recorded": metrics.get("design__disconnected_pin__count"),
        "critical_recorded": metrics.get("design__critical_disconnected_pin__count"),
        "nets": orphan_ports,
        "all_are_inputs": all(ports.get(p) == "input" for p in orphan_ports),
        "any_internal": [p for p in orphan_ports if p not in ports],
    }

    # --- 2. unannotated timing nets ---------------------------------------
    # The nets the SPEF carries no D_NET for are exactly the orphan-PIN nets
    # above. The tool's own count sits higher than that, by an offset this
    # script reports rather than explains. The first version of this section
    # did explain it, and was wrong: it charged the offset to the 16 black-box
    # macro instances, which matched on build_current and then failed on the
    # wokwi build, which has no macro at all and the same offset. Two numbers
    # agreeing once is not a mechanism.
    unannotated = sorted(set(def_nets) - set(caps))
    macro_cells = [i for i in instances
                   if not i[0].startswith("sky130_") and i[2]]
    recorded = metrics.get("timing__unannotated_net__count")
    disc = metrics.get("design__disconnected_pin__count")
    out["unannotated"] = {
        "recorded": recorded,
        "recorded_filtered": metrics.get("timing__unannotated_net_filtered__count"),
        "no_spef_dnet": len(unannotated),
        "no_spef_dnet_nets": unannotated,
        "blackbox_instances": len(macro_cells),
        "blackbox_cell": macro_cells[0][0] if macro_cells else None,
        "offset_over_disconnected": (recorded - disc)
                                    if (recorded is not None and disc is not None)
                                    else None,
    }

    # --- 3. max fanout ------------------------------------------------------
    fanout = {n: len([c for c in cs if c[0] != "PIN" and c[1] not in OUT_PINS])
              for n, cs in def_nets.items()}
    over = sorted(((v, n) for n, v in fanout.items() if v > MAX_FANOUT), reverse=True)
    at_limit = [n for n, v in fanout.items() if v == MAX_FANOUT]
    out["fanout"] = {
        "limit": MAX_FANOUT,
        "derived": len(over),
        "recorded": metrics.get("design__max_fanout_violation__count"),
        "violators": [{"net": n, "fanout": v, "driver": drivers.get(n, ("?",))[0]}
                      for v, n in over],
        "at_limit": len(at_limit),
        "histogram": dict(sorted(Counter(fanout.values()).items())),
    }

    # --- 4. floating timing nets -------------------------------------------
    # Structural check: no net in the netlist may lack a driver or a load.
    loads: dict[str, list] = defaultdict(list)
    for cell, name, pins in instances:
        for pin, net in pins.items():
            if net and pin not in OUT_PINS:
                loads[net].append((cell, name, pin))
    for lhs, rhs in assigns:
        loads[rhs].append(("assign", lhs, "rhs"))
    signal_nets = set(drivers) | set(loads)
    undriven = sorted(n for n in signal_nets
                      if n not in drivers
                      and not any(a[0] == n for a in assigns)
                      and ports.get(n) not in ("input", "inout"))
    unloaded = sorted(n for n in signal_nets
                      if not loads[n] and ports.get(n) not in ("output", "inout"))
    out["floating"] = {
        "recorded_nets": metrics.get("timing__drv__floating__nets"),
        "recorded_pins": metrics.get("timing__drv__floating__pins"),
        "special_nets": special,
        "structurally_undriven": undriven,
        "structurally_unloaded": unloaded,
        "instances_with_output_omitted": sorted(dangling_outputs),
    }

    # --- 5. max slew --------------------------------------------------------
    by_corner = {k.split("corner:")[1]: v for k, v in metrics.items()
                 if k.startswith("design__max_slew_violation__count__corner:")}
    ring_nets = {n: c for n, c in caps.items()
                 if drivers.get(n, ("",))[0] in
                 ("sky130_fd_sc_hd__inv_1", "sky130_fd_sc_hd__nand2_1")}
    heavy = sorted(caps.items(), key=lambda kv: -kv[1])[:20]
    out["slew"] = {
        "recorded": metrics.get("design__max_slew_violation__count"),
        "by_corner": dict(sorted(by_corner.items())),
        "ff_total": sum(v for k, v in by_corner.items() if "_ff_" in k),
        "ss_total": sum(v for k, v in by_corner.items() if "_ss_" in k),
        "heaviest": [{"net": n, "fF": round(c, 2),
                      "driver": drivers.get(n, ("?",))[0],
                      "fanout": fanout.get(n, 0)} for n, c in heavy],
        "ring_net_count": len(ring_nets),
        "ring_fF_min": round(min(ring_nets.values()), 3) if ring_nets else None,
        "ring_fF_max": round(max(ring_nets.values()), 3) if ring_nets else None,
        "ring_fF_mean": round(sum(ring_nets.values()) / len(ring_nets), 3)
                        if ring_nets else None,
        "heaviest_is_ring": bool(heavy) and heavy[0][0] in ring_nets,
        "nonring_fF_max": round(max((c for n, c in caps.items()
                                     if n not in ring_nets), default=0.0), 2)
                          or None,
        "heaviest_over_ring_max": round(heavy[0][1] / max(ring_nets.values()), 1)
                                  if ring_nets else None,
    }

    # --- 6. lint ------------------------------------------------------------
    out["lint"] = {
        "warnings": metrics.get("design__lint_warning__count"),
        "errors": metrics.get("design__lint_error__count"),
        "timing_constructs": metrics.get("design__lint_timing_construct__count"),
    }

    out["cells"] = dict(Counter(c for c, _, _ in instances).most_common())
    out["counts"] = {"def_nets": len(def_nets), "spef_dnets": len(caps),
                     "instances_with_pins": len([i for i in instances if i[2]])}
    return out


def verdicts(t: dict) -> list[tuple[bool, str]]:
    """Each derived number against the number the flow recorded."""
    v = []
    d, u, f, fl, s = (t["disconnected"], t["unannotated"], t["fanout"],
                      t["floating"], t["slew"])

    v.append((d["derived"] == d["recorded"],
              f"disconnected pins: derived {d['derived']}, "
              f"metrics {d['recorded']}"))
    v.append((d["all_are_inputs"] and not d["any_internal"],
              f"every disconnected pin is an unused top-level input "
              f"({len(d['nets'])} of them), no internal net among them"))
    v.append((d["critical_recorded"] == 0,
              f"critical disconnected pins recorded as {d['critical_recorded']}"))

    v.append((u["no_spef_dnet"] == d["derived"],
              f"the {u['no_spef_dnet']} nets the SPEF does not annotate are the "
              f"same nets as the disconnected pins"))
    v.append((u["recorded_filtered"] == 0,
              f"unannotated nets after the tool's own filter: "
              f"{u['recorded_filtered']} (recorded total {u['recorded']}, which "
              f"is {u['offset_over_disconnected']} above the disconnected count; "
              f"the offset is not explained here)"))

    v.append((f["derived"] == f["recorded"],
              f"max-fanout violations: derived {f['derived']}, "
              f"metrics {f['recorded']}"))
    if f["violators"]:
        w = f["violators"][0]
        v.append((w["driver"].startswith("sky130_fd_sc_hd__clkbuf"),
                  f"the violator is {w['net']} at fanout {w['fanout']} "
                  f"(limit {f['limit']}), driven by {w['driver']}"))

    v.append((not fl["structurally_undriven"] and not fl["structurally_unloaded"],
              f"no net in the netlist lacks a driver or a load "
              f"(undriven {len(fl['structurally_undriven'])}, "
              f"unloaded {len(fl['structurally_unloaded'])})"))
    v.append((len(fl["special_nets"]) == fl["recorded_nets"],
              f"floating timing nets recorded as {fl['recorded_nets']}; the DEF "
              f"carries {len(fl['special_nets'])} special nets "
              f"{fl['special_nets']}"))
    v.append((fl["recorded_pins"] == 0,
              f"floating timing pins recorded as {fl['recorded_pins']}"))

    # The corner verdicts only mean something on a build that reported per-corner
    # counts. A build with no corner keys is not a build that passed them.
    # max, min and nom are three delay views of one PVT corner, not three
    # corners, so these sum views rather than independent violations.
    if s["by_corner"]:
        ff = [k for k in s["by_corner"] if "_ff_" in k]
        ss = [k for k in s["by_corner"] if "_ss_" in k]
        v.append((s["ff_total"] == 0,
                  f"max-slew violations across all {len(ff)} fast-corner views: "
                  f"{s['ff_total']}"))
        v.append((all(s["by_corner"][k] > 0 for k in ss),
                  f"every one of the {len(ss)} slow-corner views has violations "
                  f"({', '.join(str(s['by_corner'][k]) for k in sorted(ss))}) "
                  f"while every fast-corner view has none"))
    # The claim worth testing is that the slew risk is not in the measurement
    # path. A ratio threshold would be invented, so this asks the question
    # directly: no ring net is among the heaviest in the design.
    if s["ring_fF_max"] and s["nonring_fF_max"]:
        v.append((s["ring_fF_max"] < s["nonring_fF_max"],
                  f"the heaviest ring net is lighter than the heaviest net "
                  f"outside the rings: {s['ring_fF_max']} fF across "
                  f"{s['ring_net_count']} ring nets against "
                  f"{s['nonring_fF_max']} fF"))

    v.append((t["lint"]["errors"] == 0,
              f"lint: {t['lint']['warnings']} warnings, "
              f"{t['lint']['errors']} errors, "
              f"{t['lint']['timing_constructs']} timing constructs"))
    return v


def floating_invariance(root: str) -> list[dict]:
    """The floating-net count against every archived build in the tree.

    If the number tracks design size it is a property of this design and needs
    explaining. If it is the same in a 226-instance macro and a 7000-instance
    block, it is a property of the flow.
    """
    rows = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "_github_review", "__pycache__")]
        if "metrics.json" not in filenames:
            continue
        try:
            m = json.load(open(os.path.join(dirpath, "metrics.json")))
        except (ValueError, OSError):
            continue
        disc = m.get("design__disconnected_pin__count")
        unann = m.get("timing__unannotated_net__count")
        rows.append({
            "build": os.path.relpath(dirpath, root),
            "instances": m.get("design__instance__count"),
            "floating_nets": m.get("timing__drv__floating__nets"),
            "floating_pins": m.get("timing__drv__floating__pins"),
            "disconnected": disc,
            "unannotated": unann,
            "offset": (unann - disc) if (disc is not None and unann is not None
                                         and unann) else None,
        })
    return sorted(rows, key=lambda r: (r["instances"] or 0))


# ---------------------------------------------------------------------------
# selftest
# ---------------------------------------------------------------------------

MIN_DEF = """VERSION 5.8 ;
DESIGN t ;
UNITS DISTANCE MICRONS 1000 ;
SPECIALNETS 2 ;
- VPWR ( * VPWR ) + USE POWER ;
- VGND ( * VGND ) + USE GROUND ;
END SPECIALNETS
NETS 4 ;
- n1 ( u1 Y ) ( u2 A )
  + ROUTED met1 ( 100 200 ) ( 300 200 ) ;
- n2 ( u2 X ) ( PIN out1 )
  + ROUTED met1 ( 300 200 ) ( 500 200 ) ;
- in1 ( PIN in1 ) ( u1 A ) ;
- spare ( PIN spare ) ;
END NETS
END DESIGN
"""

MIN_SPEF = """*SPEF "ieee 1481-1999"
*C_UNIT 1 PF
*NAME_MAP
*1 n1
*2 n2
*3 in1
*D_NET *1 0.000500
*END
*D_NET *2 0.001234
*END
*D_NET *3 0.000100
*END
"""

MIN_NL = """module t (in1, spare, out1);
 input in1;
 input spare;
 output out1;
 wire n1;
 wire n2;
 sky130_fd_sc_hd__inv_1 u1 (.A(in1), .Y(n1));
 sky130_fd_sc_hd__buf_1 u2 (.A(n1), .X(n2));
 assign out1 = n2;
endmodule
"""

MIN_METRICS = {
    "design__disconnected_pin__count": 1,
    "design__critical_disconnected_pin__count": 0,
    "timing__unannotated_net__count": 1,
    "timing__unannotated_net_filtered__count": 0,
    "design__max_fanout_violation__count": 0,
    "timing__drv__floating__nets": 2,
    "timing__drv__floating__pins": 0,
    "design__max_slew_violation__count": 0,
    "design__lint_warning__count": 3,
    "design__lint_error__count": 0,
    "design__lint_timing_construct__count": 0,
    "design__instance__count": 2,
}


def selftest() -> int:
    """Nine planted faults, each of which must be caught.

    An analysis that has never failed has not been tested. Case 2 is the one
    that matters most: it plants the routing-as-connection bug that inflated
    every fanout on the first pass of this script, and it has to be caught by
    the parser rather than by a number looking wrong.
    """
    import tempfile
    import shutil

    def build_dir(defs=MIN_DEF, spef=MIN_SPEF, nl=MIN_NL, metrics=None):
        d = tempfile.mkdtemp()
        open(os.path.join(d, "t.def"), "w").write(defs)
        open(os.path.join(d, "t.spef"), "w").write(spef)
        open(os.path.join(d, "t.nl.v"), "w").write(nl)
        json.dump(metrics or MIN_METRICS, open(os.path.join(d, "metrics.json"), "w"))
        return d

    cases: list[tuple[str, callable, bool]] = []

    # 1. the clean case must pass every verdict
    def clean():
        t = triage(build_dir())
        return all(ok for ok, _ in verdicts(t))
    cases.append(("clean minimal build passes all verdicts", clean, True))

    # 2. routing coordinates must not be read as connections
    def routing_leak():
        bad = MIN_DEF.replace("  + ROUTED met1 ( 100 200 ) ( 300 200 ) ;",
                              "( 100 200 ) ( 300 200 ) ;")
        try:
            triage(build_dir(defs=bad))
            return False
        except TriageError as e:
            return "routing coordinates" in str(e)
    cases.append(("routing coordinates parsed as connections is caught",
                  routing_leak, True))

    # 3. wrong capacitance unit must not pass silently
    def unit():
        # 0.001234 pF is 1.234 fF. Read as FF it would be 0.001234, read as NF
        # it would be 1234. The reported value carries two decimals.
        got = t if (t := triage(build_dir())["slew"]["heaviest"][0]["fF"]) else 0
        return abs(got - 1.23) < 0.005
    cases.append(("PF is converted to fF, 0.001234 pF reads as 1.23 fF",
                  unit, True))

    # 4. an unknown cell with no known output pin must stop the run
    def unknown_pin():
        nl = MIN_NL.replace("sky130_fd_sc_hd__buf_1 u2 (.A(n1), .X(n2));",
                            "some_new_cell u2 (.A(n1), .ZZ(n2));")
        try:
            triage(build_dir(nl=nl))
            return False
        except TriageError as e:
            return "neither a known output nor a known input" in str(e)
    cases.append(("a pin name we cannot classify stops the run",
                  unknown_pin, True))

    # An instance that omits its output is normal and must not stop the run.
    def dangling_output_ok():
        nl = MIN_NL.replace("sky130_fd_sc_hd__buf_1 u2 (.A(n1), .X(n2));",
                            "sky130_fd_sc_hd__buf_1 u2 (.A(n1), .X(n2));\n"
                            " sky130_fd_sc_hd__clkbuf_4 clkload0 (.A(n1));")
        t = triage(build_dir(nl=nl))
        return ("sky130_fd_sc_hd__clkbuf_4", "clkload0") in \
            t["floating"]["instances_with_output_omitted"]
    cases.append(("a CTS load buffer with its output omitted is recorded, "
                  "not raised on", dangling_output_ok, True))

    # 5. a disconnected pin count that disagrees with metrics must fail
    def count_mismatch():
        m = dict(MIN_METRICS, **{"design__disconnected_pin__count": 5})
        t = triage(build_dir(metrics=m))
        return not verdicts(t)[0][0]
    cases.append(("a disconnected-pin count that disagrees with metrics fails",
                  count_mismatch, True))

    # 6. an internal net among the disconnected pins must be reported
    def internal_orphan():
        defs = MIN_DEF.replace("- spare ( PIN spare ) ;",
                               "- spare ( PIN spare ) ;\n- _999_ ( PIN _999_ ) ;")
        m = dict(MIN_METRICS, **{"design__disconnected_pin__count": 2})
        t = triage(build_dir(defs=defs, metrics=m))
        return bool(t["disconnected"]["any_internal"]) and not verdicts(t)[1][0]
    cases.append(("an internal net among the disconnected pins is reported",
                  internal_orphan, True))

    # 7. an undriven net must be reported as floating
    def undriven():
        nl = MIN_NL.replace("sky130_fd_sc_hd__inv_1 u1 (.A(in1), .Y(n1));",
                            "sky130_fd_sc_hd__inv_1 u1 (.A(in1), .Y(nX));")
        t = triage(build_dir(nl=nl))
        return "n1" in t["floating"]["structurally_undriven"]
    cases.append(("a net that lost its driver is reported as undriven",
                  undriven, True))

    # 8. a real fanout violation must be found and counted
    def fanout_violation():
        loads = " ".join(f"( u{i} A )" for i in range(3, 3 + MAX_FANOUT + 1))
        defs = MIN_DEF.replace("- n1 ( u1 Y ) ( u2 A )",
                               f"- n1 ( u1 Y ) ( u2 A ) {loads}")
        m = dict(MIN_METRICS, **{"design__max_fanout_violation__count": 1})
        t = triage(build_dir(defs=defs, metrics=m))
        return (t["fanout"]["derived"] == 1
                and t["fanout"]["violators"][0]["net"] == "n1"
                and verdicts(t)[5][0])
    cases.append((f"a net at fanout {MAX_FANOUT + 1} is caught as a violation",
                  fanout_violation, True))

    # 9. a net missing from the SPEF that is not an unused input must be caught.
    # This is the case that killed the first version of the unannotated
    # section, which explained the tool's count with a decomposition that
    # happened to add up on one build.
    def spef_gap():
        spef = MIN_SPEF.replace("*D_NET *2 0.001234\n*END\n", "")
        t = triage(build_dir(spef=spef))
        return t["unannotated"]["no_spef_dnet"] == 2 and not verdicts(t)[3][0]
    cases.append(("a net missing from the SPEF that is not an unused input fails",
                  spef_gap, True))

    # 10. a DEF and SPEF from different builds must not join silently
    def wrong_pair():
        spef = MIN_SPEF.replace("*1 n1", "*1 zzz1").replace("*2 n2", "*2 zzz2")
        spef = spef.replace("*3 in1", "*3 zzz3")
        try:
            triage(build_dir(spef=spef))
            return False
        except TriageError as e:
            return "share only" in str(e)
    cases.append(("a DEF and SPEF that share no net names is caught",
                  wrong_pair, True))

    print("selftest")
    failures = 0
    for name, fn, want in cases:
        try:
            got = fn()
        except Exception as exc:                       # noqa: BLE001
            got, name = False, f"{name}  [raised {exc!r}]"
        ok = got == want
        failures += not ok
        print(f"  {'pass' if ok else 'FAIL'}  {name}")
    print(f"{len(cases) - failures} of {len(cases)} selftests pass")
    return 1 if failures else 0


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", help="archived build bundle directory")
    ap.add_argument("--all-builds", metavar="ROOT",
                    help="also walk ROOT and compare floating-net counts")
    ap.add_argument("--json", help="write the full triage here")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.build:
        ap.error("--build or --selftest is required")

    t = triage(args.build)
    c = t["counts"]
    print(f"build {t['build']}")
    print(f"  {c['def_nets']} DEF nets, {c['spef_dnets']} SPEF D_NETs, "
          f"{c['instances_with_pins']} instances with signal pins\n")

    v = verdicts(t)
    for ok, line in v:
        print(f"  {'ok  ' if ok else 'FAIL'}  {line}")
    failed = sum(not ok for ok, _ in v)
    print(f"\n{len(v) - failed} of {len(v)} checks pass")

    print("\ndisconnected pins:")
    for n in t["disconnected"]["nets"]:
        print(f"    {n}")

    print("\nmax-slew violations by corner:")
    for k, n in t["slew"]["by_corner"].items():
        print(f"    {k:24s} {n}")

    print("\nfive heaviest nets:")
    for h in t["slew"]["heaviest"][:5]:
        print(f"    {h['fF']:8.2f} fF  fanout {h['fanout']:3d}  "
              f"{h['net']:26s} <- {h['driver']}")

    if args.all_builds:
        print("\nevery archived build in the tree:")
        print(f"    {'build':34s} {'instances':>9s} {'floating':>9s} "
              f"{'disconn':>8s} {'unannot':>8s} {'offset':>7s}")
        rows = floating_invariance(args.all_builds)
        for r in rows:
            print(f"    {r['build']:34s} {str(r['instances']):>9s} "
                  f"{str(r['floating_nets']):>9s} {str(r['disconnected']):>8s} "
                  f"{str(r['unannotated']):>8s} {str(r['offset']):>7s}")
        vals = {r["floating_nets"] for r in rows if r["floating_nets"] is not None}
        offs = {r["offset"] for r in rows if r["offset"]}
        print(f"    floating-net count takes {len(vals)} distinct value(s) "
              f"across {len(rows)} builds: {sorted(vals)}")
        print(f"    unannotated-minus-disconnected takes {len(offs)} distinct "
              f"value(s): {sorted(offs)}")
        if len(vals) > 1:
            print("    the floating count varies with the design, so it is not "
                  "a flow constant and needs explaining")
            failed += 1
        t["all_builds"] = rows

    if args.json:
        json.dump(t, open(args.json, "w"), indent=2, sort_keys=True)
        print(f"\nwrote {args.json}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
