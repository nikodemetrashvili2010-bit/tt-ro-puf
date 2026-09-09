// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
// SPDX-License-Identifier: Apache-2.0
// Self-checking production TinyTapeout-wrapper test.
//
// Drives the chip the way the host will, through the pins E.2 defined:
// start on ui[0], arm on ui[1] and ui[7], index on ui[5:2], byte select on
// ui[6]; window select on uio[2:1], version select on uio[3]; done on
// uio[0], sticky overflow on uio[4], measurement active on uio[5].
//
// Rewritten 9 September 2026. The previous version expected a fixed
// thousand-cycle window and two arms, which is the chip before E.2, and it
// had been failing since the window became selectable.

`timescale 1ps/1ps
`default_nettype none

module tb_tt_um_ro_puf;
    localparam integer N_A = 16;
    localparam [15:0] WIN0 = 16'd256;
    localparam [15:0] WIN1 = 16'd512;
    localparam [7:0] PROTOCOL_VERSION = 8'd2;
    localparam [7:0] BUILD_ID         = 8'h1A;

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
    integer prev_a, prev_c, first_b;
    reg [15:0] arm_a_count [0:N_A-1];

    // The control word: start bit 0, arm bit 0 on bit 1, index on 5:2,
    // readout byte on 6, arm bit 1 on 7.
    function [7:0] ui_word(input integer arm_sel, input integer idx_sel,
                           input integer high_byte, input integer strt);
        ui_word = (strt & 1)
                | ((arm_sel & 1) << 1)
                | ((idx_sel & 15) << 2)
                | ((high_byte & 1) << 6)
                | (((arm_sel >> 1) & 1) << 7);
    endfunction

    // One measurement. The window select is already on uio_in[2:1] when
    // this is called, and win_len says how long that window is.
    task measure(input integer arm_sel, input integer idx_sel,
                 input integer win_len);
        reg [7:0] base;
        reg [15:0] expected_en;
        begin
            base = ui_word(arm_sel, idx_sel, 0, 0);
            expected_en = (arm_sel == 1) ? (16'b1 << idx_sel) : 16'b0;
            @(negedge clk) ui_in = base;
            repeat (3) @(posedge clk); // control-bundle synchronizer setup
            @(negedge clk) ui_in = ui_word(arm_sel, idx_sel, 0, 1);
            repeat (3) @(posedge clk); // documented minimum start-high time
            @(negedge clk) ui_in = base;

            guard = 0;
            saw_low = 0;
            high_cycles = 0;
            while ((!saw_low || !uio_out[0]) && guard < win_len + 64) begin
                @(posedge clk); #1;
                guard = guard + 1;
                if (!uio_out[0]) saw_low = 1;
                // E.2 put the window on a pin. It has to agree with the
                // internal signal on every cycle or it is decoration.
                if (uio_out[5] !== dut.u_puf.u_core.en_window) begin
                    errors = errors + 1;
                    $display("uio[5] disagrees with the window arm=%0d idx=%0d",
                             arm_sel, idx_sel);
                end
                if (dut.u_puf.u_core.en_window) begin
                    high_cycles = high_cycles + 1;
                    if (dut.armb_en !== expected_en) begin
                        errors = errors + 1;
                        $display("bad Arm-B enable arm=%0d idx=%0d value=%h expected=%h",
                                 arm_sel, idx_sel, dut.armb_en, expected_en);
                    end
                end else if (dut.armb_en !== 16'b0) begin
                    errors = errors + 1;
                    $display("Arm-B enabled outside the window: %h", dut.armb_en);
                end
            end
            if (!saw_low || uio_out[0] !== 1'b1) begin
                errors = errors + 1;
                $display("done timeout arm=%0d idx=%0d", arm_sel, idx_sel);
            end
            if (high_cycles != win_len) begin
                errors = errors + 1;
                $display("window=%0d, expected %0d", high_cycles, win_len);
            end
            if (uio_out[4] !== 1'b0) begin
                errors = errors + 1;
                $display("overflow set on a %0d-cycle window", win_len);
            end

            // Read the count, low byte then high byte, through uo_out.
            @(negedge clk) ui_in = base;
            repeat (3) @(posedge clk);
            @(negedge clk) count[7:0] = uo_out;
            @(negedge clk) ui_in = ui_word(arm_sel, idx_sel, 1, 0);
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

        // uio_oe follows from the pin map: outputs on 0, 4 and 5.
        if (uio_oe !== 8'h31) begin
            errors = errors + 1;
            $display("bad uio_oe=%h, expected 31", uio_oe);
        end
        if (uio_out[0] !== 1'b0 || uio_out[4] !== 1'b0 || uio_out[5] !== 1'b0) begin
            errors = errors + 1;
            $display("outputs not quiet after reset: uio_out=%h", uio_out);
        end

        // The version bytes read out through the count port when uio[3]
        // is high: protocol with the low byte selected, build id with
        // the high byte. Three clocks for the bundle to synchronize.
        @(negedge clk) begin uio_in = 8'b0000_1000; ui_in = ui_word(0, 0, 0, 0); end
        repeat (3) @(posedge clk);
        @(negedge clk);
        if (uo_out !== PROTOCOL_VERSION) begin
            errors = errors + 1;
            $display("protocol byte %h, expected %h", uo_out, PROTOCOL_VERSION);
        end
        @(negedge clk) ui_in = ui_word(0, 0, 1, 0);
        repeat (3) @(posedge clk);
        @(negedge clk);
        if (uo_out !== BUILD_ID) begin
            errors = errors + 1;
            $display("build byte %h, expected %h", uo_out, BUILD_ID);
        end
        @(negedge clk) begin uio_in = 8'b0; ui_in = 8'b0; end
        repeat (3) @(posedge clk);

        // Window select 0, the 256-cycle window, over all 48 slots.
        prev_a = 65536;
        prev_c = 65536;
        for (arm_i = 0; arm_i < 3; arm_i = arm_i + 1) begin
            for (idx_i = 0; idx_i < N_A; idx_i = idx_i + 1) begin
                measure(arm_i, idx_i, WIN0);
                $display("arm=%0d idx=%0d count=%0d", arm_i, idx_i, count);
                if (^count === 1'bx || count == 0) errors = errors + 1;
                if (arm_i == 0) begin
                    if (count >= prev_a) errors = errors + 1;
                    prev_a = count;
                    arm_a_count[idx_i] = count;
                end else if (arm_i == 1) begin
                    if (idx_i == 0) first_b = count;
                    else if (count != first_b) errors = errors + 1;
                end else begin
                    if (count >= prev_c) errors = errors + 1;
                    prev_c = count;
                    if (count <= arm_a_count[idx_i]) errors = errors + 1;
                end
            end
        end

        // Window select 1 doubles the window, so the same oscillator
        // counts about twice as much. Within one count of double, given
        // the one-count boundary the settle handshake absorbs.
        @(negedge clk) uio_in = 8'b0000_0010;
        repeat (3) @(posedge clk);
        measure(0, 0, WIN1);
        $display("arm=0 idx=0 window 512 count=%0d against 256-window %0d",
                 count, arm_a_count[0]);
        if (count < 2 * arm_a_count[0] - 2 || count > 2 * arm_a_count[0] + 2) begin
            errors = errors + 1;
            $display("512-cycle window did not double the count");
        end
        @(negedge clk) uio_in = 8'b0;

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
