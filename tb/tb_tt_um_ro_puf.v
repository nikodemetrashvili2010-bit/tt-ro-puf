// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
// SPDX-License-Identifier: Apache-2.0
//
// Testbench for the TinyTapeout wrapper. Drives the pin interface the way the
// on-board microcontroller would: set arm and index, pulse start, wait for
// done, then read the count back as two bytes and reassemble it.

`timescale 1ps/1ps
`default_nettype none

module tb_tt_um_ro_puf;

    reg  [7:0] ui_in  = 8'b0;
    wire [7:0] uo_out;
    reg  [7:0] uio_in = 8'b0;
    wire [7:0] uio_out;
    wire [7:0] uio_oe;
    reg        ena    = 1'b1;
    reg        clk    = 1'b0;
    reg        rst_n  = 1'b0;

    tt_um_nikodemetrashvili20_ro_puf dut (
        .ui_in(ui_in), .uo_out(uo_out), .uio_in(uio_in),
        .uio_out(uio_out), .uio_oe(uio_oe), .ena(ena),
        .clk(clk), .rst_n(rst_n)
    );

    always #5000 clk = ~clk;        // 100 MHz

    reg [15:0] count;
    integer a, j, errors;

    task measure(input arm_sel, input [3:0] idx);
        begin
            @(negedge clk) begin ui_in[1] = arm_sel; ui_in[5:2] = idx; end
            // hold start high two cycles to exercise the edge detector
            @(negedge clk) ui_in[0] = 1'b1;
            @(negedge clk) ui_in[0] = 1'b1;
            @(negedge clk) ui_in[0] = 1'b0;
            @(posedge uio_out[0]);                 // wait for done
            @(negedge clk) ui_in[6] = 1'b0;
            @(negedge clk) count[7:0]  = uo_out;   // low byte
            @(negedge clk) ui_in[6] = 1'b1;
            @(negedge clk) count[15:8] = uo_out;   // high byte
            ui_in[6] = 1'b0;
        end
    endtask

    initial begin
        $dumpfile("tb_tt_um_ro_puf.vcd");
        $dumpvars(0, tb_tt_um_ro_puf);

        errors = 0;
        #20000 rst_n = 1'b1;
        #20000;

        for (a = 0; a < 2; a = a + 1) begin
            if (a == 0) $display("Arm A:");
            else        $display("Arm B:");
            for (j = 0; j < 4; j = j + 1) begin
                measure(a[0], j[3:0]);
                $display("  RO %0d : count = %0d", j, count);
                if (count == 0) begin errors = errors + 1; $display("    zero count"); end
            end
        end

        if (errors == 0) $display("RESULT: PASS");
        else             $display("RESULT: FAIL (%0d)", errors);
        $finish;
    end

    initial begin
        #200000000;
        $display("RESULT: TIMEOUT");
        $finish;
    end
endmodule

`default_nettype wire
