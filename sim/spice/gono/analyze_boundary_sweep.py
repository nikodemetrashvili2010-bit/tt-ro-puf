#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Read the boundary sweep from gen_boundary_sweep.py.

The question is item 1's question asked through item 2's worst selector path. At
every enable-fall phase, does the first counter flop resolve to a clean rail, and
does the captured count only ever move by one edge as the fall moves later.

High levels and low levels are kept apart here, and that is the whole reason
this file exists in the shape it does. The first version of it did what item 2's
analyzer does, took the narrowest level at each node and compared them, and on
B15 it reported a pulse arriving at sel_ro 182 ps wider than it left the tap.
A selector cannot widen a pulse, so I went and looked at the waveform.

What the waveform says, on B15 at the fast corner. The tap runs 539 ps high and
583 ps low. At sel_ro the same ring runs 721 ps high and 401 ps low. The period
is 1122 ps at both nodes, to the picosecond, so no edge is being lost. The rise
travels the path in 360 ps and the fall in 541 ps, and that 181 ps of asymmetry
moves the trailing edge without moving the leading one. The high level grows by
181 ps and the low level shrinks by the same 181 ps.

So the narrowest level at the tap is a high and the narrowest level at sel_ro is
a low, and item 2 compared one against the other. Its headline, that levels
shorten by up to 25.0%, is not a shortening of anything. Nothing about item 2's
pass changes, because that rested on every edge arriving and the period is
preserved exactly. What changes is the alarm it raised about item 1, which is
the thing this sweep was written to answer.

The counter's first stage is a rising-edge flop. Through B15 the level after
each rising edge is longer than it was at the tap, not shorter. The selector is
helping that flop rather than starving it. The low level is the one that
shrinks, to 401 ps, which is the gap between one clock and the next.

That is a steady-state argument and this sweep is about the boundary, where the
last high level is cut short by the enable falling inside it. Below some width a
pulse stops being a narrow rectangle and becomes a bump that never reaches the
rail, and no amount of arithmetic about delays will say where that width is.
Hence the simulation.

A swallowed last pulse is not a failure. It costs one edge out of roughly twenty
thousand, which is what item 1 already accepted and what the settle handshake
absorbs, since the core publishes only after three equal reads. The failure I am
looking for is a pulse that lands near the flop's resolving threshold and leaves
q at mid-rail, because a hung flop is a corrupt word rather than a lost count.

The final-edge test does not compare totals over a window. The selector delays
every edge, so a total count reports the last one as lost for a reason that has
nothing to do with the circuit. Item 6 and then item 2 both cost me time to that
same mistake.

Run:
    python3 analyze_boundary_sweep.py /tmp/bndsweep --vdd 1.95
    python3 analyze_boundary_sweep.py --selftest
