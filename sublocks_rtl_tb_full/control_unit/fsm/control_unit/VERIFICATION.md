# Control Unit — Cocotb Verification Plan

**DUT:** `ai_byte_control_unit.v` (compute-only FSM)  
**TB:** `test_control_unit.py`  
**Status:** 7/7 PASS  

Related: architecture §12.3, teammate `rtl/control_unit.v` (reference only)

---

## 1. Purpose

Verify the compute-only Control Unit:

- Same 8-state flow: IDLE→FETCH→DECODE→ISSUE→EXEC→WBACK→DONE/ERROR
- No data/address ports; only sequences BC
- RF pulse interface (`start_pulse`, `soft_reset`, `irq_clear`)
- Continuous STATUS / level IRQ
- Illegal opcode → ERROR
- DECODE polls until buffers ready
- `mode=0` in IDLE/DONE/ERROR

---

## 2. Environment

BC ports are stubbed in Python (`busy`/`done`/`error`/`*_ready`).  
No AGU / SRAM / RF instantiated at this level.

---

## 3. Test map

| Test | Checks |
|------|--------|
| `test_reset_idle` | Idle flags, mode=0 |
| `test_compute_done` | bc_start, wait done, DONE+irq, irq_clear |
| `test_illegal_opcode_error` | OPCODE 0x5 → ERROR |
| `test_decode_polls_until_ready` | Stalls in DECODE until ready |
| `test_bc_error_path` | BC error → ERROR |
| `test_soft_reset_aborts` | Soft reset → IDLE |
| `test_config_pipeline_enables` | relu/pool/pool_type from CONFIG |

---

## 4. Run

```bash
cd control_unit && make
```
