#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Summarize the placement-density sweep and draw the dispersion figure.

Reads placement_sweep_results.csv (written by run_placement_sweep.sh) and reports
the Arm A peak-to-peak dispersion across the builds: the median, the full range,
and any trend with density. The point at the shipped density (60) is called out
because it re-runs the shipped config and so checks flow determinism against the
build_current result.

Usage: python3 plot_placement_sweep.py [--csv PATH] [--out PATH] [--ship-pct 5.53]
"""

import argparse
import csv
import os
import statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))


def load(path):
    rows, total = [], 0
    with open(path) as fh:
        for r in csv.DictReader(fh):
            total += 1
            try:
                rows.append((int(r["density"]), float(r["ptp_pct"]),
                             float(r["cap_spread_fF"]), r["rings_ok"]))
            except (ValueError, KeyError):
                continue  # skip HARDEN_FAIL / NO_ARTIFACTS rows
    return rows, total


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default=os.path.join(HERE, "placement_sweep_results.csv"))
    ap.add_argument("--out", default=os.path.join(HERE, "placement_sweep.png"))
    ap.add_argument("--ship-pct", type=float, default=5.53,
                    help="build_current dispersion at density 60, for the determinism check")
    args = ap.parse_args(argv)

    rows, total = load(args.csv)
    ok = [r for r in rows if r[3] == "ok"]
    if len(ok) < 2:
        print("not enough successful builds to summarize (%d)" % len(ok))
        return 1

    dens = [r[0] for r in ok]
    disp = [r[1] for r in ok]
    med = st.median(disp)
    lo, hi = min(disp), max(disp)
    print("== placement-density sweep ==")
    print("builds that hardened and kept all rings: %d of %d attempted" % (len(ok), total))
    print("Arm A dispersion: median %.2f%%, range %.2f-%.2f%% p-p" % (med, lo, hi))

    ship = [d for de, d, *_ in ok if de == 60]
    if ship:
        drift = ship[0] - args.ship_pct
        note = "matches build_current (deterministic)" if abs(drift) < 0.05 \
            else "differs from build_current by %.2f pts" % drift
        print("density 60 rebuild: %.2f%% vs shipped %.2f%%  -> %s"
              % (ship[0], args.ship_pct, note))

    if len(set(dens)) > 1:
        r = st.correlation(dens, disp) if hasattr(st, "correlation") else float("nan")
        trend = "no strong density trend" if not (r == r) or abs(r) < 0.5 \
            else ("dispersion rises with density" if r > 0 else "dispersion falls with density")
        print("density-vs-dispersion correlation r=%.2f (%s)" % (r, trend))

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not available; skipped the figure")
        return 0

    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    ax.axhspan(lo, hi, color="#1f4e79", alpha=0.07, zorder=0)
    ax.axhline(med, color="#1f4e79", lw=1, ls="--", zorder=2, label="median %.2f%%" % med)
    ax.plot(dens, disp, "o", color="#1f4e79", ms=7, zorder=3, label="per build")
    for de, d, *_ in ok:
        if de == 60:
            ax.plot([de], [d], "o", color="#c0392b", ms=8, zorder=4,
                    label="density 60 (shipped config)")
    ax.set_xlabel("PL_TARGET_DENSITY_PCT")
    ax.set_ylabel("Arm A dispersion (% peak-to-peak)")
    ax.set_title("Frequency dispersion across %d placements (only density varied)" % len(ok))
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(args.out, dpi=150)
    print("figure written to %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
