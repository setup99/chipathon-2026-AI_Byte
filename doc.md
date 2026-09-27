# AI_BYTE Silicon Accelerator: Complete Architecture & Multi-Workload Benchmark Specification

**Document Version**: 2.5 (Production Release)  
**Process Technology**: GlobalFoundries GF180MCU (180nm CMOS, Single-Poly Six-Metal)  
**Target Silicon Package**: Standard Workshop Slot Padframe (`chip_top`) with GF180MCU I/O Pads  
**Primary Compute Engines**: $4 \times 4$ Weight-Stationary Systolic Array + Elementary Math Library (EML)  
**Evaluated Workloads & Studies**: 
1. **MNIST** (10-Class Handwritten Digit Recognition)
2. **CIFAR-10** (Edge AI Binary Image Classification: Airplane vs. Automobile)
3. **PlantVillage Leaf Disease v1** (Binary Precision Agriculture: Tomato Healthy vs. Early Blight)
4. **PlantVillage Leaf Disease v2** (4-Class Multi-Disease SOTA: Healthy, Early Blight, Late Blight, Bacterial Spot)
5. **Systematic 6-Architecture Exploration & Pareto Optimality Study**
6. **Silicon Power, Latency & Energy Consumption Analysis at 10 MHz** (GF180MCU 5.0V Signoff Verification)

---

## 1. Executive Summary & Verification Matrix

The **AI_BYTE** accelerator is a custom digital ASIC designed for ultra-low-power TinyML and Edge AI applications. Fabricated on the open-source GlobalFoundries GF180MCU process, it provides dense INT8 matrix-vector arithmetic paired with an Elementary Math Library (EML) capable of computing transcendental functions (Softmax, Sigmoid, Tanh, Reciprocal, Square Root) directly in silicon.

The architecture was evaluated across a strict **four-tier verification hierarchy**:
- **Baseline (Float32)**: Unquantized floating-point reference model.
- **Level 1 — Full Test Set (Bit-Exact INT8)**: Fixed-point arithmetic emulation (`>>> 8` arithmetic scaling, saturating accumulation) over the complete benchmark test splits.
- **Level 2 — Architectural Golden Co-Simulation (100–200 Images)**: Register-accurate Python hardware model (`AiByteGolden`) simulating SRAM buffer transfers and control registers.
- **Level 3 — Cycle-Accurate Physical Pad RTL Simulation (20–40 Images)**: Full Icarus Verilog + Cocotb hardware simulation driving physical package pads (`chip_top`) with embedded GF180MCU SRAM macros.

### 1.1 Multi-Workload Benchmark Summary

| Workload | Target Classes | Network Topology | Input Dimensions | Parameters | Float32 Baseline | Full INT8 Test Set | Golden Co-Sim | RTL Package Pins | Hardware Status |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **MNIST** | 10 classes (`0`–`9`) | $196 \to \text{FC}(16) \to \text{FC}(16)$ | $14 \times 14$ (196B) | 3,424 | 94.20% | **93.77%** (9,377 / 10,000) | **95.50%** (191 / 200) | **95.0%** (19 / 20) | Bit-Exact Verified ✅ |
| **CIFAR-10** | 2 classes (Airplane vs Auto) | $768 \to \text{FC}(64) \to \text{FC}(4)$ | $16 \times 16 \times 3$ (768B) | 49,476 | 91.40% | **91.35%** (1,827 / 2,000) | **93.00%** (186 / 200) | **100.0%** (20 / 20) | Bit-Exact Verified ✅ |
| **Leaf Disease v1** | 2 classes (Healthy vs Early) | $768 \to \text{FC}(64) \to \text{FC}(4)$ | $16 \times 16 \times 3$ (768B) | 49,476 | 97.75% | **98.00%** (392 / 400) | **98.50%** (197 / 200) | **100.0%** (40 / 40) | Bit-Exact Verified ✅ |
| **Leaf Disease v2 (SOTA)** | 4 classes (Healthy, Early, Late, Bact) | $512 \to \text{FC}(128) \to \text{FC}(4)$ | $8 \times 8 \times 8$ (512B) | 66,180 | 91.10% | **90.48%** (722 / 798) | **91.00%** (91 / 100) | **90.0%** (18 / 20) | Bit-Exact Verified ✅ |

```mermaid
flowchart TD
    subgraph Workloads ["Edge AI Workloads Evaluated on AI_BYTE"]
        W1["MNIST Digit Classifier<br/>(10 Classes, 14x14 Grayscale)"]
        W2["CIFAR-10 Edge Binary<br/>(Airplane vs Automobile, 16x16x3 RGB)"]
        W3["PlantVillage Leaf Disease v1<br/>(Healthy vs Early Blight, 16x16x3 RGB)"]
        W4["PlantVillage Leaf Disease v2 SOTA<br/>(4 Classes, 8x8x8 Agronomic Pyramid)"]
    end

    subgraph Silicon ["AI_BYTE Silicon Engine (chip_top)"]
        direction TB
        MMIF["Memory-Mapped Interface<br/>(host_addr, host_data, we, re, irq)"]
        RF["Control & Config Register File<br/>(Opcodes, Post-Processing, Dimensions)"]
        BC["Buffer Controller & DMA Engine<br/>(Sequential & Strided Addressing)"]
        
        subgraph Compute ["Compute Subsystems"]
            SA["4x4 Weight-Stationary<br/>Systolic Array (16 INT8 PEs)"]
            POST["Configurable Post-Processor<br/>(Bias, ReLU, Max/Avg Pool, Shift >>> 8)"]
            EML["Elementary Math Library (EML)<br/>(Mitchell Log/Exp, Softmax, Sigmoid, Tanh)"]
        end
        
        subgraph SRAM ["On-Chip Memory Buffers (ai_byte_sram_buffer)"]
            SRAM_A["Activation Buffer (BUF_ACT)<br/>64 Bytes (Addresses 0x00..0x3F)"]
            SRAM_W["Weight Buffer (BUF_WT)<br/>16 Bytes (Addresses 0x00..0x0F)"]
            SRAM_R["Result Buffer (BUF_RES)<br/>16 Bytes (Addresses 0x00..0x0F)"]
        end
    end

    subgraph Verification ["Hierarchical Verification Stack"]
        V0["Level 0: Float32 Baseline"]
        V1["Level 1: Full INT8 Quantized Test Set"]
        V2["Level 2: Golden Architectural Co-Sim"]
        V3["Level 3: Physical Package Pin RTL (Icarus + Cocotb)"]
    end

    W1 --> MMIF
    W2 --> MMIF
    W3 --> MMIF
    W4 --> MMIF
    MMIF --> RF
    MMIF --> BC
    BC <--> SRAM_A
    BC <--> SRAM_W
    BC <--> SRAM_R
    SRAM_A --> SA
    SRAM_W --> SA
    SA --> POST
    POST --> SRAM_R
    SRAM_R --> EML
    EML --> SRAM_R
    Silicon --> V0 --> V1 --> V2 --> V3
```

---

## 2. Chip Architecture & Hardware Specifications ("Caractéristiques")

### 2.1 Silicon Package Pinout & Pad Interface

AI_BYTE interfaces to the host controller or test harness through standard workshop slot pads on `chip_top.sv`. All signal I/O lines are buffered by GF180MCU digital I/O cells (`gf180mcu_ws_io__dvdd`, `gf180mcu_ws_io__in_s`, `gf180mcu_ws_io__bi_s`).

