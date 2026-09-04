#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""The RTL E.2 and Arm C need, produced by transforming the live design.

An earlier version of this script wrote the three modules from scratch out of
the pin spec. That was the wrong shape and it cost a day to find out: the
generated core did not parse, it put the AND gate back on the counter clock
that July removed, it published the ripple counter before it settled, it
dropped both clock-domain synchronizers, and it instantiated none of the
sixteen Arm B macros. Everything the live design had learned since June was
simply absent, because nothing in the generator had ever read it.

So this one does not write RTL. It reads `dualarm/src/ro_puf_core.v`,
`ro_puf.v` and `tt_um_ro_puf.v` and applies a list of named edits to them.
Each edit carries the exact text it replaces and the number of times that
text must appear. If an anchor is missing, or appears a different number of
times, the script stops and says which edit and which file. That is the
point: when the live RTL moves under it, this fails loudly instead of quietly
reproducing a design that no longer exists.

What the edits add, all of it from E.2 and Arm C:

- a third arm of sixteen rings, so `ro_sel` is six bits and `arm` is two,
- a two-bit window select choosing one of four preregistered lengths,
- a sticky overflow flag,
- a measurement-active flag, which is the window enable brought out,
- a two-byte version readable in place of the count.

What the edits must NOT disturb, which is the other half of the job:

- `tff_clk[0] = sel_ro`, the ungated counter clock,
- the stopped-ring settle handshake and the two-flop counter sampler,
- the control synchronizer in the top, which now has to carry four more
  asynchronous pins than it did,
- the sixteen `ro_macro_hard` instances, whose names are placement keys,
- `ena` folded into the asynchronous project reset.

`chip/lint_rtl.py` is the independent reader that holds the output to all of
those. This script checks the transformation itself: that every anchor
matched, that everything no edit touched survives byte for byte, and that
what the edits wrote agrees with the spec they came from.

**Still not simulated.** Behaviour is the build's job and the stimulus for it
is generated here, from the acceptance table rather than by hand.

Usage:
    python3 gen_e2_rtl.py --selftest
    python3 gen_e2_rtl.py
    python3 gen_e2_rtl.py --emit chip --csv chip/e2_tb_plan.csv
    python3 gen_e2_rtl.py --diff        # show what the edits do
