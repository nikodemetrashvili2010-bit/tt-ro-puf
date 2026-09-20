#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""What the release build does on a bench rather than in a nominal deck.

Every other number in this directory comes from an oscillator on an ideal
supply, at one temperature, with nothing else on the die. This script puts
the release build (dualarm/build_armc, run 83) back into the physical world
and asks five questions of it, each from files in the repository:

  heat       how much power a running ring burns, how far that warms it, and
             whether the warming could move a bit
  current    how hard the ring wires, the rails and the power vias are driven,
             against the electromigration limits the sky130 tech LEF declares
  supply     how far the supply sags under a running ring through the real
             power grid in the DEF, and what that does to a pair's gap
  taps       whether every row still has its well taps at the flow's spacing
             after 1024 cells were fixed by hand around them
  bits       all three arms together in a Monte Carlo over dies, with mismatch,
             the supply term, reading noise and the three corners

The supply currents come from SPICE decks run for this purpose, archived under
real_world/, and the frequencies from the lumped and distributed-RC decks under
rc3/. Nothing here is fitted to the answer it reports.

Things it does not model, said once here and again in the output: the Tiny
Tapeout top-level grid, package and board, which feed the met4 stripes; the
inside of the Arm B macro's own power grid; mismatch that changes with voltage
and temperature. Where a number rests on an assumption the output says which.

Run: python3 real_world.py            (exit 1 if any check fails)
     python3 real_world.py --selftest (plants the faults the checks exist for)
