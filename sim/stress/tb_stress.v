// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
// SPDX-License-Identifier: Apache-2.0
//
// Testbench for the stress runs: the design plus monitors on every ring
// enable and every ring output. Slot order is the selector order, so
// en_vec[s] is what active_sel == s enables: 0..15 Arm A, 16..31 Arm B,
// 32..47 Arm C.
`default_nettype none
`timescale 1ns / 1ps
module tb ();
  reg        clk;
  reg        rst_n;
  reg        ena;
  reg  [7:0] ui_in;
  reg  [7:0] uio_in;
  wire [7:0] uo_out;
  wire [7:0] uio_out;
  wire [7:0] uio_oe;

  tt_um_nikodemetrashvili20_ro_puf user_project (
      .ui_in  (ui_in),
      .uo_out (uo_out),
      .uio_in (uio_in),
      .uio_out(uio_out),
      .uio_oe (uio_oe),
      .ena    (ena),
      .clk    (clk),
      .rst_n  (rst_n)
  );

  wire [47:0] en_vec;
  wire [47:0] out_vec;
  // Probes on the counter side, for the restart experiment.
  wire sel_ro_probe  = user_project.\u_puf.u_core.sel_ro ;
  wire cnt_rst_probe = user_project.\u_puf.u_core.cnt_rst_n ;
  wire [5:0] active_sel_probe = {
    user_project.\u_puf.u_core.active_sel[5] ,
    user_project.\u_puf.u_core.active_sel[4] ,
    user_project.\u_puf.u_core.active_sel[3] ,
    user_project.\u_puf.u_core.active_sel[2] ,
    user_project.\u_puf.u_core.active_sel[1] ,
    user_project.\u_puf.u_core.active_sel[0] };
  wire [15:0] cnt_probe = {
    user_project.\u_puf.u_core.g_ripple[15].q ,
    user_project.\u_puf.u_core.g_ripple[14].q ,
    user_project.\u_puf.u_core.g_ripple[13].q ,
    user_project.\u_puf.u_core.g_ripple[12].q ,
    user_project.\u_puf.u_core.g_ripple[11].q ,
    user_project.\u_puf.u_core.g_ripple[10].q ,
    user_project.\u_puf.u_core.g_ripple[9].q ,
    user_project.\u_puf.u_core.g_ripple[8].q ,
    user_project.\u_puf.u_core.g_ripple[7].q ,
    user_project.\u_puf.u_core.g_ripple[6].q ,
    user_project.\u_puf.u_core.g_ripple[5].q ,
    user_project.\u_puf.u_core.g_ripple[4].q ,
    user_project.\u_puf.u_core.g_ripple[3].q ,
    user_project.\u_puf.u_core.g_ripple[2].q ,
    user_project.\u_puf.u_core.g_ripple[1].q ,
    user_project.\u_puf.u_core.g_ripple[0].q };
  // Rising edges on the counter clock while the reset is released and no
  // ring is enabled: an edge the window did not ask for.
  integer stray_clock_edges = 0;
  always @(posedge sel_ro_probe) begin
    if (monitors_armed && cnt_rst_probe === 1'b1 && en_vec == 48'b0)
      stray_clock_edges = stray_clock_edges + 1;
  end

  assign en_vec[0] = user_project.\u_puf.u_core.g_ro_bank[0].u_ro.en ;
  assign out_vec[0] = user_project.\u_puf.u_core.g_ro_bank[0].u_ro.out ;
  assign en_vec[1] = user_project.\u_puf.u_core.g_ro_bank[1].u_ro.en ;
  assign out_vec[1] = user_project.\u_puf.u_core.g_ro_bank[1].u_ro.out ;
  assign en_vec[2] = user_project.\u_puf.u_core.g_ro_bank[2].u_ro.en ;
  assign out_vec[2] = user_project.\u_puf.u_core.g_ro_bank[2].u_ro.out ;
  assign en_vec[3] = user_project.\u_puf.u_core.g_ro_bank[3].u_ro.en ;
  assign out_vec[3] = user_project.\u_puf.u_core.g_ro_bank[3].u_ro.out ;
  assign en_vec[4] = user_project.\u_puf.u_core.g_ro_bank[4].u_ro.en ;
  assign out_vec[4] = user_project.\u_puf.u_core.g_ro_bank[4].u_ro.out ;
  assign en_vec[5] = user_project.\u_puf.u_core.g_ro_bank[5].u_ro.en ;
  assign out_vec[5] = user_project.\u_puf.u_core.g_ro_bank[5].u_ro.out ;
  assign en_vec[6] = user_project.\u_puf.u_core.g_ro_bank[6].u_ro.en ;
  assign out_vec[6] = user_project.\u_puf.u_core.g_ro_bank[6].u_ro.out ;
  assign en_vec[7] = user_project.\u_puf.u_core.g_ro_bank[7].u_ro.en ;
  assign out_vec[7] = user_project.\u_puf.u_core.g_ro_bank[7].u_ro.out ;
  assign en_vec[8] = user_project.\u_puf.u_core.g_ro_bank[8].u_ro.en ;
  assign out_vec[8] = user_project.\u_puf.u_core.g_ro_bank[8].u_ro.out ;
  assign en_vec[9] = user_project.\u_puf.u_core.g_ro_bank[9].u_ro.en ;
  assign out_vec[9] = user_project.\u_puf.u_core.g_ro_bank[9].u_ro.out ;
  assign en_vec[10] = user_project.\u_puf.u_core.g_ro_bank[10].u_ro.en ;
  assign out_vec[10] = user_project.\u_puf.u_core.g_ro_bank[10].u_ro.out ;
  assign en_vec[11] = user_project.\u_puf.u_core.g_ro_bank[11].u_ro.en ;
  assign out_vec[11] = user_project.\u_puf.u_core.g_ro_bank[11].u_ro.out ;
  assign en_vec[12] = user_project.\u_puf.u_core.g_ro_bank[12].u_ro.en ;
  assign out_vec[12] = user_project.\u_puf.u_core.g_ro_bank[12].u_ro.out ;
  assign en_vec[13] = user_project.\u_puf.u_core.g_ro_bank[13].u_ro.en ;
  assign out_vec[13] = user_project.\u_puf.u_core.g_ro_bank[13].u_ro.out ;
  assign en_vec[14] = user_project.\u_puf.u_core.g_ro_bank[14].u_ro.en ;
  assign out_vec[14] = user_project.\u_puf.u_core.g_ro_bank[14].u_ro.out ;
  assign en_vec[15] = user_project.\u_puf.u_core.g_ro_bank[15].u_ro.en ;
  assign out_vec[15] = user_project.\u_puf.u_core.g_ro_bank[15].u_ro.out ;
  assign en_vec[16] = user_project.\armb_en[0] ;
  assign out_vec[16] = user_project.\armb_out[0] ;
  assign en_vec[17] = user_project.\armb_en[1] ;
  assign out_vec[17] = user_project.\armb_out[1] ;
  assign en_vec[18] = user_project.\armb_en[2] ;
  assign out_vec[18] = user_project.\armb_out[2] ;
  assign en_vec[19] = user_project.\armb_en[3] ;
  assign out_vec[19] = user_project.\armb_out[3] ;
  assign en_vec[20] = user_project.\armb_en[4] ;
  assign out_vec[20] = user_project.\armb_out[4] ;
  assign en_vec[21] = user_project.\armb_en[5] ;
  assign out_vec[21] = user_project.\armb_out[5] ;
  assign en_vec[22] = user_project.\armb_en[6] ;
  assign out_vec[22] = user_project.\armb_out[6] ;
  assign en_vec[23] = user_project.\armb_en[7] ;
  assign out_vec[23] = user_project.\armb_out[7] ;
  assign en_vec[24] = user_project.\armb_en[8] ;
  assign out_vec[24] = user_project.\armb_out[8] ;
  assign en_vec[25] = user_project.\armb_en[9] ;
  assign out_vec[25] = user_project.\armb_out[9] ;
  assign en_vec[26] = user_project.\armb_en[10] ;
  assign out_vec[26] = user_project.\armb_out[10] ;
  assign en_vec[27] = user_project.\armb_en[11] ;
  assign out_vec[27] = user_project.\armb_out[11] ;
  assign en_vec[28] = user_project.\armb_en[12] ;
  assign out_vec[28] = user_project.\armb_out[12] ;
  assign en_vec[29] = user_project.\armb_en[13] ;
  assign out_vec[29] = user_project.\armb_out[13] ;
  assign en_vec[30] = user_project.\armb_en[14] ;
  assign out_vec[30] = user_project.\armb_out[14] ;
  assign en_vec[31] = user_project.\armb_en[15] ;
  assign out_vec[31] = user_project.\armb_out[15] ;
  assign en_vec[32] = user_project.\u_puf.u_core.g_armc[0].u_roc.en ;
  assign out_vec[32] = user_project.\u_puf.u_core.g_armc[0].u_roc.out ;
  assign en_vec[33] = user_project.\u_puf.u_core.g_armc[1].u_roc.en ;
  assign out_vec[33] = user_project.\u_puf.u_core.g_armc[1].u_roc.out ;
  assign en_vec[34] = user_project.\u_puf.u_core.g_armc[2].u_roc.en ;
  assign out_vec[34] = user_project.\u_puf.u_core.g_armc[2].u_roc.out ;
  assign en_vec[35] = user_project.\u_puf.u_core.g_armc[3].u_roc.en ;
  assign out_vec[35] = user_project.\u_puf.u_core.g_armc[3].u_roc.out ;
  assign en_vec[36] = user_project.\u_puf.u_core.g_armc[4].u_roc.en ;
  assign out_vec[36] = user_project.\u_puf.u_core.g_armc[4].u_roc.out ;
  assign en_vec[37] = user_project.\u_puf.u_core.g_armc[5].u_roc.en ;
  assign out_vec[37] = user_project.\u_puf.u_core.g_armc[5].u_roc.out ;
  assign en_vec[38] = user_project.\u_puf.u_core.g_armc[6].u_roc.en ;
  assign out_vec[38] = user_project.\u_puf.u_core.g_armc[6].u_roc.out ;
  assign en_vec[39] = user_project.\u_puf.u_core.g_armc[7].u_roc.en ;
  assign out_vec[39] = user_project.\u_puf.u_core.g_armc[7].u_roc.out ;
  assign en_vec[40] = user_project.\u_puf.u_core.g_armc[8].u_roc.en ;
  assign out_vec[40] = user_project.\u_puf.u_core.g_armc[8].u_roc.out ;
  assign en_vec[41] = user_project.\u_puf.u_core.g_armc[9].u_roc.en ;
  assign out_vec[41] = user_project.\u_puf.u_core.g_armc[9].u_roc.out ;
  assign en_vec[42] = user_project.\u_puf.u_core.g_armc[10].u_roc.en ;
  assign out_vec[42] = user_project.\u_puf.u_core.g_armc[10].u_roc.out ;
  assign en_vec[43] = user_project.\u_puf.u_core.g_armc[11].u_roc.en ;
  assign out_vec[43] = user_project.\u_puf.u_core.g_armc[11].u_roc.out ;
  assign en_vec[44] = user_project.\u_puf.u_core.g_armc[12].u_roc.en ;
  assign out_vec[44] = user_project.\u_puf.u_core.g_armc[12].u_roc.out ;
  assign en_vec[45] = user_project.\u_puf.u_core.g_armc[13].u_roc.en ;
  assign out_vec[45] = user_project.\u_puf.u_core.g_armc[13].u_roc.out ;
  assign en_vec[46] = user_project.\u_puf.u_core.g_armc[14].u_roc.en ;
  assign out_vec[46] = user_project.\u_puf.u_core.g_armc[14].u_roc.out ;
  assign en_vec[47] = user_project.\u_puf.u_core.g_armc[15].u_roc.en ;
  assign out_vec[47] = user_project.\u_puf.u_core.g_armc[15].u_roc.out ;

  // Monitors. Each is a counter cocotb reads at the end of a test, plus
  // the time of the first offence. The checks sit behind a #0 so that
  // they see the values after every zero-delay gate of the timestep has
  // settled; raw_pop_events counts the settled-or-not delta-cycle view
  // of the same thing as a diagnostic.
  integer popcount_violations = 0;   // more than one enable high, settled
  integer raw_pop_events = 0;        // same, counted on every delta event
  integer en_x_events = 0;           // an enable that is not 0 or 1
  integer disabled_toggles = 0;      // a ring output moved, enable low
  integer oe_violations = 0;         // uio_oe left 0x31
  integer active_violations = 0;     // a ring enabled while uio[5] says idle
  integer en_rises = 0;              // enables seen rising, all rings
  integer max_pop = 0;
  reg [63:0] first_bad_time = 0;
  reg monitors_armed = 0;            // set by the test after reset

  function integer pop48(input [47:0] v);
    integer k;
    begin
      pop48 = 0;
      for (k = 0; k < 48; k = k + 1) pop48 = pop48 + (v[k] === 1'b1);
    end
  endfunction

  always @(en_vec) begin
    if (monitors_armed && pop48(en_vec) > 1)
      raw_pop_events = raw_pop_events + 1;
  end

  integer p;
  always @(en_vec) begin
    #0;
    if (monitors_armed) begin
      if (^en_vec === 1'bx) begin
        en_x_events = en_x_events + 1;
        if (first_bad_time == 0) first_bad_time = $time;
      end
      p = pop48(en_vec);
      if (p > max_pop) max_pop = p;
      if (p > 1) begin
        popcount_violations = popcount_violations + 1;
        if (first_bad_time == 0) first_bad_time = $time;
      end
    end
  end

  always @(en_vec or uio_out[5]) begin
    #0;
    if (monitors_armed && (|en_vec) === 1'b1 && uio_out[5] !== 1'b1) begin
      active_violations = active_violations + 1;
      if (first_bad_time == 0) first_bad_time = $time;
    end
  end

  always @(uio_oe) begin
    if (monitors_armed && uio_oe !== 8'h31) begin
      oe_violations = oe_violations + 1;
      if (first_bad_time == 0) first_bad_time = $time;
    end
  end

  // Per ring: when the enable falls the ring may still drain for a few
  // stage delays. 4 ns is more than 31 stages of the slowest ring's
  // per-stage delay (75 ps), then any further edge is a ring running
  // while disabled.
  genvar g;
  generate
    for (g = 0; g < 48; g = g + 1) begin : g_mon
      reg [63:0] t_off = 0;
      always @(negedge en_vec[g]) t_off = $time;
      always @(posedge en_vec[g]) if (monitors_armed) en_rises = en_rises + 1;
      always @(out_vec[g]) begin
        #0;
        if (monitors_armed && en_vec[g] !== 1'b1 && ($time - t_off) > 4) begin
          disabled_toggles = disabled_toggles + 1;
          if (first_bad_time == 0) first_bad_time = $time;
        end
      end
    end
  endgenerate
endmodule
