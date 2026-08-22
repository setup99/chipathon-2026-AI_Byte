# AI_BYTE chip verification (cocotb)

This directory is the **pad-level** verification environment for the full chip top
(`chip_top` + workshop pads + AI_BYTE core). Tests drive the real package-side pins
the same way a host MCU would use the MMIF, and compare against a software
**golden model** of the programming model and datapaths.

---

## Goals

| Goal | How it is checked |
|------|-------------------|
| Pad map / reset / basic access | Smoke test on `chip_top` |
| Host protocol (reg + buffer R/W, START, IRQ) | Shared helpers in `ai_byte_pads.py` |
| Opcodes compute the expected Result / STATUS | Dual-path: DUT + `AiByteGolden` |
| Illegal opcode raises error | STATUS error + golden match |
| CNN / ALU bit-correctness | Exact byte compare (`tol=0`) |
| EML approximate math | Toleranced compare vs float/Mitchell stand-in |

What is **not** claimed here:

- Not cycle-accurate (golden does not model cycle counts).
- Not full Liberty timing / STA (use LibreLane STA for that).
- Not exhaustive random ISA fuzzing (directed e2e per opcode).
- Unit tests of isolated CE blocks live in the parent monorepo; this tree tests **integration through pads**.

---

## Layout

```text
cocotb/
├── README.md              # this file
├── chip_top_tb.py         # runner + smoke test; builds sim
├── test_ai_byte.py        # e2e opcode suite vs golden
├── ai_byte_pads.py        # host pin helpers (write/read/buffer/IRQ)
└── golden/
    ├── __init__.py        # public exports
    ├── chip.py            # AiByteGolden whole-chip model
    └── q88.py             # Q8.8 packing, ALU, scale helpers
```

| Module | Role |
|--------|------|
| `chip_top_tb.py` | Compiles Verilog (`chip_top` + AI_BYTE sources + PDK pad cells when needed), launches cocotb. Contains `test_smoke_reset`. |
| `test_ai_byte.py` | One cocotb test per major opcode (plus illegal). Dual-stimulates HW and golden. |
| `ai_byte_pads.py` | Pads ↔ MMIF: map of bidir bits, `pin_write` / `pin_read` / `buf_write` / `buf_read` / `wait_irq`. |
| `golden.AiByteGolden` | Architectural software chip: RF, three SRAMs, execute-on-START. |
| `golden.q88` | Fixed-point helpers for golden and tests. |

---

## Strategy: dual-path golden co-sim

Every serious e2e test keeps **two mirrors of host traffic**:

```text
                 ┌──────────────────┐
   host sequence │  dual_write_*    │
   (reg / buf)   │  dual_start()    │
                 └────────┬─────────┘
            ┌─────────────┴─────────────┐
            ▼                           ▼
   ┌────────────────┐         ┌────────────────────┐
   │ chip_top DUT   │         │ AiByteGolden       │
   │ (RTL, pads)    │         │ (Python model)     │
   └────────┬───────┘         └─────────┬──────────┘
            │ pin_read RESULT           │ result_bytes()
            │ STATUS / IRQ              │ STATUS bits
            └─────────────┬─────────────┘
                          ▼
                   compare (exact or tol)
```

Helpers in `test_ai_byte.py`:

| Helper | Behavior |
|--------|----------|
| `dual_write_reg(dut, g, addr, data)` | `g.write_reg` + `pin_write` on DUT |
| `dual_write_buf(dut, g, sel, addr, data)` | Same for buffer contents |
| `dual_start(dut, g)` | Golden START + DUT CONTROL START, then **wait for IRQ** on DUT |
| `clear_irq(dut, g)` | CONTROL bit2 IRQ clear on both |
| `assert_status_match` | DUT STATUS error/done vs golden |

This guarantees:

1. Stimulus is **identical** for model and silicon RTL path.
2. Failures localize to **implementation vs model**, not mismatched stimulus.
3. Golden can be run alone in pure Python for quick debugging (import `AiByteGolden`).

---

## Golden model (`golden/chip.py`)

### What it models

- Register map (CONTROL, STATUS, OPCODE, CONFIG, buffer sel/addr, sizes…).
- Three byte SRAMs: Act / Weight / Result (default depths 64 / 16 / 16).
- **START** runs **one** opcode immediately (not cycle-timed).
- STATUS / IRQ semantics aligned with control path intent.
- Pathways:
  - **Exact:** Q8.8 ADD/SUB/MUL; SA 4×4 INT8 GEMM → INT16; FC/CONV post (bias/ReLU/pool/scale→INT8).
  - **Approximate:** SQRT, RECIP, SIGMOID, TANH, SOFTMAX, MICRO — IEEE float or simple stand-in for Mitchell EML (use tolerances in tests).