| Pad Name | Direction | Pad Index | Signal Name | Description |
| :--- | :---: | :---: | :--- | :--- |
| `clk_PAD` | Input | — | `clk` | Master system clock (Nominal 50 MHz, tested at 20 ns period) |
| `rst_n_PAD` | Input | — | `rst_n` | Global active-low asynchronous reset |
| `bidir_PAD[3:0]` | Input | `[3:0]` | `host_addr[3:0]` | Register File / Memory-Mapped address bus |
| `bidir_PAD[11:4]`| Bidir | `[11:4]`| `host_data[7:0]` | 8-bit bidirectional data bus (core drives iff `re=1` and `we=0`) |
| `bidir_PAD[12]` | Input | `[12]` | `we` | Host write enable (active high) |
| `bidir_PAD[13]` | Input | `[13]` | `re` | Host read enable (active high) |
| `bidir_PAD[14]` | Output | `[14]` | `irq` | Interrupt request (pulsed on compute/EML completion) |
| `bidir_PAD[16:15]`| Unused | `[16:15]`| — | Reserved / Unused (Status readable through `ADDR_STATUS`) |
| `bidir_PAD[19:17]`| Output | `[19:17]`| `debug_state[2:0]` | Real-time FSM controller execution state |
| `input_PAD[15:0]`| Input | `[15:0]`| `input_in[15:0]` | General purpose auxiliary digital inputs |

---

### 2.2 Memory-Mapped Register File Specification

Communication with the accelerator is mediated by `ai_byte_mmif.v` and `ai_byte_reg_file_v2.v`:
- Access to `host_addr != 0x6` targets internal control/status registers.
- Access to `host_addr == 0x6` (`ADDR_BUFFER_DATA`) accesses the selected SRAM macro at the auto-incrementing address specified by `ADDR_BUFFER_ADDR`.

| Address | Name | Access | Reset | Description & Bit Fields |
| :---: | :--- | :---: | :---: | :--- |
| `0x0` | `ADDR_CONTROL` | WO | `0x00` | **Execution Control**: <br/>• `bit[0]`: `START` pulse (triggers opcode execution if not busy)<br/>• `bit[1]`: `SOFT_RESET` (active-low single-cycle reset)<br/>• `bit[2]`: `IRQ_CLEAR` (clears pending interrupt) |
| `0x1` | `ADDR_STATUS` | RO | `0x00` | **Status Flags**: <br/>• `bit[0]`: `BUSY` (1 = compute in progress)<br/>• `bit[1]`: `DONE` (1 = execution complete)<br/>• `bit[2]`: `ERROR` (1 = arithmetic/tiling fault)<br/>• `bit[3]`: `IRQ` (1 = interrupt pending) |
| `0x2` | `ADDR_OPCODE` | RW | `0x00` | **Operational Opcode**: Selects compute kernel (`0x0`–`0xB`) |
| `0x3` | `ADDR_CONFIG` | RW | `0x00` | **Post-Processing Configuration Bitmask**: <br/>• `bit[0]`: `CFG_RELU` (enables $\max(0, x)$)<br/>• `bit[1]`: `CFG_POOL` (enables $2 \times 2$ Max Pooling)<br/>• `bit[2]`: `CFG_POOL_AVG` (enables $2 \times 2$ Average Pooling)<br/>• `bit[3]`: `CFG_BIAS` (adds bias vector from Activation SRAM)<br/>• `bit[4]`: `CFG_SCALE` (applies fixed shift `>>> 8` + saturation to $[-128, 127]$)<br/>• `bit[5]`: `CFG_EML_SCALE` (scales Q8.8 results to INT8) |
| `0x4` | `ADDR_BUFFER_SELECT` | RW | `0x00` | **Target SRAM Buffer Selection**: <br/>• `0x0`: Activation Buffer (`BUF_ACT`)<br/>• `0x1`: Weight Buffer (`BUF_WT`)<br/>• `0x2`: Result Buffer (`BUF_RES`) |
| `0x5` | `ADDR_BUFFER_ADDR` | RW | `0x00` | **SRAM Pointer**: 8-bit byte address in selected SRAM. Automatically increments by 1 on every read or write to `ADDR_BUFFER_DATA`. |
| `0x6` | `ADDR_BUFFER_DATA` | RW | — | **SRAM Data Port**: Reading/writing streams data to/from selected SRAM macro at current pointer. |
| `0x7` | `ADDR_FEATURE_ROWS` | RW | `0x00` | Input feature map vertical height ($H$) |
| `0x8` | `ADDR_FEATURE_COLS` | RW | `0x00` | Input feature map horizontal width ($W$) |
| `0x9` | `ADDR_INPUT_CHANNELS` | RW | `0x00` | Input channel depth ($C_{in}$) |
| `0xA` | `ADDR_OUTPUT_CHANNELS`| RW | `0x00` | Output channel depth ($C_{out}$) |
| `0xB` | `ADDR_SOFTMAX_N` | RW | `0x00` | Vector dimension $N$ for EML Softmax ($2 \le N \le 8$) |
| `0xF` | `ADDR_VERSION` | RO | `0x02` | Silicon Core Identification (`0x02` = AI_BYTE v2) |

---

### 2.3 Opcode Set & Hardware Latency Table

| Opcode | Mnemonic | Engine | Math Operation | Silicon Cycles | Description |
| :---: | :--- | :---: | :--- | :---: | :--- |
| `0x0` | `OP_CONV` | SA + Post | $Y = \text{Pool}(\text{ReLU}(X * W + b))$ | Variable | 2D spatial convolution with optional $2 \times 2$ pooling |
| `0x1` | `OP_FC` | SA + Post | $Y = \text{Scale}(\text{ReLU}(W \cdot X + b))$ | $12\text{ cycles / tile}$ | Fully-connected dense matrix multiplication |
| `0x2` | `OP_ADD` | ALU | $Z = X + Y$ (Q8.8) | 2 | Vector elementwise signed addition |
| `0x3` | `OP_SUB` | ALU | $Z = X - Y$ (Q8.8) | 2 | Vector elementwise signed subtraction |
| `0x4` | `OP_MUL` | ALU | $Z = X \times Y$ (Q8.8) | 2 | Vector elementwise fixed-point multiplication |
| `0x6` | `OP_SIGMOID` | EML | $\sigma(x) = \frac{1}{1 + e^{-x}}$ | 5 | Computes logistic sigmoid in Q8.8 precision |
| `0x7` | `OP_TANH` | EML | $\tanh(x) = 2\sigma(2x) - 1$ | 6 | Computes hyperbolic tangent in Q8.8 precision |
| `0x8` | `OP_RECIP` | EML | $y = 1 / x$ | 3 | High-speed reciprocal approximation |
| `0x9` | `OP_SQRT` | EML | $y = \sqrt{x}$ | 3 | Integer/Q8.8 square root |
| `0xA` | `OP_SOFTMAX` | EML | $p_i = \frac{e^{z_i - \max(z)}}{\sum_j e^{z_j - \max(z)}}$ | $11N + 3$ | Numerically stable serial softmax ($2 \le N \le 8$) |
| `0xB` | `OP_MICRO` | EML | Microprogrammed Feedback | 14 | Iterative transcendental feedback loop |

---

### 2.4 $4 \times 4$ Weight-Stationary Systolic Array Microarchitecture

The core GEMM/GEMV computational engine is a 2D mesh of 16 Processing Elements (`pe_gemv_ws.v`):
- **Precision**: 8-bit signed two's complement inputs $\times$ 8-bit signed weights $\to$ 16-bit signed accumulator.
- **Weight Stationarity**: Weights are pre-loaded into internal PE registers via a single cycle pulse (`sa_w_load`). Weights remain stationary inside the PEs across repeated activation passes, maximizing data reuse and minimizing SRAM energy.
- **Skewed Activation Streaming**: Activation vectors stream horizontally into the array rows. Activation inputs are staggered cycle-by-cycle (row 0 at $t=0$, row 1 at $t=1$, etc.).
- **Accumulation Flow**: Partial sums stream downward through column PEs. Each PE performs:
  $$P_{out} = P_{in} + (W_{local} \times A_{in})$$
- **Cycle Timing per $4 \times 4$ Tile**:
  - Weight setup: 4 cycles
  - Systolic computation: 7 cycles
  - Drain & Post-Processing: 1 cycle
  - **Total Latency per Tile**: **12 clock cycles**

