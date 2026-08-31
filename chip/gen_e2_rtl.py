#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""The RTL E.2 and Arm C need, generated from the frozen spec and checked.

E.2 settled the pin map, the four window lengths and the acceptance table on
28 August. Arm C settled the sixteen regions and the sixth select bit on the
30th. Neither wrote any RTL, because `src/` has been proven unchanged at the
geometry-record level since 7 August and every edit there costs a full
re-verify. This writes the three modules the build installs, beside the
script rather than into `src/`, so the edit happens once inside the Arm C
build and G.3 pays for it once.

Everything here is generated from `OBSERVABILITY.json` and
`ARMC_REGIONS.json`. Nothing is typed twice. If the window table changes, the
constants in the emitted Verilog change with it, and the check that they
agree is not a comparison against a copy but against the file the spec lives
in.

What is new in the RTL, all of it from E.2:

- three arms instead of two, so `ro_sel` is six bits and `arm` is two,
- a two-bit window select choosing one of four preregistered lengths,
- a sticky overflow flag, set by the counter's own carry out of bit 15 and
  cleared only by reset,
- a measurement-active flag, which is the window enable brought out,
- a two-byte version readable in place of the count.

**None of it has been simulated.** This checks structure: that every pin the
spec claims appears once and only once, that the emitted constants are the
spec's constants, that the select arithmetic closes, that the three modules
agree on their ports, and that every register the design declares is reset.
Behaviour is the build's job, and the stimulus for it is generated here too,
from the acceptance table rather than by hand.

Usage:
    python3 gen_e2_rtl.py --selftest
    python3 gen_e2_rtl.py
    python3 gen_e2_rtl.py --emit chip --csv chip/e2_tb_plan.csv
