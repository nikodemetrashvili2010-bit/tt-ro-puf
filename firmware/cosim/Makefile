# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
#
# measure_puf.py against the chip's RTL, under cocotb and Icarus. The rings
# are the behavioural models the cocotb regression in test/ uses. Needs
# iverilog and cocotb 2.0.1 (test/requirements.txt).
#
#   make                              all three hosts
#   make COCOTB_TEST_FILTER=typical   one of them

SIM ?= icarus
TOPLEVEL_LANG ?= verilog
SIM_BUILD = sim_build/rtl
SRC_DIR = $(PWD)/../../src
VERILOG_SOURCES += $(addprefix $(SRC_DIR)/,ro_macro_sim.v ro_armc_sim.v \
                   ro_puf_core.v ro_puf.v tt_um_ro_puf.v)
VERILOG_SOURCES += $(PWD)/../../test/ro_macro_hard_sim.v
VERILOG_SOURCES += $(PWD)/tb_cosim.v
COCOTB_TOPLEVEL = tb
COCOTB_TEST_MODULES = cosim_firmware

include $(shell cocotb-config --makefiles)/Makefile.sim