"""

import argparse
import collections
import difflib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

OBS_JSON = os.path.join(HERE, "OBSERVABILITY.json")
REGIONS_JSON = os.path.join(HERE, "ARMC_REGIONS.json")
LIVE_DIR = os.path.join(ROOT, "dualarm", "src")
# The two-arm design as chip/archive_baseline.py froze it in G.3 step 1.
FROZEN_DIR = os.path.join(ROOT, "dualarm", "build_2arm_frozen", "dualarm_src")

N_PER_ARM = 16
CNT_W = 16
TOP = "tt_um_nikodemetrashvili20_ro_puf"

# live file -> emitted file. The emitted names are flat and keep the e2_
# prefix, because chip/ is mirrored flat and the gate diffs them by name.
SOURCES = collections.OrderedDict([
    ("ro_puf_core.v", "e2_ro_puf_core.v"),
    ("ro_puf.v", "e2_ro_puf.v"),
    ("tt_um_ro_puf.v", "e2_tt_um_ro_puf.v"),
])
MODULE_OF = {"e2_ro_puf_core.v": "ro_puf_core",
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


class AnchorError(Exception):
    pass


class Edit(object):
    """One named change to one live file.

    `old` has to appear exactly `count` times or the edit refuses to apply.
    An edit that quietly matched nothing, or matched twice and changed only
    the first, is how a generator drifts away from its source without
    anybody noticing.
    """

    def __init__(self, eid, why, old, new, count=1):
        self.id = eid
        self.why = why
        self.old = old
        self.new = new
        self.count = count

    def apply(self, text, fname):
        found = text.count(self.old)
        if found != self.count:
            raise AnchorError(
                "%s in %s: anchor appears %d times, expected %d\n"
                "  anchor starts: %r"
                % (self.id, fname, found, self.count, self.old[:70]))
        return text.replace(self.old, self.new)


def apply_edits(text, edits, fname):
    for e in edits:
        text = e.apply(text, fname)
    return text


def residue(text, blocks):
    """What is left of a file once every edited region is taken out of it.

    Run over the live text with the edits' `old` blocks and over the emitted
    text with their `new` blocks, the two remainders have to be identical.
    That is the whole preservation claim in one line: everything no edit
    named came through untouched.
    """
    for b in blocks:
        text = text.replace(b, "\x00")
    return text


# --------------------------------------------------------------- spec bits

def window_constants(obs):
    w = obs["windows"]
    return list(w["safe"]) + [w["overflow"]]


def input_bits(obs, port):
    """Bits of `port` the spec gives a job to, as an input."""
    return sorted(p["bit"] for p in obs["pin_map"]
                  if p["port"] == port and p["direction"] == "in"
                  and p["owner"] != "spare")


def output_bits(obs, port):
    return sorted(p["bit"] for p in obs["pin_map"]
                  if p["port"] == port and p["direction"] == "out")


def bit_ranges(bits):
    """[7, 6, 5, 4, 0] -> ['7:4', '0'], high to low."""
    out = []
    for b in sorted(bits, reverse=True):
        if out and out[-1][1] == b + 1:
            out[-1][1] = b
        else:
            out.append([b, b])
    return ["%d" % hi if hi == lo else "%d:%d" % (hi, lo) for hi, lo in out]


def pin_map_comment(obs):
    lines = ["//   clk           measurement reference clock",
             "//   rst_n         active-low reset"]
    for p in obs["pin_map"]:
        port = "ui_in" if p["port"] == "ui" else (
            "uio_out" if p["direction"] == "out" else "uio_in")
        lines.append("//   %-13s %s" % ("%s[%d]" % (port, p["bit"]),
                                        p["name"]))
    lines.append("//   uo_out[7:0]   count byte, or version byte when "
                 "uio_in[%d] is high" % [p["bit"] for p in obs["pin_map"]
                                         if p["name"].startswith("read "
                                                                 "version")][0])
    lines.append("//   uio_oe = 0x%02X" % obs["uio_oe"])
    return "\n".join(lines)


def sync_bundle(obs):
    """The concatenation the first synchronizer stage samples, and where each
    control signal lands in it. ui_in first at the bottom so the existing bit
    positions do not move, which keeps the start/arm/idx/byte decodes and the
    host protocol exactly where they were."""
    order = []
    for b in range(8):
        order.append(("ui", b))
    for b in input_bits(obs, "uio"):
        order.append(("uio", b))
    pos = dict((k, i) for i, k in enumerate(order))
    parts = []
    for r in bit_ranges(input_bits(obs, "uio")):
        parts.append("uio_in[%s]" % r)
    parts.append("ui_in[7:0]")
    return ", ".join(parts), pos, len(order)


def uio_out_concat(obs, drivers):
    outs = output_bits(obs, "uio")
    parts = []
    run = 0
    for b in range(7, -1, -1):
        name = drivers.get(b) if b in outs else None
        if name is None:
            run += 1
            continue
        if run:
            parts.append("%d'b0" % run if run > 1 else "1'b0")
            run = 0
        parts.append(name)
    if run:
        parts.append("%d'b0" % run if run > 1 else "1'b0")
    return "{%s}" % ", ".join(parts)


def unused_concat(obs):
    """uio_in bits nothing reads: the output pins and the spares."""
    read = set(input_bits(obs, "uio"))
    dead = [b for b in range(8) if b not in read]
    return "&{%s, 1'b0}" % ", ".join("uio_in[%s]" % r
                                     for r in bit_ranges(dead))


# ------------------------------------------------------------- core edits

def core_edits(obs, regions):
    sel = regions["select"]["select_bits"]
    n_arms = len(regions["select"].get("arms", [])) or 3
    del n_arms
    e = []
    e.append(Edit(
        "C01", "the header describes three arms, not two",
        "// Serial RO-PUF measurement core, dual-arm version (v2).\n"
        "// Arm A (oscillators 0..N_RO/2-1) is generated here as ro_macro"
        " instances and\n"
        "// auto-placed by the flow. Arm B (oscillators N_RO/2..N_RO-1) lives"
        " OUTSIDE\n"
        "// this module: the top level instantiates the hardened ro_macro_hard"
        " macros\n"
        "// flat (so their instance names match the MACROS placement keys in\n"
        "// config.json) and connects them through the armb_en / armb_out"
        " buses.\n",
        "// Serial RO-PUF measurement core, three-arm version (v3).\n"
        "//\n"
        "// Produced by chip/gen_e2_rtl.py from the frozen two-arm design\n"
        "// in dualarm/build_2arm_frozen/dualarm_src/ by named edits. The\n"
        "// transformation is one-shot, so this file is the design now:\n"
        "// change it here and say why in the day's writeup.\n"
        "//\n"
        "// Arm A (oscillators 0..N_A-1) is generated here as ro_macro\n"
        "// instances and auto-placed by the flow. Arm C (2*N_A..3*N_A-1) is\n"
        "// generated here too, as ro_armc, the same ring under its own name\n"
        "// so that the placement constraints in chip/armc_place.tcl can hold\n"
        "// it to equalized regions. Arm B (N_A..2*N_A-1) lives OUTSIDE this\n"
        "// module: the top level instantiates the hardened ro_macro_hard\n"
        "// macros flat (so their instance names match the MACROS placement\n"
        "// keys in config.json) and connects them through the armb_en /\n"
        "// armb_out buses.\n"))
    e.append(Edit(
        "C02", "the defaults have to divide by three",
        "    parameter integer N_RO  = 8,\n"
        "    parameter integer SEL_W = 3,\n",
        "    parameter integer N_RO  = 12,\n"
        "    parameter integer SEL_W = 4,\n"))
    e.append(Edit(
        "C03", "an arm is a third of the oscillators, and two flags come out",
        "    output wire [N_RO/2-1:0]    armb_en,   // per-oscillator enables"
        " for Arm B\n"
        "    input  wire [N_RO/2-1:0]    armb_out,  // Arm B oscillator"
        " outputs\n"
        "    output reg                  done,\n"
        "    output wire [CNT_W-1:0]     count_out\n"
        ");\n"
        "    localparam integer N_A            = N_RO / 2;\n",
        "    output wire [N_RO/3-1:0]    armb_en,   // per-oscillator enables"
        " for Arm B\n"
        "    input  wire [N_RO/3-1:0]    armb_out,  // Arm B oscillator"
        " outputs\n"
        "    output reg                  done,\n"
        "    output wire                 active,    // the window is open\n"
        "    output reg                  overflow,  // sticky: a run wrapped"
        " the counter\n"
        "    output wire [CNT_W-1:0]     count_out\n"
        ");\n"
        "    localparam integer N_A            = N_RO / 3;\n"
        "    localparam integer N_SLOT         = 1 << SEL_W;\n"))
    e.append(Edit(
        "C04", "the sampler carries the wrap flag alongside the count",
        "    (* async_reg = \"true\" *) reg [CNT_W-1:0] cnt_meta;\n"
        "    (* async_reg = \"true\" *) reg [CNT_W-1:0] cnt_sync;\n"
        "    reg [CNT_W-1:0] cnt_sync_prev;\n",
        "    // One bit wider than the counter. Bit CNT_W is the ring-domain\n"
        "    // wrap flag, so a wrap crosses into xclk through the same two\n"
        "    // async_reg stages and the same stable-sample rule as the count,\n"
        "    // rather than through a path of its own.\n"
        "    (* async_reg = \"true\" *) reg [CNT_W:0] cnt_meta;\n"
        "    (* async_reg = \"true\" *) reg [CNT_W:0] cnt_sync;\n"
        "    reg [CNT_W:0]   cnt_sync_prev;\n"))
    e.append(Edit(
        "C05", "the oscillator vector is one slot per select code",
        "    wire [N_RO-1:0] ro_out;\n",
        "    wire [N_SLOT-1:0] ro_out;\n"))
    e.append(Edit(
        "C06", "Arm C's bank, the empty slots, and the active flag",
        "    endgenerate\n"
        "\n"
        "    wire sel_ro = ro_out[active_sel];\n",
        "    endgenerate\n"
        "\n"
        "    // Arm C: the same ring as Arm A, under its own module name so\n"
        "    // synthesis cannot share cells between the arms, placed inside\n"
        "    // the equalized regions chip/armc_place.tcl declares. The select\n"
        "    // constant goes through a localparam the way Arm B's does,\n"
        "    // because a part-select applies to a name and never to a\n"
        "    // parenthesised expression.\n"
        "    generate\n"
        "        for (i = 0; i < N_A; i = i + 1) begin : g_armc\n"
        "            localparam integer SC = 2 * N_A + i;\n"
        "            ro_armc #(.IDX(i)) u_roc (\n"
        "                .en (en_window & (active_sel == SC[SEL_W-1:0])),\n"
        "                .out(ro_out[2*N_A+i])\n"
        "            );\n"
        "        end\n"
        "    endgenerate\n"
        "\n"
        "    // Two arm bits name four arms and there are three, so active_sel\n"
        "    // can point at a slot no oscillator fills. Those slots are tied\n"
        "    // low here rather than left off the vector, which keeps the\n"
        "    // selection below a plain index with no gate in front of it.\n"
        "    generate\n"
        "        for (i = N_RO; i < N_SLOT; i = i + 1) begin : g_no_arm\n"
        "            assign ro_out[i] = 1'b0;\n"
        "        end\n"
        "    endgenerate\n"
        "\n"
        "    // The measurement-active flag is the window enable brought out,\n"
        "    // not a second timer that could disagree with it.\n"
        "    assign active = en_window;\n"
        "\n"
        "    wire sel_ro = ro_out[active_sel];\n"))
    e.append(Edit(
        "C07", "a set-only wrap flag in the ring domain",
        "            assign tff_clk[b+1] = ~q;   // Q-bar clocks the next"
        " stage\n"
        "        end\n"
        "    endgenerate\n",
        "            assign tff_clk[b+1] = ~q;   // Q-bar clocks the next"
        " stage\n"
        "        end\n"
        "    endgenerate\n"
        "\n"
        "    // Wrap flag, in the ring domain. tff_clk[CNT_W] is the top bit's\n"
        "    // Q-bar, so its rising edge is the counter rolling over. The\n"
        "    // flop only ever sets and its D is tied high, so there is no\n"
        "    // data edge for the ring clock to catch. cnt_rst_n clears it\n"
        "    // with the counter at the start of each measurement, which is\n"
        "    // also why the falling edge the counter's own clear produces on\n"
        "    // tff_clk[CNT_W] cannot set it: the clear is asserted first and\n"
        "    // is held for the whole of ST_ARM.\n"
        "    //\n"
        "    // Set-only and not a seventeenth toggle bit, deliberately. The\n"
        "    // overflow window wraps once at the slow corner and four times\n"
        "    // at the fast one, and a toggle would read back as no wrap at\n"
        "    // all on a fast die.\n"
        "    reg wrapped;\n"
        "    always @(posedge tff_clk[CNT_W] or negedge cnt_rst_n)\n"
        "        if (!cnt_rst_n) wrapped <= 1'b0;\n"
        "        else            wrapped <= 1'b1;\n"))
    e.append(Edit(
        "C08", "reset clears the wider sampler and the sticky flag",
        "            cnt_meta      <= {CNT_W{1'b0}};\n"
        "            cnt_sync      <= {CNT_W{1'b0}};\n"
        "            cnt_sync_prev <= {CNT_W{1'b0}};\n"
        "            done         <= 1'b0;\n",
        "            cnt_meta      <= {(CNT_W+1){1'b0}};\n"
        "            cnt_sync      <= {(CNT_W+1){1'b0}};\n"
        "            cnt_sync_prev <= {(CNT_W+1){1'b0}};\n"
        "            done         <= 1'b0;\n"
        "            overflow     <= 1'b0;\n"))
    e.append(Edit(
        "C09", "the sampler takes the wrap flag with the count",
        "            cnt_meta <= cnt;\n",
        "            cnt_meta <= {wrapped, cnt};\n"))
    e.append(Edit(
        "C10", "a start clears the wider previous-sample register",
        "                cnt_sync_prev  <= {CNT_W{1'b0}};\n"
        "                count_latched  <= {CNT_W{1'b0}};\n",
        "                cnt_sync_prev  <= {(CNT_W+1){1'b0}};\n"
        "                count_latched  <= {CNT_W{1'b0}};\n"))
    e.append(Edit(
        "C11", "the latch splits the count from the wrap flag",
        "                            count_latched  <= cnt_sync;\n"
        "                            done           <= 1'b1;\n",
        "                            count_latched  <= cnt_sync[CNT_W-1:0];\n"
        "                            if (cnt_sync[CNT_W])\n"
        "                                overflow   <= 1'b1;\n"
        "                            done           <= 1'b1;\n"))
    del sel
    return e


# -------------------------------------------------------------- puf edits

def puf_edits(obs, regions):
    sel = regions["select"]["select_bits"]
    arms = regions["select"]["arm_bits"]
    e = []
    e.append(Edit(
        "P01", "the header describes three arms",
        "// Two-arm RO-PUF top, dual-arm version (v2). 32 oscillators, 16 per"
        " arm,\n"
        "// measured by one shared core. Arm A is auto-placed by the flow;"
        " Arm B is 16\n"
        "// bit-identical hardened macros instantiated at the TinyTapeout top"
        " level and\n"
        "// wired through here via armb_en / armb_out. `arm` selects the arm"
        " and\n"
        "// `ro_idx` the oscillator within it.\n",
        "// Three-arm RO-PUF top, version v3. %d oscillators, %d per arm,\n"
        "// measured by one shared core. Arm A is auto-placed by the flow;\n"
        "// Arm B is 16 bit-identical hardened macros instantiated at the\n"
        "// TinyTapeout top level and wired through here via armb_en /\n"
        "// armb_out; Arm C is auto-placed under the equalization\n"
        "// constraints. `arm` selects the arm and `ro_idx` the oscillator\n"
        "// within it.\n"
        "//\n"
        "// Produced by chip/gen_e2_rtl.py from the frozen two-arm design\n"
        "// in dualarm/build_2arm_frozen/dualarm_src/ro_puf.v.\n"
        % (3 * N_PER_ARM, N_PER_ARM)))
    e.append(Edit(
        "P02", "two arm bits, three arms, and the two new flags",
        "    input  wire                 arm,        // 0 = Arm A, 1 = Arm B\n"
        "    input  wire [3:0]           ro_idx,     // oscillator within the"
        " arm, 0..15\n"
        "    input  wire [CNT_W-1:0]     window,\n"
        "    output wire [N_PER_ARM-1:0] armb_en,\n"
        "    input  wire [N_PER_ARM-1:0] armb_out,\n"
        "    output wire                 done,\n"
        "    output wire [CNT_W-1:0]     count_out\n"
        ");\n"
        "    localparam integer N_RO  = 2 * N_PER_ARM;\n"
        "    localparam integer SEL_W = 5;\n",
        "    input  wire [%d:0]           arm,        // 0 = A, 1 = B, 2 = C\n"
        "    input  wire [3:0]           ro_idx,     // oscillator within the"
        " arm, 0..15\n"
        "    input  wire [CNT_W-1:0]     window,\n"
        "    output wire [N_PER_ARM-1:0] armb_en,\n"
        "    input  wire [N_PER_ARM-1:0] armb_out,\n"
        "    output wire                 done,\n"
        "    output wire                 active,\n"
        "    output wire                 overflow,\n"
        "    output wire [CNT_W-1:0]     count_out\n"
        ");\n"
        "    localparam integer N_RO  = 3 * N_PER_ARM;\n"
        "    localparam integer SEL_W = %d;\n" % (arms - 1, sel)))
    e.append(Edit(
        "P03", "the flags pass through to the core",
        "        .done     (done),\n"
        "        .count_out(count_out)\n",
        "        .done     (done),\n"
        "        .active   (active),\n"
        "        .overflow (overflow),\n"
        "        .count_out(count_out)\n"))
    del obs
    return e


# -------------------------------------------------------------- top edits

def bit_named(obs, pos, needle):
    """Where a pin the spec names by hand lands in the synchronized bundle."""
    hits = [p for p in obs["pin_map"] if needle in p["name"]]
    if len(hits) != 1:
        raise AnchorError("the pin map has %d pins matching %r, wanted 1"
                          % (len(hits), needle))
    p = hits[0]
    return pos[(p["port"], p["bit"])]


def slice_named(obs, pos, needles):
    """A contiguous slice of the bundle, given the pins in bit order."""
    idx = [bit_named(obs, pos, n) for n in needles]
    for a, b in zip(idx, idx[1:]):
        if b != a + 1:
            raise AnchorError("%s do not land next to each other in the "
                              "bundle: %s" % (", ".join(needles), idx))
    return idx[-1], idx[0]


def top_edits(obs, regions):
    bundle, pos, width = sync_bundle(obs)
    wins = window_constants(obs)
    start_b = bit_named(obs, pos, "start")
    arm0_b = bit_named(obs, pos, "arm select bit 0")
    arm1_b = bit_named(obs, pos, "arm select bit 1")
    byte_b = bit_named(obs, pos, "readout byte select")
    ver_b = bit_named(obs, pos, "read version")
    idx_hi, idx_lo = slice_named(obs, pos, ["ro_idx[%d]" % i
                                            for i in range(4)])
    win_hi, win_lo = slice_named(obs, pos, ["window select bit 0",
                                            "window select bit 1"])
    e = []
    e.append(Edit(
        "T01", "the header and the pin map are the spec's, not a copy",
        "// TinyTapeout top level for the two-arm RO-PUF, dual-arm version"
        " (v2).\n",
        "// TinyTapeout top level for the three-arm RO-PUF, version v3.\n"
        "//\n"
        "// Produced by chip/gen_e2_rtl.py from the frozen two-arm design\n"
        "// in dualarm/build_2arm_frozen/dualarm_src/tt_um_ro_puf.v and\n"
        "// chip/OBSERVABILITY.json.\n"))
    e.append(Edit(
        "T02", "the pin map comes out of the spec",
        "// Pin map (unchanged from v1):\n"
        "//   clk           measurement reference clock\n"
        "//   rst_n         active-low reset\n"
        "//   ui_in[0]      start, hold high for at least three clk cycles\n"
        "//   ui_in[1]      arm select (0 = Arm A auto-placed, 1 = Arm B"
        " hardened)\n"
        "//   ui_in[5:2]    ro_idx, oscillator within the arm (0..15)\n"
        "//   ui_in[6]      byte select for readout (0 = low byte, 1 = high"
        " byte)\n"
        "//   uo_out[7:0]   selected byte of the 16-bit count\n"
        "//   uio_out[0]    done, high when the count is valid (uio_oe ="
        " 0x01)\n",
        "// Pin map, straight out of chip/OBSERVABILITY.json:\n"
        + pin_map_comment(obs) + "\n"))
    e.append(Edit(
        "T03", "four window lengths chosen by a pin, and the version bytes",
        "    localparam [15:0] WINDOW = 16'd1000;\n",
        "    // The four preregistered window lengths, in xclk cycles. The\n"
        "    // first three are safe at every corner; the last overflows the\n"
        "    // counter at every corner on purpose, so the sticky flag can be\n"
        "    // exercised on any die. E.2 chose these, not this file. The\n"
        "    // multiplexer that picks between them sits below the select\n"
        "    // bits it reads.\n"
        + "".join("    localparam [15:0] WIN%d = 16'd%d;\n" % (i, w)
                  for i, w in enumerate(wins))
        + "\n"
        "    localparam [7:0] PROTOCOL_VERSION = 8'd%d;\n"
        "    localparam [7:0] BUILD_ID         = 8'h%02X;\n"
        % (obs["protocol_version"], obs["build_id"])))
    e.append(Edit(
        "T04", "the four new control pins are asynchronous too",
        "    // The board GPIOs are asynchronous to clk. Synchronize the"
        " complete\n"
        "    // control bundle, then edge-detect start in the synchronized"
        " domain. The\n",
        "    // The board GPIOs are asynchronous to clk. Synchronize the"
        " complete\n"
        "    // control bundle, then edge-detect start in the synchronized"
        " domain.\n"
        "    // E.2 put four more control signals on pins - the second arm"
        " bit, the\n"
        "    // two window select bits and the version select - and they are"
        " no less\n"
        "    // asynchronous than the rest, so they go through the same two"
        " stages\n"
        "    // rather than being read raw. ui_in keeps the low eight bits of"
        " the\n"
        "    // bundle so every existing decode stays where it was. The\n"))
    win_case = "".join("            2'd%d:    window = WIN%d;\n" % (i, i)
                       for i in range(len(wins) - 1))
    win_case += "            default: window = WIN%d;\n" % (len(wins) - 1)
    e.append(Edit(
        "T05", "the synchronizer widens to carry the whole control bundle",
        "    (* async_reg = \"true\" *) reg [6:0] ui_meta;\n"
        "    (* async_reg = \"true\" *) reg [6:0] ui_sync;\n"
        "    reg start_sync_d;\n"
        "\n"
        "    always @(posedge clk or negedge project_rst_n) begin\n"
        "        if (!project_rst_n) begin\n"
        "            ui_meta      <= 7'b0;\n"
        "            ui_sync      <= 7'b0;\n"
        "            start_sync_d <= 1'b0;\n"
        "        end else begin\n"
        "            ui_meta      <= ui_in[6:0];\n"
        "            ui_sync      <= ui_meta;\n"
        "            start_sync_d <= ui_sync[0];\n"
        "        end\n"
        "    end\n"
        "\n"
        "    wire       start_pulse = ui_sync[0] & ~start_sync_d;\n"
        "    wire       arm         = ui_sync[1];\n"
        "    wire [3:0] ro_idx      = ui_sync[5:2];\n"
        "    wire       byte_sel    = ui_sync[6];\n",
        ("    (* async_reg = \"true\" *) reg [%d:0] ui_meta;\n"
         "    (* async_reg = \"true\" *) reg [%d:0] ui_sync;\n"
         "    reg start_sync_d;\n"
         "\n"
         "    always @(posedge clk or negedge project_rst_n) begin\n"
         "        if (!project_rst_n) begin\n"
         "            ui_meta      <= %d'b0;\n"
         "            ui_sync      <= %d'b0;\n"
         "            start_sync_d <= 1'b0;\n"
         "        end else begin\n"
         "            ui_meta      <= {%s};\n"
         "            ui_sync      <= ui_meta;\n"
         "            start_sync_d <= ui_sync[%d];\n"
         "        end\n"
         "    end\n"
         "\n"
         "    wire       start_pulse = ui_sync[%d] & ~start_sync_d;\n"
         "    wire [1:0] arm         = {ui_sync[%d], ui_sync[%d]};\n"
         "    wire [3:0] ro_idx      = ui_sync[%d:%d];\n"
         "    wire       byte_sel    = ui_sync[%d];\n"
         "    wire [1:0] win_sel     = ui_sync[%d:%d];\n"
         "    wire       rd_ver      = ui_sync[%d];\n"
         % (width - 1, width - 1, width, width, bundle, start_b, start_b,
            arm1_b, arm0_b, idx_hi, idx_lo, byte_b, win_hi, win_lo, ver_b))
        + "\n"
        "    // The window is one of the four lengths above, picked by the\n"
        "    // two synchronized select bits. It sits here, under the wires\n"
        "    // it reads, rather than up beside the constants.\n"
        "    reg [15:0] window;\n"
        "    always @(*) begin\n"
        "        case (win_sel)\n"
        + win_case
        + "        endcase\n"
        "    end\n"))
    e.append(Edit(
        "T06", "the two new flags are declared",
        "    wire        done;\n"
        "    wire [15:0] count;\n",
        "    wire        done;\n"
        "    wire        active;\n"
        "    wire        overflow;\n"
        "    wire [15:0] count;\n"))
    e.append(Edit(
        "T07", "the window is chosen by a pin now, not fixed at 1000",
        "        .window   (WINDOW),\n",
        "        .window   (window),\n"))
    e.append(Edit(
        "T08", "the flags come back out of the core",
        "        .done     (done),\n"
        "        .count_out(count)\n",
        "        .done     (done),\n"
        "        .active   (active),\n"
        "        .overflow (overflow),\n"
        "        .count_out(count)\n"))
    e.append(Edit(
        "T09", "the readout carries a version byte and two more flags",
        "    assign uo_out  = byte_sel ? count[15:8] : count[7:0];\n"
        "    assign uio_out = {7'b0, done};\n"
        "    assign uio_oe  = 8'b0000_0001;        // only uio[0] is an"
        " output\n",
        "    // The version bytes read out through the same port as the"
        " count,\n"
        "    // selected by a pin, so a board can identify the design without"
        " a\n"
        "    // second readout path. byte_sel picks the half in both modes.\n"
        "    wire [7:0] count_byte = byte_sel ? count[15:8] : count[7:0];\n"
        "    wire [7:0] ver_byte   = byte_sel ? BUILD_ID : PROTOCOL_VERSION;\n"
        "    assign uo_out  = rd_ver ? ver_byte : count_byte;\n"
        "    assign uio_out = %s;\n"
        "    assign uio_oe  = 8'h%02X;             // uio[%s] drive\n"
        % (uio_out_concat(obs, {0: "done", 4: "overflow", 5: "active"}),
           obs["uio_oe"],
           "], uio[".join(str(b) for b in output_bits(obs, "uio")))))
    e.append(Edit(
        "T10", "ui_in[7] has a job now and three uio_in bits do not",
        "    wire _unused = &{uio_in, ui_in[7], 1'b0};\n",
        "    wire _unused = %s;\n" % unused_concat(obs)))
    del regions
    return e


def all_edits(obs, regions):
    return collections.OrderedDict([
        ("ro_puf_core.v", core_edits(obs, regions)),
        ("ro_puf.v", puf_edits(obs, regions)),
        ("tt_um_ro_puf.v", top_edits(obs, regions)),
    ])


# ---------------------------------------------------- a little Verilog

MODULE_RE = re.compile(r"^\s*module\s+(\w+)\s*(?:#\s*\(.*?\)\s*)?\((.*?)\)\s*;",
                       re.S | re.M)
PORT_DECL_RE = re.compile(
    r"^\s*(input|output|inout)\s+(?:wire\s+|reg\s+)?"
    r"(?:\[\s*([^\]]+?)\s*\]\s*)?(\w+)\s*[,;]", re.M)
REG_DECL_RE = re.compile(r"^\s*reg\s+(?:\[[^\]]+\]\s*)?(\w+)", re.M)
ALWAYS_RE = re.compile(r"always\s*@\s*\(([^)]*)\)")


def clocked_blocks(body):
    """(sensitivity, text) for every clocked always block in a module body.

    A block runs from its own `always @` to the next one, or to the end of
    the module. Combinational blocks are skipped: the window mux is an
    `always @(*)` writing a reg, and a reset on it would mean nothing.
    """
    hits = list(ALWAYS_RE.finditer(body))
    out = []
    for i, mo in enumerate(hits):
        stop = hits[i + 1].start() if i + 1 < len(hits) else len(body)
        if "posedge" not in mo.group(1):
            continue
        out.append((mo.group(1), body[mo.end():stop]))
    return out


def parse_modules(text):
    """Module names, their port lists and their declared registers.

    Deliberately small. It reads one dialect, the one this project writes,
    and a parser that accepts less is a parser that catches more.
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
        out[name] = {"ports": ports, "regs": sorted(set(
            REG_DECL_RE.findall(body))), "body": body}
    return out


