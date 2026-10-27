#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Where along a selector path the last pulse gives out.

The boundary screen of 26 October says which of four pulse widths each of
the 48 selector paths passes on to the counter, and nothing about where in
the chain a lost one is lost. Its table had a pattern in it. Four pairs of
Arm B paths run through the same cell types on the same pins except for
one, the o21ba_2, entered on A1 in one path of the pair and on A2 in the
other, and in all four pairs the A2 path needs a wider pulse, one or two
screened widths more. The data could not say whether the o21ba_2 is where
the difference happens.

This makes it say. --make takes a deck the screen ran and rewrites three
lines: every net of the chain is saved, not just the tap, sel_ro and q,
and the transient writes out only a window around the stop. The circuit
lines are not touched. Each rewrite has to match exactly once or nothing
is written, the rule gen_boundary_sweep.py keeps for the same reason.

It said no. On all four A2 paths the pulse is gone before it reaches the
o21ba_2, at the first cell on B00 and at the second on the other three.
The first cell of each drives a heavy net, _221_ at 27.09 fF on B00 and
B03 and _219_ at 17.98 on B12 and B15, where the A1 paths start on _216_
at 11.95 and _214_ at 4.01. The pin was only a label for which of those a
path starts on: _221_ and _219_ lie behind the o21ba_2's A2 input, _216_
and _214_ behind its A1.

Reading a run, each net gets the treatment analyze_boundary_sweep.py gives
sel_ro. A steady rise delay from the tap, measured on the cycles before
the stop. Then the last high at the tap, and whether a rising edge turns
up at that net one rise delay later. If it does, the width it arrives
with. If it does not, how high the net got while the pulse was trying,
which is the part a crossing count cannot show.

The window is the reduced form. --reduce keeps the rows around every
crossing at half the supply, every row from just before the last tap rise
to a nanosecond after it, and the last row, then reads both copies and
refuses to write unless every number comes out the same.

Checks over a read, each with a planted fault in --selftest that trips it
and nothing else:

  N01  every deck has a waveform for every net of its chain
  N02  every net has a steady rise delay, the chain's delays in order
  N03  a pulse lost at one net is not found again further down
  N04  sel_ro's verdict is the screen's for the same deck
  N05  the tap, sel_ro and q are the screen's on every row both kept

N04 reads the screen's csv and N05 its reduced waveforms. A probe that
disagreed with the screen about the nets they share would be measuring a
different circuit. A probe changes what is saved and when the output
starts, not the steps the solver takes, so the rows the two reductions
both kept carry the same numbers to the last printed digit, and N05 holds
them to that. It fails a deck with no rows in common rather than passing
it. A what-if deck, one whose loads were changed on purpose, is a
different circuit by design and has no screen row, so --no-screen reads
it with N04 and N05 reported as not run rather than passed.

Run:
    python3 bnd_nodes.py --make bnd3/screen_ff/B00/bnd_02.spice \\
        --out DIR/B00
    python3 bnd_nodes.py --reduce DIR --out bnd3/nodes_ff
    python3 bnd_nodes.py bnd3/nodes_ff --screen boundary_screen_ff.csv \\
        --screen-runs bnd3/screen_ff --csv bnd_nodes_ff.csv
    python3 bnd_nodes.py bnd3/nodes_whatif --no-screen \\
        --csv bnd_nodes_whatif.csv
    python3 bnd_nodes.py --selftest
