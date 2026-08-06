# INT16/Q8.8 Compute Blocks + block_wrapper

This design is a set of compute blocks — **ALU (Q8.8)**, **ReLU**,
**Pool**, and **Scale (→INT8)** — plus a **`block_wrapper`** top level
that composes them into fixed pipelines selected by mode-decode enable
bits, behind a single serial, handshake-driven interface.

All blocks share the same per-block handshake convention:

```
start : pulse 1 cycle to load inputs and begin
busy  : high while the block is processing
valid : pulses high for 1 cycle when the output is ready
```

Saturation (clamping to the type's min/max instead of wrapping) is
used everywhere overflow is possible, with an `overflow` flag reported
alongside the result.

---

## 1. `alu_q88` — Q8.8 fixed-point Add / Subtract / Multiply

**Ports:** `clk, rst, start, A, B, opcode[1:0] → busy, valid, result, overflow`
**Parameters:** `WIDTH=16, FRAC=8`

| `opcode` | Operation |
|---|---|
| `00` | `result = A + B` (plain integer add — same for Q8.8 or INT16) |
| `01` | `result = A - B` (plain integer subtract) |
| `10` | `result = sat( (A * B) >>> FRAC )` — Q8.8 × Q8.8 → Q8.8 |

ADD/SUB never touch the fractional point — a Q8.8 value's bit pattern
adds/subtracts exactly like any other signed integer of the same
width. This is what makes the same ALU usable both for standalone
Q8.8 math *and* for an FC bias add between an INT16 SA accumulator and
a sign-extended INT8 bias (see `block_wrapper` §5, Bias ADD mode).

### Area-optimized multiplier

Like its plain-integer sibling `alu_int16` (kept in this repo for
legacy use — see that file's header for the full area-optimization
rationale), `alu_q88` uses **one shared adder**, time-multiplexed
across every arithmetic step: direct ADD/SUB, sign/magnitude split for
MUL, the `WIDTH` shift-and-add accumulation steps of a sequential
multiplier, and the final sign correction. Only one physical adder is
ever instantiated. ADD/SUB stay at 2-cycle latency; MUL takes about
`WIDTH + 4` cycles.

### Rounding correctness (Q8.8-specific)

The spec's `>>>` is Verilog's *arithmetic* right shift, which floors
toward negative infinity for negative values — not the same as
truncating a magnitude toward zero and re-applying the sign. Naively
negating a truncated unsigned-magnitude product gives the wrong answer
whenever there's a nonzero fractional remainder on a negative result
(verified empirically: this mismatched Python's exact `>>` reference
on roughly half of all such cases in a sweep). `alu_q88` adds one
conditional extra cycle (`S_MUL_ROUND`, still using the same shared
adder) to apply a floor correction only when needed, including
correctly *saturating* — rather than wrapping — the one exact boundary
case where the correction would otherwise push the result one step
past `MIN_VAL`.

---

## 2. `relu_int16` — Rectified Linear Unit

**Ports:** `clk, rst, start, din → busy, valid, dout`

```
dout = max(0, din)
```

Pure sign-bit check. No saturation is possible, so there's no
`overflow` port. Fixed 2-cycle latency.

---

## 3. `pool_int16` — 2×2 Max / Average Pooling

**Ports:** `clk, rst, start, A, B, C, D, opcode → busy, valid, out`

| `opcode` | Operation |
|---|---|
| `0` (MAX) | `out = max(A, B, C, D)` |
| `1` (AVG) | `out = (A + B + C + D) >> 2` (arithmetic/floor shift) |

One module, sharing hardware between the two modes via the opcode.
Average pooling rounds toward negative infinity, not toward zero.
Fixed 2-cycle latency.

---

## 4. `scale_int16_to_int8` — Requantize → INT8

**Ports:** `clk, rst, start, din → busy, valid, dout, overflow`
**Parameters:** `WIDTH_IN=16, WIDTH_OUT=8, SHIFT=8`

```
dout = saturate_to_int8( din >>> SHIFT )
```

The same requantization operation used at the end of a quantized
inference layer. With the default `SHIFT=8`, the full INT16 range
always maps exactly onto INT8 with `overflow` never firing (confirmed
in simulation, not just claimed). Fixed 2-cycle latency.

---

## 5. `block_wrapper` — mode-decoded top level

`block_wrapper` instantiates one each of `alu_q88`, `relu_int16`,
`pool_int16`, and `scale_int16_to_int8`, and composes them per
transaction according to three independent enable bits sampled with
the first input word: `bias_en`, `relu_en`, `pool_en`.

```
                 ┌──────────────┐
        ┌───────►│   alu_q88    │──┐
        │        └──────────────┘  │
in_data │        ┌──────────────┐  │      ┌──────────────────────┐
in_valid├───────►│  relu_int16  │──┼─────►│ scale_int16_to_int8   │──► out_data8 (if scale_en)
in_ready│        └──────────────┘  │      │  (only if scale_en)   │
        │        ┌──────────────┐  │      └──────────────────────┘
        └───────►│  pool_int16  │──┘             │
                 └──────────────┘                 ▼ (bypass if !scale_en)
                                                out_data16 / out_data8
                                                out_is_int8, out_valid,
                                                out_ready, out_overflow
```

### Ports

| Port | Dir | Width | Meaning |
|---|---|---|---|
| `clk` / `rst` | in | 1 | clock / synchronous active-high reset |
| `bias_en` | in | 1 | enable Bias ADD stage (FC post-path, before ReLU) |
| `relu_en` | in | 1 | enable ReLU stage |
| `pool_en` | in | 1 | enable 2×2 Pool stage (forced off whenever `bias_en=1`) |
| `alu_opcode` | in | 2 | `00`=ADD `01`=SUB `10`=MUL — standalone ALU mode only |
| `pool_op` | in | 1 | `0`=MAX `1`=AVG |
| `scale_en` | in | 1 | `1` = requantize the final result to INT8; `0` = pass INT16/Q8.8 through |
| `in_data` | in | 16 (signed) | one operand word |
| `in_valid` / `in_ready` | in / out | 1 | input handshake |
| `out_data16` | out | 16 (signed) | raw result — valid when `out_is_int8=0` |
| `out_data8` | out | 8 (signed) | requantized result — valid when `out_is_int8=1` |
| `out_is_int8` | out | 1 | which output bus is meaningful |
| `out_valid` / `out_ready` | out / in | 1 | output handshake |
| `out_overflow` | out | 1 | saturation occurred anywhere in the chain |
| `busy` | out | 1 | an operation is in flight |

There is **no top-level `start`**: the wrapper is idle until it has
accepted however many words its latched mode needs, then begins
automatically. `bias_en`/`relu_en`/`pool_en`/`alu_opcode`/`pool_op`/
`scale_en` only need to be correct on the **first** word of an
operation.

### Mode table

| `bias_en` | `relu_en` | `pool_en` | Mode | Words | Internal flow |
|---|---|---|---|---|---|
| 0 | 0 | 0 | ALU | 2 (A, B) | `alu_q88(alu_opcode)` → [scale] |
| 0 | 1 | 0 | ReLU only | 1 | ReLU → [scale] |
| 0 | 0 | 1 | Pool only | 4 (A,B,C,D) | `Pool(pool_op)` → [scale] |
| 0 | 1 | 1 | ReLU→Pool | 4 (A,B,C,D) | ReLU×4 → `Pool(pool_op)` → [scale] |
| 1 | 0 | 0 | Bias ADD | 2 (y, bias_ext) | `alu_q88` ADD → [scale] |
| 1 | 1 | 0 | FC Bias→ReLU | 2 (y, bias_ext) | `alu_q88` ADD → ReLU → [scale] |
| 1 | x | 1 | *(illegal combo)* | — | `pool_en` is **forced off** whenever `bias_en=1` |

Rules enforced by the RTL:
- Standalone ALU (using `alu_opcode`) only runs when
  `bias_en=relu_en=pool_en=0`.
- Whenever `bias_en=1`, the ALU always runs **ADD** (`alu_opcode` is
  ignored), Pool never runs, and ReLU is optional.
- Whenever `bias_en=0` and (`relu_en` or `pool_en`) is set, the ALU
  never runs standalone — only the ReLU/Pool path.
- The `bias_en=1, pool_en=1` combo (spec'd illegal) is handled
  deterministically: `pool_en` is ANDed with `~bias_en` at the moment
  of latching, so it behaves exactly like plain Bias ADD / FC
  Bias→ReLU regardless of what `pool_en` was driven to.

### Handshake protocol

Both directions use the standard "transfer happens when valid and
ready are both high at a clock edge" rule — one word (or one result)
per handshake:

**Input:** drive `in_data` (+ mode bits on the first word), hold
`in_valid=1`, wait for `in_ready=1`; repeat for however many words the
mode needs.

**Output:** once the pipeline finishes, `out_valid` goes high with the
result on `out_data16` or `out_data8` per `out_is_int8`; held high
until `out_ready` is asserted.

### Internal flow

1. **Load** — accept words until the mode's word count is reached,
   latching all mode/opcode bits from the first word.
2. **Dispatch** — based on the latched `bias_en`/`relu_en`/`pool_en`,
   decide which of the 6 legal flows above to run.
3. **ALU / ReLU / Pool** — run the selected block(s). ReLU is reused
   for three different roles depending on mode: a single call
   (ReLU-only), a 4-iteration loop over `operand_reg[0..3]` writing
   each result back in place (ReLU→Pool, feeding Pool afterward), or a
   single call fed from the ALU's sum register instead of an operand
   word (FC Bias→ReLU).
4. **Scale (optional)** — if `scale_en` was set, requantize to INT8.
5. **Hold** — present the result until the consumer accepts it, then
   return to step 1.

### Overflow flag

`out_overflow` is the OR of every stage's own overflow: the ALU's flag
(ReLU/Pool never overflow) when `scale_en=0`, or ALU-overflow **OR**
Scale-overflow when `scale_en=1` — one flag covers the whole chain
regardless of which pipeline ran.

### Verified behavior

`test_block_wrapper.py` exercises all 6 legal modes directly (with and
without Scale engaged), the illegal bias+pool combo, saturation
propagation, and back-to-back transitions between differently-shaped
modes (confirming no leftover operand/loop state leaks between them).
Two dedicated tests introspect the internal `valid` signals of
`relu_int16` and `pool_int16` to confirm in hardware — not just from
the final answer — that ALU-only operations never touch ReLU/Pool, and
that Pool never activates whenever `bias_en=1` even if `pool_en` was
asserted alongside it. A further 80 randomized operations sweep all 6
modes together.

---

## Summary table

| Block | Inputs | Output | Cycles (typical) | Notes |
|---|---|---|---|---|
| `alu_q88` | A, B, opcode | result, overflow | 2 (ADD/SUB), ~20–21 (MUL) | shared adder; sequential multiplier with Q8.8 rescale + floor-rounding correction |
| `alu_int16` | A, B, opcode | result, overflow | 2 (ADD/SUB), ~19 (MUL) | plain-integer sibling, kept for legacy use |
| `relu_int16` | din | dout | 2 | pure sign-bit check |
| `pool_int16` | A,B,C,D, opcode | out | 2 | one module, shared hardware for MAX/AVG |
| `scale_int16_to_int8` | din | dout, overflow | 2 | shift + saturate requantizer |
| `block_wrapper` | serial in_data stream | serial out_data16/out_data8 stream | varies by mode + optional Scale | mode-decoded pipeline composition, fully handshake-driven I/O |

## Verified together

Every block above (and `block_wrapper` composing them) has been
synthesized and simulated with real Icarus Verilog + cocotb runs in
this environment — not just reviewed by eye — including full directed
edge cases, saturation and rounding boundaries, and hundreds of
randomized test vectors per block. Current total: **45 tests across
all suites, all passing**, plus a clean Yosys synthesis of the full
`block_wrapper` design with no warnings, errors, or inferred latches.
