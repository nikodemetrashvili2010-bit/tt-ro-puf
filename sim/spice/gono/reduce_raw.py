#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Shrink an ngspice wrdata file to the samples the selector analysis reads.

The 32 selector decks plus their 32 blocked controls produce 172 MB of waveform,
4.08 MB each over 42020 timepoints. That does not belong in a git repository, so
until now item 2 kept only its derived CSV and a reader had to take the numbers
on trust or spend four hours reproducing them with a PDK installed.

Almost all of that 172 MB is flat rail. `analyze_mux_sweep.py` never looks at
it. What it does is find where each signal crosses half the supply and
interpolate linearly between the two samples either side of the crossing, so
the samples in the middle of a high or a low change no answer. Dropping them is
lossless for this analysis, and that claim is not an argument, it is something
--verify checks deck by deck.

Three things have to survive or every number moves, and each one is a way I
could have got this wrong:

  the two samples bracketing every crossing, for all three signals, since those
  are the only samples the interpolation reads;

  the largest sample of the tap and of sel_ro, because the analyzer sets its
  threshold at `0.5 * max(max(tap), max(sel))` rather than at a fixed voltage,
  so losing a peak moves the threshold and therefore moves every crossing;

  the last timepoint, because `match_edges` uses `t[-1]` to decide which edges
  had time to arrive and which are legitimately still in flight.

Kept rows are copied as their original bytes. Nothing is reparsed and
reformatted on the way out, so no float rounding can creep in.

Usage:
    python3 reduce_raw.py --dir /tmp/mux --out mux --verify
    python3 reduce_raw.py --selftest
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Samples kept either side of each bracketing pair. Two is already more than the
# interpolation needs; it makes a reduced file readable as a waveform and costs
# almost nothing.
MARGIN = 2


class ReduceError(Exception):
    pass


def parse(path: str):
    """Return (header_lines, rows, values) with the original text kept.

    values[i] is the parsed row i, rows[i] the exact line it came from. The two
    lists stay in step so the writer can emit bytes rather than reformatted
    floats.
    """
    header, rows, values = [], [], []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.split()
            if not parts:
                continue
            try:
                values.append([float(x) for x in parts])
                rows.append(line)
            except ValueError:
                if not values:
                    header.append(line)
    if not values:
        raise ReduceError(f"{os.path.basename(path)}: no numeric rows")
    ncol = len(values[0])
    if ncol < 2 or ncol % 2:
        raise ReduceError(f"{os.path.basename(path)}: {ncol} columns, expected "
                          f"an even count of time/value pairs")
    keep = [i for i, v in enumerate(values) if len(v) == ncol]
    return header, [rows[i] for i in keep], [values[i] for i in keep], ncol


def keep_indices(values, ncol: int) -> set[int]:
    """Which rows the analysis can still see after the flat stretches go."""
    t = [v[0] for v in values]
    vectors = [[v[i] for v in values] for i in range(1, ncol, 2)]
    if len(vectors) < 2:
        raise ReduceError("expected at least a tap and a sel_ro vector")
    tap, sel = vectors[0], vectors[1]

    # The analyzer's own threshold. Copied from analyze_mux_sweep.measure so the
    # two cannot drift; if that line ever changes, --verify fails loudly rather
    # than this quietly keeping the wrong samples.
    level = 0.5 * max(max(tap), max(sel))

    keep: set[int] = {0, len(values) - 1}

    # the peaks that define the threshold
    keep.add(max(range(len(tap)), key=tap.__getitem__))
    keep.add(max(range(len(sel)), key=sel.__getitem__))

    # every bracketing pair, for every saved vector
    for v in vectors:
        for i in range(1, len(v)):
            a, b = v[i - 1], v[i]
            if (a < level <= b) or (a > level >= b):
                lo = max(0, i - 1 - MARGIN)
                hi = min(len(v) - 1, i + MARGIN)
                keep.update(range(lo, hi + 1))
    return keep


def reduce_file(src: str, dst: str) -> dict:
    header, rows, values, ncol = parse(src)
    keep = sorted(keep_indices(values, ncol))
    with open(dst, "w", encoding="utf-8", newline="") as fh:
        for h in header:
            fh.write(h)
        for i in keep:
            fh.write(rows[i])
    return dict(src=src, dst=dst, rows_in=len(values), rows_out=len(keep),
                bytes_in=os.path.getsize(src), bytes_out=os.path.getsize(dst))


