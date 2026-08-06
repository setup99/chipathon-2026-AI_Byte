# EML Q8.8 — Full Architecture and Mathematics

**Format:** Q8.8 fixed point — 16-bit signed, 8 integer bits, 8 fractional bits
**Range:** −128.0 to +127.996 · **Resolution:** 1/256 ≈ 0.0039
**Verification:** Icarus Verilog 12.0 + cocotb 2.0.1, every number below reproduced directly from simulation, not derived on paper.

---

## 1. The EML core: one operator underneath everything

Every block in this library — sigmoid, tanh, reciprocal, sqrt, softmax, the feedback cell, the wrapper — is built from a single primitive:

```
eml(x, y) = exp(x) − ln(y)
```

This is the same operator described in the paper *"All elementary functions from a single operator"* (arXiv:2603.21852): just as NAND is universal for Boolean logic, `eml(x,y)` is universal for elementary functions — every function in this library is `eml` composed with itself and a handful of free digital operations (add, subtract, shift, negate).

```verilog
module eml_tile_q88 #(parameter W=16, F=8)(
    input  wire signed [W-1:0] x,   // signed Q8.8
    input  wire        [W-1:0] y,   // unsigned Q8.8, y > 0
    output wire signed [W-1:0] out,
    output wire                 ovf
);
```

| Port | Direction | Width | Description |
|---|---|---|---|
| `x` | in | 16 (signed) | Exponent argument |
| `y` | in | 16 (unsigned) | Log argument, must be `> 0` |
| `out` | out | 16 (signed) | `exp(x) − ln(y)`, saturating |
| `ovf` | out | 1 | High if any internal stage saturated |

`eml_tile_q88` is **purely combinational** — no clock, no state. Every FSM in this library works by presenting a new `(x,y)` each cycle and reading `out` back one cycle later; the "latency" of every function is really just "how many EML calls does the math need, plus a few free digital steps."

### 1.1 Why this needs two approximated primitives, not two exact ones

`exp(x)` and `ln(y)` are both transcendental — no exact fixed-point circuit computes them in bounded time. This library uses **Mitchell's algorithm**, a classic bit-level approximation for both `log2` and `2^x`, corrected with a cheap shift-add term to bring worst-case error down from Mitchell's raw ~7% to under 1%.

### 1.2 The correction, and why it doesn't depend on word width

Mitchell's approximation error has the shape `f·(1−f)` where `f` is the fractional part of the operand — this is a property of `f ∈ [0,1)` as a continuous quantity, not of how many bits represent it. A numerical sweep over all possible `f` (256 discrete steps at F=8, versus 16.7 million at F=24 in the parent Q8.24 design) found the **same optimal correction coefficient, 11/32**, at both word widths — confirming the correction is a property of the curve, not the format. This meant the whole architecture ported from Q8.24 to Q8.8 with only width/constant changes, no re-derivation.

The correction is implemented as pure shift-add (`prod·8 + prod·2 + prod = prod·11`), never a real multiplier:

```verilog
prod = f_raw * inv_f;                 // one F×F multiply (the only multiply here)
p11  = (prod<<3) + (prod<<1) + prod;  // ×11 via shift-add
delta = p11 >> (F+5);                 // scale back down
```

### 1.3 The bug found and fixed in this core (affects every block below)