"""

import json
import math
import os
import random
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
REL = os.path.join(PROJ, "dualarm", "build_armc")
BASE = os.path.join(PROJ, "dualarm", "build_current")
DEF_NAME = "tt_um_nikodemetrashvili20_ro_puf.def"
PWR = os.path.join(HERE, "real_world")
RC3 = os.path.join(HERE, "rc3")

# sky130 tech LEF, efabless/skywater-pdk-libs-sky130_fd_sc_hd at 5a42fd0,
# tech/sky130_fd_sc_hd__nom.tlef: sheet resistance in ohm/sq, via resistance
# in ohm per cut, and the electromigration limits it declares at Tj = 90 C,
# DC average and AC RMS in mA per um of width, cuts in mA per cut (DC only).
RSQ = {"met1": 0.125, "met2": 0.125, "met3": 0.047, "met4": 0.047}
RCUT = {"via": 4.50, "via2": 3.41, "via3": 3.41}
EM_DC = {"met1": 2.8, "met2": 2.8, "met3": 6.8, "met4": 6.8}
EM_RMS = {"met1": 6.1, "met2": 6.1, "met3": 14.9, "met4": 14.9}
EM_CUT = {"mcon": 0.36, "via": 0.29, "via2": 0.48, "via3": 0.48}
W_MIN_MET1 = 0.14  # um, the width a signal wire can be at its thinnest
RAIL_W, STRIPE_W = 0.48, 2.40  # um, from the DEF's SPECIALNETS
# The power via stack at every rail-stripe crossing, from the DEF's VIAS:
# met1-met2 1x7 cuts, met2-met3 1x6, met3-met4 1x6.
STACK_CUTS = {"via": 7, "via2": 6, "via3": 6}
R_STACK = sum(RCUT[v] / n for v, n in STACK_CUTS.items())

# Silicon, for the heating estimate. Conductivity falls as it warms, so the
# hot value is the one the check uses.
K_SI_COLD, K_SI_HOT = 148.0, 100.0  # W/(m K), about 300 K and 400 K
ALPHA_SI = 8.8e-5  # m^2/s, thermal diffusivity
THETA_JA = 100.0  # K/W, ASSUMED: package plus board, set high on purpose

SIGMA_RING = 0.062  # percent, per-ring mismatch, sim/spice/mc
READ_NOISE = (
    0.0013  # percent rms, one reading at 2048 cycles (analyze_noise.py)
)
PAIRS = [(i, i + 1) for i in range(0, 16, 2)]

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
    print(
        "%s  %s%s"
        % (
            "PASS" if cond else "FAIL",
            name,
            ("   [%s]" % detail) if detail else "",
        )
    )
    return cond


# ------------------------------------------------------------------ readers
def read_def(path):
    """Rows, components and the power grid of one DEF."""
    txt = open(path).read()
    rows = [
        (int(x), int(y), o, int(n) * int(s))
        for x, y, o, n, s in re.findall(
            r"^ROW \S+ \S+ (\d+) (\d+) (\S+) DO (\d+) BY 1 STEP (\d+) 0",
            txt,
            re.M,
        )
    ]
    comp = re.search(
        r"^COMPONENTS \d+ ;(.*?)^END COMPONENTS", txt, re.S | re.M
    ).group(1)
    cells = [
        (n.replace("\\", ""), m, int(x), int(y), o)
        for n, m, x, y, o in re.findall(
            r"- (\S+) (\S+) .*?\( (-?\d+) (-?\d+) \) (\S+) ;", comp
        )
    ]
    grid = {}
    sn = re.search(
        r"^SPECIALNETS \d+ ;(.*?)^END SPECIALNETS", txt, re.S | re.M
    ).group(1)
    for net, body in re.findall(
        r"- (VPWR|VGND) (.*?)(?=^\s+- |\Z)", sn, re.S | re.M
    ):
        g = grid.setdefault(net, {"rails": [], "stripes": [], "stacks": []})
        for w, x1, y, x2 in re.findall(
            r"met1 (\d+) \+ SHAPE FOLLOWPIN \( (\d+) (\d+) \) \( (\d+) \d+ \)",
            body,
        ):
            g["rails"].append((int(y), int(x1), int(x2)))
        for x, y1, y2 in re.findall(
            r"met4 2400 \+ SHAPE STRIPE \( (\d+) (\d+) \) \( \d+ (\d+) \)",
            body,
        ):
            g["stripes"].append((int(x), int(y1), int(y2)))
        for x, y in re.findall(
            r"met1 0 \+ SHAPE STRIPE \( (\d+) (\d+) \) via2_3", body
        ):
            g["stacks"].append((int(x), int(y)))
    return rows, cells, grid


def cell_widths(rows, cells):
    """dbu width of every row cell: the next origin in its row, or the row end.
    Exact on a final DEF, which the fill step leaves covered edge to edge."""
    ends = {}
    for x, y, o, w in rows:
        ends.setdefault(y, []).append((x, x + w))
    byrow = {}
    for c in cells:
        if c[1].startswith("sky130_fd_sc_hd__"):
            byrow.setdefault(c[3], []).append(c)
    out = {}
    for y, cs in byrow.items():
        cs.sort(key=lambda c: c[2])
        for i, c in enumerate(cs):
            nxt = (
                cs[i + 1][2]
                if i + 1 < len(cs)
                else max(e for s, e in ends[y] if s <= c[2])
            )
            out[c[0]] = nxt - c[2]
    return out


def ring_cells(cells, arm, ring):
    key = (
        "u_puf.u_core.g_ro_bank[%d].u_ro."
        if arm == "A"
        else "u_puf.u_core.g_armc[%d].u_roc."
    ) % ring
    return [c for c in cells if c[0].startswith(key)]


def meas(path, names):
    """ngspice .meas results from a log, by name."""
    txt = open(path, errors="ignore").read()
    out = {}
    for n in names:
        m = re.search(r"^%s\s*=\s*(-?[0-9.]+(?:[eE][+-]?\d+)?)" % n, txt, re.M)
        out[n] = float(m.group(1)) if m else None
    return out


def freqs(path, n=16):
    """f0..f15 in MHz from a sixteen-ring log."""
    d = {
        int(k): float(v) / 1e6
        for k, v in re.findall(
            r"^f(\d+)\s*=\s*([0-9.eE+-]+)", open(path).read(), re.M
        )
    }
    return [d[i] for i in range(n)]


def one_freq(path):
    """The f printed by a single-ring deck (20 periods over tp), in MHz."""
    m = re.search(
        r"^tp\s*=\s*([0-9.eE+-]+)", open(path, errors="ignore").read(), re.M
    )
    return 20.0 / float(m.group(1)) / 1e6 if m else None


# ------------------------------------------------------------------- IR grid
def solve_grid(g, loads, fixed="ends", tol=1e-12, it_max=20000):
    """Drop at every node of one supply net for given current draws.

    g       rails [(y, x1, x2)], stripes [(x, y1, y2)], stacks [(x, y)], dbu
    loads   {("rail", y, x): amps} drawn at a rail point, or
            {("stripe", x, y): amps} drawn straight off a stripe
    fixed   "ends": only the two ends of each met4 stripe sit at the supply,
            the worst the Tiny Tapeout grid could do. "stripes": every point
            of every stripe sits at the supply, the best it could do.
    Returns ({node: volts of drop}, {edge: amps}).
    """
    edges = []
    node_id = {}

    def nid(key):
        if key not in node_id:
            node_id[key] = len(node_id)
        return node_id[key]

    stack_at = {}
    for x, y in g["stacks"]:
        stack_at.setdefault(y, []).append(x)
    for y, x1, x2 in g["rails"]:
        xs = {x1, x2}
        xs.update(x for x in stack_at.get(y, []) if x1 <= x <= x2)
        xs.update(
            k[2]
            for k in loads
            if k[0] == "rail" and k[1] == y and x1 <= k[2] <= x2
        )
        xs = sorted(xs)
        for a, b in zip(xs, xs[1:]):
            edges.append(
                (
                    nid(("rail", y, a)),
                    nid(("rail", y, b)),
                    RSQ["met1"] * (b - a) / 1000.0 / RAIL_W,
                    "met1",
                )
            )
    stripe_x = {x for x, _, _ in g["stripes"]}
    for x, y1, y2 in g["stripes"]:
        ys = {y1, y2}
        ys.update(y for sx, y in g["stacks"] if sx == x and y1 <= y <= y2)
        ys.update(k[2] for k in loads if k[0] == "stripe" and k[1] == x)
        ys = sorted(ys)
        for a, b in zip(ys, ys[1:]):
            edges.append(
                (
                    nid(("stripe", x, a)),
                    nid(("stripe", x, b)),
                    RSQ["met4"] * (b - a) / 1000.0 / STRIPE_W,
                    "met4",
                )
            )
    for x, y in g["stacks"]:
        if x in stripe_x:
            edges.append(
                (nid(("rail", y, x)), nid(("stripe", x, y)), R_STACK, "stack")
            )
    n = len(node_id)
    is_fixed = [False] * n
    for key, i in node_id.items():
        if key[0] == "stripe":
            ends = [(y1, y2) for sx, y1, y2 in g["stripes"] if sx == key[1]][0]
            if fixed == "stripes" or key[2] in ends:
                is_fixed[i] = True
    adj = [[] for _ in range(n)]
    for a, b, r, _ in edges:
        adj[a].append((b, 1.0 / r))
        adj[b].append((a, 1.0 / r))
    rhs = [0.0] * n
    for key, amps in loads.items():
        rhs[node_id[key]] += amps
    # conjugate gradient on the free nodes, fixed nodes held at zero drop
    free = [i for i in range(n) if not is_fixed[i]]

    def apply(v):
        out = [0.0] * n
        for i in free:
            s = 0.0
            for j, gg in adj[i]:
                s += gg * (v[i] - (0.0 if is_fixed[j] else v[j]))
            out[i] = s
        return out

    v = [0.0] * n
    r = [rhs[i] if not is_fixed[i] else 0.0 for i in range(n)]
    p = r[:]
    rs = sum(x * x for x in r)
    for _ in range(it_max):
        if rs < tol * tol:
            break
        ap = apply(p)
        alpha = rs / sum(p[i] * ap[i] for i in free)
        for i in free:
            v[i] += alpha * p[i]
            r[i] -= alpha * ap[i]
        rs_new = sum(r[i] * r[i] for i in free)
        beta = rs_new / rs
        for i in free:
            p[i] = r[i] + beta * p[i]
        rs = rs_new
    drop = {key: v[i] for key, i in node_id.items()}
    current = {}
    for a, b, rr, kind in edges:
        current[(a, b, kind)] = abs(v[a] - v[b]) / rr
    return drop, current, edges


def ring_loads(cells, widths, net, amps):
    """Spread a ring's supply current over its cells, each at its own rail."""
    per = amps / len(cells)
    loads = {}
    for name, master, x, y, o in cells:
        # N and FN rows: VGND on the bottom edge, VPWR on the top. FS and S
        # are mirrored top to bottom, so the rails swap.
        flipped = o in ("FS", "S")
        y_vpwr = y if flipped else y + 2720
        y_vgnd = y + 2720 if flipped else y
        xc = x + widths.get(name, 1380) // 2
        key = ("rail", y_vpwr if net == "VPWR" else y_vgnd, xc)
        loads[key] = loads.get(key, 0.0) + per
    return loads


