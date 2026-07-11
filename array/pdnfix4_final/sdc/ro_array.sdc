###############################################################################
# Created by write_sdc
###############################################################################
current_design ro_array
###############################################################################
# Timing Constraints
###############################################################################
create_clock -name __VIRTUAL_CLK__ -period 20.0000 
set_clock_uncertainty 0.2500 __VIRTUAL_CLK__
set_input_delay 4.0000 -clock [get_clocks {__VIRTUAL_CLK__}] -add_delay [get_ports {en}]
set_output_delay 4.0000 -clock [get_clocks {__VIRTUAL_CLK__}] -add_delay [get_ports {out[0]}]
set_output_delay 4.0000 -clock [get_clocks {__VIRTUAL_CLK__}] -add_delay [get_ports {out[10]}]
set_output_delay 4.0000 -clock [get_clocks {__VIRTUAL_CLK__}] -add_delay [get_ports {out[11]}]
set_output_delay 4.0000 -clock [get_clocks {__VIRTUAL_CLK__}] -add_delay [get_ports {out[12]}]
set_output_delay 4.0000 -clock [get_clocks {__VIRTUAL_CLK__}] -add_delay [get_ports {out[13]}]
set_output_delay 4.0000 -clock [get_clocks {__VIRTUAL_CLK__}] -add_delay [get_ports {out[14]}]
set_output_delay 4.0000 -clock [get_clocks {__VIRTUAL_CLK__}] -add_delay [get_ports {out[15]}]
set_output_delay 4.0000 -clock [get_clocks {__VIRTUAL_CLK__}] -add_delay [get_ports {out[1]}]
set_output_delay 4.0000 -clock [get_clocks {__VIRTUAL_CLK__}] -add_delay [get_ports {out[2]}]
set_output_delay 4.0000 -clock [get_clocks {__VIRTUAL_CLK__}] -add_delay [get_ports {out[3]}]
set_output_delay 4.0000 -clock [get_clocks {__VIRTUAL_CLK__}] -add_delay [get_ports {out[4]}]
set_output_delay 4.0000 -clock [get_clocks {__VIRTUAL_CLK__}] -add_delay [get_ports {out[5]}]
set_output_delay 4.0000 -clock [get_clocks {__VIRTUAL_CLK__}] -add_delay [get_ports {out[6]}]
set_output_delay 4.0000 -clock [get_clocks {__VIRTUAL_CLK__}] -add_delay [get_ports {out[7]}]
set_output_delay 4.0000 -clock [get_clocks {__VIRTUAL_CLK__}] -add_delay [get_ports {out[8]}]
set_output_delay 4.0000 -clock [get_clocks {__VIRTUAL_CLK__}] -add_delay [get_ports {out[9]}]
###############################################################################
# Environment
###############################################################################
set_load -pin_load 0.0334 [get_ports {out[15]}]
set_load -pin_load 0.0334 [get_ports {out[14]}]
set_load -pin_load 0.0334 [get_ports {out[13]}]
set_load -pin_load 0.0334 [get_ports {out[12]}]
set_load -pin_load 0.0334 [get_ports {out[11]}]
set_load -pin_load 0.0334 [get_ports {out[10]}]
set_load -pin_load 0.0334 [get_ports {out[9]}]
set_load -pin_load 0.0334 [get_ports {out[8]}]
set_load -pin_load 0.0334 [get_ports {out[7]}]
set_load -pin_load 0.0334 [get_ports {out[6]}]
set_load -pin_load 0.0334 [get_ports {out[5]}]
set_load -pin_load 0.0334 [get_ports {out[4]}]
set_load -pin_load 0.0334 [get_ports {out[3]}]
set_load -pin_load 0.0334 [get_ports {out[2]}]
set_load -pin_load 0.0334 [get_ports {out[1]}]
set_load -pin_load 0.0334 [get_ports {out[0]}]
set_driving_cell -lib_cell sky130_fd_sc_hd__inv_2 -pin {Y} -input_transition_rise 0.0000 -input_transition_fall 0.0000 [get_ports {en}]
###############################################################################
# Design Rules
###############################################################################
set_max_transition 0.7500 [current_design]
set_max_capacitance 0.2000 [current_design]
set_max_fanout 10.0000 [current_design]
