#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""How hard the clock can pull a ring, with the clock switching beside it.

Every deck in this directory grounds a coupling whose far end is outside
the ring, as if the neighbour never moved. For another ring that is right,
since only one runs at a time. For the clock tree and the flops that change
on its edges it is not: they switch through every window, and
clock_neighbours.py found the clock tree beside eleven routed rings, C08
the most at 0.760 fF, and the window timer's two low bits beside C12 at
1.388 fF.

This takes gen_rc_decks.py's distributed deck of one ring, its own parser,
resistors and couplings as they are, and changes one thing. A coupling
whose far end is on a named aggressor net goes to a node driven by a
square wave instead of to ground. The source is ideal and swings the whole
supply, so each edge pushes the most charge that capacitor can carry. Its
edges are 100 ps unless told otherwise; how fast they are matters too, see
below.

A ring pulled toward the n-th harmonic of a square wave locks when it runs
within K of it, and runs free outside. K is what this measures. With the
square wave at exactly f0/n, f0 the ring's own frequency from the reference
deck, the ring's frequency moves by an amount that depends on psi, the
phase between the two, and K is the most it moves. Eight decks, or as many
as --phases says, start the square wave that share of a ring period apart,
so psi steps round the circle; each is read over a whole number of the
square wave's periods. read gives the first harmonic of what comes back
and the largest single change. n odd, because a square wave of even duty
has no even harmonics; a skewed duty brings them back, but two edges
pulling together, which is what an odd n gives, is the most one period of
the wave can do.

Where the coupling lands matters more than how much there is. Two stages
in a row switch opposite ways, so charge spread evenly along a run of
stages mostly undoes itself: C08 has the most clock wire beside it, about
0.1 fF on each of eight stages in a row, and shows nothing. C11 has its
0.489 fF on one node, the NAND's input, and nothing undoes it. A spike in
the phase sweep is narrower than an eighth of a ring period, so --phases
takes more, --offset starts a second set halfway between the first's, and
--only runs the few phases around a spike. --edge-ps sets the edge rate,
which moves how much of an edge's charge lands while a stage switches.
--swing multiplies the swing, for a pull under the simulator's noise.
--loop-only grounds the couplings to the ring's output net beyond the tap
buffer, which is in the deck since it is what gets measured.

Decks:

  ref       the aggressor held at 0 V. The same ring as gen_rc_decks.py
            builds; its frequency has to match the archived log
  pJ        the square wave at f0/n, delayed J/phases of a ring period
  small_pJ  as pJ at 1/100 of the swing, for the noise floor

Run, from sim/spice/gono/:

  python3 inject.py make --arm C --ro 8 --corner tt \\
      --aggressor clknet_4_15_0_clk --n 11 --out inject3/C08_tt_clk
  python3 inject.py run inject3/C08_tt_clk         (ngspice, ref first)
  python3 inject.py read inject3/C08_tt_clk        (K, from the crossings)

make writes ref.spice and, once ref has run, the phase decks with the
frequency it measured. run keeps each deck's log and its rising crossings
at half the supply in <deck>_cross.txt, and deletes the waveform. read
needs only the crossings. For the archive in inject3/: check makes every
folder's decks again from the SPEF and compares them with the files, and
table writes one row a folder, both without ngspice or a PDK; selftest
plants faults for both.
"""

import argparse
import contextlib
import glob
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))
import gen_rc_decks as rc  # noqa: E402
from pdk_paths import atomic_write_text, sky130_spice_paths, spice_path  # noqa

SPEF = os.path.join(PROJ, "dualarm", "build_armc",
                    "tt_um_nikodemetrashvili20_ro_puf.nom.spef")
PHASES = 8
EDGE_PS = 100        # rise and fall of the aggressor, ps
SETTLE_NS = 30.0     # crossings before this are startup
SMALL = 0.01         # swing of the small decks, as a share of the supply
# ngspice's default reltol, 1e-3, moves this ring's frequency by tens of ppm
# between two circuits that are electrically the same: C08's archived deck
# and ref here, whose outside couplings go to a 0 V source instead of to
# ground, come out 9.3 ppm apart at 1e-3, 3.7 at 1e-4 and 0.5 at 1e-5. The
# pull is a difference between decks of one structure, and the small decks
# measure what is left of the noise.
RELTOL = 1e-4


def partner_nets(nets):
    """(instance, pin) -> net id, from every net's *CONN list."""
    out = {}
    for num, net in nets.items():
        for inst, pin, _ in net["conn"]:
            out[(inst, pin)] = num
    return out


