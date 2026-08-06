# AI_BYTE Buffer Controller (BC)

**Project:** AI_BYTE Edge AI Accelerator  
**Technology:** GF180MCU (180 nm)  
**Core Area Constraint:** 1100 µm × 1100 µm  
**Version:** V1.0  
**Status:** RTL + cocotb — see VERIFICATION.md

**RTL:** `buffer_ctrl.v` (`ai_byte_buffer_ctrl`)  
**TB (cocotb):** `test_buffer_ctrl.py` — see [VERIFICATION.md](VERIFICATION.md)

```bash
cd buffer_ctrl && make
```

---

# 1. Overview

The Buffer Controller is a **memory-movement datapath**.

It is **not** a second system controller. High-level sequencing belongs to the main FSM.

The BC bridges:

- CPU / Memory-Mapped Interface
- Register File (`buffer_addr_inc`)
- Address Generation Unit (AGU)
- Compute Engine stream ports
- Three external SRAM buffers

The BC **does not** perform computation and **does not** decide which instruction to run.

---

# 2. Design Philosophy (V1)

Optimized for:

- Simplicity
- Small area
- Easy verification
- Easy integration

Therefore V1 deliberately avoids:

- Separate Stream Reader / Result Writer / Arbiter modules
- FIFOs or address queues
- Complex internal FSMs
- Arbitration between CPU and Compute (modes are mutually exclusive)

Conceptual structure:

```text
                    +----------------------+
                    |  Buffer Controller   |
 CPU -------------->|                      |
 FSM -------------->|  CPU / Compute MUX   |
 AGU -------------->|  SRAM Read / Write   |
                    |  Tiny local FSM      |
                    +----------+-----------+
                               |
                     Activation / Weight / Result SRAM
```

---

# 3. Responsibilities

- CPU Mode access to Activation / Weight / Result buffers
- Compute Mode streaming of activations and weights to the Compute Engine
- Capture of `result_valid` into the Result Buffer
- Consume AGU addresses (`addr_valid` / `addr_ready`)
- Enable AGU (`agu_en`) while computing
- Complete when `agu_done` is seen and in-flight beats are drained
- Report `busy`, `done`, `error`, `*_ready` to the FSM
- Pulse `buffer_addr_inc` after successful CPU buffer accesses

The BC **never**:

- Generates convolution traversal (AGU)
- Drives `relu_en` / `pool_en` (FSM)
- Performs INT16 / Q8.8 conversion (Compute Engine IPs)

---

# 4. Internal Buffers

SRAMs are **external** to the BC (instantiated at top level).

| Buffer | Purpose | Size | Width |
|--------|---------|-----:|------:|
| Activation | Feature maps | 256 B | INT8 |
| Weight | Weights | 256 B | INT8 |
| Result | Outputs | 256 B | INT8 |

V1 assumes single-port synchronous SRAM (1-cycle read).

---

# 5. Operating Modes

## Mode 0 — CPU Access (`mode = 0`)

- Main FSM stays idle
- CPU owns the buffers
- Path: `CPU → MMIF → BC → selected SRAM`
- `BUFFER_SELECT` / `BUFFER_ADDR` / `BUFFER_DATA` programming model
- Every successful access pulses `buffer_addr_inc`

`cpu_buf_sel` encoding:

| Value | Buffer |
|------:|--------|
| `00` | Activation |
| `01` | Weight |
| `10` | Result |
| `11` | Illegal → `error` |

## Mode 1 — Compute (`mode = 1`)

- Started by `bc_start`
- Compute owns the buffers (CPU access blocked)
- AGU supplies addresses
- BC streams Act/Weight, writes Result
- Completes on `agu_done` + drain → `done`

```text
AGU addresses
      ↓
Buffer Controller
      ↓
Act / Weight SRAM  →  Compute Engine  →  Result SRAM
```

CPU and Compute **never** access SRAM at the same time. A mode mux is enough — no arbiter.

---

# 6. Local FSM

States:

| State | Meaning |
|-------|---------|
| `IDLE` | Wait for CPU access or `bc_start` |
| `CPU_ACC` | One CPU transaction, then return to IDLE |
| `COMPUTE` | Stream / capture until completion |
| `FINISH` | One-cycle `done` pulse to FSM, then IDLE |

This FSM only sequences **memory movement**. It does not decode opcodes or configure the pipeline.

---

# 7. External Interfaces

## 7.1 CPU / MMIF