def pin_uses(text, port, bits):
    """How many times each bit of a packed port is named.

    A bit counts when it appears on its own, `ui_in[6]`, and also when it
    falls inside a slice, `ui_in[5:2]`. Counting only the first form would
    call the four ro_idx bits unread, because the top takes them as one
    slice, and a check that is wrong about the design it reads is worse than
    no check.
    """
    seen = collections.Counter()
    for b in range(bits):
        seen[b] = len(re.findall(r"\b%s\[%d\]" % (port, b), text))
    for hi, lo in re.findall(r"\b%s\[\s*(\d+)\s*:\s*(\d+)\s*\]" % port, text):
        for b in range(int(lo), int(hi) + 1):
            if 0 <= b < bits:
                seen[b] += 1
    return seen


def reset_branch(code):
    """The body of `if (!rst_n) begin` up to its `end else begin`."""
    i = code.find("if (!rst_n) begin")
    if i < 0:
        return ""
    j = code.find("\n        end else begin", i)
    return code[i:j] if j > 0 else code[i:]


def sampler_rhs(code):
    """What the first synchronizer stage in the top samples.

    Found by name rather than by position: the top has three async_reg
    registers and the first of them is the reset synchronizer, not this one.
    Every right-hand side assigned to a candidate is taken together, because
    one of them is the reset value and reading only the first would call the
    whole bundle unsynchronized.
    """
    names = re.findall(r'async_reg\s*=\s*"true"\s*\*\)\s*reg'
                       r'\s*(?:\[[^\]]*\])?\s*(\w+)', code)
    for n in names:
        rhs = re.findall(r"\b%s\s*<=\s*([^;]+);" % n, code)
        if any("ui_in" in r for r in rhs):
            return " ".join(r.strip() for r in rhs)
    return ""