def outside_net(node, nets, pins):
    """The net a SPEF node outside the ring belongs to, or None."""
    base, _, rest = node.lstrip("*").partition(":")
    if base in nets and rest.isdigit():
        return base
    return pins.get((base, rest))


def body(ro, arm, names, nets, aggressors, loop_only=False):
    """The ring's RC network with the aggressors' couplings on AGG nodes.

    The ring's output net, beyond the tap buffer, is in the deck too, since
    it is what gets measured. loop_only grounds its couplings, so only the
    31 loop nets see the aggressor. Returns (lines, coupling pF per
    aggressor on the loop, stats with out_pf, the output net's)."""
    labels = rc.ring_nets(names, ro, arm)
    missing = [l for l in ["n%d" % k for k in range(rc.NINV + 1)]
               if l not in labels]
    if missing:
        raise SystemExit("oscillator %d: SPEF lacks ring nets %s"
                         % (ro, missing[:5]))
    pins = partner_nets(nets)
    by_name = {}
    for i, a in enumerate(aggressors):
        hits = [k for k, v in names.items() if v == a and k in nets]
        if len(hits) != 1:
            raise SystemExit("aggressor %s: %d nets by that name"
                             % (a, len(hits)))
        by_name[hits[0]] = i
    lines, seen = [], {}
    agg_pf = [0.0] * len(aggressors)
    st = dict(res=0, cg=0, ccoup=0, cx=0, cagg=0, out_pf=0.0)
    for lbl, num in sorted(labels.items()):
        net = nets[num]
        for a, b, ohm in net["res"]:
            na = rc.node_name(a, names, ro, arm)
            nb = rc.node_name(b, names, ro, arm)
            if na is None or nb is None or na == nb:
                continue
            lines.append("R%s_%d %s %s %.4f" % (lbl, st["res"], na, nb, ohm))
            st["res"] += 1
        for a, b, pf in net["caps"]:
            na = rc.node_name(a, names, ro, arm)
            nb = rc.node_name(b, names, ro, arm) if b else None
            if na is None and nb is None:
                continue
            if b is None:
                lines.append("Cg%d %s 0 %.6e" % (st["cg"], na, pf * 1e-12))
                st["cg"] += 1
            elif na is not None and nb is not None:
                key = (min(na, nb), max(na, nb))
                if key in seen:
                    continue
                seen[key] = pf
                lines.append("Cc%d %s %s %.6e"
                             % (st["ccoup"], na, nb, pf * 1e-12))
                st["ccoup"] += 1
            else:
                keep = na if na is not None else nb
                far = b if na is not None else a
                other = outside_net(far, nets, pins)
                if other in by_name and lbl == "out":
                    st["out_pf"] += pf
                if other in by_name and not (loop_only and lbl == "out"):
                    i = by_name[other]
                    if lbl != "out":
                        agg_pf[i] += pf
                    lines.append("Ca%d %s AGG%d %.6e"
                                 % (st["cagg"], keep, i, pf * 1e-12))
                    st["cagg"] += 1
                else:
                    lines.append("Cx%d %s 0 %.6e" % (st["cx"], keep,
                                                     pf * 1e-12))
                    st["cx"] += 1
    return lines, agg_pf, st