# ------------------------------------------------------------ the arms' data
ARMS_POWER = {"A": ("A00", "A04", "A14"), "C": ("C00", "C04", "C14")}
CORNER_V = {"tt": 1.80, "ss": 1.60, "ff": 1.95}


def power_table(pwr_dir):
    """{(tag, corner): (MHz, supply amps avg, rms, peak)}, power logs."""
    out = {}
    for fn in sorted(os.listdir(pwr_dir)):
        m = re.fullmatch(r"([AC]\d\d)_(tt|ss|ff)_pwr_out\.txt", fn)
        if not m:
            continue
        r = meas(os.path.join(pwr_dir, fn), ["tp", "iavg", "irms", "ipk"])
        if None in r.values():
            continue
        out[(m.group(1), m.group(2))] = (
            20.0 / r["tp"] / 1e6,
            -r["iavg"],
            r["irms"],
            -r["ipk"],
        )
    return out


def arm_freqs(rc3_dir, arm, corner):
    """Sixteen frequencies of one arm at one corner, lumped model, MHz."""
    sub = os.path.join(
        rc3_dir, "arm%s" % arm + ("" if corner == "tt" else "_" + corner)
    )
    return [
        one_freq(os.path.join(sub, "ro%02d_lumped_out.txt" % i))
        for i in range(16)
    ]


def arm_rc(rc3_dir, arm):
    sub = os.path.join(rc3_dir, "arm%s" % arm)
    return [
        one_freq(os.path.join(sub, "ro%02d_rc_out.txt" % i)) for i in range(16)
    ]


