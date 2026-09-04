#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Lint the RTL that is going to the chip.

Ten days of Phase E produced three generated Verilog modules under `chip/`
and a runbook whose second step copies them into the source tree. Nothing in
the ninety-seven command gate ever compiled a `.v` file. The gate regenerates
each module and diffs it against the committed copy, which proves the
generator is deterministic and proves nothing at all about the Verilog.

This script is the missing half. It does two separate jobs.

The first is a real elaboration. `iverilog -g2005 -Wall` over a file set,
with the standard cell modules stubbed out. The stubs are built from the pin
names the design itself uses, not from a table typed out here, because a
hand-written table of sky130 pin names is the habit A.1 was corrected for.
Every stub port is declared `inout`, which means the elaboration checks
names and arity and deliberately does not check pin direction. Direction
belongs to `extraction/cell_library.py` when that module is split out.

The second job needs no compiler. Eight structural properties are read
straight out of the text, and each one exists because the live design earned
it and a draft lost it. A ripple counter clocked through an AND gate, a
count published before it has settled, a control bundle that skips the
synchronizer, sixteen macro instances that vanish, an arm that is supposed
to be a copy of another arm and is not. A compiler catches none of those.
They are all legal Verilog.

Until 4 September there were two file sets. The drafts under `chip/` were a
different design from the one in `dualarm/src`, so both were linted and the
drafts were reported rather than enforced, which is how `draft_installable`
came to be the field G.3 step 2 read before it ran. On 1 September the
drafts failed nine of ten; on the 2nd, rebuilt by `chip/gen_e2_rtl.py` as a
transformation of the live RTL rather than as fresh Verilog, they passed all
ten, and on the 4th step 2 installed them. There is one design now and one
set, and the copies under `chip/` are held to it by a diff in the gate
rather than by a second lint of the same bytes.

R08 has stopped being n/a as a result. The live set carries `ro_armc.v`, so
the check that Arm C is the Arm A ring node for node now runs on what is
going to the chip rather than on a draft of it.

A check that does not apply to a file set reports `n/a` and is counted
separately. It is never folded into the pass count. A check that passes
because it found nothing to look at is worse than a missing check.

Usage:
    python3 lint_rtl.py --selftest
    python3 lint_rtl.py
    python3 lint_rtl.py --json /tmp/rtl_lint.json
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

LIVE_DIR = os.path.join(ROOT, "dualarm", "src")
CONFIG_JSON = os.path.join(LIVE_DIR, "config.json")

# One file set. Until G.3 step 2 there were two, because the Phase E drafts
# under chip/ were a different design from the one in dualarm/src and both
# had to be reported. Step 2 installed them on 4 September, so dualarm/src
# is the three-arm design and the copies under chip/ are copies: the gate
# diffs them against these files rather than linting them twice.
LIVE_SET = ["tt_um_ro_puf.v", "ro_puf.v", "ro_puf_core.v", "ro_armc.v",
            "ro_macro.v", "ro_macro_hard_bb.v"]

TOP_MODULE = "tt_um_nikodemetrashvili20_ro_puf"

CELL_INST = re.compile(r"(sky130_fd_sc_hd__\w+)\s+(\w+)\s*\((.*?)\)\s*;", re.S)
PORT_CONN = re.compile(r"\.(\w+)\s*\(\s*([^()]*?)\s*\)")
MODULE_HEAD = re.compile(r"\bmodule\s+(\w+)")