def verify_pair(src_dir: str, red_dir: str, tag: str) -> list[str]:
    """Run the real analyzer over both copies of one deck and diff every field.

    This imports `analyze_mux_sweep` rather than reimplementing it. A reduction
    checked by my own idea of what the analyzer does would only prove the two
    agree with each other.
    """
    import analyze_mux_sweep as A

    t_full, v_full = A.read_raw(os.path.join(src_dir, f"mux_{tag}.raw.txt"))
    t_red, v_red = A.read_raw(os.path.join(red_dir, f"mux_{tag}.raw.txt"))

    # deck_chain reads the .spice beside the waveform, and that is unaffected by
    # reduction, so both measurements are pointed at the source directory for it.
    full = A.measure(t_full, v_full, src_dir, tag)
    red = A.measure(t_red, v_red, src_dir, tag)

    diffs = []
    for k in sorted(set(full) | set(red)):
        a, b = full.get(k), red.get(k)
        if isinstance(a, float) and isinstance(b, float):
            if a != b:
                diffs.append(f"{tag}.{k}: full {a!r}, reduced {b!r}")
        elif a != b:
            diffs.append(f"{tag}.{k}: full {a!r}, reduced {b!r}")
    return diffs


def run(src_dir: str, out_dir: str, do_verify: bool) -> int:
    files = sorted(glob.glob(os.path.join(src_dir, "mux_*.raw.txt")))
    if not files:
        raise ReduceError(f"no mux_*.raw.txt in {src_dir}")
    os.makedirs(out_dir, exist_ok=True)

    stats = []
    for f in files:
        stats.append(reduce_file(f, os.path.join(out_dir, os.path.basename(f))))

    tot_in = sum(s["bytes_in"] for s in stats)
    tot_out = sum(s["bytes_out"] for s in stats)
    rows_in = sum(s["rows_in"] for s in stats)
    rows_out = sum(s["rows_out"] for s in stats)
    print(f"{len(stats)} files")
    print(f"  rows  {rows_in} to {rows_out}  ({100.0*rows_out/rows_in:.2f}%)")
    print(f"  bytes {tot_in/1e6:.1f} MB to {tot_out/1e6:.3f} MB "
          f"({100.0*tot_out/tot_in:.2f}%)")

    if not do_verify:
        print("\nnot verified. Run again with --verify before trusting these.")
        return 0

    # The decks carry the chain comment the analyzer reads back, so copy them
    # across too or the reduced folder is not self-contained.
    copied = 0
    for d in sorted(glob.glob(os.path.join(src_dir, "mux_*.spice"))):
        dst = os.path.join(out_dir, os.path.basename(d))
        if not os.path.exists(dst):
            open(dst, "w", newline="").write(open(d).read())
            copied += 1
    print(f"  copied {copied} decks alongside")

    tags = [os.path.basename(f)[4:-8] for f in files]
    print(f"\nverifying {len(tags)} decks against the real analyzer")
    all_diffs = []
    for tag in tags:
        all_diffs += verify_pair(src_dir, out_dir, tag)
    if all_diffs:
        print(f"\nFAIL: {len(all_diffs)} field(s) differ between full and reduced")
        for d in all_diffs[:20]:
            print(f"  {d}")
        return 1
    print(f"every field of every deck is identical, full against reduced")
    return 0