| Signal | Dir | Description |
|--------|-----|-------------|
| `cpu_buf_sel[1:0]` | In | Buffer select |
| `cpu_buf_addr` | In | Byte address |
| `cpu_wdata` | In | Write data |
| `cpu_rdata` | Out | Read data (valid while `cpu_re`) |
| `cpu_we` / `cpu_re` | In | Write / read enable |
| `buffer_addr_inc` | Out | Auto-increment pulse → Register File |

## 7.2 FSM

| Signal | Dir | Description |
|--------|-----|-------------|
| `bc_start` | In | Start Compute Mode |
| `mode` | In | `0` = CPU, `1` = Compute |
| `compute_unit[2:0]` | In | Reserved for later ALU/EML (unused in V1 datapath) |
| `busy` | Out | High in `COMPUTE` |
| `done` | Out | High in `FINISH` (one cycle) |
| `error` | Out | Sticky; illegal `cpu_buf_sel==11` |
| `act_ready` / `weight_ready` / `result_ready` | Out | `!(state==COMPUTE)` |

## 7.3 AGU

| Signal | Dir | Description |
|--------|-----|-------------|
| `agu_en` | Out | High while `COMPUTE` |
| `act_addr` | In | Activation address |
| `weight_addr` | In | Weight address |
| `result_addr` | In | Result address for this beat |
| `addr_valid` | In | Address beat valid |
| `addr_ready` | Out | BC accepts address (`COMPUTE` and AGU not finished) |
| `agu_done` | In | AGU finished generating addresses |

## 7.4 Compute Engine

| Signal | Dir | Description |
|--------|-----|-------------|
| `act_data` / `act_valid` | Out | Activation stream |
| `weight_data` / `weight_valid` | Out | Weight stream |
| `result_data` / `result_valid` | In | Result capture |

## 7.5 SRAM (×3)

Per buffer: `addr`, `wdata`, `rdata`, `ce`, `we`.

---

# 8. Compute Datapath Timing (V1)

```text
Cycle N   : addr_fire  → CE Act/Weight SRAM with live AGU addresses
Cycle N+1 : latch rdata → act_valid / weight_valid to Compute Engine
Cycle N+2 : Compute returns result_valid (latency depends on CE)
            BC writes Result SRAM @ delayed result_addr
```

Completion:

```text
agu_done seen
  AND pending address/result beats == 0
  AND stream pipeline drained
    → done_int → FINISH → done=1 → IDLE
```

No FIFO: only a small pending counter and a fixed result-address delay line.

---

# 9. Error Handling (V1)

Minimal:

- `cpu_buf_sel == 2'b11` → sticky `error`
- Cleared by `soft_reset` / hard reset

Not checked in V1 (deferred):

- Out-of-range addresses (MMIF responsibility)
- Protocol violations
- ALU/EML-specific faults

---

# 10. RTL Status

### Implemented and tested

- CPU Mode read / write + `buffer_addr_inc`
- Compute Mode streaming
- AGU handshake + `agu_done` completion
- Result writeback
- Mode mux (no arbitration)
- Status outputs (`busy` / `done` / `error` / `*_ready`)
- Soft reset
- Directed testbench (sync SRAM model)

### Deferred

- ALU / EML streaming (`compute_unit` unused)
- Richer ready semantics
- Constrained-random / coverage closure
- Assertions library expansion

---

# 11. Verification

### How to run

```bash
cd buffer_ctrl
make        # cocotb
```

### Current directed tests

| Test | Coverage |
|------|----------|
| Reset | `busy`/`done`/`error`/`ready` defaults |
| CPU R/W | Activation + Weight buffers |
| Invalid select | `error` set / cleared by `soft_reset` |
| Compute stream | 4 AGU beats, `done`, Result SRAM check |

**Result:** see [VERIFICATION.md](VERIFICATION.md) (cocotb)

---

# 12. File Structure

```text
buffer_ctrl/
    buffer_ctrl.v
    test_buffer_ctrl.py
    Makefile
    README.md
    VERIFICATION.md
```

---

# 13. Related Documents

- `AI_BYTE_Architecture_Specification.md` — system architecture
- `AI_BYTE_Verification_Plan.md` — verification methodology
- `Compute_engine_blocks_interfaces.md` — black-box compute IP interfaces

---

# Version History

| Version | Description |
|---------|-------------|
| V1.0 | Simplified datapath BC; CPU + CONV/FC stream; `agu_done` completion; directed TB passing |