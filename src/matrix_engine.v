/*
 * Copyright (c) 2026 Syver Haraldsen
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module matrix_engine #(
    parameter N = 2,
    parameter DATA_BITS = 8,
    parameter ACC_BITS = 32,
    parameter INDEX_BITS = (N*N > 1) ? $clog2(N*N) : 1
) (
    input wire clk,
    input wire rst_n,

    // Write one element per clock while idle. Index is row*N + column.
    input wire write_en,
    input wire write_matrix_b, // 0 selects A, 1 selects B.
    input wire [INDEX_BITS-1:0] write_index,
    input wire signed [DATA_BITS-1:0] write_data,

    // Pulse start for one clock after loading both matrices completely.
    input wire start,
    input wire accumulate, // 0: C = A*B, 1: C = C + A*B.
    output wire busy,
    output reg done,

    // Read a complete result element. Data is valid only when done is high.
    input wire [INDEX_BITS-1:0] read_index,
    output wire signed [ACC_BITS-1:0] read_data
);

    localparam ELEMENTS = N*N;
    localparam COUNTER_BITS = (N > 1) ? $clog2(N) : 1;
    // Compare counters with a constant of the same width, for any matrix size.
    localparam [COUNTER_BITS-1:0] LAST_INDEX = COUNTER_BITS'(N-1);
    localparam [2:0] IDLE = 3'd0, CLEAR = 3'd1,
                     COMPUTE = 3'd2, DRAIN = 3'd3, STORE = 3'd4;

    reg [2:0] state;
    reg accumulate_job;
    reg [COUNTER_BITS-1:0] row, column, k;
    reg signed [DATA_BITS-1:0] matrix_a [0:ELEMENTS-1];
    reg signed [DATA_BITS-1:0] matrix_b [0:ELEMENTS-1];
    reg signed [ACC_BITS-1:0] matrix_c [0:ELEMENTS-1];

    assign busy = (state != IDLE);
    assign read_data = (done && read_index < ELEMENTS)
                     ? matrix_c[read_index] : {ACC_BITS{1'b0}};

    wire signed [DATA_BITS-1:0] operand_a;
    wire signed [DATA_BITS-1:0] operand_b;
    wire signed [ACC_BITS-1:0] mac_acc;

    // C[row,column] = sum over k of A[row,k] * B[k,column].
    assign operand_a = matrix_a[row*N + k];
    assign operand_b = matrix_b[k*N + column];

    mac #(.DATA_BITS(DATA_BITS), .ACC_BITS(ACC_BITS)) calculator (
        .clk(clk),
        .rst_n(rst_n),
        .clear((state == CLEAR) && !accumulate_job),
        .load((state == CLEAR) && accumulate_job),
        .load_value(matrix_c[row*N + column]),
        .enable(state == COMPUTE),
        .a(operand_a),
        .b(operand_b),
        .acc(mac_acc)
    );

    // Avoid resetting every data bit. The caller must fully load A and B
    // after reset; C is hidden until all its elements have been computed.
    // The SPI controller owns incomplete-load validation.
    always @(posedge clk) begin
        if (rst_n && !busy && write_en && write_index < ELEMENTS) begin
            if (write_matrix_b)
                matrix_b[write_index] <= write_data;
            else
                matrix_a[write_index] <= write_data;
        end
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            state <= IDLE;
            accumulate_job <= 1'b0;
            done <= 1'b0;
            row <= 0;
            column <= 0;
            k <= 0;
        end else begin
            case (state)
                IDLE: begin
                    // If write and start coincide, perform only the write.
                    if (start && !write_en && (!accumulate || done)) begin
                        accumulate_job <= accumulate;
                        done <= 1'b0;
                        row <= 0;
                        column <= 0;
                        k <= 0;
                        state <= CLEAR;
                    end
                end

                CLEAR: begin
                    // Clear the MAC, or load the old C element for accumulation.
                    k <= 0;
                    state <= COMPUTE;
                end

                COMPUTE: begin
                    // Issue one product per edge. The last one is still
                    // pending in the MAC when we leave this state.
                    if (k == LAST_INDEX)
                        state <= DRAIN;
                    else
                        k <= k + 1'b1;
                end

                DRAIN: begin
                    // Stop issuing operands while the MAC adds its last product.
                    state <= STORE;
                end

                STORE: begin
                    // One edge after the final MAC update, acc contains the
                    // complete dot product (nonblocking assignment timing).
                    matrix_c[row*N + column] <= mac_acc;
                    if (column == LAST_INDEX) begin
                        column <= 0;
                        if (row == LAST_INDEX) begin
                            done <= 1'b1;
                            state <= IDLE;
                        end else begin
                            row <= row + 1'b1;
                            state <= CLEAR;
                        end
                    end else begin
                        column <= column + 1'b1;
                        state <= CLEAR;
                    end
                end

                default: begin
                    state <= IDLE;
                    done <= 1'b0;
                end
            endcase
        end
    end

endmodule
