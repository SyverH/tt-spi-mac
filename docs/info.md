## How it works

Just the template adder to check that simulation and the ASIC build work.
It adds ui_in and uio_in and puts the low 8 bits on uo_out.
The bidirectional pins are inputs. Clock and reset are unused.

## How to test

Set ui_in to 20 and uio_in to 30; uo_out should be 50.
Run `make` in the test directory to try it in simulation.

## External hardware

None needed for simulation.
