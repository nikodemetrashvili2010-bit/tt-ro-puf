# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
#
# Build and run the simulations with Icarus Verilog.
#
#   make         run the two-arm testbench
#   make tt      run the TinyTapeout wrapper testbench
#   make core    run the core unit testbench
#   make waves   run the two-arm test, then open the waveform
#   make clean   remove build artifacts
#
# Simulation uses the behavioural oscillator model (sim/ro_macro_sim.v) in
# place of the real cell (rtl/ro_macro.v), which is a logic loop and cannot run
# in an event simulator. Windows users without `make` can run the iverilog/vvp
# commands by hand.

IVERILOG ?= iverilog
VVP      ?= vvp
GTKWAVE  ?= gtkwave
IFLAGS   ?= -g2012

RTL := sim/ro_macro_sim.v rtl/ro_puf_core.v rtl/ro_puf.v

.PHONY: all sim tt core waves clean
all: sim

sim:
	$(IVERILOG) $(IFLAGS) -o sim_out $(RTL) tb/tb_ro_puf.v
	$(VVP) sim_out

tt:
	$(IVERILOG) $(IFLAGS) -o tt_out $(RTL) rtl/tt_um_ro_puf.v tb/tb_tt_um_ro_puf.v
	$(VVP) tt_out

core:
	$(IVERILOG) $(IFLAGS) -o core_out sim/ro_macro_sim.v rtl/ro_puf_core.v tb/tb_ro_puf_core.v
	$(VVP) core_out

waves: sim
	$(GTKWAVE) tb_ro_puf.vcd

clean:
	rm -f sim_out tt_out core_out *.vcd