---

### 2.5 Elementary Math Library (EML) Theory & Mitchell Approximator

The EML unit provides on-chip non-linear activation and probability distribution evaluation without external CPU intervention:
- **Number Representation (Q8.8)**: 16-bit word where bit 15 is sign, bits 14..8 represent the integer portion ($[-128, +127]$), and bits 7..0 represent the fractional part ($1/256 \approx 0.00390625$ resolution).
- **Mitchell Base-2 Approximation**:
  For an operand $x = 2^k (1 + m)$ with $m \in [0, 1)$:
  $$\log_2(x) = k + m + P(m)$$
  $$\exp_2(k + m) = 2^k (1 + m + Q(m))$$
  where $P(m)$ and $Q(m)$ are combinational correction polynomials implemented with a hardware-efficient factor of $11/32$.
- **Serial Softmax Execution ($11N + 3$ cycles)**:
  1. **Pass 1 (Max Extraction)**: Streams all $N$ logits ($2 \le N \le 8$) to compute $z_{\max} = \max_i(z_i)$.
  2. **Pass 2 (Exp & Accumulate)**: Computes shifted differences $d_i = z_i - z_{\max} \le 0$, evaluates $e_i = \exp(d_i)$ via Mitchell exponential core, and sums $\Sigma = \sum_{i=1}^N e_i$.
  3. **Pass 3 (Normalization)**: Computes the reciprocal $1 / \Sigma$ and multiplies each $e_i$ to generate exact Q8.8 normalized probabilities satisfying $\sum_{i=1}^N p_i = 1.0$.

---

### 2.6 Silicon Implementation & GF180MCU SRAM Macro

- **Fabrication Process**: GlobalFoundries 180nm MCU (`gf180mcuD` design rules).
- **SRAM Memories**: 3 separate instances of `gf180mcu_fd_ip_sram__sram512x8m8wm1`:
  - 512 words $\times$ 8 bits (512 bytes each, 1.5 KB total on-chip).
  - Single-port synchronous read/write interface with byte-level write masking.
  - Fully mapped to the core memory hierarchy: `BUF_ACT`, `BUF_WT`, and `BUF_RES`.

---

## 3. Workload 1: MNIST 10-Class Digit Recognition

### 3.1 Network Topology & Hardware Mapping
- **Problem**: 10-class handwritten digit recognition on standard MNIST test split.
- **Preprocessing**: $28 \times 28$ grayscale digits are downsampled via $2 \times 2$ average pooling to $14 \times 14$ ($196$ pixels) and normalized to signed INT8 $[-64, 63]$.
- **Layer 1 (Feature Extraction)**:
  - Linear transform: $196 \to 16$ hidden units.
  - Matrix dimensions: Input $(1, 196)$, Weights $(196, 16)$, Output $(1, 16)$.
  - Tiling on $4 \times 4$ Systolic Array: 4 output blocks $\times$ 49 input blocks = **196 systolic tile executions**.
  - Post-processing: ReLU activation (`CFG_RELU = 0x01`) + Requantization scaling (`CFG_SCALE = 0x10`, arithmetic right-shift `>>> 8` with saturation to $[0, 127]$).
- **Layer 2 (Digit Classification)**:
  - Linear transform: $16 \to 16$ (10 active classes + 6 zero-padded).
  - Matrix dimensions: Input $(1, 16)$, Weights $(16, 16)$, Output $(1, 16)$.
  - Tiling on $4 \times 4$ Systolic Array: 4 output blocks $\times$ 4 input blocks = **16 systolic tile executions**.
  - Post-processing: Hardware bias vector addition ($b_2 \in [-128, 127]$).
  - Decision: $\text{ArgMax}(\text{logits}[0..9])$.

### 3.2 Verification Results

| Verification Level | Samples Evaluated | Accuracy | Correct Predictions | Status |
| :--- | :---: | :---: | :---: | :---: |
| **Float Baseline** | 10,000 test digits | **94.20%** | 9,420 / 10,000 | 32-bit Floating-Point Reference |
| **Full INT8 Quantized Test Set** | 10,000 test digits | **93.77%** | 9,377 / 10,000 | Bit-Exact Fixed-Point Model |
| **Golden Co-Simulation** | 200 test digits | **95.50%** | 191 / 200 | Architectural Model Simulation |
| **Cycle-Accurate RTL Hardware** | 20 test digits | **95.00%** | 19 / 20 | Verified on `chip_top` Package Pins ✅ |

### 3.3 20-Digit Cycle-Accurate Hardware Execution Log

Evaluated consecutively through `cocotb/rtl_mnist_accuracy_test.py` on physical package pins:

| Image Index | True Digit | RTL Predicted Digit | Correct? | Running HW Accuracy | Sim Time (Real Time) |
| :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | 7 | 7 | ✅ | 1/1 (100.0%) | 5.3s |
| 2 | 2 | 2 | ✅ | 2/2 (100.0%) | 10.7s |
| 3 | 1 | 1 | ✅ | 3/3 (100.0%) | 16.1s |
| 4 | 0 | 0 | ✅ | 4/4 (100.0%) | 21.4s |
| 5 | 4 | 4 | ✅ | 5/5 (100.0%) | 26.8s |
| 6 | 1 | 1 | ✅ | 6/6 (100.0%) | 32.2s |
| 7 | 4 | 4 | ✅ | 7/7 (100.0%) | 37.6s |
| 8 | 9 | 9 | ✅ | 8/8 (100.0%) | 42.9s |
| 9 | 5 | 6 | ❌ | 8/9 (88.9%) | 48.3s |
| 10 | 9 | 9 | ✅ | 9/10 (90.0%) | 53.7s |
| 11 | 0 | 0 | ✅ | 10/11 (90.9%) | 59.1s |
| 12 | 6 | 6 | ✅ | 11/12 (91.7%) | 64.5s |
| 13 | 9 | 9 | ✅ | 12/13 (92.3%) | 69.9s |
| 14 | 0 | 0 | ✅ | 13/14 (92.9%) | 75.3s |
| 15 | 1 | 1 | ✅ | 14/15 (93.3%) | 80.7s |
| 16 | 5 | 5 | ✅ | 15/16 (93.8%) | 86.1s |
| 17 | 9 | 9 | ✅ | 16/17 (94.1%) | 91.5s |
| 18 | 7 | 7 | ✅ | 17/18 (94.4%) | 96.9s |
| 19 | 3 | 3 | ✅ | 18/19 (94.7%) | 102.3s |
| 20 | 4 | 4 | ✅ | **19/20 (95.0%)** | 113.6s |

---

## 4. Workload 2: CIFAR-10 Edge AI Binary Classification (Airplane vs. Automobile)

### 4.1 Network Topology & Hardware Mapping
- **Problem**: Edge binary image classification distinguishing Airplanes (Class 0) from Automobiles (Class 1).
- **Preprocessing**: $32 \times 32 \times 3$ RGB images downsampled via $2 \times 2$ spatial pooling to $16 \times 16 \times 3$ ($768$ INT8 bytes in $[-64, 63]$).
- **Layer 1 (Feature Extraction)**:
  - Linear transform: $768 \to 64$ hidden units.
  - Tiling on $4 \times 4$ Systolic Array: 16 output blocks $\times$ 192 input blocks = **3,072 systolic tile executions**.
  - Post-processing: ReLU + Shift `>>> 8` produces 64 INT8 activations in $[0, 127]$.
- **Layer 2 (Binary Classifier)**:
  - Linear transform: $64 \to 4$ (2 active classes + 2 padded).
  - Tiling on $4 \times 4$ Systolic Array: 1 output block $\times$ 16 input blocks = **16 systolic tile executions**.
  - Post-processing: Hardware bias addition ($b_2 \in [-128, 127]$).