"""

import argparse
import csv
import glob
import math
import os
import re
import shutil
import sys
import tempfile

T_BEFORE_NS = 6.0     # the window opens this long before the enable falls
T_AFTER_NS = 3.0      # and closes this long after
STEADY_GAP_NS = 1.0   # steady cycles end this long before the fall
KEEP_NS = 1.0         # rows kept at full resolution after the last tap rise
KEEP_LEAD_PS = 50.0   # and this long before it
TAP = "b_out"
SEL = "u_puf_u_core_sel_ro"

SAVE_OLD = ".save v(%s) v(%s) v(q)" % (TAP, SEL)
WR_RE = re.compile(r"^wrdata (bnd_(\d\d))\.raw\.txt v\(%s\) v\(%s\) v\(q\)$"
                   % (TAP, SEL), re.M)
TRAN_RE = re.compile(r"^\.tran 1p ([0-9.]+)n$", re.M)
FALL_RE = re.compile(r"enable falls at ([0-9.]+) ns")
CHAIN_RE = re.compile(r"^\* chain: (.+)$", re.M)
PROBE_RE = re.compile(r"^\* probe: every net of the chain saved, written "
                      r"from ([0-9.]+) to ([0-9.]+) ns$", re.M)
NODES_RE = re.compile(r"nodes_(\d\d)\.spice$")
OSC_RE = re.compile(r"^\* --- selector path for oscillator (\w+),", re.M)
XSEL_RE = re.compile(r"^Xsel(\d+) (.+) (\S+) (sky130_fd_sc_hd__\w+)$", re.M)
CSEL_RE = re.compile(r"^Csel(\d+) (\S+) 0 \S+$", re.M)


# ------------------------------------------------------------------ decks

def chain_nets(text):
    """The nets a deck's chain drives, in order, each checked twice: as the
    last port of its Xsel line and as the node of its Csel line."""
    outs = dict((int(m.group(1)), m.group(3)) for m in XSEL_RE.finditer(text))
    caps = dict((int(m.group(1)), m.group(2)) for m in CSEL_RE.finditer(text))
    if not outs or sorted(outs) != list(range(len(outs))):
        raise ValueError("no Xsel lines numbered from 0")
    if outs != caps:
        raise ValueError("Xsel and Csel lines disagree on the chain's nets")
    nets = [outs[i] for i in range(len(outs))]
    if nets[-1] != SEL:
        raise ValueError("the chain does not end on %s" % SEL)
    return nets


def make(deck_path, out_dir):
    """Write the probe version of one boundary deck. Three lines change and
    each must be found exactly once."""
    with open(deck_path, "r", encoding="utf-8") as fh:
        text = fh.read()
    nets = chain_nets(text)
    fall = FALL_RE.findall(text)
    if len(fall) != 1:
        raise ValueError("%s: the enable fall is named %d times"
                         % (deck_path, len(fall)))
    t_fall = float(fall[0])
    vecs = " ".join("v(%s)" % n for n in [TAP] + nets + ["q"])

    if text.count(SAVE_OLD + "\n") != 1:
        raise ValueError("%s: the .save line is not the generator's"
                         % deck_path)
    text = text.replace(SAVE_OLD + "\n", ".save %s\n" % vecs)

    trans = TRAN_RE.findall(text)
    if len(trans) != 1:
        raise ValueError("%s: %d .tran lines" % (deck_path, len(trans)))
    start, stop = t_fall - T_BEFORE_NS, t_fall + T_AFTER_NS
    text = TRAN_RE.sub(".tran 1p %.2fn %.2fn" % (stop, start), text)

    wr = WR_RE.findall(text)
    if len(wr) != 1:
        raise ValueError("%s: %d wrdata lines" % (deck_path, len(wr)))
    k = wr[0][1]
    text = WR_RE.sub("wrdata nodes_%s.raw.txt %s" % (k, vecs), text)

    note = ("* probe: every net of the chain saved, written from %.2f to "
            "%.2f ns\n" % (start, stop))
    text = text.replace("* chain: ", note + "* chain: ", 1)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "nodes_%s.spice" % k)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return out


# ---------------------------------------------------------------- reading

def read_raw(path):
    """wrdata output with a header: (names, t, [series])."""
    with open(path, "r", encoding="utf-8") as fh:
        head = fh.readline().split()
        rows = [ln.split() for ln in fh if ln.strip()]
    names = [h[2:-1] for h in head[1::2]]
    t = [float(r[0]) for r in rows]
    series = [[float(r[2 * i + 1]) for r in rows] for i in range(len(names))]
    return names, t, series


def crossings(t, v, level, t0=0.0):
    out = []
    for i in range(1, len(t)):
        if t[i] < t0:
            continue
        a, b = v[i - 1] - level, v[i] - level
        if (a < 0) != (b < 0):
            frac = -a / (b - a) if b != a else 0.0
            out.append((t[i - 1] + frac * (t[i] - t[i - 1]),
                        1 if b >= 0 else -1))
    return out


def median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def deck_info(deck_path):
    with open(deck_path, "r", encoding="utf-8") as fh:
        text = fh.read()
    osc = OSC_RE.findall(text)
    win = PROBE_RE.findall(text)
    return {"osc": osc[0] if osc else "",
            "chain": CHAIN_RE.findall(text)[0].split(),
            "nets": chain_nets(text),
            "t_fall": float(FALL_RE.findall(text)[0]) * 1e-9,
            "vdd": float(re.findall(r"^\.param SUPPLY=([0-9.]+)$", text,
                                    re.M)[0]),
            "window": tuple(float(x) * 1e-9 for x in win[0])
            if len(win) == 1 else None}


def read_deck(deck_path, raw_path):
    """Everything one probe deck says about its chain, net by net."""
    info = deck_info(deck_path)
    names, t, series = read_raw(raw_path)
    vdd, t_fall = info["vdd"], info["t_fall"]
    by = dict(zip(names, series))
    level = 0.5 * vdd
    steady_end = t_fall - STEADY_GAP_NS * 1e-9

    tap = crossings(t, by[TAP], level)
    rises = [x for x, d in tap if d > 0 and x <= steady_end]
    period = median([b - a for a, b in zip(rises, rises[1:])]) \
        if len(rises) > 2 else 0.0
    last = None
    for i in range(len(tap) - 1, 0, -1):
        if tap[i][1] < 0 and tap[i - 1][1] > 0:
            last = (tap[i - 1][0], tap[i][0])
            break

    nodes = []
    for cell, net in zip(info["chain"], info["nets"]):
        if net not in by:
            nodes.append({"cell": cell, "net": net, "present": False})
            continue
        x = crossings(t, by[net], level)
        up = [a for a, d in x if d > 0]
        gaps = []
        for r in rises[:-1]:
            later = [a for a in up if a >= r]
            if later:
                gaps.append(later[0] - r)
        delay = median(gaps) if len(gaps) > 1 else 0.0
        row = {"cell": cell, "net": net, "present": True, "delay": delay,
               "arrived": False, "width": 0.0, "peak": 0.0}
        if delay and period and last:
            want = last[0] + delay
            hit = [a for a in up if abs(a - want) <= 0.25 * period]
            if hit:
                row["arrived"] = True
                downs = [a for a, d in x if d < 0 and a > hit[0]]
                row["width"] = downs[0] - hit[0] if downs else 0.0
            lo, hi = last[0], want + 0.5 * period
            row["peak"] = max([v for tt, v in zip(t, by[net])
                               if lo <= tt <= hi] or [0.0])
        nodes.append(row)
    k = NODES_RE.findall(deck_path)
    return {"osc": info["osc"], "t_fall": t_fall, "vdd": vdd,
            "period": period, "tap": (last[1] - last[0]) if last else 0.0,
            "tap_rise": last[0] if last else None, "nodes": nodes,
            "raw": raw_path, "phase": k[0] if k else None,
            "window": info["window"]}


def raw_rows(path):
    """time -> (tap, sel_ro, q), all three as the file prints them."""
    with open(path, "r", encoding="utf-8") as fh:
        names = [h[2:-1] for h in fh.readline().split()[1::2]]
        idx = [names.index(n) for n in (TAP, SEL, "q")]
        out = {}
        for ln in fh:
            f = ln.split()
            if f:
                out[f[0]] = tuple(f[2 * i + 1] for i in idx)
    return out


def pairs(directory):
    out = []
    for deck in sorted(glob.glob(os.path.join(directory, "*",
                                              "nodes_*.spice"))):
        raw = deck[:-len(".spice")] + ".raw.txt"
        out.append((deck, raw))
    return out


def load(directory):
    return [read_deck(d, r) for d, r in pairs(directory)
            if os.path.exists(r)]


# ------------------------------------------------------------- reduction

def reduce_rows(raw_path, out_path, vdd):
    """Keep what read_deck reads and nothing else, then prove it. The
    level is half the deck's own supply, the one read_deck uses. It was
    the waveform's maximum at first, and a real rail overshoots."""
    with open(raw_path, "r", encoding="utf-8") as fh:
        head = fh.readline()
        rows = [ln for ln in fh if ln.strip()]
    names, t, series = read_raw(raw_path)
    level = 0.5 * vdd
    keep = {0, len(rows) - 1}
    for s in series:
        for i in range(1, len(t)):
            if (s[i - 1] < level) != (s[i] < level):
                keep.update((i - 1, i))
    tap = crossings(t, series[names.index(TAP)], level)
    last = None
    for i in range(len(tap) - 1, 0, -1):
        if tap[i][1] < 0 and tap[i - 1][1] > 0:
            last = tap[i - 1][0]
            break
    if last is not None:
        lo, hi = last - KEEP_LEAD_PS * 1e-12, last + KEEP_NS * 1e-9
        keep.update(i for i, tt in enumerate(t) if lo <= tt <= hi)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(head)
        for i in sorted(keep):
            fh.write(rows[i])
    return len(rows), len(keep)


