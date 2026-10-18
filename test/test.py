# SPDX-FileCopyrightText: © 2024 Tiny Tapeout
# SPDX-License-Identifier: Apache-2.0

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, Timer


HALF_PERIOD_NS = 50_000  # 10 kHz SPI, with a 100 kHz system clock.


async def setup_dut(dut):
    """Start the system clock and reset the device before each test."""
    dut.spi_cs_n.value = 1
    dut.spi_clk.value = 0
    dut.spi_mosi.value = 0
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.rst_n.value = 0

    cocotb.start_soon(Clock(dut.clk, 10, unit="us").start())
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)


async def spi_transfer_bit(dut, tx_bit, half_period_ns):
    """Transfer one mode-0 bit, leaving SCK low afterwards."""
    dut.spi_mosi.value = tx_bit
    await Timer(half_period_ns, unit="ns")

    # Sample the stable MISO value immediately before raising SCK.
    rx_bit = int(dut.spi_miso.value)
    dut.spi_clk.value = 1
    await Timer(half_period_ns, unit="ns")
    dut.spi_clk.value = 0
    return rx_bit


async def spi_transfer_byte(dut, tx_byte, half_period_ns):
    """Perform a single SPI transfer of one byte."""
    rx_byte = 0

    for bit in range(7, -1, -1):
        rx_bit = await spi_transfer_bit(dut, (tx_byte >> bit) & 1, half_period_ns)
        rx_byte = (rx_byte << 1) | rx_bit

    return rx_byte

async def spi_command(dut, command, half_period_ns=HALF_PERIOD_NS):
    """Send a command byte over SPI and read the response."""
    # Assert CS
    dut.spi_cs_n.value = 0
    await Timer(half_period_ns, unit="ns")

    # Send the command; ignore data received during this byte.
    await spi_transfer_byte(dut, command, half_period_ns)

    # Clock out the response by sending a dummy byte.
    response = await spi_transfer_byte(dut, 0x00, half_period_ns)

    # Deassert CS
    await Timer(half_period_ns, unit="ns")
    dut.spi_cs_n.value = 1

    # Let the slave register CS high before the next transaction.
    await Timer(half_period_ns, unit="ns")

    return response


async def spi_transaction(dut, data, half_period_ns=HALF_PERIOD_NS):
    """One complete CS-low frame; return the byte received for each byte sent."""
    dut.spi_cs_n.value = 0
    await Timer(half_period_ns, unit="ns")
    received = []
    for value in data:
        received.append(await spi_transfer_byte(dut, value & 0xFF, half_period_ns))
    await Timer(half_period_ns, unit="ns")
    dut.spi_cs_n.value = 1
    await Timer(half_period_ns, unit="ns")
    assert int(dut.uio_oe.value) == 0, "MISO must be released between frames"
    return received


async def wait_matrix_done(dut):
    # The system clock keeps running; no SPI clocks are needed to finish.
    for _ in range(40):
        if int(dut.uo_out.value) & 1:
            return
        await Timer(10, unit="us")
    assert False, "DONE pin did not rise before timeout"


async def read_matrix(dut):
    received = await spi_transaction(dut, [0x30] + [0]*16)
    data = bytes(received[1:])
    return [int.from_bytes(data[i:i+4], "little", signed=True) for i in range(0, 16, 4)]


def matrix_reference(a, b):
    return [sum(a[row*2+k]*b[k*2+col] for k in range(2))
            for row in range(2) for col in range(2)]


async def spi_abort(dut, command, bit_count, sck_high=False, delay_ns=HALF_PERIOD_NS):
    """Release CS after 1–15 rising edges of a command + dummy-byte transfer."""
    assert 1 <= bit_count <= 15
    dut.spi_cs_n.value = 0
    await Timer(HALF_PERIOD_NS, unit="ns")

    # The first eight bits are the command; the next eight are dummy zeros.
    tx_word = command << 8
    for bit in range(15, 16 - bit_count, -1):
        await spi_transfer_bit(dut, (tx_word >> bit) & 1, HALF_PERIOD_NS)

    # Handle the final bit separately so we can abort with SCK high or low.
    dut.spi_mosi.value = (tx_word >> (16 - bit_count)) & 1
    await Timer(HALF_PERIOD_NS, unit="ns")
    dut.spi_clk.value = 1
    if not sck_high:
        await Timer(HALF_PERIOD_NS, unit="ns")
        dut.spi_clk.value = 0

    await Timer(delay_ns, unit="ns")
    dut.spi_cs_n.value = 1
    await Timer(HALF_PERIOD_NS, unit="ns")

    # Return to mode-0 idle while deselected. Do not reset the device.
    dut.spi_clk.value = 0
    dut.spi_mosi.value = 0
    await Timer(HALF_PERIOD_NS, unit="ns")


