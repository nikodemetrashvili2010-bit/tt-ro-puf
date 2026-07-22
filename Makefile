# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
#
# Build and run the simulations with Icarus Verilog.
#
#   make         run the production two-arm testbench
#   make check   run production core, two-arm, and wrapper testbenches
#   make tt      run the production TinyTapeout wrapper testbench
#   make core    run the production core unit testbench
#   make waves   run the production two-arm test, then open the waveform
#   make clean   remove build artifacts
#
# The tapeout source of truth is src/. Simulation substitutes src/ro_macro_sim.v
# and test/ro_macro_hard_sim.v for the two physical oscillator implementations.
# The older single-bank reference sources remain under rtl/ but are not used by
# these production tests.

IVERILOG ?= iverilog
VVP      ?= vvp
GTKWAVE  ?= gtkwave
IFLAGS   ?= -g2012

CORE_RTL := src/ro_macro_sim.v src/ro_puf_core.v
PUF_RTL  := $(CORE_RTL) src/ro_puf.v test/ro_macro_hard_sim.v
TOP_RTL  := $(PUF_RTL) src/tt_um_ro_puf.v

.PHONY: all sim check puf tt core waves clean
all: sim

sim: puf

check: core puf tt

puf:
	$(IVERILOG) $(IFLAGS) -Wall -o sim_out $(PUF_RTL) tb/tb_ro_puf.v
	$(VVP) sim_out

tt:
	$(IVERILOG) $(IFLAGS) -Wall -o tt_out $(TOP_RTL) tb/tb_tt_um_ro_puf.v
	$(VVP) tt_out

core:
	$(IVERILOG) $(IFLAGS) -Wall -o core_out $(CORE_RTL) test/ro_macro_hard_sim.v tb/tb_ro_puf_core.v
	$(VVP) core_out

waves: sim
	$(GTKWAVE) tb_ro_puf.vcd

clean:
	rm -f sim_out tt_out core_out *.vcd
