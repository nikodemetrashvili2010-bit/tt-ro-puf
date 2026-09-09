// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
// SPDX-License-Identifier: Apache-2.0
// Self-checking production ro_puf_core test.
//
// Three arms of sixteen, the shape that gets fabricated: Arm A is the
// core's own ro_macro bank, Arm B is sixteen ro_macro_hard models hung on
// the armb ports the way the top level hangs the real macros, Arm C is the
// core's ro_armc bank. The sim models give Arm A and Arm C a period that
// grows with index and Arm B one fixed period, so the counts have a shape
// the test can insist on without knowing a single expected number.
//
// Rewritten 9 September 2026. The previous version was written for an
// eight-oscillator, two-arm core and had not compiled since the Arm C
// install on 4 September; the root make check had been red for five
// pushes and nobody could see it.

`timescale 1ps/1ps
`default_nettype none

module tb_ro_puf_core;
    localparam integer N_A   = 16;
    localparam integer N_RO  = 3 * N_A;
    localparam integer SEL_W = 6;
    localparam integer CNT_W = 16;
    localparam integer WINDOW = 200;

    reg xclk = 0;
    reg rst_n = 0;
    reg start = 0;
    reg [SEL_W-1:0] ro_sel = 0;
    reg [CNT_W-1:0] window = WINDOW;
    wire [N_A-1:0] armb_en;
    wire [N_A-1:0] armb_out;
    wire done;
    wire active;
    wire overflow;
    wire [CNT_W-1:0] count_out;

    genvar m;
    generate
        for (m = 0; m < N_A; m = m + 1) begin : g_armb_model
            ro_macro_hard u_model (.en(armb_en[m]), .out(armb_out[m]));
        end
    endgenerate

    ro_puf_core #(.N_RO(N_RO), .SEL_W(SEL_W), .CNT_W(CNT_W)) dut (
        .xclk(xclk), .rst_n(rst_n), .start(start), .ro_sel(ro_sel),
        .window(window), .armb_en(armb_en), .armb_out(armb_out),
        .done(done), .active(active), .overflow(overflow),
        .count_out(count_out)
    );

    always #5000 xclk = ~xclk;

    integer idx_i, errors, guard, saw_low, high_cycles;
    integer prev_a, prev_c, first_b;
    reg [CNT_W-1:0] arm_a_count [0:N_A-1];

    // One measurement of slot i. Checks, every sampled cycle of the run:
    // the active output equals the internal window; Arm B's enables are
    // one-hot at i-N_A while the window is open and an Arm B slot is
    // selected, and all zero otherwise. Then: done rose, the window was
    // open for exactly WINDOW cycles, overflow stayed clear.
    task measure(input integer i);
        reg [N_A-1:0] expected_en;
        begin
            expected_en = (i >= N_A && i < 2 * N_A)
                        ? ({{(N_A-1){1'b0}}, 1'b1} << (i - N_A))
                        : {N_A{1'b0}};
            @(negedge xclk) begin ro_sel = i[SEL_W-1:0]; start = 1; end
            @(negedge xclk) start = 0;
            guard = 0;
            saw_low = 0;
            high_cycles = 0;
            while ((!saw_low || !done) && guard < WINDOW + 16) begin
                @(posedge xclk); #1;
                guard = guard + 1;
                if (!done) saw_low = 1;
                if (active !== dut.en_window) begin
                    errors = errors + 1;
                    $display("active pin disagrees with the window, slot %0d", i);
                end
                if (dut.en_window) begin
                    high_cycles = high_cycles + 1;
                    if (armb_en !== expected_en) begin
                        errors = errors + 1;
                        $display("bad Arm-B enable slot=%0d value=%h expected=%h",
                                 i, armb_en, expected_en);
                    end
                end else if (armb_en !== {N_A{1'b0}}) begin
                    errors = errors + 1;
                    $display("Arm-B enabled outside the window, slot %0d: %h",
                             i, armb_en);
                end
            end
            if (done !== 1'b1) begin
                errors = errors + 1;
                $display("done timeout slot=%0d", i);
            end
            if (high_cycles != WINDOW) begin
                errors = errors + 1;
                $display("window=%0d, expected %0d, slot %0d", high_cycles, WINDOW, i);
            end
            if (overflow !== 1'b0) begin
                errors = errors + 1;
                $display("overflow set on a %0d-cycle window, slot %0d", WINDOW, i);
            end
        end
    endtask

    initial begin
        $dumpfile("tb_ro_puf_core.vcd");
        $dumpvars(0, tb_ro_puf_core);
        errors = 0;
        repeat (4) @(posedge xclk);
        rst_n = 1;
        repeat (2) @(posedge xclk);
        if (done !== 1'b0 || active !== 1'b0 || overflow !== 1'b0) begin
            errors = errors + 1;
            $display("outputs not quiet after reset");
        end

        // Arm A, slots 0..15: every count real, strictly falling with index.
        prev_a = 65536;
        for (idx_i = 0; idx_i < N_A; idx_i = idx_i + 1) begin
            measure(idx_i);
            $display("A %2d count=%0d", idx_i, count_out);
            if (^count_out === 1'bx || count_out == 0) errors = errors + 1;
            if (count_out >= prev_a) errors = errors + 1;
            prev_a = count_out;
            arm_a_count[idx_i] = count_out;
        end

        // Arm B, slots 16..31: sixteen copies of one model, one count.
        for (idx_i = N_A; idx_i < 2 * N_A; idx_i = idx_i + 1) begin
            measure(idx_i);
            $display("B %2d count=%0d", idx_i - N_A, count_out);
            if (^count_out === 1'bx || count_out == 0) errors = errors + 1;
            if (idx_i == N_A) first_b = count_out;
            else if (count_out != first_b) errors = errors + 1;
        end

        // Arm C, slots 32..47: falling with index, and faster than Arm A
        // at the same index, which is how the two sim models differ.
        prev_c = 65536;
        for (idx_i = 2 * N_A; idx_i < N_RO; idx_i = idx_i + 1) begin
            measure(idx_i);
            $display("C %2d count=%0d", idx_i - 2 * N_A, count_out);
            if (^count_out === 1'bx || count_out == 0) errors = errors + 1;
            if (count_out >= prev_c) errors = errors + 1;
            prev_c = count_out;
            if (count_out <= arm_a_count[idx_i - 2 * N_A]) errors = errors + 1;
        end

        // A slot no oscillator fills. Two select bits name four arms and
        // there are three; the core ties those slots low rather than
        // leaving them off the vector. done must still rise, with zero.
        measure(N_RO);
        $display("dead slot %0d count=%0d", N_RO, count_out);
        if (count_out !== {CNT_W{1'b0}}) begin
            errors = errors + 1;
            $display("dead slot counted");
        end

        if (errors != 0) $fatal(1, "RESULT: FAIL (%0d errors)", errors);
        $display("RESULT: PASS");
        $finish;
    end

    initial begin
        #400000000;
        $fatal(1, "RESULT: TIMEOUT");
    end
endmodule

`default_nettype wire