While stress-testing the softmax max-trick with extreme logits, `eml_tile_q88`'s `x·log2(e)` and `log2(y)·ln(2)` scaling multiplies were found to truncate with a **raw bit-slice instead of saturating**. For `|x| > 128/log2(e) ≈ 88.7`, the true scaled value exceeds Q8.8's ±128 range, and the untreated slice wrapped sign (`x=−100.0` produced `exp(−100)=+127.996` instead of `~0`). Fixed by checking the 9 redundant top bits of the 32-bit product form a valid sign extension (the same pattern as the module's own final `diff[W]!=diff[W-1]` saturation check, just widened) and saturating on the true sign if not. Verified with **zero regressions** across every downstream block (12/12 feedback_cell, 47/47 full wrapper, 1012/1012 exact matches in a dedicated bit-exact crosscheck against a similarly-fixed Python model).

---

## 2. `mitchell_log2_q88` — log2(x)

```verilog
module mitchell_log2_q88 #(parameter W=16, F=8)(
    input  wire [W-1:0] x,     // unsigned Q8.8, x > 0
    output wire signed [W-1:0] y,  // log2(x), signed Q8.8
    output wire ovf
);
```

| Port | Direction | Width | Description |
|---|---|---|---|
| `x` | in | 16 (unsigned) | Argument, `x > 0` |
| `y` | out | 16 (signed) | `log2(x)` |
| `ovf` | out | 1 | High iff `x == 0` (undefined input) |

**Architecture:** leading-bit detect (LZD) finds the MSB position → exponent falls out directly (`e_fp = (msb_pos−F)<<F`) → mantissa normalized and the fractional part extracted (`f_raw`) → shift-add correction network → `y = e_fp + f_corr`.

**Test result:** max absolute error **0.0081**, identical to the parent Q8.24 design's error at the same correction coefficient — confirming the word-width independence claim in §1.2 empirically, not just by derivation.

**Conclusion:** the correctness of every other block in this library rests on this one module being accurate and its only failure mode (`x=0`) being cleanly flagged — both hold.

---

## 3. `mitchell_exp2_q88` — 2^x

```verilog
module mitchell_exp2_q88 #(parameter W=16, F=8)(
    input  wire signed [W-1:0] x,   // signed Q8.8
    output wire [W-1:0] y           // 2^x, unsigned Q8.8
);
```

| Port | Direction | Width | Description |
|---|---|---|---|
| `x` | in | 16 (signed) | Exponent |
| `y` | out | 16 (unsigned) | `2^x`, saturates to `0` or max at the format's limits |

**Architecture:** integer/fraction split (`e=x[15:8]`, `f=x[7:0]`) → same shift-add correction network as `mitchell_log2_q88` → corrected mantissa → barrel shift by `rsh = 16−e` → range-checked saturation (`rsh<0 → max`, `rsh≥32 → 0`).

**Test result:** max absolute error **0.0039**, again matching the Q8.24 design at the same coefficient.

**Conclusion:** the widest single piece of combinational logic in the whole library is this module's barrel shifter, paired with the LZD in `mitchell_log2_q88` — together they're the two heaviest blocks feeding `eml_tile_q88`.

---

## 4. `eml_tile_q88` — the shared primitive

Covered fully in §1. Combinational, 2,405 gate-equivalent cells (Yosys generic mapping), zero flip-flops, instantiated by every FSM below.

**Test result:** bit-exact crosscheck against a from-scratch Python re-derivation — 12/12 named cases and **1000/1000 random raw (x,y) pairs**, exact match, both before and after the truncation-saturation fix.

**Conclusion:** this is the correctness bottleneck for the entire library — any bug here propagates to all six higher-level blocks, which is exactly what the §1.3 discovery demonstrated. It is also, not coincidentally, the single highest-leverage target for area optimization, since every higher block pays for a full copy of it.

---

## 5. `eml_mul_q88` — multiplication via the log domain

```verilog
module eml_mul_q88 #(parameter W=16, F=8)(
    input  wire signed [W-1:0] a, b,
    output wire signed [W-1:0] out,
    output wire ovf
);
```

| Port | Direction | Width | Description |
|---|---|---|---|
| `a`, `b` | in | 16 (signed) each | Operands |
| `out` | out | 16 (signed) | `a·b` |
| `ovf` | out | 1 | High if either operand's log2 overflows, or the sum saturates |

**Math:** `a·b = 2^(log2|a| + log2|b|)`, sign handled separately (`sign_out = sign_a XOR sign_b`). Zero operands short-circuit to `out=0, ovf=0`.

**Architecture:** sign+abs extraction on each operand → two independent `mitchell_log2_q88` calls → saturating add → one `mitchell_exp2_q88` call → sign reapplied.

**Conclusion:** this is the only block in the library that calls the two Mitchell primitives **directly**, bypassing `eml_tile_q88` entirely — because multiplication needs two independent logs before a single exp, a shape `eml_tile_q88`'s fixed `exp(x)−ln(y)` structure doesn't fit. It is not currently wired into the wrapper.

---

## 6. `eml_feedback_cell_q88` — the sequencing primitive

```verilog
module eml_feedback_cell_q88 #(parameter W=16, F=8)(
    input  wire clk, rst, valid_in,
    input  wire signed [W-1:0] x_ext,
    input  wire        [W-1:0] y_ext,
    input  wire sel_x, sel_y,
    output reg  signed [W-1:0] out,
    output reg  ovf, valid_out
);
```

| Port | Direction | Width | Description |
|---|---|---|---|
| `x_ext` | in | 16 (signed) | External x operand |
| `y_ext` | in | 16 (unsigned) | External y operand |
| `sel_x`, `sel_y` | in | 1 each | Mode select (table below) |
| `out` | out | 16 (signed) | `eml(x,y)` for the selected mode, registered |
| `valid_out` | out | 1 | 1-cycle-delayed mirror of `valid_in` |

| sel_x | sel_y | Mode | Computes |
|---|---|---|---|
| 0 | 0 | feed-forward | `eml(x_ext, y_ext)` |
| 1 | 0 | iterate X | `eml(out_prev, y_ext)` |
| 0 | 1 | iterate Y | `eml(x_ext, out_prev)` |
| 1 | 1 | cross-feedback | `eml(out_prev, out_prev)` |

**Architecture:** the only sequencing this block does is a single register (`fb_reg`) latching the tile's output every cycle `valid_in` is high — no FSM, 1-cycle latency, but capable of driving the tile through arbitrary fixed-point iterations if `valid_in` is held high continuously (a free-running streaming mode, verified to work but not exercised by any current higher-level block).

**Test results (12/12):**
- `eml(0,1) = 1.0` exact
- `eml(0.5,0.5)` within 0.08 absolute
- exp/ln sweep: 27 points, ≤4 failures allowed, all pass
- 38-function compiled-program sweep (using this cell as the sole primitive, via a Python routing layer that intercepts 8 "multiply-shaped" functions to short, direct hardware calls): **26/38 accurate at a 20% relative-error bar**, with the same four functions (`COS`, `ASIN`, `ACOS`, `ACOSH`) failing for a structural reason — they compile to 200-500+ nested EML calls, and Mitchell error compounds multiplicatively through that many nested calls regardless of word width
- iterate-X: exponential tower, saturates gracefully (`1.0 → 2.7188 → 15.1562 → 127.9961`)
- iterate-Y: converges toward the fixed point ≈1.763
- cross-feedback: diverges, saturates gracefully
- average relative error across 6 named EML cases: **0.204%**

**Conclusion:** this is the "compiler target" primitive — the 38-function sweep proves the single `eml(x,y)` operator really does reconstruct a wide swath of elementary functions through composition alone, exactly as the underlying paper's thesis claims, with the failure mode (deep nested-call compounding) being a property of composition depth, not of this hardware.

---

## 7. `eml_sigmoid_q88` — σ(x) = 1/(1+e⁻ˣ)

```verilog
module eml_sigmoid_q88 #(parameter W=16, F=8)(
    input  wire clk, rst, start,
    input  wire signed [W-1:0] x_in,
    output reg  signed [W-1:0] result,
    output reg  valid, ovf
);
```

**Derivation:** `σ(x) = exp(−ln(1+e⁻ˣ))`, decomposed into 3 EML passes plus 2 free digital steps (`+1`, negate):

```
Pass 1: eml(-x, 1)        = e^-x
Digital: Y = 1 + e^-x
Pass 2: eml(0, Y)         = 1 - ln(Y)
Digital: -ln(Y) = (1-ln Y) - 1
Pass 3: eml(-ln(Y), 1)    = 1/Y = σ(x)
```

**6-state FSM**, one clock per pass: `S_IDLE → S_P1 → S_ADD → S_P2 → S_SUB → S_P3 → S_IDLE`. **Latency: 6 cycles.**

**Test results (5/5):**
- `σ(0) = 0.5` exact (both `e^0=1` and `ln(1)=0` are exact in Mitchell's approximation, since the correction term vanishes at `f=0`)
- Sweep `[-4,+4]`: well-conditioned region (`|x|<4`) stays under 6% relative error; the two extreme points get an absolute-error bound instead (`x=-4`: 0.00236 abs; `x=+4`: 0.00627 abs — asymmetric, traced to the exponent-amplification effect landing on opposite output regimes: near-zero for `x=-4`, near-saturation for `x=+4`)
- Symmetry: `σ(x)+σ(-x)=1.0`, worst deviation 0.0117
- Latency: exactly 6 cycles
- Back-to-back calls: no reset needed between them

**Conclusion:** the extreme-input asymmetry here is a property of the 3-pass identity amplifying Pass-1's small absolute error through Pass-3's `exp()`, not a hardware defect — and it's the direct ancestor of the accuracy story in every function built on top of sigmoid (softmax, tanh).

---

## 8. `eml_tanh_q88` — tanh(x) = 2σ(2x) − 1

```verilog
module eml_tanh_q88 #(parameter W=16, F=8)(
    input  wire clk, rst, start,
    input  wire signed [W-1:0] x_in,
    output reg  signed [W-1:0] result,
    output reg  valid, ovf
);
```

**Derivation:** reuses sigmoid's exact 3-pass chain verbatim, with one free input transform (double + negate) and one free output transform (double + subtract 1) bracketing it — no new arithmetic primitive, just two more digital ALU steps.

**7-state FSM** (sigmoid's 6 plus one `S_SCALE` state for the output rescale). **Latency: 7 cycles.**

**Test results (6/6):**
- `tanh(0) = 0` exact, same reason `σ(0)=0.5` is exact
- Sweep `[-2,+2]` (half of sigmoid's range, since doubling the input means `tanh(2.0)` drives the tile as hard as `σ(4.0)` does): **max relative error 3.126% at x=+0.5** — worst error sits mid-range here, the opposite pattern from sigmoid, because tanh's worst case isn't at the tails but where a moderate absolute error lands on a moderate-magnitude output
- Symmetry (`tanh(-x)=-tanh(x)`): worst deviation 0.01562
- Cross-check against true (non-hardware) `2σ(2x)-1`: errors nearly identical to the sweep test's, confirming no algebraic error in the derivation
- Latency: exactly 7 cycles

**Conclusion:** tanh costs exactly one more cycle than sigmoid because the output rescale is a genuinely new digital step — unlike sqrt's halving (§10), which fits for free inside a cycle that already had to happen.

---

## 9. `eml_recip_q88` — 1/x

```verilog
module eml_recip_q88 #(parameter W=16, F=8)(
    input  wire clk, rst, start,
    input  wire [W-1:0] x_in,     // unsigned Q8.8, x > 0
    output reg  signed [W-1:0] result,
    output reg  valid, ovf
);
```

**Derivation:** `1/x = exp(-ln(x))`, 2 EML passes plus one free digital negate:

```
Pass 1: eml(0, x)   = 1 - ln(x)
Digital: -ln(x) = (1-ln x) - 1
Pass 2: eml(-ln(x), 1) = 1/x
```

**4-state FSM:** `S_IDLE → S_P1 → S_SUB → S_P2 → S_IDLE`. **Latency: 4 cycles.**

**Test results (6/6):**
- `1/1.0 = 1.0` exact
- Sweep across `[0.1, 64.0]`: relative error under 4% or absolute under 0.02 at every point
- Identity check (`x · (1/x) ≈ 1.0`): passes across `[0.5, 10.0]`
- Latency: exactly 4 cycles
- `x=0 → ovf=1` (ln(0) undefined)
- Back-to-back calls: no reset needed

**Conclusion:** the shortest EML chain in the library (2 passes) also has the tightest accuracy — a direct, empirically-confirmed relationship between composition depth and compounded Mitchell error, echoed at every longer chain in this document.

---

## 10. `eml_sqrt_q88` — √x

```verilog
module eml_sqrt_q88 #(parameter W=16, F=8)(
    input  wire clk, rst, start,
    input  wire [W-1:0] x_in,     // unsigned Q8.8, x > 0
    output reg  signed [W-1:0] result,
    output reg  valid, ovf
);
```

**Derivation:** `√x = exp(ln(x)/2)`, 2 EML passes plus one **free** digital halving (arithmetic right-shift):

```
Pass 1: eml(0, x)   = 1 - ln(x)
Digital: ln(x) = 1 - (1-ln x);  ln(x)/2 via >>>1 (free)
Pass 2: eml(ln(x)/2, 1) = sqrt(x)
```

**4-state FSM**, same cycle count as recip (`S_IDLE → S_P1 → S_HALF → S_P2 → S_IDLE`) because the halving is free — it doesn't need its own ALU cycle the way recip's negate does, since both fit inside a single state transition.

**Test results (6/6):**
- `sqrt(1.0) = 1.0` exact
- Perfect squares (4, 9, 16, 25, 36, 49, 64): all within 3% relative or 0.02 absolute
- General sweep `[0.1, 100.0]`: same bound holds throughout
- Identity check (`sqrt(x)² ≈ x`): within 6% relative
- Latency: exactly 4 cycles
- `x=0 → ovf=1`

**Conclusion:** this module is the cleanest illustration of "free digital steps" in the whole library — any operation linear in an already-computed EML result folds into a state transition at zero cycle cost, the same principle recip's negate and tanh's rescale use, just with a shift instead of an add/subtract.


`eml_softmax_q88_serial` removes the packed buses entirely:

```verilog
module eml_softmax_q88_serial #(
    parameter W = 16, parameter F = 8, parameter MAX_N = 8
)(
    input  wire                clk, rst, start,
    input  wire [3:0]          n_in,
    input  wire signed [W-1:0] z_in,
    input  wire                z_valid,
    output reg  signed [W-1:0] result,
    output reg                 result_valid,
    output reg                 valid,
    output reg                 ovf,
    output reg                 n_err,

    output wire signed [W-1:0] eml_x_out,
    output wire        [W-1:0] eml_y_out,
    input  wire signed [W-1:0] eml_out_in,
    input  wire                eml_ovf_in
);
```

| Port | Direction | Width | Description |
|---|---|---|---|
| `n_in` | in | 4 | Vector length, sampled with `start`, valid range 2..8 |
| `z_in` | in | 16 (signed) | One logit, captured when `z_valid` is high |
| `z_valid` | in | 1 | Strobe — the FSM holds in `S_LOAD` through gaps, so a producer that isn't always ready still works |
| `result` | out | 16 (signed) | One softmax output element |
| `result_valid` | out | 1 | Strobe, pulses once per output element (`n_in` pulses total per transaction) |
| `valid` | out | 1 | Transaction-complete pulse, coincident with the **last** `result_valid` pulse (or with immediate `n_err` rejection, which has no real output) |
| `ovf`, `n_err` | out | 1 each | Same meaning as every other module in this family |
| `eml_x_out`/`eml_y_out`/`eml_out_in`/`eml_ovf_in` | — | 16/16/16/1 | Tile-client ports — shares an external `eml_tile_q88` instance, same pattern as every `_shared` block |

**Architecture:** logits load one per cycle into `z_buf` in `S_LOAD` (with a running max kept live, so the max-trick shift needs no separate max-finding pass); `S_SHIFT`/`S_SHIFT_LAT` then re-uses the same shared ALU the rest of the FSM already needs (for `S_SUM`, `S_LNS_SUB`, `S_TGT`) to compute `zi − max_z` for every element, one element per two cycles; from there the compute pipeline is **unchanged** from the packed-bus version — per-element `exp`, running sum, `ln(sum)`, per-element `target − ln(sum)`, per-element final `eml` pass — except `S_FIN_LAT` now drives `result`/`result_valid` directly out to the pins each iteration instead of writing into a slot of a wide register.

### 1.1 Latency: measured, not assumed

The packed-bus version's `8·n_in+3` formula does not apply here, since logits/results now arrive and leave serially instead of all at once. Measured directly (`test_serial_latency_all_n`, back-to-back pushes, no gaps) across every N in 2..8:

| N | Cycles (measured) |
|---|---|
| 2 | 25 |
| 3 | 36 |
| 4 | 47 |
| 5 | 58 |
| 6 | 69 |
| 7 | 80 |
| 8 | 91 |

Linear fit: **`cycles = 11·n_in + 3`**, exact to within 0.5 cycles at every N — a load phase (`N` cycles minimum, more with producer gaps) and a shift phase (`2N` cycles, same per-element cost as the existing `S_SUM` loop) added ahead of the unchanged Pass1/Sum/Pass2/Pass3 pipeline, with results then streamed out over the last `N` cycles instead of landing all at once.

### 1.2 Test results (7/7)

| Test | Result |
|---|---|
| `test_serial_uniform_all_n` | outputs ≈ 1/N for every N in 2..8 |
| `test_serial_peaked_all_n` | dominant element correctly identified, every N |
| `test_serial_ramp_all_n` | monotonic ramp logits, every N |
| `test_serial_sum_to_one_all_n` | 56/56 random trials (8 per N × 7 N) sum to ~1.0 |
| `test_serial_latency_all_n` | fitted formula `11N+3` matches every measured N to <0.5 cycles |
| `test_serial_large_range_all_n` | spread-3 logits, zero overflow, every N |
| `test_serial_gapped_push` | FSM correctly waits through `z_valid` stalls — a producer that isn't always ready is handled with no restructuring beyond `S_LOAD`'s existing hold-and-wait behavior |

**Conclusion:** removing the packed bus cost roughly `3N` extra cycles (`11N+3` vs `8N+3`) — the price of accepting/emitting one value per cycle instead of all `N` at once — but changed nothing about the underlying math: same max-trick, same log-sum-exp stabilization, same accuracy shapes across every N. The only genuinely new piece of FSM logic is the gap-tolerant wait in `S_LOAD`; everything downstream of the load phase is the packed-bus version's pipeline, untouched.

---

---



## 13. Conclusions

1. **One operator, six functions.** Every block in this document reduces to some composition of `eml(x,y) = exp(x) − ln(y)` plus free digital steps (add, subtract, shift, negate) — sigmoid needs 3 passes, tanh reuses sigmoid's 3 plus 2 free steps, recip and sqrt each need 2, softmax needs `2N+1`, and the feedback cell exposes the raw operator directly for host-side composition.

2. **The correction is a property of the math, not the hardware.** The 11/32 Mitchell correction coefficient was verified to be word-width-independent by direct numerical sweep, which is why the entire architecture ported from Q8.24 to Q8.8 with only constant/width changes and no re-derivation.

3. **Compounding error is the dominant accuracy story.** Every accuracy number in this document traces back to how many EML passes a function needs: 2-pass functions (recip, sqrt) are the most accurate, 3-pass functions (sigmoid, tanh) show measurable but bounded degradation, and the deep compiled-program compositions in the 38-function sweep (200-500+ nested calls for `COS`/`ASIN`/`ACOS`/`ACOSH`) are where Mitchell error compounds enough to fail a 20% bar — a property of composition depth, confirmed to be identical in both Q8.8 and Q8.24.

4. **Free digital steps are real and load-bearing.** Every "+1 cycle" or "+0 cycle" in this library's latency table is explained by whether a post-processing step needed its own ALU cycle (tanh's rescale, recip's negate) or fit inside an existing state transition (sqrt's halving) — a small but consistent design pattern worth preserving in any future block.

5. **One real bug was found in the shared core, not in any individual block's own logic** — the `eml_tile_q88` scaling-multiply truncation — and it was found by pushing softmax's max-trick harder than any prior test had pushed the tile's input range, illustrating that this library's own composability is also its best testing tool: stressing one block can surface a latent bug in the primitive every other block depends on.


# eml_wrapper_q88_serial — Architecture and Gate-Level Verification

**Module:** `eml_wrapper_q88_serial`
**Format:** Q8.8 fixed point — 16-bit signed, 8 integer bits, 8 fractional bits
**Status:** RTL 47/47, clean synthesis (0 errors/warnings), gate-level netlist simulated directly — **47/47, bit-identical to RTL.**

---

## 1. Interface

```verilog
module eml_wrapper_q88_serial #(
    parameter W = 16, parameter F = 8, parameter MAX_N = 8
)(
    input  wire             clk, rst, start,
    input  wire [2:0]       opcode,
    input  wire signed [W-1:0]  x_in,
    input  wire [3:0]           n_in,
    input  wire signed [W-1:0]  z_in,
    input  wire                 z_valid,
    input  wire signed [W-1:0]  x_ext,
    input  wire        [W-1:0]  y_ext,
    input  wire                 sel_x,
    input  wire                 sel_y,
    output reg  signed [W-1:0]  result,
    output reg                  valid,
    output reg                  ovf,
    output reg                  n_err,
    output wire                 busy,
    output wire                 ready
);
```

| Opcode | Value | Block | Latency |
|---|---|---|---|
| `OP_SIGMOID` | `000` | 6 cycles |
| `OP_TANH` | `001` | 7 cycles |
| `OP_RECIP` | `010` | 4 cycles |
| `OP_SQRT` | `011` | 4 cycles |
| `OP_SOFTMAX` | `100` | `11·n_in+3` cycles, back-to-back pushes |
| `OP_FEEDBACK` | `101` | 1 cycle |

Every opcode drives its result out through the same two ports, `result` and `valid` — there is no separate output pair for any block, including softmax. For the five single-shot opcodes, `valid` pulses exactly once, coincident with `result` holding the answer. For `OP_SOFTMAX`, `valid` pulses once per output element — `n_in` pulses total — with `result` carrying that element on each pulse; a caller just keeps sampling `result` on every `valid` cycle until it has collected `n_in` values.

---

## 2. Busy/ready handshake

```verilog
reg  busy_reg;
reg [2:0] opcode_reg;
assign busy  = busy_reg;
assign ready = ~busy_reg;
wire accept = start & ready;
```

`start` is only honored when `ready` is high. Once accepted, `opcode_reg` latches the opcode for the whole transaction, so a caller changing `opcode` mid-flight can't corrupt which block's result is being routed to the output — the routing mux for tile access (`route_opcode`) can see the live `opcode` on the accept cycle itself, but the **output** mux is keyed strictly off the latched `opcode_reg`.

`busy` is cleared by an internal `done` signal, not by the exposed `valid` port directly:

```verilog
reg done;
always @(*) begin
    case (opcode_reg)
        OP_SIGMOID:  begin result = sigmoid_result;  valid = sigmoid_valid;  ovf = sigmoid_ovf;  n_err = 1'b0; done = sigmoid_valid;  end
        OP_TANH:     begin result = tanh_result;     valid = tanh_valid;     ovf = tanh_ovf;     n_err = 1'b0; done = tanh_valid;     end
        OP_RECIP:    begin result = recip_result;    valid = recip_valid;    ovf = recip_ovf;    n_err = 1'b0; done = recip_valid;    end
        OP_SQRT:     begin result = sqrt_result;     valid = sqrt_valid;     ovf = sqrt_ovf;     n_err = 1'b0; done = sqrt_valid;     end
        OP_SOFTMAX:  begin result = softmax_result_w; valid = softmax_result_valid_w | softmax_valid; ovf = softmax_ovf; n_err = softmax_n_err; done = softmax_valid; end
        OP_FEEDBACK: begin result = feedback_result; valid = feedback_valid; ovf = feedback_ovf; n_err = 1'b0; done = feedback_valid; end
        default:     begin result = {W{1'b0}}; valid = 1'b0; ovf = 1'b0; n_err = 1'b0; done = 1'b0; end
    endcase
end

always @(posedge clk) begin
    if (rst) begin
        busy_reg <= 1'b0; opcode_reg <= 3'b0;
    end else begin
        if (accept)                 begin busy_reg <= 1'b1; opcode_reg <= opcode; end
        else if (busy_reg && done)  begin busy_reg <= 1'b0; end
    end
end
```

For the five single-shot opcodes, `done` and the exposed `valid` are the same signal, so this is just "clear busy when the answer is ready." `OP_SOFTMAX` is the one case where they differ: `done` is `eml_softmax_q88_serial`'s own transaction-complete pulse (fires once, on the last streamed element), while the exposed `valid` fires once per element. This is what lets `busy` stay correctly asserted through all `n_in` elemental pulses instead of dropping after the first one.

`OP_SOFTMAX`'s `valid` expression, `softmax_result_valid_w | softmax_valid`, exists for one specific case: an out-of-range `n_in` makes the softmax block reject immediately, asserting its own transaction-complete `valid` with no element ever produced (so `softmax_result_valid_w` never fires at all). OR-ing the two means a rejection is still visible on the shared `valid` line even though nothing was streamed. In every normal transaction the two signals already coincide on the last element, so the OR has no effect there.

---

## 3. Test results (47/47)

| Block | Tests | Result |
|---|---|---|
| SIGMOID | 5 | all PASS |
| TANH | 6 | all PASS |
| RECIP | 6 | all PASS |
| SQRT | 6 | all PASS |
| SOFTMAX | 12 | all PASS — uniform/peaked/ramp/sum-to-one/latency/large-range, the three max-trick regression cases, and the invalid-`n_in` rejection case |
| FEEDBACK | 12 | all PASS — 30/38 accurate on the 38-function compiled-program sweep at the 20% relative-error bar, 0 poor |

The softmax adapter in the test harness pushes `n_in` logits one per cycle via `z_in`/`z_valid`, then samples `result` on every `valid` pulse until it has collected `n_in` values:

```python
results = []
for _ in range(timeout):
    await RisingEdge(dut.clk)
    cycles += 1
    if int(dut.valid.value) == 1:
        results.append(q88_to_float(dut.result.value))
        if len(results) == n:
            break
```

---

## 4. Synthesis

```
yosys -p "
  read_verilog mitchell_exp2_q88.v mitchell_log2_q88.v eml_tile_q88.v \
    eml_sigmoid_q88_shared.v eml_tanh_q88_shared.v eml_recip_q88_shared.v \
    eml_sqrt_q88_shared.v eml_softmax_q88_serial.v \
    eml_feedback_cell_q88_shared.v eml_wrapper_q88_serial.v
  hierarchy -check -top eml_wrapper_q88_serial
  proc; opt; memory; opt; techmap; opt
  synth -top eml_wrapper_q88_serial
  stat
  write_verilog -noattr synth_eml_wrapper_q88_serial.v
"
```

**Clean synthesis: 0 errors, 0 warnings.**

### 4.1 Full flattened design

| Metric | Count |
|---|---|
| Wires (bits) | 5,686 (8,527 bits) |
| Total cells | **6,640** |
| Flip-flops | **723** |
| Combinational cells | ~5,917 |

### 4.2 Per-submodule breakdown

| Module | Cells | Notes |
|---|---|---|
| `eml_softmax_q88_serial` | 1,760 | 256 FFs — per-element logit/exp buffers plus FSM/index/accumulator state |
| `eml_tile_q88` | 1,180 | Combinational, zero flip-flops — shared once, paid for once |
| `mitchell_exp2_q88` | 793 | Combinational — barrel shifter dominates |
| `mitchell_log2_q88` | 728 | Combinational — leading-bit detector dominates |
| `eml_tanh_q88_shared` | 592 | One extra state vs. sigmoid for the output rescale |
| `eml_wrapper_q88_serial` (glue/FSM/busy-ready only) | 660 | Includes `busy_reg`/`opcode_reg` and the output mux |

The output netlist keeps the top-level module name `eml_wrapper_q88_serial` unchanged, so it can be dropped straight into a cocotb `TOPLEVEL` with no port-mapping shim.

---

## 5. Gate-level simulation

The synthesized netlist is simulated directly against the same test suite, with no RTL sources present at all:

```makefile
VERILOG_SOURCES  = /usr/share/yosys/simcells.v      # $_AND_/$_MUX_/$_SDFF*_ behavioral models
VERILOG_SOURCES += synth_eml_wrapper_q88_serial.v
TOPLEVEL          = eml_wrapper_q88_serial
MODULE            = test_wrapper_all_functions_q88
```

`simcells.v` (shipped with Yosys) supplies the behavioral models for the generic cells (`$_AND_`, `$_MUX_`, `$_SDFFE_PP0P_`, etc.) that `write_verilog` emits — Icarus has no built-in simulation behavior for those primitives on its own.

**Result: TESTS=47 PASS=47 FAIL=0 — bit-identical to RTL.** `test_feedback_all_38_functions` alone drives ~485,000 ns of simulated time through hundreds of back-to-back tile requests via the shared-tile mux and the busy/ready handshake, with no race conditions or arbitration errors surfacing under that load.

---

## 6. Conclusion

Every opcode in `eml_wrapper_q88_serial`, including softmax, speaks through the same two output ports. The one place this needed care — softmax's `valid` meaning "here's an element" rather than "transaction complete" — is handled entirely inside the module via the internal `done` signal and the `result_valid_w | softmax_valid` OR, both of which are verified down to the gate level: the flattened netlist reproduces all 47 test results exactly, with no RTL present during that simulation.
