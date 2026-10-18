# SPDX-FileCopyrightText: 2026 Syver Haraldsen
# SPDX-License-Identifier: Apache-2.0

import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge


N = int(os.environ.get("MATRIX_N", "2"))


def reference(a, b):
    """Row-major matrix multiplication, independently calculated in Python."""
    return [
        sum(a[row*N + k] * b[k*N + col] for k in range(N))
        for row in range(N) for col in range(N)
    ]


async def tick(dut, **inputs):
    await FallingEdge(dut.clk)
    # Requests are pulses unless explicitly supplied on consecutive cycles.
    dut.start.value = 0
    dut.write_en.value = 0
    for name, value in inputs.items():
        signal = getattr(dut, name)
        signal.value = value & ((1 << len(signal)) - 1)
    await RisingEdge(dut.clk)
    await ReadOnly()


async def setup(dut):
    for name in ("rst_n", "start", "accumulate", "write_en", "write_matrix_b",
                 "write_index", "write_data", "read_index"):
        getattr(dut, name).value = 0
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await tick(dut)
    assert int(dut.busy.value) == 0
    assert int(dut.done.value) == 0
    assert int(dut.read_data.value) == 0
    await tick(dut, rst_n=1)


async def load(dut, values, matrix_b=False):
    for index, value in enumerate(values):
        await tick(dut, write_en=1, write_matrix_b=int(matrix_b),
                   write_index=index, write_data=value)


async def start(dut, accumulate=False):
    await tick(dut, start=1, accumulate=int(accumulate))
    assert int(dut.busy.value) == 1
    assert int(dut.done.value) == 0


async def wait_done(dut):
    # A generous bounded wait, rather than depending on a particular FSM latency.
    for _ in range(10*N**3 + 20):
        if int(dut.done.value):
            assert int(dut.busy.value) == 0
            return
        assert int(dut.busy.value) == 1
        await tick(dut)
    assert False, "Matrix engine did not finish before timeout"


async def read_result(dut):
    result = []
    for index in range(N*N):
        await tick(dut, read_index=index)
        assert int(dut.done.value) == 1
        assert int(dut.busy.value) == 0
        raw = int(dut.read_data.value)
        width = len(dut.read_data)
        result.append(raw - (1 << width) if raw & (1 << (width - 1)) else raw)
    return result


@cocotb.test()
async def test_example_and_reuse(dut):
    await setup(dut)
    a = list(range(1, N*N + 1))
    b = list(range(N*N + 1, 2*N*N + 1))
    await load(dut, a)
    await load(dut, b, matrix_b=True)
    await start(dut)
    await wait_done(dut)
    result = await read_result(dut)
    assert result == reference(a, b)
    if N == 2:
        assert result == [19, 22, 43, 50]
    dut._log.info("N=%d: A=%s, B=%s, C=%s", N, a, b, result)

    # Reading does not clear done, and operands survive repeated calculations.
    assert await read_result(dut) == result
    await start(dut)
    await wait_done(dut)
    assert await read_result(dut) == result

    # Keep A and replace only B with the identity matrix: C must become A.
    identity = [int(row == col) for row in range(N) for col in range(N)]
    await load(dut, identity, matrix_b=True)
    await start(dut)
    await wait_done(dut)
    assert await read_result(dut) == a


@cocotb.test()
async def test_signed_matrices(dut):
    await setup(dut)
    rng = random.Random(0x77)
    cases = [([-128]*(N*N), [-128]*(N*N)),
             ([-128]*(N*N), [127]*(N*N)),
             ([0]*(N*N), [127]*(N*N))]
    cases += [([rng.randint(-128, 127) for _ in range(N*N)],
               [rng.randint(-128, 127) for _ in range(N*N)])
              for _ in range(30)]
    for case, (a, b) in enumerate(cases):
        await load(dut, a)
        await load(dut, b, matrix_b=True)
        await start(dut)
        await wait_done(dut)
        actual = await read_result(dut)
        assert actual == reference(a, b), f"Seed 0x77, case {case}, A={a}, B={b}, C={actual}"


@cocotb.test()
async def test_busy_rejects_requests(dut):
    await setup(dut)
    a, b = [3]*(N*N), [-2]*(N*N)
    await load(dut, a)
    await load(dut, b, matrix_b=True)

    # A write wins if write and start arrive together while idle.
    await tick(dut, write_en=1, write_matrix_b=0, write_index=0,
               write_data=3, start=1)
    assert int(dut.busy.value) == 0
    await start(dut)
    await tick(dut, start=1, write_en=1, write_matrix_b=0,
               write_index=0, write_data=127)
    await tick(dut, write_en=1, write_matrix_b=1,
               write_index=0, write_data=-128)
    await wait_done(dut)
    assert await read_result(dut) == reference(a, b)

    # Ignored writes must not have changed the stored operands either.
    await start(dut)
    await wait_done(dut)
    assert await read_result(dut) == reference(a, b)


@cocotb.test()
async def test_accumulation(dut):
    await setup(dut)
    a, b = [3]*(N*N), [-2]*(N*N)
    await load(dut, a)
    await load(dut, b, matrix_b=True)
    # No old C exists after reset: accumulation is rejected.
    await tick(dut, start=1, accumulate=1)
    assert int(dut.busy.value) == 0
    assert int(dut.done.value) == 0
    await start(dut)
    await wait_done(dut)
    expected = reference(a, b)
    for repetition in range(2, 5):
        await start(dut, accumulate=True)
        await wait_done(dut)
        assert await read_result(dut) == [x * repetition for x in expected]
    # Ordinary multiply replaces C again, rather than adding to it.
    await start(dut)
    await wait_done(dut)
    assert await read_result(dut) == expected


@cocotb.test()
async def test_reset_during_calculation(dut):
    await setup(dut)
    await load(dut, [127]*(N*N))
    await load(dut, [127]*(N*N), matrix_b=True)
    await start(dut)
    await tick(dut)
    await tick(dut)
    await tick(dut, rst_n=0)
    assert int(dut.busy.value) == 0
    assert int(dut.done.value) == 0
    assert int(dut.read_data.value) == 0
    await tick(dut, rst_n=1)

    # Reset invalidates the previous job; reload operands before restarting.
    a, b = [-1]*(N*N), [2]*(N*N)
    await load(dut, a)
    await load(dut, b, matrix_b=True)
    await start(dut)
    await wait_done(dut)
    assert await read_result(dut) == reference(a, b)
