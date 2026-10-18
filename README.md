![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg)

# SPI matrix accelerator

A Tiny Tapeout learning project: signed int8 2x2 matrix multiplication with one
reused, pipelined MAC and signed 32-bit results. Supports `C = A * B` and `C = C + A * B`,
SPI loading/readout, status polling and a persistent DONE output.

- [Protocol, pinout and example](docs/info.md)
- [Running the tests](test/README.md)

The data path is `SPI -> command controller -> matrix engine -> MAC`.
The engine size is a build-time parameter; the integrated target is currently
2x2 on two SKY130 tiles (1x2), with a placement density target of 75%.
The GDS workflow fits the design in two tiles and meets setup and hold timing
at the 50 MHz build target. The slow corner still has maximum-slew violations.

From `test/`, run `make` for the full SPI test and the Makefile.mac,
Makefile.matrix and Makefile.controller targets for unit tests.

Built using the [Tiny Tapeout](https://tinytapeout.com) Verilog template.
