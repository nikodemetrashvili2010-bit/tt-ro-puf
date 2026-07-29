#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Decks for the operating-point and noise-floor question.

Everything else in this directory asks how far apart the sixteen Arm A rings sit
at one operating point. This asks a different question: how much does a reading
move when the operating point moves, and how much does it move when nothing
moves at all.

The reason it matters is that the compensation residual is only interesting if a
real measurement can resolve it. A residual of 0.83 percent means nothing if a
returned count wanders by more than that between windows.

Three sets of decks come out of here, all built from the same shipped netlist
and SPEF as `gen_dualarm_decks.py`, and in fact from that script's own topology
builder so the ring cannot drift between the two:

  noise_vdd_<mV>.spice   sixteen Arm A rings at 1.62, 1.80 and 1.98 V, typical
                         devices, 27 C. Gives the supply pushing figure per ring
                         and, more to the point, says whether the ring-to-ring
                         differences move when the supply does.

  noise_temp_<T>.spice   the same sixteen rings at -40, 0, 85 and 125 C at
                         1.80 V. The 27 C point is the 1.80 V supply deck, so it
                         is not repeated here.

  noise_jitter.spice     three rings only, the lightest, the median and the
                         heaviest by ring capacitance, with every internal node
                         saved and the local slope at the switching threshold
                         measured on a rising and a falling edge at each node.
                         That slope plus the node capacitance is what turns
                         thermal noise into a timing number. No frequency comes
                         out of this deck; it runs at a tenth of the usual
                         timestep and stops early.

The 1.80 V deck is a byte-level clone of the shipped nominal deck apart from the
transient window, so it has to return the archived nominal frequencies. The
analyzer refuses to report anything if it does not.

Usage:
    python3 gen_noise_decks.py
    python3 gen_noise_decks.py --output-dir /tmp/decks
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))

from gen_dualarm_decks import (            # noqa: E402
    NRO, NINV, TAP, SPEF, DEFF, net, outnet, parse_spef, emit_ro,
)
from pdk_paths import atomic_write_text, sky130_spice_paths, spice_path  # noqa: E402

# Supply points, in volts. Plus and minus ten percent around nominal is wider
# than any regulator on the demo board should ever drift, which is the point:
# if the ring-to-ring pattern survives that, it survives the real thing.
SUPPLIES = [1.62, 1.80, 1.98]

# Temperature points, in Celsius. 27 C is covered by the 1.80 V supply deck.
TEMPS = [-40, 0, 85, 125]

# The temperature sweep at 1.80 V came out almost flat, which is the signature
# of a stage biased near the point where a falling threshold voltage and a
# falling mobility cancel. If that is the reason, the cancellation is a property
# of the overdrive and not of the circuit, so moving the supply has to move the
# balance: less overdrive should make the ring speed up with heat, more should
# make it slow down. These four points are that test. Two supplies, the two ends
# of the temperature range, and the 27 C points already measured in between.
GRID = [(1.62, -40), (1.62, 125), (1.98, -40), (1.98, 125)]

# Transient length. The slowest point here is 1.62 V or 125 C, and 120 ns holds
# 25 rising edges at any frequency above 220 MHz, far below anything the corner
# runs produced. The nominal point keeps the shipped deck's 80 ns instead, so
# that deck comes out identical to `dualarm_par.spice` apart from its title and
# has to return the archived nominal frequencies.
TSTOP_NS = 120
TSTOP_NOMINAL_NS = 80

# The slope deck is a different measurement and needs a different step. The band
# it times is a tenth of the supply, which a 555 MHz ring crosses in about four
# picoseconds, so a 5 ps step would put one or two points inside it and the
# answer would be the interpolation rather than the circuit. It runs at 0.5 ps
# instead, and only long enough to reach the tenth edge, which keeps the vector
# file manageable. A finer step also shifts the frequency slightly, which does
# not matter here because this deck is not used for frequency.
TSTOP_JITTER_NS = 40
TSTEP_JITTER_PS = 0.5

# Edge indices for the frequency measurement. These are the shipped deck's
# values and they are not free parameters: changing them would break the
# comparison against the archived nominal log.
RISE_FIRST, RISE_LAST = 5, 25

# The slope at the switching threshold is measured across a narrow band centred
# on midpoint, so it is a local derivative and not a 10-to-90 average.
SLOPE_LO_FRAC, SLOPE_HI_FRAC = 0.45, 0.55

# Edge index for the slope measurement. Late enough that startup is over.
SLOPE_EDGE = 10


def ring_caps(caps):
    """Total ring capacitance per RO in femtofarads, n0 through n30."""
    return {i: sum(caps.get(net(i, k), 0.0) for k in range(NINV + 1)) * 1000.0
            for i in range(NRO)}