def strip_comments(text):
    """Verilog comments out. Nothing here needs to survive a string literal,
    because this RTL has none outside of comments."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


class Results(object):
    def __init__(self):
        self.rows = []

    def add(self, cid, target, name, ok, detail="", applies=True):
        self.rows.append({"id": cid, "target": target, "name": name,
                          "pass": bool(ok) if applies else None,
                          "applies": bool(applies), "detail": detail})

    def failed(self, target=None):
        return [r["id"] for r in self.rows
                if r["applies"] and not r["pass"]
                and (target is None or r["target"] == target)]

    def counts(self, target=None):
        rows = [r for r in self.rows
                if target is None or r["target"] == target]
        ok = len([r for r in rows if r["applies"] and r["pass"]])
        bad = len([r for r in rows if r["applies"] and not r["pass"]])
        na = len([r for r in rows if not r["applies"]])
        return ok, bad, na


# ---------------------------------------------------------------------------
# Stub generation. The pin names come out of the design, never out of a table
# typed here. Every port is inout on purpose: see the module docstring.
# ---------------------------------------------------------------------------
def cell_pins(sources):
    pins = {}
    for text in sources.values():
        for m in CELL_INST.finditer(strip_comments(text)):
            cell = m.group(1)
            names = [p[0] for p in PORT_CONN.findall(m.group(3))]
            got = pins.setdefault(cell, [])
            for n in names:
                if n not in got:
                    got.append(n)
    return pins


def write_stubs(path, pins):
    lines = ["// generated by lint_rtl.py from the pin names the design uses",
             "`timescale 1ps/1ps", ""]
    for cell in sorted(pins):
        ports = ", ".join("inout %s" % p for p in pins[cell])
        lines.append("module %s (%s);" % (cell, ports))
        lines.append("endmodule")
        lines.append("")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))


# ---------------------------------------------------------------------------
# E01, E02: the compiler half.
# ---------------------------------------------------------------------------
def elaborate(sources, target, res):
    exe = shutil.which("iverilog")
    if not exe:
        res.add("E01", target, "the file set elaborates under iverilog "
                "-g2005", False, "iverilog is not installed, so nothing was "
                "compiled. This is a failure and not a skip: the reason this "
                "check exists is that the gate never compiled anything.")
        res.add("E02", target, "no width warnings anywhere in the set",
                False, "not reached, iverilog is not installed")
        return {"available": False, "errors": [], "warnings": []}

    tmp = tempfile.mkdtemp(prefix="lint_rtl_")
    try:
        names = []
        for name, text in sorted(sources.items()):
            p = os.path.join(tmp, name)
            with open(p, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
            names.append(p)
        stub = os.path.join(tmp, "zz_stub_cells.v")
        write_stubs(stub, cell_pins(sources))
        names.append(stub)

        proc = subprocess.run([exe, "-g2005", "-Wall", "-t", "null",
                               "-o", os.devnull] + names,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT)
        out = proc.stdout.decode("utf-8", "replace")
        # The temp directory is different on every run, and its name lands in
        # every message. Left in, this file could never diff clean against
        # itself twice and the gate would fail forever for a reason that has
        # nothing to do with the RTL. Same fault RELEASE_MANIFEST.json had
        # when it recorded its own hash.
        out = out.replace(tmp + os.sep, "").replace(tmp + "/", "")
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        errs = [l for l in lines if "error" in l.lower()
                or re.search(r":\d+:\s*syntax error", l)]
        warns = [l for l in lines if "warning" in l.lower()]
        widths = [l for l in warns if "width" in l.lower()]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    res.add("E01", target, "the file set elaborates under iverilog -g2005",
            not errs, "; ".join(errs[:6]) if errs else "clean")
    res.add("E02", target, "no width warnings anywhere in the set",
            not widths, "; ".join(widths[:6]) if widths else
            "%d other warnings" % (len(warns) - len(widths)))
    return {"available": True, "errors": errs, "warnings": warns}


# ---------------------------------------------------------------------------
# R01: a part-select applied to a parenthesised expression. Not legal in
# Verilog-2001 or 2005, and iverilog rejects it, but this catches it with no
# compiler at all, which is the point on a machine that has none.
# ---------------------------------------------------------------------------
def check_r01(sources, target, res):
    bad = []
    for name, text in sorted(sources.items()):
        code = strip_comments(text)
        for m in re.finditer(r"\)\s*\[", code):
            head = code[:m.start() + 1]
            depth, i = 0, len(head) - 1
            while i >= 0:
                if head[i] == ")":
                    depth += 1
                elif head[i] == "(":
                    depth -= 1
                    if depth == 0:
                        break
                i -= 1
            before = head[:i].rstrip()
            # A function call or a task is an identifier immediately before
            # the open paren. Anything else is an expression.
            if not re.search(r"[\w$]$", before):
                line = code[:m.start()].count("\n") + 1
                bad.append("%s:%d" % (name, line))
    res.add("R01", target, "no part-select applied to a parenthesised "
            "expression", not bad, ", ".join(bad) if bad else "none found")


# ---------------------------------------------------------------------------
# Small helpers shared by the structural checks.
# ---------------------------------------------------------------------------
def assignments(code):
    """Every continuous assign and every wire-with-initialiser, as a map from
    the assigned name (bit-select stripped) to its right-hand side."""
    out = {}
    for m in re.finditer(r"\bassign\s+([\w\[\]:\s+\-*/]+?)\s*=\s*(.+?);",
                         code, re.S):
        out.setdefault(m.group(1).strip(), m.group(2).strip())
    for m in re.finditer(r"\bwire\s*(?:\[[^\]]*\])?\s*(\w+)\s*=\s*(.+?);",
                         code, re.S):
        out.setdefault(m.group(1), m.group(2).strip())
    return out


def resolve_alias(name, amap, limit=8):
    """Follow assign a = b; assign b = c & d; down to the first expression
    that is not a bare identifier."""
    seen = set()
    cur = name
    for _ in range(limit):
        if cur in seen:
            break
        seen.add(cur)
        rhs = amap.get(cur)
        if rhs is None:
            break
        rhs = re.sub(r"\s+", " ", rhs).strip()
        if re.fullmatch(r"\w+", rhs):
            cur = rhs
            continue
        return rhs
    return cur


def declared_regs(code):
    names = set()
    for m in re.finditer(r"\breg\s*(?:\[[^\]]*\])?\s*([\w\s,]+?);", code):
        for n in m.group(1).split(","):
            n = n.strip()
            if n:
                names.add(n)
    for m in re.finditer(r"\boutput\s+reg\s*(?:\[[^\]]*\])?\s*(\w+)", code):
        names.add(m.group(1))
    return names


def core_text(sources):
    for name, text in sources.items():
        if re.search(r"\bmodule\s+ro_puf_core\b", strip_comments(text)):
            return name, strip_comments(text)
    return None, None


def top_text(sources):
    for name, text in sources.items():
        if re.search(r"\bmodule\s+%s\b" % TOP_MODULE, strip_comments(text)):
            return name, strip_comments(text)
    return None, None


# ---------------------------------------------------------------------------
# R02: the ripple counter's first stage is clocked by the raw ring output.
#
# Putting `sel_ro & en_window` on that net is the revision the live core
# removed in July. en_window lives in the xclk domain and can fall at any
# phase of a ~570 MHz ring, so the gate can chop the last high pulse into a
# runt on a clock net. The live file carries the whole argument in a comment
# and a SPICE phase sweep behind it. A draft reintroduced it.
# ---------------------------------------------------------------------------
def check_r02(sources, target, res):
    name, code = core_text(sources)
    if code is None:
        res.add("R02", target, "the ripple counter's first stage is clocked "
                "by an ungated ring output", None, "no ro_puf_core in this "
                "set", applies=False)
        return
    amap = assignments(code)
    key = None
    for k in amap:
        if re.fullmatch(r"tff_clk\s*\[\s*0\s*\]", k):
            key = k
    if key is None:
        res.add("R02", target, "the ripple counter's first stage is clocked "
                "by an ungated ring output", False,
                "no assignment to tff_clk[0] found in %s" % name)
        return
    expr = resolve_alias(amap[key].strip(), amap) \
        if re.fullmatch(r"\w+", amap[key].strip()) else amap[key].strip()
    gated = bool(re.search(r"[&|^?]", expr))
    res.add("R02", target, "the ripple counter's first stage is clocked by "
            "an ungated ring output", not gated,
            "tff_clk[0] resolves to '%s'" % re.sub(r"\s+", " ", expr))


# ---------------------------------------------------------------------------
# R03: the count is published out of a register, never straight off the
# asynchronous ripple counter.
# ---------------------------------------------------------------------------
def check_r03(sources, target, res):
    name, code = core_text(sources)
    if code is None:
        res.add("R03", target, "count_out is published from a register",
                None, "no ro_puf_core in this set", applies=False)
        return
    amap = assignments(code)
    rhs = None
    for k, v in amap.items():
        if k.strip() == "count_out":
            rhs = v.strip()
    if rhs is None:
        res.add("R03", target, "count_out is published from a register",
                False, "no assignment to count_out in %s" % name)
        return
    regs = declared_regs(code)
    ok = bool(re.fullmatch(r"\w+", rhs)) and rhs in regs
    res.add("R03", target, "count_out is published from a register", ok,
            "count_out = %s, %s" % (rhs, "a reg" if ok else "not a reg"))


# ---------------------------------------------------------------------------
# R04: the stopped-ring settle handshake.
#
# One property, not three. The live core stops every oscillator, drains a
# two-flop sampler and then requires three consecutive equal synchronized
# samples before it latches. Take away the settle state, the sampler or the
# sample count and what is left publishes a torn word, so no fixture can
# separate them. Same call as T06 in the tile budget.
# ---------------------------------------------------------------------------
def check_r04(sources, target, res):
    name, code = core_text(sources)
    if code is None:
        res.add("R04", target, "the stopped-ring settle handshake is present",
                None, "no ro_puf_core in this set", applies=False)
        return
    settle = bool(re.search(r"\bST_SETTLE\b", code))
    stable = bool(re.search(r"\w*STABLE\w*\s*=", code))
    sampler = len(re.findall(r'async_reg\s*=\s*"true"', code))
    ok = settle and stable and sampler >= 2
    res.add("R04", target, "the stopped-ring settle handshake is present",
            ok, "settle state %s, stable-sample rule %s, %d async_reg "
            "sampler stages" % ("yes" if settle else "NO",
                                "yes" if stable else "NO", sampler))


# ---------------------------------------------------------------------------
# R05: the board GPIOs are asynchronous to clk, so the control bundle goes
# through two async_reg stages in the top before anything reads it.
#
# Named, not counted. The top has three async_reg registers and the first of
# them is the reset synchronizer, so "there are at least two" says nothing
# about the control path. This finds the register that actually samples
# ui_in and then the register that samples that one, which is the two-stage
# chain the property is about.
#
# The bundle is not required to be ui_in on its own. E.2 puts three more
# control signals on uio_in and they go through the same chain, so the test
# is that a register carrying ui_in feeds a second register, whatever else
# rides alongside it. Which pins have to be in that bundle is a question
# about the spec rather than about the RTL, and chip/gen_e2_rtl.py R03
# answers it against OBSERVABILITY.json.
# ---------------------------------------------------------------------------
def check_r05(sources, target, res):
    name, code = top_text(sources)
    if code is None:
        res.add("R05", target, "the control bundle reaches the design "
                "through two async_reg stages", None,
                "no top module in this set", applies=False)
        return
    names = re.findall(r'async_reg\s*=\s*"true"\s*\*\)\s*reg'
                       r'\s*(?:\[[^\]]*\])?\s*(\w+)', code)
    meta = None
    for n in names:
        rhs = re.findall(r"\b%s\s*<=\s*([^;]+);" % n, code)
        if any("ui_in" in r for r in rhs):
            meta = n
            break
    second = None
    if meta is not None:
        for n in names:
            if n != meta and re.search(r"\b%s\s*<=\s*%s\s*;" % (n, meta),
                                       code):
                second = n
                break
    ok = meta is not None and second is not None
    if ok:
        detail = "%d async_reg registers, %s samples ui_in and %s samples %s" \
            % (len(names), meta, second, meta)
    elif meta is None:
        detail = "%d async_reg registers, none of them samples ui_in" \
            % len(names)
    else:
        detail = "%s samples ui_in but no second async_reg stage reads it" \
            % meta
    res.add("R05", target, "the control bundle reaches the design through "
            "two async_reg stages", ok, detail)


# ---------------------------------------------------------------------------
# R06: every Arm B macro named in config.json is instantiated in the top.
#
# The instance names are the keys of MACROS.ro_macro_hard.instances, and the
# flow places the hardened GDS by those names. A top that does not
# instantiate them is a chip with no Arm B.
# ---------------------------------------------------------------------------
def check_r06(sources, target, res, config_path=None):
    path = config_path or CONFIG_JSON
    name, code = top_text(sources)
    if code is None or not os.path.exists(path):
        res.add("R06", target, "every macro instance named in config.json is "
                "instantiated in the top", None,
                "no top module in this set" if code is None
                else "no config.json at %s" % path, applies=False)
        return
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    want = sorted(cfg.get("MACROS", {}).get("ro_macro_hard", {})
                  .get("instances", {}).keys())
    if not want:
        res.add("R06", target, "every macro instance named in config.json is "
                "instantiated in the top", None,
                "config.json names no macro instances", applies=False)
        return
    have = set(re.findall(r"\bro_macro_hard\s+(\w+)\s*\(", code))
    missing = [w for w in want if w not in have]
    res.add("R06", target, "every macro instance named in config.json is "
            "instantiated in the top", not missing,
            "%d of %d present%s" % (len(want) - len(missing), len(want),
                                    ", missing " + ", ".join(missing[:4])
                                    if missing else ""))


# ---------------------------------------------------------------------------
# R07: ena takes part in the project reset rather than being tied off.
#
# Pulling ena low has to shut down a running oscillator even when the
# reference clock has stopped, so it belongs in the asynchronous reset and
# not in the _unused bundle.
# ---------------------------------------------------------------------------
def check_r07(sources, target, res):
    name, code = top_text(sources)
    if code is None:
        res.add("R07", target, "ena takes part in the project reset", None,
                "no top module in this set", applies=False)
        return
    unused = re.findall(r"_unused\s*=\s*&\{([^}]*)\}", code)
    tied = any(re.search(r"\bena\b", u) for u in unused)
    body = re.sub(r"_unused\s*=\s*&\{[^}]*\}", "", code)
    used = bool(re.search(r"\bena\b\s*(?:&|\))", body)
                or re.search(r"[&(]\s*\bena\b", body))
    res.add("R07", target, "ena takes part in the project reset",
            used and not tied,
            "ena is %sin a reset expression and %stied off"
            % ("" if used else "NOT ", "" if tied else "not "))


# ---------------------------------------------------------------------------
# R08: the Arm C ring matches the Arm A ring node for node.
#
# Arm C exists so that one arm differs from another in placement treatment
# and in nothing else. Any fixed difference in the circuit is a confound: a
# frequency offset between the arms could be the difference rather than the
# placement. So the two ring modules have to agree cell for cell and net for
# net once the loop index is normalised, and the check reports the node that
# differs rather than only that something does.
# ---------------------------------------------------------------------------
def _net(expr, env):
    """Turn n[N_INV/2] into n[15]. Verilog integer parameters divide as
    integers, so // is the right operator here and / would be wrong."""
    expr = re.sub(r"\s+", "", expr)
    m = re.fullmatch(r"(\w+)\[([^\]]+)\]", expr)
    if not m:
        return expr
    body = m.group(2).replace("/", "//")
    try:
        return "%s[%d]" % (m.group(1), int(eval(body, {"__builtins__": {}},
                                                dict(env))))
    except Exception:
        return expr


