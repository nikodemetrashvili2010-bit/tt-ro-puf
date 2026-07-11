#!/usr/bin/env python3
# Independent re-verification of the go/no-go result. Recomputes everything from
# the raw ngspice logs + SPEF with fresh code (does NOT import analyze.py), and
# cross-checks against gono_results.csv. Prints PASS/FAIL on each check.
import re, os, csv, math

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SPEF = os.path.join(PROJ, "gds_build", "runs", "wokwi", "final", "spef", "nom",
                    "tt_um_nikodemetrashvili20_ro_puf.nom.spef")

def read_fN(path):
    d = {}
    for line in open(path):
        m = re.match(r'^f(\d+)\s*=\s*([0-9.eE+\-]+)', line)
        if m:
            d[int(m.group(1))] = float(m.group(2))
    return d

def pearson(a, b):
    n = len(a); ma = sum(a)/n; mb = sum(b)/n
    num = sum((a[i]-ma)*(b[i]-mb) for i in range(n))
    da = math.sqrt(sum((v-ma)**2 for v in a)); db = math.sqrt(sum((v-mb)**2 for v in b))
    return num/(da*db)

def ranks(v):
    order = sorted(range(len(v)), key=lambda i: v[i]); r = [0]*len(v)
    for pos, i in enumerate(order): r[i] = pos
    return r

PASS = []; FAIL = []
def chk(name, cond, detail=""):
    (PASS if cond else FAIL).append(name + ("" if not detail else f"  [{detail}]"))

par  = read_fN(os.path.join(HERE, "par2.txt"))
ctrl = read_fN(os.path.join(HERE, "ctrl2.txt"))
chk("par2.txt has 32 freqs", len(par) == 32, f"got {len(par)}")
chk("ctrl2.txt has 32 freqs", len(ctrl) == 32, f"got {len(ctrl)}")

# control must be identical across all 32
cvals = list(ctrl.values())
chk("control all identical (spread < 1 kHz)", (max(cvals)-min(cvals)) < 1e3,
    f"min={min(cvals):.3e} max={max(cvals):.3e}")

# parasitic all physical: every RO <= control (caps only slow)
fctrl = cvals[0]
chk("every parasitic freq <= control", all(v <= fctrl+1e3 for v in par.values()),
    f"max_par={max(par.values()):.3e} ctrl={fctrl:.3e}")

# load csv
rows = {}
with open(os.path.join(HERE, "gono_results.csv")) as f:
    for r in csv.DictReader(f):
        rows[int(r["ro"])] = (float(r["x_um"]), float(r["y_um"]),
                              float(r["ring_cap_fF"]), float(r["freq_MHz"]))

# cross-check csv freq vs par2.txt
md = max(abs(par[i]/1e6 - rows[i][2 + 1]) for i in range(32))
chk("csv freq_MHz matches par2.txt", md < 0.01, f"max diff {md:.4g} MHz")

# independent SPEF re-parse -> per-RO ring cap (fF), compare to csv
num2name, name2cap = {}, {}
for line in open(SPEF):
    m = re.match(r'^\*(\d+)\s+(\S+)\s*$', line)
    if m:
        num2name[m.group(1)] = m.group(2).replace("\\", ""); continue
    if line.startswith("*D_NET"):
        p = line.split(); nm = num2name.get(p[1].lstrip("*"))
        if nm: name2cap[nm] = float(p[2])
def ring_fF(i):
    return sum(name2cap.get(f"u_puf.u_core.g_ro_bank[{i}].u_ro.n[{k}]", 0.0)
               for k in range(31)) * 1000.0
capdiff = max(abs(ring_fF(i) - rows[i][2]) for i in range(32))
chk("SPEF re-parse matches csv ring cap", capdiff < 0.01, f"max diff {capdiff:.4g} fF")

# recompute stats independently
f   = [par[i]/1e6 for i in range(32)]
cap = [rows[i][2] for i in range(32)]
x   = [rows[i][0] for i in range(32)]
y   = [rows[i][1] for i in range(32)]
mean = sum(f)/32
pstd = math.sqrt(sum((v-mean)**2 for v in f)/32)
sstd = math.sqrt(sum((v-mean)**2 for v in f)/31)
ptp  = max(f)-min(f)
cx, cy = (min(x)+max(x))/2, (min(y)+max(y))/2
rad = [math.hypot(x[i]-cx, y[i]-cy) for i in range(32)]
r_cap = pearson(f, cap)
r_x, r_y, r_r = pearson(f, x), pearson(f, y), pearson(f, rad)
mc = sum(cap)/32
slope = sum((cap[i]-mc)*(f[i]-mean) for i in range(32))/sum((c-mc)**2 for c in cap)
spear = pearson(ranks(cap), ranks(f))

imin = min(range(32), key=lambda i: f[i]); imax = max(range(32), key=lambda i: f[i])
chk("slowest RO has the most cap", cap[imin] == max(cap), f"RO{imin} cap={cap[imin]:.1f}")
chk("fastest RO has the least cap", cap[imax] == min(cap), f"RO{imax} cap={cap[imax]:.1f}")
chk("freq-cap correlation strongly negative", r_cap < -0.99, f"r={r_cap:.4f}")

print("="*64)
print("INDEPENDENT RE-VERIFICATION")
print("="*64)
print(f"control freq (all 32)      : {fctrl/1e6:.3f} MHz  (spread {(max(cvals)-min(cvals)):.1f} Hz)")
print(f"parasitic mean             : {mean:.2f} MHz")
print(f"parasitic std (population)  : {pstd:.2f} MHz ({100*pstd/mean:.2f}%)")
print(f"parasitic std (sample)      : {sstd:.2f} MHz ({100*sstd/mean:.2f}%)")
print(f"min / max                   : {min(f):.2f} (RO{imin}) / {max(f):.2f} (RO{imax}) MHz")
print(f"peak-to-peak                : {ptp:.2f} MHz ({100*ptp/mean:.2f}% of mean)")
print(f"corr(freq, ring_cap)        : {r_cap:.4f}")
print(f"spearman(freq, ring_cap)    : {spear:.4f}")
print(f"regression slope            : {slope:.2f} MHz/fF")
print(f"corr(freq, x/y/radius)      : {r_x:+.3f} / {r_y:+.3f} / {r_r:+.3f}")
print(f"cap range                   : {min(cap):.1f} - {max(cap):.1f} fF (mean {mc:.1f})")
print()
print(f"CHECKS PASSED ({len(PASS)}):")
for s in PASS: print("  [OK]", s)
if FAIL:
    print(f"\nCHECKS FAILED ({len(FAIL)}):")
    for s in FAIL: print("  [!!]", s)
else:
    print("\nALL CHECKS PASSED.")
