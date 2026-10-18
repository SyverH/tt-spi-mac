# Tests

Run these commands from this directory with the Python environment active:

```sh
make                              # Complete 2x2 SPI accelerator
make -f Makefile.controller        # Protocol rules, including busy rejection
make -f Makefile.mac               # Arithmetic, hold, clear/load/reset, overflow
make -f Makefile.matrix            # Matrix engine, N=2
make -f Makefile.matrix N=3        # Engine parameterization only
```

The top-level test uses the external pins only, so it also runs against the
hardened netlist with `make GATES=yes` when `gate_level_netlist.v` and the PDK
models are available. The GitHub GDS workflow supplies those files.

`make` writes `results.xml` and `tb.fst`; open `tb.fst` in VaporView to see the
SPI signals, DONE on `uo_out[0]`, and the RTL internals. Standalone unit tests
write results under `sim_build/controller`, `sim_build/mac`, and
`sim_build/matrix_<N>`. They do not currently produce waveforms.

## Interfaces under test

The integrated design has signed 8-bit inputs, signed 32-bit results, and N=2.
See [the protocol documentation](../docs/info.md) for command bytes and timing.

The MAC supports configurable DATA_BITS and ACC_BITS, with ACC_BITS at least
2*DATA_BITS. An enabled input is captured as a product on one edge and added
to the accumulator on the following edge. Consecutive inputs sustain one
product per clock; disabling input allows the final pending product to finish.
Reset, clear and load (in that priority order) discard pending products and
ignore simultaneous input requests. Matrix accumulation loads an old C element
into the MAC before adding the next dot product. The engine drains the pipeline
before storing each result.

The matrix engine uses row-major element write/read ports. Pulse start only
when both matrices are fully loaded. With accumulate=1, an old completed C must
also exist. Writes and starts are ignored while busy; simultaneous write/start
while idle performs the write. DONE remains high until accepted start/reset.
Arrays are not reset; the command controller tracks input validity, and the
engine hides C until complete. Unit tests reload operands after reset.

N=3 simulation confirms arithmetic and indexing, not that a 3x3 design fits
the allocated two tiles. RTL unit-test clock periods are simulation stimuli,
not established silicon performance.
