/*
 * Copyright (c) 2026 Syver Haraldsen
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// One command per CS-low frame. All ports operate in the clk domain.
// Input bytes are signed int8; each result occupies four little-endian bytes.
module command_controller #(
    parameter N = 2,
    parameter INDEX_BITS = (N*N > 1) ? $clog2(N*N) : 1
) (
    input wire clk,
    input wire rst_n,
    input wire selected,
    input wire rx_valid,
    input wire [7:0] rx_byte,
    output reg [7:0] tx_byte,

    output reg write_en,
    output reg write_matrix_b,
    output reg [INDEX_BITS-1:0] write_index,
    output reg signed [7:0] write_data,
    output reg start,
    output reg accumulate,
    input wire busy,
    input wire done,
    output reg [INDEX_BITS-1:0] read_index,
    input wire signed [31:0] read_data
);
    localparam [7:0] READ_ID = 8'h01, READ_STATUS = 8'h02,
                     LOAD_A = 8'h10, LOAD_B = 8'h11,
                     MULTIPLY = 8'h20, ACCUMULATE = 8'h21,
                     READ_RESULT = 8'h30;
    localparam [2:0] COMMAND = 3'd0, REPLY = 3'd1,
                     WRITE_A = 3'd2, WRITE_B = 3'd3,
                     READ_C = 3'd4, IGNORE = 3'd5;

    reg [2:0] state;
    reg a_valid, b_valid;
    reg [INDEX_BITS-1:0] load_index;
    reg [1:0] result_byte;
    reg [7:0] reply_byte;

    // The SPI transmitter latches this byte at the next byte boundary.
    // Status is a snapshot taken when its command is received.
    always @(*) begin
        case (state)
            REPLY: tx_byte = reply_byte;
            READ_C: tx_byte = read_data[8*result_byte +: 8];
            default: tx_byte = 8'h00;
        endcase
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            state <= COMMAND;
            a_valid <= 1'b0;
            b_valid <= 1'b0;
            load_index <= 0;
            read_index <= 0;
            result_byte <= 0;
            reply_byte <= 0;
            write_en <= 1'b0;
            write_matrix_b <= 1'b0;
            write_index <= 0;
            write_data <= 0;
            start <= 1'b0;
            accumulate <= 1'b0;
        end else begin
            // Requests to the engine last exactly one system-clock cycle.
            write_en <= 1'b0;
            start <= 1'b0;

            if (!selected) begin
                // Abort the frame, preserving matrix validity and results.
                state <= COMMAND;
                load_index <= 0;
                read_index <= 0;
                result_byte <= 0;
            end else if (rx_valid) begin
                case (state)
                    COMMAND: begin
                        // Unknown or rejected commands consume the whole frame.
                        state <= IGNORE;
                        case (rx_byte)
                            READ_ID: begin
                                reply_byte <= 8'h77;
                                state <= REPLY;
                            end
                            READ_STATUS: begin
                                reply_byte <= {6'b0, done, busy};
                                state <= REPLY;
                            end
                            LOAD_A, LOAD_B: begin
                                if (!busy) begin
                                    load_index <= 0;
                                    if (rx_byte == LOAD_A) begin
                                        a_valid <= 1'b0;
                                        state <= WRITE_A;
                                    end else begin
                                        b_valid <= 1'b0;
                                        state <= WRITE_B;
                                    end
                                end
                            end
                            MULTIPLY, ACCUMULATE: begin
                                if (!busy && a_valid && b_valid &&
                                    ((rx_byte == MULTIPLY) || done)) begin
                                    accumulate <= (rx_byte == ACCUMULATE);
                                    start <= 1'b1;
                                end
                            end
                            READ_RESULT: begin
                                if (!busy && done) begin
                                    read_index <= 0;
                                    result_byte <= 0;
                                    state <= READ_C;
                                end
                            end
                            default: begin end
                        endcase
                    end

                    WRITE_A, WRITE_B: begin
                        write_en <= 1'b1;
                        write_matrix_b <= (state == WRITE_B);
                        write_index <= load_index;
                        write_data <= rx_byte;
                        if (load_index == N*N-1) begin
                            if (state == WRITE_A)
                                a_valid <= 1'b1;
                            else
                                b_valid <= 1'b1;
                            state <= IGNORE;
                        end else begin
                            load_index <= load_index + 1'b1;
                        end
                    end

                    REPLY: state <= IGNORE;

                    READ_C: begin
                        if (result_byte == 2'd3) begin
                            result_byte <= 0;
                            if (read_index == N*N-1)
                                state <= IGNORE;
                            else
                                read_index <= read_index + 1'b1;
                        end else begin
                            result_byte <= result_byte + 1'b1;
                        end
                    end

                    default: state <= IGNORE;
                endcase
            end
        end
    end
endmodule