def same(a, b):
    """Two reads of one deck, compared number by number."""
    if len(a["nodes"]) != len(b["nodes"]):
        return False
    for key in ("period", "tap"):
        if not math.isclose(a[key], b[key], rel_tol=0, abs_tol=1e-15):
            return False
    for x, y in zip(a["nodes"], b["nodes"]):
        if x.get("arrived") != y.get("arrived"):
            return False
        for key in ("delay", "width", "peak"):
            if not math.isclose(x.get(key, 0.0), y.get(key, 0.0),
                                rel_tol=0, abs_tol=1e-15):
                return False
    return True


def reduce_dir(src, dst):
    done = 0
    for deck, raw in pairs(src):
        sub = os.path.basename(os.path.dirname(deck))
        out = os.path.join(dst, sub)
        os.makedirs(out, exist_ok=True)
        red = os.path.join(out, os.path.basename(raw))
        n_all, n_kept = reduce_rows(raw, red, deck_info(deck)["vdd"])
        shutil.copyfile(deck, os.path.join(out, os.path.basename(deck)))
        log = deck[:-len(".spice")] + ".log"
        if os.path.exists(log):
            shutil.copyfile(log, os.path.join(out, os.path.basename(log)))
        full = read_deck(deck, raw)
        cut = read_deck(os.path.join(out, os.path.basename(deck)), red)
        if not same(full, cut):
            os.remove(red)
            raise SystemExit("%s: the reduced copy reads differently, "
                             "nothing kept" % raw)
        print("%s/%s  %d of %d rows kept, every number the same"
              % (sub, os.path.basename(raw), n_kept, n_all))
        done += 1
    if not done:
        raise SystemExit("no probe decks with waveforms in %s" % src)


