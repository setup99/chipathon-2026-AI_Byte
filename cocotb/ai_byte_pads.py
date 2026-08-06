"""AI_BYTE host helpers over workshop bidir pads on chip_top."""
from cocotb.triggers import RisingEdge, Timer
from cocotb.types import LogicArray

# Pad map (matches src/chip_core.sv)
# bidir[3:0]=addr [11:4]=data [12]=we [13]=re [14]=irq
# [15]=done [16]=error [17:19]=debug


def host_la(addr=0, data=0, we=0, re=0):
    """
    Host drive with Z on chip-driven pins (irq/done/error/debug and data
    during read so OE can pull them).
    """
    bits = ["z"] * 20
    for i in range(4):
        bits[i] = "1" if (addr >> i) & 1 else "0"
    drive_data = not (re and not we)
    if drive_data:
        for i in range(8):
            bits[4 + i] = "1" if (data >> i) & 1 else "0"
    bits[12] = "1" if we else "0"
    bits[13] = "1" if re else "0"
    # pins 14..19 left as z
    return LogicArray("".join(reversed(bits)))


def _bit(dut, idx: int) -> int:
    """Read one bidir bit as 0/1; treat X/Z as 0."""
    try:
        v = dut.bidir_PAD[idx].value
        s = str(v).lower()
        if s in ("1", "true"):
            return 1
        if s in ("0", "false"):
            return 0
        # integer-like
        try:
            return int(v) & 1
        except Exception:
            return 0
    except Exception:
        # fallback: binstr
        try:
            bs = dut.bidir_PAD.value.binstr
            # binstr MSB left = high index
            ch = bs[len(bs) - 1 - idx]
            return 1 if ch == "1" else 0
        except Exception:
            return 0


def irq_pad(dut) -> int:
    return _bit(dut, 14)


def sample_data(dut) -> int:
    v = 0
    for i in range(8):
        v |= _bit(dut, 4 + i) << i
    return v


async def pin_write(dut, addr, data):
    await RisingEdge(dut.clk_PAD)
    dut.bidir_PAD.value = host_la(addr, data, we=1, re=0)
    await RisingEdge(dut.clk_PAD)
    dut.bidir_PAD.value = host_la(0, 0, we=0, re=0)


async def pin_read(dut, addr):
    await RisingEdge(dut.clk_PAD)
    dut.bidir_PAD.value = host_la(addr, 0, we=0, re=1)
    await Timer(1, unit="ns")
    await RisingEdge(dut.clk_PAD)
    await Timer(1, unit="ns")
    val = sample_data(dut)
    dut.bidir_PAD.value = host_la(0, 0, we=0, re=0)
    await RisingEdge(dut.clk_PAD)
    return val


async def buf_write(dut, sel, addr, data):
    await pin_write(dut, 0x4, sel)
    await pin_write(dut, 0x5, addr)
    await pin_write(dut, 0x6, data)


async def buf_read(dut, sel, addr):
    await pin_write(dut, 0x4, sel)
    await pin_write(dut, 0x5, addr)
    await RisingEdge(dut.clk_PAD)
    # BUFFER_DATA read with sync-SRAM latency (same as bare MMIF TB)
    await RisingEdge(dut.clk_PAD)
    dut.bidir_PAD.value = host_la(0x6, 0, we=0, re=1)
    await RisingEdge(dut.clk_PAD)
    await RisingEdge(dut.clk_PAD)
    await Timer(1, unit="ns")
    val = sample_data(dut)
    dut.bidir_PAD.value = host_la(0, 0, we=0, re=0)
    return val


async def wait_irq(dut, timeout=80000):
    for _ in range(timeout):
        await RisingEdge(dut.clk_PAD)
        if irq_pad(dut):
            return
    raise AssertionError("timeout waiting for IRQ on bidir[14]")