"""

import argparse
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

OBS_JSON = os.path.join(HERE, "OBSERVABILITY.json")
REGIONS_JSON = os.path.join(HERE, "ARMC_REGIONS.json")
ACCEPT_CSV = os.path.join(HERE, "e2_acceptance.csv")

N_PER_ARM = 16
ARMS = ("A", "B", "C")
TOP = "tt_um_nikodemetrashvili20_ro_puf"

# Which emitted file carries which module. Flat names, because chip/ is
# mirrored flat and a subdirectory would need another rule in the mirror.
FILES = {"e2_ro_puf_core.v": "ro_puf_core",
         "e2_ro_puf.v": "ro_puf",
         "e2_tt_um_ro_puf.v": TOP}


class Results(object):
    def __init__(self):
        self.rows = []

    def add(self, cid, name, ok, detail=""):
        self.rows.append({"id": cid, "name": name, "pass": bool(ok),
                          "detail": detail})
        return ok

    def failed(self):
        return [r["id"] for r in self.rows if not r["pass"]]


# ------------------------------------------------------- a little Verilog

MODULE_RE = re.compile(r"^\s*module\s+(\w+)\s*(?:#\s*\(.*?\)\s*)?\((.*?)\)\s*;",
                       re.S | re.M)
PORT_DECL_RE = re.compile(
    r"^\s*(input|output|inout)\s+(?:wire\s+|reg\s+)?"
    r"(?:\[\s*([^\]]+?)\s*\]\s*)?(\w+)\s*[,;]", re.M)
REG_DECL_RE = re.compile(r"^\s*reg\s+(?:\[[^\]]+\]\s*)?(\w+)", re.M)
ALWAYS_RST_RE = re.compile(r"negedge\s+rst_n")
INST_RE = re.compile(r"^\s*(\w+)\s*(?:#\s*\([^;]*?\)\s*)?(\w+)\s*\(", re.M)


ALWAYS_RE = re.compile(r"always\s*@\s*\(([^)]*)\)")


def clocked_blocks(body):
    """(sensitivity, text) for every clocked always block in a module body.

    A block runs from its own `always @` to the next one, or to the end.
    That is enough here because nothing this file writes nests them, and a
    parser that assumes less than it needs would be guessing.
    """
    hits = list(ALWAYS_RE.finditer(body))
    out = []
    for i, mo in enumerate(hits):
        stop = hits[i + 1].start() if i + 1 < len(hits) else len(body)
        sens = mo.group(1)
        if "posedge" not in sens:
            continue
        out.append((sens, body[mo.end():stop]))
    return out


def parse_modules(text):
    """Module names, their port lists and their declared registers.

    Deliberately small. It reads what this file itself writes, so it needs to
    understand one dialect and no more, and a parser that accepts less is a
    parser that catches more.
    """
    out = {}
    for mo in MODULE_RE.finditer(text):
        name = mo.group(1)
        body = text[mo.end():]
        stop = body.find("\nendmodule")
        body = body[:stop] if stop >= 0 else body
        ports = collections.OrderedDict()
        for d, width, pname in PORT_DECL_RE.findall(mo.group(2) + ";" + body):
            ports[pname] = {"dir": d, "width": (width or "").strip()}
        regs = sorted(set(REG_DECL_RE.findall(body)))
        out[name] = {"ports": ports, "regs": regs, "body": body,
                     "header": mo.group(2)}
    return out


def pin_uses(text, port, bits):
    """How many times each bit of a packed port is named in the text.

    A bit counts as named when it appears on its own, `ui_in[6]`, and also
    when it falls inside a slice, `ui_in[5:2]`. Counting only the first form
    would call the four `ro_idx` bits unread, because the top takes them as
    one slice, and a check that is wrong about the design it reads is worse
    than no check.
    """
    seen = collections.Counter()
    for b in range(bits):
        seen[b] = len(re.findall(r"\b%s\[%d\]" % (port, b), text))
    for hi, lo in re.findall(r"\b%s\[\s*(\d+)\s*:\s*(\d+)\s*\]" % port,
                             text):
        for b in range(int(lo), int(hi) + 1):
            if 0 <= b < bits:
                seen[b] += 1
    return seen


# ------------------------------------------------------------- generation

def window_constants(obs):
    w = obs["windows"]
    return list(w["safe"]) + [w["overflow"]]


def gen_core(obs, sel_bits, cnt_w=16):
    """The measurement core. Three arms, a selectable window, a sticky
    overflow and an active flag."""
    wins = window_constants(obs)
    lines = []
    a = lines.append
    a("// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili")
    a("// SPDX-License-Identifier: Apache-2.0")
    a("//")
    a("// Generated by chip/gen_e2_rtl.py from chip/OBSERVABILITY.json.")
    a("// Do not edit. NOT SIMULATED: lint and gate-level test in the build.")
    a("//")
    a("// Three arms of %d. Arm A is auto-placed ro_macro, Arm C is ro_armc"
      % N_PER_ARM)
    a("// under placement constraints, Arm B is the external hardened macro")
    a("// bank reached through armb_en and armb_out.")
    a("")
    a("`timescale 1ps/1ps")
    a("`default_nettype none")
    a("")
    a("module ro_puf_core #(")
    a("    parameter integer N_PER_ARM = %d," % N_PER_ARM)
    a("    parameter integer SEL_W     = %d," % sel_bits)
    a("    parameter integer CNT_W     = %d" % cnt_w)
    a(") (")
    a("    input  wire                 xclk,")
    a("    input  wire                 rst_n,")
    a("    input  wire                 start,")
    a("    input  wire [SEL_W-1:0]     ro_sel,")
    a("    input  wire [1:0]           win_sel,")
    a("    output wire [N_PER_ARM-1:0] armb_en,")
    a("    input  wire [N_PER_ARM-1:0] armb_out,")
    a("    output reg                  done,")
    a("    output wire                 active,")
    a("    output reg                  overflow,")
    a("    output wire [CNT_W-1:0]     count_out")
    a(");")
    a("    localparam integer N_RO = 3 * N_PER_ARM;")
    a("")
    a("    // The four preregistered window lengths, in xclk cycles. Three")
    a("    // are safe at every corner; the last overflows at every corner")
    a("    // on purpose, so the sticky flag can be tested on any die.")
    for i, w in enumerate(wins):
        a("    localparam [CNT_W-1:0] WIN%d = %d'd%d;" % (i, cnt_w, w))
    a("")
    a("    reg  [CNT_W-1:0] window;")
    a("    always @(*) begin")
    a("        case (win_sel)")
    for i, w in enumerate(wins):
        a("            2'd%d:    window = WIN%d;" % (i, i))
    a("            default: window = WIN0;")
    a("        endcase")
    a("    end")
    a("")
    a("    reg             en_window;")
    a("    reg [CNT_W-1:0] wtimer;")
    a("    reg [SEL_W-1:0] active_sel;")
    a("")
    a("    assign active = en_window;")
    a("")
    a("    // Arm A, auto-placed. Arm C, the same circuit under placement")
    a("    // equalization. Only the selected oscillator runs, and only")
    a("    // while the window is open.")
    a("    wire [N_PER_ARM-1:0] roa_out;")
    a("    wire [N_PER_ARM-1:0] roc_out;")
    a("    genvar i;")
    a("    generate")
    a("        for (i = 0; i < N_PER_ARM; i = i + 1) begin : g_ro_bank")
    a("            ro_macro #(.IDX(i)) u_ro (")
    a("                .en (en_window & (active_sel == i[SEL_W-1:0])),")
    a("                .out(roa_out[i]));")
    a("        end")
    a("        for (i = 0; i < N_PER_ARM; i = i + 1) begin : g_ro_armc")
    a("            ro_armc #(.IDX(i)) u_ro (")
    a("                .en (en_window & (active_sel =="
      " (i + 2 * N_PER_ARM)[SEL_W-1:0])),")
    a("                .out(roc_out[i]));")
    a("        end")
    a("        for (i = 0; i < N_PER_ARM; i = i + 1) begin : g_ro_armb")
    a("            assign armb_en[i] = en_window &"
      " (active_sel == (i + N_PER_ARM)[SEL_W-1:0]);")
    a("        end")
    a("    endgenerate")
    a("")
    a("    wire [2:0] arm_hot = {active_sel >= 2 * N_PER_ARM,")
    a("                          (active_sel >= N_PER_ARM)"
      " & (active_sel < 2 * N_PER_ARM),")
    a("                          active_sel < N_PER_ARM};")
    a("    wire [3:0] idx = active_sel[3:0];")
    a("    wire sel_ro = (arm_hot[0] & roa_out[idx])")
    a("                | (arm_hot[1] & armb_out[idx])")
    a("                | (arm_hot[2] & roc_out[idx]);")
    a("")
    a("    always @(posedge xclk or negedge rst_n) begin")
    a("        if (!rst_n) begin")
    a("            en_window  <= 1'b0;")
    a("            wtimer     <= {CNT_W{1'b0}};")
    a("            done       <= 1'b0;")
    a("            active_sel <= {SEL_W{1'b0}};")
    a("        end else if (start) begin")
    a("            en_window  <= 1'b1;")
    a("            wtimer     <= {CNT_W{1'b0}};")
    a("            done       <= 1'b0;")
    a("            active_sel <= ro_sel;")
    a("        end else if (en_window) begin")
    a("            if (wtimer == window) begin")
    a("                en_window <= 1'b0;")
    a("                done      <= 1'b1;")
    a("            end else begin")
    a("                wtimer <= wtimer + 1'b1;")
    a("            end")
    a("        end")
    a("    end")
    a("")
    a("    wire gated_ro  = sel_ro & en_window;")
    a("    wire cnt_rst_n = rst_n & ~start;")
    a("")
    a("    // Asynchronous ripple counter, one toggle flip-flop a bit, each")
    a("    // clocked by the previous stage's inverted output. Built bit by")
    a("    // bit so every flip-flop keeps a single driver, which the linter")
    a("    // requires.")
    a("    wire [CNT_W-1:0] cnt;")
    a("    wire [CNT_W:0]   tff_clk;")
    a("    assign tff_clk[0] = gated_ro;")
    a("")
    a("    genvar b;")
    a("    generate")
    a("        for (b = 0; b < CNT_W; b = b + 1) begin : g_ripple")
    a("            reg q;")
    a("            always @(posedge tff_clk[b] or negedge cnt_rst_n)")
    a("                if (!cnt_rst_n) q <= 1'b0;")
    a("                else            q <= ~q;")
    a("            assign cnt[b]       = q;")
    a("            assign tff_clk[b+1] = ~q;")
    a("        end")
    a("    endgenerate")
    a("")
    a("    assign count_out = cnt;")
    a("")
    a("    // Sticky overflow. tff_clk[CNT_W] is the carry out of the top")
    a("    // bit, so its rising edge is the wrap. Set only, cleared by")
    a("    // reset alone, so a wrap anywhere in a batch is still readable")
    a("    // after the batch.")
    a("    always @(posedge tff_clk[CNT_W] or negedge rst_n) begin")
    a("        if (!rst_n) overflow <= 1'b0;")
    a("        else        overflow <= 1'b1;")
    a("    end")
    a("endmodule")
    a("")
    a("`default_nettype wire")
    return "\n".join(lines) + "\n"


def gen_puf(sel_bits, cnt_w=16):
    lines = []
    a = lines.append
    a("// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili")
    a("// SPDX-License-Identifier: Apache-2.0")
    a("//")
    a("// Generated by chip/gen_e2_rtl.py. Do not edit. NOT SIMULATED.")
    a("//")
    a("// Three-arm RO-PUF top. arm picks the arm and ro_idx the oscillator")
    a("// inside it, so ro_sel is {arm, ro_idx} and arm is two bits now.")
    a("")
    a("`timescale 1ps/1ps")
    a("`default_nettype none")
    a("")
    a("module ro_puf #(")
    a("    parameter integer N_PER_ARM = %d," % N_PER_ARM)
    a("    parameter integer CNT_W     = %d" % cnt_w)
    a(") (")
    a("    input  wire                 xclk,")
    a("    input  wire                 rst_n,")
    a("    input  wire                 start,")
    a("    input  wire [1:0]           arm,")
    a("    input  wire [3:0]           ro_idx,")
    a("    input  wire [1:0]           win_sel,")
    a("    output wire [N_PER_ARM-1:0] armb_en,")
    a("    input  wire [N_PER_ARM-1:0] armb_out,")
    a("    output wire                 done,")
    a("    output wire                 active,")
    a("    output wire                 overflow,")
    a("    output wire [CNT_W-1:0]     count_out")
    a(");")
    a("    localparam integer SEL_W = %d;" % sel_bits)
    a("")
    a("    wire [SEL_W-1:0] ro_sel = {arm, ro_idx};")
    a("")
    a("    ro_puf_core #(.N_PER_ARM(N_PER_ARM), .SEL_W(SEL_W),"
      " .CNT_W(CNT_W)) u_core (")
    a("        .xclk     (xclk),")
    a("        .rst_n    (rst_n),")
    a("        .start    (start),")
    a("        .ro_sel   (ro_sel),")
    a("        .win_sel  (win_sel),")
    a("        .armb_en  (armb_en),")
    a("        .armb_out (armb_out),")
    a("        .done     (done),")
    a("        .active   (active),")
    a("        .overflow (overflow),")
    a("        .count_out(count_out));")
    a("endmodule")
    a("")
    a("`default_nettype wire")
    return "\n".join(lines) + "\n"


def gen_top(obs, cnt_w=16):
    """The Tiny Tapeout top, with E.2's pin map wired exactly as the spec
    records it. Every bit comes out of the pin map rather than being typed."""
    pins = dict(((p["port"], p["bit"]), p) for p in obs["pin_map"])
    lines = []
    a = lines.append
    a("// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili")
    a("// SPDX-License-Identifier: Apache-2.0")
    a("//")
    a("// Generated by chip/gen_e2_rtl.py from chip/OBSERVABILITY.json.")
    a("// Do not edit. NOT SIMULATED.")
    a("//")
    a("// Pin map, which is the spec's and not a copy of it:")
    for p in obs["pin_map"]:
        a("//   %-3s[%d] %-3s %s" % (p["port"], p["bit"], p["direction"],
                                     p["name"]))
    a("//   uio_oe = 0x%02X" % obs["uio_oe"])
    a("")
    a("`timescale 1ps/1ps")
    a("`default_nettype none")
    a("")
    a("module %s (" % TOP)
    a("    input  wire [7:0] ui_in,")
    a("    output wire [7:0] uo_out,")
    a("    input  wire [7:0] uio_in,")
    a("    output wire [7:0] uio_out,")
    a("    output wire [7:0] uio_oe,")
    a("    input  wire       ena,")
    a("    input  wire       clk,")
    a("    input  wire       rst_n")
    a(");")
    a("    localparam [7:0] PROTOCOL_VERSION = 8'd%d;"
      % obs["protocol_version"])
    a("    localparam [7:0] BUILD_ID         = 8'h%02X;" % obs["build_id"])
    a("")
    a("    wire [1:0] arm      = {ui_in[7], ui_in[1]};")
    a("    wire [3:0] ro_idx   = ui_in[5:2];")
    a("    wire       byte_sel = ui_in[6];")
    a("    wire [1:0] win_sel  = {uio_in[2], uio_in[1]};")
    a("    wire       rd_ver   = uio_in[3];")
    a("")
    a("    // One-cycle start pulse from the rising edge of ui_in[0], so a")
    a("    // slow write that holds the pin high still starts one run.")
    a("    reg start_d;")
    a("    always @(posedge clk or negedge rst_n)")
    a("        if (!rst_n) start_d <= 1'b0;")
    a("        else        start_d <= ui_in[0];")
    a("    wire start_pulse = ui_in[0] & ~start_d;")
    a("")
    a("    wire        done;")
    a("    wire        active;")
    a("    wire        overflow;")
    a("    wire [%d:0] count;" % (cnt_w - 1))
    a("    wire [%d:0] armb_en;" % (N_PER_ARM - 1))
    a("    wire [%d:0] armb_out;" % (N_PER_ARM - 1))
    a("")
    a("    ro_puf #(.N_PER_ARM(%d), .CNT_W(%d)) u_puf (" % (N_PER_ARM, cnt_w))
    a("        .xclk     (clk),")
    a("        .rst_n    (rst_n),")
    a("        .start    (start_pulse),")
    a("        .arm      (arm),")
    a("        .ro_idx   (ro_idx),")
    a("        .win_sel  (win_sel),")
    a("        .armb_en  (armb_en),")
    a("        .armb_out (armb_out),")
    a("        .done     (done),")
    a("        .active   (active),")
    a("        .overflow (overflow),")
    a("        .count_out(count));")
    a("")
    a("    wire [7:0] count_byte = byte_sel ? count[%d:8] : count[7:0];"
      % (cnt_w - 1))
    a("    wire [7:0] ver_byte   = byte_sel ? BUILD_ID : PROTOCOL_VERSION;")
    a("    assign uo_out = rd_ver ? ver_byte : count_byte;")
    a("")
    outs = sorted(b for (p, b), v in pins.items()
                  if p == "uio" and v["direction"] == "out")
    drv = {0: "done", 4: "overflow", 5: "active"}
    parts = []
    for b in range(7, -1, -1):
        parts.append(drv[b] if b in outs and b in drv else "1'b0")
    a("    assign uio_out = {%s};" % ", ".join(parts))
    a("    assign uio_oe  = 8'h%02X;" % obs["uio_oe"])
    a("")
    a("    // Tie off what nothing reads, so the linter stays quiet.")
    a("    wire _unused = &{ena, uio_in[0], uio_in[7:4], 1'b0};")
    a("endmodule")
    a("")
    a("`default_nettype wire")
    return "\n".join(lines) + "\n"


def gen_tb_plan(obs):
    """Stimulus for every acceptance test, derived from the table rather than
    written out, so a test cannot exist without a vector or the other way
    round."""
    wins = window_constants(obs)
    sel = dict((w, i) for i, w in enumerate(wins))
    rows = [("id", "kind", "arm", "ro_idx", "win_sel", "rd_ver", "byte_sel",
             "reset_first", "expect")]
    for t in obs["tests"]:
        w = t.get("window")
        rows.append((t["id"], t["kind"],
                     {"reset": 0, "version": 0}.get(t["kind"], 0),
                     0, sel.get(w, 0) if w else 0,
                     1 if t["kind"] == "version" else 0,
                     1 if "high" in t["expect"] or "BUILD" in t["expect"]
                     else 0,
                     1 if t["kind"] == "reset" else 0,
                     t["expect"]))
    return rows


# ------------------------------------------------------------------ checks

def run_checks(obs, regions, emitted, tb_rows):
    res = Results()
    text = "\n".join(emitted[k] for k in sorted(emitted))
    mods = parse_modules(text)

    res.add("R01", "the three modules the build installs are all emitted",
            set(FILES.values()) <= set(mods),
            "missing: %s" % (", ".join(sorted(set(FILES.values())
                                              - set(mods))) or "none"))

    top = mods.get(TOP, {"ports": {}, "regs": [], "body": ""})
    want_top = {"ui_in": "input", "uo_out": "output", "uio_in": "input",
                "uio_out": "output", "uio_oe": "output", "ena": "input",
                "clk": "input", "rst_n": "input"}
    got = dict((k, v["dir"]) for k, v in top["ports"].items())
    res.add("R02", "the top keeps exactly Tiny Tapeout's eight ports",
            got == want_top,
            "differs: %s" % (", ".join(sorted(set(got) ^ set(want_top)))
                             or "none"))

    # Every pin the spec gives a job to has to be read or driven, and every
    # pin it calls spare must not be.
    body = mods.get(TOP, {}).get("body", "")
    used_in = pin_uses(body, "ui_in", 8)
    used_uio = pin_uses(body, "uio_in", 8)
    bad = []
    for p in obs["pin_map"]:
        if p["port"] == "ui":
            n = used_in[p["bit"]]
        elif p["port"] == "uio" and p["direction"] == "in":
            n = used_uio[p["bit"]]
        else:
            continue
        if p["owner"] == "spare":
            continue
        if n == 0:
            bad.append("%s[%d] unread" % (p["port"], p["bit"]))
    res.add("R03", "every input pin with a job in the spec is read",
            not bad, "; ".join(bad) or "none")

    oe = re.search(r"assign uio_oe\s*=\s*8'h([0-9A-Fa-f]{2})", body)
    res.add("R04", "uio_oe in the RTL is the value the spec derived",
            oe is not None and int(oe.group(1), 16) == obs["uio_oe"],
            "RTL %s, spec 0x%02X" % (oe.group(1) if oe else "absent",
                                     obs["uio_oe"]))

    core = mods.get("ro_puf_core", {"body": ""})["body"]
    wins = window_constants(obs)
    found = [int(x) for x in re.findall(r"localparam \[CNT_W-1:0\] WIN\d+ ="
                                        r" \d+'d(\d+);", core)]
    res.add("R05", "the window constants are the spec's four, in order",
            found == wins, "%s against %s" % (found, wins))

    sel_bits = regions["select"]["select_bits"]
    # Searched across everything emitted, not inside one module, so a module
    # that goes missing is R01's business and not also R06's.
    m = re.search(r"localparam integer SEL_W = (\d+);", text)
    res.add("R06", "the select width is the one the arm count needs",
            m is not None and int(m.group(1)) == sel_bits,
            "RTL %s, needed %d" % (m.group(1) if m else "absent", sel_bits))

    # Every register a clocked block writes must have an asynchronous
    # reset in that block's sensitivity list. Combinational blocks are
    # skipped: `window` is a reg written by `always @(*)` and a reset on it
    # would be meaningless. `cnt_rst_n` counts, because it is rst_n gated by
    # start and the ripple counter is cleared through it by design.
    unreset = []
    for name, mod in mods.items():
        blocks = clocked_blocks(mod["body"])
        for r in mod["regs"]:
            writing = [b for b in blocks if re.search(r"\b%s\s*<=" % r, b[1])]
            for sens, _text in writing:
                if not re.search(r"negedge\s+(rst_n|cnt_rst_n)", sens):
                    unreset.append("%s.%s" % (name, r))
                    break
    res.add("R07", "every register a clocked block writes has a reset",
            not unreset, ", ".join(sorted(set(unreset))) or "none")

    res.add("R08", "the sticky overflow is cleared by reset and nothing else",
            "posedge tff_clk[CNT_W] or negedge rst_n" in core
            and core.count("overflow <= 1'b0;") == 1
            and core.count("overflow <= 1'b1;") == 1,
            "set once, cleared once" if "overflow <= 1'b1;" in core
            else "not found")

    res.add("R09", "active is the window enable and not a second timer",
            "assign active = en_window;" in core,
            "present" if "assign active = en_window;" in core else "absent")

    n_ro = re.search(r"localparam integer N_RO = 3 \* N_PER_ARM;", core)
    banks = len(re.findall(r"begin : g_ro_(bank|armc|armb)", core))
    res.add("R10", "three arms are generated, one bank each",
            n_ro is not None and banks == 3,
            "%d banks" % banks)

    ids = set(r[0] for r in tb_rows[1:])
    want = set(t["id"] for t in obs["tests"])
    res.add("R11", "every acceptance test has exactly one stimulus row",
            ids == want and len(tb_rows) - 1 == len(obs["tests"]),
            "%d rows, %d tests" % (len(tb_rows) - 1, len(obs["tests"])))

    winsel = set(int(r[4]) for r in tb_rows[1:])
    res.add("R12", "the stimulus reaches every window the spec declares",
            winsel >= set(range(len(wins))),
            "selects used: %s" % sorted(winsel))

    res.add("R13", "no emitted file writes into src/",
            all(not k.startswith("/") and "src" not in k for k in emitted),
            ", ".join(sorted(emitted)))
    return res


# ----------------------------------------------------------------- fixture

def fixture_obs():
    return {"windows": {"safe": [256, 512, 2048], "overflow": 16384},
            "counter_bits": 16, "clock_hz": 50000000,
            "uio_oe": 0x31, "protocol_version": 2, "build_id": 0x1A,
            "pin_map": [{"port": "ui", "bit": 0, "direction": "in",
                         "owner": "existing", "name": "start"},
                        {"port": "ui", "bit": 1, "direction": "in",
                         "owner": "existing", "name": "arm select bit 0"},
                        {"port": "ui", "bit": 2, "direction": "in",
                         "owner": "existing", "name": "ro_idx[0]"},
                        {"port": "ui", "bit": 3, "direction": "in",
                         "owner": "existing", "name": "ro_idx[1]"},
                        {"port": "ui", "bit": 4, "direction": "in",
                         "owner": "existing", "name": "ro_idx[2]"},
                        {"port": "ui", "bit": 5, "direction": "in",
                         "owner": "existing", "name": "ro_idx[3]"},
                        {"port": "ui", "bit": 6, "direction": "in",
                         "owner": "existing", "name": "byte select"},
                        {"port": "ui", "bit": 7, "direction": "in",
                         "owner": "armc", "name": "arm select bit 1"},
                        {"port": "uio", "bit": 0, "direction": "out",
                         "owner": "existing", "name": "done"},
                        {"port": "uio", "bit": 1, "direction": "in",
                         "owner": "e2", "name": "window select bit 0"},
                        {"port": "uio", "bit": 2, "direction": "in",
                         "owner": "e2", "name": "window select bit 1"},
                        {"port": "uio", "bit": 3, "direction": "in",
                         "owner": "e2", "name": "read version"},
                        {"port": "uio", "bit": 4, "direction": "out",
                         "owner": "e2", "name": "overflow"},
                        {"port": "uio", "bit": 5, "direction": "out",
                         "owner": "e2", "name": "active"},
                        {"port": "uio", "bit": 6, "direction": "in",
                         "owner": "spare", "name": "reserved"},
                        {"port": "uio", "bit": 7, "direction": "in",
                         "owner": "spare", "name": "reserved"}],
            "tests": [{"id": "E2-01", "kind": "reset", "window": None,
                       "expect": "all low"},
                      {"id": "E2-02", "kind": "mode", "window": 256,
                       "expect": "count nonzero"},
                      {"id": "E2-03", "kind": "mode", "window": 512,
                       "expect": "count nonzero"},
                      {"id": "E2-04", "kind": "mode", "window": 2048,
                       "expect": "count nonzero"},
                      {"id": "E2-05", "kind": "overflow", "window": 16384,
                       "expect": "overflow high"},
                      {"id": "E2-06", "kind": "version", "window": None,
                       "expect": "uo_out = BUILD high byte"}]}


def fixture_regions():
    return {"select": {"oscillators": 48, "select_bits": 6, "arm_bits": 2,
                       "idx_bits": 4}}


def build_all(obs, regions):
    sel = regions["select"]["select_bits"]
    emitted = {"e2_ro_puf_core.v": gen_core(obs, sel),
               "e2_ro_puf.v": gen_puf(sel),
               "e2_tt_um_ro_puf.v": gen_top(obs)}
    return emitted, gen_tb_plan(obs)


def selftest():
    print("gen_e2_rtl selftest")
    ok = True
    obs, regions = fixture_obs(), fixture_regions()
    emitted, tb = build_all(obs, regions)
    res = run_checks(obs, regions, emitted, tb)
    if res.failed():
        print("  FAIL: clean fixture fails %s" % ", ".join(res.failed()))
        for r in res.rows:
            if not r["pass"]:
                print("        %s %s" % (r["id"], r["detail"]))
        ok = False
    else:
        print("  clean fixture passes all %d checks" % len(res.rows))

    def rename_module(e, t, o, g):
        # Renamed, not deleted. Deleting the file would take its SEL_W with
        # it and R06 would answer for that instead.
        e = dict(e)
        e["e2_ro_puf.v"] = e["e2_ro_puf.v"].replace("module ro_puf #(",
                                                    "module ro_puf_x #(")
        return e, t, o, g

    def break_top_ports(e, t, o, g):
        e = dict(e)
        e["e2_tt_um_ro_puf.v"] = e["e2_tt_um_ro_puf.v"].replace(
            "    input  wire       ena,\n", "")
        return e, t, o, g

    def unread_pin(e, t, o, g):
        e = dict(e)
        e["e2_tt_um_ro_puf.v"] = e["e2_tt_um_ro_puf.v"].replace(
            "wire [1:0] win_sel  = {uio_in[2], uio_in[1]};",
            "wire [1:0] win_sel  = 2'b00;")
        return e, t, o, g

    def wrong_oe(e, t, o, g):
        e = dict(e)
        e["e2_tt_um_ro_puf.v"] = e["e2_tt_um_ro_puf.v"].replace(
            "assign uio_oe  = 8'h31;", "assign uio_oe  = 8'h33;")
        return e, t, o, g

    def wrong_window(e, t, o, g):
        e = dict(e)
        e["e2_ro_puf_core.v"] = e["e2_ro_puf_core.v"].replace(
            "WIN2 = 16'd2048;", "WIN2 = 16'd4096;")
        return e, t, o, g

    def wrong_selw(e, t, o, g):
        e = dict(e)
        e["e2_ro_puf.v"] = e["e2_ro_puf.v"].replace(
            "localparam integer SEL_W = 6;",
            "localparam integer SEL_W = 5;")
        return e, t, o, g

    def unreset_reg(e, t, o, g):
        e = dict(e)
        e["e2_tt_um_ro_puf.v"] = e["e2_tt_um_ro_puf.v"].replace(
            "    always @(posedge clk or negedge rst_n)\n"
            "        if (!rst_n) start_d <= 1'b0;\n"
            "        else        start_d <= ui_in[0];",
            "    always @(posedge clk)\n"
            "        start_d <= ui_in[0];")
        return e, t, o, g

    def clearable_overflow(e, t, o, g):
        e = dict(e)
        e["e2_ro_puf_core.v"] = e["e2_ro_puf_core.v"].replace(
            "        if (!rst_n) overflow <= 1'b0;\n"
            "        else        overflow <= 1'b1;",
            "        if (!rst_n) overflow <= 1'b0;\n"
            "        else if (start) overflow <= 1'b0;\n"
            "        else        overflow <= 1'b1;")
        return e, t, o, g

    def no_active(e, t, o, g):
        e = dict(e)
        e["e2_ro_puf_core.v"] = e["e2_ro_puf_core.v"].replace(
            "assign active = en_window;", "assign active = 1'b0;")
        return e, t, o, g

    def two_arms(e, t, o, g):
        e = dict(e)
        e["e2_ro_puf_core.v"] = e["e2_ro_puf_core.v"].replace(
            "for (i = 0; i < N_PER_ARM; i = i + 1) begin : g_ro_armc",
            "for (i = 0; i < N_PER_ARM; i = i + 1) begin : g_spare")
        return e, t, o, g

    def short_stimulus(e, t, o, g):
        return e, t[:-1], o, g

    def one_window_untested(e, t, o, g):
        t = [t[0]] + [list(r[:4]) + [0] + list(r[5:]) for r in t[1:]]
        return e, t, o, g

    faults = [
        ("R01", "a module the build needs is not there under its name",
         rename_module),
        ("R02", "the top loses one of Tiny Tapeout's ports", break_top_ports),
        ("R03", "a pin the spec gives a job to is never read", unread_pin),
        ("R04", "uio_oe in the RTL disagrees with the spec", wrong_oe),
        ("R05", "a window constant the spec did not choose", wrong_window),
        ("R06", "a select width too narrow for three arms", wrong_selw),
        ("R07", "a register a clocked block writes and reset misses",
         unreset_reg),
        ("R08", "an overflow flag something other than reset clears",
         clearable_overflow),
        ("R09", "an active flag tied off instead of wired", no_active),
        ("R10", "only two arms generated", two_arms),
        ("R11", "an acceptance test with no stimulus row", short_stimulus),
        ("R12", "stimulus that never selects three of the windows",
         one_window_untested),
    ]
    for want, label, fn in faults:
        e2, t2, o2, g2 = fn(emitted, tb, obs, regions)
        r2 = run_checks(o2, g2, e2, t2)
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

    # R13 cannot be reached from the spec; it guards the emitter's own idea
    # of where files go, so the fault comes from the other side.
    r3 = run_checks(obs, regions, dict(emitted, **{"src/ro_puf.v": "// no"}),
                    tb)
    if set(r3.failed()) == {"R13"}:
        print("  ok    R13  an emitted path that reaches into src/")
    else:
        print("  FAIL  R13  tripped %s" % (", ".join(r3.failed()) or "nothing"))
        ok = False

    # The parser, on a module it did not write.
    mods = parse_modules("module m (a, b);\n input wire a;\n"
                         " output reg [3:0] b;\n reg c;\n"
                         " always @(posedge a or negedge rst_n)\n"
                         "  if (!rst_n) c <= 1'b0; else c <= a;\n"
                         "endmodule\n")
    good = ("m" in mods and mods["m"]["ports"]["a"]["dir"] == "input"
            and mods["m"]["ports"]["b"]["width"] == "3:0"
            and "c" in mods["m"]["regs"])
    print("  %-5s parse  ports, widths and registers off a hand-written module"
          % ("ok" if good else "FAIL"))
    ok = ok and good

    print("\n  %s" % ("all faults isolated" if ok else "SELFTEST FAILED"))
    return 0 if ok else 1


# ---------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--emit", help="directory for the generated verilog")
    ap.add_argument("--csv", help="write the stimulus plan here")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    for p in (OBS_JSON, REGIONS_JSON):
        if not os.path.exists(p):
            raise SystemExit("missing input: %s" % p)
    with open(OBS_JSON, "r", encoding="utf-8") as fh:
        obs = json.load(fh)
    with open(REGIONS_JSON, "r", encoding="utf-8") as fh:
        regions = json.load(fh)

    emitted, tb = build_all(obs, regions)
    res = run_checks(obs, regions, emitted, tb)

    print("E.2 and Arm C RTL, generated from the frozen spec")
    print("  windows   %s cycles, select %d bits, %d oscillators"
          % (window_constants(obs), regions["select"]["select_bits"],
             regions["select"]["oscillators"]))
    print("  uio_oe    0x%02X, protocol %d, build 0x%02X"
          % (obs["uio_oe"], obs["protocol_version"], obs["build_id"]))
    for name in sorted(emitted):
        print("  %-22s %5d lines" % (name, len(emitted[name].split("\n"))))
    print("  %-22s %5d rows" % ("e2_tb_plan.csv", len(tb) - 1))
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

    if a.emit:
        if not os.path.isdir(a.emit):
            os.makedirs(a.emit)
        for name, body in sorted(emitted.items()):
            with open(os.path.join(a.emit, name), "w", encoding="utf-8",
                      newline="\n") as fh:
                fh.write(body)
            print("  wrote %s" % os.path.join(a.emit, name))
    if a.csv:
        with open(a.csv, "w", encoding="utf-8", newline="\n") as fh:
            for row in tb:
                fh.write(",".join('"%s"' % str(c) if "," in str(c)
                                  else str(c) for c in row) + "\n")
        print("  wrote %s" % a.csv)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