### What it does **not** model

- Gate delays, pad delays, reset release timing edge cases beyond basic STATUS.
- Multi-job concurrent START / illegal while busy edge cases are only lightly covered.
- Full padframe analog floating pins.

### Key API

```python
from golden import AiByteGolden, ADDR_OPCODE, OP_ADD

g = AiByteGolden()
g.write_buf(BUF_ACT, 0, lo)   # etc.
g.write_reg(ADDR_OPCODE, OP_ADD)
g.write_reg(ADDR_CONTROL, 0x01)  # START → computes Result
gold = g.result_bytes(2)
status = g.read_reg(ADDR_STATUS)
```

Compare helpers: `compare_bytes`, `compare_q88_words` (optional absolute tolerance).

---

## Pad map used by tests

Host drives workshop `bidir_PAD` according to `chip_core.sv` / `ai_byte_pads.py`:

| Pads | Signal |
|------|--------|
| `[3:0]` | `addr[3:0]` |
| `[11:4]` | `data[7:0]` |
| `[12]` | `we` |
| `[13]` | `re` |
| `[14]` | `irq` (chip → host) |
| `[15:16]` | unused (`done`/`error` are in STATUS) |
| `[17:19]` | `debug_state` (not scored; left Z on host) |

Dedicated: `clk_PAD`, `rst_n_PAD`.  
On gate-level sim (`GL=1`), `VDD` / `VSS` may be forced.

---

## Test inventory

### Smoke — `chip_top_tb.py`

| Test | Intent |
|------|--------|
| `test_smoke_reset` | Power (if needed), reset, clocks, basic aliveness |

### E2E suite — `test_ai_byte.py`

| Test | Path | Compare |
|------|------|---------|
| `test_e2e_illegal` | Opcode `0x5` | STATUS error matches golden |
| `test_e2e_add` / `sub` / `mul` | Q8.8 ALU | **Bit-exact** Result bytes |
| `test_e2e_sqrt` / `recip` / `sigmoid` / `tanh` | EML | Tolerance (`TOL_EML_*`) |
| `test_e2e_softmax` | EML serial | INT8 tolerance |
| `test_e2e_microprog` | EML micro / feedback | Q8.8 tolerance |
| `test_e2e_fc` | SA + post (bias/ReLU/scale options) | Bit-exact Result |
| `test_e2e_conv` | SA + ReLU/pool/scale options | Bit-exact Result |

Default tolerances (see `test_ai_byte.py`):

- EML Q8.8: `0x80` (0.5 Q8.8 step)
- EML INT8: ±2
- Softmax INT8: ±3

Adjust only if intentional RTL/Mitchell behavior changes; prefer documenting why.

---

## Results (last known good run)

**Status: all green** on pad-level RTL sim (`SLOT=workshop`, Icarus + cocotb).

| Suite | Tests | Result |
|-------|------:|--------|
| Smoke (`chip_top_tb`) | 1 | **PASS** |
| E2E (`test_ai_byte`) | 12 | **PASS** |
| **Total** | **13** | **PASS** |

### Error budget vs golden

`err` = max |DUT − golden| over compared elements.  
Q8.8: `1` LSB = `1/256` ≈ `0.003906`.

| Constant | Allowed max \|err\| | Meaning |
|----------|-------------------:|---------|
| bit-exact (`tol=0`) | **0** | Exact match |
| `TOL_EML_Q88` / `TOL_MICRO_Q88` | **0x80 = 128** | 0.5 in Q8.8 |
| `TOL_EML_I8` | **2** | ±2 INT8 codes |
| `TOL_SOFTMAX_I8` | **3** | ±3 INT8 codes |

