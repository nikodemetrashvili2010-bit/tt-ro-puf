// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
// SPDX-License-Identifier: Apache-2.0
// Self-checking production ro_puf_core test.

`timescale 1ps/1ps
`default_nettype none

module tb_ro_puf_core;
    localparam integer N_RO = 8;
    localparam integer SEL_W = 3;
    localparam integer CNT_W = 16;
    localparam integer WINDOW = 200;

    reg xclk = 0;
    reg rst_n = 0;
    reg start = 0;
    reg [SEL_W-1:0] ro_sel = 0;
    reg [CNT_W-1:0] window = WINDOW;
    wire [N_RO/2-1:0] armb_en;
    wire [N_RO/2-1:0] armb_out;
    wire done;
    wire [CNT_W-1:0] count_out;

    genvar m;
    generate
        for (m = 0; m < N_RO/2; m = m + 1) begin : g_armb_model
            ro_macro_hard u_model (.en(armb_en[m]), .out(armb_out[m]));
        end
    endgenerate

    ro_puf_core #(.N_RO(N_RO), .SEL_W(SEL_W), .CNT_W(CNT_W)) dut (
        .xclk(xclk), .rst_n(rst_n), .start(start), .ro_sel(ro_sel),
        .window(window), .armb_en(armb_en), .armb_out(armb_out),
        .done(done), .count_out(count_out)
    );

    always #5000 xclk = ~xclk;

    integer idx_i, errors, guard, saw_low, high_cycles;
    integer prev_a, first_b;

    task measure(input integer i);
        reg [3:0] expected_en;
        begin
            expected_en = (i >= 4) ? (4'b1 << (i - 4)) : 4'b0;
            @(negedge xclk) begin ro_sel = i[SEL_W-1:0]; start = 1; end
            @(negedge xclk) start = 0;
            guard = 0;
            saw_low = 0;
            high_cycles = 0;
            while ((!saw_low || !done) && guard < WINDOW + 16) begin
                @(posedge xclk); #1;
                guard = guard + 1;
                if (!done) saw_low = 1;
                if (dut.en_window) begin
                    high_cycles = high_cycles + 1;
                    if (i >= 4 && armb_en !== expected_en) errors = errors + 1;
                    if (i < 4 && armb_en !== 4'b0) errors = errors + 1;
                end
            end
            if (done !== 1'b1 || high_cycles != WINDOW) errors = errors + 1;
        end
    endtask

    initial begin
        $dumpfile("tb_ro_puf_core.vcd");
        $dumpvars(0, tb_ro_puf_core);
        errors = 0;
        repeat (4) @(posedge xclk);
        rst_n = 1;
        repeat (2) @(posedge xclk);
        prev_a = 65536;

        for (idx_i = 0; idx_i < N_RO; idx_i = idx_i + 1) begin
            measure(idx_i);
            $display("RO %0d count=%0d", idx_i, count_out);
            if (^count_out === 1'bx || count_out == 0) errors = errors + 1;
            if (idx_i < 4) begin
                if (count_out >= prev_a) errors = errors + 1;
                prev_a = count_out;
            end else if (idx_i == 4) begin
                first_b = count_out;
            end else if (count_out != first_b) begin
                errors = errors + 1;
            end
        end

        if (errors != 0) $fatal(1, "RESULT: FAIL (%0d errors)", errors);
        $display("RESULT: PASS");
        $finish;
    end

    initial begin
        #75000000;
        $fatal(1, "RESULT: TIMEOUT");
    end
endmodule

`default_nettype wire
