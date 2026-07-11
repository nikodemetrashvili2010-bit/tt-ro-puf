// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
// SPDX-License-Identifier: Apache-2.0
//
// Testbench for ro_puf_core. Measures every oscillator once and checks the
// counts are non-zero, distinct, and falling with index.

`timescale 1ps/1ps
`default_nettype none

module tb_ro_puf_core;

    localparam integer N_RO  = 8;
    localparam integer SEL_W = 3;
    localparam integer CNT_W = 16;

    reg              xclk  = 1'b0;
    reg              rst_n = 1'b0;
    reg              start = 1'b0;
    reg  [SEL_W-1:0] ro_sel = {SEL_W{1'b0}};
    reg  [CNT_W-1:0] window = 16'd200;
    wire             done;
    wire [CNT_W-1:0] count_out;

    ro_puf_core #(.N_RO(N_RO), .SEL_W(SEL_W), .CNT_W(CNT_W)) dut (
        .xclk(xclk), .rst_n(rst_n), .start(start), .ro_sel(ro_sel),
        .window(window), .done(done), .count_out(count_out)
    );

    always #5000 xclk = ~xclk;        // 100 MHz

    integer k, prev, errors;

    initial begin
        $dumpfile("tb_ro_puf_core.vcd");
        $dumpvars(0, tb_ro_puf_core);

        errors = 0;
        #20000 rst_n = 1'b1;
        #20000;
        prev = (1 << CNT_W);

        for (k = 0; k < N_RO; k = k + 1) begin
            @(negedge xclk) ro_sel = k[SEL_W-1:0];
            @(negedge xclk) start = 1'b1;
            @(negedge xclk) start = 1'b0;
            @(posedge done);
            @(negedge xclk);

            $display("RO %0d : count = %0d", k, count_out);
            if (count_out == 0)    begin errors = errors + 1; $display("  zero count"); end
            if (count_out >= prev) begin errors = errors + 1; $display("  not below previous"); end
            prev = count_out;
        end

        if (errors == 0) $display("RESULT: PASS");
        else             $display("RESULT: FAIL (%0d)", errors);
        $finish;
    end

    initial begin
        #60000000;
        $display("RESULT: TIMEOUT");
        $finish;
    end
endmodule

`default_nettype wire
