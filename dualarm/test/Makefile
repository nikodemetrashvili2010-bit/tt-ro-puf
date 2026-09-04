# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
#
# cocotb test makefile, three-arm version (v3). RTL simulation uses
# behavioural oscillator models in place of the real cells: ro_macro_sim.v for
# Arm A, ro_armc_sim.v for Arm C, and ro_macro_hard_sim.v (parameterless, all
# copies identical - that is the point of the matched arm) for Arm B.
# Gate-level simulation uses the post-layout Arm-A and Arm-C logic while
# preserving the intentional Arm-B hard-macro boundary and supplying that
# boundary's parameterless functional model.
#
# Two test modules. `make` runs the protocol regression in test.py. `make
# E2=yes` runs the E.2 acceptance table in test_e2.py, which is G.3 step 6 and
# works chip/e2_tb_plan.csv row by row.

SIM ?= icarus
FST ?= -fst
TOPLEVEL_LANG ?= verilog
SRC_DIR = $(PWD)/../src
PROJECT_SOURCES = ro_macro_sim.v ro_armc_sim.v ro_puf_core.v ro_puf.v \
                  tt_um_ro_puf.v

ifneq ($(GATES),yes)

# RTL simulation
SIM_BUILD        = sim_build/rtl
VERILOG_SOURCES += $(addprefix $(SRC_DIR)/,$(PROJECT_SOURCES))
VERILOG_SOURCES += $(PWD)/ro_macro_hard_sim.v

else

# Gate-level simulation
SIM_BUILD        = sim_build/gl
COMPILE_ARGS    += -DGL_TEST
COMPILE_ARGS    += -DFUNCTIONAL
COMPILE_ARGS    += -DUSE_POWER_PINS
COMPILE_ARGS    += -DSIM
COMPILE_ARGS    += -DUNIT_DELAY=\#1
VERILOG_SOURCES += $(PDK_ROOT)/sky130A/libs.ref/sky130_fd_sc_hd/verilog/primitives.v
VERILOG_SOURCES += $(PDK_ROOT)/sky130A/libs.ref/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd.v
VERILOG_SOURCES += $(PWD)/gate_level_netlist.v
# The top-level GL netlist intentionally preserves the physical Arm-B macro as
# a black box. Supply its parameterless functional model so elaboration and the
# project-level protocol test cover that boundary. The macro's extracted
# transistor behavior is verified separately by the physical flow.
VERILOG_SOURCES += $(PWD)/ro_macro_hard_sim.v

endif

VERILOG_SOURCES += $(PWD)/tb.v
COCOTB_TOPLEVEL = tb

ifeq ($(E2),yes)
COCOTB_TEST_MODULES = test_e2
else
COCOTB_TEST_MODULES = test
endif

include $(shell cocotb-config --makefiles)/Makefile.sim