# ---------------------------------------------------------- the stimulus

def gen_tb_plan(obs):
    """Stimulus for every acceptance test, derived from the table rather than
    written out, so a test cannot exist without a vector or a vector without
    a test."""
    wins = window_constants(obs)
    sel = dict((w, i) for i, w in enumerate(wins))
    rows = [("id", "kind", "arm", "ro_idx", "sweep", "win_sel", "rd_ver",
             "byte_sel", "reset_first", "expect")]
    for t in obs["tests"]:
        blob = "%s %s" % (t.get("setup", ""), t.get("expect", ""))
        arm = 0
        for label, n in (("arm A", 0), ("arm B", 1), ("arm C", 2)):
            if label in blob:
                arm = n
        m = re.search(r"arm\s*=\s*(\d)", blob)
        if m:
            arm = int(m.group(1))
        sweep = 1 if "0..15" in blob else 0
        m = re.search(r"ro_idx\s*=\s*(\d+)", blob)
        idx = int(m.group(1)) if m else 0
        rows.append((t["id"], t["kind"], arm, idx, sweep,
                     sel.get(t.get("window"), 0),
                     1 if t["kind"] == "version" else 0,
                     1 if ("ui[6]=1" in blob or "high byte" in blob
                           or "BUILD" in blob or "0x1A" in blob) else 0,
                     1 if t["kind"] == "reset" else 0,
                     t["expect"]))
    return rows


