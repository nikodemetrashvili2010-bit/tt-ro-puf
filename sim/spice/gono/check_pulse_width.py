#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""
What clock pulse width the PDK itself promises for the counter's first flop.

The boundary sweeps show the flop resolving to a clean rail on every phase, but
SPICE resolving a pulse is not the same claim as the vendor having characterized
the cell at that width. B00 at its own threshold hands the flop an 80 ps clock
high, which is narrow enough that I want the library's opinion and not only the
simulator's.

Liberty writes this two different ways depending on who generated it, either as
a min_pulse_width_high attribute on the pin or as a timing group whose
timing_type is minimum_pulse_width with rise and fall constraint tables. This
reads both, and if it finds neither it prints what it did find rather than
returning a quiet answer, because the first version of this script reported "no
CLK pin" when the real problem was that it only knew one of the two spellings.

Run (WSL, PDK_ROOT set):
    python3 check_pulse_width.py
    python3 check_pulse_width.py --narrowest 80
"""
import argparse
import glob
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(
    os.path.abspath(__file__)), "..")))
from pdk_paths import sky130_spice_paths  # noqa: E402

CELL = "sky130_fd_sc_hd__dfrtp_2"
CLK = "CLK"

# The Liberty that matches each corner the decks use. Named rather than pattern
# matched, because the first version took the first file whose name contained
# "ff" and got ff_100C_1v65, which is not the corner anything here ran at. It
# reported 109.4 ps where the real corner promises 77.5, and that flipped the
# verdict. Getting the corner wrong is the whole failure mode of this check.
CORNER_LIB = {
    "ff": "sky130_fd_sc_hd__ff_n40C_1v95.lib",   # -40 C, 1.95 V
    "tt": "sky130_fd_sc_hd__tt_025C_1v80.lib",   #  25 C, 1.80 V
    "ss": "sky130_fd_sc_hd__ss_100C_1v60.lib",   # 100 C, 1.60 V
}


def lib_dir():
    cells = sky130_spice_paths()[1]
    return os.path.join(os.path.dirname(os.path.dirname(str(cells))), "lib")


def block(text, start):
    """Text of the brace block that opens at or after `start`."""
    i = text.index("{", start)
    depth, j = 0, i
    while j < len(text):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[i + 1:j]
        j += 1
    raise ValueError("unbalanced braces")


def group(text, keyword, name=None):
    """First `keyword (name) { ... }` block, quotes optional."""
    want = r'"?%s"?' % re.escape(name) if name else r'[^)]*'
    m = re.search(r"\b%s\s*\(\s*%s\s*\)" % (re.escape(keyword), want), text)
    return block(text, m.end()) if m else None


def first_value(text):
    """The first number inside a values(...) list."""
    m = re.search(r"values\s*\(\s*\"?\s*([-0-9.eE]+)", text)
    return float(m.group(1)) if m else None


def pulse_widths(pin_text):
    """ps, from either Liberty spelling. None if this file does not say."""
    out = {}
    for edge in ("high", "low"):
        m = re.search(r"\bmin_pulse_width_%s\s*:\s*([-0-9.eE]+)" % edge, pin_text)
        if m:
            out[edge] = float(m.group(1)) * 1000.0
    if out:
        return out
    for m in re.finditer(r"\btiming\s*\(\s*[^)]*\)", pin_text):
        tim = block(pin_text, m.end())
        t = re.search(r"timing_type\s*:\s*\"?([a-z_]+)", tim)
        if not t or "pulse_width" not in t.group(1):
            continue
        rise = group(tim, "rise_constraint")
        fall = group(tim, "fall_constraint")
        if rise is not None and first_value(rise) is not None:
            out["high"] = first_value(rise) * 1000.0
        if fall is not None and first_value(fall) is not None:
            out["low"] = first_value(fall) * 1000.0
    return out or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--narrowest", type=float, default=80.0,
                    help="narrowest clock high the sweeps delivered, in ps "
                         "(default 80, B00 at its own threshold)")
    ap.add_argument("--cell", default=CELL)
    ap.add_argument("--corner", default="ff", choices=sorted(CORNER_LIB),
                    help="which corner the sweep ran at (default ff, where the "
                         "boundary sweeps ran)")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(lib_dir(), "sky130_fd_sc_hd__*.lib")))
    print("Liberty files found: %d in %s" % (len(files), lib_dir()))
    if not files:
        raise SystemExit("nothing to read")

    rows, diag = [], []
    for path in files:
        text = open(path, errors="replace").read()
        cell = group(text, "cell", args.cell)
        if cell is None:
            continue
        pin = group(cell, "pin", CLK)
        if pin is None:
            diag.append((os.path.basename(path), "no %s pin; pins are %s" % (
                CLK, ", ".join(sorted(set(re.findall(
                    r"\bpin\s*\(\s*\"?([A-Za-z0-9_]+)", cell))))[:10])))
            continue
        w = pulse_widths(pin)
        if w:
            rows.append((os.path.basename(path), w))
        else:
            hits = [l.strip() for l in pin.splitlines() if "pulse_width" in l]
            diag.append((os.path.basename(path),
                         "no pulse width; lines mentioning it: %s"
                         % (hits[:3] or "none")))

    if not rows:
        print("\nCould not read a pulse width. What each file did contain:")
        for name, why in diag[:6]:
            print("  %-42s %s" % (name, why))
        raise SystemExit("no pulse width available, so this check says nothing "
                         "and the SPICE result stands on its own")

    print("\n%s, clock pulse width the library promises" % args.cell)
    for name, w in rows:
        print("  %-42s high %7.1f ps   low %7.1f ps"
              % (name, w.get("high", float("nan")), w.get("low", float("nan"))))

    want = CORNER_LIB[args.corner]
    hit = [(n, w) for n, w in rows if n == want]
    if not hit:
        raise SystemExit(
            "the %s corner needs %s and it is not among the files read. Picking "
            "a different corner would answer a different question, so this "
            "stops instead." % (args.corner, want))
    ref = hit[0]
    need = ref[1].get("high")
    print()
    print("corner used for the comparison: %s, which is the %s the sweep ran at"
          % (ref[0], args.corner))
    print("narrowest clock high the sweeps delivered: %.1f ps" % args.narrowest)
    if need is None:
        raise SystemExit("that file gives a low width but no high width")
    if args.narrowest >= need:
        print("VERDICT: %.1f ps clears the characterized %.1f ps, so the capture "
              "is one the library stands behind." % (args.narrowest, need))
    else:
        print("VERDICT: %.1f ps is below the characterized %.1f ps. SPICE resolves "
              "it to a clean rail, but the library never promised that width, so "
              "write it up as a possible lost edge rather than a guaranteed "
              "capture. The settle handshake already tolerates one lost count."
              % (args.narrowest, need))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
