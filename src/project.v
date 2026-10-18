/*
 * Copyright (c) 2026 Syver Haraldsen
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module tt_um_syverh_spi_mac (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered, so you can ignore it
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);

localparam N = 2;
localparam INDEX_BITS = $clog2(N*N);

wire logic_rst_n = rst_n && ena;
wire spi_miso;
wire spi_selected_sync;
wire rx_valid;
wire [7:0] rx_byte, tx_byte;
wire matrix_write_en, matrix_write_b, matrix_start, matrix_accumulate;
wire [INDEX_BITS-1:0] matrix_write_index, matrix_read_index;
wire signed [7:0] matrix_write_data;
wire signed [31:0] matrix_read_data;
wire matrix_busy, matrix_done;

spi_slave spi (
    .clk(clk), .rst_n(logic_rst_n),
    .cs_n(uio_in[0]), .sck(uio_in[1]), .mosi(uio_in[2]), .miso(spi_miso),
    .selected(spi_selected_sync), .rx_valid(rx_valid),
    .rx_byte(rx_byte), .tx_byte(tx_byte)
);

command_controller #(.N(N)) controller (
    .clk(clk), .rst_n(logic_rst_n),
    .selected(spi_selected_sync), .rx_valid(rx_valid),
    .rx_byte(rx_byte), .tx_byte(tx_byte),
    .write_en(matrix_write_en), .write_matrix_b(matrix_write_b),
    .write_index(matrix_write_index), .write_data(matrix_write_data),
    .start(matrix_start), .accumulate(matrix_accumulate),
    .busy(matrix_busy), .done(matrix_done),
    .read_index(matrix_read_index), .read_data(matrix_read_data)
);

matrix_engine #(.N(N)) engine (
    .clk(clk), .rst_n(logic_rst_n),
    .write_en(matrix_write_en), .write_matrix_b(matrix_write_b),
    .write_index(matrix_write_index), .write_data(matrix_write_data),
    .start(matrix_start), .accumulate(matrix_accumulate),
    .busy(matrix_busy), .done(matrix_done),
    .read_index(matrix_read_index), .read_data(matrix_read_data)
);

// DONE stays high after completion, until the next accepted start or reset.
assign uo_out[0] = matrix_done && logic_rst_n;
assign uo_out[7:1] = 7'b0;

// Output data: only pin 3 carries a signal (MISO).
// Output-enable below decides whether a pin actually drives this value.
assign uio_out[3]   = spi_miso;
assign uio_out[2:0] = 3'b000;
assign uio_out[7:4] = 4'b0000;

wire spi_selected;
wire miso_output_enabled;

assign spi_selected = !uio_in[0]; // CS_n is active low.
assign miso_output_enabled = ena && rst_n && spi_selected;

// Output-enable: 0 = input / output driver off, 1 = output driver on.
assign uio_oe[0]   = 1'b0;                // CS_n: input
assign uio_oe[1]   = 1'b0;                // SCK: input
assign uio_oe[2]   = 1'b0;                // MOSI: input
assign uio_oe[3]   = miso_output_enabled; // MISO: output while selected
assign uio_oe[7:4] = 4'b0000;             // Unused pins: drivers off

// Tell the linter these inputs are intentionally unused.
// The reduction AND (&) includes a constant 0, so this is optimized away.
wire _unused = &{ui_in, uio_in[7:3], 1'b0};

endmodule
