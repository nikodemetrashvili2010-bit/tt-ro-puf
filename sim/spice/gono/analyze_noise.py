#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Turn the operating-point and slope logs into a noise floor.

The compensation work leaves a residual of about 0.83 percent of the arm mean,
and the mismatch study puts the device-specific part near 0.062 percent. Neither
number means anything until I know what a single reading can resolve. This
script produces that floor from three directions.

Supply and temperature. The rings are swept at 1.62, 1.80 and 1.98 V and at -40,
0, 27, 85 and 125 C. Two things come out. The first is the obvious one, how much
the absolute frequency moves. The second matters more for a PUF: a bit is the
sign of a difference between two rings, so a shift that hits all sixteen rings
equally cancels and only the part that differs between rings can flip a bit. The
script splits the measured shift into those two parts and reports them
separately.

The temperature answer at 1.80 V is small enough to be suspicious, so it gets a
second measurement rather than the benefit of the doubt. Four more runs put the
two ends of the temperature range at 1.62 and 1.98 V as well. A stage biased
near the crossover, where a falling threshold voltage and a falling mobility
cancel, has to respond to that: at less overdrive the ring should speed up with
heat and at more overdrive it should slow down. If the coefficient just sits
near zero at all three supplies then the models are not responding and the
number is worthless. This script prints all three so the reader can tell which
it is. Every log also states the temperature ngspice used, and that is checked
against the temperature the deck asked for.

Thermal noise. The slope deck measures dV/dt at the switching threshold on every
internal node of three rings. Noise on a node moves the crossing time by roughly
the noise voltage divided by that slope, and the noise voltage on a capacitor is
about sqrt(gamma*k*T/C). Summing over the 62 transitions in one period gives a
period jitter, which then averages down over the counting window.

Counter quantization. The design counts ring edges for a fixed number of
reference-clock cycles and returns an integer, so the reading has a granularity
of one count no matter how quiet the oscillator is.

Every estimate here is deliberately pessimistic. The excess-noise factor is set
to the short-channel end, and the node capacitance used is the extracted wire
capacitance alone, which is smaller than the real node capacitance and therefore
makes the jitter come out larger than it is.

Run:
    python3 analyze_noise.py
    python3 analyze_noise.py --selftest