def ring_signature(code, module, n_inv=30):
    """The ring as a netlist, not as text. The generate loop is expanded so
    that two files writing the same chain with different loop bounds compare
    equal, because they elaborate to the same thing and the only differences
    worth reporting are the ones that reach the silicon."""
    m = re.search(r"\bmodule\s+%s\b.*?\bendmodule\b" % module, code, re.S)
    if not m:
        return None
    body = m.group(0)
    env = {"N_INV": n_inv}

    loops = []
    for g in re.finditer(r"for\s*\(\s*(\w+)\s*=\s*([^;]+);\s*\1\s*"
                         r"(<=?)\s*([^;]+);.*?\bend\b", body, re.S):
        var, lo, op, hi = g.group(1), g.group(2), g.group(3), g.group(4)
        try:
            lo_i = int(eval(lo.replace("/", "//"), {"__builtins__": {}},
                            dict(env)))
            hi_i = int(eval(hi.replace("/", "//"), {"__builtins__": {}},
                            dict(env)))
        except Exception:
            return None
        loops.append((g.start(), g.end(), var, lo_i,
                      hi_i + 1 if op == "<=" else hi_i, g.group(0)))

    cells = []

    def add(text, extra):
        for inst in CELL_INST.finditer(text):
            conns = {}
            for pin, net in PORT_CONN.findall(inst.group(3)):
                conns[pin] = _net(net, dict(env, **extra))
            cells.append((inst.group(1), tuple(sorted(conns.items()))))

    covered = "".join(body[a:b] for a, b, _, _, _, _ in loops)
    outside = body
    for a, b, _, _, _, _ in loops:
        outside = outside.replace(body[a:b], "")
    add(outside, {})
    for _, _, var, lo_i, hi_i, text in loops:
        for i in range(lo_i, hi_i):
            add(text, {var: i})

    return {"cells": sorted(cells), "n_cells": len(cells)}


