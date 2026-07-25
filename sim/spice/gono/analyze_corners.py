#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Bound the operating range from the PVT-corner go/no-go logs.

The nominal deck says what the oscillators do at 27 C and 1.8 V. It says nothing
about the range the measurement has to survive. This reads the per-corner
parasitic logs and answers the three questions that decide whether a returned
count can be trusted:

  Does every ring start?  A corner where the meas statement finds no edges is a
  ring that did not oscillate, or a transient window too short to hold 25 rising
  edges. Either way the log cannot be read as a frequency.

  What are the frequency bounds?  The slow and fast corners give the range the
  selector path and the first counter flop have to pass.

  Can the counter wrap?  The counter is 16 bit and the window is a fixed number
  of reference-clock cycles, so the count is the ring frequency times the window
  duration. Past 65535 it wraps silently and returns a believable smaller number
  instead of an error, which would corrupt the ranking rather than flag it.

Usage:
    python3 analyze_corners.py --logs tt=dualarm_par_out.txt \\
        ss=dualarm_par_ss_out.txt ff=dualarm_par_ff_out.txt
"""

import argparse
import os
import re
import statistics as st
import sys

CNT_BITS = 16
DEFAULT_WINDOW = 1000       # reference-clock cycles, fixed in the RTL
DEFAULT_FREF_HZ = 25e6      # project clock the firmware asks for


def read_freqs(path):
    """Return {index: MHz} for the printed f<i> values in an ngspice log."""
    txt = open(path, errors="ignore").read()
    return {int(a): float(b) / 1e6
            for a, b in re.findall(r'^f(\d+)\s*=\s*([0-9.eE+-]+)', txt, re.M)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--logs", nargs="+", required=True,
                    help="corner=logpath pairs, for example tt=dualarm_par_out.txt")
    ap.add_argument("--n-ro", type=int, default=16)
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW,
                    help="measurement window in reference-clock cycles (default %(default)s)")
    ap.add_argument("--fref", type=float, default=DEFAULT_FREF_HZ,
                    help="reference clock in Hz (default 25e6)")
    args = ap.parse_args(argv)

    ceiling = (1 << CNT_BITS) - 1
    win_s = args.window / args.fref
    f_wrap_mhz = (ceiling + 1) / win_s / 1e6

    print("counter %d bit, window %d cycles at %.3g Hz = %.2f us"
          % (CNT_BITS, args.window, args.fref, win_s * 1e6))
    print("a count of %d is the ceiling, so wrap begins at %.1f MHz\n"
          % (ceiling, f_wrap_mhz))

    rows, problems = [], []
    for spec in args.logs:
        if "=" not in spec:
            print("error: expected corner=path, got %r" % spec, file=sys.stderr)
            return 2
        name, path = spec.split("=", 1)
        if not os.path.exists(path):
            problems.append("%s: log not found (%s)" % (name, path))
            continue
        f = read_freqs(path)
        missing = [i for i in range(args.n_ro) if i not in f]
        if missing:
            problems.append("%s: %d of %d oscillators produced no frequency (rings %s)"
                            % (name, len(missing), args.n_ro,
                               ",".join(map(str, missing[:6])) + ("..." if len(missing) > 6 else "")))
        vals = [f[i] for i in sorted(f)]
        if not vals:
            continue
        rows.append((name, vals))

    if not rows:
        print("no usable corner logs")
        for p in problems:
            print("  " + p)
        return 2

    print("%-6s %5s %9s %9s %9s %9s %11s %11s" %
          ("corner", "n", "min MHz", "mean MHz", "max MHz", "p-p %", "max count", "headroom"))
    print("-" * 78)
    worst_count = 0
    for name, v in rows:
        mean = st.mean(v)
        ptp = 100 * (max(v) - min(v)) / mean
        cnt = max(v) * 1e6 * win_s
        worst_count = max(worst_count, cnt)
        head = "WRAPS" if cnt > ceiling else "%.2fx" % (ceiling / cnt)
        print("%-6s %5d %9.1f %9.1f %9.1f %9.2f %11.0f %11s"
              % (name, len(v), min(v), mean, max(v), ptp, cnt, head))

    allv = [x for _, v in rows for x in v]
    print("\nacross all corners: %.1f to %.1f MHz (ratio %.2fx)"
          % (min(allv), max(allv), max(allv) / min(allv)))

    ok = True
    if worst_count > ceiling:
        print("FAIL: the fastest corner overflows the %d-bit counter "
              "(count %.0f > %d). Lower the window or the reference clock, or add "
              "an overflow flag, before trusting a fast-corner run."
              % (CNT_BITS, worst_count, ceiling))
        ok = False
    else:
        print("counter headroom holds at every corner tested: worst count %.0f of %d"
              % (worst_count, ceiling))
    for p in problems:
        print("FAIL: " + p)
        ok = False
    if ok:
        print("PASS: every ring started at every corner and no corner wraps the counter")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