def deck(cfg, sources, name, pdk=None):
    """The deck text. pdk is the (.lib, .include) pair of quoted paths, or
    None for the ones PDK_ROOT names."""
    if pdk is None:
        corner, cellspice = sky130_spice_paths()
        pdk = (spice_path(corner), spice_path(cellspice))
    cn = rc.CORNERS[cfg["corner"]]
    v = cn["supply"]
    head = ["* Arm %s oscillator %d at %s, the ring's RC network from the"
            " SPEF," % (cfg["arm"], cfg["ro"], cfg["corner"]),
            "* aggressors %s" % ", ".join(cfg["aggressors"]),
            "* auto-generated by inject.py, deck %s" % name,
            ".lib %s %s" % (pdk[0], cn["section"]),
            ".include %s" % pdk[1]]
    if cn["temp"] != 27:
        head.append(".temp %g" % cn["temp"])
    head += [".param SUPPLY=%g" % v,
             "Vdd VPWR 0 {SUPPLY}",
             "Ven EN 0 PULSE(0 %g 2n 50p 50p 1 2)" % v]
    head += ["Vagg%d AGG%d 0 %s" % (i, i, s) for i, s in enumerate(sources)]
    lines = cfg["_body"]
    half = v / 2
    tail = ["",
            ".options reltol=%g" % RELTOL,
            ".save v(buf_X)",
            ".tran 1p %gn" % cfg["tran_ns"],
            ".control",
            "run",
            "meas tran tp TRIG v(buf_X) VAL=%g RISE=5 TARG v(buf_X) VAL=%g"
            " RISE=25" % (half, half),
            "let f = 20 / tp",
            "print f",
            "wrdata %s_wave.txt v(buf_X)" % name,
            ".endc",
            ".end"]
    return "\n".join(head + [""] + rc.cells(cfg["ro"], False, cfg["arm"])
                     + [""] + lines + tail) + "\n"


def square(v, f, td_s, scale=1.0, edge_ps=EDGE_PS):
    """PULSE for a square wave of even duty at f, first rise at td_s."""
    per = 1.0 / f
    tr = edge_ps * 1e-12
    pw = per / 2 - tr
    return ("PULSE(0 %.6g %.9e %.3e %.3e %.9e %.9e)"
            % (v * scale, td_s, tr, tr, pw, per))


def load_cfg(out):
    with open(os.path.join(out, "config.json")) as fh:
        return json.load(fh)