# ---------------------------------------------------------------- checks

def screen_arrivals(path):
    """osc -> the screen's arrived string, one character a phase."""
    with open(path, "r", encoding="utf-8") as fh:
        return dict((r["osc"], r["arrived"]) for r in csv.DictReader(fh))


SCREEN_FALLS = ("30.080", "30.090", "30.100", "30.110")


def run_checks(decks, screen, screen_runs=None):
    """N01 to N05. With screen None, N04 and N05 are reported as not run:
    their entries carry None in place of a verdict."""
    res = []

    def add(cid, name, ok, detail):
        res.append((cid, name, bool(ok), detail))

    gone = ["%s %s" % (d["osc"], n["net"]) for d in decks
            for n in d["nodes"] if not n["present"]]
    add("N01", "every deck has a waveform for every net of its chain",
        decks and not gone, "; ".join(gone[:4]) or "%d decks, %d nets"
        % (len(decks), sum(len(d["nodes"]) for d in decks)))

    bad = []
    for d in decks:
        ds = [n.get("delay", 0.0) for n in d["nodes"] if n["present"]]
        if not all(ds) or any(b <= a for a, b in zip(ds, ds[1:])):
            bad.append(d["osc"])
    add("N02", "every net has a steady rise delay, in order down the chain",
        not bad, ", ".join(bad) or "all in order")

    back = []
    for d in decks:
        got = [n["arrived"] for n in d["nodes"] if n["present"]]
        if any(not a and b for a, b in zip(got, got[1:])):
            back.append(d["osc"])
    add("N03", "a pulse lost at one net is not found further down",
        not back, ", ".join(back) or "none")

    if screen is None:
        res.append(("N04", "sel_ro's verdict is the screen's for the same "
                           "deck", None, "not run: these decks are not the "
                           "screen's circuit"))
        res.append(("N05", "the tap, sel_ro and q are the screen's on every "
                           "row both kept", None, "not run: these decks are "
                           "not the screen's circuit"))
        return res
    wrong = []
    for d in decks:
        fall = "%.3f" % (d["t_fall"] * 1e9)
        if d["osc"] not in screen or fall not in SCREEN_FALLS:
            wrong.append("%s at %s ns has no screen row" % (d["osc"], fall))
            continue
        said = screen[d["osc"]][SCREEN_FALLS.index(fall)] == "1"
        if d["nodes"] and d["nodes"][-1].get("arrived") != said:
            wrong.append("%s at %s ns" % (d["osc"], fall))
    add("N04", "sel_ro's verdict is the screen's for the same deck",
        not wrong, "; ".join(wrong) or "%d decks agree" % len(decks))

    off, shared = [], 0
    for d in decks:
        theirs = os.path.join(screen_runs or "", d["osc"],
                              "bnd_%s.raw.txt" % d["phase"])
        if not screen_runs or not d["window"] or not os.path.exists(theirs):
            off.append("%s has no screen run to compare" % d["osc"])
            continue
        mine, theirs = raw_rows(d["raw"]), raw_rows(theirs)
        lo, hi = d["window"]
        common = [t for t in mine if t in theirs
                  and lo + 1e-12 <= float(t) <= hi - 1e-12]
        shared += len(common)
        if not common:
            off.append("%s has no row in common with the screen"
                       % d["osc"])
        elif any(mine[t] != theirs[t] for t in common):
            off.append("%s differs from the screen" % d["osc"])
    add("N05", "the tap, sel_ro and q are the screen's on every row both "
        "kept", decks and not off, "; ".join(off[:4]) or
        "%d rows in common, every one the same" % shared)
    return res