| Test | Result | Allowed max \|err\| | Notes |
|------|--------|--------------------:|-------|
| `test_smoke_reset` | PASS | — | No numeric compare |
| `test_e2e_illegal` | PASS | — | STATUS ERROR bit only |
| `test_e2e_add` | PASS | **0** | Q8.8 bit-exact |
| `test_e2e_sub` | PASS | **0** | Q8.8 bit-exact |
| `test_e2e_mul` | PASS | **0** | Q8.8 bit-exact |
| `test_e2e_sqrt` | PASS | **128** (0.5 Q8.8) | vs float/Mitchell stand-in |
| `test_e2e_recip` | PASS | **128** (0.5 Q8.8) | vs float/Mitchell stand-in |
| `test_e2e_sigmoid` | PASS | **2** (INT8) | EML path |
| `test_e2e_tanh` | PASS | **2** (INT8) | EML path |
| `test_e2e_softmax` | PASS | **3** (INT8) | EML serial |
| `test_e2e_microprog` | PASS | **128** (0.5 Q8.8) | micro / feedback EML |
| `test_e2e_fc` | PASS | **0** | SA + post bit-exact |
| `test_e2e_conv` | PASS | **0** | SA + post bit-exact |

Measured `max_err` for each compare is printed in the cocotb log on PASS, e.g.  
`ok max_err=… tol=…` (see `compare_bytes` / `compare_q88_words`). Re-run `make sim` and copy those values here if you need the exact measured errors from a fresh run.

Command used:

```bash
SLOT=workshop make sim
```

That also copies `cocotb/sim_build/results.xml` → **`cocotb/results.xml`** (tracked).  
`sim_build/` stays gitignored. After a green run:

```bash
git add cocotb/results.xml
git commit -m "Add cocotb pass log (results.xml)"
```

Confirm no failures: `grep failure cocotb/results.xml` should print nothing.

Re-run after RTL or pad-map changes and update this table if anything fails.

---

## How to run

From repo root (Nix shell recommended if using project tools):

```bash
# Full default suite: smoke + all e2e tests
make sim

# AI_BYTE e2e only
COCOTB_TEST_MODULES=test_ai_byte make sim

# Smoke only
COCOTB_TEST_MODULES=chip_top_tb make sim

# Workshop slot (default in Makefile)
SLOT=workshop make sim

# Gate-level (after netlist available; needs PDK + GL flow)
make sim-gl

# Waveforms (if FST enabled in build)
make sim-view
```

Runner entrypoint is always `python3 cocotb/chip_top_tb.py` (Makefile `cd cocotb` + env).

Useful environment variables (see `chip_top_tb.py`):

| Env | Default | Meaning |
|-----|---------|---------|
| `SIM` | `icarus` | Simulator backend for cocotb runner |
| `SLOT` | `workshop` | Padframe slot define |
| `PDK_ROOT` / `PDK` | Makefile / cache | Pad cell libraries when GL / pad models need them |
| `COCOTB_TEST_MODULES` | `chip_top_tb,test_ai_byte` | Which Python modules export tests |
| `GL` | `0` | Gate-level path |

Python needs **cocotb** (and cocotb-tools for the runner). Use the project or parent monorepo venv if needed.

---

## Adding a new opcode test

1. Confirm `OPCODE` constants and datapath handling exist in RTL + `AiByteGolden`.
2. Implement golden execute path if missing (exact math preferred; document approx).
3. In `test_ai_byte.py`:
   - `start_up(dut)`
   - Create `g = AiByteGolden()`
   - Load buffers with `dual_write_buf`
   - Program OPCODE / CONFIG / size regs with `dual_write_reg`
   - `dual_start` → `assert_status_match` → read Result → `compare_*` → `clear_irq`
4. Prefer **same** packing helpers (`pack_q88_bytes`, INT8 layouts) for DUT and golden so stimulus cannot diverge.

---

## Interpreting failures

| Symptom | Likely cause |
|---------|----------------|
| STATUS error mismatch | Illegal / decode / soft-reset path, or START while busy |
| Exact ALU mismatch | Byte order (Q8.8 LE), wrong buffer select, FEATURE_COLS |
| Exact FC/CONV mismatch | CONFIG flags, tile packing, scale/ReLU/pool order |
| EML out of tol | Approximation / range; raise timeout if IRQ never fires |
| IRQ timeout | Core hang, wrong pad OE map, clock/reset not released |
| Pad X/Z on data | Host still driving data during read; check `ai_byte_pads.host_la` |

---

## Relation to other verification

| Layer | Location | Purpose |
|-------|----------|---------|
| **Pad e2e (this folder)** | `chipathon-2026-AI_Byte/cocotb` | Full chip host-visible behavior |
| Monorepo block / unit tests | parent `AI_BYTE_accelerator` | Isolated control / CE blocks |
| PnR STA / DRC | LibreLane runs | Timing and physical signoff |

Architectural programming model for firmware authors is summarized in the repo root [`README.md`](../README.md). This file is the **verification companion**.