- **EML Softmax Normalization (`OP_SOFTMAX`)**:
  - Direct execution on package pins: $N=2$ takes 25 clock cycles, yielding exact Q8.8 normalized probabilities $P(\text{Airplane})$ and $P(\text{Auto})$.

### 4.2 Verification Results

| Verification Level | Samples Evaluated | Accuracy | Correct Predictions | Status |
| :--- | :---: | :---: | :---: | :---: |
| **Float Baseline** | 2,000 test images | **91.40%** | 1,828 / 2,000 | 32-bit Floating-Point Reference |
| **Full INT8 Quantized Test Set** | 2,000 test images | **91.35%** | 1,827 / 2,000 | Bit-Exact Fixed-Point Model (-0.05% loss) |
| **Golden Co-Simulation** | 200 test images | **93.00%** | 186 / 200 | Architectural Model Simulation |
| **Cycle-Accurate RTL Hardware** | 20 test images | **100.0%** | 20 / 20 | Verified on `chip_top` Package Pins ✅ |

### 4.3 20-Image Cycle-Accurate Hardware Execution Log

Evaluated consecutively through `cocotb/rtl_cifar_accuracy_test.py` on physical package pins:

| Image Index | True Class | RTL Predicted Class | Systolic Logits $[z_0, z_1]$ | EML $P(\text{Airplane})$ | EML $P(\text{Auto})$ | Correct? | Running HW Accuracy |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | Airplane | Airplane | $[+53, -324]$ | **87.9%** | 12.1% | ✅ | 1/1 (100.0%) |
| 2 | Automobile | Automobile | $[+138, +874]$ | 0.8% | **99.2%** | ✅ | 2/2 (100.0%) |
| 3 | Automobile | Automobile | $[-426, +161]$ | 2.0% | **98.0%** | ✅ | 3/3 (100.0%) |
| 4 | Airplane | Airplane | $[+296, +1]$ | **87.9%** | 12.1% | ✅ | 4/4 (100.0%) |
| 5 | Airplane | Airplane | $[+583, +217]$ | **95.3%** | 4.7% | ✅ | 5/5 (100.0%) |
| 6 | Airplane | Airplane | $[+275, -267]$ | **98.0%** | 2.0% | ✅ | 6/6 (100.0%) |
| 7 | Automobile | Automobile | $[+16, +371]$ | 12.1% | **87.9%** | ✅ | 7/7 (100.0%) |
| 8 | Airplane | Airplane | $[+333, -215]$ | **95.3%** | 4.7% | ✅ | 8/8 (100.0%) |
| 9 | Airplane | Airplane | $[+206, +107]$ | **50.0%** | 50.0% | ✅ | 9/9 (100.0%) |
| 10 | Automobile | Automobile | $[-128, +219]$ | 12.1% | **87.9%** | ✅ | 10/10 (100.0%) |
| 11 | Airplane | Airplane | $[+173, -300]$ | **95.3%** | 4.7% | ✅ | 11/11 (100.0%) |
| 12 | Automobile | Automobile | $[-301, +390]$ | 2.0% | **98.0%** | ✅ | 12/12 (100.0%) |
| 13 | Automobile | Automobile | $[-550, +126]$ | 2.0% | **98.0%** | ✅ | 13/13 (100.0%) |
| 14 | Airplane | Airplane | $[+285, +42]$ | **84.0%** | 16.0% | ✅ | 14/14 (100.0%) |
| 15 | Airplane | Airplane | $[+400, -111]$ | **96.5%** | 3.5% | ✅ | 15/15 (100.0%) |
| 16 | Airplane | Airplane | $[+1135, +285]$ | **99.6%** | 0.4% | ✅ | 16/16 (100.0%) |
| 17 | Automobile | Automobile | $[+126, +329]$ | 22.3% | **77.7%** | ✅ | 17/17 (100.0%) |
| 18 | Automobile | Automobile | $[-390, +514]$ | 0.4% | **99.6%** | ✅ | 18/18 (100.0%) |
| 19 | Airplane | Airplane | $[+39, -19]$ | **60.2%** | 39.8% | ✅ | 19/19 (100.0%) |
| 20 | Automobile | Automobile | $[-26, +200]$ | 22.3% | **77.7%** | ✅ | **20/20 (100.0%)** |

---

## 5. Workload 3: PlantVillage Leaf Disease v1 (Binary Tomato Classification)

### 5.1 Motivation & Precision Agriculture TinyML
Automated disease surveillance on crops directly at the field edge enables battery-powered smart sensors to detect fungal outbreaks early. This workload targets differential diagnosis between healthy tomato foliage and early blight (*Alternaria solani*), characterized by concentric brown necrosis.

### 5.2 Network Topology & Hardware Mapping
- **Input**: $16 \times 16 \times 3 = 768$ INT8 bytes in $[-64, 63]$ (derived from $32 \times 32 \times 3$ leaves via $2 \times 2$ average pooling).
- **Layer 1 (Feature Extraction)**: $768 \to 64$ with ReLU + Shift `>>> 8` (3,072 systolic tile executions).
- **Layer 2 (Disease Classifier)**: $64 \to 4$ (Healthy vs. Early Blight) + Hardware Bias (16 systolic tile executions).
- **EML Softmax (`OP_SOFTMAX`)**: Computes exact normalized infection probabilities $P(\text{Healthy})$ vs $P(\text{Early Blight})$ in 25 clock cycles.

### 5.3 Verification Results

| Verification Level | Samples Evaluated | Accuracy | Correct Predictions | Status |
| :--- | :---: | :---: | :---: | :---: |
| **Float Baseline** | 400 test leaves | **97.75%** | 391 / 400 | Floating-Point Baseline |
| **Full INT8 Quantized Test Set** | 400 test leaves | **98.00%** | 392 / 400 | Bit-Exact Fixed-Point Model (+0.25%) |
| **Golden Co-Simulation** | 200 test leaves | **98.50%** | 197 / 200 | Architectural Model Simulation |
| **Cycle-Accurate RTL Hardware** | 40 test leaves | **100.0%** | 40 / 40 | Verified on `chip_top` Package Pins ✅ |

### 5.4 40-Leaf Cycle-Accurate Hardware Execution Log

Evaluated consecutively through `cocotb/rtl_leaf_accuracy_test.py` on physical package pins (real simulation time: 1,635.89s):

