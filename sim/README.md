# Simulations

Two kinds of work sit here. The Python files at this level are architectural
models that need no external tools. The SPICE work is under `spice/`.

`ref_model.py` reproduces the measurement core in plain Python and checks the
architecture when no Verilog simulator is around. `montecarlo.py` models many
chips and measures how far apart two chips' keys are on average, where the
ideal for a PUF is one half. `h3_audit.py` plays an attacker who knows only an
oscillator's position and tries to predict a chip's key. `ro_macro_sim.v` is a
simulation-only oscillator model.

The two Python chip models are parametric. They show the mechanism with assumed
spread and mismatch numbers, not silicon measurements, and the paper presents
them that way.

`spice/gono/` is a nominal lumped-capacitance experiment on routed-layout
artifacts. `spice/mc/` is a first-order mismatch-sensitivity study. Neither is
a silicon measurement or an entropy/reliability validation; the exact modeled
scope and omitted effects are stated in each subdirectory README.

`spice/magic/` is a second extractor over the release build: magic's
extraction of the same layout through the archive's lumped decks, with and
without metal fill. `chip/PREREG_AMENDMENT_2.json` reads its ring table, and
the gate rebuilds that table from the deck logs. It is not silicon either,
and its README says what it leaves out.

`tt_fit.py` reads Tiny Tapeout's own sources at pinned commits, the precheck,
the multiplexer and the demo board's SDK, and holds the chip and the bench
firmware to them: the layout through four of their precheck functions, what
the build writes over `config.json`, what a project that is not selected
gets, the power switch, the clock the board makes, the SDK calls and who
drives which pin. It needs the three repositories and run 83's final views,
so it is not in the evidence gate. `spice/pg/` has the three decks of the
switch's channel. `docs/phaseG_tt_fit.md` covers both.
