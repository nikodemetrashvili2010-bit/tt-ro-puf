#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Read the two Arm B macro logs and re-derive the distributed-RC shift.

`gen_macro_rc_deck.py` writes a lumped deck and a distributed deck for the
hardened macro. This reads what ngspice returned for each, takes the shift
between them, and checks it against the prediction that was written down in
`docs/macro_rc_run_steps.md` before the run.

The logs are archived in `sim/spice/gono/macrorc/`, so this runs from a clone
with no ngspice, no PDK and no network. That is the pattern the supply sweep and
the per-instance run already follow and the RC, mux and boundary sweeps do not.

Two things are checked rather than reported. The measured frequency comes from
`f = `, and the period from `tp = `, and those are two separate lines that ngspice
wrote independently, so f x tp must be 20 by construction of the measurement. And
the shift has to be negative, because both differences between the models load
the ring further: series resistance the lumped deck dropped entirely, and a
coupling capacitor between two antiphase nodes presenting about twice its value
where the lumped deck grounds it and presents one times. A positive shift means
something is wired backwards.

Usage:
    python3 analyze_macro_rc.py
    python3 analyze_macro_rc.py --dir macrorc
    python3 analyze_macro_rc.py --selftest
"""

from __future__ import annotations

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Written down in docs/macro_rc_run_steps.md before the run, from the Arm A fit
# shift = -0.4147 - 0.03961 x ring_cap_fF at the macro's 11.01 fF, and from
# Arm A's plain mean shift. The residual scatter of that fit is 0.159 points.
PREDICTED_FIT = -0.851
PREDICTED_MEAN = -0.971
FIT_RESIDUAL_SD = 0.159

# Independently produced by item 5's supply sweep for Arm B at an ideal supply,
# and quoted in item 5 of docs/hardware_todo.md. Nothing in this deck knows
# about that number, which is what makes the agreement worth anything.
ARMB_IDEAL_SUPPLY_MHZ = 570.616

# gen_macro_deck.py, the original lumped-only prediction, at a 5 ps step over
# 80 ns where these decks step at 1 ps over 140 ns.
ARMB_LUMPED_COARSE_MHZ = 569.5134


class AnalysisError(Exception):
    pass


def read_log(path: str) -> dict:
    """Pull the frequency and the period out of one ngspice log.

    A run that fell over still leaves a log, and a log missing its measurement
    reads as an absent number rather than a wrong one, so both lines are
    required and their consistency is checked rather than assumed.
    """
    if not os.path.exists(path):
        raise AnalysisError(f"missing log {path}")
    txt = open(path).read()

    fm = re.search(r"^f\s*=\s*([0-9.eE+-]+)\s*$", txt, re.M)
    tm = re.search(r"^tp\s+=\s+([0-9.eE+-]+)", txt, re.M)
    if not fm:
        raise AnalysisError(f"{os.path.basename(path)}: no 'f = ' line, so the "
                            f"measurement did not happen")
    if not tm:
        raise AnalysisError(f"{os.path.basename(path)}: no 'tp = ' line")

    f_hz, tp_s = float(fm.group(1)), float(tm.group(1))
    if f_hz <= 0 or tp_s <= 0:
        raise AnalysisError(f"{os.path.basename(path)}: f={f_hz} tp={tp_s}, "
                            f"a ring that oscillates gives neither")

    # The deck measures across 20 periods, so this identity is fixed by the
    # deck and not by the circuit. It catches a log whose two numbers came from
    # different runs, which is what a half-overwritten file looks like.
    cycles = f_hz * tp_s
    if abs(cycles - 20.0) > 0.01:
        raise AnalysisError(
            f"{os.path.basename(path)}: f x tp = {cycles:.4f}, expected 20. "
            f"The frequency and the period do not come from the same run.")

    rows = re.search(r"No\. of Data Rows\s*:\s*(\d+)", txt)
    return dict(path=path, f_MHz=f_hz / 1e6, tp_ns=tp_s * 1e9,
                cycles=cycles, rows=int(rows.group(1)) if rows else None)


def analyze(directory: str) -> dict:
    lumped = read_log(os.path.join(directory, "ro_macro_lumped_out.txt"))
    rc = read_log(os.path.join(directory, "ro_macro_rc_out.txt"))

    shift = 100.0 * (rc["f_MHz"] - lumped["f_MHz"]) / lumped["f_MHz"]
    return dict(
        lumped=lumped, rc=rc, shift_pct=shift,
        gap_vs_ideal_supply=100.0 * (lumped["f_MHz"] - ARMB_IDEAL_SUPPLY_MHZ)
                            / ARMB_IDEAL_SUPPLY_MHZ,
        gap_vs_coarse=100.0 * (lumped["f_MHz"] - ARMB_LUMPED_COARSE_MHZ)
                      / ARMB_LUMPED_COARSE_MHZ,
        sigma_from_fit=abs(shift - PREDICTED_FIT) / FIT_RESIDUAL_SD,
    )


def verdicts(a: dict) -> list[tuple[bool, str]]:
    v = []
    lm, rc = a["lumped"], a["rc"]

    v.append((True, f"lumped      {lm['f_MHz']:.4f} MHz over {lm['tp_ns']:.4f} ns"))
    v.append((True, f"distributed {rc['f_MHz']:.4f} MHz over {rc['tp_ns']:.4f} ns"))

    v.append((lm["rows"] == rc["rows"],
              f"both runs stepped the same transient: {lm['rows']} rows "
              f"against {rc['rows']}"))

    v.append((a["shift_pct"] < 0,
              f"the distributed model is slower, as it has to be: "
              f"{a['shift_pct']:+.3f} %"))

    # The lumped rebuild against a number produced by a different generator.
    v.append((abs(a["gap_vs_ideal_supply"]) < 0.01,
              f"the lumped rebuild reproduces item 5's independent Arm B "
              f"ideal-supply figure of {ARMB_IDEAL_SUPPLY_MHZ} MHz to "
              f"{a['gap_vs_ideal_supply']:+.4f} %"))

    # And against the coarse-step original, where a small gap was predicted.
    v.append((abs(a["gap_vs_coarse"]) < 0.3,
              f"it sits {a['gap_vs_coarse']:+.3f} % from gen_macro_deck.py's "
              f"{ARMB_LUMPED_COARSE_MHZ} MHz, which stepped at 5 ps where these "
              f"step at 1 ps"))

    v.append((a["sigma_from_fit"] < 2.0,
              f"the shift sits {a['sigma_from_fit']:.2f} sigma from the "
              f"{PREDICTED_FIT} % the Arm A fit predicted, on that fit's own "
              f"residual scatter of {FIT_RESIDUAL_SD} points"))

    v.append((min(PREDICTED_FIT, PREDICTED_MEAN) - 0.4 < a["shift_pct"]
              < max(PREDICTED_FIT, PREDICTED_MEAN) + 0.4,
              f"and inside the band the two predictions bracket, "
              f"{PREDICTED_MEAN} to {PREDICTED_FIT} %"))
    return v


def selftest() -> int:
    """Faults that would otherwise read as a result."""
    import tempfile

    GOOD_L = ("No. of Data Rows : 140014\n"
              "tp                  =  3.504985e-08 targ= 1 trig= 2\n"
              "f = 5.706159e+08\n")
    GOOD_R = ("No. of Data Rows : 140014\n"
              "tp                  =  3.533278e-08 targ= 1 trig= 2\n"
              "f = 5.660466e+08\n")

    def d(lumped=GOOD_L, rc=GOOD_R):
        p = tempfile.mkdtemp()
        open(os.path.join(p, "ro_macro_lumped_out.txt"), "w").write(lumped)
        open(os.path.join(p, "ro_macro_rc_out.txt"), "w").write(rc)
        return p

    cases = []

    cases.append(("the archived pair passes every verdict",
                  lambda: all(ok for ok, _ in verdicts(analyze(d()))), True))

    def missing_f():
        try:
            analyze(d(lumped="No. of Data Rows : 10\ntp = 1e-8 targ= 1 trig= 2\n"))
            return False
        except AnalysisError as e:
            return "did not happen" in str(e)
    cases.append(("a log with no frequency line is caught", missing_f, True))

    def inconsistent():
        # f and tp that do not multiply to 20 cycles
        try:
            analyze(d(rc="No. of Data Rows : 140014\n"
                         "tp                  =  1.000000e-08 targ= 1 trig= 2\n"
                         "f = 5.660466e+08\n"))
            return False
        except AnalysisError as e:
            return "do not come from the same run" in str(e)
    cases.append(("f and tp from different runs are caught", inconsistent, True))

    def backwards():
        # distributed faster than lumped: physically impossible here
        swapped = analyze(d(lumped=GOOD_R, rc=GOOD_L))
        return not verdicts(swapped)[3][0]
    cases.append(("a distributed result faster than lumped fails", backwards, True))

    def rows_differ():
        a = analyze(d(rc=GOOD_R.replace("140014", "80014")))
        return not verdicts(a)[2][0]
    cases.append(("two runs with different transient lengths fail",
                  rows_differ, True))

    def drifted():
        # a lumped rebuild that misses the independent reference
        a = analyze(d(lumped=GOOD_L.replace("5.706159e+08", "5.500000e+08")
                                   .replace("3.504985e-08", "3.636364e-08")))
        return not verdicts(a)[4][0]
    cases.append(("a lumped rebuild that misses the independent reference fails",
                  drifted, True))

    def missing_file():
        try:
            analyze(tempfile.mkdtemp())
            return False
        except AnalysisError as e:
            return "missing log" in str(e)
    cases.append(("an absent log is caught", missing_file, True))

    print("selftest")
    bad = 0
    for name, fn, want in cases:
        try:
            got = fn()
        except Exception as exc:                       # noqa: BLE001
            got, name = False, f"{name}  [raised {exc!r}]"
        ok = got == want
        bad += not ok
        print(f"  {'pass' if ok else 'FAIL'}  {name}")
    print(f"{len(cases) - bad} of {len(cases)} selftests pass")
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=os.path.join(HERE, "macrorc"))
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    a = analyze(args.dir)
    v = verdicts(a)
    for ok, line in v:
        print(f"  {'ok  ' if ok else 'FAIL'}  {line}")
    failed = sum(not ok for ok, _ in v)
    print(f"\n{len(v) - failed} of {len(v)} checks pass")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AnalysisError as exc:
        print(f"analyze_macro_rc: {exc}", file=sys.stderr)
        raise SystemExit(2)