def make(args):
    path = os.path.join(args.out, "config.json")
    if os.path.exists(path):
        cfg = load_cfg(args.out)
    elif args.check:
        raise SystemExit("%s: no config.json to check against" % args.out)
    else:
        if args.n % 2 == 0 and not args.allow_even:
            raise SystemExit("--n %d is even; use an odd harmonic, or"
                             " --allow-even for the control" % args.n)
        os.makedirs(args.out, exist_ok=True)
        cfg = dict(arm=args.arm, ro=args.ro, corner=args.corner,
                   aggressors=args.aggressor.split(","), n=args.n,
                   tran_ns=args.tran_ns, no_small=args.no_small,
                   reltol=RELTOL, spef=os.path.relpath(args.spef, args.out))
        if args.swing != 1.0:
            cfg["swing"] = args.swing
        if args.phases != PHASES:
            cfg["phases"] = args.phases
        if args.edge_ps != EDGE_PS:
            cfg["edge_ps"] = args.edge_ps
        if args.loop_only:
            cfg["loop_only"] = True
        if args.offset:
            cfg["offset"] = args.offset
        if args.only:
            cfg["only"] = sorted(set(int(x) for x in args.only.split(",")))
        atomic_write_text(path, json.dumps(cfg, indent=1) + "\n")
    names, nets = rc.parse_spef(os.path.join(args.out, cfg["spef"]))
    lines, agg_pf, st = body(cfg["ro"], cfg["arm"], names, nets,
                             cfg["aggressors"], cfg.get("loop_only", False))
    cfg["_body"] = lines
    v = rc.CORNERS[cfg["corner"]]["supply"]
    quiet = ["DC 0"] * len(cfg["aggressors"])
    # A check needs no PDK: the two paths come from the archived ref, and
    # everything else is made again.
    pdk = archived_pdk(args.out) if args.check else None
    decks = [("ref", deck(cfg, quiet, "ref", pdk))]
    print("%s: %d resistors, %d grounded caps, %d inside couplings, %d"
          " outside grounded, %d on aggressors"
          % (shown(args.out), st["res"], st["cg"], st["ccoup"], st["cx"],
             st["cagg"]))
    for a, pf in zip(cfg["aggressors"], agg_pf):
        print("  %s: %.3f fF to the loop" % (a, pf * 1e3))
    if st["out_pf"]:
        print("  and %.3f fF to the output net beyond the tap, %s"
              % (st["out_pf"] * 1e3, "grounded" if cfg.get("loop_only")
                 else "driven"))
    ref = os.path.join(args.out, "ref_cross.txt")
    if os.path.exists(ref):
        f0 = frequency(read_cross(ref), cfg)[0]
        t0 = 1.0 / f0
        phases = cfg.get("phases", PHASES)
        swing = cfg.get("swing", 1.0)
        edge = cfg.get("edge_ps", EDGE_PS)
        shift = cfg.get("offset", 0.0)
        for j in cfg.get("only") or range(phases):
            td = 1e-9 + (j + shift) * t0 / phases if shift else (
                1e-9 + j * t0 / phases)
            tags = (("p", swing),) if cfg.get("no_small") else (
                ("p", swing), ("small_p", SMALL))
            for tag, scale in tags:
                srcs = [square(v, f0 / cfg["n"], td, scale, edge)
                        for _ in cfg["aggressors"]]
                name = "%s%d" % (tag, j)
                decks.append((name, deck(cfg, srcs, name, pdk)))
        print("  f0 %.6f MHz, square wave at f0/%d = %.6f MHz, %d phases,"
              " %g ps edges%s"
              % (f0 / 1e6, cfg["n"], f0 / cfg["n"] / 1e6, phases, edge,
                 ", %g times the supply" % swing if swing != 1.0 else ""))
    elif not args.check:
        print("  ref not run yet; run it, then make again for the phases")
    if args.check:
        # The archived decks against what the SPEF and the archived ref
        # give today, byte for byte.
        differ = []
        for name, text in decks:
            p = os.path.join(args.out, name + ".spice")
            if not os.path.exists(p):
                differ.append(name + " missing")
                continue
            with open(p) as fh:
                if fh.read() != text:
                    differ.append(name)
        made = set(name for name, _ in decks)
        extra = sorted(os.path.basename(p)[:-6] for p in
                       glob.glob(os.path.join(args.out, "*.spice"))
                       if os.path.basename(p)[:-6] not in made
                       and not os.path.basename(p).startswith("portable_"))
        print("  %d decks made again, %s%s"
              % (len(decks), "differ: " + ", ".join(differ) if differ
                 else "every one the same as the file",
                 "; not made: " + ", ".join(extra) if extra else ""))
        return 1 if differ or extra else 0
    for name, text in decks:
        atomic_write_text(os.path.join(args.out, name + ".spice"), text)
    return 0


def archived_pdk(out):
    """The quoted .lib and .include paths in the archived ref.spice."""
    lib = inc = None
    with open(os.path.join(out, "ref.spice")) as fh:
        for line in fh:
            if line.startswith(".lib ") and lib is None:
                lib = line[5:].rsplit(" ", 1)[0]
            elif line.startswith(".include ") and inc is None:
                inc = line[9:].rstrip("\n")
    if lib is None or inc is None:
        raise SystemExit("%s: ref.spice has no .lib or no .include line"
                         % shown(out))
    return lib, inc


def shown(out):
    """The folder as the output names it, from the project root when it is
    inside it, so two machines print the same."""
    rel = os.path.relpath(out, PROJ)
    return out if rel.startswith("..") else rel


def crossings(path, level):
    """Rising crossings of level in a wrdata file, linearly interpolated."""
    out, prev = [], None
    with open(path) as fh:
        for line in fh:
            p = line.split()
            if len(p) < 2:
                continue
            t, y = float(p[0]), float(p[1])
            if prev is not None and prev[1] < level <= y:
                t0, y0 = prev
                out.append(t0 + (level - y0) * (t - t0) / (y - y0))
            prev = (t, y)
    return out


