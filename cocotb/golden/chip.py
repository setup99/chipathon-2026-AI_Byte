"""
AI_BYTE whole-chip golden model (control_path_v2 programming model).

Mirrors hardware:
  MMIF decode (addr 0x6 = BUFFER_DATA)
  RF → START pulse runs one opcode through buffers + engines
  Result lands in Result SRAM (and STATUS/IRQ)

Exact paths (bit-faithful integer math):
  • ALU ADD/SUB/MUL Q8.8
  • SA 4×4 INT8 GEMM → INT16
  • FC post: bias? → ReLU? → scale→INT8
  • CONV post: ReLU? → 2×2 pool? → scale→INT8
  • scale_int16_to_int8 (>>>8 + sat)

Approximate paths (IEEE float stand-in for Mitchell EML tile):
  • SQRT, RECIP, SIGMOID, TANH, Softmax, Microprog FEEDBACK (eml tile)
  Use compare_result(..., tol=...) when scoring HW vs golden for EML.

Not cycle-accurate; models architectural Result / STATUS only.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from .q88 import (
    Q88_ONE,
    alu_q88_add,
    alu_q88_mul,
    alu_q88_sub,
    clamp_i16,
    float_to_q88,
    pack_q88_bytes,
    prom_int8_to_q88,
    q88_to_float,
    scale_int16_to_int8,
    to_i8,
    to_i16,
    unpack_q88_bytes,
)

# Register map (matches reg_file.v)
ADDR_CONTROL = 0x0
ADDR_STATUS = 0x1
ADDR_OPCODE = 0x2
ADDR_CONFIG = 0x3
ADDR_BUF_SEL = 0x4
ADDR_BUF_ADDR = 0x5
ADDR_BUF_DATA = 0x6
ADDR_FEATURE_ROWS = 0x7
ADDR_FEATURE_COLS = 0x8
ADDR_SOFTMAX_N = 0xB

BUF_ACT, BUF_WT, BUF_RES = 0, 1, 2

# Opcodes
OP_CONV = 0x0
OP_FC = 0x1
OP_ADD = 0x2
OP_SUB = 0x3
OP_MUL = 0x4
OP_SIGMOID = 0x6
OP_TANH = 0x7
OP_RECIP = 0x8
OP_SQRT = 0x9
OP_SOFTMAX = 0xA
OP_MICRO = 0xB

# CONFIG bits
CFG_RELU = 1 << 0
CFG_POOL = 1 << 1
CFG_POOL_AVG = 1 << 2
CFG_BIAS = 1 << 3
CFG_SCALE = 1 << 4
CFG_EML_SCALE = 1 << 5


@dataclass
class ExecResult:
    ok: bool
    error: bool
    opcode: int
    message: str = ""
    # Result buffer snapshot after run (full depth)
    result: List[int] = field(default_factory=list)
    # Optional logical words for scoring helpers
    result_words: List[int] = field(default_factory=list)


class AiByteGolden:
    """Byte-level chip model: Act/Wt/Res + RF + one START executes one op."""

    def __init__(
        self,
        act_depth: int = 64,
        wt_depth: int = 16,
        res_depth: int = 16,
        tile: int = 4,
        cnn_act_n: Optional[int] = None,
        softmax_max_n: int = 8,
        enable_sa: bool = True,
        enable_microprog: bool = True,
        enable_softmax: bool = True,
    ):
        self.act_depth = act_depth
        self.wt_depth = wt_depth
        self.res_depth = res_depth
        self.tile = tile
        self.tile_bytes = tile * tile
        self.cnn_act_n = cnn_act_n if cnn_act_n is not None else self.tile_bytes
        self.softmax_max_n = softmax_max_n
        self.enable_sa = enable_sa
        self.enable_microprog = enable_microprog
        self.enable_softmax = enable_softmax

        self.act = [0] * act_depth
        self.wt = [0] * wt_depth
        self.res = [0] * res_depth

        self.opcode = 0
        self.config = 0
        self.feature_rows = 0
        self.feature_cols = 1
        self.softmax_n = 2
        self.buf_sel = 0
        self.buf_addr = 0

        self.status_error = 0
        self.status_done = 0
        self.status_busy = 0
        self.last_exec: Optional[ExecResult] = None

    # ------------------------------------------------------------------
    # Memory / RF access (same decode as MMIF)
    # ------------------------------------------------------------------
    def reset(self) -> None:
        self.act = [0] * self.act_depth
        self.wt = [0] * self.wt_depth
        self.res = [0] * self.res_depth
        self.opcode = 0
        self.config = 0
        self.feature_rows = 0
        self.feature_cols = 1
        self.softmax_n = 2
        self.buf_sel = 0
        self.buf_addr = 0
        self.status_error = 0
        self.status_done = 0
        self.status_busy = 0
        self.last_exec = None

    def _buf(self, sel: int) -> List[int]:
        if sel == BUF_ACT:
            return self.act
        if sel == BUF_WT:
            return self.wt
        if sel == BUF_RES:
            return self.res
        raise ValueError(f"bad buffer select {sel}")

    def write_buf(self, sel: int, addr: int, data: int) -> None:
        mem = self._buf(sel)
        if 0 <= addr < len(mem):
            mem[addr] = data & 0xFF

    def read_buf(self, sel: int, addr: int) -> int:
        mem = self._buf(sel)
        if 0 <= addr < len(mem):
            return mem[addr] & 0xFF
        return 0

    def write_reg(self, addr: int, data: int) -> None:
        addr &= 0xF
        data &= 0xFF
        if addr == ADDR_CONTROL:
            if data & 0x1:  # START
                self.execute()
            if data & 0x4:  # IRQ_CLEAR
                self.status_done = 0
                self.status_error = 0
            if data & 0x2:  # SOFT_RESET
                self.status_done = 0
                self.status_error = 0
                self.status_busy = 0
        elif addr == ADDR_OPCODE:
            self.opcode = data & 0xF
        elif addr == ADDR_CONFIG:
            self.config = data
        elif addr == ADDR_BUF_SEL:
            self.buf_sel = data & 0x3
        elif addr == ADDR_BUF_ADDR:
            self.buf_addr = data
        elif addr == ADDR_BUF_DATA:
            self.write_buf(self.buf_sel, self.buf_addr, data)
        elif addr == ADDR_FEATURE_ROWS:
            self.feature_rows = data
        elif addr == ADDR_FEATURE_COLS:
            self.feature_cols = max(1, data)
        elif addr == ADDR_SOFTMAX_N:
            self.softmax_n = data & 0xF

    def read_reg(self, addr: int) -> int:
        addr &= 0xF
        if addr == ADDR_STATUS:
            return (
                ((self.status_busy & 1) << 2)
                | ((self.status_done & 1) << 1)
                | (self.status_error & 1)
            )
        if addr == ADDR_OPCODE:
            return self.opcode & 0xF
        if addr == ADDR_CONFIG:
            return self.config & 0xFF
        if addr == ADDR_BUF_SEL:
            return self.buf_sel
        if addr == ADDR_BUF_ADDR:
            return self.buf_addr & 0xFF
        if addr == ADDR_BUF_DATA:
            return self.read_buf(self.buf_sel, self.buf_addr)
        if addr == ADDR_FEATURE_ROWS:
            return self.feature_rows & 0xFF
        if addr == ADDR_FEATURE_COLS:
            return self.feature_cols & 0xFF
        if addr == ADDR_SOFTMAX_N:
            return self.softmax_n & 0xFF
        return 0

    # MMIF pin helpers (addr==6 → buf data using BUFFER_SELECT/ADDR)
    def mmif_write(self, addr: int, data: int) -> None:
        self.write_reg(addr, data)

    def mmif_read(self, addr: int) -> int:
        return self.read_reg(addr)

    @property
    def irq(self) -> int:
        return 1 if (self.status_done or self.status_error) else 0

    def cfg(self, bit: int) -> bool:
        return bool(self.config & bit)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    def execute(self) -> ExecResult:
        op = self.opcode & 0xF
        illegal = (
            op == 0x5
            or op >= 0xC
            or (op in (OP_CONV, OP_FC) and not self.enable_sa)
            or (op == OP_SOFTMAX and not self.enable_softmax)
            or (op == OP_MICRO and not self.enable_microprog)
        )
        sm_bad = op == OP_SOFTMAX and not (2 <= self.softmax_n <= self.softmax_max_n)

        if illegal or sm_bad:
            self.status_error = 1
            self.status_done = 0
            self.status_busy = 0
            er = ExecResult(ok=False, error=True, opcode=op, message="decode error")
            self.last_exec = er
            return er

        # Clear previous result region used by ops (full res for simplicity)
        self.res = [0] * self.res_depth
        words: List[int] = []

        try:
            if op == OP_CONV:
                words = self._run_conv()
            elif op == OP_FC:
                words = self._run_fc()
            elif op in (OP_ADD, OP_SUB, OP_MUL):
                words = self._run_alu(op)
            elif op in (OP_SIGMOID, OP_TANH):
                words = self._run_eml_vector(op)
            elif op in (OP_RECIP, OP_SQRT):
                words = self._run_eml_scalar(op)
            elif op == OP_SOFTMAX:
                words = self._run_softmax()
            elif op == OP_MICRO:
                words = self._run_microprog()
            else:
                raise ValueError(f"unhandled opcode {op:#x}")
        except Exception as exc:  # noqa: BLE001 — map to ERROR like HW fault
            self.status_error = 1
            self.status_done = 0
            er = ExecResult(ok=False, error=True, opcode=op, message=str(exc))
            self.last_exec = er
            return er

        self.status_error = 0
        self.status_done = 1
        self.status_busy = 0
        er = ExecResult(
            ok=True,
            error=False,
            opcode=op,
            result=list(self.res),
            result_words=words,
        )
        self.last_exec = er
        return er

    # ------------------------------------------------------------------
    # SA + post
    # ------------------------------------------------------------------
    def _load_w_matrix(self) -> List[List[int]]:
        """W[r][c] from Weight[r*T+c] INT8 (matches BC sa_w_row/col packing)."""
        T = self.tile
        W = [[0] * T for _ in range(T)]
        for r in range(T):
            for c in range(T):
                W[r][c] = to_i8(self.wt[r * T + c])
        return W

    def _load_x_matrix(self) -> List[List[int]]:
        """X[r][c] from Act[r*T+c] INT8."""
        T = self.tile
        X = [[0] * T for _ in range(T)]
        for r in range(T):
            for c in range(T):
                X[r][c] = to_i8(self.act[r * T + c])
        return X

    def _gemm_int8(self) -> List[int]:
        """Y[r][c] = sum_k W[r][k]*X[k][c] → flat row-major INT16 list len T²."""
        T = self.tile
        Wm = self._load_w_matrix()
        Xm = self._load_x_matrix()
        yflat: List[int] = []
        for r in range(T):
            for c in range(T):
                acc = 0
                for k in range(T):
                    acc += Wm[r][k] * Xm[k][c]
                yflat.append(clamp_i16(acc))
        return yflat

    def _run_fc(self) -> List[int]:
        y = self._gemm_int8()
        words: List[int] = []
        for i in range(self.tile_bytes):
            v = y[i]
            if self.cfg(CFG_BIAS):
                v = clamp_i16(v + to_i8(self.act[self.tile_bytes + i]))
            if self.cfg(CFG_RELU):
                v = max(0, v)
            # HW forces CNN FC → INT8 via scale path
            out = scale_int16_to_int8(v)
            self.res[i] = out & 0xFF
            words.append(out)
        return words

    @staticmethod
    def _win_coords(w: int, k: int) -> int:
        """Match buffer_ctrl win_coords: 2×2 windows over 4×4."""
        r0 = (w & 2)  # 0 or 2 (bit1 << 1)
        c0 = (w & 1) << 1
        if k == 0:
            return (r0 << 2) + c0
        if k == 1:
            return (r0 << 2) + c0 + 1
        if k == 2:
            return ((r0 + 1) << 2) + c0
        return ((r0 + 1) << 2) + c0 + 1

    def _run_conv(self) -> List[int]:
        y = self._gemm_int8()
        words: List[int] = []
        for win in range(4):
            vals = [y[self._win_coords(win, k)] for k in range(4)]
            if self.cfg(CFG_RELU):
                vals = [max(0, v) for v in vals]
            if self.cfg(CFG_POOL):
                if self.cfg(CFG_POOL_AVG):
                    # sum >>> 2 (matches pool_int16)
                    s = sum(vals)
                    v = s >> 2
                else:
                    v = max(vals)
            else:
                # without pool, HW still streams 4 into wrapper; take first after ReLU
                v = vals[0]
            out = scale_int16_to_int8(v)
            self.res[win] = out & 0xFF
            words.append(out)
        return words

    # ------------------------------------------------------------------
    # ALU
    # ------------------------------------------------------------------
    def _run_alu(self, op: int) -> List[int]:
        n = self.feature_cols
        words: List[int] = []
        for i in range(n):
            a = unpack_q88_bytes(self.act[2 * i], self.act[2 * i + 1])
            b = unpack_q88_bytes(self.wt[2 * i], self.wt[2 * i + 1])
            if op == OP_ADD:
                r = alu_q88_add(a, b)
            elif op == OP_SUB:
                r = alu_q88_sub(a, b)
            else:
                r = alu_q88_mul(a, b)
            if self.cfg(CFG_SCALE):
                out8 = scale_int16_to_int8(r)
                self.res[i] = out8 & 0xFF
                words.append(out8)
            else:
                lo, hi = pack_q88_bytes(r)
                self.res[2 * i] = lo
                self.res[2 * i + 1] = hi
                words.append(r)
        return words

    # ------------------------------------------------------------------
    # EML (float approx of tile / ideal math)
    # ------------------------------------------------------------------
    @staticmethod
    def eml_tile(x_q88: int, y_q88: int) -> int:
        """Idealised float model of eml_tile_q88: exp(x) - ln(y)."""
        x = q88_to_float(x_q88)
        y_u = to_i16(y_q88) & 0xFFFF  # treat as unsigned magnitude for ln
        y = max(y_u / 256.0, 1e-12)
        try:
            out = math.exp(x) - math.log(y)
        except (ValueError, OverflowError):
            out = 127.0 if x >= 0 else -128.0
        return float_to_q88(out)

    def _run_eml_scalar(self, op: int) -> List[int]:
        n = self.feature_cols
        words: List[int] = []
        for i in range(n):
            x = unpack_q88_bytes(self.act[2 * i], self.act[2 * i + 1])
            xf = max(q88_to_float(x), 1e-12)
            if op == OP_SQRT:
                r = float_to_q88(math.sqrt(xf))
            else:  # RECIP
                r = float_to_q88(1.0 / xf)
            if self.cfg(CFG_EML_SCALE):
                o8 = scale_int16_to_int8(r)
                self.res[i] = o8 & 0xFF
                words.append(o8)
            else:
                lo, hi = pack_q88_bytes(r)
                self.res[2 * i] = lo
                self.res[2 * i + 1] = hi
                words.append(r)
        return words

    def _run_eml_vector(self, op: int) -> List[int]:
        """SIGMOID/TANH on CNN_ACT_N INT8 → always INT8 Result (BC always scales)."""
        words: List[int] = []
        for i in range(self.cnn_act_n):
            x = prom_int8_to_q88(self.act[i])
            xf = q88_to_float(x)
            if op == OP_SIGMOID:
                # σ(x) = 1/(1+e^-x)
                try:
                    s = 1.0 / (1.0 + math.exp(-xf))
                except OverflowError:
                    s = 0.0 if xf < 0 else 1.0
                r = float_to_q88(s)
            else:
                # tanh
                try:
                    t = math.tanh(xf)
                except OverflowError:
                    t = -1.0 if xf < 0 else 1.0
                r = float_to_q88(t)
            o8 = scale_int16_to_int8(r)
            self.res[i] = o8 & 0xFF
            words.append(o8)
        return words

    def _run_softmax(self) -> List[int]:
        n = self.softmax_n
        xs = [prom_int8_to_q88(self.act[i]) for i in range(n)]
        xfs = [q88_to_float(x) for x in xs]
        m = max(xfs)
        exps = [math.exp(x - m) for x in xfs]
        s = sum(exps) or 1.0
        words: List[int] = []
        for i, e in enumerate(exps):
            r = float_to_q88(e / s)
            if self.cfg(CFG_EML_SCALE):
                o8 = scale_int16_to_int8(r)
                self.res[i] = o8 & 0xFF
                words.append(o8)
            else:
                lo, hi = pack_q88_bytes(r)
                self.res[2 * i] = lo
                self.res[2 * i + 1] = hi
                words.append(r)
        return words

    def _run_microprog(self) -> List[int]:
        """FEEDBACK microprog: Act[i] instr, Weight const Q8.8 leaves.

        instr: [7]=sel_x [6]=sel_y [5:3]=xsrc [2:0]=ysrc
        tile ≈ eml_tile; fb_reg starts at 1.0
        Final Result[0:1] = last Q8.8 word.
        """
        n = self.feature_cols
        fb = Q88_ONE
        out = Q88_ONE
        for i in range(n):
            instr = self.act[i] & 0xFF
            xsrc = (instr >> 3) & 0x7
            ysrc = instr & 0x7
            sel_x = (instr >> 7) & 1
            sel_y = (instr >> 6) & 1
            cx = unpack_q88_bytes(self.wt[2 * xsrc], self.wt[2 * xsrc + 1])
            cy = unpack_q88_bytes(self.wt[2 * ysrc], self.wt[2 * ysrc + 1])
            # y path for tile is unsigned Q8.8 bus
            cy_u = cy & 0xFFFF
            x_in = fb if sel_x else cx
            y_in = fb if sel_y else cy_u
            out = self.eml_tile(x_in, y_in)
            fb = out
        lo, hi = pack_q88_bytes(out)
        self.res[0] = lo
        self.res[1] = hi
        return [out]

    # ------------------------------------------------------------------
    # Helpers for loading / comparing
    # ------------------------------------------------------------------
    def load_q88_pair(self, sel: int, index: int, value: int) -> None:
        lo, hi = pack_q88_bytes(value)
        self.write_buf(sel, 2 * index, lo)
        self.write_buf(sel, 2 * index + 1, hi)

    def load_q88_float(self, sel: int, index: int, x: float) -> None:
        self.load_q88_pair(sel, index, float_to_q88(x))

    def result_q88(self, index: int = 0) -> int:
        return unpack_q88_bytes(self.res[2 * index], self.res[2 * index + 1])

    def result_bytes(self, n: int) -> List[int]:
        return [self.res[i] & 0xFF for i in range(n)]


def compare_bytes(
    hw: Sequence[int], golden: Sequence[int], tol: int = 0
) -> Tuple[bool, str]:
    if len(hw) != len(golden):
        return False, f"len hw={len(hw)} gold={len(golden)}"
    max_err = 0
    worst_i = 0
    for i, (a, b) in enumerate(zip(hw, golden)):
        a8 = to_i8(a)
        b8 = to_i8(b)
        e = abs(a8 - b8)
        if e > max_err:
            max_err = e
            worst_i = i
        if e > tol:
            return False, f"idx {i}: hw={a8} gold={b8} err={e} tol={tol}"
    return True, f"ok max_err={max_err} (idx {worst_i}) tol={tol}"


def compare_q88_words(
    hw_words: Sequence[int], golden_words: Sequence[int], tol: int = 0
) -> Tuple[bool, str]:
    if len(hw_words) != len(golden_words):
        return False, f"len hw={len(hw_words)} gold={len(golden_words)}"
    max_err = 0
    worst_i = 0
    for i, (a, b) in enumerate(zip(hw_words, golden_words)):
        e = abs(to_i16(a) - to_i16(b))
        if e > max_err:
            max_err = e
            worst_i = i
        if e > tol:
            return (
                False,
                f"idx {i}: hw={to_i16(a):#x} gold={to_i16(b):#x} err={e} ({e/256:.4f}) tol={tol}",
            )
    return (
        True,
        f"ok max_err={max_err} ({max_err/256:.4f} Q8.8) idx={worst_i} tol={tol}",
    )