# A resistor with a first-order temperature coefficient, driven by a fixed
# current, reads back the temperature ngspice actually used. R(T) = R0 (1 + tc1
# (T - TNOM)) with TNOM 27 C by default, so 1 mA through 1 kohm gives 1.000 V at
# 27 C and 0.01 V per degree away from it. It shares no node with the rings.
PROBE_R0, PROBE_TC1, PROBE_I = 1000.0, 0.01, 1e-3


def probe_lines():
    return ["* temperature readback, isolated from the rings",
            f"Iprobe 0 nprobe DC {PROBE_I:g}",
            f"Rprobe nprobe 0 {PROBE_R0:g} tc1={PROBE_TC1:g}",
            ""]


def probe_temp_from_volts(v):
    return 27.0 + (v / (PROBE_I * PROBE_R0) - 1.0) / PROBE_TC1


def header(title, supply, temp):
    corner, cells = sky130_spice_paths()
    lines = [
        f"* Operating point and noise floor: {title}",
        "* auto-generated by gen_noise_decks.py, ring topology from gen_dualarm_decks.py",
        f".lib {spice_path(corner)} tt",
        f".include {spice_path(cells)}",
    ]
    if temp != 27:
        lines.append(f".temp {temp}")
    lines += [
        f".param SUPPLY={supply:g}",
        "Vdd VPWR 0 {SUPPLY}",
        f"Ven EN 0 PULSE(0 {supply:g} 2n 50p 50p 1 2)",
        "",
    ]
    return "\n".join(lines)


def sweep_deck(title, caps, supply, temp):
    """Sixteen Arm A rings, one operating point, one frequency per ring."""
    tstop = TSTOP_NOMINAL_NS if (supply == 1.80 and temp == 27) else TSTOP_NS
    out = [header(title, supply, temp)]
    for i in range(NRO):
        out += emit_ro(i, caps)
    out.append("")
    out.append(".save " + " ".join(f"v(x{i}_out)" for i in range(NRO)))
    out.append(f".tran 5p {tstop:g}n")
    out.append(".control")
    out.append("run")
    th = supply / 2.0
    for i in range(NRO):
        out.append(f"meas tran tp{i} TRIG v(x{i}_out) VAL={th:g} RISE={RISE_FIRST} "
                   f"TARG v(x{i}_out) VAL={th:g} RISE={RISE_LAST}")
    for i in range(NRO):
        out.append(f"let f{i} = {RISE_LAST - RISE_FIRST} / tp{i}")
    for i in range(NRO):
        out.append(f"print f{i}")
    out.append(".endc")
    out.append(".end")
    return "\n".join(out) + "\n"


def jitter_deck(title, caps, rings, supply=1.80, temp=27):
    """Three rings, every internal node saved, slope at threshold on each node."""
    out = [header(title, supply, temp)]
    for i in rings:
        out += emit_ro(i, caps)
    out.append("")
    saves = []
    for i in rings:
        saves += [f"v(x{i}_n{k})" for k in range(NINV + 1)]
        saves.append(f"v(x{i}_out)")
    out.append(".save " + " ".join(saves))
    out.append(f".tran {TSTEP_JITTER_PS:g}p {TSTOP_JITTER_NS:g}n")
    out.append(".control")
    out.append("run")
    lo, hi = SLOPE_LO_FRAC * supply, SLOPE_HI_FRAC * supply
    for i in rings:
        for k in range(NINV + 1):
            n = f"v(x{i}_n{k})"
            out.append(f"meas tran tr_{i}_{k} TRIG {n} VAL={lo:g} RISE={SLOPE_EDGE} "
                       f"TARG {n} VAL={hi:g} RISE={SLOPE_EDGE}")
            out.append(f"meas tran tf_{i}_{k} TRIG {n} VAL={hi:g} FALL={SLOPE_EDGE} "
                       f"TARG {n} VAL={lo:g} FALL={SLOPE_EDGE}")
    out.append(".endc")
    out.append(".end")
    return "\n".join(out) + "\n"


# Four ways of asking ngspice for a temperature. Which of them the SKY130
# corner library actually lets through is a question about the library, not
# about this circuit, so it gets its own tiny decks that run in a second.
PROBE_MODES = {
    "none":   dict(card=None,             before=False),
    "after":  dict(card=".temp {T:g}",    before=False),
    "before": dict(card=".temp {T:g}",    before=True),
    "option": dict(card=".option temp={T:g}", before=False),
}
PROBE_TEMP = 125.0


