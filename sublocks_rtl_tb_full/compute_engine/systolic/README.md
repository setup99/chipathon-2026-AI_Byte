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
