#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0

# Placement-density sweep for the multi-build dispersion study (hardware_todo item 9).
#
# LibreLane 3.0.3 does not expose OpenROAD's global-placement random seed, so a
# pure seed-only replicate set is not available in this flow. This sweep instead
# perturbs one neutral placement knob, PL_TARGET_DENSITY_PCT, across a small band
# around the shipped value of 60. Everything else is frozen: the RTL, the macro
# placement, the floorplan size, the constraints, the tool, and the PDK. Only the
# standard-cell placement of the Arm A rings moves, which is the layout variable
# that sets the frequency dispersion. Read the result as a placement-sensitivity
# range, not as a seed distribution.
#
# The density = 60 point rebuilds the shipped config, so it doubles as a
# determinism check: if it reproduces build_current's dispersion, the flow is
# deterministic and the other points show genuine placement sensitivity.
#
# Run from anywhere, with the venv active and PDK_ROOT / PDK exported:
#   bash dualarm/placement_sweep/run_placement_sweep.sh
# Override the LibreLane build directory if it is not ~/siliconchip:
#   TT_BUILD_DIR=/path/to/build bash .../run_placement_sweep.sh
#
# Artifacts per build (netlist, DEF, SPEF, logs) are archived OUTSIDE the repo in
# $ARCH so the repo stays lean. Only the results table and figure are committed.

set -u

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd "$SCRIPT_DIR/../.." && pwd)
GONO="$REPO/sim/spice/gono"
BUILD="${TT_BUILD_DIR:-$HOME/siliconchip}"
CONFIG="$BUILD/src/config.json"
ARCH="${SWEEP_ARCH:-$HOME/placement_sweep_runs}"
LOGDIR="$ARCH/logs"
RESULTS="$SCRIPT_DIR/placement_sweep_results.csv"
DENSITIES="56 57 58 59 60 61 62 63 64"

for need in "$CONFIG" "$GONO/gen_dualarm_decks.py" "$GONO/verify_ring_topology.py"; do
  [ -e "$need" ] || { echo "missing: $need"; exit 1; }
done
mkdir -p "$ARCH" "$LOGDIR"
echo "density,rings_ok,cap_min_fF,cap_max_fF,cap_spread_fF,cap_pct,mean_MHz,ptp_MHz,ptp_pct,std_pct" > "$RESULTS"

ORIG=$(grep -oE '"PL_TARGET_DENSITY_PCT"[[:space:]]*:[[:space:]]*[0-9]+' "$CONFIG" | grep -oE '[0-9]+$')
echo "original PL_TARGET_DENSITY_PCT = ${ORIG:-unknown}; archiving to $ARCH"
cd "$BUILD" || exit 1
git config user.email >/dev/null 2>&1 || git config user.email "sweep@local"
git config user.name  >/dev/null 2>&1 || git config user.name  "placement sweep"

set_density() {  # $1 = value; edits only the numeric value, preserves the rest
  python3 - "$CONFIG" "$1" <<'PY'
import re, sys
path, val = sys.argv[1], sys.argv[2]
s = open(path).read()
assert re.search(r'"PL_TARGET_DENSITY_PCT"\s*:\s*\d+', s), "PL_TARGET_DENSITY_PCT not found"
open(path, "w").write(re.sub(r'("PL_TARGET_DENSITY_PCT"\s*:\s*)\d+', r'\g<1>'+val, s, count=1))
PY
}

