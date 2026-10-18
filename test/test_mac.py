# SPDX-FileCopyrightText: 2026 Syver Haraldsen
# SPDX-License-Identifier: Apache-2.0

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge


def signed_acc(dut):
    """Interpret the accumulator bits as a signed two's-complement integer."""
    raw = int(dut.acc.value)
    width = len(dut.acc)
    return raw - (1 << width) if raw & (1 << (width - 1)) else raw


async def setup_mac(dut):
    dut.rst_n.value = 0
    dut.clear.value = 0
    dut.enable.value = 0
    dut.load.value = 0
    dut.load_value.value = 0
    dut.a.value = 0
    dut.b.value = 0
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await ClockCycles(dut.clk, 2)
    await ReadOnly()
    assert signed_acc(dut) == 0


async def step(dut, a=0, b=0, enable=0, clear=0, rst_n=1, load=0, load_value=0):
    """Drive inputs before the active edge and read the settled result."""
    await FallingEdge(dut.clk)
    dut.a.value = a & ((1 << len(dut.a)) - 1)
    dut.b.value = b & ((1 << len(dut.b)) - 1)
    dut.enable.value = enable
    dut.load.value = load
    dut.load_value.value = load_value & ((1 << len(dut.acc)) - 1)
    dut.clear.value = clear
    dut.rst_n.value = rst_n
    await RisingEdge(dut.clk)
    await ReadOnly()
    return signed_acc(dut)


@cocotb.test()
async def test_accumulate_and_hold(dut):
    await setup_mac(dut)
    # The input is accepted now, and added to acc on the next clock edge.
    assert await step(dut, 3, 4, enable=1) == 0
    assert await step(dut, -2, 5, enable=1) == 12
    # Disabling input still lets the final pending product finish.
    assert await step(dut, 127, -128) == 2
    assert await step(dut, -128, -128) == 2

    # Consecutive requests sustain one completed product per clock.
    for expected in (2, 14, 26):
        assert await step(dut, 3, 4, enable=1) == expected
    assert await step(dut) == 38
    assert await step(dut) == 38


@cocotb.test()
async def test_clear_and_reset_priority(dut):
    await setup_mac(dut)
    for control in ({"clear": 1}, {"rst_n": 0}, {"clear": 1, "rst_n": 0}):
        assert await step(dut, load=1, load_value=100) == 100
        assert await step(dut, 7, 9, enable=1) == 100
        # Cancel both the queued product and the new request.
        assert await step(dut, -3, 4, enable=1, **control) == 0
        assert await step(dut) == 0
        assert await step(dut, -3, 4, enable=1) == 0
        assert await step(dut) == -12
        assert await step(dut) == -12


@cocotb.test()
async def test_signed_products(dut):
    await setup_mac(dut)
    operands = [-128, -127, -1, 0, 1, 126, 127]
    for a in operands:
        for b in operands:
            await step(dut, clear=1)
            assert await step(dut, a, b, enable=1) == 0
            actual = await step(dut)
            assert actual == a * b, f"{a} * {b}: got {actual}"

    rng = random.Random(0x77)
    await step(dut, clear=1)
    expected, pending = 0, 0
    for index in range(200):
        a, b = rng.randint(-128, 127), rng.randint(-128, 127)
        enable = rng.randrange(2)
        expected += pending
        actual = await step(dut, a, b, enable=enable)
        assert actual == expected, f"Seed 0x77, operation {index}: got {actual}, expected {expected}"
        pending = a * b if enable else 0
    assert await step(dut) == expected + pending
    assert await step(dut) == expected + pending


@cocotb.test()
async def test_load_accumulator(dut):
    await setup_mac(dut)
    assert await step(dut, load=1, load_value=-100) == -100
    assert await step(dut, 3, 4, enable=1) == -100
    assert await step(dut) == -88
    assert await step(dut, 7, 9, enable=1) == -88
    # Load discards the pending 63 and ignores the simultaneous input 12.
    assert await step(dut, 3, 4, enable=1, load=1, load_value=9) == 9
    assert await step(dut) == 9
    assert await step(dut, clear=1, load=1, load_value=9) == 0
    assert await step(dut, rst_n=0, load=1, load_value=9) == 0
    assert await step(dut) == 0


@cocotb.test()
async def test_overflow_wraps(dut):
    await setup_mac(dut)
    maximum = (1 << (len(dut.acc) - 1)) - 1
    minimum = -(1 << (len(dut.acc) - 1))
    assert await step(dut, load=1, load_value=maximum) == maximum
    assert await step(dut, 1, 1, enable=1) == maximum
    assert await step(dut, -1, 1, enable=1) == minimum
    assert await step(dut) == maximum
    assert await step(dut) == maximum

    # Signed extreme products arriving on consecutive cycles across overflow.
    assert await step(dut, load=1, load_value=maximum - 16383) == maximum - 16383
    assert await step(dut, -128, -128, enable=1) == maximum - 16383
    assert await step(dut, -128, 127, enable=1) == minimum
    assert await step(dut) == (1 << 31) - 16256


@cocotb.test()
async def test_random_pipeline_controls(dut):
    await setup_mac(dut)
    rng = random.Random(0x7711)
    width = len(dut.acc)
    def wrap(value):
        return (value + (1 << (width - 1))) % (1 << width) - (1 << (width - 1))

    expected, pending = 0, 0
    for index in range(400):
        a, b = rng.randint(-128, 127), rng.randint(-128, 127)
        enable = rng.randrange(2)
        clear, load = rng.randrange(8) == 0, rng.randrange(8) == 0
        rst_n = int(rng.randrange(16) != 0)
        seed = rng.randrange(-(1 << (width - 1)), 1 << (width - 1))
        if not rst_n or clear:
            expected, pending = 0, 0
        elif load:
            expected, pending = seed, 0
        else:
            expected = wrap(expected + pending)
            pending = a * b if enable else 0
        actual = await step(dut, a, b, enable=enable, clear=clear,
                            load=load, load_value=seed, rst_n=rst_n)
        assert actual == expected, f"Seed 0x7711, cycle {index}: {actual} != {expected}"
    assert await step(dut) == wrap(expected + pending)
    assert await step(dut) == wrap(expected + pending)
