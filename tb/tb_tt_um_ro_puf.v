// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
// SPDX-License-Identifier: Apache-2.0
// Self-checking production TinyTapeout-wrapper test.

`timescale 1ps/1ps
`default_nettype none

module tb_tt_um_ro_puf;
    localparam integer WINDOW = 1000;

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

    always #10000 clk = ~clk; // 50 MHz, matching info.yaml

    reg [15:0] count;
    integer arm_i, idx_i, errors, guard, saw_low, high_cycles;
    integer prev_a, first_b;

    task measure(input integer arm_sel, input integer idx_sel);
        reg [7:0] base;
        reg [15:0] expected_en;
        begin
            base = ((arm_sel & 1) << 1) | ((idx_sel & 15) << 2);
            expected_en = 16'b1 << idx_sel;
            @(negedge clk) ui_in = base;
            repeat (3) @(posedge clk); // control-bundle synchronizer setup
            @(negedge clk) ui_in = base | 8'h01;
            repeat (3) @(posedge clk); // documented minimum start-high time
            @(negedge clk) ui_in = base;

            guard = 0;
            saw_low = 0;
            high_cycles = 0;
            while ((!saw_low || !uio_out[0]) && guard < WINDOW + 64) begin
                @(posedge clk); #1;
                guard = guard + 1;
                if (!uio_out[0]) saw_low = 1;
                if (dut.u_puf.u_core.en_window) begin
                    high_cycles = high_cycles + 1;
                    if (arm_sel && dut.armb_en !== expected_en) begin
                        errors = errors + 1;
                        $display("bad Arm-B enable arm=%0d idx=%0d value=%h",
                                 arm_sel, idx_sel, dut.armb_en);
                    end
                    if (!arm_sel && dut.armb_en !== 16'b0) begin
                        errors = errors + 1;
                        $display("Arm-B enabled during Arm A: %h", dut.armb_en);
                    end
                end
            end
            if (!saw_low || uio_out[0] !== 1'b1) begin
                errors = errors + 1;
                $display("done timeout arm=%0d idx=%0d", arm_sel, idx_sel);
            end
            if (high_cycles != WINDOW) begin
                errors = errors + 1;
                $display("window=%0d, expected %0d", high_cycles, WINDOW);
            end

            @(negedge clk) ui_in = base;
            repeat (3) @(posedge clk);
            @(negedge clk) count[7:0] = uo_out;
            @(negedge clk) ui_in = base | 8'h40;
            repeat (3) @(posedge clk);
            @(negedge clk) count[15:8] = uo_out;
            ui_in = base;
        end
    endtask

    initial begin
        $dumpfile("tb_tt_um_ro_puf.vcd");
        $dumpvars(0, tb_tt_um_ro_puf);
        errors = 0;
        repeat (4) @(posedge clk);
        @(negedge clk) rst_n = 1'b1;
        @(posedge clk); #1;
        if (dut.project_rst_n !== 1'b0) begin
            errors = errors + 1;
            $display("project reset released before synchronization");
        end
        @(posedge clk); #1;
        if (dut.project_rst_n !== 1'b1) begin
            errors = errors + 1;
            $display("project reset did not release after two clocks");
        end
        repeat (2) @(posedge clk);

        if (uio_oe !== 8'h01 || uio_out !== 8'h00) begin
            errors = errors + 1;
            $display("bad UIO constants oe=%h out=%h", uio_oe, uio_out);
        end

        prev_a = 65536;
        for (arm_i = 0; arm_i < 2; arm_i = arm_i + 1) begin
            for (idx_i = 0; idx_i < 16; idx_i = idx_i + 1) begin
                measure(arm_i, idx_i);
                $display("arm=%0d idx=%0d count=%0d", arm_i, idx_i, count);
                if (^count === 1'bx || count == 0) errors = errors + 1;
                if (arm_i == 0) begin
                    if (count >= prev_a) errors = errors + 1;
                    prev_a = count;
                end else if (idx_i == 0) begin
                    first_b = count;
                end else if (count != first_b) begin
                    errors = errors + 1;
                end
            end
        end

        if (errors != 0) $fatal(1, "RESULT: FAIL (%0d errors)", errors);
        $display("RESULT: PASS");
        $finish;
    end

    initial begin
        #1000000000;
        $fatal(1, "RESULT: TIMEOUT");
    end
endmodule

`default_nettype wire
