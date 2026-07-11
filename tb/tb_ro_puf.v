// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
// SPDX-License-Identifier: Apache-2.0
//
// Testbench for the two-arm ro_puf. Measures all 16 oscillators in each arm
// and checks the counts are non-zero and distinct.

`timescale 1ps/1ps
`default_nettype none

module tb_ro_puf;

    localparam integer N_PER_ARM = 16;
    localparam integer CNT_W     = 16;

    reg              xclk   = 1'b0;
    reg              rst_n  = 1'b0;
    reg              start  = 1'b0;
    reg              arm    = 1'b0;
    reg  [3:0]       ro_idx = 4'd0;
    reg  [CNT_W-1:0] window = 16'd200;
    wire             done;
    wire [CNT_W-1:0] count_out;

    ro_puf #(.N_PER_ARM(N_PER_ARM), .CNT_W(CNT_W)) dut (
        .xclk(xclk), .rst_n(rst_n), .start(start), .arm(arm),
        .ro_idx(ro_idx), .window(window), .done(done), .count_out(count_out)
    );

    always #5000 xclk = ~xclk;        // 100 MHz

    integer a, j, prev, errors;

    task run_measurement;
        begin
            @(negedge xclk) start = 1'b1;
            @(negedge xclk) start = 1'b0;
            @(posedge done);
            @(negedge xclk);
        end
    endtask

    initial begin
        $dumpfile("tb_ro_puf.vcd");
        $dumpvars(0, tb_ro_puf);

        errors = 0;
        #20000 rst_n = 1'b1;
        #20000;
        prev = (1 << CNT_W);

        for (a = 0; a < 2; a = a + 1) begin
            arm = a[0];
            if (a == 0) $display("Arm A:");
            else        $display("Arm B:");

            for (j = 0; j < N_PER_ARM; j = j + 1) begin
                @(negedge xclk) ro_idx = j[3:0];
                run_measurement;
                $display("  RO %0d : count = %0d", j, count_out);
                if (count_out == 0)    begin errors = errors + 1; $display("    zero count"); end
                if (count_out >= prev) begin errors = errors + 1; $display("    not below previous"); end
                prev = count_out;
            end
        end

        if (errors == 0) $display("RESULT: PASS");
        else             $display("RESULT: FAIL (%0d)", errors);
        $finish;
    end

    initial begin
        #300000000;
        $display("RESULT: TIMEOUT");
        $finish;
    end
endmodule

`default_nettype wire
