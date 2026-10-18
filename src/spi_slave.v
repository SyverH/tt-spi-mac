/*
 * Copyright (c) 2026 Syver Haraldsen
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module spi_slave (
    input wire clk,
    input wire rst_n,

    input wire cs_n,
    input wire sck,
    input wire mosi,
    output reg miso,

    // Byte interface in the system-clock domain.
    output wire selected,
    output wire rx_valid,
    output wire [7:0] rx_byte,
    input wire [7:0] tx_byte
);

// Internal registers
reg sck_metastable;
reg sck_sync;

reg cs_n_metastable;
reg cs_n_sync;

reg mosi_metastable;
reg mosi_sync;

// Synchronize the SCK signal to the clk domain
always @(posedge clk) begin
    if (!rst_n) begin
        sck_metastable <= 1'b0;
        sck_sync <= 1'b0;
    end else begin
        sck_metastable <= sck;
        sck_sync <= sck_metastable;
    end
end

// Synchronize the CS signal to the clk domain
always @(posedge clk) begin
    if (!rst_n) begin
        cs_n_metastable <= 1'b1; // Active low, so default to high (not selected)
        cs_n_sync <= 1'b1;
    end else begin
        cs_n_metastable <= cs_n;
        cs_n_sync <= cs_n_metastable;
    end
end

// Synchronize the MOSI signal to the clk domain
always @(posedge clk) begin
    if (!rst_n) begin
        mosi_metastable <= 1'b0;
        mosi_sync <= 1'b0;
    end else begin
        mosi_metastable <= mosi;
        mosi_sync <= mosi_metastable;
    end
end

// SPI Flank Detection
reg sck_prev;

always @(posedge clk) begin
    if (!rst_n) begin
        sck_prev <= 1'b0;
    end else begin
        sck_prev <= sck_sync;
    end
end

wire sck_rising = sck_sync & ~sck_prev;
wire sck_falling = ~sck_sync & sck_prev;

// Store seven previous bits; the eighth bit comes directly from mosi_sync.
reg [6:0] rx_shift;
reg [2:0] bit_count;

// Include the incoming bit: rx_shift still holds the previous bits when
// the response is sampled. This is not a registered command or valid pulse.
assign selected = !cs_n_sync;
assign rx_valid = rst_n && selected && sck_rising && (bit_count == 3'd7);
assign rx_byte = {rx_shift, mosi_sync};

always @(posedge clk) begin
    if (!rst_n) begin
        rx_shift <= 7'h00;
        bit_count <= 3'd0;
    end else if (cs_n_sync) begin
        // Not selected: prepare for a new transaction
        rx_shift <= 7'h00;
        bit_count <= 3'd0;
    end else if (sck_rising) begin
        rx_shift <= {rx_shift[5:0], mosi_sync};
        bit_count <= bit_count + 3'd1;
    end
end

// Each received byte triggers transmission of a new byte. The controller
// updates tx_byte on the eighth rising edge; we load it on the following
// detected falling edge, before the host samples the next byte's first bit.
reg tx_pending;
reg [7:0] tx_shift;

always @(posedge clk) begin
    if (!rst_n || cs_n_sync) begin
        miso <= 1'b0;
        tx_pending <= 1'b0;
        tx_shift <= 8'h00;
    end else if (rx_valid) begin
        tx_pending <= 1'b1;
    end else if (sck_falling) begin
        if (tx_pending) begin
            miso <= tx_byte[7];
            tx_shift <= {tx_byte[6:0], 1'b0};
            tx_pending <= 1'b0;
        end else begin
            miso <= tx_shift[7];
            tx_shift <= {tx_shift[6:0], 1'b0};
        end
    end
end

endmodule