def check_r08(sources, target, res):
    joined = {n: strip_comments(t) for n, t in sources.items()}
    a = c = None
    for text in joined.values():
        a = a or ring_signature(text, "ro_macro")
        c = c or ring_signature(text, "ro_armc")
    if a is None or c is None:
        res.add("R08", target, "the Arm C ring matches the Arm A ring node "
                "for node", None,
                "this set has %s" % ("no ro_armc" if c is None
                                     else "no ro_macro"), applies=False)
        return
    diffs = []
    if a["n_cells"] != c["n_cells"]:
        diffs.append("Arm A elaborates to %d cells and Arm C to %d"
                     % (a["n_cells"], c["n_cells"]))
    only_a = [x for x in a["cells"] if x not in c["cells"]]
    only_c = [x for x in c["cells"] if x not in a["cells"]]
    for cell, conns in only_a[:4]:
        match = [x for x in only_c if x[0] == cell]
        if match:
            other = dict(match[0][1])
            for pin, net in conns:
                if other.get(pin) != net:
                    diffs.append("%s pin %s is %s in Arm A and %s in Arm C"
                                 % (cell, pin, net, other.get(pin)))
        else:
            diffs.append("%s %s is in Arm A only" % (cell, dict(conns)))
    for cell, conns in only_c[:4]:
        if not [x for x in only_a if x[0] == cell]:
            diffs.append("%s %s is in Arm C only" % (cell, dict(conns)))
    res.add("R08", target, "the Arm C ring matches the Arm A ring node for "
            "node", not diffs,
            "; ".join(diffs) if diffs
            else "identical, %d cells each" % a["n_cells"])