def armb_freqs(corner):
    name = "armb_instances%s_out.txt" % (
        "" if corner == "tt" else "_" + corner
    )
    txt = open(os.path.join(HERE, name), errors="ignore").read()
    got = dict(re.findall(r"^f_k(\d\d)\s*=\s*([0-9.eE+-]+)", txt, re.M))
    return [float(got["%02d" % k]) / 1e6 for k in range(16)]


def pushing_and_tempco():
    """Supply pushing per volt and the worst temperature coefficient, per ring,
    from the baseline's operating-point logs (tt, sixteen Arm A rings)."""
    f = {
        v: freqs(os.path.join(HERE, "noise_vdd_%d_out.txt" % v))
        for v in (1620, 1800, 1980)
    }
    push = [(f[1980][i] - f[1620][i]) / 0.36 / f[1800][i] for i in range(16)]
    tc = []
    for v in (1620, 1980):
        cold = freqs(os.path.join(HERE, "noise_vt_%d_m40_out.txt" % v))
        hot = freqs(os.path.join(HERE, "noise_vt_%d_125_out.txt" % v))
        tc += [
            abs(h - c) / 165.0 / f[v][i]
            for i, (c, h) in enumerate(zip(cold, hot))
        ]
    return push, tc


def bits(f):
    return [1 if f[a] > f[b] else 0 for a, b in PAIRS]


def gaps_pct(f):
    m = st.fmean(f)
    return [abs(f[a] - f[b]) / m * 100.0 for a, b in PAIRS]


# --------------------------------------------------------------- Monte Carlo
def monte_carlo(
    design, ir_pct, rng, dies=20000, sigma=SIGMA_RING, noise=READ_NOISE
):
    """design {"ss", "tt", "ff": sixteen MHz on one parasitic model, and
    optionally "rc": the full RC network at tt}; ir_pct sixteen shifts, in
    percent.

    Entropy, the reader's score, uniqueness and reading flips use "rc" when it
    is there, the model the headline figures use. Corner flips compare ss and
    ff against tt on the one model all three corners share, so a difference
    between models is never counted as a flip. Mismatch is drawn once per die
    and held at every corner, which is an assumption: real mismatch moves
    somewhat with supply and temperature."""
    head = design.get("rc", design["tt"])
    predicted = bits([f * (1 + d / 100.0) for f, d in zip(head, ir_pct)])
    ones = [0] * 8
    right = flips_read = flips_corner = 0
    keep = []

    def shifted(f, mm):
        return [
            fi * (1 + (mi + d) / 100.0) for fi, mi, d in zip(f, mm, ir_pct)
        ]

    for _ in range(dies):
        mm = [rng.gauss(0.0, sigma) for _ in range(16)]
        b = bits(shifted(head, mm))
        for k in range(8):
            ones[k] += b[k]
            right += b[k] == predicted[k]
        read = bits(
            [
                fi * (1 + rng.gauss(0.0, noise) / 100.0)
                for fi in shifted(head, mm)
            ]
        )
        flips_read += sum(x != y for x, y in zip(b, read))
        at_tt = bits(shifted(design["tt"], mm))
        for c in ("ss", "ff"):
            flips_corner += sum(
                x != y for x, y in zip(at_tt, bits(shifted(design[c], mm)))
            )
        if len(keep) < 400:
            keep.append(b)
    p = [o / dies for o in ones]
    ent = sum(
        (
            0.0
            if q in (0.0, 1.0)
            else -(q * math.log2(q) + (1 - q) * math.log2(1 - q))
        )
        for q in p
    )
    hd = [
        sum(x != y for x, y in zip(keep[i], keep[j])) / 8.0
        for i in range(len(keep))
        for j in range(i + 1, len(keep))
    ]
    return {
        "entropy": ent,
        "called": right / dies,
        "uniqueness": st.fmean(hd),
        "read_flip": flips_read / dies / 8.0,
        "corner_flip": flips_corner / dies / 8.0 / 2.0,
    }