# ---------------------------------------------------------------- checks

# Lines the live design earned and that no edit is allowed to take away.
# Every one of them is a decision with an argument behind it: the ungated
# counter clock has a SPICE phase sweep, the settle handshake is why a torn
# word is never published, cnt_rst_n is why each measurement starts clean,
# and ena in the asynchronous reset is why deselection stops an oscillator
# when the reference clock has stopped.
SURVIVORS = {
    "e2_ro_puf_core.v": [
        "    assign tff_clk[0] = sel_ro;",
        "    // revision put `sel_ro & en_window` here, but en_window belongs"
        " to the",
        "    wire cnt_rst_n = rst_n & ~start;        // clear before each"
        " measurement",
        "    assign count_out = count_latched;",
        "                    end else if (cnt_sync == cnt_sync_prev) begin",
        "    localparam [1:0] REQUIRED_STABLE_SAMPLES = 2'd3;",
        "            ro_macro #(.IDX(i)) u_ro (",
    ],
    "e2_tt_um_ro_puf.v": [
        "    wire async_project_rst_n = rst_n & ena;",
        "    wire project_rst_n = reset_sync[1];",
    ],
}


def run_checks(obs, regions, emitted, tb_rows, counts, live, config):
    res = Results()

    bad = ["%s wanted %d, found %d" % (e.id, e.count, n)
           for e, n in counts if e.count != n]
    res.add("R14", "every edit matched its anchor the declared number of "
            "times", not bad, "; ".join(bad) or
            "%d edits, all anchored" % len(counts))
    if bad:
        res.add("R00", "the remaining checks were not reached", False,
                "an anchor missed, so nothing was transformed and nothing "
                "is emitted")
        return res

    text = "\n".join(emitted[k] for k in sorted(emitted))
    mods = parse_modules(text)

    res.add("R01", "the three modules the build installs are all emitted",
            set(MODULE_OF.values()) <= set(mods),
            "missing: %s" % (", ".join(sorted(set(MODULE_OF.values())
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

    # R03 is one property and not two. A pin read straight off the port and a
    # pin never read at all are the same bug from the design's point of view:
    # the value that reaches the core did not come through the synchronizer.
    rhs = sampler_rhs(top["body"])
    ui_seen = pin_uses(rhs, "ui_in", 8)
    uio_seen = pin_uses(rhs, "uio_in", 8)
    missing = []
    for p in obs["pin_map"]:
        if p["direction"] != "in" or p["owner"] == "spare":
            continue
        seen = ui_seen if p["port"] == "ui" else uio_seen
        if not seen[p["bit"]]:
            missing.append("%s_in[%d] %s" % (p["port"], p["bit"], p["name"]))
    res.add("R03", "every input pin with a job goes through the "
            "synchronizer", rhs and not missing,
            "not synchronized: %s" % "; ".join(missing) if missing
            else "bundle is %s" % rhs)

    oe = re.search(r"assign uio_oe\s*=\s*8'h([0-9A-Fa-f]{2})", top["body"])
    res.add("R04", "uio_oe in the RTL is the value the spec derived",
            oe is not None and int(oe.group(1), 16) == obs["uio_oe"],
            "RTL %s, spec 0x%02X" % (oe.group(1) if oe else "absent",
                                     obs["uio_oe"]))

    wins = window_constants(obs)
    found = [int(x) for x in re.findall(
        r"localparam \[15:0\] WIN\d+ = 16'd(\d+);", top["body"])]
    res.add("R05", "the window constants are the spec's four, in order",
            found == wins, "%s against %s" % (found, wins))

    sel_bits = regions["select"]["select_bits"]
    m = re.search(r"localparam integer SEL_W = (\d+);", text)
    res.add("R06", "the select width is the one the arm count needs",
            m is not None and int(m.group(1)) == sel_bits,
            "RTL %s, needed %d" % (m.group(1) if m else "absent", sel_bits))

    unreset = []
    for name, mod in mods.items():
        blocks = clocked_blocks(mod["body"])
        for r in mod["regs"]:
            for sens, btext in blocks:
                if not re.search(r"\b%s\s*<=" % r, btext):
                    continue
                if not re.search(r"negedge\s+(\w*rst_n)", sens):
                    unreset.append("%s.%s" % (name, r))
                break
    res.add("R07", "every register a clocked block writes has a reset",
            not unreset, ", ".join(sorted(set(unreset))) or "none")

    core = mods.get("ro_puf_core", {"body": ""})["body"]
    sets = core.count("overflow   <= 1'b1;") + core.count("overflow <= 1'b1;")
    clears = core.count("overflow     <= 1'b0;") + \
        core.count("overflow <= 1'b0;") + core.count("overflow   <= 1'b0;")
    in_reset = "overflow" in reset_branch(core)
    res.add("R08", "the sticky flag is set at the latch and cleared only by "
            "reset", sets == 1 and clears == 1 and in_reset,
            "set %d, cleared %d, %sin the reset branch"
            % (sets, clears, "" if in_reset else "NOT "))

    res.add("R09", "active is the window enable and not a second timer",
            "assign active = en_window;" in core,
            "present" if "assign active = en_window;" in core else "absent")

    banks = sorted(re.findall(r"begin : (g_ro_bank|g_armb|g_armc)\b", core))
    res.add("R10", "three arms are generated, one bank each",
            banks == ["g_armb", "g_armc", "g_ro_bank"]
            and "localparam integer N_RO  = 3 * N_PER_ARM;" in text,
            "banks %s" % (", ".join(banks) or "none"))

    ids = [r[0] for r in tb_rows[1:]]
    want = [t["id"] for t in obs["tests"]]
    res.add("R11", "every acceptance test has exactly one stimulus row",
            sorted(ids) == sorted(want) and len(ids) == len(set(ids)),
            "%d rows, %d tests" % (len(ids), len(want)))

    used_w = set(int(r[5]) for r in tb_rows[1:])
    used_a = set(int(r[2]) for r in tb_rows[1:])
    res.add("R12", "the stimulus reaches every window and every arm",
            used_w >= set(range(len(wins))) and used_a >= {0, 1, 2},
            "windows %s, arms %s" % (sorted(used_w), sorted(used_a)))

    res.add("R13", "no emitted path reaches into a source tree",
            all(not k.startswith("/") and "src" not in k for k in emitted),
            ", ".join(sorted(emitted)))

    lost = []
    for fname, lines in SURVIVORS.items():
        for ln in lines:
            if ln not in emitted.get(fname, ""):
                lost.append("%s: %s" % (fname, ln.strip()[:52]))
    kept = sum(1 for f in SOURCES.values() for ln in
               live[[k for k, v in SOURCES.items() if v == f][0]].split("\n")
               if ln.strip() and ln in emitted.get(f, ""))
    res.add("R15", "the lines the live design earned survive verbatim",
            not lost, "; ".join(lost) if lost
            else "%d anchors held, %d live lines came through unchanged"
            % (sum(len(v) for v in SURVIVORS.values()), kept))

    want_m = sorted(config.get("MACROS", {}).get("ro_macro_hard", {})
                    .get("instances", {}).keys())
    have = set(re.findall(r"\bro_macro_hard\s+(\w+)\s*\(",
                          emitted.get("e2_tt_um_ro_puf.v", "")))
    gone = [w for w in want_m if w not in have]
    res.add("R16", "every Arm B macro instance in config.json survives in "
            "the top", bool(want_m) and not gone,
            "%d of %d present%s" % (len(want_m) - len(gone), len(want_m),
                                    ", missing " + ", ".join(gone[:4])
                                    if gone else ""))
    return res


# ----------------------------------------------------------------- build

def source_dir():
    """Where the untransformed two-arm design is.

    Before G.3 step 2 that is dualarm/src. Step 2 copies the emitted modules
    over it, and from that moment the live tree IS the three-arm design and
    this transformation has no input left. The plan written on 31 August
    dealt with that by retiring this script from the gate along with the
    drafts it diffs, which would have thrown away the checks, the control
    and the sixteen planted faults on the day they stopped being
    hypothetical.

    Step 1 freezes the two-arm sources first, so there is a better answer:
    read them from the archive, and let the gate diff the emitted modules
    against what is installed in dualarm/src. That is a stronger claim than
    the draft diff made. It says the design going to the chip is exactly
    what transforming the recorded two-arm design produces, and it says it
    again every time CI runs.
    """
    if os.path.isdir(FROZEN_DIR):
        probe = os.path.join(LIVE_DIR, "ro_puf_core.v")
        if os.path.exists(probe):
            with open(probe, "r", encoding="utf-8") as fh:
                if "begin : g_armc" in fh.read():
                    return FROZEN_DIR
    return LIVE_DIR


def read_live(dirpath=None):
    """The live design, with line endings normalised.

    dualarm/src carries a mix: ro_puf_core.v is LF, ro_puf.v is CRLF and
    tt_um_ro_puf.v has both. Text mode folds all of them to \\n on the way in
    and the emitter writes \\n on the way out, so the emitted files are the
    same bytes on any machine and the gate's diff means something.
    """
    d = dirpath or source_dir()
    out = collections.OrderedDict()
    for n in SOURCES:
        p = os.path.join(d, n)
        if not os.path.exists(p):
            raise SystemExit("missing live source: %s" % p)
        with open(p, "r", encoding="utf-8") as fh:
            out[n] = fh.read()
    return out


def read_config(dirpath=None):
    p = os.path.join(dirpath or source_dir(), "config.json")
    if not os.path.exists(p):
        return {}
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def already_installed(live):
    """Has the live design already had these edits installed over it?

    The transformation is one-shot by construction. G.3 step 2 copies the
    emitted modules over `dualarm/src/`, and from that moment the live design
    IS the three-arm design, so every anchor here refers to text that no
    longer exists. Sixteen anchor misses is a true report and a useless one,
    so say the useful thing instead: this script has done its job and its
    four commands in the archived-evidence job come out of the gate at the
    same time as the install, along with the drafts they diff against.
    """
    return "begin : g_armc" in live.get("ro_puf_core.v", "")


def build_all(obs, regions, live, edits=None):
    """Transform, counting every anchor as it goes.

    An edit whose anchor does not match the number of times it declared is
    not applied at all, and R14 reports it. Half-applying a set of edits
    would leave RTL that is neither the live design nor the intended one,
    which is the worst of the three.
    """
    edits = edits if edits is not None else all_edits(obs, regions)
    emitted = collections.OrderedDict()
    counts = []
    for src, dst in SOURCES.items():
        text = live[src]
        for e in edits.get(src, []):
            n = text.count(e.old)
            counts.append((e, n))
            if n == e.count:
                text = text.replace(e.old, e.new)
        emitted[dst] = text
    return emitted, gen_tb_plan(obs), counts


def unified(live, emitted):
    out = []
    for src, dst in SOURCES.items():
        out.extend(difflib.unified_diff(
            live[src].split("\n"), emitted[dst].split("\n"),
            "dualarm/src/" + src, "chip/" + dst, n=2, lineterm=""))
    return "\n".join(out)


# -------------------------------------------------------------- selftest

def _live_sub(live, name, old, new, count=1):
    out = dict(live)
    if out[name].count(old) != count:
        raise AssertionError("fixture anchor appears %d times in %s, wanted "
                             "%d: %r" % (out[name].count(old), name, count,
                                         old[:60]))
    out[name] = out[name].replace(old, new)
    return out


def _edit_sub(edits, fname, eid, old, new):
    """Change one edit's replacement text. This is the realistic fault: the
    live design is fine and the generator writes the wrong thing."""
    out = dict((k, list(v)) for k, v in edits.items())
    for e in out[fname]:
        if e.id == eid:
            if e.new.count(old) != 1:
                raise AssertionError("%s replacement text has %d copies of "
                                     "%r" % (eid, e.new.count(old), old[:50]))
            e.new = e.new.replace(old, new)
            return out
    raise AssertionError("no edit %s in %s" % (eid, fname))


def _state(live, obs, regions, config, edits):
    return {"live": live, "obs": obs, "regions": regions, "config": config,
            "edits": edits, "post": []}


def _evaluate(st):
    emitted, tb, counts = build_all(st["obs"], st["regions"], st["live"],
                                    st["edits"])
    for fn in st["post"]:
        emitted, tb = fn(emitted, tb)
    return run_checks(st["obs"], st["regions"], emitted, tb, counts,
                      st["live"], st["config"])


def selftest():
    print("gen_e2_rtl selftest")
    ok = True
    live = read_live()
    config = read_config()
    with open(OBS_JSON, "r", encoding="utf-8") as fh:
        obs = json.load(fh)
    with open(REGIONS_JSON, "r", encoding="utf-8") as fh:
        regions = json.load(fh)

    base = _state(live, obs, regions, config, all_edits(obs, regions))
    res = _evaluate(base)
    if res.failed():
        print("  FAIL: the live design transformed cleanly fails %s"
              % ", ".join(res.failed()))
        for r in res.rows:
            if not r["pass"]:
                print("        %s %s" % (r["id"], r["detail"]))
        ok = False
    else:
        print("  the transformed live design passes all %d checks"
              % len(res.rows))

    # Control. With no edits at all the output is the live two-arm design,
    # and the checks that are about E.2 and Arm C have to fail on it. A check
    # that passes on the design it was written to reject is decorative.
    ctl = _state(live, obs, regions, config,
                 dict((k, []) for k in SOURCES))
    cres = _evaluate(ctl)
    want_fail = {"R03", "R04", "R05", "R06", "R08", "R09", "R10"}
    got_fail = set(cres.failed())
    if got_fail == want_fail:
        print("  ok    control  the untransformed live design fails exactly "
              "%s" % ", ".join(sorted(want_fail)))
    else:
        print("  FAIL  control  untransformed live design fails %s, wanted %s"
              % (", ".join(sorted(got_fail)) or "nothing",
                 ", ".join(sorted(want_fail))))
        ok = False

    def f_r01(st):
        st["live"] = _live_sub(st["live"], "ro_puf.v", "module ro_puf #(",
                               "module ro_puf_x #(")
        return st

    def f_r02(st):
        st["live"] = _live_sub(st["live"], "tt_um_ro_puf.v",
                               "    input  wire       ena,\n", "")
        return st

    def f_r03(st):
        st["edits"] = _edit_sub(st["edits"], "tt_um_ro_puf.v", "T05",
                                "{uio_in[3:1], ui_in[7:0]}",
                                "{3'b0, ui_in[7:0]}")
        return st

    def f_r04(st):
        st["edits"] = _edit_sub(st["edits"], "tt_um_ro_puf.v", "T09",
                                "8'h31", "8'h33")
        return st

    def f_r05(st):
        st["edits"] = _edit_sub(st["edits"], "tt_um_ro_puf.v", "T03",
                                "WIN2 = 16'd2048;", "WIN2 = 16'd4096;")
        return st

    def f_r06(st):
        st["edits"] = _edit_sub(st["edits"], "ro_puf.v", "P02",
                                "localparam integer SEL_W = 6;",
                                "localparam integer SEL_W = 5;")
        return st

    def f_r07(st):
        st["edits"] = _edit_sub(st["edits"], "tt_um_ro_puf.v", "T05",
                                "always @(posedge clk or negedge "
                                "project_rst_n) begin",
                                "always @(posedge clk) begin")
        return st

    def f_r08(st):
        st["edits"] = _edit_sub(st["edits"], "ro_puf_core.v", "C10",
                                "                cnt_sync_prev  <= "
                                "{(CNT_W+1){1'b0}};\n",
                                "                cnt_sync_prev  <= "
                                "{(CNT_W+1){1'b0}};\n"
                                "                overflow <= 1'b0;\n")
        return st

    def f_r09(st):
        st["edits"] = _edit_sub(st["edits"], "ro_puf_core.v", "C06",
                                "assign active = en_window;",
                                "assign active = 1'b0;")
        return st

    def f_r10(st):
        st["edits"] = _edit_sub(st["edits"], "ro_puf_core.v", "C06",
                                "begin : g_armc", "begin : g_spare")
        return st

    def f_r11(st):
        # Dropped by name, not by position. The last row is the only one that
        # exercises Arm C, so taking it off the end trips R12 as well and the
        # fault stops saying which check caught it.
        st["post"].append(lambda e, t: (
            e, [r for r in t if r[0] != "E2-15"]))
        return st

    def f_r12(st):
        st["post"].append(lambda e, t: (
            e, [t[0]] + [list(r[:5]) + [0] + list(r[6:]) for r in t[1:]]))
        return st

    def f_r13(st):
        st["post"].append(lambda e, t: (
            dict(e, **{"src/ro_puf.v": "// no"}), t))
        return st

    def f_r14(st):
        st["live"] = _live_sub(st["live"], "ro_puf_core.v",
                               "    wire sel_ro = ro_out[active_sel];",
                               "    wire sel_ro = ro_out[active_sel];  //")
        return st

    def f_r15(st):
        # An edit that reintroduces the AND gate the live core removed in
        # July. This is the fault of record: it is legal Verilog, it changes
        # no port, and only a check that knows the line is load-bearing can
        # see it.
        ed = dict((k, list(v)) for k, v in st["edits"].items())
        ed["ro_puf_core.v"].append(Edit(
            "CXX", "the July bug, put back",
            "    assign tff_clk[0] = sel_ro;\n",
            "    assign tff_clk[0] = sel_ro & en_window;\n"))
        st["edits"] = ed
        return st

    def f_r16(st):
        st["live"] = _live_sub(
            st["live"], "tt_um_ro_puf.v",
            "    ro_macro_hard u_rob7  (.en(armb_en[7]),  .out(armb_out[7]));"
            "\n", "")
        return st

    faults = [
        ("R01", "a module the build needs is not there under its name",
         f_r01),
        ("R02", "the top loses one of Tiny Tapeout's ports", f_r02),
        ("R03", "a control pin read raw instead of through the sampler",
         f_r03),
        ("R04", "uio_oe in the RTL disagrees with the spec", f_r04),
        ("R05", "a window constant the spec did not choose", f_r05),
        ("R06", "a select width too narrow for three arms", f_r06),
        ("R07", "a synchronizer whose reset went missing", f_r07),
        ("R08", "an overflow flag a start clears", f_r08),
        ("R09", "an active flag tied off instead of wired", f_r09),
        ("R10", "only two arms generated", f_r10),
        ("R11", "an acceptance test with no stimulus row", f_r11),
        ("R12", "stimulus that never selects three of the windows", f_r12),
        ("R13", "an emitted path that reaches into a source tree", f_r13),
        ("R14", "a live file that moved under an anchor", f_r14),
        ("R15", "an edit that puts the AND gate back on the counter clock",
         f_r15),
        ("R16", "an Arm B macro instance dropped from the top", f_r16),
    ]
    for want, label, fn in faults:
        st = fn(_state(live, obs, regions, config, all_edits(obs, regions)))
        tripped = set(_evaluate(st).failed()) - {"R00"}
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

    installed = dict(live)
    installed["ro_puf_core.v"] = build_all(
        obs, regions, live)[0]["e2_ro_puf_core.v"]
    if already_installed(live) or not already_installed(installed):
        print("  FAIL  one-shot  the already-installed guard is wrong: live "
              "%s, installed %s" % (already_installed(live),
                                    already_installed(installed)))
        ok = False
    else:
        print("  ok    one-shot the guard sees an installed source tree and "
              "not an untouched one")

    mods = parse_modules("module m (a, b);\n input wire a;\n"
                         " output reg [3:0] b;\n reg c;\n"
                         " always @(posedge a or negedge rst_n)\n"
                         "  if (!rst_n) c <= 1'b0; else c <= a;\n"
                         "endmodule\n")
    good = ("m" in mods and mods["m"]["ports"]["a"]["dir"] == "input"
            and mods["m"]["ports"]["b"]["width"] == "3:0"
            and "c" in mods["m"]["regs"])
    print("  %-5s parse  ports, widths and registers off a hand-written "
          "module" % ("ok" if good else "FAIL"))
    ok = ok and good

    print("\n  %s" % ("all faults isolated" if ok else "SELFTEST FAILED"))
    return 0 if ok else 1


# ---------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--emit", help="directory for the generated verilog")
    ap.add_argument("--csv", help="write the stimulus plan here")
    ap.add_argument("--diff", action="store_true",
                    help="print what the edits do to the live design")
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

    live = read_live()
    config = read_config()
    if already_installed(live):
        print("dualarm/src already carries the three-arm design and there "
              "is no frozen two-arm baseline to transform instead.")
        print("G.3 step 1 writes that archive and step 2 does the install. "
              "If it has been deleted, restore dualarm/build_2arm_frozen "
              "from git before running this.")
        return 3
    emitted, tb, counts = build_all(obs, regions, live)
    res = run_checks(obs, regions, emitted, tb, counts, live, config)

    print("E.2 and Arm C RTL, transformed from %s"
          % os.path.relpath(source_dir(), ROOT).replace(os.sep, "/"))
    print("  windows   %s cycles, select %d bits, %d oscillators"
          % (window_constants(obs), regions["select"]["select_bits"],
             regions["select"]["oscillators"]))
    print("  uio_oe    0x%02X, protocol %d, build 0x%02X"
          % (obs["uio_oe"], obs["protocol_version"], obs["build_id"]))
    edits = all_edits(obs, regions)
    for src, dst in SOURCES.items():
        print("  %-22s %4d lines from %4d, %2d edits"
              % (dst, len(emitted[dst].split("\n")),
                 len(live[src].split("\n")), len(edits[src])))
    print("  %-22s %4d rows" % ("e2_tb_plan.csv", len(tb) - 1))
    print()
    for r in res.rows:
        print("  %-4s %-60s %s" % (r["id"], r["name"],
                                   "pass" if r["pass"] else "FAIL"))
    bad = res.failed()
    print("\n  %s" % ("all %d checks pass" % len(res.rows) if not bad
                      else "FAILED: " + ", ".join(bad)))
    for r in res.rows:
        if not r["pass"]:
            print("       %s: %s" % (r["id"], r["detail"]))

    if a.diff:
        print()
        print(unified(live, emitted))

    if bad:
        if a.emit or a.csv:
            print("\n  nothing written: a generator that failed its own "
                  "checks must not leave RTL on disk for somebody to "
                  "install.")
        return 1

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
    return 0


if __name__ == "__main__":
    sys.exit(main())