| Leaf Index | True Class | RTL Predicted Class | Systolic Logits $[z_0, z_1]$ | EML $P(\text{Healthy})$ | EML $P(\text{Blight})$ | Correct? | Running HW Accuracy |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | Healthy | Healthy | $[+26, -77]$ | **73.0%** | 27.0% | ✅ | 1/1 (100.0%) |
| 2 | Healthy | Healthy | $[+82, -90]$ | **87.9%** | 12.1% | ✅ | 2/2 (100.0%) |
| 3 | Early Blight | Early Blight | $[-202, -55]$ | 27.0% | **73.0%** | ✅ | 3/3 (100.0%) |
| 4 | Healthy | Healthy | $[+42, -85]$ | **73.0%** | 27.0% | ✅ | 4/4 (100.0%) |
| 5 | Healthy | Healthy | $[+54, -179]$ | **95.3%** | 4.7% | ✅ | 5/5 (100.0%) |
| 6 | Early Blight | Early Blight | $[-206, +81]$ | 4.7% | **95.3%** | ✅ | 6/6 (100.0%) |
| 7 | Early Blight | Early Blight | $[-224, +51]$ | 4.7% | **95.3%** | ✅ | 7/7 (100.0%) |
| 8 | Healthy | Healthy | $[+23, -2]$ | **50.0%** | 50.0% | ✅ | 8/8 (100.0%) |
| 9 | Healthy | Healthy | $[+106, -160]$ | **95.3%** | 4.7% | ✅ | 9/9 (100.0%) |
| 10 | Early Blight | Early Blight | $[-231, -10]$ | 12.1% | **87.9%** | ✅ | 10/10 (100.0%) |
| 11 | Healthy | Healthy | $[+93, -120]$ | **87.9%** | 12.1% | ✅ | 11/11 (100.0%) |
| 12 | Early Blight | Early Blight | $[+18, +71]$ | 27.0% | **73.0%** | ✅ | 12/12 (100.0%) |
| 13 | Healthy | Healthy | $[+107, -105]$ | **87.9%** | 12.1% | ✅ | 13/13 (100.0%) |
| 14 | Early Blight | Early Blight | $[-92, +121]$ | 12.1% | **87.9%** | ✅ | 14/14 (100.0%) |
| 15 | Healthy | Healthy | $[+75, -169]$ | **95.3%** | 4.7% | ✅ | 15/15 (100.0%) |
| 16 | Healthy | Healthy | $[+99, -115]$ | **87.9%** | 12.1% | ✅ | 16/16 (100.0%) |
| 17 | Healthy | Healthy | $[+67, -95]$ | **87.9%** | 12.1% | ✅ | 17/17 (100.0%) |
| 18 | Healthy | Healthy | $[+25, -91]$ | **73.0%** | 27.0% | ✅ | 18/18 (100.0%) |
| 19 | Early Blight | Early Blight | $[-187, +20]$ | 12.1% | **87.9%** | ✅ | 19/19 (100.0%) |
| 20 | Early Blight | Early Blight | $[-225, +112]$ | 4.7% | **95.3%** | ✅ | 20/20 (100.0%) |
| 21 | Early Blight | Early Blight | $[-215, -187]$ | 50.0% | **50.0%** | ✅ | 21/21 (100.0%) |
| 22 | Healthy | Healthy | $[+80, -123]$ | **87.9%** | 12.1% | ✅ | 22/22 (100.0%) |
| 23 | Early Blight | Early Blight | $[-272, +21]$ | 4.7% | **95.3%** | ✅ | 23/23 (100.0%) |
| 24 | Early Blight | Early Blight | $[-275, +221]$ | 0.8% | **99.2%** | ✅ | 24/24 (100.0%) |
| 25 | Early Blight | Early Blight | $[-140, +1]$ | 27.0% | **73.0%** | ✅ | 25/25 (100.0%) |
| 26 | Healthy | Healthy | $[+17, -141]$ | **73.0%** | 27.0% | ✅ | 26/26 (100.0%) |
| 27 | Early Blight | Early Blight | $[-159, +199]$ | 2.0% | **98.0%** | ✅ | 27/27 (100.0%) |
| 28 | Healthy | Healthy | $[+43, -128]$ | **73.0%** | 27.0% | ✅ | 28/28 (100.0%) |
| 29 | Healthy | Healthy | $[+114, -94]$ | **87.9%** | 12.1% | ✅ | 29/29 (100.0%) |
| 30 | Early Blight | Early Blight | $[-349, +128]$ | 2.0% | **98.0%** | ✅ | 30/30 (100.0%) |
| 31 | Healthy | Healthy | $[+94, -134]$ | **87.9%** | 12.1% | ✅ | 31/31 (100.0%) |
| 32 | Early Blight | Early Blight | $[-67, -1]$ | 27.0% | **73.0%** | ✅ | 32/32 (100.0%) |
| 33 | Healthy | Healthy | $[+107, -199]$ | **95.3%** | 4.7% | ✅ | 33/33 (100.0%) |
| 34 | Healthy | Healthy | $[-16, -77]$ | **73.0%** | 27.0% | ✅ | 34/34 (100.0%) |
| 35 | Healthy | Healthy | $[+58, -132]$ | **87.9%** | 12.1% | ✅ | 35/35 (100.0%) |
| 36 | Early Blight | Early Blight | $[-253, +40]$ | 4.7% | **95.3%** | ✅ | 36/36 (100.0%) |
| 37 | Early Blight | Early Blight | $[-120, +90]$ | 12.1% | **87.9%** | ✅ | 37/37 (100.0%) |
| 38 | Early Blight | Early Blight | $[-185, -4]$ | 12.1% | **87.9%** | ✅ | 38/38 (100.0%) |
| 39 | Healthy | Healthy | $[+94, -196]$ | **95.3%** | 4.7% | ✅ | 39/39 (100.0%) |
| 40 | Early Blight | Early Blight | $[-291, +65]$ | 2.0% | **98.0%** | ✅ | **40/40 (100.0%)** |

---

## 6. Workload 4: PlantVillage Leaf Disease v2 (4-Class Multi-Disease SOTA Breakthrough)

### 6.1 Clinical Pathology Breakdown
Expanding beyond binary diagnosis, Workload 4 classifies 4 mutually exclusive pathological categories:
1. **Healthy (Class 0)**: Uniform chlorophyll absorption, vivid green leaf blade, intact cellular parenchyma.
2. **Early Blight (Class 1, *Alternaria solani*)**: Target-like brown concentric rings with surrounding yellow chlorosis halo.
3. **Late Blight (Class 2, *Phytophthora infestans*)**: Dark, water-soaked expanding necrotic lesions rapidly rotting foliage.
4. **Bacterial Spot (Class 3, *Xanthomonas campestris*)**: Small, discrete circular brown pustules and scabs with distinct margins.

### 6.2 The 87% Ceiling & Root Cause Analysis
Initial baseline models hit an accuracy ceiling between 80% and 87%:
- **Pustule Dilution Effect**: Bacterial Spot lesions are small ($1$–$2$ pixels wide). Standard spatial pooling ($2 \times 2$ downsampling from $32 \times 32 \to 16 \times 16$) diluted the lesion intensity by 75% into the background green chlorophyll, destroying diagnostic high-frequency features.
- **Spectral Overlap**: Necrotic tissue in Early Blight vs. Late Blight shares similar RGB brown hues; simple RGB pixels lack discriminatory spectral depth.

### 6.3 SOTA Architecture: Multi-Scale Agronomic Spectral Pyramid ($512 \to 128 \to 4$)

To conquer this challenge while honoring AI_BYTE silicon constraints, we engineered the **Multi-Scale Agronomic Spectral Pyramid**:
1. **Feature Extraction ($32 \times 32 \times 3 \to 8 \times 8 \times 8 = 512$ Bytes)**:
   Extracts 8 domain-specific physiological and textural channels directly from raw leaves before spatial pooling:
   - $f_0, f_1, f_2$: Spatial RGB color channels ($R, G, B$).
   - $f_3$: **Excess Green Index** ($ExG = 2G - R - B$, photosynthetically active chlorophyll vigor).
   - $f_4$: **Necrotic Browning Index** ($NBI = R - G$, fungal cell wall collapse).
   - $f_5$: **Chlorotic Halo Index** ($(R+G) - 2B$, border disease halo demarcation).
   - $f_6$: **Pustule Texture Contrast** ($\max_{2\times2} - \min_{2\times2}$, preserves circular scab boundaries from getting averaged away).
   - $f_7$: **Peak Necrosis Intensity** ($\max_{2\times2} R$, captures the dense necrotic core).
2. **100% Activation SRAM (`BUF_ACT`) Utilization**:
   The resulting tensor has $8 \times 8 \times 8 = \mathbf{512\text{ bytes}}$. This **exactly equals** AI_BYTE’s 512-byte Activation SRAM capacity, enabling a single burst DMA transfer with zero memory fragmentation.
3. **Silicon Execution Mapping**:
   - **Layer 1** ($512 \to 128$): 32 output blocks $\times$ 128 input blocks = **4,096 systolic tile executions** + ReLU + Shift `>>> 8`.
   - **Layer 2** ($128 \to 4$): 1 output block $\times$ 32 input blocks = **32 systolic tile executions** + Hardware Bias.
   - **100% Systolic PE Utilization**: All 4 PE outputs compute active disease category logits simultaneously.
   - **EML Softmax**: Direct on-chip computation of exact normalized probabilities across all 4 categories in 25 clock cycles.