STRUCTURAL = [check_r01, check_r02, check_r03, check_r04,
              check_r05, check_r06, check_r07, check_r08]


def run_set(sources, target, res, config_path=None):
    info = elaborate(sources, target, res)
    for fn in STRUCTURAL:
        if fn is check_r06:
            fn(sources, target, res, config_path=config_path)
        else:
            fn(sources, target, res)
    return info


def load(dirpath, names):
    out = {}
    for n in names:
        p = os.path.join(dirpath, n)
        if os.path.exists(p):
            out[n] = read(p)
    return out


def live_sources():
    return load(LIVE_DIR, LIVE_SET)


def _sub(sources, name, old, new, count=1):
    s = dict(sources)
    if s[name].count(old) != count:
        raise AssertionError("fixture anchor appears %d times in %s, wanted "
                             "%d: %r" % (s[name].count(old), name, count,
                                         old[:60]))
    s[name] = s[name].replace(old, new, count)
    return s


def _armc_fixture(tap):
    """Deliberately written with the opposite loop bounds to ro_macro.v. The
    chain elaborates to the same thirty inverters either way, so a passing
    control here is what proves R08 compares netlists and not text. An
    earlier version compared the loop bounds and reported a difference that
    does not reach the silicon."""
    return ("`timescale 1ps/1ps\n"
            "module ro_armc #(parameter integer N_INV = 30,\n"
            "                 parameter integer IDX = 0)\n"
            "    (input wire en, output wire out);\n"
            "    wire [N_INV:0] n;\n"
            "    sky130_fd_sc_hd__nand2_1 u_nand "
            "(.A(en), .B(n[N_INV]), .Y(n[0]));\n"
            "    genvar i;\n"
            "    generate\n"
            "        for (i = 0; i < N_INV; i = i + 1) begin : g_inv\n"
            "            sky130_fd_sc_hd__inv_1 u_inv "
            "(.A(n[i]), .Y(n[i+1]));\n"
            "        end\n"
            "    endgenerate\n"
            "    sky130_fd_sc_hd__buf_1 u_buf (.A(%s), .X(out));\n"
            "endmodule\n" % tap)


