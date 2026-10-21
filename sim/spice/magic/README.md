# A second extractor, and metal fill

This folder is magic's extraction of the release build, the layout the
shuttle holds, run through the archive's own ring decks with and without
metal fill. It exists because every prediction in this repository came
through one extractor, OpenRCX, by way of the SPEF.

It was run on 20 October 2026 outside the repository and brought in on the
21st, because `chip/PREREG_AMENDMENT_2.json` now reads its ring table,
`magic_rings.csv`. Nothing the chip is built from changed for any of it.

## Why there is a second extractor at all

After submission Tiny Tapeout swaps a tenth of the top-level decap_3 cells
for a fill cell, and metal fill goes in later still. Whether the fill
reaches inside a project tile, and which tool draws it, is not confirmed
`[uncertain]`. Checking fill needs an extractor that can see it, and magic
can. It also sees inside the standard cells, which the SPEF never does,
so the same run is a second opinion on every ring with no fill at all.

## Setup

- magic 8.3.685, built from source (`bed8d4ff`)
- `sky130A.tech` and `sky130A-GDS.tech` preprocessed from open_pdks
  `8afc8346`, the PDK the shuttle pins, with `common/preproc.py
  -DTECHNAME=sky130A -DMETAL5 -DMIM -DREDISTRIBUTION` as its Makefile does
- ngspice 42; sky130_fd_pr models at `1232782c` and the hd cells at
  `892688b`, the two commits open_pdks pins. The archive's own
  `sim/spice/gono/rc3/armA/ro00_lumped.spice` gives 550.9165 MHz in this
  setup, the archived number to the last digit (`results/check.txt`)
- the layout: the shuttle's copy (`TinyTapeout/tinytapeout-sky-26d`,
  branch `projects/tt_um_nikodemetrashvili20_ro_puf-36036095908`) written
  out as GDS. It XORs to nothing against `dualarm/build_armc`'s GDS on all
  36 layers. And the same copy after the shuttle's decap swap

## How

1. **Fill.** `make_fill.py` runs the commands of open_pdks'
   `generate_fill.py`: `sky130A-GDS.tech`, `cif ostyle wafflefill(tiled)`,
   the tile flattened 1.6 um past the fill box. One tile, the design grown
   5 um on each side. The fill grid hangs off the box corner and where it
   lands on the chip is unknown, so four grid positions: (0, 0), (1.37,
   0.91), (0.53, 2.17) and (2.29, 1.61) um. About 210000 squares each
   (`results/fill_counts.txt`)
2. **Into the extractor.** magic's extraction rules have no fill types, so
   fill read in as fill adds nothing. `merge_fill.py` puts poly, li1 and
   met1 to met4 fill onto the drawn layers, flat in the top cell, where
   every square is a floating conductor of its own. Diff fill needs
   implants to mean anything here, and met5 over the tile is Tiny Tapeout's
   power grid in the chip, so both are left out
3. **Extract.** `extract.sh`: flat, capacitance and coupling, no
   resistance, every capacitor kept. About 4 minutes without fill and 8
   with
4. **Loads.** `ring_loads.py` and `node_caps.py`. A ring's loop is its 31
   nets and a net's load is every capacitor on it, the way a SPEF total
   counts. A fill square that couples Crf to a ring net and Cf in all adds
   Crf (Cf - Crf) / Cf, its series path with everything else held still
5. **Frequencies.** `gen_decks.py` writes the archive's lumped deck with
   magic's loads in place of the SPEF's: 96 decks, `decks_base` and
   `decks_fill0`, fill at the first grid position. The other three grid
   positions move each ring from there by the fitted slope times its change
   in fill load (`phase_bits.py`). `coupled_decks.py` keeps a ring's own
   couplings as couplings, for A00, A01, C12 and C13
6. **The table.** `tabulate.py` writes `magic_rings.csv` from the logs in
   `decks_base` and `decks_fill0`. The gate writes it again and diffs it

A separation below is f_a - f_b as a percent of the arm's mean frequency in
the same table, the way `sim/spice/gono/predictable_bits.py` and
`extraction/TOLERANCES.json` count it. The notes of 20 October divided by
the pair's own mean, which moves a number by 0.06 at most.

## What it found

Arm A's pairs, and Arm C's C12/C13, positive when the even ring is faster.
The SPEF column is `sim/spice/gono/rc_validation_3arm.csv` and
`rc_validation_armc.csv`, the full RC decks the predictions come from. The
magic columns are lumped decks, one capacitor per net, because the
extraction was capacitance only:

    pair      SPEF     magic    magic + fill, four positions
    A00/A01  +1.083   -0.015   -0.033 to -0.328
    A02/A03  +0.212   -0.058   -0.000 to +0.126     abstains
    A04/A05  +2.037   +1.628   +1.641 to +1.825
    A06/A07  -1.423   -2.428   -1.753 to -1.957
    A08/A09  -0.316   -1.520   -1.254 to -1.494     abstains
    A10/A11  -2.291   -0.964   -0.685 to -0.975
    A12/A13  -2.878   -2.258   -2.052 to -2.225
    A14/A15  -1.840   -2.992   -1.044 to -1.168
    C12/C13  +1.201   +2.220   -0.075 to -0.164

`results/compare_base_fill0.txt` and `results/phase_bits.txt` have every
pair of all three arms.

- Five of the six pairs the SPEF scores in Arm A keep its sign in every
  view, and stay over the abstention line, 0.6179, in every one.
