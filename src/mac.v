/*
 * Copyright (c) 2026 Syver Haraldsen
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module mac #(
    parameter DATA_BITS = 8,
    parameter ACC_BITS = 32  // Must be at least 2 * DATA_BITS.
) (
    input wire clk,
    input wire rst_n,
    input wire clear,
    input wire enable, // Accept a new product; accumulate it on the next edge.
    input wire load,
    input wire signed [ACC_BITS-1:0] load_value,
    input wire signed [DATA_BITS-1:0] a,
    input wire signed [DATA_BITS-1:0] b,
    output reg signed [ACC_BITS-1:0] acc
);

    // Stage 1 stores the signed product. Stage 2 adds the previous product.
    // Once filled, the pipeline accepts and completes one product per clock.
    reg signed [2*DATA_BITS-1:0] product;
    reg product_valid;
    wire signed [ACC_BITS-1:0] extended_product;

    always @(posedge clk) begin
        if (!rst_n || clear || load) begin
            // Discard pending work and ignore enable on these control edges.
            product_valid <= 1'b0;
        end else begin
            product_valid <= enable;
            if (enable)
                product <= a * b;
        end
        // No data reset is needed: product is read only when valid.
    end

    // Repeat the sign bit so negative products remain negative at ACC_BITS.
    assign extended_product = {
        {(ACC_BITS-2*DATA_BITS){product[2*DATA_BITS-1]}}, product
    };

    // Priority: reset > clear > load > pending product > hold.
    // Nonblocking assignments make this read the previous cycle's product.
    always @(posedge clk) begin
        if (!rst_n)
            acc <= {ACC_BITS{1'b0}};
        else if (clear)
            acc <= {ACC_BITS{1'b0}};
        else if (load)
            acc <= load_value;
        else if (product_valid)
            acc <= acc + extended_product;
        // enable=0 stops new work; a pending product still finishes once.
    end

    // Overflow wraps in two's complement; there is no saturation logic.
endmodule
