# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
#
# Stress runs on the gate-level netlist with every ring simulated. Needs
# what the gate-level job in test/ needs: iverilog, cocotb 2.0.1 and the
# sky130A PDK at PDK_ROOT. The netlist defaults to the archived release
# build; in CI the gl_test action drops the fresh one at
# test/gate_level_netlist.v, so pass NETLIST=... there. It lives under
# sim/ and not test/ because the mirror copies test/ without its
# subdirectories. See stress.py and make_stress_netlist.py.
#
#   make                            all tests, seed 1, 150 random actions
#   make STRESS_SEED=7 STRESS_N=400 COCOTB_TESTCASE=test_random_protocol

SIM ?= icarus
TOPLEVEL_LANG ?= verilog
SIM_BUILD = sim_build/stress
RELEASE = $(PWD)/../../dualarm/build_armc
NETLIST ?= $(RELEASE)/tt_um_nikodemetrashvili20_ro_puf.nl.v
MACRO_NETLIST ?= $(PWD)/../../dualarm/src/ro_macro_hard.nl.v

COMPILE_ARGS += -DGL_TEST -DFUNCTIONAL -DSIM -DUNIT_DELAY=\#1
CELLS = $(PDK_ROOT)/sky130A/libs.ref/sky130_fd_sc_hd/verilog
VERILOG_SOURCES += $(CELLS)/primitives.v
VERILOG_SOURCES += $(CELLS)/sky130_fd_sc_hd.v
VERILOG_SOURCES += $(PWD)/stress_netlist.v
VERILOG_SOURCES += $(PWD)/tb_stress.v
COCOTB_TOPLEVEL = tb
COCOTB_TEST_MODULES ?= stress

include $(shell cocotb-config --makefiles)/Makefile.sim

# After the include, so that cocotb's own first target stays the default.
$(PWD)/stress_netlist.v: $(NETLIST) $(MACRO_NETLIST) \
		$(PWD)/make_stress_netlist.py
	python3 $(PWD)/make_stress_netlist.py $(NETLIST) $(MACRO_NETLIST) $@