"""

import argparse
import csv
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from analyze_mux_sweep import crossings, median, read_raw  # noqa: E402

T_START_NS = 8.0        # ring is enabled at 2 ns; ignore the startup transient
T_RESET_NS = 1.5        # q is counted only after the reset is released
BAND_FRAC = 0.01        # tolerated fraction of tail samples inside the forbidden band
RAIL_FRAC = 0.05        # how close to a rail the settled level has to sit
MIN_SPREAD_S = 50e-12   # boundary pulses must differ by at least this before the
                        # fixed-time and fixed-fraction models can be told apart


def stdev(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return (sum((x - m) ** 2 for x in xs) / (n - 1)) ** 0.5


def fall_time(directory, k):
    """The enable-fall time this deck was built for, read back out of the deck."""
    path = os.path.join(directory, "bnd_%02d.spice" % k)
    if not os.path.isfile(path):
        return None
    for line in open(path, encoding="utf-8", errors="replace"):
        m = re.search(r'enable falls at ([0-9.]+) ns', line)
        if m:
            return float(m.group(1)) * 1e-9
    return None


def last_high(xs):
    """Width and start of the final complete high level, a rise closed by a fall."""
    for i in range(len(xs) - 1, 0, -1):
        if xs[i][1] < 0 and xs[i - 1][1] > 0:
            return xs[i][0] - xs[i - 1][0], xs[i - 1][0]
    return 0.0, 0.0


def last_low(xs):
    """Width of the final complete low level, a fall closed by a rise."""
    for i in range(len(xs) - 1, 0, -1):
        if xs[i][1] > 0 and xs[i - 1][1] < 0:
            return xs[i][0] - xs[i - 1][0]
    return 0.0


def steady_delays(tap, sel, t0, t_fall):
    """Rise delay, fall delay and ring period, all measured away from the boundary.

    Rise and fall are kept separate because their difference is what moves the
    trailing edge of every level, and lumping them into one delay is how the
    first version of this analysis ended up reporting a widened pulse.
    """
    def match(src, dst):
        gaps = []
        for x in src[:-1]:
            later = [y for y in dst if y >= x]
            if later:
                gaps.append(later[0] - x)
        return median(gaps) if gaps else 0.0

    win_in = lambda xs, d: [x for x, dd in xs if dd == d and t0 <= x <= t_fall - 1e-9]
    win_out = lambda xs, d: [x for x, dd in xs if dd == d and t0 <= x]

    r_in, f_in = win_in(tap, 1), win_in(tap, -1)
    r_out, f_out = win_out(sel, 1), win_out(sel, -1)
    if len(r_in) < 3 or len(r_out) < 2:
        return 0.0, 0.0, 0.0
    period = median([r_in[i + 1] - r_in[i] for i in range(len(r_in) - 1)])
    return match(r_in, r_out), match(f_in, f_out), period


def tail_state(t, v, tail_ns, vdd):
    """Fraction of the settle tail inside the forbidden band, and the final level."""
    lo, hi = 0.2 * vdd, 0.8 * vdd
    start = t[-1] - tail_ns * 1e-9
    tail = [vi for ti, vi in zip(t, v) if ti >= start]
    if not tail:
        return 1.0, v[-1], vdd
    in_band = sum(1 for vi in tail if lo < vi < hi)
    final = sum(tail[-50:]) / len(tail[-50:])
    return in_band / len(tail), final, min(abs(final), abs(final - vdd))


def read_phase(directory, path, vdd, tail_ns):
    """Everything one phase deck has to say."""
    k = int(os.path.basename(path)[4:6])
    t, vec = read_raw(path)
    if len(vec) < 3:
        raise ValueError("%s: expected three saved vectors, found %d"
                         % (os.path.basename(path), len(vec)))
    tap, sel, q = vec
    level = 0.5 * vdd
    t0 = T_START_NS * 1e-9
    t_fall = fall_time(directory, k)
    if t_fall is None:
        t_fall = t[-1] - tail_ns * 1e-9

    x_tap = crossings(t, tap, level, t0)
    x_sel = crossings(t, sel, level, t0)
    x_q = crossings(t, q, level, T_RESET_NS * 1e-9)

    rise_d, fall_d, period = steady_delays(x_tap, x_sel, t0, t_fall)
    tap_hi, tap_rise = last_high(x_tap)
    sel_hi, _ = last_high(x_sel)

    # If the steady window held too few edges the delay is unknown, and an
    # unknown delay must not quietly become a verdict. Without this the phase
    # reports its final edge as swallowed, which reads as a real result and is
    # only a measurement that never happened.
    measured = bool(period) and bool(tap_rise)

    # The last high at the tap is the boundary pulse. It reached the flop only if
    # a rising edge turned up at sel_ro one rise-delay later.
    arrived = False
    if measured:
        want = tap_rise + rise_d
        arrived = any(abs(x - want) <= 0.25 * period for x, d in x_sel if d > 0)
    if not arrived:
        sel_hi = 0.0

    frac_band, final, rail = tail_state(t, q, tail_ns, vdd)
    return dict(
        k=k, t_fall=t_fall, rise_d=rise_d, fall_d=fall_d, period=period,
        tap_hi=tap_hi, sel_hi=sel_hi, tap_lo=last_low(x_tap), sel_lo=last_low(x_sel),
        arrived=arrived, measured=measured, toggles=len(x_q),
        frac_band=frac_band, final=final,
        settled=(frac_band < BAND_FRAC and rail < RAIL_FRAC * vdd))


def compare_models(rows):
    """Does the selector change a high level by a fixed time or by a fixed fraction?

    Both are fitted to the boundary pulses this sweep produced and judged on the
    spread of what they leave behind. Highs are compared against highs. Comparing
    the narrowest level at one node against the narrowest at the other is the
    error this whole file was rewritten to stop repeating.
    """
    pairs = [(r["tap_hi"], r["sel_hi"]) for r in rows if r["arrived"] and r["tap_hi"] > 0]
    if len(pairs) < 4:
        return None
    spread = max(a for a, _ in pairs) - min(a for a, _ in pairs)
    offsets = [b - a for a, b in pairs]
    ratios = [b / a for a, b in pairs]
    r_mean = sum(ratios) / len(ratios)
    off_sd, prop_sd = stdev(offsets), stdev([b - r_mean * a for a, b in pairs])
    separable = spread > MIN_SPREAD_S and abs(off_sd - prop_sd) > 0.1 * max(off_sd, prop_sd)
    return dict(n=len(pairs), tap_spread=spread, separable=separable,
                offset=sum(offsets) / len(offsets), offset_sd=off_sd,
                ratio=r_mean, prop_sd=prop_sd)


def report(rows, models, csv_path=None):
    problems = []
    ordered = sorted(rows, key=lambda r: r["k"])

    print("ring-stop boundary through the selector")
    print()
    print("  phase  EN falls   last high at tap   at sel_ro  flop edges  final q  tail")
    for r in ordered:
        if not r["measured"]:
            sel = "no reading"
        elif r["arrived"]:
            sel = "%6.0f ps" % (r["sel_hi"] * 1e12)
        else:
            sel = "swallowed"
        print("  %5d  %6.2f ns  %12.0f ps  %11s  %10d  %6.3f V  %s"
              % (r["k"], r["t_fall"] * 1e9, r["tap_hi"] * 1e12, sel, r["toggles"],
                 r["final"], "settled" if r["settled"] else "NOT SETTLED"))
        if not r["measured"]:
            problems.append("phase %d had too few steady edges between %.0f ns and the "
                            "enable fall to measure the path delay, so nothing can be "
                            "said about its final edge" % (r["k"], T_START_NS))
        if not r["settled"]:
            problems.append("phase %d left q at %.3f V with %.1f%% of the tail in the "
                            "forbidden band" % (r["k"], r["final"], 100 * r["frac_band"]))

    counts = [r["toggles"] for r in ordered]
    steps = [b - a for a, b in zip(counts, counts[1:])]
    bad = [(i, d) for i, d in enumerate(steps) if d < 0 or d > 1]
    swallowed = [r["k"] for r in ordered if r["measured"] and not r["arrived"]]
    taps = [r["tap_hi"] * 1e12 for r in ordered if r["tap_hi"] > 0]
    sels = [r["sel_hi"] * 1e12 for r in ordered if r["arrived"]]
    rise = [r["rise_d"] * 1e12 for r in ordered if r["rise_d"]]
    fall = [r["fall_d"] * 1e12 for r in ordered if r["fall_d"]]

    print()
    if rise and fall:
        print("steady path delay: rise %.0f ps, fall %.0f ps, asymmetry %.0f ps"
              % (median(rise), median(fall), median(fall) - median(rise)))
        print("that asymmetry moves each trailing edge, so it %s every high level "
              "and %s every low one by the same amount"
              % ("lengthens" if median(fall) > median(rise) else "shortens",
                 "shortens" if median(fall) > median(rise) else "lengthens"))
    if taps:
        print("boundary pulse at the tap: %.0f ps to %.0f ps across %d phases"
              % (min(taps), max(taps), len(taps)))
    if sels:
        print("the same pulse at sel_ro: %.0f ps to %.0f ps" % (min(sels), max(sels)))
    print("final rising edge swallowed on %d of %d phases%s"
          % (len(swallowed), len(ordered),
             "" if not swallowed else ": " + ", ".join(str(k) for k in swallowed)))
    print("counted toggles: min %d, max %d" % (min(counts), max(counts)))
    print("count only ever steps up by one: %s" % ("yes" if not bad else "NO"))

    if models:
        print()
        print("what the selector does to a high level, fitted on %d boundary pulses "
              "spanning %.0f ps:" % (models["n"], models["tap_spread"] * 1e12))
        print("  fixed time      %+.0f ps, residual spread %.1f ps"
              % (models["offset"] * 1e12, models["offset_sd"] * 1e12))
        print("  fixed fraction  %+.1f%%, residual spread %.1f ps"
              % (100 * (models["ratio"] - 1), models["prop_sd"] * 1e12))
        if not models["separable"]:
            print("  the pulses here are too alike to tell the two apart; both fit "
                  "and neither is evidence")
        else:
            print("  the tighter fit is %s"
                  % ("a fixed time" if models["offset_sd"] < models["prop_sd"]
                     else "a fixed fraction"))

    if bad:
        problems.append("the count changed by more than one edge between adjacent "
                        "phases: " + ", ".join("%d to %d: %+d" % (i, i + 1, d)
                                               for i, d in bad[:6]))

    # A sweep that never changes the count never moved the enable fall past a
    # ring edge, so it never reached the boundary it exists to test and every
    # phase below is the same easy case repeated. The slow corner found this:
    # the default 38 steps span 1.9 ns, which is longer than the ring period at
    # tt and ff but only half of it at ss, and the run came back clean without
    # having tested anything. A vacuous pass is worse than a failure.
    if len(counts) > 1 and max(counts) == min(counts):
        problems.append("the count is %d at every phase, so the sweep never "
                        "crossed a ring edge and never reached the boundary. "
                        "It spans %.2f ns; widen it past one ring period with "
                        "--steps." % (counts[0],
                                      (ordered[-1]["t_fall"] - ordered[0]["t_fall"]) * 1e9))

    if csv_path:
        with open(csv_path, "w", newline="\n", encoding="utf-8") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(["phase", "en_fall_ns", "tap_high_ps", "sel_high_ps",
                        "tap_low_ps", "sel_low_ps", "rise_delay_ps", "fall_delay_ps",
                        "final_edge_arrived", "flop_edges", "final_q_v", "settled"])
            for r in ordered:
                w.writerow([r["k"], "%.3f" % (r["t_fall"] * 1e9),
                            "%.0f" % (r["tap_hi"] * 1e12),
                            "%.0f" % (r["sel_hi"] * 1e12) if r["arrived"] else "",
                            "%.0f" % (r["tap_lo"] * 1e12), "%.0f" % (r["sel_lo"] * 1e12),
                            "%.0f" % (r["rise_d"] * 1e12), "%.0f" % (r["fall_d"] * 1e12),
                            "yes" if r["arrived"] else "no", r["toggles"],
                            "%.4f" % r["final"], "yes" if r["settled"] else "no"])
        print()
        print("wrote %s" % csv_path)

    print()
    if problems:
        print("FAIL, %d problem%s" % (len(problems), "" if len(problems) == 1 else "s"))
        for p in problems:
            print("  " + p)
        return 1
    print("PASS: every enable-fall phase resolved the flop to a clean rail, and the "
          "count never moved by more than one edge")
    if swallowed:
        print("      %d phase(s) lost the final rising edge, which is the one-count "
              "error the settle handshake already tolerates" % len(swallowed))
    return 0


# --------------------------------------------------------------------------
# Self-test. An analysis that has never failed has not been tested, so this
# plants each fault it claims to catch and checks that it catches it.
# --------------------------------------------------------------------------

def _tap_highs(period, t_start, t_stop):
    """High intervals of a ring that runs from t_start and is stopped at t_stop.

    Wherever t_stop lands inside a high level, that level is cut short. The
    truncated one is the boundary pulse, and varying its width is the whole
    point of the phase sweep, so the synthetic has to reproduce that rather than
    a train of identical pulses.
    """
    highs, k = [], 0
    while True:
        rise = t_start + k * period
        if rise >= t_stop:
            return highs
        highs.append((rise, min(rise + 0.5 * period, t_stop)))
        k += 1


def _sample(t, highs, high):
    out, j = [], 0
    for x in t:
        while j < len(highs) and x >= highs[j][1]:
            j += 1
        out.append(high if j < len(highs) and highs[j][0] <= x else 0.0)
    return out


def _write_deck(d, k, t_fall_ns):
    with open(os.path.join(d, "bnd_%02d.spice" % k), "w", newline="\n") as fh:
        fh.write("* chain: synthetic\n")
        fh.write("* boundary sweep: enable falls at %.4f ns, phase %d of 7\n"
                 % (t_fall_ns, k))


def _write_raw(d, k, t, tap, sel, q):
    with open(os.path.join(d, "bnd_%02d.raw.txt" % k), "w", newline="\n") as fh:
        fh.write("time v(b_out) time v(sel_ro) time v(q)\n")
        for i in range(len(t)):
            fh.write("%.6e %.6e %.6e %.6e %.6e %.6e\n"
                     % (t[i], tap[i], t[i], sel[i], t[i], q[i]))


def _synth(d, k, vdd, period, t_fall, rise_d, fall_d, min_width,
           hang=False, extra_edges=0):
    """A stopped ring, the selector's version of it, and the flop it clocks.

    The selector is modelled the way the waveform says it behaves: the rising
    edge moves by one delay and the falling edge by another, so the high level
    changes by the difference. A tap pulse narrower than min_width is dropped
    entirely, standing in for a bump the real gates cannot respond to.
    """
    step = 2e-12
    t = [i * step for i in range(int(20e-9 / step))]

    highs = _tap_highs(period, 2e-9, t_fall)
    tap = _sample(t, highs, vdd)
    sel_highs = [(r + rise_d, f + fall_d) for r, f in highs
                 if f - r >= min_width and f + fall_d > r + rise_d]
    sel = _sample(t, sel_highs, vdd)

    q, level, j = [], 0.0, 0
    for x in t:
        while j < len(sel_highs) and x >= sel_highs[j][0]:
            level = vdd - level
            j += 1
        q.append(level)

    if extra_edges:
        a = int(len(q) * 0.55)
        q = q[:a] + [vdd - v for v in q[a:a + 400]] + q[a + 400:]   # two crossings
    if hang:
        cut = int(len(q) * 0.75)
        q = q[:cut] + [0.5 * vdd] * (len(q) - cut)

    _write_deck(d, k, t_fall * 1e9)
    _write_raw(d, k, t, tap, sel, q)


def selftest():
    import io
    import shutil
    import tempfile

    vdd, period = 1.95, 1.13e-9
    # B15's own numbers, so the synthetic behaves like the path being swept.
    RISE, FALL = 0.360e-9, 0.541e-9
    ok = True

    def sweep(base, step, n, rise_d=RISE, fall_d=FALL, min_width=120e-12, **kw):
        def build(d):
            for k in range(n):
                extra = dict((key, val(k)) for key, val in kw.items())
                _synth(d, k, vdd, period, base + k * step, rise_d, fall_d,
                       min_width, **extra)
        return build

    def run(label, build, expect_fail, check=None):
        nonlocal ok
        d = tempfile.mkdtemp(prefix="bndselftest.")
        try:
            build(d)
            rows = [read_phase(d, p, vdd, 2.0)
                    for p in sorted(glob.glob(os.path.join(d, "bnd_*.raw.txt")))]
            buf, keep = io.StringIO(), sys.stdout
            sys.stdout = buf
            try:
                rc = report(rows, compare_models(rows))
            finally:
                sys.stdout = keep
            text = buf.getvalue()
            good = ((rc != 0) == expect_fail) and (check is None or check(rows, text))
            print("  %-54s %s" % (label, "ok" if good else "MISSED"))
            if not good:
                ok = False
                print(text)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    print("self-test of analyze_boundary_sweep")

    # 14.0 to 14.98 ns walks the enable fall through a whole ring period, so the
    # boundary pulse width varies instead of repeating. Starting this late also
    # leaves enough steady edges after 8 ns for the path delay to be measured,
    # which an earlier version of this sweep did not and which showed up as
    # phases reporting a swallowed edge when they had simply not been measured.
    full = dict(base=14.0e-9, step=0.14e-9, n=8)

    run("a clean sweep passes", sweep(**full), expect_fail=False)

    run("a flop left at mid-rail is caught",
        sweep(hang=lambda k: k == 3, **full), expect_fail=True,
        check=lambda rows, text: "NOT SETTLED" in text)

    run("a count that jumps two edges is caught",
        sweep(extra_edges=lambda k: 1 if k == 4 else 0, **full), expect_fail=True,
        check=lambda rows, text: "more than one edge" in text)

    # min_width here is set above the narrowest boundary pulse the sweep makes,
    # so one phase produces a tap pulse the gates cannot pass on.
    run("a pulse too narrow to survive is reported, not failed",
        sweep(min_width=200e-12, **full), expect_fail=False,
        check=lambda rows, text: any(r["measured"] and not r["arrived"] for r in rows))

    # The asymmetry is what this has to get right, and getting it backwards is
    # the bug that sent me to the waveform in the first place.
    def fitted_offset(text):
        m = re.search(r'fixed time\s+([+-][0-9]+) ps', text)
        return float(m.group(1)) if m else None

    run("a high level that grows is not called a shortening",
        sweep(**full), expect_fail=False,
        check=lambda rows, text: "lengthens every high level" in text
        and fitted_offset(text) is not None
        and abs(fitted_offset(text) - 181) <= 5)

    run("a sweep with too few steady edges refuses to guess",
        sweep(base=9.6e-9, step=0.14e-9, n=4), expect_fail=True,
        check=lambda rows, text: "no reading" in text)

    run("a path whose fall is faster shortens the high instead",
        sweep(rise_d=0.360e-9, fall_d=0.240e-9, **full), expect_fail=False,
        check=lambda rows, text: "shortens every high level" in text)

    # Every fall lands in the same low level here, so every boundary pulse comes
    # out the same width and neither model can be preferred. It also never moves
    # the fall past a ring edge, which is the second thing wrong with a sweep
    # this narrow and the reason it now fails rather than passes with a note.
    # The slow-corner run is what taught me these are the same mistake: it came
    # back clean having never reached the boundary at all.
    run("a sweep too narrow to separate the models says so, and fails for not "
        "reaching the boundary",
        sweep(base=12.80e-9, step=0.10e-9, n=5), expect_fail=True,
        check=lambda rows, text: "too alike" in text
        and "never crossed a ring edge" in text)

    print("self-test %s" % ("passed" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("directory", nargs="?")
    ap.add_argument("--vdd", type=float, default=1.95,
                    help="supply of the swept corner (1.95 ff, 1.8 tt, 1.6 ss)")
    ap.add_argument("--tail-ns", type=float, default=2.0,
                    help="window at the end of each run tested for a settled rail")
    ap.add_argument("--csv", help="write the derived per-phase record here")
    ap.add_argument("--selftest", action="store_true",
                    help="run the planted-fault checks and exit")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.directory:
        ap.error("give a sweep directory, or --selftest")

    files = sorted(glob.glob(os.path.join(args.directory, "bnd_*.raw.txt")))
    if not files:
        raise SystemExit("no bnd_*.raw.txt in %s; run the decks first" % args.directory)
    rows = [read_phase(args.directory, p, args.vdd, args.tail_ns) for p in files]
    return report(rows, compare_models(rows), args.csv)


if __name__ == "__main__":
    sys.exit(main())
