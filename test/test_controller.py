# SPDX-FileCopyrightText: 2026 Syver Haraldsen
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, ReadOnly


async def tick(dut, **inputs):
    await FallingEdge(dut.clk)
    dut.rx_valid.value = 0
    for name, value in inputs.items():
        getattr(dut, name).value = value
    await RisingEdge(dut.clk)
    await ReadOnly()


async def setup(dut):
    for name in ("rst_n", "selected", "rx_valid", "rx_byte", "busy", "done", "read_data"):
        getattr(dut, name).value = 0
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await tick(dut)
    await tick(dut, rst_n=1)


async def command(dut, opcode):
    await tick(dut, selected=0)
    await tick(dut, selected=1, rx_valid=1, rx_byte=opcode)


async def load(dut, opcode):
    await command(dut, opcode)
    for index in range(4):
        await tick(dut, rx_valid=1, rx_byte=index+1)
        assert int(dut.write_en.value) == 1
        assert int(dut.write_matrix_b.value) == (opcode == 0x11)
        assert int(dut.write_index.value) == index
        assert int(dut.write_data.value) == index+1
    await tick(dut, selected=0)
    assert int(dut.write_en.value) == 0


@cocotb.test()
async def test_busy_rejection_and_status_snapshot(dut):
    """Exercise BUSY directly: the small engine may finish before SPI can poll."""
    await setup(dut)
    await load(dut, 0x10)
    await load(dut, 0x11)
    await tick(dut, busy=1)
    for opcode in (0x10, 0x11, 0x20, 0x21, 0x30):
        await command(dut, opcode)
        assert int(dut.start.value) == 0
        assert int(dut.write_en.value) == 0
        assert int(dut.tx_byte.value) == 0
        # Finishing during a rejected frame must not revive that command.
        await tick(dut, busy=0, done=1, rx_valid=1, rx_byte=0x20)
        assert int(dut.start.value) == 0
        assert int(dut.write_en.value) == 0
        assert int(dut.tx_byte.value) == 0
        await tick(dut, busy=1, done=0)

    await command(dut, 0x02)
    assert int(dut.tx_byte.value) == 1
    await tick(dut, busy=0, done=1)
    assert int(dut.tx_byte.value) == 1  # Reply is a snapshot, not a live bus.
    await command(dut, 0x02)
    assert int(dut.tx_byte.value) == 2
    await tick(dut, busy=1, done=0)
    await command(dut, 0x01)
    assert int(dut.tx_byte.value) == 0x77

    # Rejected loads must not invalidate previously complete matrices.
    await tick(dut, busy=0)
    await command(dut, 0x20)
    assert int(dut.start.value) == 1
    assert int(dut.accumulate.value) == 0
    await tick(dut)
    assert int(dut.start.value) == 0
    await tick(dut, done=1)
    await command(dut, 0x21)
    assert int(dut.start.value) == 1
    assert int(dut.accumulate.value) == 1


@cocotb.test()
async def test_short_load_invalidates_only_target(dut):
    await setup(dut)
    for opcode in (0x10, 0x11):
        await load(dut, 0x10)
        await load(dut, 0x11)
        await command(dut, opcode)
        await tick(dut, rx_valid=1, rx_byte=99)
        await command(dut, 0x20)
        assert int(dut.start.value) == 0
        await load(dut, opcode)
        await command(dut, 0x20)
        assert int(dut.start.value) == 1