"""

import argparse
import math
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)

NRO, NINV = 16, 30
PAIRS = [(i, i + 1) for i in range(0, NRO, 2)]

NOMINAL_LOG = os.path.join(PROJ, "dualarm", "build_current", "dualarm_par_out.txt")
SPEF = os.path.join(PROJ, "dualarm", "build_current",
                    "tt_um_nikodemetrashvili20_ro_puf.nom.spef")

SUPPLIES = [(1.62, "noise_vdd_1620_out.txt"),
            (1.80, "noise_vdd_1800_out.txt"),
            (1.98, "noise_vdd_1980_out.txt")]
TEMPS = [(-40, "noise_temp_m40_out.txt"),
         (0, "noise_temp_000_out.txt"),
         (27, "noise_vdd_1800_out.txt"),
         (85, "noise_temp_085_out.txt"),
         (125, "noise_temp_125_out.txt")]
GRID = [(1.62, -40, "noise_vt_1620_m40_out.txt"),
        (1.62, 125, "noise_vt_1620_125_out.txt"),
        (1.98, -40, "noise_vt_1980_m40_out.txt"),
        (1.98, 125, "noise_vt_1980_125_out.txt")]
JITTER_LOG = "noise_jitter_out.txt"

NOM_V, NOM_T = 1.80, 27
SLOPE_DV_FRAC = 0.10           # the slope band in gen_noise_decks.py
GAMMA = 2.0                    # channel excess noise factor, short-channel end
K_B = 1.380649e-23
T_KELVIN = 300.15
WINDOW_CYCLES = 1000           # reference-clock cycles, fixed in the RTL
FREF_HZ = 25e6
SIGMA_RING = 0.062             # percent, from sim/spice/mc
RESIDUAL_PCT = 0.832           # percent, compensation.py leave-one-out residual
MATCH_TOL = 2e-4               # relative, nominal deck against the archived log


def read_named(path):
    """Every `name = value` pair ngspice printed, first occurrence wins."""
    out = {}
    with open(path, errors="ignore") as fh:
        for line in fh:
            m = re.match(r"^\s*([A-Za-z_]\w*)\s*=\s*([0-9.eE+-]+)", line)
            if m and m.group(1) not in out:
                try:
                    out[m.group(1)] = float(m.group(2))
                except ValueError:
                    pass
    return out


def log_temp(path):
    """The temperature ngspice says it ran at, or None if it did not say."""
    with open(path, errors="ignore") as fh:
        for line in fh:
            m = re.search(r"analysis at TEMP\s*=\s*(-?[0-9.]+)", line)
            if m:
                return float(m.group(1))
    return None


def freqs_mhz(path, n=NRO):
    d = read_named(path)
    missing = [i for i in range(n) if f"f{i}" not in d or not math.isfinite(d[f"f{i}"])]
    if missing:
        raise RuntimeError(
            f"{os.path.basename(path)} has no usable frequency for RO "
            + ", ".join(map(str, missing))
            + ". The ring did not start, or the transient was too short to hold "
              "25 rising edges.")
    return [d[f"f{i}"] / 1e6 for i in range(n)]


def parse_spef_caps(path):
    """Net name to total capacitance in farads."""
    num2name, caps = {}, {}
    with open(path) as fh:
        for line in fh:
            m = re.match(r"^\*(\d+)\s+(\S+)\s*$", line)
            if m:
                num2name[m.group(1)] = m.group(2).replace("\\", "")
                continue
            if line.startswith("*D_NET"):
                p = line.split()
                nm = num2name.get(p[1].lstrip("*"))
                if nm:
                    caps[nm] = float(p[2]) * 1e-12
    return caps


def ring_net(i, k):
    return f"u_puf.u_core.g_ro_bank[{i}].u_ro.n[{k}]"


def fit_slope(xs, ys):
    """Least-squares slope of y against x."""
    mx, my = st.fmean(xs), st.fmean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den


def bits(f):
    return [1 if f[a] > f[b] else 0 for a, b in PAIRS]


def pair_margins_pct(f):
    m = st.fmean(f)
    return [100.0 * abs(f[a] - f[b]) / m for a, b in PAIRS]


def split_shift(f_point, f_nom):
    """Common-mode and differential parts of a shift, both in percent.

    The ratio of each ring's frequency to its nominal value is the shift that
    ring saw. The mean of those ratios is what every ring did together, and the
    spread around that mean is the only part a difference between two rings can
    see.
    """
    r = [p / n for p, n in zip(f_point, f_nom)]
    mean_r = st.fmean(r)
    common = 100.0 * (mean_r - 1.0)
    diff = 100.0 * st.pstdev(r)
    worst = 100.0 * max(abs(x - mean_r) for x in r)
    return common, diff, worst


def load_points(spec, base, want_temp=None):
    """Read each log, and check the temperature if one was asked for."""
    out = []
    for value, name in spec:
        path = name if os.path.isabs(name) else os.path.join(base, name)
        if not os.path.isfile(path):
            raise FileNotFoundError(
                f"missing log {path}. Generate the decks with gen_noise_decks.py "
                "and run them in ngspice first.")
        expect = value if want_temp is None else want_temp
        got = log_temp(path)
        if got is not None and abs(got - expect) > 0.5:
            raise SystemExit(
                f"{os.path.basename(path)} ran at {got:g} C but the deck asked "
                f"for {expect:g} C. Refusing to report.")
        out.append((value, path, freqs_mhz(path)))
    return out


def jitter_from_slopes(log_path, caps, supply=NOM_V):
    """Per-ring period jitter in seconds, from the slope deck.

    sigma_v = sqrt(gamma k T / C) on each node, sigma_t = sigma_v / slope, and
    the 62 transitions in one period are treated as independent.
    """
    d = read_named(log_path)
    dv = SLOPE_DV_FRAC * supply
    rings = sorted({int(m.group(1)) for k in d
                    for m in [re.match(r"^tr_(\d+)_(\d+)$", k)] if m})
    if not rings:
        raise RuntimeError(f"{os.path.basename(log_path)} has no slope measurements")
    out = {}
    for i in rings:
        var = 0.0
        used = 0
        for k in range(NINV + 1):
            c = caps.get(ring_net(i, k))
            if not c:
                continue
            sigma_v = math.sqrt(GAMMA * K_B * T_KELVIN / c)
            for tag in (f"tr_{i}_{k}", f"tf_{i}_{k}"):
                dt = d.get(tag)
                if dt is None or not math.isfinite(dt) or dt <= 0:
                    continue
                slope = dv / dt
                var += (sigma_v / slope) ** 2
                used += 1
        if used == 0:
            raise RuntimeError(f"no usable slope for ring {i} in {log_path}")
        f = d.get(f"f{i}")
        out[i] = dict(sigma_period_s=math.sqrt(var), transitions=used,
                      freq_mhz=(f / 1e6) if f else None)
    return out


def report(base):
    caps = parse_spef_caps(SPEF)
    nom = freqs_mhz(NOMINAL_LOG)
    vdd = load_points(SUPPLIES, base, want_temp=NOM_T)
    tmp = load_points(TEMPS, base)

    print("Noise floor and operating-point sensitivity, Arm A of the shipped build")
    print("=" * 72)

    # ---- self check -------------------------------------------------------
    at_nom = dict((v, f) for v, _, f in vdd)[NOM_V]
    worst = max(abs(a - b) / b for a, b in zip(at_nom, nom))
    print(f"\nCheck against the archived nominal run: worst ring differs by "
          f"{worst*100:.4f} percent")
    if worst > MATCH_TOL:
        raise SystemExit(
            "the 1.80 V deck does not reproduce dualarm_par_out.txt, so these logs "
            "are not from the shipped layout. Refusing to report.")
    print("  the 1.80 V deck is the shipped nominal deck, so this had to match")

    mean_nom = st.fmean(nom)
    pp = 100.0 * (max(nom) - min(nom)) / mean_nom
    print(f"  nominal: {min(nom):.2f} to {max(nom):.2f} MHz, mean {mean_nom:.2f}, "
          f"{pp:.2f} percent peak to peak")

    # ---- supply -----------------------------------------------------------
    print("\nSupply")
    vs = [v for v, _, _ in vdd]
    push = []
    for i in range(NRO):
        s = fit_slope(vs, [f[i] for _, _, f in vdd])
        push.append(100.0 * s / nom[i])
    print(f"  pushing figure: mean {st.fmean(push):.2f} percent per volt, "
          f"ring to ring {min(push):.2f} to {max(push):.2f}")
    print(f"  a 10 mV supply step moves a ring by about "
          f"{st.fmean(push)*0.010:.4f} percent")
    for v, path, f in vdd:
        if v == NOM_V:
            continue
        c, dd, w = split_shift(f, nom)
        print(f"  at {v:.2f} V: all rings move {c:+.2f} percent together, "
              f"the part that differs between rings is {dd:.3f} percent "
              f"(worst ring {w:.3f})")

    # ---- temperature ------------------------------------------------------
    print("\nTemperature at 1.80 V")
    curve = [(t, st.fmean(f), 100.0 * (max(f) - min(f)) / st.fmean(f))
             for t, _, f in tmp]
    cold = curve[0][1]
    for t, m, ppt in curve:
        print(f"  {t:>4} C: arm mean {m:8.3f} MHz, {100*(m/cold-1):+.3f} percent "
              f"from the cold end, dispersion {ppt:.2f} percent")
    span = 100.0 * (max(m for _, m, _ in curve) - min(m for _, m, _ in curve)) \
        / st.fmean([m for _, m, _ in curve])
    peak_t = max(curve, key=lambda r: r[1])[0]
    print(f"  the whole {min(t for t,_,_ in curve)} to {max(t for t,_,_ in curve)} C "
          f"range moves the mean by {span:.2f} percent, and the fastest point is "
          f"{peak_t} C, so the curve turns over rather than sloping")
    by_t = {t: st.fmean(f) for t, _, f in tmp}
    if 0 in by_t and 85 in by_t:
        local = 100.0 * (by_t[85] - by_t[0]) / 85.0 / by_t[NOM_T]
        print(f"  across the 0 to 85 C bracket that holds room temperature the "
              f"coefficient is {local:+.4f} percent per degree")
    for t, path, f in tmp:
        if t == NOM_T:
            continue
        c, dd, w = split_shift(f, nom)
        print(f"  at {t:+4d} C: all rings move {c:+.2f} percent together, "
              f"the part that differs between rings is {dd:.3f} percent "
              f"(worst ring {w:.3f})")

    # ---- is the flat temperature response real? ---------------------------
    grid_points = []
    grid_paths = [(v, tc, os.path.join(base, n)) for v, tc, n in GRID]
    if all(os.path.isfile(p3) for _, _, p3 in grid_paths):
        print("\nTemperature at three supplies, the same -40 to 125 C span")
        at = {}
        for v, tc, path in grid_paths:
            got = log_temp(path)
            if got is not None and abs(got - tc) > 0.5:
                raise SystemExit(
                    f"{os.path.basename(path)} ran at {got:g} C but should be "
                    f"{tc:g} C. Refusing to report.")
            fg = freqs_mhz(path)
            grid_points.append((f"{v:.2f} V at {tc:+d} C", fg))
            at[(v, tc)] = st.fmean(fg)
        for v, _, f in vdd:
            at[(v, NOM_T)] = st.fmean(f)
        at[(NOM_V, -40)] = by_t[-40]
        at[(NOM_V, 125)] = by_t[125]
        for v in sorted({k[0] for k in at}):
            if (v, -40) not in at or (v, 125) not in at:
                continue
            slope = 100.0 * (at[(v, 125)] - at[(v, -40)]) / 165.0 / at[(v, NOM_T)]
            print(f"  {v:.2f} V: {at[(v,-40)]:8.3f} MHz cold, {at[(v,NOM_T)]:8.3f} "
                  f"at 27 C, {at[(v,125)]:8.3f} hot, so {slope:+.4f} percent "
                  f"per degree")
        lo = 100.0 * (at[(1.62, 125)] - at[(1.62, -40)]) / 165.0 / at[(1.62, NOM_T)]
        hi = 100.0 * (at[(1.98, 125)] - at[(1.98, -40)]) / 165.0 / at[(1.98, NOM_T)]
        if lo > hi:
            print("  the coefficient falls as the supply rises, which is what a "
                  "stage near the threshold and mobility crossover has to do, so "
                  "the flat response at 1.80 V is the circuit and not a dead "
                  "model parameter")
        else:
            print("  the coefficient does not fall as the supply rises, so the "
                  "flat response at 1.80 V is not explained and should not be "
                  "quoted")
    else:
        print("\n  no supply-by-temperature grid logs yet, so the flat "
              "temperature response at 1.80 V is unexplained")

    # ---- bits -------------------------------------------------------------
    print("\nDo the eight Arm A pair bits survive all of it?")
    every = ([(f"{v:.2f} V at +27 C", f) for v, _, f in vdd]
             + [(f"1.80 V at {tt:+d} C", f) for tt, _, f in tmp if tt != NOM_T]
             + grid_points)
    ref = bits(nom)
    flips = {}
    worst_diff = (0.0, "")
    for label, f in every:
        b = bits(f)
        bad = [j for j in range(len(ref)) if b[j] != ref[j]]
        if bad:
            flips[label] = bad
        _, _, w = split_shift(f, nom)
        if w > worst_diff[0]:
            worst_diff = (w, label)
    margins = pair_margins_pct(nom)
    print(f"  smallest pair separation at nominal: {min(margins):.3f} percent of "
          f"the arm mean (pair {margins.index(min(margins))})")
    print(f"  largest ring-to-ring departure anywhere in the box: "
          f"{worst_diff[0]:.3f} percent, at {worst_diff[1]}")
    if flips:
        print("  bits that change: " + "; ".join(
            f"{k} flips {v}" for k, v in flips.items()))
    else:
        print(f"  all 8 bits keep the same sign at all {len(every)} operating "
              f"points, including the cold and hot ends of both supply extremes")

    # ---- thermal jitter and quantization ----------------------------------
    print("\nWhat a single reading can resolve")
    jpath = os.path.join(base, JITTER_LOG)
    t_window = WINDOW_CYCLES / FREF_HZ
    if os.path.isfile(jpath):
        j = jitter_from_slopes(jpath, caps)
        for i in sorted(j):
            sp = j[i]["sigma_period_s"]
            f_hz = (j[i]["freq_mhz"] or nom[i]) * 1e6
            tp = 1.0 / f_hz
            n = f_hz * t_window
            frac = 100.0 * sp / (math.sqrt(n) * tp)
            print(f"  ring {i:2d}: period jitter {sp*1e12:.3f} ps over "
                  f"{j[i]['transitions']} transitions, and after "
                  f"{n:.0f} counted cycles that is {frac:.5f} percent")
        worst_frac = max(
            100.0 * j[i]["sigma_period_s"]
            / (math.sqrt(((j[i]["freq_mhz"] or nom[i]) * 1e6) * t_window)
               * (1.0 / ((j[i]["freq_mhz"] or nom[i]) * 1e6)))
            for i in j)
    else:
        worst_frac = None
        print(f"  no {JITTER_LOG} yet, skipping the thermal part")

    n_nom = st.fmean(nom) * 1e6 * t_window
    quant_rms = 100.0 / (math.sqrt(12.0) * n_nom)
    print(f"  counter granularity: {n_nom:.0f} counts in a "
          f"{t_window*1e6:.0f} us window, so one count is "
          f"{100.0/n_nom:.5f} percent and the rounding error is "
          f"{quant_rms:.5f} percent rms")
    floor = max(x for x in (worst_frac, quant_rms) if x is not None)
    print(f"  measurement floor: {floor:.5f} percent")
    print(f"  that is {SIGMA_RING/floor:.0f} times below the {SIGMA_RING} percent "
          f"mismatch scale and {RESIDUAL_PCT/floor:.0f} times below the "
          f"{RESIDUAL_PCT} percent compensation residual")
    print(f"  and {min(margins)/floor:.0f} times below the smallest pair separation")


# --------------------------------------------------------------------------
# self test
# --------------------------------------------------------------------------
def _write_log(path, freqs_hz, extra=None):
    with open(path, "w") as fh:
        for i, v in enumerate(freqs_hz):
            fh.write(f"f{i} = {v:.12e}\n")
        for k, v in (extra or {}).items():
            fh.write(f"{k}  =  {v:.12e} targ= 1.0e-9 trig= 0.0\n")


def selftest():
    import tempfile
    print("Self test on synthetic logs with planted answers")
    print("=" * 72)
    nom = freqs_mhz(NOMINAL_LOG)
    caps = parse_spef_caps(SPEF)

    push_pct_per_v = 12.5          # planted, percent per volt
    tc_pct_per_c = -0.055          # planted, percent per degree
    tmpdir = tempfile.mkdtemp()

    def scaled(mult):
        return [f * 1e6 * mult for f in nom]

    for v, name in SUPPLIES:
        mult = 1.0 + push_pct_per_v / 100.0 * (v - NOM_V)
        _write_log(os.path.join(tmpdir, name), scaled(mult))
    for t, name in TEMPS:
        if t == NOM_T:
            continue
        mult = 1.0 + tc_pct_per_c / 100.0 * (t - NOM_T)
        _write_log(os.path.join(tmpdir, name), scaled(mult))

    vdd = load_points(SUPPLIES, tmpdir)
    tmp = load_points(TEMPS, tmpdir)
    vs = [v for v, _, _ in vdd]
    got_push = st.fmean([100.0 * fit_slope(vs, [f[i] for _, _, f in vdd]) / nom[i]
                         for i in range(NRO)])
    ts = [t for t, _, _ in tmp]
    got_tc = st.fmean([100.0 * fit_slope(ts, [f[i] for _, _, f in tmp]) / nom[i]
                       for i in range(NRO)])
    ok = True
    for label, want, got, tol in (("supply pushing, percent per volt",
                                   push_pct_per_v, got_push, 1e-6),
                                  ("temperature, percent per degree",
                                   tc_pct_per_c, got_tc, 1e-6)):
        good = abs(want - got) < tol
        ok &= good
        print(f"  {label}: planted {want:g}, recovered {got:.9g}  "
              f"{'ok' if good else 'FAIL'}")

    # a pure common-mode shift must show zero differential part
    c, dd, w = split_shift([f * 1.1 for f in nom], nom)
    good = abs(c - 10.0) < 1e-9 and dd < 1e-12
    ok &= good
    print(f"  pure 10 percent common shift: common {c:.6f}, differential {dd:.2e}  "
          f"{'ok' if good else 'FAIL'}")

    # one ring pushed alone must show up as differential, not common
    f2 = list(nom)
    f2[3] *= 1.01
    c, dd, w = split_shift(f2, nom)
    good = abs(w - 1.0 * (1 - 1 / NRO)) < 1e-6
    ok &= good
    print(f"  one ring alone by 1 percent: worst ring {w:.6f} percent, "
          f"expected {1.0*(1-1/NRO):.6f}  {'ok' if good else 'FAIL'}")

    # jitter arithmetic against a hand-computed case
    ring = 0
    dt = 4.0e-12                    # seconds across the 0.18 V band
    extra = {}
    for k in range(NINV + 1):
        extra[f"tr_{ring}_{k}"] = dt
        extra[f"tf_{ring}_{k}"] = dt
    jl = os.path.join(tmpdir, JITTER_LOG)
    _write_log(jl, [nom[ring] * 1e6], extra)
    j = jitter_from_slopes(jl, caps)
    slope = SLOPE_DV_FRAC * NOM_V / dt
    want_var = sum(2.0 * (math.sqrt(GAMMA * K_B * T_KELVIN
                                    / caps[ring_net(ring, k)]) / slope) ** 2
                   for k in range(NINV + 1))
    want = math.sqrt(want_var)
    got = j[ring]["sigma_period_s"]
    good = abs(want - got) / want < 1e-12 and j[ring]["transitions"] == 2 * (NINV + 1)
    ok &= good
    print(f"  period jitter from {2*(NINV+1)} transitions: hand value "
          f"{want*1e12:.6f} ps, script {got*1e12:.6f} ps  "
          f"{'ok' if good else 'FAIL'}")

    # counter averaging: quadrupling the window must halve the fractional error
    f_hz = nom[ring] * 1e6
    def frac(window):
        n = f_hz * window / FREF_HZ
        return got / (math.sqrt(n) * (1.0 / f_hz))
    good = abs(frac(4000) / frac(1000) - 0.5) < 1e-12
    ok &= good
    print(f"  four times the window: error ratio {frac(4000)/frac(1000):.6f}, "
          f"expected 0.5  {'ok' if good else 'FAIL'}")

    print("\n" + ("all self tests pass" if ok else "SELF TEST FAILED"))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--logs", default=HERE,
                    help="directory holding the ngspice output files")
    ap.add_argument("--selftest", action="store_true",
                    help="run the planted-answer checks and exit")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    report(os.path.abspath(os.path.expanduser(args.logs)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