# ---------------------------------------------------------------------- main
def run(
    rel=REL, base=BASE, pwr_dir=PWR, rc3_dir=RC3, dies=20000, seed=20260920
):
    rows, cells, grid = read_def(os.path.join(rel, DEF_NAME))
    widths = cell_widths(rows, cells)
    metrics = json.load(open(os.path.join(rel, "metrics.json")))
    pw = power_table(pwr_dir)
    push, tc = pushing_and_tempco()
    s_push = st.fmean(push)  # fraction per volt
    result = {}

    print("== signoff counts on the release build, from its metrics.json ==")
    for key, label in (
        ("magic__drc_error__count", "Magic DRC"),
        ("klayout__drc_error__count", "KLayout DRC"),
        ("design__lvs_error__count", "LVS"),
        ("antenna__violating__nets", "antenna nets"),
        ("route__drc_errors", "routing DRC"),
    ):
        check(
            "%s errors: 0" % label,
            metrics.get(key) == 0,
            str(metrics.get(key)),
        )

    print("\n== heat ==")
    need = [
        (t, c) for tags in ARMS_POWER.values() for t in tags for c in CORNER_V
    ]
    check(
        "all %d ring power logs are present and parse" % len(need),
        all(k in pw for k in need),
        "missing %s" % [k for k in need if k not in pw],
    )
    p_ring = {
        c: max(pw[k][1] * CORNER_V[c] for k in pw if k[1] == c)
        for c in CORNER_V
    }
    mux = meas(os.path.join(pwr_dir, "mux_A00_ff_pwr_out.txt"), ["iavg", "tp"])
    p_mux = -mux["iavg"] * 1.95
    for c in ("ss", "tt", "ff"):
        print(
            "  one ring at %s: %.3f mW at most over the six rings run"
            % (c, p_ring[c] * 1e3)
        )
    print(
        "  ring plus the selector path and the first counter flop, ff: %.3f mW"
        % (p_mux * 1e3)
    )
    area = {}
    for arm in ("A", "C"):
        for ring in range(16):
            cs = ring_cells(cells, arm, ring)
            xs = [c[2] for c in cs] + [
                c[2] + widths.get(c[0], 1380) for c in cs
            ]
            ys = [c[3] for c in cs] + [c[3] + 2720 for c in cs]
            area[(arm, ring)] = (
                (max(xs) - min(xs)) * (max(ys) - min(ys)) / 1e6
            )  # um^2
    p_ff = [pw[k][1] * CORNER_V["ff"] for k in pw if k[1] == "ff"]
    p_spread = (max(p_ff) - min(p_ff)) / st.fmean(p_ff)
    tc_worst = max(tc)

    def warm(a_um2):
        return 0.4732 * p_ring["ff"] / (K_SI_HOT * math.sqrt(a_um2) * 1e-6)

    small = min(area, key=area.get)
    dt_local = warm(area[small])
    dt_die = p_mux * THETA_JA
    tau = area[small] * 1e-12 / ALPHA_SI
    df_heat = (dt_local + dt_die) * tc_worst * 100.0
    print(
        "  smallest ring footprint: Arm %s ring %d, %.0f um2"
        % (small[0], small[1], area[small])
    )
    print(
        "  one ring at %.3f mW warms that footprint by %.3f K, settling in"
        " %.1f us of a 41 us window"
        % (p_ring["ff"] * 1e3, dt_local, tau * 1e6)
    )
    print(
        "  the whole measurement at %.3f mW warms the die by %.3f K at %.0f"
        " K/W (assumed, high on purpose)" % (p_mux * 1e3, dt_die, THETA_JA)
    )
    print(
        "  worst temperature coefficient in the -40 to 125 C box: %.4f %%/K"
        % (tc_worst * 100)
    )
    print(
        "  so a running ring reads %.4f %% off its cold self; both rings of a"
        " pair do this, so it is common to the comparison" % df_heat
    )
    diff = 0.0
    for arm in ("A", "C"):
        for a, b in PAIRS:
            ta, tb = warm(area[(arm, a)]), warm(area[(arm, b)])
            d = (abs(ta - tb) + p_spread * max(ta, tb)) * tc_worst * 100.0
            diff = max(diff, d)
    print(
        "  what does not cancel: footprints that differ inside a pair, plus"
        " the %.1f %% power spread over the six rings run: at most %.4f %%"
        % (100 * p_spread, diff)
    )
    result["p_ring_tt_mw"], result["p_ring_ff_mw"] = (
        p_ring["tt"] * 1e3,
        p_ring["ff"] * 1e3,
    )
    result["p_mux_ff_mw"], result["dt_local_k"] = p_mux * 1e3, dt_local
    result["df_heat_pct"], result["df_heat_pair_pct"] = df_heat, diff
    check(
        "self-heating moves a pair's gap by less than a tenth of the mismatch"
        " scale",
        diff < SIGMA_RING / 10.0,
        "%.4f%% against %.4f%%" % (diff, SIGMA_RING / 10.0),
    )

    print(
        "\n== current density against the tech LEF's electromigration"
        " limits =="
    )
    netlogs = sorted(
        f
        for f in os.listdir(pwr_dir)
        if f.startswith("net_") and f.endswith("_out.txt")
    )
    check(
        "three wire-current logs are present", len(netlogs) == 3, str(netlogs)
    )
    j_rms_worst = 0.0
    for fn in netlogs:
        r = meas(
            os.path.join(pwr_dir, fn),
            ["inet_avg", "inet_rms", "inet_max", "inet_min", "tp"],
        )
        j_rms = r["inet_rms"] * 1e3 / W_MIN_MET1
        j_pk = max(abs(r["inet_max"]), abs(r["inet_min"])) * 1e3 / W_MIN_MET1
        j_rms_worst = max(j_rms_worst, j_rms)
        print(
            "  %-18s rms %.1f uA, peak %.0f uA, mean %+.2f uA; on a %.2f um"
            " wire %.2f mA/um rms, %.1f peak"
            % (
                fn[4:-8],
                r["inet_rms"] * 1e6,
                max(abs(r["inet_max"]), abs(r["inet_min"])) * 1e6,
                r["inet_avg"] * 1e6,
                W_MIN_MET1,
                j_rms,
                j_pk,
            )
        )
    check(
        "the heaviest ring wires stay under the met1 RMS limit at ff, as if"
        " min width",
        j_rms_worst < EM_RMS["met1"],
        "%.2f against %.1f mA/um" % (j_rms_worst, EM_RMS["met1"]),
    )
    result["j_rms_worst"] = j_rms_worst

    print(
        "\n== supply drop with one ring running, through the DEF's power"
        " grid =="
    )
    i_tt = {
        arm: st.fmean(pw[(t, "tt")][1] for t in tags)
        for arm, tags in ARMS_POWER.items()
    }
    i_tt["B"] = i_tt[
        "A"
    ]  # same ring; the macro's own run was not repeated here
    print(
        "  ring supply current at tt: Arm A %.1f uA, Arm C %.1f uA; Arm B"
        " taken as Arm A's" % (i_tt["A"] * 1e6, i_tt["C"] * 1e6)
    )
    macros = sorted(
        (c for c in cells if c[1] == "ro_macro_hard"),
        key=lambda c: int(re.sub(r"\D", "", c[0])),
    )
    drops = {}
    rail_i = stack_i = stripe_i = 0.0
    for mode in ("ends", "stripes"):
        for arm in ("A", "C", "B"):
            vals = []
            for ring in range(16):
                total = 0.0
                for net in ("VPWR", "VGND"):
                    if arm == "B":
                        mc = macros[ring]
                        # the macro's own met4 pins sit on the stripes, VPWR at
                        # x + 21.84 um and VGND at x + 25.14, over y
                        # 10.64 to 27.44 um
                        xpin = mc[2] + (21840 if net == "VPWR" else 25140)
                        loads = {("stripe", xpin, mc[3] + 19040): i_tt["B"]}
                    else:
                        cs = ring_cells(cells, arm, ring)
                        loads = ring_loads(cs, widths, net, i_tt[arm])
                    drop, cur, edges = solve_grid(grid[net], loads, mode)
                    amps = sum(loads.values())
                    total += sum(drop[k] * a for k, a in loads.items()) / amps
                    if mode == "ends":
                        for (a, b, kind), i in cur.items():
                            if kind == "met1":
                                rail_i = max(rail_i, i)
                            elif kind == "stack":
                                stack_i = max(stack_i, i)
                            else:
                                stripe_i = max(stripe_i, i)
                vals.append(total)
            drops[(mode, arm)] = vals
            shift = [v * s_push * 100.0 for v in vals]
            pair = [abs(shift[a] - shift[b]) for a, b in PAIRS]
            print(
                "  %-8s Arm %s: %.3f to %.3f mV, so %.4f to %.4f %% slower; "
                "pair difference up to %.4f %%"
                % (
                    mode,
                    arm,
                    min(vals) * 1e3,
                    max(vals) * 1e3,
                    min(shift),
                    max(shift),
                    max(pair),
                )
            )
    print(
        "  supply pushing, baseline rings at tt: %.2f %% per volt"
        % (s_push * 100)
    )
    j_rail = rail_i * 1e3 / RAIL_W
    j_stripe = stripe_i * 1e3 / STRIPE_W
    check(
        "worst rail segment under the met1 DC limit",
        j_rail < EM_DC["met1"],
        "%.1f uA, %.3f against %.1f mA/um"
        % (rail_i * 1e6, j_rail, EM_DC["met1"]),
    )
    check(
        "worst power via stack under the via DC limit per cut",
        stack_i / STACK_CUTS["via"] * 1e3 < EM_CUT["via"],
        "%.1f uA over %d cuts against %.2f mA a cut"
        % (stack_i * 1e6, STACK_CUTS["via"], EM_CUT["via"]),
    )
    check(
        "worst met4 stripe segment under the met4 DC limit",
        j_stripe < EM_DC["met4"],
        "%.4f against %.1f mA/um" % (j_stripe, EM_DC["met4"]),
    )
    result["drops"] = drops
    result["push"] = s_push

    print("\n== well taps ==")
    taps_rel = sorted(
        (c[3], c[2]) for c in cells if c[1].endswith("tapvpwrvgnd_1")
    )
    _, base_cells, _ = read_def(os.path.join(base, DEF_NAME))
    taps_base = sorted(
        (c[3], c[2]) for c in base_cells if c[1].endswith("tapvpwrvgnd_1")
    )
    check(
        "the release build keeps every tap of the baseline, same sites",
        taps_rel == taps_base,
        "%d and %d taps" % (len(taps_rel), len(taps_base)),
    )
    worst_gap = tap_distance(rows, taps_rel)
    far = worst_gap[0] / 1000.0
    print(
        "  %d taps in %d rows; the farthest any site sits from a tap in its"
        " own row or the next one is %.2f um (row at y %.2f)"
        % (len(taps_rel), len(rows), far, worst_gap[1] / 1000.0)
    )
    check(
        "every site is within 15 um of a tap, the working figure for sky130 "
        "(not a quoted rule)",
        far <= 15.0,
        "%.2f um" % far,
    )
    result["tap_far_um"] = far

    print("\n== the three arms on a bench, Monte Carlo over %d dies ==" % dies)
    rng = random.Random(seed)
    design = {
        "A": {c: arm_freqs(rc3_dir, "A", c) for c in CORNER_V},
        "C": {c: arm_freqs(rc3_dir, "C", c) for c in CORNER_V},
        "B": {c: armb_freqs(c) for c in CORNER_V},
    }
    design["A"]["rc"], design["C"]["rc"] = arm_rc(rc3_dir, "A"), arm_rc(
        rc3_dir, "C"
    )
    for arm in ("A", "C"):
        ok_all = all(
            len(v) == 16 and None not in v for v in design[arm].values()
        )
        check(
            "Arm %s has sixteen frequencies at ss, tt and ff, and under RC"
            " at tt" % arm,
            ok_all,
        )
    mc = {}
    for arm in ("A", "B", "C"):
        ir = [-v * s_push * 100.0 for v in drops[("ends", arm)]]
        r = monte_carlo(design[arm], ir, rng, dies)
        mc[arm] = r
        print(
            "  Arm %s: %.2f bits of 8 across dies, reader calls %.2f,"
            " uniqueness %.3f, a single reading flips %.4f of bits, a corner"
            " change %.4f"
            % (
                arm,
                r["entropy"],
                r["called"],
                r["uniqueness"],
                r["read_flip"],
                r["corner_flip"],
            )
        )
    result["mc"] = mc
    sd = {arm: st.pstdev(design[arm]["rc"]) for arm in ("A", "C")}
    print(
        "  Arm C sd over Arm A sd at tt, design alone: %.3f"
        % (sd["C"] / sd["A"])
    )
    corner_bits = {
        arm: {c: "".join(map(str, bits(design[arm][c]))) for c in CORNER_V}
        for arm in ("A", "C")
    }
    for arm in ("A", "C"):
        same = len(set(corner_bits[arm].values())) == 1
        check(
            "Arm %s's design bits are the same at ss, tt and ff" % arm,
            same,
            " ".join("%s %s" % kv for kv in sorted(corner_bits[arm].items())),
        )
    result["corner_bits"] = corner_bits
    result["gaps"] = {
        arm: min(gaps_pct(design[arm]["rc"])) for arm in ("A", "C")
    }
    for arm in ("A", "C"):
        f = design[arm]["rc"]
        d = drops[("ends", arm)]
        with_ir = [fi * (1 - di * s_push) for fi, di in zip(f, d)]
        ratio = max(
            abs(d[a] - d[b])
            * s_push
            * 100.0
            / (abs(f[a] - f[b]) / st.fmean(f) * 100.0)
            for a, b in PAIRS
        )
        check(
            "the supply term changes no Arm %s bit; at most %.0f%% of its own"
            " pair's gap" % (arm, 100 * ratio),
            bits(with_ir) == bits(f),
            "%.3f" % ratio,
        )
        result["ir_ratio_" + arm] = ratio
    print(
        "\nNot modelled: the Tiny Tapeout grid, package and board above the"
        " met4 stripes; the macro's internal grid; mismatch that moves with V"
        " and T."
    )
    return result


