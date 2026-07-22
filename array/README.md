# The matched array

This is Arm B on its own: 16 identical copies of the hardened macro on a
uniform 4x4 grid. It is a standalone test build. The real chip puts both arms
together in `dualarm/`.

`gen_array.py` writes the array RTL and the LibreLane config that places and
powers the 16 macros. `pdnfix4_final/` is a complete archived build. Its final
metrics report zero route/Magic/KLayout DRC, XOR, LVS, antenna, power-grid, and
disconnected-pin violations, but do report **one max-slew violation** at the
slow corner. It should therefore be described as physically clean with one
documented electrical timing-rule exception, not unqualified full signoff.

`met4only_debug/` is mixed-stage diagnostic evidence for the met4-only power
recipe. Its `metrics.json` describes the 3,616-instance final run, while its DEF
is an earlier 409-component checkpoint. They must not be treated as two views
of one final database. `config_met4only.json` records the configuration used.

Powering the macros with met4 alone was the difficult part. It took four builds
to reach the archived physically clean result, with the one slew exception
noted above. The full story and the exact numbers are in
`docs/dualarm_pdn_plan.md`.
