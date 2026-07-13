# The matched array

This is Arm B on its own: 16 identical copies of the hardened macro on a
uniform 4x4 grid. It is a standalone test build. The real chip puts both arms
together in `dualarm/`.

`gen_array.py` writes the array RTL and the LibreLane config that places and
powers the 16 macros. `pdnfix4_final/` is the signed-off build, with DRC, LVS,
antenna and power connectivity all clean. `met4only_debug/` holds the evidence
for the met4-only power recipe, the metrics and the DEF that show continuous
power stripes over every macro. `config_met4only.json` is the configuration it used.

Powering the macros with met4 alone was the difficult part. It took four builds
to reach a clean signoff. The full story and the exact numbers are in
`docs/dualarm_pdn_plan.md`.