- **A00/A01 does not.** The SPEF has A00 faster by 1.08 percent. magic has
  the two level, -0.015, and A01 ahead once fill is in. Keeping the ring's
  own couplings, run for A00, A01, C12 and C13 only, still has A01 ahead
  by about 0.1 percent with and without fill (`results/cpl.txt`), and a
  run of twenty periods in 140 ns gives the same as ten
  (`decks_long/`). magic sees 18.58 fF more than the SPEF on A00 and 17.32
  on A01, spread over most of the 31 nets, so the SPEF's 1.36 fF between
  them nearly closes. Which of the two is nearer silicon this does not say.
- The two columns are not the same kind of deck. In the SPEF's own lumped
  decks, the `lumped_MHz` column of the same tables, A00/A01 is +1.069, so
  the split on it is the extractor's and not the resistance's, and Arm A's
  other five scored pairs clear the line there too. Arm C's 4/5 and 14/15
  do not: -0.588 and -0.602 lumped, against -1.322 and -0.648 in the RC
  decks.
- Fill adds 2.4 to 5.8 fF to every ring: 54.5 percent of it from met2
  fill, 33.9 from met3, 7.7 from met1 and 3.9 from met4.
  That is 1.8 to 4.4 percent of frequency at 0.749 percent a fF, fitted
  across the 48 rings with a residual of 0.061. The amount is set by the
  layout, not by where the grid lands: from one grid position to another
  the difference across rings has a standard deviation of 0.10 to 0.16 fF,
  and each position correlates with the first at 0.96 to 0.99 in Arm A,
  0.99 or more in Arm C and 0.68 to 0.87 in Arm B.
- With no fill, magic sees 17 to 20 fF more than the SPEF on every ring of
  Arms A and C, and across rings the two agree at Pearson 0.94 in Arm A
  and 0.77 in Arm C (`results/crosscheck.txt`). On ordinary routed nets
  they agree on the whole, a median ratio of 0.968 with quartiles 0.81
  and 1.09 over 185 nets above 5 fF, which points at what the SPEF does
  not cover, the wiring inside the cells.
- **Arm B is not 0.0033 percent apart in magic's view.** The macro's LEF
  blocks met2 only over the middle of the macro and met3 over one stripe,
  so the top level routes across the macro cores, and magic couples 0.03
  fF (B11) to 0.74 fF (B15) of top-level nets onto the ring nets, each
  macro's own enable and output routes included. Arm B spreads 0.495
  percent without fill and 0.16 to 0.26 with it over the four grid
  positions, and with fill some of its pair signs move with the grid
  position. The archive's Arm B decks only had each macro's own enable and
  output routes as loads, because the SPEF never sees inside a macro.
- M4, Arm C's standard deviation over Arm A's, is 0.36 from the SPEF, 0.47
  from magic and 0.20 to 0.23 with fill. Run through
  `chip/primary_tests.py` with the ring frequencies as they stand, p(1) is
  0.0011, 0.012 and at most 0.00011, all under 0.025.
- Absolute speed: with fill, Arm A runs 452 to 474 MHz and Arm C 476 to
  482 at tt, against 534 to 566 and 567 to 579 in the SPEF's RC decks. At
  the 2048 window and 50 MHz that is about 18500 to 19400 counts for Arm A,
  against 21866 to 23183 from the RC decks. `docs/info.md` quotes 22052 to
  23347, from the release build's lumped decks, 538.4 to 570.0 MHz.

The decap swap, extracted the same way: 0.023 fF at most on any ring
(`results/loads_swapped.csv` against `results/loads_base.csv`).

## What it changed

`chip/PREREG_AMENDMENT_2.json`, 21 October, with no die read: a pair is
scored only when this table and the SPEF's both put it over the
abstention line with the same sign. This table is lumped and the SPEF's
is full RC, as above. Arm A keeps five scored pairs, 4/5, 6/7, 10/11,
12/13 and 14/15, and A00/A01 abstains. See
`docs/phaseG_prereg_amendment_2.md`.

## Files

- `magic_rings.csv`: the 48 ring frequencies in MHz, no fill and fill at
  the first grid position, written by `tabulate.py`
- `decks_base/`, `decks_fill0/`: the 96 decks and their logs.
  `decks_cpl_base/` and `decks_cpl_fill0/`: four rings with their own
  couplings. `decks_long/`: A00 and A01, twenty periods in 140 ns.
  `decks_check/`: the archive's ro00 loads in this deck at ten periods,
  with its log, and the log of the same deck run at twenty periods in
  80 ns. `LIB` and `CELLS` in every deck stand for the two library paths,
  which `gen_decks.py` writes in
- `results/`: the ring loads (`loads_*.csv`), the per-node loads the decks
  were written from (`nodes_*.json`), the two pair tables, the
  cross-check, the coupled rings and the fill counts
- `spiceinit` is sky130_fd_pr's `models/.spiceinit` set to one thread

## Not covered

- magic works from 2.5D rules and OpenRCX from calibrated ones. Neither is
  a field solver and neither is silicon. This shows the A00/A01 call
  depends on the extractor, not which extractor is right
- the real fill tool and its settings are not public
- tt only, lumped decks, plus the coupled check on four rings. No Monte
  Carlo and no other corner
- the swap and fill were not extracted together. The swap moves 0.023 fF
  at most, against 0.10 to 0.16 fF between fill grid positions

## Rerun

`run_fill.sh` says what it needs, about two hours on two cores. Run it in
a copy of this folder without the `decks_*` folders: `run_decks.sh` skips
every deck that already has a log.

    python3 tabulate.py --selftest
    python3 tabulate.py --csv /tmp/magic_rings.csv
    diff /tmp/magic_rings.csv magic_rings.csv