### 6.4 Verification Results

| Verification Level | Samples Evaluated | Accuracy | Correct Predictions | Status |
| :--- | :---: | :---: | :---: | :---: |
| **Float Baseline** | 798 test leaves | **91.10%** | 727 / 798 | 4-Class Floating-Point Reference |
| **Full INT8 Quantized Test Set** | 798 test leaves | **90.48%** | 722 / 798 | **+10.53% Gain** over baseline (79.95%) 🚀 |
| **Golden Co-Simulation** | 100 test leaves | **91.00%** | 91 / 100 | Architectural Model Simulation |
| **Cycle-Accurate RTL Hardware** | 20 test leaves | **90.00%** | 18 / 20 | Verified on `chip_top` Package Pins ✅ |

#### Per-Class Accuracy Breakdown (Full 798-Leaf INT8 Test Split):
- **Healthy**: **97.5%** (194 / 199) `█████████████████████████████`
- **Early Blight**: **78.0%** (156 / 200) `███████████████████████`
- **Late Blight**: **90.5%** (180 / 199) `███████████████████████████`
- **Bacterial Spot**: **96.0%** (192 / 200) `████████████████████████████`

### 6.5 20-Leaf Cycle-Accurate Hardware Execution Log

Evaluated consecutively through `cocotb/rtl_leaf_v2_accuracy_test.py` on physical package pins (PASS=1, FAIL=0, real simulation time: 1064.22s):

| Leaf Index | True Diagnosis | RTL Predicted Diagnosis | Systolic Logits $[z_0, z_1, z_2, z_3]$ | Correct? | Running HW Accuracy |
| :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | Healthy | Healthy | $[31850, 5172, -3258, -23381]$ | ✅ | 1/1 (100.0%) |
| 2 | Early Blight | Early Blight | $[-10109, 8240, -6407, 5727]$ | ✅ | 2/2 (100.0%) |
| 3 | Healthy | Healthy | $[15258, -1580, 870, -21841]$ | ✅ | 3/3 (100.0%) |
| 4 | Early Blight | Late Blight | $[-33836, 18489, 21143, -30746]$ | ❌ | 3/4 (75.0%) |
| 5 | Healthy | Healthy | $[45489, -15905, -6003, 3659]$ | ✅ | 4/5 (80.0%) |
| 6 | Bacterial Spot | Bacterial Spot | $[-48668, -8095, -10129, -3123]$ | ✅ | 5/6 (83.3%) |
| 7 | Late Blight | Late Blight | $[-38862, 374, 20249, -12326]$ | ✅ | 6/7 (85.7%) |
| 8 | Late Blight | Late Blight | $[-32861, -7212, 56495, -21219]$ | ✅ | 7/8 (87.5%) |
| 9 | Early Blight | Late Blight | $[-15783, 1205, 4155, -6865]$ | ❌ | 7/9 (77.8%) |
| 10 | Healthy | Healthy | $[20974, -880, -902, -21937]$ | ✅ | 8/10 (80.0%) |
| 11 | Bacterial Spot | Bacterial Spot | $[-46163, -4192, -9252, 11944]$ | ✅ | 9/11 (81.8%) |
| 12 | Late Blight | Late Blight | $[-7359, -8276, 1277, -15032]$ | ✅ | 10/12 (83.3%) |
| 13 | Bacterial Spot | Bacterial Spot | $[-27783, 1706, 3839, 4548]$ | ✅ | 11/13 (84.6%) |
| 14 | Bacterial Spot | Bacterial Spot | $[-29109, 5877, -1840, 11230]$ | ✅ | 12/14 (85.7%) |
| 15 | Late Blight | Late Blight | $[-10407, 11618, 20207, -32451]$ | ✅ | 13/15 (86.7%) |
| 16 | Healthy | Healthy | $[21129, -13863, -3515, -4547]$ | ✅ | 14/16 (87.5%) |
| 17 | Healthy | Healthy | $[39018, -11819, -7559, -1050]$ | ✅ | 15/17 (88.2%) |
| 18 | Bacterial Spot | Bacterial Spot | $[-29904, 9094, -4582, 17514]$ | ✅ | 16/18 (88.9%) |
| 19 | Late Blight | Late Blight | $[-31431, 28513, 33466, -36377]$ | ✅ | 17/19 (89.5%) |
| 20 | Healthy | Healthy | $[8917, -7658, -1184, -32961]$ | ✅ | **18/20 (90.0%)** |

---

## 7. Systematic 6-Architecture Exploration & Pareto Optimality Study

To systematically explore the design space for 4-class multi-disease leaf classification on the AI_BYTE accelerator, 6 distinct candidate topologies were trained and evaluated under identical training epochs, learning rates, and quantization schemes:

### 7.1 Quantitative Benchmark Matrix

| Architecture ID | Model Topology | Input Features | Parameters | MAC Operations | Systolic Tiles | Float32 Acc | INT8 Acc | Gain vs. Baseline | Silicon Tradeoff Profile |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Arch 0 (Baseline)** | $\text{FC}(768 \to 64 \to 4)$ | 768 | 49,476 | 49,408 | 3,088 | 80.45% | **79.95%** | Baseline | Reference architecture |
| **Arch 1 (Wider Hidden)** | $\text{FC}(768 \to 128 \to 4)$ | 768 | 98,948 | 98,816 | 6,176 | 84.21% | **84.09%** | **+4.14%** | $2\times$ compute, higher capacity |
| **Arch 2 (Multi-Spectral)** | $\text{FC}(1024 \to 128 \to 4)$ with $ExG$ | 1,024 | 131,716 | 131,584 | 8,224 | 85.71% | **85.71%** | **+5.76%** | Zero Float/INT8 quantization loss |
| **Arch 3 (Hierarchical Deep)**| $\text{FC}(1024 \to 128 \to 32 \to 4)$ | 1,024 | 135,460 | 135,296 | 8,456 | 87.34% | **84.84%** | **+4.89%** | Multi-stage non-linear compression |
| **Arch 4 (Conv + MaxPool)** | $\text{Conv}(3\times3) \to \text{Pool}(2\times2) \to \text{FC}(256 \to 64 \to 4)$ | **256** | **16,708** | **16,640** | **1,040** | **87.34%** | **87.09%** | **+7.14%** | **$3\times$ Faster on Silicon (Throughput Champion)** |
| **Arch 5 (Agronomic Pyramid)**| $\text{FC}(512 \to 128 \to 4)$ | **512** | **66,180** | **66,048** | **4,128** | **91.10%** | **90.48%** | **+10.53% 🏆** | **SOTA Accuracy Champion (100% SRAM Fit)** |

```mermaid
xychart-beta
    title "Pareto Frontier: Accuracy vs. Silicon Compute (MAC Operations)"
    x-axis ["Arch 4 (Conv)", "Arch 0 (Base)", "Arch 5 (Pyramid)", "Arch 1 (Wide)", "Arch 2 (Multi)", "Arch 3 (Deep)"]
    y-axis "INT8 Accuracy (%)" 75 --> 95
    bar [87.09, 79.95, 90.48, 84.09, 85.71, 84.84]
```

### 7.2 Architectural Analysis & Takeaways

1. **Overall SOTA Accuracy Champion — Arch 5 (Multi-Scale Agronomic Spectral Pyramid)**:
   - Smashes the 87% barrier to achieve **90.48% INT8 accuracy** (Float 91.10%).
   - Retains high-frequency pustule textures via $\max_{2\times2} - \min_{2\times2}$ while capturing vegetative vigor and border halos.
   - Generates a 512-byte feature tensor that divides perfectly into 128 integer systolic blocks of size $4 \times 1$ (**zero padding waste**).
