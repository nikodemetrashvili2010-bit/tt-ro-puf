# Release build, Arm A and Arm C ring decks

The sixteen Arm A rings and the sixteen Arm C rings of run 83's three-arm
build (`dualarm/build_armc/`), each as two decks from `gen_rc_decks.py`: one
with every ring net's extracted capacitance lumped on a single node, one with
the SPEF's resistors and coupling capacitors wired as extracted. Run on
2026-09-20 with ngspice 42 against the hand-assembled sky130A tree described
in `docs/phaseG_spice_rerun.md`, one ngspice thread per deck.

    armA/       tt, lumped and RC, 32 decks and their logs
    armC/       the same for Arm C, made with --arm C
    armA_ss/    lumped only, ss 100 C 1.60 V
    armA_ff/    lumped only, ff -40 C 1.95 V
    armC_ss/    as armA_ss, for Arm C
    armC_ff/    as armA_ff, for Arm C

Regenerating a deck, from `sim/spice/gono/`:

    SPEF=../../../dualarm/build_armc/tt_um_nikodemetrashvili20_ro_puf.nom.spef
    python3 gen_rc_decks.py --ro 7 --spef $SPEF
    python3 gen_rc_decks.py --arm C --ro 7 --corner ss --spef $SPEF

The corner decks come out named `ro07_ss_lumped.spice`; they are stored as
`ro07_lumped.spice` in their corner directory. The absolute PDK paths inside a
deck are the machine they ran on, and `../run_ngspice.py` swaps them for
`PDK_ROOT` at run time.

The tables made from these logs are `../rc_validation_3arm.csv` and
`../rc_validation_armc.csv`, written by

    python3 analyze_rc.py --dir rc3/armA --ro $(seq 0 15) --spef $SPEF \
        --csv rc_validation_3arm.csv
    python3 analyze_rc.py --arm C --dir rc3/armC --ro $(seq 0 15) \
        --spef $SPEF --csv rc_validation_armc.csv

The same environment reproduces the baseline archive: ring 7 of the two-arm
build comes back at 571.82 MHz lumped and 567.91 MHz with the full RC network,
the two numbers `rc_validation.csv` recorded in July.