for D in $DENSITIES; do
  echo "==================== density $D ===================="
  set_density "$D" || { echo "$D,SET_FAIL,,,,,,,," >> "$RESULTS"; continue; }
  git add -A && git commit -q -m "placement sweep: PL_TARGET_DENSITY_PCT=$D" 2>/dev/null || true
  python tt/tt_tool.py --create-user-config >/dev/null 2>&1

  BLOG="$LOGDIR/harden_d$D.log"
  if python tt/tt_tool.py --harden >"$BLOG" 2>&1; then
    echo "  harden OK"
  else
    echo "  harden FAILED (see $BLOG)"; echo "$D,HARDEN_FAIL,,,,,,,," >> "$RESULTS"; continue
  fi

  F=$(ls -dt "$BUILD"/runs/*/final 2>/dev/null | head -1)
  DST="$ARCH/d$D"; mkdir -p "$DST"
  cp "$F/nl/"*.nl.v "$DST/" 2>/dev/null
  cp "$F/def/"*.def "$DST/" 2>/dev/null
  cp "$F/spef/nom/"*.nom.spef "$DST/" 2>/dev/null
  NL=$(ls "$DST/"*.nl.v 2>/dev/null | head -1)
  SPEF=$(ls "$DST/"*.nom.spef 2>/dev/null | head -1)
  DEFF=$(ls "$DST/"*.def 2>/dev/null | head -1)
  if [ -z "$NL" ] || [ -z "$SPEF" ] || [ -z "$DEFF" ]; then
    echo "  artifacts missing after harden"; echo "$D,NO_ARTIFACTS,,,,,,,," >> "$RESULTS"; continue
  fi
  case "$F" in */runs/*) rm -rf "$(dirname "$F")" 2>/dev/null;; esac   # free disk; next harden recreates it

  if python3 "$GONO/verify_ring_topology.py" --netlist "$NL" >"$LOGDIR/rings_d$D.log" 2>&1; then RINGS=ok; else RINGS=FAIL; fi

  OUT="$ARCH/gono_d$D"; mkdir -p "$OUT"
  python3 "$GONO/gen_dualarm_decks.py" --spef "$SPEF" --def "$DEFF" --output-dir "$OUT" >"$LOGDIR/gen_d$D.log" 2>&1
  ( cd "$GONO" && python3 ../run_ngspice.py "$OUT/dualarm_par.spice" --log "$OUT/dualarm_par_out.txt" ) >/dev/null 2>&1

  python3 - "$D" "$RINGS" "$OUT/dualarm_par.spice" "$OUT/dualarm_par_out.txt" "$RESULTS" <<'PY'
import re, sys, statistics as st
D, rings, deck, log, res = sys.argv[1:6]
def readfile(p):
    try: return open(p).read()
    except OSError: return ""
t = {}
for m in re.finditer(r'^C(\d+)_n\d+\s+\S+\s+0\s+([0-9.eE+-]+)', readfile(deck), re.M):
    i = int(m.group(1)); t[i] = t.get(i, 0.0) + float(m.group(2))
caps = [t[i]*1e15 for i in range(16)] if len(t) >= 16 else []
f = [float(b)/1e6 for a, b in re.findall(r'f(\d+) = ([0-9.eE+-]+)', readfile(log))]
def add(*a): open(res, "a").write(",".join(str(x) for x in a) + "\n")
if len(f) >= 16 and caps:
    mean = sum(f)/16; ptp = max(f)-min(f); std = st.pstdev(f)
    cmin, cmax, cmean = min(caps), max(caps), sum(caps)/16
    add(D, rings, f"{cmin:.1f}", f"{cmax:.1f}", f"{cmax-cmin:.1f}", f"{100*(cmax-cmin)/cmean:.0f}",
        f"{mean:.1f}", f"{ptp:.1f}", f"{100*ptp/mean:.2f}", f"{100*std/mean:.2f}")
    print(f"  d{D}: {100*ptp/mean:.2f}% p-p  (mean {mean:.1f} MHz, cap spread {cmax-cmin:.1f} fF, rings {rings})")
else:
    add(D, rings + "_NOFREQ", "", "", "", "", "", "", "", "")
    print(f"  d{D}: frequency extraction failed")
PY
done

set_density "${ORIG:-60}"
git add -A && git commit -q -m "placement sweep: restore PL_TARGET_DENSITY_PCT=${ORIG:-60}" 2>/dev/null || true
echo "==================== sweep complete ===================="
echo "results: $RESULTS"
( command -v column >/dev/null && column -s, -t "$RESULTS" ) || cat "$RESULTS"
