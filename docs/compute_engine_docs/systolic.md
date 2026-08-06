# 2D Systolic Array Compute Engine (GEMM)

The **2D Systolic Array Compute Engine** in `AI_Byte` provides high-throughput fixed-point matrix-matrix multiplication ($Y = W \cdot X$). Designed specifically for deep learning workloads—such as Fully-Connected (FC) layers, Recurrent/LSTM gates, and 2D Convolutions (via *im2col*)—the architecture utilizes a **Weight-Stationary (WS)** dataflow with an $M \times P$ grid of pipelined Processing Elements (PEs), accepting **INT8 inputs** and producing **INT16 outputs**.

---

## 1. Directory & File Structure

| File | Description |
|---|---|
| [`src/ram_sdp.v`](file:///home/hamza/dev/IC/AI_Byte/compute_engine/systolic/src/ram_sdp.v) | Simple Dual-Port RAM module for PE weight storage (Port A write preload, Port B registered read stream). |
| [`src/pe_gemv_ws.v`](file:///home/hamza/dev/IC/AI_Byte/compute_engine/systolic/src/pe_gemv_ws.v) | Core Weight-Stationary Processing Element with 3-stage pipeline (INT8 multiply, wide accumulation, INT16 saturation). |
| [`src/gemm_systolic_2d.v`](file:///home/hamza/dev/IC/AI_Byte/compute_engine/systolic/src/gemm_systolic_2d.v) | 2D Systolic Grid ($M \times P$ PEs) for Matrix-Matrix Multiplication & Convolutions. |
| [`tb/test_gemm.py`](file:///home/hamza/dev/IC/AI_Byte/compute_engine/systolic/tb/test_gemm.py) | Cocotb verification testbench for 2D GEMM engine (6 test cases). |
| [`Makefile`](file:///home/hamza/dev/IC/AI_Byte/compute_engine/systolic/Makefile) | Top-level Makefile for running Icarus Verilog and Cocotb simulation suites. |
| [`Makefile.cocotb`](file:///home/hamza/dev/IC/AI_Byte/compute_engine/systolic/Makefile.cocotb) | Sub-makefile for Cocotb framework integration. |

---

## 2. Integer Quantization & Arithmetic

The engine is parameterized to handle mixed-precision integer matrix multiplication:

- **Input Format (`IN_WIDTH=8`)**: 8-bit signed 2's complement integers (`INT8`).
  - Dynamic Range: $-128$ to $+127$.
- **Output Format (`OUT_WIDTH=16`)**: 16-bit signed 2's complement integers (`INT16`).
  - Dynamic Range: $-32768$ to $+32767$.

### Accumulation & Saturation Pipeline

1. **Stage 1 (Fetch)**: Loads 8-bit weight `w_dout` from `ram_sdp` and registers 8-bit activation `x_in`.
2. **Stage 2 (Multiply)**: Computes 8-bit $\times$ 8-bit signed multiplication yielding a 16-bit intermediate product:
   ```
   prod_reg = w_dout * x_reg1   (16 bits)
   ```
3. **Stage 3 (Accumulate & Saturate)**: Accumulates products over $N$ cycles into an extended accumulator register (`ACC_W = 16 + $clog2(N)` bits) to prevent overflow during sum reduction:
   ```
   sum = acc + prod_reg
   ```
4. **Rounding & Saturation Logic**:
   - If `FRAC > 0`, applies convergent rounding and right-shifting.
   - Clamps the result to 16-bit signed integer limits (`-32768` to `+32767`) to produce `y_out`.

---

## 3. Hardware Architecture & Modules

### 3.1 `ram_sdp.v` — Simple Dual-Port Weight RAM

Inferred FPGA Block RAM primitive used internally by every PE to hold INT8 weights.

```
       +------------------------------------+
       |              ram_sdp               |
       |  DEPTH=N, DATA_W=IN_WIDTH, ADDR_W  |
       +------------------------------------+
       | Port A (Write)   | Port B (Read)   |
  clk  |---> clk          |---> clk         |
  we   |---> we           |                 |
addr_a |---> addr_a       |---> addr_b      |
din_a  |---> din_a        |---> dout_b (reg)|
       +------------------------------------+
```

---

### 3.2 `pe_gemv_ws.v` — Weight-Stationary Processing Element

The fundamental compute element. Each PE calculates a single dot product between a stored 8-bit weight vector row $W[i, :]$ and an incoming 8-bit activation vector stream $X[:]$, producing a 16-bit result `y_out`.

```
                      +------------------------------------------+
                      |               pe_gemv_ws                 |
                      +------------------------------------------+
  w_load_* -----------> Weight Preload (8-bit Port A ram_sdp)    |
                      |                                          |
  x_in (8-bit) -------> [Stage 1: Fetch] ---> x_out (8-bit)     |
                      |        |                                 |
                      |  w_dout (8-bit)                          |
                      |        v                                 |
                      | [Stage 2: 8x8 Multiply -> 16-bit prod]   |
                      |        |                                 |
                      |     prod_reg                             |
                      |        v                                 |
                      | [Stage 3: Accumulate & Saturate (16-bit)]|
                      |        |                                 |
                      |        v                                 |
  y_out (16-bit) <----- [Result Handshake]                        |
                      +------------------------------------------+
```

---

### 3.3 `gemm_systolic_2d.v` — 2D Systolic Matrix-Matrix Grid

Instantiates an $M \times P$ grid of PEs to execute matrix-matrix multiplication $Y = W \cdot X$, where:
- $W \in \mathbb{Z}^{M \times N}$ (8-bit Weight Matrix preloaded row-by-row, broadcasted across $P$ columns).
- $X \in \mathbb{Z}^{N \times P}$ (8-bit Input Activation Matrix, streamed $P$ elements in parallel per cycle for $N$ cycles).
- $Y \in \mathbb{Z}^{M \times P}$ (16-bit Output Result Matrix, registered in parallel).

```
                  Col 0           Col 1                  Col P-1
              x_in_data[0]    x_in_data[1]            x_in_data[P-1]
                (8-bit)         (8-bit)                 (8-bit)
                   |               |                       |
                   v               v                       v
  Row 0  ---> +----------+    +----------+           +----------+
              | PE [0][0]|    | PE [0][1]|   ...     |PE[0][P-1]|
              +----------+    +----------+           +----------+
                   |               |                       |
                   v               v                       v
  Row 1  ---> +----------+    +----------+           +----------+
              | PE [1][0]|    | PE [1][1]|   ...     |PE[1][P-1]|
              +----------+    +----------+           +----------+
                   |               |                       |
                   v               v                       v
                 .....           .....                   .....
                   |               |                       |
                   v               v                       v
  Row M-1 -> +----------+    +----------+           +----------+
              |PE[M-1][0]|    |PE[M-1][1]|   ...     |PE[M-1][P-1]
              +----------+    +----------+           +----------+
```

---

## 4. Parameters & Interfaces

### 4.1 Module Parameters

| Parameter | Default | Description |
|---|---|---|
| `M` | `4` | Number of rows in PE matrix ($M$). |
| `P` | `4` | Number of columns in PE matrix (batch size / parallel activation channels $P$). |
| `N` | `4` | Inner matrix dimension (number of weights per PE). |
| `IN_WIDTH` | `8` | Input data width in bits (`INT8`). |
| `OUT_WIDTH` | `16` | Output result width in bits (`INT16`). |
| `FRAC` | `0` | Optional fractional right-shift bits. |
| `ROW_W` | `$clog2(M)` | Bit width for row addressing. |
| `IDX_W` | `$clog2(N)` | Bit width for column/RAM element addressing. |

---

### 4.2 Port Descriptions

#### `pe_gemv_ws.v` (Single PE)

| Signal | Dir | Width | Description |
|---|---|---|---|
| `clk`, `rst` | in | 1 | Clock and active-high asynchronous reset. |
| `w_load` | in | 1 | Weight RAM write strobe. |
| `w_load_idx` | in | `IDX_W` | RAM address index ($0$ to $N-1$). |
| `w_load_data` | in | `IN_WIDTH` (8) | Signed INT8 weight value to write. |
| `compute_start` | in | 1 | Strobe signaling first element of new vector stream. |
| `x_in_valid` | in | 1 | Input activation valid strobe. |
| `x_in` | in | `IN_WIDTH` (8) | Signed INT8 input activation value. |
| `x_in_last` | in | 1 | End-of-vector indicator. |
| `x_in_ready` | out | 1 | Ready signal backpressure output. |
| `x_out_valid` | out | 1 | Forwarded valid strobe (1-cycle delay). |
| `x_out` | out | `IN_WIDTH` (8) | Forwarded INT8 activation data (1-cycle delay). |
| `x_out_last` | out | 1 | Forwarded end-of-vector indicator. |
| `x_out_ready` | in | 1 | Downstream ready signal. |
| `y_out_valid` | out | 1 | Output result valid strobe. |
| `y_out` | out | `OUT_WIDTH` (16) | INT16 dot-product result. |
| `y_out_ready` | in | 1 | Handshake acknowledge for result. |

#### `gemm_systolic_2d.v` (2D Grid Array)

| Signal | Dir | Width | Description |
|---|---|---|---|
| `clk`, `rst` | in | 1 | Clock and active-high reset. |
| `op_sel` | in | 4 | Opcode selector (`OP_CONV = 4'b0101`). |
| `start` | in | 1 | Compute start strobe. |
| `busy`, `done` | out | 1 | Array status flags. |
| `w_load`, `w_load_row`, `w_load_col`, `w_load_data` | in | - | Weight preload interface (`w_load_data` is INT8). |
| `x_in_data` | in | `P*IN_WIDTH` | Parallel INT8 input vector streamed each cycle ($P$ elements). |
| `y_mat` | out | `M*P*OUT_WIDTH` | Parallel packed INT16 output result matrix ($M \times P$ elements). |

---

## 5. Verification & Test Suite

Verification is performed using **Icarus Verilog** and **Cocotb** with Python reference models implementing exact bit-level INT8 $\times$ INT8 accumulation and INT16 saturation.

### 5.1 Running Simulations

To run the simulation suite:

```bash
cd compute_engine/systolic
make
```

### 5.2 Test Cases & Coverage Summary (`test_gemm.py` — 6/6 PASS)

1. **`test_gemm_standard_random`**: $4 \times 4$ matrix-matrix multiplication with random INT8 inputs and INT16 outputs.
2. **`test_gemm_fc_mapping`**: Fully-Connected layer mapping with batch size $P=4$.
3. **`test_gemm_conv_mapping`**: 2D Convolution layer mapping via *im2col*.
4. **`test_gemm_mid_stream_reset`**: Cancels driver mid-stream, applies hard reset, and verifies pipeline recovery.
5. **`test_gemm_rounding_saturation`**: Boundary test for maximum/minimum INT16 saturation limits.
6. **`test_gemm_op_sel_filtering`**: Verifies that non-systolic opcodes (e.g. `0b0001`) are ignored and only `OP_CONV` (`0b0101`) triggers computation.

# Area Optimization Report: `gemm_systolic_2d` Systolic Array

**Target:** ASIC/SoC RTL flow (generic standard-cell synthesis, no FPGA hard macros)
**Method:** Generic gate-level synthesis via Yosys (`synth -top gemm_systolic_2d`), default parameters (M=P=N=4, IN_WIDTH=8, OUT_WIDTH=16, FRAC=0)
**Verification:** cocotb + Icarus Verilog testbench (`test_gemm.py`), 6/6 tests re-run and passing bit-exact after every change (including a final re-run with fresh random matrices)

## Result

| Stage | Cells | Δ vs. original | Interface change? |
|---|---:|---:|---|
| Original RTL | 13,428 | — | — |
| Cheaper saturation logic, stripped sim-only debug code | 12,761 | −5.0% | no |
| Shared weight RAM per row (was duplicated per PE) | 11,798 | −12.1% | no |
| Merged 3-stage pipeline → 2-stage (fused multiply-accumulate), removed dead backpressure logic | 11,088 | −17.4% | no |
| Removed redundant output double-buffering | 10,819 | −19.4% | no |
| Removed remaining dead ready/backpressure wiring + never-exercised wraparound compare | 10,806 | −19.5% | no |
| Row address turned into a propagated chain (only row 0 has a real counter) | 10,791 | −19.6% | no |
| Streamed row output instead of parallel `y_mat` | 10,797 | −19.6% (see note below) | **yes** |
| **Time-multiplexed rows (2 physical rows, 2 passes)** | **5,834** | **−56.5%** | no *(external ports unchanged, only latency)* |

Flip-flop count fell from 644 to roughly a quarter of that -- most of the original excess was duplicated storage and pipeline slack, not the actual arithmetic. Final latency for the default test config went from 300ns to 350ns (the time-multiplexing trade).

---

## Part 1 -- Free cleanups (no functional or interface change)

These all kept the exact same ports and timing at the array boundary (`start`/`busy`/`done`, weight-load interface). Same testbench, unmodified, passes throughout.

### 1. Cheaper saturation check
The original logic ran **two full-width magnitude comparisons** against constant bounds to decide whether to clamp. In two's-complement arithmetic, a value fits in `OUT_WIDTH` bits exactly when all bits from the sign position up to the MSB of the wider accumulator are identical -- a cheap AND/OR reduction instead of two subtractor-based comparators:

```verilog
wire [EXTRA_W-1:0] extra_bits = shifted_sum[ACC_W-1 -: EXTRA_W];
wire               ovf        = ~(&extra_bits) & (|extra_bits);
wire               sign       = shifted_sum[ACC_W-1];
```

### 2. Stripped non-synthesizable debug code
`pe_gemv_ws.v` had a per-cycle `$display` instrumenting internal pipeline state. Not real hardware, but Yosys still emitted a `$print` cell per PE. Wrapped in `// synthesis translate_off` / `translate_on` so it stays available for simulation but never reaches synthesis.

### 3. Shared weight RAM per row instead of per PE
The biggest single structural finding in the "free" category. Weights are **broadcast row-wise**: every PE in row `r` holds the identical weight vector `W[r,:]`, and -- since all `P` columns in a row share identical `compute_start`/`x_in_valid` timing -- every PE in that row reads the *same RAM address on the same cycle*. The original RTL instantiated one `ram_sdp` (plus its own address counter) **per PE**, storing `P` bit-for-bit identical copies of the same weight vector per row.

Fix: hoist a single `ram_sdp` + row-level address counter out to `gemm_systolic_2d.v`, one per row (`M` instances instead of `M*P`), broadcasting `row_w_dout[r]` into every PE in that row.

### 4. Merged the 3-stage pipeline into 2 stages
Originally: **Stage 1** register the incoming activation (`x_reg1`, also forwarded to the next row for the systolic delay) -> **Stage 2** register the raw multiply product (`prod_reg`) -> **Stage 3** register the accumulated sum (`acc`). Since `x_reg1` has to stay (it drives the systolic forwarding) but the raw product doesn't need its own register, multiply and accumulate-add were fused into one combinational step registered directly into `acc`:

```verilog
wire signed [PROD_W-1:0] prod = w_dout * x_reg1;
wire signed [ACC_W-1:0]  sum  = acc_eff + sign_extend(prod);
// acc <= sum;   (single register; was prod_reg <= ...; then acc <= ... one cycle later)
```

This removed `prod_reg` (16 bits) plus `valid_reg2`/`last_reg2`/`start_reg2` (3 bits) **per PE** -- 19 x 16 = 304 flip-flops, matching the synthesis delta exactly. Shortens per-PE latency by one cycle (harmless -- verified it only affects *when* a row's result becomes valid, not the row-to-row systolic delay, which is driven entirely by `x_reg1`).

**Trade-off:** the combinational path is now multiply + 18-bit add in one cycle instead of two registered steps. If your target clock is tight, re-check timing after synthesizing with your real cell library.

### 5. Removed dead backpressure/stall logic
`y_out_ready` was hardwired to `1'b1` for every PE, and `x_out_ready` chained down to a constant `1'b1` at the bottom row, making `stall` **provably always 0**. Removed the comparator/OR logic computing it and the `x_in_ready`/`x_out_ready`/`y_out_ready` ports entirely, with a comment flagging the assumption for future reuse in a genuinely backpressured context.

### 6. Removed redundant output double-buffering
The top level latched each PE's result into an intermediate `y_buf` array, then **separately copied the whole array again** into `y_mat` once `ST_DONE` was reached -- two full `M*P*OUT_WIDTH`-bit copies of the same data (256 bits of pure duplication). Fixed by writing directly into the final destination the cycle a result becomes valid; safe because the FSM only reaches `ST_DONE` after the *last* row's result arrives, by which point every earlier row was already written.

### 7. Removed the never-exercised wraparound compare
Each row's address counter had a `(count == N-1) ? 0 : count+1` wraparound guard. Given this FSM's fixed timing, `x_in_valid` only ever stays high for exactly `N` consecutive cycles per row per operation, so the wraparound branch is never actually taken -- it's dead defensive logic in *this specific* integration. Removed (with a comment noting the assumption).

### 8. Row address as a propagated chain instead of independent counters
Row `r`'s read-address sequence is *exactly* row `r-1`'s sequence delayed by one cycle, because `pe_start` and `chain_valid` are themselves just delayed-by-one-cycle-per-row copies of row 0's. So only row 0 needs a real up-counter (with the reset mux and increment adder); every other row became a plain register that copies the row above's effective address each cycle -- no arithmetic needed there at all. Removed `M-1` small adders/muxes. (Modest at `N=4`; matters more as `N` grows.)

---

## Part 2 -- Architectural changes (interface and/or throughput trade-offs)

These required updating the module's external ports and/or the testbench's *monitor* logic (never the stimulus generation). Both were done at your explicit request after flagging the trade-offs.

### 9. Streamed row output -- an honest result, not a clean win
Replaced the parallel `output [M*P*OUT_WIDTH-1:0] y_mat` (holds the whole result matrix at once) with a streamed interface:

```verilog
output reg [ROW_W-1:0]       y_row_idx,
output reg [P*OUT_WIDTH-1:0] y_row_data,
output reg                   y_row_valid
```

One row's `P` results are presented per pulse, one cycle apart (matching the natural systolic completion order), instead of waiting for the whole matrix to be ready.

**What actually happened:** my first attempt (a registered `y_row_data`) came out *worse* in raw cell count than not touching it at all (10,774 vs. 10,791) -- routing whichever of `M` rows is currently valid into one shared register needs an `M`-way multiplexer, and that mux cost almost exactly canceled the flip-flops saved. I caught and fixed the obvious mistake (dropped the redundant register -- each PE's `y_out` is already registered internally, so re-registering it at the top level was the exact same double-buffering mistake fixed in item 6), which improved things but still landed at essentially break-even (10,797, -19.6% overall -- no better than before this change).

**Why it's still probably worth it in real silicon, even though the crude cell count says "wash":** this metric treats every generic cell as one unit, but a real standard-cell flip-flop is typically 3-6x the physical area of a simple mux/gate. Trading ~190 flip-flops for ~190 mux-equivalent combinational cells is very likely a genuine win in real µm² even though it's invisible here. I don't have a real technology library in this environment to confirm that precisely -- treat it as directionally likely, not proven.

**This does change the external contract:** the testbench's `monitor_output_y` was rewritten to collect row pulses as they stream by and assemble the matrix itself, rather than reading one parallel snapshot at `done`. The stimulus-driving functions (`load_weights`, `stream_input_x`) were untouched.

### 10. Time-multiplexed rows -- the real win
Cut physical PE rows from `M=4` to `M_PHYS=2`, running the array twice ("passes") to cover all 4 logical rows, via a new `ROW_REUSE=2` parameter. This is the first change that removes actual physical hardware (multipliers, accumulators, weight RAM) rather than just restructuring registers, and it shows: **10,797 -> 5,834 cells, a 46% additional cut**, for **56.5% smaller than the original** overall.

Key design points:
- **External interface is unchanged.** `w_load_row` and `y_row_idx` still address all `M` logical rows exactly as before -- only the internal implementation knows there are fewer physical rows. Nothing downstream needs to change.
- **Weight RAM per physical row got deeper** (`DEPTH = N x ROW_REUSE`) instead of adding more RAM instances, holding one weight vector per pass it stands in for. Logical row -> (physical row, pass) is plain bit-slicing of `w_load_row` (free -- no divider), which requires `M_PHYS` and `ROW_REUSE` to both be powers of two.
- **Input replay buffer**: since every pass needs the same `N x P` input matrix but the external interface only streams it once, pass 0 captures each cycle's `x_in_data` into a `x_buf[N][P]` register array as it streams by; passes 1..`ROW_REUSE-1` replay it into physical row 0 instead of re-reading `x_in_data`. This is genuine added storage (`N x P x IN_WIDTH` = 128 bits at default sizing) but it's tiny next to the ~8 PE instances removed.
- **FSM extended** with a `pass_idx` counter; `ST_WAIT` now loops back to `ST_COMPUTE` for the next pass instead of going straight to `ST_DONE`, until the last pass completes.
- Logical row number for the streamed output is reconstructed as `pass_idx * M_PHYS + physical_row`.

**Real cost -- throughput:** default-config latency went from 300ns to 350ns (about 1.17x, not a clean 2x since the per-pass pipeline-drain overhead doesn't double along with the streaming cycles). Verified with a fresh random-data re-run of all 6 tests after this change, not just the original one.

**Choices made that weren't specified and would need sign-off before going further:**
- Reuse factor of exactly 2 (halves the array) -- an arbitrary but conservative starting point. A larger factor (e.g. 4) would shrink area further but slow throughput more, and the module currently requires `M` to be evenly divisible by `ROW_REUSE`, with both `M_PHYS` and `ROW_REUSE` powers of two.
- If your real `M` isn't a power of two, this exact bit-slicing trick doesn't apply as-is and would need a real (small) divider or a different row-count choice.

---

## What was considered but not changed

- **Trimming `ACC_W`** (currently `max(2xIN_WIDTH, OUT_WIDTH) + IDX_W` bits) -- already the minimum headroom needed for correctness at the given `N`; only worth revisiting with a firm bound on the real maximum `N`.
- **Column time-multiplexing** (fewer physical columns, replaying columns instead of rows) -- not implemented; would need buffering the "extra" columns' worth of streamed input specifically, a bit more involved than the row-reuse case since column data all arrives in the same cycle window rather than being reusable wholesale like the row case.
- **Bit-serial multiplier** -- would shrink the multiplier further at the cost of `IN_WIDTH` extra cycles per MAC; not attempted.
- **DSP/BRAM hard-macro mapping** -- not applicable; target is a standard-cell ASIC/SoC flow, not an FPGA.

## Files changed

- `pe_gemv_ws.v` -- removed internal weight RAM + address counter (now an external input), merged multiply/accumulate into one pipeline stage, cheaper saturation check, removed dead ready/backpressure ports entirely, debug print wrapped in synthesis guards.
- `gemm_systolic_2d.v` -- added per-row (then per-physical-row) shared weight RAM with propagated addressing, removed redundant `y_buf`/`y_mat` double-buffer in favor of a streamed row output, removed dead `active_op_sel` register and wraparound compare, added row time-multiplexing (`ROW_REUSE` parameter, input replay buffer, extended FSM).
- `ram_sdp.v` -- unchanged.
- `test_gemm.py` -- `monitor_output_y` rewritten to collect streamed row pulses instead of reading one parallel `y_mat` snapshot; all stimulus-driving logic (`load_weights`, `stream_input_x`, reset/op_sel handling) untouched.