# ----------------------------------------------------------------- report

def lost_at(d):
    for i, n in enumerate(d["nodes"]):
        if n["present"] and not n["arrived"]:
            return i
    return None


# peak_v is the highest the net got from the last tap rise to half a period
# after the pulse was due, crossed or not. On a net the pulse crossed it
# is mostly the rail and its overshoot; on one it did not, it says how
# close the pulse came.
CSV_HEAD = ["osc", "en_fall_ns", "tap_ps", "stage", "cell", "net",
            "delay_ps", "arrived", "width_ps", "peak_v"]


def write_csv(decks, path):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(CSV_HEAD)
        for d in decks:
            for i, n in enumerate(d["nodes"]):
                w.writerow([d["osc"], "%.3f" % (d["t_fall"] * 1e9),
                            "%.0f" % (d["tap"] * 1e12), i, n["cell"],
                            n["net"], "%.0f" % (n.get("delay", 0) * 1e12),
                            "yes" if n.get("arrived") else "no",
                            "%.0f" % (n.get("width", 0) * 1e12)
                            if n.get("arrived") else "",
                            "%.3f" % n.get("peak", 0.0)])


def report(decks, screen, screen_runs=None, csv_path=None):
    print("the last pulse, net by net")
    print()
    for d in sorted(decks, key=lambda d: (d["t_fall"], d["osc"])):
        k = lost_at(d)
        print("  %s  enable falls %.3f ns, %.0f ps at the tap, %s"
              % (d["osc"], d["t_fall"] * 1e9, d["tap"] * 1e12,
                 "reaches sel_ro" if k is None else
                 "lost at stage %d" % k))
        for i, n in enumerate(d["nodes"]):
            if not n["present"]:
                print("      %d  %-14s %-22s no waveform" % (i, n["cell"],
                                                            n["net"]))
                continue
            got = ("%4.0f ps wide" % (n["width"] * 1e12) if n["arrived"]
                   else "lost, peaks at %.2f V" % n["peak"])
            print("      %d  %-14s %-22s %4.0f ps  %s"
                  % (i, n["cell"], n["net"], n["delay"] * 1e12, got))
    print()
    res = run_checks(decks, screen, screen_runs)
    for cid, name, ok, detail in res:
        mark = "--  " if ok is None else ("ok  " if ok else "FAIL")
        print("  %s %s  %s" % (mark, cid, name))
        print("            %s" % detail)
    if csv_path:
        write_csv(decks, csv_path)
        print()
        print("wrote %s" % csv_path)
    bad = [cid for cid, _, ok, _ in res if ok is False]
    print()
    if bad:
        print("FAIL: %s" % ", ".join(bad))
    elif screen is None:
        print("PASS: every net read. N04 and N05 not run, these are "
              "what-if decks")
    else:
        print("PASS: every net read, and every probe is the screen's run "
              "where the two meet")
    return 1 if bad else 0


# -------------------------------------------------------------- selftest

S_PERIOD = 1.13e-9
S_VDD = 1.95
S_HIGH = 1.958        # a rail that overshoots the supply a little, as real
                      # ones do; a reducer that took its level from the
                      # waveform's maximum keeps the wrong rows on it
S_CELLS = ["a221o_2.A1", "a22o_2.B1", "o21ba_2.A2", "a211o_2.A2"]