@cocotb.test()
async def test_commands(dut):
    """Repeat known and unknown commands without resetting between them."""
    await setup_dut(dut)

    # Each entry contains a command and its expected response.
    test_cases = [
        (0x01, 0x77),  # Read device ID
        (0x01, 0x77),  # Repeat without resetting
        (0xFF, 0x00),  # Unknown command
        (0x01, 0x77),  # Read ID after an unknown command
    ]

    repetitions = 10

    for repetition in range(repetitions):
        for command, expected in test_cases:
            response = await spi_command(dut, command)

            assert response == expected, (
                f"Repetition {repetition}, command {command:#04x}: "
                f"expected {expected:#04x}, got {response:#04x}"
            )


@cocotb.test()
async def test_aborted_command(dut):
    """Check recovery after every incomplete command length: 1 through 7 bits."""
    await setup_dut(dut)

    for bit_count in range(1, 8):
        await spi_abort(dut, 0x01, bit_count)
        response = await spi_command(dut, 0x01)
        assert response == 0x77, (
            f"After aborting at {bit_count} bits: expected 0x77, got {response:#04x}"
        )


@cocotb.test()
async def test_random_aborts(dut):
    """Vary abort timing and command data, then check recovery without reset."""
    await setup_dut(dut)
    seed = 0x77
    rng = random.Random(seed)
    dut._log.info("Random abort seed: %#x", seed)

    # Cover both clock levels at every position, including the response byte.
    cases = [(bits, high) for bits in range(1, 16) for high in (False, True)]
    rng.shuffle(cases)

    for case, (bit_count, sck_high) in enumerate(cases):
        command = rng.choice([0x01, 0xFF, rng.randrange(256)])
        delay_ns = rng.randint(1, HALF_PERIOD_NS - 1)
        # Also vary the phase relative to the system clock.
        await Timer(rng.randint(1, HALF_PERIOD_NS), unit="ns")
        await spi_abort(dut, command, bit_count, sck_high, delay_ns)

        for next_command, expected in [(0x01, 0x77), (0xFF, 0x00)]:
            response = await spi_command(dut, next_command)
            assert response == expected, (
                f"Seed {seed:#x}, case {case}, aborted command {command:#04x} "
                f"after {bit_count} bits, SCK high={sck_high}, delay={delay_ns} ns: "
                f"next command {next_command:#04x} expected {expected:#04x}, "
                f"got {response:#04x}"
            )


@cocotb.test()
async def test_miso_output_enable(dut):
    """Only MISO may drive, and only when enabled, selected and out of reset."""
    await setup_dut(dut)

    # Check all eight combinations of enable, reset and chip select.
    for ena in (1, 0):
        for rst_n in (1, 0):
            for cs_n in (1, 0):
                dut.ena.value = ena
                dut.rst_n.value = rst_n
                dut.spi_cs_n.value = cs_n
                await Timer(HALF_PERIOD_NS, unit="ns")

                expected = 0b00001000 if ena and rst_n and not cs_n else 0
                actual = int(dut.uio_oe.value)
                assert actual == expected, (
                    f"ena={ena}, rst_n={rst_n}, CS_n={cs_n}: "
                    f"expected uio_oe={expected:#04x}, got {actual:#04x}"
                )


@cocotb.test()
async def test_matrix_over_spi(dut):
    """ID -> load A/B -> multiply -> DONE -> read -> accumulate -> read."""
    await setup_dut(dut)
    assert await spi_command(dut, 0x01) == 0x77
    assert await spi_command(dut, 0x02) == 0
    assert await read_matrix(dut) == [0]*4
    await spi_transaction(dut, [0x10, 1, 2, 3, 4])
    await spi_transaction(dut, [0x11, 5, 6, 7, 8])
    await spi_transaction(dut, [0x20])
    await wait_matrix_done(dut)
    assert await spi_command(dut, 0x02) == 2  # DONE=1, BUSY=0.
    assert await read_matrix(dut) == [19, 22, 43, 50]
    assert await read_matrix(dut) == [19, 22, 43, 50]
    assert int(dut.uo_out.value) == 1

    # Start while old DONE is high. Observe it clear, then finish without SCK.
    dut.spi_cs_n.value = 0
    await Timer(HALF_PERIOD_NS, unit="ns")
    await spi_transfer_byte(dut, 0x21, HALF_PERIOD_NS)
    await Timer(1, unit="ns")
    assert int(dut.uo_out.value) == 0
    await Timer(HALF_PERIOD_NS, unit="ns")
    dut.spi_cs_n.value = 1
    await Timer(HALF_PERIOD_NS, unit="ns")
    await wait_matrix_done(dut)
    assert await read_matrix(dut) == [38, 44, 86, 100]

    # A fresh multiply replaces C instead of accumulating again.
    await spi_transaction(dut, [0x20])
    await wait_matrix_done(dut)
    assert await read_matrix(dut) == [19, 22, 43, 50]
    dut._log.info("SPI matrix example passed: C=[19, 22, 43, 50], accumulated C=[38, 44, 86, 100]")

    # Replace B only; old C remains available as an accumulation starting point.
    await spi_transaction(dut, [0x11, 1, 0, 0, 1])
    await spi_transaction(dut, [0x21])
    await wait_matrix_done(dut)
    assert await read_matrix(dut) == [20, 24, 46, 54]


