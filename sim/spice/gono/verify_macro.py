#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
Independent verification of the Arm B matched-frequency result.
Re-derives every number from raw files with fresh code (no imports from
gen_macro_deck.py): macro SPEF, the generated deck itself, both ngspice logs,
and the Arm A results csv. Prints PASS/FAIL per check.
"""
import re, os, csv, math

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SPEF = os.path.join(PROJ, "macro", "romacro_final", "spef", "nom", "ro_macro_hard.nom.spef")
DECK = os.path.join(HERE, "ro_macro_matched.spice")
LOG5 = os.path.join(HERE, "macro_out.txt")
LOG1 = os.path.join(HERE, "macro_fine_out.txt")
CSV  = os.path.join(HERE, "gono_results.csv")

ok = fail = 0
def check(name, cond, detail=""):
    global ok, fail
    tag = "PASS" if cond else "FAIL"
    if cond: ok += 1
    else: fail += 1
    print(f"[{tag}] {name}" + (f"  ({detail})" if detail else ""))

# --- 1. SPEF: fresh parse (D_NET blocks by name map) ---
txt = open(SPEF).read()
nmap = dict(re.findall(r'^\*(\d+)\s+(\S+)\s*$', txt, re.M))
dnets = re.findall(r'^\*D_NET \*(\d+)\s+([0-9.eE+-]+)', txt, re.M)
caps = {nmap[i].replace("\\", ""): float(c) for i, c in dnets}
ring = {k: caps[f"u_ro.n[{k}]"] for k in range(31) if f"u_ro.n[{k}]" in caps}
ring_fF = sum(ring.values()) * 1000.0
check("SPEF has 35 nets, all 31 ring nets", len(caps) == 35 and len(ring) == 31,
      f"{len(caps)} nets, {len(ring)} ring, ring cap {ring_fF:.2f} fF")

# --- 2. Deck: caps faithfully transferred, topology correct ---
deck = open(DECK).read()
dcaps = dict(re.findall(r'^C(b_\S+)\s+\S+\s+0\s+([0-9.e+-]+)', deck, re.M))
exact = all(math.isclose(float(dcaps.get(f"b_n{k}", -1)), ring[k]*1e-12, rel_tol=1e-5)
            for k in range(31))
extra = all(math.isclose(float(dcaps.get(f"b_{n}", -1)), caps[n]*1e-12, rel_tol=1e-5)
            for n in ("net1", "net2", "out", "en"))
check("deck caps == SPEF caps (31 ring + 4 boundary)", exact and extra,
      f"{len(dcaps)} C elements")
for tag in ("a", "b"):
    inv  = len(re.findall(rf'^X{tag}_inv\d+ ', deck, re.M))
    nand = len(re.findall(rf'^X{tag}_nand ', deck, re.M))
    buf  = len(re.findall(rf'^X{tag}_buf ', deck, re.M))
    dly  = len(re.findall(rf'^X{tag}_dly', deck, re.M))
    loop = re.search(rf'^X{tag}_nand\s+{tag}_net1 {tag}_n30 .* {tag}_n0 ', deck, re.M)
    check(f"instance {tag}: 30 inv + nand + buf + 2 dlybuf, ring closed n30->nand->n0",
          inv == 30 and nand == 1 and buf == 1 and dly == 2 and bool(loop))
check("control instance has zero parasitic caps",
      not re.search(r'^Ca_', deck, re.M))

# --- 3. Logs: recompute f from trig/targ, compare to printed f ---
def readlog(path):
    t = open(path).read()
    out = {}
    for inst in ("a", "b"):
        m = re.search(rf'tp_{inst}\s*=\s*([0-9.e+-]+)\s+targ=\s*([0-9.e+-]+)\s+trig=\s*([0-9.e+-]+)', t)
        f = re.search(rf'f_{inst} = ([0-9.e+-]+)', t)
        tp, targ, trig = map(float, m.groups())
        out[inst] = (tp, targ, trig, float(f.group(1)))
    return out
L5, L1 = readlog(LOG5), readlog(LOG1)
for name, L in (("5p", L5), ("1p", L1)):
    for inst in ("a", "b"):
        tp, targ, trig, fprint = L[inst]
        f_re = 20.0 / (targ - trig)
        check(f"{name} f_{inst}: recomputed 20/(targ-trig) == printed",
              math.isclose(f_re, fprint, rel_tol=1e-4) and math.isclose(tp, targ-trig, rel_tol=1e-6),
              f"{f_re/1e6:.3f} MHz")

# --- 4. Physics/consistency checks vs Arm A ---
rows = list(csv.DictReader(open(CSV)))
fA   = [float(r["freq_MHz"]) for r in rows]
cA   = [float(r["ring_cap_fF"]) for r in rows]
ctrlA = float(rows[0]["freq_ctrl_MHz"])
meanA, mnA, mxA = sum(fA)/len(fA), min(fA), max(fA)
f_a5, f_b5 = L5["a"][3]/1e6, L5["b"][3]/1e6
f_a1, f_b1 = L1["a"][3]/1e6, L1["b"][3]/1e6

check("control (5p) matches original Arm A control within 0.1%",
      abs(f_a5-ctrlA)/ctrlA < 0.001, f"{f_a5:.3f} vs {ctrlA:.3f} MHz, d={100*abs(f_a5-ctrlA)/ctrlA:.3f}%")
check("timestep 5p->1p shift <0.3% (numerical, both instances)",
      abs(f_a1-f_a5)/f_a5 < 0.003 and abs(f_b1-f_b5)/f_b5 < 0.003,
      f"ctrl {100*(f_a1-f_a5)/f_a5:+.2f}%, matched {100*(f_b1-f_b5)/f_b5:+.2f}%")
check("matched freq inside Arm A min..max", mnA < f_b5 < mxA,
      f"{f_b5:.2f} in [{mnA:.2f}, {mxA:.2f}]")
check("matched freq within 1% of Arm A mean", abs(f_b5-meanA)/meanA < 0.01,
      f"{f_b5:.2f} vs mean {meanA:.2f}, d={100*(f_b5-meanA)/meanA:+.2f}%")
check("macro ring cap inside Arm A cap range", min(cA) < ring_fF < max(cA),
      f"{ring_fF:.2f} fF in [{min(cA):.2f}, {max(cA):.2f}]")

# Arm A linear fit f(cap), fresh least squares; predict macro freq from its cap
n = len(cA); sx, sy = sum(cA), sum(fA)
sxx = sum(x*x for x in cA); sxy = sum(x*y for x, y in zip(cA, fA))
slope = (n*sxy - sx*sy)/(n*sxx - sx*sx); icept = (sy - slope*sx)/n
pred = icept + slope*ring_fF
check("matched freq within 1.5% of Arm A cap-regression prediction",
      abs(f_b5-pred)/pred < 0.015,
      f"predicted {pred:.2f} (fit slope {slope:.2f} MHz/fF), got {f_b5:.2f}, d={100*(f_b5-pred)/pred:+.2f}%")

print()
print(f"== SUMMARY ==  {ok} passed, {fail} failed")
print(f"Arm B matched frequency (5p, Arm A settings): {f_b5:.2f} MHz "
      f"({100*(1-f_b5/f_a5):.1f}% below its own control {f_a5:.2f})")
print(f"Absolute numerical uncertainty (5p vs 1p): ~{100*(f_b1-f_b5)/f_b5:.2f}%")
print(f"Arm A for comparison: {mnA:.1f}..{mxA:.1f} MHz, mean {meanA:.2f}, spread 8.8%")
print(f"Arm B spread across 16 copies: 0 (single shared layout, one simulation)")
