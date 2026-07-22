// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
// SPDX-License-Identifier: Apache-2.0
// Self-checking production ro_puf test.

`timescale 1ps/1ps
`default_nettype none

module tb_ro_puf;
    localparam integer N_PER_ARM = 16;
    localparam integer CNT_W = 16;
    localparam integer WINDOW = 200;

    reg xclk = 0;
    reg rst_n = 0;
    reg start = 0;
    reg arm = 0;
    reg [3:0] ro_idx = 0;
    reg [CNT_W-1:0] window = WINDOW;
    wire [N_PER_ARM-1:0] armb_en;
    wire [N_PER_ARM-1:0] armb_out;
    wire done;
    wire [CNT_W-1:0] count_out;

    genvar m;
    generate
        for (m = 0; m < N_PER_ARM; m = m + 1) begin : g_armb_model
            ro_macro_hard u_model (.en(armb_en[m]), .out(armb_out[m]));
        end
    endgenerate

    ro_puf #(.N_PER_ARM(N_PER_ARM), .CNT_W(CNT_W)) dut (
        .xclk(xclk), .rst_n(rst_n), .start(start), .arm(arm),
        .ro_idx(ro_idx), .window(window), .armb_en(armb_en),
        .armb_out(armb_out), .done(done), .count_out(count_out)
    );

    always #5000 xclk = ~xclk;

    integer arm_i, idx_i, errors, guard, saw_low, high_cycles;
    integer prev_a, first_b;

    task measure(input integer a, input integer i);
        reg [15:0] expected_en;
        begin
            expected_en = 16'b1 << i;
            @(negedge xclk) begin arm = a[0]; ro_idx = i[3:0]; start = 1; end
            @(negedge xclk) start = 0;
            guard = 0;
            saw_low = 0;
            high_cycles = 0;
            while ((!saw_low || !done) && guard < WINDOW + 16) begin
                @(posedge xclk); #1;
                guard = guard + 1;
                if (!done) saw_low = 1;
                if (dut.u_core.en_window) begin
                    high_cycles = high_cycles + 1;
                    if (a && armb_en !== expected_en) errors = errors + 1;
                    if (!a && armb_en !== 16'b0) errors = errors + 1;
                end
            end
            if (done !== 1'b1 || high_cycles != WINDOW) errors = errors + 1;
        end
    endtask

    initial begin
        $dumpfile("tb_ro_puf.vcd");
        $dumpvars(0, tb_ro_puf);
        errors = 0;
        repeat (4) @(posedge xclk);
        rst_n = 1;
        repeat (2) @(posedge xclk);
        prev_a = 65536;

        for (arm_i = 0; arm_i < 2; arm_i = arm_i + 1) begin
            for (idx_i = 0; idx_i < N_PER_ARM; idx_i = idx_i + 1) begin
                measure(arm_i, idx_i);
                $display("arm=%0d idx=%0d count=%0d", arm_i, idx_i, count_out);
                if (^count_out === 1'bx || count_out == 0) errors = errors + 1;
                if (arm_i == 0) begin
                    if (count_out >= prev_a) errors = errors + 1;
                    prev_a = count_out;
                end else if (idx_i == 0) begin
                    first_b = count_out;
                end else if (count_out != first_b) begin
                    errors = errors + 1;
                end
            end
        end

        if (errors != 0) $fatal(1, "RESULT: FAIL (%0d errors)", errors);
        $display("RESULT: PASS");
        $finish;
    end

    initial begin
        #250000000;
        $fatal(1, "RESULT: TIMEOUT");
    end
endmodule

`default_nettype wire