def read_cross(path):
    with open(path) as fh:
        return [float(l) for l in fh if l.strip() and not l.startswith("#")]


def frequency(cross, cfg, periods=None):
    """(f, first, count) over whole periods of the square wave after the
    settle time: n ring periods for each period of the wave."""
    start = next(i for i, t in enumerate(cross) if t >= SETTLE_NS * 1e-9)
    avail = len(cross) - 1 - start
    q = periods or avail // cfg["n"]
    m = q * cfg["n"]
    if q < 1 or m > avail:
        raise SystemExit("not enough crossings: %d after the settle time,"
                         " %d wanted" % (avail, m))
    return m / (cross[start + m] - cross[start]), start, m


def per_period(cross, ref, cfg, q):
    """Each period of the square wave in the read, as ppm from the same
    period of the reference. The pull moves the ring's phase while it is
    read, so near a spike the read's average sits under the steepest
    single period."""
    n = cfg["n"]
    a = next(i for i, t in enumerate(cross) if t >= SETTLE_NS * 1e-9)
    b = next(i for i, t in enumerate(ref) if t >= SETTLE_NS * 1e-9)
    return [1e6 * ((ref[b + (k + 1) * n] - ref[b + k * n])
                   / (cross[a + (k + 1) * n] - cross[a + k * n]) - 1.0)
            for k in range(q)]


def run(args):
    ngspice = os.environ.get("NGSPICE", "ngspice")
    level = rc.CORNERS[load_cfg(args.out)["corner"]]["supply"] / 2
    decks = sorted(glob.glob(os.path.join(args.out, "*.spice")))
    if args.only:
        decks = [d for d in decks if os.path.basename(d)[:-6] in args.only]
    for d in decks:
        name = os.path.basename(d)[:-6]
        cross = os.path.join(args.out, name + "_cross.txt")
        if os.path.exists(cross) and not args.again:
            continue
        log = os.path.join(args.out, name + "_out.txt")
        r = subprocess.run([sys.executable,
                            os.path.join(HERE, "..", "run_ngspice.py"), d,
                            "--log", log], env=dict(os.environ,
                                                    NGSPICE=ngspice))
        wave = os.path.join(args.out, name + "_wave.txt")
        if r.returncode != 0 or not os.path.exists(wave):
            raise SystemExit("%s: ngspice failed, see %s" % (name, log))
        xs = crossings(wave, level)
        with open(cross, "w") as fh:
            fh.write("# rising crossings of v(buf_X) at %g V, s\n" % level)
            fh.writelines("%.15e\n" % t for t in xs)
        os.remove(wave)
        print("%s: %d crossings" % (name, len(xs)))
    return 0


def amplitude(df):
    """First harmonic of df over the phase steps: (amplitude, offset)."""
    n = len(df)
    c = sum(d * math.cos(2 * math.pi * j / n) for j, d in enumerate(df))
    s = sum(d * math.sin(2 * math.pi * j / n) for j, d in enumerate(df))
    return 2.0 / n * math.hypot(c, s), sum(df) / n