def _deck_text(osc, t_fall_ns, nets, probe=True):
    lines = ["* synthetic deck for bnd_nodes.py --selftest",
             ".param SUPPLY=%.2f" % S_VDD,
             "* --- selector path for oscillator %s, %d cells, open path ---"
             % (osc, len(nets))]
    if probe:
        lines.append("* probe: every net of the chain saved, written from "
                     "%.2f to %.2f ns" % (t_fall_ns - T_BEFORE_NS,
                                          t_fall_ns + T_AFTER_NS))
    lines += ["* chain: %s" % " ".join(S_CELLS[:len(nets)]),
              "* boundary sweep: enable falls at %.4f ns, phase 2 of 3"
              % t_fall_ns]
    prev = TAP
    for i, (cell, net) in enumerate(zip(S_CELLS, nets)):
        lines.append("Xsel%d %s ONE 0 0 VPWR VPWR %s sky130_fd_sc_hd__%s"
                     % (i, prev, net, cell.split(".")[0]))
        lines.append("Csel%d %s 0 1.0e-15" % (i, net))
        prev = net
    vecs = " ".join("v(%s)" % n for n in [TAP] + nets + ["q"])
    if probe:
        lines += [".save %s" % vecs, ".tran 1p 33.10n 24.10n",
                  "wrdata nodes_02.raw.txt %s" % vecs]
    else:
        lines += [SAVE_OLD, ".tran 1p 42.10n", ".control", "run",
                  "wrdata bnd_02.raw.txt v(%s) v(%s) v(q)" % (TAP, SEL),
                  ".endc"]
    return "\n".join(lines) + "\n"


def _highs_through(highs, rd, fd, minw):
    """One stage: rises move by rd, falls by fd, and a high narrower than
    minw does not get through. Returns (highs out, the one that died)."""
    out, died = [], None
    for r, f in highs:
        if f - r >= minw and f + fd > r + rd:
            out.append((r + rd, f + fd))
        else:
            died = (r + rd, f + rd)
    return out, died


# Three samples on every synthetic edge. Half the supply is 0.975 V, and
# 0.977 sits between it and 0.98, so the two crossings land between
# different pairs of rows, the way they can on a real edge.
RAMP = (0.9, 0.977, 0.99)


def _ramped(v, high):
    out = list(v)
    for i in range(1, len(v) - len(RAMP)):
        if v[i - 1] == 0.0 and v[i] == high:
            out[i:i + len(RAMP)] = RAMP
        elif v[i - 1] == high and v[i] == 0.0 and i >= len(RAMP):
            out[i - len(RAMP):i] = RAMP[::-1]
    return out


def _sample(t, highs, high, bump=None):
    """A dropped pulse leaves a bump that rises to 0.6 V and falls again,
    sloped so a reduction that loses its rows reads a different peak."""
    v = []
    for x in t:
        if any(r <= x < f for r, f in highs):
            v.append(high)
        elif bump and bump[0] <= x < bump[1]:
            mid = 0.5 * (bump[0] + bump[1])
            v.append(0.6 * (1 - abs(x - mid) / (mid - bump[0])))
        else:
            v.append(0.0)
    return v