2. **Silicon Throughput & Energy Champion — Arch 4 (Conv2D + Hardware MaxPool)**:
   - Delivers **87.09% INT8 accuracy** while executing in only **16,640 MACs** ($3\times$ fewer operations than baseline).
   - Requires only **1,040 systolic tiles** (vs. 3,088 tiles for baseline), reducing inference energy by 66%.
   - Leverages AI_BYTE hardware `OP_CONV` and on-chip $2 \times 2$ Max Pooling (`CFG_POOL = 0x02`).
3. **Quantization Stability Leader — Arch 2 (Multi-Spectral Botanical Index)**:
   - Achieves **0.00% quantization delta** between Float32 (85.71%) and INT8 (85.71%), proving that spectral indices provide strong numerical margins for fixed-point integer math.

---

## 8. Silicon Power, Latency & Energy Consumption Analysis at 10 MHz

The power, latency, and energy metrics below are derived directly from the physical post-layout signoff database of the **AI_BYTE macro (`A02_A`)** on the **GlobalFoundries GF180MCU process** (`nom_tt_025C_5v00` nominal corner at $V_{DD} = 5.0\text{ V}$ using the 7-track standard cell library `GF018hv5v_mcu_sc7`):

### 8.1 Physical Signoff Baseline & 10 MHz Frequency Scaling

From the physical design signoff database (`docs/signoff_a02_macro/metrics.json` and `irdrop.rpt`):
- **PnR Reference Baseline**: Evaluated at clock period $T_0 = 140\text{ ns}$ ($f_0 = 7.143\text{ MHz}$, $V_{DD} = 5.0\text{ V}$):
  - **Internal Cell Power**: $P_{\text{internal}} = 27.94\text{ mW}$
  - **Net Switching Power**: $P_{\text{switching}} = 10.34\text{ mW}$
  - **Total Dynamic Power**: $P_{\text{dyn}}(7.143\text{ MHz}) = 38.28\text{ mW}$
  - **Static Leakage Power**: $P_{\text{leak}} = \mathbf{8.08\text{ }\mu\text{W}}$ ($0.008\text{ mW}$, ultra-low due to 5V thick-oxide transistors)
- **Linear Frequency Scaling to 10.0 MHz ($T_{\text{clk}} = 100\text{ ns}$)**:
  $$P_{\text{dyn}}(10\text{ MHz}) = P_{\text{dyn}}(7.143\text{ MHz}) \times \left(\frac{10.0\text{ MHz}}{7.143\text{ MHz}}\right) = 38.28\text{ mW} \times 1.400 = \mathbf{53.59\text{ mW}}$$
  $$P_{\text{active}}(10\text{ MHz}) = P_{\text{dyn}}(10\text{ MHz}) + P_{\text{leak}} = 53.59\text{ mW} + 0.008\text{ mW} = \mathbf{53.60\text{ mW}}$$

*(Note: If operating on a 3.3V power supply instead of 5.0V, power scales with $(V/V_0)^2 = (3.3/5.0)^2 = 0.4356$, reducing active power to **$\sim 23.3\text{ mW}$**).*

---

### 8.2 Operational Regimes: Core Systolic Engine vs. Package Pin Streaming

When calculating inference energy and latency on AI_BYTE, there are two distinct operational regimes:
1. **Regime 1: Pure Core Compute Engine (On-Chip SRAM to Systolic Array)**:
   - Direct execution between register buffers and the $4 \times 4$ systolic PEs.
   - Evaluates a $4 \times 4$ tile in **12 clock cycles** (4 load + 7 compute + 1 drain).
   - Represents the intrinsic compute throughput of the silicon core.
2. **Regime 2: End-to-End Package Pad Streaming (`chip_top` Pins via Cocotb)**:
   - Evaluated directly on physical package pins where an external host streams activations and weights byte-by-byte through `bidir_PAD[11:4]`.
   - Every byte transfer over the bidirectional GPIO bus requires 4–6 clock cycles of pad handshaking (`we`, `re`, `addr`, `data`).

---

### 8.3 Detailed Model-by-Model Power & Energy Breakdown at 10 MHz

| Model / Workload | Layer Topology | Systolic Tiles | Core Cycles | Core Latency @ 10 MHz | Core FPS | Core Energy / Inf ($E_{\text{core}}$) | Pad Cycles (Measured Cocotb) | Pad Latency @ 10 MHz | Pad FPS | Pad Energy / Inf ($E_{\text{pad}}$) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **MNIST** (10-Class Digit) | $196 \to \text{FC}(16) \to \text{FC}(16)$ | 212 | 2,544 | **0.25 ms** | 3,931 FPS | **13.6 $\mu$J** | ~93,000 | **9.3 ms** | 107.5 FPS | **0.50 mJ** |
| **Arch 4: Conv+Pool** (Throughput SOTA) | $\text{Conv}(3\times3) \to \text{Pool} \to \text{FC}(64\to4)$ | 1,040 | 12,527 | **1.25 ms** | 798 FPS | **67.1 $\mu$J** | ~460,000 | **46.0 ms** | 21.7 FPS | **2.47 mJ** |
| **CIFAR-10** (Binary Edge AI) | $768 \to \text{FC}(64) \to \text{FC}(4)$ | 3,088 | 37,081 | **3.71 ms** | 270 FPS | **198.8 $\mu$J** | ~1,350,000 | **135.0 ms** | 7.4 FPS | **7.24 mJ** |
| **PlantVillage Leaf v1** (Binary) | $768 \to \text{FC}(64) \to \text{FC}(4)$ | 3,088 | 37,081 | **3.71 ms** | 270 FPS | **198.8 $\mu$J** | ~1,350,000 | **135.0 ms** | 7.4 FPS | **7.24 mJ** |
| **PlantVillage Leaf v2 SOTA** (4-Class) | $512 \to \text{FC}(128) \to \text{FC}(4)$ | 4,128 | 49,583 | **4.96 ms** | 202 FPS | **265.8 $\mu$J** | **1,810,368** *(exact)* | **181.0 ms** | 5.5 FPS | **9.70 mJ** |

---

### 8.4 Real-World Battery & Edge IoT Lifetime Analysis (Duty Cycling)

In edge deployments, the accelerator is duty-cycled: waking up to process a frame, then entering clock-gated standby ($P_{\text{leak}} = 8.08\text{ }\mu\text{W}$):
$$P_{\text{avg}} = (D \times P_{\text{active}}) + ((1 - D) \times P_{\text{leak}}), \quad \text{where } D = \text{Frame Rate} \times t_{\text{latency}}$$

- **1 Frame per Second (Periodic Surveillance)**:
  - **Leaf Disease v2 SOTA (Core Compute)**: Duty cycle $D = 1 \times 4.96\text{ ms} = 0.496\% \implies \mathbf{P_{\text{avg}} = 0.274\text{ mW}} \quad (274\text{ }\mu\text{W})$.
  - A compact 1,000 mAh 3.7V LiPo battery (13.3 kJ) can power autonomous field crop monitoring for **over 1.5 years**!
- **10 Frames per Second (Continuous Edge Video Stream)**:
  - **Arch 4 (Conv+Pool)**: Duty cycle $D = 10 \times 1.25\text{ ms} = 1.25\% \implies \mathbf{P_{\text{avg}} = 0.678\text{ mW}}$.
  - **Leaf Disease v2 SOTA**: Duty cycle $D = 10 \times 4.96\text{ ms} = 4.96\% \implies \mathbf{P_{\text{avg}} = 2.66\text{ mW}}$.
- **Continuous 100% Throughput**:
  - Consumes **53.60 mW** at full sustained 10 MHz clocking.

---

## 9. Complete Catalog of Visual Artifacts & Figures

All figures are programmatically generated and updated by the executed Jupyter notebooks:

