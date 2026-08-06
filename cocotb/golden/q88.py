"""Q8.8 and INT packing helpers matching AI_BYTE DATA_FORMAT_CONTRACT."""
from __future__ import annotations

Q88_ONE = 0x0100
Q88_MAX = 0x7FFF
Q88_MIN = -0x8000


def clamp_i16(x: int) -> int:
    if x > Q88_MAX:
        return Q88_MAX
    if x < Q88_MIN:
        return Q88_MIN
    return int(x)


def clamp_i8(x: int) -> int:
    if x > 127:
        return 127
    if x < -128:
        return -128
    return int(x)


def to_i8(b: int) -> int:
    b &= 0xFF
    return b - 256 if b >= 128 else b


def to_i16(w: int) -> int:
    w &= 0xFFFF
    return w - 0x10000 if w >= 0x8000 else w


def pack_q88_bytes(word: int) -> tuple[int, int]:
    """Return (lo, hi) bytes for a signed 16-bit Q8.8/INT16 word."""
    w = int(word) & 0xFFFF
    return w & 0xFF, (w >> 8) & 0xFF


def unpack_q88_bytes(lo: int, hi: int) -> int:
    return to_i16(((hi & 0xFF) << 8) | (lo & 0xFF))


def float_to_q88(x: float) -> int:
    return clamp_i16(int(round(x * 256.0)))


def q88_to_float(w: int) -> float:
    return float(to_i16(w)) / 256.0


def pack_float_q88(x: float) -> tuple[int, int]:
    return pack_q88_bytes(float_to_q88(x))


def scale_int16_to_int8(din: int, shift: int = 8) -> int:
    """Match scale_int16_to_int8.v: arithmetic >>> SHIFT then sat to INT8."""
    shifted = to_i16(din) >> shift  # Python >> is arithmetic for signed int
    return clamp_i8(shifted)


def alu_q88_add(a: int, b: int) -> int:
    return clamp_i16(to_i16(a) + to_i16(b))


def alu_q88_sub(a: int, b: int) -> int:
    return clamp_i16(to_i16(a) - to_i16(b))


def alu_q88_mul(a: int, b: int) -> int:
    """sat((A*B) >>> 8) in Q8.8 — floor divide matches HW signed product >>> FRAC."""
    prod = to_i16(a) * to_i16(b)
    return clamp_i16(prod >> 8)  # Python >> floors signed ints


def prom_int8_to_q88(b: int) -> int:
    """CNN INT8 → Q8.8: {int8, 8'h00}."""
    v = to_i8(b)
    return clamp_i16(v << 8)