def _write_case(root, osc, t_fall_ns, tap_ps, stages, drop_net=None,
                revive=None, screen=None):
    """One synthetic probe deck, and the screen's run of the same deck as
    a reduction would leave it, every third row. stages is a list of (rd,
    fd, minw) in seconds, one a cell. revive names a stage that takes the
    tap's own highs rather than its predecessor's, so a lost pulse turns
    up again. screen "off" moves sel_ro on one row of the screen's copy,
    "shift" moves every row of it a picosecond."""
    d = os.path.join(root, osc + "_" + t_fall_ns.replace(".", "p"))
    os.makedirs(d)
    nets = ["_n%d_" % i for i in range(len(stages) - 1)] + [SEL]
    with open(os.path.join(d, "nodes_02.spice"), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write(_deck_text(osc, float(t_fall_ns), nets))
    t_fall = float(t_fall_ns) * 1e-9
    last_rise = t_fall - tap_ps * 1e-12
    k = int(math.ceil((last_rise - (t_fall - T_BEFORE_NS * 1e-9))
                      / S_PERIOD)) + 1
    t0 = last_rise - k * S_PERIOD
    highs = []
    for j in range(k + 1):
        r = t0 + j * S_PERIOD
        highs.append((r, min(r + 0.5 * S_PERIOD, t_fall)))
    step = 2e-12
    start, stop = t_fall - T_BEFORE_NS * 1e-9, t_fall + T_AFTER_NS * 1e-9
    t = [start + i * step for i in range(int((stop - start) / step))]
    cols = [(TAP, _ramped(_sample(t, highs, S_HIGH), S_HIGH))]
    cur = highs
    for i, (rd, fd, minw) in enumerate(stages):
        src = highs if revive == i else cur
        cum_rd = rd + (sum(s[0] for s in stages[:i])
                       if revive == i else 0.0)
        cum_fd = fd + (sum(s[1] for s in stages[:i])
                       if revive == i else 0.0)
        cur, died = _highs_through(src, cum_rd, cum_fd, minw)
        cols.append((nets[i], _ramped(_sample(t, cur, S_HIGH, died),
                                      S_HIGH)))
    q, state = [], 0.0
    ups = sorted(r for r, _ in cur)
    j = 0
    for x in t:
        while j < len(ups) and x >= ups[j]:
            state = S_VDD - state
            j += 1
        q.append(state)
    cols.append(("q", q))
    trio = dict(cols)
    sdir = os.path.join(root, "screen", osc)
    os.makedirs(sdir)
    mid = (len(t) // 6) * 3
    with open(os.path.join(sdir, "bnd_02.raw.txt"), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write(" ".join("time v(%s)" % n for n in (TAP, SEL, "q")) + "\n")
        for i in range(0, len(t), 3):
            x = t[i] + (1e-12 if screen == "shift" else 0.0)
            vals = [trio[n][i] for n in (TAP, SEL, "q")]
            if screen == "off" and i == mid:
                vals[1] += 0.01
            fh.write(" ".join("%.8e %.8e" % (x, v) for v in vals) + "\n")
    if drop_net:
        cols = [c for c in cols if c[0] != drop_net]
    with open(os.path.join(d, "nodes_02.raw.txt"), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write(" ".join("time v(%s)" % n for n, _ in cols) + "\n")
        for i, x in enumerate(t):
            fh.write(" ".join("%.8e %.8e" % (x, c[i]) for _, c in cols)
                     + "\n")
    return d


# Every stage lengthens a high by its fall delay less its rise delay, 40 ps
# here, so a 66 ps pulse at the tap reaches the third stage about 146 ps
# wide. B00's third stage wants 160 and drops it; B04's wants 40.
STAGES = [(80e-12, 120e-12, 40e-12), (60e-12, 100e-12, 40e-12),
          (90e-12, 130e-12, 160e-12), (70e-12, 110e-12, 40e-12)]


def _tree(root, faults=()):
    """Two decks: B00 at 68 ps, which the third stage swallows, and B04
    at 68 ps, which arrives."""
    os.makedirs(root)
    kw = dict(faults)
    _write_case(root, "B00", "30.100", 68,
                kw.get("B00_stages", STAGES),
                drop_net=kw.get("drop"), revive=kw.get("revive"),
                screen=kw.get("screen"))
    easy = [(rd, fd, 40e-12) for rd, fd, _ in STAGES]
    _write_case(root, "B04", "30.100", 68, kw.get("B04_stages", easy))
    scr = os.path.join(root, "screen.csv")
    with open(scr, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("osc,arrived\n")
        fh.write("B00,%s\n" % kw.get("B00_screen", "0000"))
        fh.write("B04,0011\n")
    return scr


def selftest():
    print("self-test of bnd_nodes")
    ok = True
    tmp = tempfile.mkdtemp(prefix="bnd_nodes_selftest.")
    try:
        cases = [
            ("a clean pair: B00 lost at stage 2, B04 through", {}, []),
            ("a net with no waveform", {"drop": "_n1_"}, ["N01"]),
            ("a stage that leads the one before it",
             {"B00_stages": [(80e-12, 120e-12, 40e-12),
                             (60e-12, 100e-12, 40e-12),
                             (-90e-12, -50e-12, 40e-12),
                             (70e-12, 110e-12, 40e-12)],
              "B00_screen": "0011"}, ["N02"]),
            ("a pulse lost at stage 2 that turns up at stage 3",
             {"revive": 3, "B00_screen": "0011"}, ["N03"]),
            ("the screen says B00 kept the 68 ps pulse",
             {"B00_screen": "0011"}, ["N04"]),
            ("the screen's run has sel_ro 10 mV off on one row",
             {"screen": "off"}, ["N05"]),
            ("the screen's run shares no row with the probe",
             {"screen": "shift"}, ["N05"]),
        ]
        for i, (label, faults, expect) in enumerate(cases):
            root = os.path.join(tmp, "c%d" % i)
            scr = _tree(root, faults.items())
            decks = load(root)
            got = [cid for cid, _, good, _ in
                   run_checks(decks, screen_arrivals(scr),
                              os.path.join(root, "screen")) if not good]
            good = got == expect
            if i == 0:
                where = dict((d["osc"], lost_at(d)) for d in decks)
                good = good and where == {"B00": 2, "B04": None}
                peak = [d for d in decks if d["osc"] == "B00"][0]
                good = good and 0.55 < peak["nodes"][2]["peak"] <= 0.6
            ok = ok and good
            print("  %-56s %s" % (label, ("ok" if not expect else
                                          "trips %s" % expect[0])
                                  if good else "MISSED, tripped %s" % got))

        root = os.path.join(tmp, "noscr")
        _tree(root)
        res = run_checks(load(root), None)
        good = [r[2] for r in res] == [True, True, True, None, None]
        ok = ok and good
        print("  %-56s %s" % ("without a screen N04 and N05 say not run",
                              "ok" if good else "WRONG"))

        src = os.path.join(tmp, "make")
        os.makedirs(src)
        deck = os.path.join(src, "bnd_02.spice")
        with open(deck, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(_deck_text("B00", 30.100, ["_n0_", "_n1_", "_n2_", SEL],
                                probe=False))
        out = make(deck, os.path.join(tmp, "made"))
        text = open(out, encoding="utf-8").read()
        good = ("wrdata nodes_02.raw.txt v(b_out) v(_n0_)" in text
                and ".tran 1p 33.10n 24.10n" in text
                and SAVE_OLD not in text)
        print("  %-56s %s" % ("--make rewrites the three lines",
                              "ok" if good else "WRONG"))
        ok = ok and good
        with open(deck, "a", encoding="utf-8") as fh:
            fh.write(SAVE_OLD + "\n")
        try:
            make(deck, os.path.join(tmp, "made2"))
            good = False
        except ValueError:
            good = True
        print("  %-56s %s" % ("--make refuses a deck with two .save lines",
                              "refused" if good else "MISSED"))
        ok = ok and good

        global KEEP_NS
        root = os.path.join(tmp, "red")
        _tree(root)
        good = True
        saved, sys.stdout = sys.stdout, open(os.devnull, "w")
        try:
            try:
                reduce_dir(root, os.path.join(tmp, "red_out"))
            except SystemExit:
                good = False
            keep, KEEP_NS = KEEP_NS, 0.0
            try:
                reduce_dir(root, os.path.join(tmp, "red_cut"))
                good = False
            except SystemExit:
                pass
            finally:
                KEEP_NS = keep
        finally:
            sys.stdout.close()
            sys.stdout = saved
        print("  %-56s %s" % ("--reduce keeps a faithful copy, refuses a "
                              "lossy one", "ok" if good else "FAILED"))
        ok = ok and good
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("self-test %s" % ("passed" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("directory", nargs="?")
    ap.add_argument("--make", help="a boundary deck to write a probe of")
    ap.add_argument("--reduce", help="a folder of probe runs to reduce")
    ap.add_argument("--out", help="where --make or --reduce writes")
    ap.add_argument("--screen", help="the screen's csv, for N04")
    ap.add_argument("--screen-runs",
                    help="the screen's reduced runs, one folder a path, "
                         "for N05")
    ap.add_argument("--no-screen", action="store_true",
                    help="what-if decks: N04 and N05 reported as not run")
    ap.add_argument("--csv", help="write the per-net record here")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.make:
        print("wrote %s" % make(args.make, args.out or "."))
        return 0
    if args.reduce:
        if not args.out:
            ap.error("--reduce needs --out")
        reduce_dir(args.reduce, args.out)
        return 0
    if not args.directory or bool(args.screen) == args.no_screen:
        ap.error("give the probe folder and one of --screen or "
                 "--no-screen, or --selftest")
    if bool(args.screen) != bool(args.screen_runs):
        ap.error("--screen and --screen-runs go together")
    decks = load(args.directory)
    if not decks:
        raise SystemExit("no probe decks with waveforms in %s"
                         % args.directory)
    screen = None if args.no_screen else screen_arrivals(args.screen)
    return report(decks, screen, args.screen_runs, args.csv)


if __name__ == "__main__":
    sys.exit(main())
