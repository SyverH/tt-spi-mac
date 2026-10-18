`default_nettype none
`timescale 1ns / 1ps

/* This testbench just instantiates the module and makes some convenient wires
   that can be driven / tested by the cocotb test.py.
*/
module tb ();

  // Dump the signals to a FST file. You can view it with gtkwave or surfer.
  initial begin
    $dumpfile("tb.fst");
    $dumpvars(0, tb);
    #1;
  end

  // Wire up the inputs and outputs:
  reg clk;
  reg rst_n;
  reg ena;
  reg [7:0] ui_in;
  wire [7:0] uio_in;
  wire [7:0] uo_out;
  wire [7:0] uio_out;
  wire [7:0] uio_oe;

  // SPI signals driven by the test
  reg spi_cs_n;
  reg spi_clk;
  reg spi_mosi;

  // SPI signal read by the test
  wire spi_miso;

  assign uio_in[0] = spi_cs_n;  // SPI chip select
  assign uio_in[1] = spi_clk;   // SPI clock
  assign uio_in[2] = spi_mosi;  // Data from the master
  assign uio_in[3] = 1'b0;      // MISO is an output, so its input is unused
  assign uio_in[7:4] = 4'b0;    // Unused bits tied to 0

  assign spi_miso = uio_out[3];  // Data to the master

`ifdef GL_TEST
  wire VPWR = 1'b1;
  wire VGND = 1'b0;
`endif

  // Instantiate the Tiny Tapeout top module.
  tt_um_syverh_spi_mac user_project (

      // Include power ports for the Gate Level test:
`ifdef GL_TEST
      .VPWR(VPWR),
      .VGND(VGND),
`endif

      .ui_in  (ui_in),    // Dedicated inputs
      .uo_out (uo_out),   // Dedicated outputs
      .uio_in (uio_in),   // IOs: Input path
      .uio_out(uio_out),  // IOs: Output path
      .uio_oe (uio_oe),   // IOs: Enable path (active high: 0=input, 1=output)
      .ena    (ena),      // enable - goes high when design is selected
      .clk    (clk),      // clock
      .rst_n  (rst_n)     // not reset
  );

endmodule