def results(out, cfg):
    """f0 and, for each set of phase decks that has run, the frequency
    change by phase in ppm, its first harmonic (the pull) and its mean."""
    ref = read_cross(os.path.join(out, "ref_cross.txt"))
    f0, start, m = frequency(ref, cfg)
    res = {"f0": f0, "periods": m, "ref": ref}
    js = cfg.get("only") or list(range(cfg.get("phases", PHASES)))
    for tag in ("p", "small_p"):
        df, steps = [], []
        for j in js:
            path = os.path.join(out, "%s%d_cross.txt" % (tag, j))
            if not os.path.exists(path):
                break
            cross = read_cross(path)
            f = frequency(cross, cfg, m // cfg["n"])[0]
            df.append(1e6 * (f / f0 - 1.0))
            steps.extend(per_period(cross, ref, cfg, m // cfg["n"]))
        if len(df) != len(js):
            continue
        if cfg.get("only"):
            # Part of the circle has no first harmonic and no mean, so the
            # largest change is taken from the reference itself.
            res[tag] = dict(df_ppm=df, phases_run=js, amp_ppm=None,
                            offset_ppm=None,
                            peak_ppm=max(abs(d) for d in df),
                            steepest_ppm=max(abs(d) for d in steps))
            continue
        amp, off = amplitude(df)
        res[tag] = dict(df_ppm=df, amp_ppm=amp, offset_ppm=off,
                        peak_ppm=max(abs(d - off) for d in df),
                        steepest_ppm=max(abs(d - off) for d in steps))
    return res


def read(args):
    cfg = load_cfg(args.out)
    res = results(args.out, cfg)
    f0, m, ref = res.pop("f0"), res.pop("periods"), res.pop("ref")
    print("%s: Arm %s ring %d at %s, %s, n = %d, %g ps edges%s"
          % (shown(args.out), cfg["arm"], cfg["ro"], cfg["corner"],
             ", ".join(cfg["aggressors"]), cfg["n"],
             cfg.get("edge_ps", EDGE_PS),
             ", %g times the swing" % cfg["swing"] if "swing" in cfg
             else ""))
    print("  ref %.6f MHz over %d periods" % (f0 / 1e6, m))
    if len(ref) > 25:
        f20 = 20.0 / (ref[24] - ref[4])
        print("  ref over rises 5 to 25, the archived deck's measure: %.6e"
              % f20)
    for tag in ("p", "small_p"):
        if tag not in res:
            continue
        r = res[tag]
        if r["amp_ppm"] is None:
            print("  %-8s ppm at phases %s of %d: %s" % (
                tag, ",".join(str(j) for j in r["phases_run"]),
                cfg.get("phases", PHASES),
                " ".join("%+.2f" % d for d in r["df_ppm"])))
            print("  %-8s largest change from the reference %.2f ppm,"
                  " in a single period of the wave %.2f"
                  % (tag, r["peak_ppm"], r["steepest_ppm"]))
            continue
        print("  %-8s ppm by phase: %s" % (tag, " ".join(
            "%+.2f" % d for d in r["df_ppm"])))
        print("  %-8s pull amplitude %.2f ppm, offset %+.2f ppm, largest"
              " %.2f, in a single period of the wave %.2f"
              % (tag, r["amp_ppm"], r["offset_ppm"], r["peak_ppm"],
                 r["steepest_ppm"]))
    if ("p" in res and "small_p" in res and res["p"]["amp_ppm"]
            and res["small_p"]["amp_ppm"]):
        print("  full over small: %.1f (the swing is %.0f times)"
              % (res["p"]["amp_ppm"] / res["small_p"]["amp_ppm"],
                 1.0 / SMALL))
    if args.json:
        res["f0"] = f0
        with open(args.json, "w") as fh:
            json.dump(res, fh, indent=1)
    return 0


TABLE = ("config", "arm", "ro", "corner", "aggressor", "loop_ff", "out_ff",
         "out_driven", "swing", "edge_ps", "n", "phases", "offset", "run",
         "f0_mhz", "square_mhz", "pull_ppm", "offset_ppm", "peak_ppm",
         "steepest_ppm", "small_pull_ppm", "full_over_small")


def table(args):
    """One row a folder under args.dir, from its crossings and the SPEF."""
    spefs, rows = {}, []
    for path in sorted(glob.glob(os.path.join(args.dir, "*",
                                              "config.json"))):
        out = os.path.dirname(path)
        cfg = load_cfg(out)
        sp = os.path.normpath(os.path.join(out, cfg["spef"]))
        if sp not in spefs:
            spefs[sp] = rc.parse_spef(sp)
        names, nets = spefs[sp]
        _, agg_pf, st = body(cfg["ro"], cfg["arm"], names, nets,
                             cfg["aggressors"], cfg.get("loop_only", False))
        res = results(out, cfg)
        if "p" not in res:
            raise SystemExit("%s: the phase decks have not all run"
                             % shown(out))
        small = res.get("small_p")
        rows.append([os.path.basename(out), cfg["arm"], cfg["ro"],
                     cfg["corner"], "+".join(cfg["aggressors"]),
                     "%.3f" % (1e3 * sum(agg_pf)),
                     "%.3f" % (1e3 * st["out_pf"]),
                     "no" if cfg.get("loop_only") or not st["out_pf"]
                     else "yes",
                     "%g" % cfg.get("swing", 1.0),
                     "%g" % cfg.get("edge_ps", EDGE_PS), cfg["n"],
                     cfg.get("phases", PHASES), "%g" % cfg.get("offset", 0.0),
                     len(cfg.get("only") or range(cfg.get("phases", PHASES))),
                     "%.4f" % (res["f0"] / 1e6),
                     "%.4f" % (res["f0"] / cfg["n"] / 1e6),
                     "" if res["p"]["amp_ppm"] is None
                     else "%.2f" % res["p"]["amp_ppm"],
                     "" if res["p"]["offset_ppm"] is None
                     else "%+.2f" % res["p"]["offset_ppm"],
                     "%.2f" % res["p"]["peak_ppm"],
                     "%.2f" % res["p"]["steepest_ppm"],
                     "%.3f" % small["amp_ppm"]
                     if small and small["amp_ppm"] is not None else "",
                     "%.1f" % (res["p"]["amp_ppm"] / small["amp_ppm"])
                     if small and small["amp_ppm"] and res["p"]["amp_ppm"]
                     else ""])
    if not rows:
        raise SystemExit("%s: no folder with a config.json" % args.dir)
    text = "".join(",".join(str(x) for x in r) + "\n"
                   for r in [list(TABLE)] + rows)
    if args.csv:
        atomic_write_text(args.csv, text)
    else:
        sys.stdout.write(text)
    return 0


def check(args):
    """make --check on every folder under args.dir."""
    bad = 0
    folders = sorted(os.path.dirname(p) for p in glob.glob(
        os.path.join(args.dir, "*", "config.json")))
    for out in folders:
        bad += make(argparse.Namespace(out=out, check=True))
    if not folders:
        raise SystemExit("%s: no folder with a config.json" % args.dir)
    print("%d folders, %d with decks that differ" % (len(folders), bad))
    return 1 if bad else 0


def selftest(args):
    """The arithmetic on planted inputs, and a planted change in an
    archived deck caught by the check."""
    fails = []

    def expect(ok, what):
        print("  %s %s" % ("ok  " if ok else "FAIL", what))
        if not ok:
            fails.append(what)

    df = [2.0 + 5.0 * math.sin(2 * math.pi * j / 16 + 0.7)
          for j in range(16)]
    amp, off = amplitude(df)
    expect(abs(amp - 5.0) < 1e-9 and abs(off - 2.0) < 1e-9,
           "a 5 ppm pull on a 2 ppm offset reads 5 and 2")
    f = 571.56e6
    with tempfile.TemporaryDirectory() as tmp:
        wave = os.path.join(tmp, "wave.txt")
        with open(wave, "w") as fh:
            for k in range(20001):
                t = k * 1e-12
                fh.write("%.15e %.12f\n"
                         % (t, 0.9 + 0.9 * math.sin(2 * math.pi * f * t)))
        xs = crossings(wave, 0.9)
    want = [j / f for j in range(1, int(20e-9 * f) + 1)]
    expect(len(xs) == len(want)
           and max(abs(x - w) for x, w in zip(xs, want)) < 1e-15,
           "%d rising crossings of a sampled sine, each within 1 fs"
           % len(want))
    cross = [k / f for k in range(1, 120)]
    fr, start, m = frequency(cross, {"n": 11})
    expect(abs(fr / f - 1.0) < 1e-12 and m % 11 == 0
           and cross[start] >= SETTLE_NS * 1e-9,
           "frequency over whole periods of the wave, after the settle")
    slow = cross[:start + 1] + [cross[start] + (k / f) * (1 + 1e-5)
                                for k in range(1, 120 - start - 1)]
    fs = frequency(slow, {"n": 11}, m // 11)[0]
    expect(abs(1e6 * (fs / f - 1.0) + 10.0) < 1e-3,
           "a ring planted 10 ppm slow reads -10 ppm")
    n, base = 11, cross[start]
    late = [t if t <= base + n / f + 1e-15 else
            t + (t - (base + n / f)) * 1e-5 for t in cross]
    steps = per_period(late, cross, {"n": 11}, 2)
    expect(abs(steps[0]) < 1e-6 and abs(steps[1] + 10.0) < 1e-3,
           "a second period planted 10 ppm slow, and only the second")
    src = os.path.join(HERE, "inject3", "C08_tt_clk")
    with tempfile.TemporaryDirectory() as tmp:
        dst = os.path.join(tmp, "C08_tt_clk")
        shutil.copytree(src, dst)
        cfg = load_cfg(dst)
        cfg["spef"] = os.path.normpath(os.path.join(src, cfg["spef"]))
        atomic_write_text(os.path.join(dst, "config.json"),
                          json.dumps(cfg, indent=1) + "\n")

        def quiet_check():
            with contextlib.redirect_stdout(io.StringIO()):
                return make(argparse.Namespace(out=dst, check=True))
        expect(quiet_check() == 0, "the archived C08 decks pass the check")
        p3 = os.path.join(dst, "p3.spice")
        with open(p3) as fh:
            text = fh.read()
        i = text.index("\nCa0 ")
        j = text.index("\n", i + 1)
        line = text[i + 1:j]
        planted = line[:-1] + ("1" if line[-1] != "1" else "2")
        atomic_write_text(p3, text[:i + 1] + planted + text[j:])
        expect(quiet_check() == 1, "a coupling changed in its last digit")
        atomic_write_text(p3, text)
        os.remove(os.path.join(dst, "p5.spice"))
        expect(quiet_check() == 1, "a phase deck missing")
    print("%d failed" % len(fails))
    return 1 if fails else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("--arm", default="C", choices=sorted(rc.ARMS))
    m.add_argument("--ro", type=int, default=8)
    m.add_argument("--corner", default="tt", choices=sorted(rc.CORNERS))
    m.add_argument("--aggressor", default="clknet_4_15_0_clk")
    m.add_argument("--n", type=int, default=11)
    m.add_argument("--tran-ns", type=float, default=140.0)
    m.add_argument("--spef", default=SPEF)
    m.add_argument("--allow-even", action="store_true",
                   help="an even n, as a control: the two edges cancel")
    m.add_argument("--no-small", action="store_true",
                   help="leave out the small decks")
    m.add_argument("--out", required=True)
    m.add_argument("--swing", type=float, default=1.0,
                   help="the square wave's swing as a multiple of the"
                        " supply, for a pull the noise would hide")
    m.add_argument("--phases", type=int, default=PHASES)
    m.add_argument("--edge-ps", type=float, default=EDGE_PS,
                   help="the square wave's rise and fall, ps")
    m.add_argument("--only", help="make only these phases, e.g. 0,1,9:"
                   " a closer look where another set found the pull")
    m.add_argument("--offset", type=float, default=0.0,
                   help="start every phase this share of a step later, to"
                        " fall between another set's phases")
    m.add_argument("--loop-only", action="store_true",
                   help="ground the output net's couplings, drive only"
                        " the loop's")
    m.add_argument("--check", action="store_true",
                   help="make the decks again and compare with the files,"
                        " writing nothing")
    r = sub.add_parser("run")
    r.add_argument("out")
    r.add_argument("--only", nargs="*")
    r.add_argument("--again", action="store_true")
    d = sub.add_parser("read")
    d.add_argument("out")
    d.add_argument("--json")
    t = sub.add_parser("table")
    t.add_argument("dir")
    t.add_argument("--csv")
    c = sub.add_parser("check")
    c.add_argument("dir")
    sub.add_parser("selftest")
    a = ap.parse_args(argv)
    if a.cmd == "selftest":
        return selftest(a)
    if a.cmd in ("table", "check"):
        a.dir = os.path.abspath(a.dir)
        return table(a) if a.cmd == "table" else check(a)
    a.out = os.path.abspath(a.out)
    return {"make": make, "run": run, "read": read}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