# ------------------------------------------------------------------ selftest
def selftest():
    """Plant the fault each check exists for, and require the check to see
    it."""
    global ok, fail
    good = bad = 0

    def expect(name, cond):
        nonlocal good, bad
        good, bad = good + bool(cond), bad + (not cond)
        print("%s  selftest: %s" % ("PASS" if cond else "FAIL", name))

    # 1. the solver against a line that can be checked by hand: one rail 100 um
    # long, fed at both ends by stripes held at the supply, 1 mA drawn in the
    # middle. Each half is 50 um of 0.48 um met1 in parallel with the other.
    g = {
        "rails": [(0, 0, 100000)],
        "stripes": [(0, -1000, 1000), (100000, -1000, 1000)],
        "stacks": [(0, 0), (100000, 0)],
    }
    drop, _, _ = solve_grid(g, {("rail", 0, 50000): 1e-3}, "stripes")
    half = RSQ["met1"] * 50.0 / RAIL_W + R_STACK
    expect(
        "a centre load on a doubly fed rail drops I times R/2 of each half",
        abs(drop[("rail", 0, 50000)] - 1e-3 * half / 2.0) < 1e-12,
    )
    _, cur, _ = solve_grid(g, {("rail", 0, 50000): 1e-3}, "stripes")
    rails = [i for (a, b, kind), i in cur.items() if kind == "met1"]
    expect(
        "each half of that rail carries half the current, 0.5 mA",
        abs(max(rails) - 0.5e-3) < 1e-12 and abs(min(rails) - 0.5e-3) < 1e-12,
    )
    # 2. cut one feed and the drop has to become the whole path
    g2 = dict(g, stacks=[(0, 0)])
    drop2, _, _ = solve_grid(g2, {("rail", 0, 50000): 1e-3}, "stripes")
    expect(
        "removing one via stack doubles the path, and the solver sees it",
        abs(drop2[("rail", 0, 50000)] - 1e-3 * half) < 1e-12,
    )
    # 3. a stripe fed only at its ends carries a middle load to both ends
    g3 = {"rails": [], "stripes": [(0, 0, 200000)], "stacks": []}
    drop3, _, _ = solve_grid(g3, {("stripe", 0, 100000): 2e-3}, "ends")
    expect(
        "a stripe load drops I times R/4 of the stripe with ends fed",
        abs(
            drop3[("stripe", 0, 100000)]
            - 2e-3 * RSQ["met4"] * 200.0 / STRIPE_W / 4
        )
        < 1e-12,
    )
    # 4. the Monte Carlo has to tell a matched arm from a fixed one
    rng = random.Random(7)
    flat = [570.0] * 16
    fixed = [570.0 * (1 + (0.02 if k % 2 == 0 else -0.02)) for k in range(16)]
    zero = [0.0] * 16
    m_flat = monte_carlo({"tt": flat, "ss": flat, "ff": flat}, zero, rng, 4000)
    m_fixed = monte_carlo(
        {"tt": fixed, "ss": fixed, "ff": fixed}, zero, rng, 4000
    )
    expect(
        "sixteen identical rings keep close to 8 bits and a reader near 4",
        m_flat["entropy"] > 7.9 and abs(m_flat["called"] - 4.0) < 0.2,
    )
    expect(
        "pairs 4% apart keep no entropy and a reader calls all 8",
        m_fixed["entropy"] < 0.01 and m_fixed["called"] > 7.99,
    )
    # 5. a corner that reverses a pair has to show up as corner flips
    swapped = fixed[:]
    swapped[0], swapped[1] = swapped[1], swapped[0]
    m_sw = monte_carlo(
        {"tt": fixed, "ss": swapped, "ff": fixed}, zero, rng, 2000
    )
    expect(
        "a pair that reverses at one corner is counted as a corner flip",
        abs(m_sw["corner_flip"] - 1.0 / 16.0) < 1e-9,
    )
    # 6. taps: a row that loses a tap has to read farther from its taps
    rows = [(0, 0, "N", 60 * 460), (0, 2720, "FS", 60 * 460)]
    taps = [(0, 5 * 460), (0, 33 * 460), (2720, 19 * 460), (2720, 47 * 460)]
    far_ok = tap_distance(rows, taps)[0]
    far_bad = tap_distance(rows, [taps[0], taps[2]])[0]
    expect(
        "taking the right-hand taps out of both rows opens a hole the check"
        " sees",
        far_ok < 15000 < far_bad,
    )
    print("\nselftest: %d passed, %d failed" % (good, bad))
    return 0 if bad == 0 else 1


def tap_distance(rows, taps, step=460):
    """(farthest dbu from any site centre of any row to the nearest tap centre
    in the same row or the row above or below, y of that row).

    The tap step places taps on a checkerboard, so a row's own taps can sit
    25.76 um apart with the neighbouring rows' taps in the gaps. Measuring
    only along a row would call that a hole."""
    tapc = [(x + 230, y + 1360) for y, x in taps]
    by_y = {}
    for x, y in tapc:
        by_y.setdefault(y, []).append(x)
    worst = (0.0, None)
    for x0, y, o, w in rows:
        yc = y + 1360
        near = [
            (x, yy)
            for yy in (yc - 2720, yc, yc + 2720)
            for x in by_y.get(yy, [])
        ]
        if not near:
            worst = max(worst, (float("inf"), y))
            continue
        for s in range(x0 + step // 2, x0 + w, step):
            d = min(math.hypot(s - x, yc - yy) for x, yy in near)
            if d > worst[0]:
                worst = (d, y)
    return worst


def main(argv):
    if "--selftest" in argv:
        return selftest()
    run()
    print("\n%d passed, %d failed" % (ok, fail))
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