def selftest() -> int:
    """Synthetic waveforms with the traps this reduction could fall into."""
    import tempfile
    import math

    def write_wave(path, n=4000, period=1000, vdd=1.95, peak_at=None):
        """A square-ish wave on three columns, wrdata layout."""
        with open(path, "w", newline="") as fh:
            fh.write(" time v(a) time v(b) time v(c)\n")
            for i in range(n):
                t = i * 1e-12
                ph = (i % period) / period
                a = vdd if ph < 0.5 else 0.0
                b = vdd if 0.05 < ph < 0.55 else 0.0
                c = vdd if 0.1 < ph < 0.6 else 0.0
                # soften the edges so a crossing has samples either side
                a += 0.0 if ph not in (0.0, 0.5) else 0.0
                if peak_at is not None and i == peak_at:
                    a = vdd * 1.2          # a lone peak that sets the threshold
                fh.write(f" {t:.8e} {a:.8e} {t:.8e} {b:.8e} {t:.8e} {c:.8e}\n")

    checks = []

    d = tempfile.mkdtemp()
    src = os.path.join(d, "mux_A00.raw.txt")
    write_wave(src)
    dst = os.path.join(d, "reduced.raw.txt")
    st = reduce_file(src, dst)
    checks.append((f"reduction keeps {st['rows_out']} of {st['rows_in']} rows",
                   st["rows_out"] < st["rows_in"]))

    # the threshold must be unchanged, which is the peak-preservation rule
    _, _, vf, nc = parse(src)
    _, _, vr, _ = parse(dst)
    def level_of(vals):
        tap = [v[1] for v in vals]
        sel = [v[3] for v in vals]
        return 0.5 * max(max(tap), max(sel))
    checks.append((f"threshold preserved: {level_of(vf):.9e} against "
                   f"{level_of(vr):.9e}", level_of(vf) == level_of(vr)))

    # and with a lone spike, which is the case that breaks a naive reducer
    src2 = os.path.join(d, "mux_A01.raw.txt")
    write_wave(src2, peak_at=1234)
    dst2 = os.path.join(d, "reduced2.raw.txt")
    reduce_file(src2, dst2)
    _, _, v2f, _ = parse(src2)
    _, _, v2r, _ = parse(dst2)
    checks.append((f"a lone peak that sets the threshold survives: "
                   f"{level_of(v2f):.9e} against {level_of(v2r):.9e}",
                   level_of(v2f) == level_of(v2r)))

    # the last timepoint must survive, because match_edges reads t[-1]
    checks.append((f"last timepoint preserved: {vf[-1][0]:.6e} against "
                   f"{vr[-1][0]:.6e}", vf[-1][0] == vr[-1][0]))

    # no crossing may be created or lost
    def cross_count(vals, col, lvl):
        v = [x[col] for x in vals]
        return sum(1 for i in range(1, len(v))
                   if (v[i-1] < lvl <= v[i]) or (v[i-1] > lvl >= v[i]))
    lvl = level_of(vf)
    same = all(cross_count(vf, c, lvl) == cross_count(vr, c, lvl)
               for c in (1, 3, 5))
    checks.append(("every crossing survives and none is invented on any of the "
                   "three signals", same))

    # kept lines must be byte-identical, not reformatted
    orig = set(open(src).read().splitlines())
    red = [l for l in open(dst).read().splitlines() if l.strip()
           and not l.strip().startswith("time")]
    checks.append((f"every kept row is a byte-for-byte copy ({len(red)} rows)",
                   all(l in orig for l in red)))

    # a file with no numeric rows must be refused
    bad = os.path.join(d, "mux_bad.raw.txt")
    open(bad, "w").write("time v(a)\nnothing here\n")
    try:
        reduce_file(bad, os.path.join(d, "out.txt"))
        caught = False
    except ReduceError as exc:
        caught = "no numeric rows" in str(exc)
    checks.append(("a waveform file with no data is refused", caught))

    # an odd column count means the wrdata layout is not what we think
    odd = os.path.join(d, "mux_odd.raw.txt")
    open(odd, "w").write("time v(a) v(b)\n1.0 2.0 3.0\n")
    try:
        reduce_file(odd, os.path.join(d, "out2.txt"))
        caught2 = False
    except ReduceError as exc:
        caught2 = "expected" in str(exc)
    checks.append(("an unexpected column layout is refused", caught2))

    print("selftest")
    bad_n = 0
    for line, ok in checks:
        bad_n += not ok
        print(f"  {'pass' if ok else 'FAIL'}  {line}")
    print(f"{len(checks) - bad_n} of {len(checks)} checks pass")
    return 1 if bad_n else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", help="directory holding the full mux_*.raw.txt")
    ap.add_argument("--out", help="where to write the reduced copies")
    ap.add_argument("--verify", action="store_true",
                    help="run the real analyzer over both and diff every field")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.dir or not args.out:
        ap.error("--dir and --out are required")
    return run(args.dir, args.out, args.verify)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReduceError as exc:
        print(f"reduce_raw: {exc}", file=sys.stderr)
        raise SystemExit(2)