| Visual Artifact | File Location | Description & Diagnostic Purpose |
| :--- | :--- | :--- |
| **MNIST Comparison** | `cnn_test_flow/accuracy_comparison.png` | Bar chart comparing Baseline vs INT8 vs Golden vs RTL Hardware (95.0%) |
| **MNIST Detailed Plots** | `cnn_test_flow/accuracy_plots.png` | Per-digit breakdown, $10 \times 10$ confusion matrix, and 25 exemplar predictions |
| **MNIST Exemplar Samples** | `cnn_test_flow/mnist_samples.png` | Grid of raw $28 \times 28$ handwritten digits across all classes |
| **MNIST Misclassified** | `cnn_test_flow/misclassified.png` | Ambiguous digit corner cases |
| **CIFAR-10 Comparison** | `cnn_test_flow/cifar_accuracy_comparison.png` | Multi-level verification bar chart showing jump from 50% baseline to 100.0% RTL |
| **CIFAR-10 Detailed Plots** | `cnn_test_flow/cifar_accuracy_plots.png` | Class accuracy bar chart, $2 \times 2$ confusion matrix, and 25 test samples |
| **CIFAR-10 Samples** | `cnn_test_flow/cifar_samples.png` | Grid of $32 \times 32 \times 3$ Airplane and Automobile images |
| **CIFAR-10 Misclassified** | `cnn_test_flow/cifar_misclassified.png` | Visual edge cases (e.g. seaplanes on water, convertibles) |
| **Leaf Disease v1 Comparison** | `cnn_test_flow/leaf_accuracy_comparison.png` | Bar chart comparing 50% baseline $\to$ 98.00% INT8 $\to$ 100.0% RTL Hardware |
| **Leaf Disease v1 Plots** | `cnn_test_flow/leaf_accuracy_plots.png` | Per-class accuracy, $2 \times 2$ confusion matrix, and 25 leaf test samples |
| **Leaf Disease v1 Samples** | `cnn_test_flow/leaf_samples.png` | Grid of raw $32 \times 32$ Healthy and Early Blight tomato leaves |
| **Leaf Disease v1 Misclassified**| `cnn_test_flow/leaf_misclassified.png` | The 8 misclassified edge cases out of 400 test leaves |
| **Leaf Disease v2 Comparison** | `cnn_test_flow/leaf_v2_accuracy_comparison.png` | Multi-level verification bar chart for the 4-class SOTA model (90.48% INT8, 90.0% RTL) |
| **Leaf Disease v2 Detailed Plots** | `cnn_test_flow/leaf_v2_accuracy_plots.png` | $4 \times 4$ confusion matrix and per-class accuracy bar chart |
| **Leaf Disease v2 Samples** | `cnn_test_flow/leaf_v2_samples.png` | $4 \times 4$ exemplar grid of raw leaves across all 4 disease classes |
| **Arch Comparison Bar Chart** | `cnn_test_flow/arch_comparison_accuracy.png` | Side-by-side Float vs. INT8 accuracy across all 6 candidate topologies |
| **Arch Pareto Frontier** | `cnn_test_flow/arch_comparison_pareto.png` | Accuracy vs. Silicon MAC Operations tradeoff curve |
| **Arch Comparison Confusion** | `cnn_test_flow/arch_comparison_confusion.png` | 6 side-by-side $4 \times 4$ confusion matrices across all candidate topologies |

---

## 10. Reproduction & Verification Guide

### 10.1 Environment Requirements
- **OS**: Linux (x86_64 Ubuntu 24.04 LTS / Debian)
- **Toolchain**: Python 3.14, Icarus Verilog 12.0, Cocotb 2.1.0
- **PDK Root**: `$HOME/.cache/ai-byte/pdk/gf180mcu` (`gf180mcuD` PDK)
- **Docker**: **Not Required** (All simulation, quantization, and notebooks run natively).

---

### 10.2 Running Jupyter Notebooks
All 5 notebooks can be executed headless to regenerate executed notebooks and plot artifacts:

```bash
# 1. Execute MNIST Digit Recognition Notebook
jupyter nbconvert --to notebook --execute cnn_test_flow/AI_BYTE_MNIST_Inference.ipynb \
  --output AI_BYTE_MNIST_Inference_executed.ipynb

# 2. Execute CIFAR-10 Binary Classifier Notebook
jupyter nbconvert --to notebook --execute cnn_test_flow/AI_BYTE_CIFAR10_Inference.ipynb \
  --output AI_BYTE_CIFAR10_Inference_executed.ipynb

# 3. Execute PlantVillage Leaf Disease v1 Notebook (Binary)
jupyter nbconvert --to notebook --execute cnn_test_flow/AI_BYTE_LeafDisease_Inference.ipynb \
  --output AI_BYTE_LeafDisease_Inference_executed.ipynb

# 4. Execute PlantVillage Leaf Disease v2 Notebook (4-Class Multi-Disease SOTA)
jupyter nbconvert --to notebook --execute cnn_test_flow/AI_BYTE_LeafDisease_v2_MultiClass.ipynb \
  --output AI_BYTE_LeafDisease_v2_MultiClass_executed.ipynb

# 5. Execute 6-Architecture Head-to-Head Comparison & Pareto Study Notebook
jupyter nbconvert --to notebook --execute cnn_test_flow/AI_BYTE_Architecture_Comparison_Study.ipynb \
  --output AI_BYTE_Architecture_Comparison_Study_executed.ipynb
```

---

### 10.3 Running Cycle-Accurate Physical Pad RTL Tests
To run cycle-accurate package pin simulation under Icarus Verilog + Cocotb locally:

```bash
# 1. Run 20-image MNIST RTL hardware test on physical pins
WAVES=0 PDK_ROOT=$HOME/.cache/ai-byte/pdk/gf180mcu PDK=gf180mcuD \
COCOTB_TEST_MODULES=rtl_mnist_accuracy_test PYTHONPATH=.:cocotb python3 cocotb/chip_top_tb.py

# 2. Run 20-image CIFAR-10 RTL hardware test on physical pins
WAVES=0 PDK_ROOT=$HOME/.cache/ai-byte/pdk/gf180mcu PDK=gf180mcuD \
COCOTB_TEST_MODULES=rtl_cifar_accuracy_test PYTHONPATH=.:cocotb python3 cocotb/chip_top_tb.py

# 3. Run 40-image Leaf Disease v1 RTL hardware test on physical pins
WAVES=0 PDK_ROOT=$HOME/.cache/ai-byte/pdk/gf180mcu PDK=gf180mcuD \
COCOTB_TEST_MODULES=rtl_leaf_accuracy_test PYTHONPATH=.:cocotb python3 cocotb/chip_top_tb.py

# 4. Run 20-image Leaf Disease v2 RTL hardware test on physical pins
RTL_NUM_TEST=20 WAVES=0 PDK_ROOT=$HOME/.cache/ai-byte/pdk/gf180mcu PDK=gf180mcuD \
COCOTB_TEST_MODULES=rtl_leaf_v2_accuracy_test PYTHONPATH=.:cocotb python3 cocotb/chip_top_tb.py
```

---

### 10.4 Retraining & Quantizing Models
To retrain and regenerate INT8 weights and spec files from scratch:

```bash
# Train MNIST (93.8% INT8)
python3 -m cnn_test_flow.model

# Train CIFAR-10 (91.4% INT8)
python3 -m cnn_test_flow.cifar_model

# Train Leaf Disease v1 (Binary, 98.0% INT8)
python3 -m cnn_test_flow.leaf_model

# Train Leaf Disease v2 (4-Class Multi-Disease SOTA Pyramid, 90.5% INT8)
python3 -m cnn_test_flow.leaf_model_v2
```

---

## 11. Summary & Conclusion

Across all four benchmark workloads, the **AI_BYTE** accelerator demonstrates outstanding silicon efficiency, bit-exact numerical stability between software simulation and physical silicon package pads, and competitive accuracy on edge vision tasks. The newly deployed **Multi-Scale Agronomic Spectral Pyramid** (Arch 5) successfully breaks the 87% accuracy barrier, delivering **90.48% INT8 accuracy** on the 4-class PlantVillage dataset with 100% systolic PE utilization and zero padding waste.