def probe_deck(mode, temp=PROBE_TEMP):
    corner, _ = sky130_spice_paths()
    spec = PROBE_MODES[mode]
    card = spec["card"].format(T=temp) if spec["card"] else None
    lines = [f"* temperature mechanism probe: {mode}"]
    if card and spec["before"]:
        lines.append(card)
    lines.append(f".lib {spice_path(corner)} tt")
    if card and not spec["before"]:
        lines.append(card)
    lines += probe_lines()
    lines += [".tran 1n 10n", ".control", "run",
              "meas tran vprobe FIND v(nprobe) AT=5n", ".endc", ".end"]
    return "\n".join(lines) + "\n"


def supply_tag(v):
    return f"{int(round(v * 1000)):d}"


def temp_tag(t):
    return ("m" + str(abs(int(t)))) if t < 0 else f"{int(t):03d}"


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Generate the supply, temperature and slope decks from the "
                    "shipped dual-arm extraction.")
    p.add_argument("--spef", default=SPEF, help="final nominal SPEF")
    p.add_argument("--output-dir", default=HERE, help="where to write the decks")
    p.add_argument("--probe", action="store_true",
                   help="write only the four tiny temperature-mechanism decks")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    spef_path = os.path.abspath(os.path.expanduser(args.spef))
    out_dir = os.path.abspath(os.path.expanduser(args.output_dir))
    if args.probe:
        os.makedirs(out_dir, exist_ok=True)
        for mode in PROBE_MODES:
            atomic_write_text(os.path.join(out_dir, f"tprobe_{mode}.spice"),
                              probe_deck(mode))
        print(f"output directory: {out_dir}")
        print(f"asked for {PROBE_TEMP:g} C four different ways: "
              + ", ".join(f"tprobe_{m}.spice" for m in PROBE_MODES))
        print("run them, then read vprobe: 1.000 V means 27 C and every 0.01 V "
              "above that is one degree, so 125 C reads 1.980 V")
        return

    caps = parse_spef(spef_path)

    missing = [net(i, k) for i in range(NRO) for k in range(NINV + 1)
               if net(i, k) not in caps]
    if missing:
        raise RuntimeError(
            "this SPEF is not a complete Arm A extraction, refusing to write "
            "decks with missing ring loads: " + ", ".join(missing[:8]))

    rc = ring_caps(caps)
    order = sorted(rc, key=lambda i: rc[i])
    picked = [order[0], order[len(order) // 2], order[-1]]

    os.makedirs(out_dir, exist_ok=True)
    written = []
    for v in SUPPLIES:
        name = f"noise_vdd_{supply_tag(v)}.spice"
        atomic_write_text(os.path.join(out_dir, name),
                          sweep_deck(f"16 Arm A rings, tt, 27 C, {v:g} V", caps, v, 27))
        written.append(name)
    for v, tc in GRID:
        name = f"noise_vt_{supply_tag(v)}_{temp_tag(tc)}.spice"
        atomic_write_text(os.path.join(out_dir, name),
                          sweep_deck(f"16 Arm A rings, tt, {tc:g} C, {v:g} V", caps, v, tc))
        written.append(name)
    for t in TEMPS:
        name = f"noise_temp_{temp_tag(t)}.spice"
        atomic_write_text(os.path.join(out_dir, name),
                          sweep_deck(f"16 Arm A rings, tt, {t:g} C, 1.80 V", caps, 1.80, t))
        written.append(name)
    atomic_write_text(
        os.path.join(out_dir, "noise_jitter.spice"),
        jitter_deck("slope at threshold, rings "
                    + ", ".join(str(i) for i in picked), caps, picked))
    written.append("noise_jitter.spice")

    print(f"SPEF: {spef_path}")
    print(f"output directory: {out_dir}")
    print("ring capacitance, fF: "
          f"min RO{picked[0]}={rc[picked[0]]:.2f} "
          f"median RO{picked[1]}={rc[picked[1]]:.2f} "
          f"max RO{picked[2]}={rc[picked[2]]:.2f}")
    print(f"supply points, V: " + ", ".join(f"{v:g}" for v in SUPPLIES))
    print("temperature points, C: " + ", ".join(f"{t:g}" for t in TEMPS)
          + " (27 comes from the 1.80 V deck)")
    print("supply by temperature grid: "
          + ", ".join(f"{v:g} V at {tc:g} C" for v, tc in GRID))
    print(f"transient: {TSTOP_NOMINAL_NS:g} ns at nominal, {TSTOP_NS:g} ns off nominal, "
          f"{TSTOP_JITTER_NS:g} ns at {TSTEP_JITTER_PS:g} ps for the slope deck")
    print("decks written: " + ", ".join(written))


if __name__ == "__main__":
    main()
