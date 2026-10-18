## How it works

A small signed int8 matrix accelerator controlled over SPI. The built design
multiplies two 2x2 matrices using one reused MAC, with signed 32-bit results.
It supports both `C = A * B` and `C = C + A * B`. Overflow wraps in two's
complement; there is no saturation or floating-point logic.

The modules are:

- `spi_slave`: synchronizes the SPI inputs and transfers bytes.
- `command_controller`: interprets one command per CS-low frame, tracks complete
  input loads, and streams result bytes.
- `matrix_engine`: stores A/B/C and selects operands for each dot product.
- `mac`: one multiplier, product register, adder and accumulator, reused for every result.

The MAC has two pipeline stages: it captures a signed 16-bit product, then
adds that product to the 32-bit accumulator on the next clock edge. It can
accept one new product per clock. The matrix engine waits for the last product
to be accumulated before storing each result. Clear, load and reset discard
any pending product. The SPI commands and result format are unchanged.
- `project`: connects the modules and the Tiny Tapeout pins.

### Pins and clocks

| Pin | Function |
| --- | --- |
| `uio[0]` | SPI CS_n input, active low |
| `uio[1]` | SPI SCK input |
| `uio[2]` | SPI MOSI input |
| `uio[3]` | SPI MISO output, driven only while selected, enabled and out of reset |
| `uo[0]` | DONE output, active high |
| `clk` | Continuous system clock for the SPI logic and calculation |
| `rst_n` | Active-low synchronous reset |

Other output drivers are disabled or tied low, and other inputs are unused.
When `ena` is low, the design is held in reset and MISO is released.

SPI uses mode 0 (SCK idle low), MSB first. Keep each SCK half-period at least
five system-clock periods. Keep CS low for at least five system-clock periods
before the first SCK rising edge and after the final falling edge; keep CS high
for at least five periods between frames. This is the conservative protocol
operating envelope used by the RTL tests, not a measured silicon speed limit.
The 50 MHz ASIC clock constraint (20 ns period) meets setup and hold timing in
the GDS workflow; the slow corner still has maximum-slew violations.

SPI SCK is sampled by the system clock, rather than clocking the MAC directly.
The system clock must keep running while using SPI or computing a result.
A calculation finishes even if SCK stops.

### Commands

Each CS-low frame starts with one command byte. All numbers below are hex.
Data bytes that happen to equal a command are still data. Matrix elements are
sent row by row; negative inputs use 8-bit two's complement.

| Command | Following MOSI bytes | MISO response after command byte |
| --- | --- | --- |
| `01` | One dummy byte | Device ID `77` |
| `02` | One dummy byte | Status: bit 0 BUSY, bit 1 DONE; other bits zero |
| `10` | Four matrix A elements | Ignored (zero) |
| `11` | Four matrix B elements | Ignored (zero) |
| `20` | None | Start `C = A * B` |
| `21` | None | Start `C = C + A * B` |
| `30` | Sixteen dummy bytes | Four signed 32-bit results, low byte first |

MISO during the command byte is zero and should be ignored. Dummy bytes only
provide the clock pulses to read data; their MOSI value does not matter.
Status is captured when the command byte is received and stays fixed for that
reply. Extra bytes after a complete command/response are ignored and return zero
until CS goes high. Unknown and rejected commands behave the same way.

### Loading, calculation and DONE

Reset invalidates both input matrices and clears DONE. Start requires a complete
A and B. Accumulation also requires an existing completed C. A rejected start
leaves the current state and previous result unchanged; there are no error codes.

Starting a matrix load immediately invalidates that input matrix. Elements are
written as their bytes arrive. Only the fourth complete data byte marks the
matrix valid again. If CS rises early, reload the entire target matrix. An
incomplete load does not invalidate the other matrix or the previous result.

A command takes effect as soon as its required bytes are received; CS rising
ends the frame but is not a separate commit operation. Accepted starts clear
DONE and set BUSY. Completion clears BUSY and raises DONE. Reading results,
reading status or loading new input matrices does not clear DONE. It remains
high until the next accepted start or reset, so a host can use a rising-edge GPIO
interrupt or poll status. A stale DONE after a rejected start is possible: the
host must follow the loading rules.

While busy, only ID and status commands are accepted. Loads, starts and result
reads received while busy are ignored for the entire frame. Reading C before
there is a complete result returns zeros. The 2x2 calculation is short enough
that it may finish before a subsequent SPI status command can observe BUSY.

### Example

For A = `[1, 2; 3, 4]` and B = `[5, 6; 7, 8]`, send each line with its own CS:

```text
MOSI: 01 00                         MISO: 00 77
MOSI: 10 01 02 03 04                 Load A
MOSI: 11 05 06 07 08                 Load B
MOSI: 20                            Start multiplication
        Wait for DONE, or poll 02 00 until status is 02.
MOSI: 30 + sixteen dummy bytes
MISO: 00  13 00 00 00  16 00 00 00  2B 00 00 00  32 00 00 00
```

The result is `[19, 22; 43, 50]`. Send `21`, wait for the next completion, and
read again to get `[38, 44; 86, 100]`. A subsequent `20` replaces C again.

## How to test

Activate the Python environment, then run from `test/`:

```sh
make
make -f Makefile.controller
make -f Makefile.mac
make -f Makefile.matrix
make -f Makefile.matrix N=3
```

The top-level tests exercise the full SPI path, signed and random matrices,
accumulation, DONE, frame boundaries, incomplete loads and recovery, reset,
and MISO output-enable. Unit tests additionally check busy rejection, status
snapshots, arithmetic overflow, and the parameterized matrix engine.

`N=3` tests the engine only; the integrated SPI design is 2x2. Changing the
integrated size requires rebuilding with a different `N` in `project.v` and
adjusting host/test lengths (N*N input bytes and 4*N*N result bytes).
Passing simulation does not establish area fit or maximum clock speed. These
require the GDS flow, timing checks and gate-level tests.

## External hardware

An SPI host, a continuous system clock and reset. Optionally connect DONE to a
host GPIO interrupt. No external hardware is required for simulation.
