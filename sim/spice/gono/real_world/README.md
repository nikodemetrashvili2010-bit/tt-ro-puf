# Supply and wire current decks, release build

What `../real_world.py` reads for its heat and current checks. Run on
2026-09-20, ngspice 42, the same sky130A tree as `../rc3/`.

    A00 A04 A14   Arm A rings 0, 4 and 14; 4 is the lightest loop and 14
                  the heaviest, 0 sits between
    C00 C04 C14   the same ring numbers in Arm C
    _tt _ss _ff   27 C 1.80 V, 100 C 1.60 V, -40 C 1.95 V
    mux_A00_ff    the three-arm selector path A00 with its extracted
                  macro ring and the first counter flop, at ff
    net_*_ff      one ring wire each, with a 0 V source between the driving
                  cell's output and the net: Arm A ring 15 node 30, Arm A
                  ring 5 node 15 (the tap) and Arm C ring 6 node 30, the
                  three heaviest ring wires in the release SPEF

The ring decks are the lumped decks `gen_rc_decks.py` writes, with three
changes and nothing else: `i(Vdd)` added to the `.save` line, and after
`let f = 20 / tp` the lines

    meas tran iavg AVG i(Vdd) FROM=20n TO=140n
    meas tran irms RMS i(Vdd) FROM=20n TO=140n
    meas tran ipk MIN i(Vdd) FROM=20n TO=140n

The `net_` decks change the driving inverter's output node to `n<k>_d`, add
`Vsense n<k>_d n<k> 0`, and measure `i(Vsense)` the same way (average, RMS,
most positive, most negative). The selector deck is
`../mux3/mux_A00.spice` with its `wrdata` line replaced by the same three
supply measurements over 10 to 42 ns and a period measurement on the tap.

ngspice reports the current into the source's positive terminal, so a supply
delivering current reads negative. `real_world.py` flips the sign.