def selftest():
    have_iv = shutil.which("iverilog") is not None
    live = live_sources()
    missing = [n for n in LIVE_SET if n not in live]
    if missing:
        print("  selftest cannot run, missing %s" % ", ".join(missing))
        return 1

    layer = None if have_iv else "R"
    print("  iverilog %s, so the selftest asserts on %s"
          % ("is installed" if have_iv else "is NOT installed",
             "every check" if have_iv else "the structural checks only"))

    def fires(sources, cfg=None):
        r = Results()
        run_set(sources, "fixture", r, config_path=cfg)
        bad = set(r.failed())
        if layer == "R":
            bad = set(b for b in bad if b.startswith("R"))
        return bad, r

    # Each fault names the whole set of checks it is allowed to trip. Every
    # entry is a single check except R01, which is deliberately two: a
    # part-select on an expression is a syntax error, so the compiler catches
    # it as well. R01 exists to catch it on a machine with no compiler, and
    # both firing is the correct answer rather than an overlap to merge away.

    # The control. Nothing planted, nothing should fire.
    bad, r = fires(live)
    if bad:
        print("  CONTROL FAILED: the untouched live design fails %s"
              % ", ".join(sorted(bad)))
        for row in r.rows:
            if row["applies"] and not row["pass"]:
                print("      %s %s" % (row["id"], row["detail"]))
        return 1
    ok, _, na = r.counts()
    print("  control       untouched live design, %d pass, %d n/a" % (ok, na))

    core = "ro_puf_core.v"
    top = "tt_um_ro_puf.v"
    cases = []

    cases.append(({"R01", "E01"} if have_iv else {"R01"}, _sub(
        live, core, "wire sel_ro = ro_out[active_sel];",
        "wire sel_ro = ro_out[(active_sel + 0)[SEL_W-1:0]];"), None))

    cases.append(({"R02"}, _sub(
        live, core, "assign tff_clk[0] = sel_ro;",
        "wire gated_ro = sel_ro & en_window;\n"
        "    assign tff_clk[0] = gated_ro;"), None))

    cases.append(({"R03"}, _sub(
        live, core, "assign count_out = count_latched;",
        "assign count_out = cnt;"), None))

    cases.append(({"R04"}, _sub(
        live, core, "ST_SETTLE", "ST_QUIET", count=5), None))

    cases.append(({"R05"}, _sub(
        live, top, '(* async_reg = "true" *) reg [10:0] ui_meta;\n'
                   '    (* async_reg = "true" *) reg [10:0] ui_sync;',
        "reg [10:0] ui_meta;\n    reg [10:0] ui_sync;"), None))

    # The second R05 fault is the one E.2 made reachable: the chain is still
    # there and still two stages deep, but the control bits are taken off the
    # port instead of out of it. Counting stages cannot see this.
    cases.append(({"R05"}, _sub(
        live, top, "ui_meta      <= {uio_in[3:1], ui_in[7:0]};",
        "ui_meta      <= 11'b0;"), None))

    cases.append(({"R06"}, _sub(
        live, top,
        "ro_macro_hard u_rob7  (.en(armb_en[7]),  .out(armb_out[7]));",
        "assign armb_out[7] = 1'b0;"), None))

    cases.append(({"R07"}, _sub(
        live, top, "wire async_project_rst_n = rst_n & ena;",
        "wire async_project_rst_n = rst_n;"), None))

    # R08 needs both rings in one set, so the fixture supplies an Arm C that
    # matches, then breaks the tap. The matching version is the control for
    # this check: without it R08 could be a check that only ever fails.
    good = dict(live)
    good["ro_armc.v"] = _armc_fixture("n[N_INV/2]")
    bad8, r8 = fires(good)
    if "R08" in bad8:
        row = [x for x in r8.rows if x["id"] == "R08"][0]
        print("  R08 CONTROL FAILED: a matching Arm C ring was rejected: %s"
              % row["detail"])
        return 1
    print("  control       a matching Arm C ring passes R08")
    broken = dict(good)
    broken["ro_armc.v"] = _armc_fixture("n[N_INV]")
    cases.append(({"R08"}, broken, None))

    # The E01 fixture is planted in ro_macro.v on purpose. A missing
    # semicolon inside the core would also stop R03 from finding the
    # assignment it reads, and then the fault would trip two checks for a
    # reason that has nothing to do with either of them. ro_macro.v is read
    # by no structural check unless an Arm C ring is in the set, and this one
    # is the live set.
    if have_iv:
        cases.append(({"E01"}, _sub(
            live, "ro_macro.v", "wire [N_INV:0] n;", "wire [N_INV:0] n"),
            None))

    rc = 0
    for expect, sources, cfg in cases:
        got, r = fires(sources, cfg)
        label = "+".join(sorted(expect))
        if got == expect:
            print("  %-9s planted, %s fired" % (label, label))
        else:
            rc = 1
            print("  %-9s planted, but %s fired"
                  % (label, ", ".join(sorted(got)) if got else "nothing"))
            for row in r.rows:
                if row["applies"] and not row["pass"]:
                    print("      %s: %s" % (row["id"], row["detail"]))

    print("  %d faults, %s" % (len(cases), "all isolated" if not rc
                               else "SOME NOT ISOLATED"))
    return rc


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--json")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    res = Results()
    live = live_sources()

    missing = [n for n in LIVE_SET if n not in live]
    if missing:
        print("  live design is missing %s" % ", ".join(missing))
        return 1

    print("")
    print("  live   %s" % ", ".join(sorted(live)))
    live_info = run_set(live, "live", res)
    print("")

    for target in ("live",):
        ok, bad, na = res.counts(target)
        print("  %-6s %d pass, %d fail, %d n/a" % (target, ok, bad, na))
        for r in res.rows:
            if r["target"] != target:
                continue
            mark = "n/a " if not r["applies"] else \
                   ("pass" if r["pass"] else "FAIL")
            print("    %s %-4s %-58s" % (mark, r["id"], r["name"][:58]))
            if not r["applies"] or not r["pass"]:
                print("           %s" % r["detail"][:140])
        print("")

    live_bad = res.failed("live")
    # Not compiling anything and failing to compile are different answers and
    # deserve different exit codes. A machine with no iverilog gets 2, which
    # says the structural half passed and the compiler half did not run. CI
    # installs iverilog and requires 0, so the enforcement point is there and
    # a local run does not have to read red every time to stay honest.
    uncompiled = not live_info["available"]
    structural_bad = [c for c in live_bad if not c.startswith("E")]

    if structural_bad:
        print("  the live design FAILS %s" % ", ".join(structural_bad))
    elif uncompiled:
        print("  the live design passes every structural check. Nothing was "
              "compiled: install iverilog to run E01 and E02.")
    else:
        print("  the live design passes everything that applies to it.")

    if a.json:
        # Only the structural half is recorded. Whether iverilog was
        # installed is a fact about the machine, not about the RTL, and this
        # file is diffed in the gate: a run on a machine without a compiler
        # would otherwise disagree with a run on one that has it, forever,
        # for a reason that has nothing to do with the design. The compiler
        # half is enforced by this script's exit code instead. Same shape as
        # the manifest that could not carry its own hash.
        rows = [r for r in res.rows if not r["id"].startswith("E")]
        out = {"top_module": TOP_MODULE,
               "sets": {"live": sorted(live)},
               "compiler_checks": "E01 and E02 run but are not recorded "
                                  "here, because whether a compiler was "
                                  "present is not a property of the RTL. "
                                  "They are enforced by the exit code in "
                                  "the archived-evidence job.",
               "checks": rows,
               "live_failures": [c for c in sorted(live_bad)
                                 if not c.startswith("E")]}
        with open(a.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(out, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print("  wrote %s" % a.json)

    if structural_bad:
        return 1
    return 2 if uncompiled else 0


if __name__ == "__main__":
    sys.exit(main())