@cocotb.test()
async def test_signed_random_matrices_over_spi(dut):
    await setup_dut(dut)
    rng = random.Random(0x77)
    cases = [([-128]*4, [-128]*4), ([-128]*4, [127]*4),
             ([0]*4, [127]*4), ([0x10, 0x11, 0x20, 0x30], [1, 0, 0, 1])]
    cases += [([rng.randint(-128, 127) for _ in range(4)],
               [rng.randint(-128, 127) for _ in range(4)]) for _ in range(8)]
    for case, (a, b) in enumerate(cases):
        # Vary SPI phase and run slower as well as at the nominal 10:1 ratio.
        await Timer(rng.randint(1, 9999), unit="ns")
        half_period = rng.choice([50_000, 63_001, 100_000])
        await spi_transaction(dut, [0x10] + a, half_period)
        await spi_transaction(dut, [0x11] + b, half_period)
        await spi_transaction(dut, [0x20], half_period)
        await wait_matrix_done(dut)
        actual = await read_matrix(dut)
        assert actual == matrix_reference(a, b), f"Seed 0x77, case {case}: A={a}, B={b}, C={actual}"


@cocotb.test()
async def test_incomplete_loads_and_recovery(dut):
    await setup_dut(dut)
    # Missing A/B, or missing an old C for accumulation, must not start work.
    await spi_transaction(dut, [0x20])
    assert await spi_command(dut, 0x02) == 0
    await spi_transaction(dut, [0x10, 1, 2, 3, 4])
    await spi_transaction(dut, [0x20])
    assert await spi_command(dut, 0x02) == 0
    await spi_transaction(dut, [0x11, 5, 6, 7, 8])
    await spi_transaction(dut, [0x21])
    assert await spi_command(dut, 0x02) == 0

    # Invalidate previously complete A/B by aborting a replacement load.
    for command, values in [(0x10, [1, 2, 3, 4]), (0x11, [5, 6, 7, 8])]:
        for count in range(4):
            await spi_transaction(dut, [command] + [99]*count)
            await spi_transaction(dut, [0x20])
            assert await spi_command(dut, 0x02) == 0
            await spi_transaction(dut, [command] + values)

        # Abort every possible partial length of the last data byte.
        for bits in range(1, 8):
            dut.spi_cs_n.value = 0
            await Timer(HALF_PERIOD_NS, unit="ns")
            for byte in [command] + values[:3]:
                await spi_transfer_byte(dut, byte, HALF_PERIOD_NS)
            for bit in range(7, 7-bits, -1):
                await spi_transfer_bit(dut, (values[3] >> bit) & 1, HALF_PERIOD_NS)
            await Timer(HALF_PERIOD_NS, unit="ns")
            dut.spi_cs_n.value = 1
            await Timer(HALF_PERIOD_NS, unit="ns")
            await spi_transaction(dut, [0x20])
            assert await spi_command(dut, 0x02) == 0
            await spi_transaction(dut, [command] + values)

    await spi_transaction(dut, [0x20])
    await wait_matrix_done(dut)
    assert await read_matrix(dut) == [19, 22, 43, 50]

    # An incomplete new load preserves the previous complete result and DONE.
    await spi_transaction(dut, [0x10, 99])
    await spi_transaction(dut, [0x21])
    assert await spi_command(dut, 0x02) == 2
    assert await read_matrix(dut) == [19, 22, 43, 50]


@cocotb.test()
async def test_spi_frame_boundaries(dut):
    await setup_dut(dut)
    # Extra bytes, even command-looking bytes, are ignored in the same frame.
    assert (await spi_transaction(dut, [0x01, 0, 0x20, 0x01])) == [0, 0x77, 0, 0]
    await spi_transaction(dut, [0x10, 1, 2, 3, 4, 0x11, 99])
    await spi_transaction(dut, [0x11, 5, 6, 7, 8, 0x20])
    assert await spi_command(dut, 0x02) == 0
    await spi_transaction(dut, [0xFF, 0x20])
    assert await spi_command(dut, 0x02) == 0
    await spi_transaction(dut, [0x20, 0x21])
    await wait_matrix_done(dut)
    assert await read_matrix(dut) == [19, 22, 43, 50]

    # Abort a read halfway through a result; the next read starts at C[0,0].
    await spi_transaction(dut, [0x30, 0, 0, 0])
    response = await spi_transaction(dut, [0x30] + [0]*18)
    assert response[1:17] == [19, 0, 0, 0, 22, 0, 0, 0, 43, 0, 0, 0, 50, 0, 0, 0]
    assert response[17:] == [0, 0]

    # Reset invalidates operands and results, and releases MISO during reset.
    dut.rst_n.value = 0
    await Timer(100, unit="us")
    assert int(dut.uo_out.value) == 0
    assert int(dut.uio_oe.value) == 0
    dut.rst_n.value = 1
    await Timer(100, unit="us")
    await spi_transaction(dut, [0x20])
    assert await spi_command(dut, 0x02) == 0
    assert await read_matrix(dut) == [0]*4
    assert await spi_command(dut, 0x01) == 0x77
