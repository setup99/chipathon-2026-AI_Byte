# Register File — Cocotb Verification Plan

**DUT:** `reg_file.v` (`ai_byte_reg_file`)  
**TB:** `test_reg_file.py`  
**Simulator:** Icarus Verilog + cocotb 2.x  
**Level:** Unit (block-level directed)  
**Status:** 6/6 PASS

Related: architecture §7–8, `AI_BYTE_Verification_Plan.md` §6.1, `README.md`

---

## 1. Purpose

Verify that the Register File correctly:

- Stores and reads configuration registers
- Broadcasts live values to downstream blocks
- Generates one-cycle CONTROL side-effect pulses
- Mirrors STATUS / VERSION without owning status logic
- Auto-increments `BUFFER_ADDR` when pulsed by the Buffer Controller

Out of scope for this plan: MMIF protocol, STATUS flag generation, instruction decode.

---

## 2. Verification method

| Item | Choice |
|------|--------|
| Style | Directed (stimulus + expected checks) |
| Language | Python (cocotb) |
| Clock | 10 ns period |
| Reset | Active-low async `rst_n` |
| Scoreboard | Inline `assert` against golden values |
| Waves | Optional (`WAVES=1` via Makefile; default off) |

Each `@cocotb.test()` is an independent case: clock start → reset → stimulus → checks.

---

## 3. Test environment

```text
  test_reg_file.py
        │
        ▼
  ai_byte_reg_file   ◄── driven: reg_*, status_i, busy_i, buffer_addr_inc
        │
        └── observed: reg_rdata, *_pulse, *_o broadcasts
```

No other RTL is instantiated. `status_i` / `busy_i` / `buffer_addr_inc` are TB-driven stubs that stand in for Status Logic / Buffer Controller.

---

## 4. Features under test

| ID | Feature | Spec note |
|----|---------|-----------|
| RF-F1 | Reset defaults | All stored regs `0`; VERSION `0x01` |
| RF-F2 | OPCODE / CONFIG truncation | OPCODE `[3:0]`, CONFIG `[5:0]` |
| RF-F3 | Continuous broadcast | `opcode_o`, `config_o`, dims, buffer fields |
| RF-F4 | STATUS mirror | Read `0x1` returns `status_i`; writes ignored |
| RF-F5 | VERSION RO | Always `0x01`; writes ignored |
| RF-F6 | Reserved addresses | `0xB`–`0xE` read `0`; writes ignored |
| RF-F7 | CONTROL pulses | START / SOFT_RESET / IRQ_CLEAR, 1-cycle |
| RF-F8 | START gate | START ignored when `busy_i=1` |
| RF-F9 | CONTROL readback | Always `0x00` |
| RF-F10 | Soft-reset pulse scope | Does **not** clear stored config |
| RF-F11 | `buffer_addr_inc` | +1 when no CPU write |
| RF-F12 | Write vs inc priority | Same-cycle CPU write wins |

---

## 5. Test case map

| Test function | Covers | Checks (summary) |
|---------------|--------|------------------|
| `test_reset_defaults` | RF-F1 | CONTROL/OPCODE/CONFIG/BUF_*/FEAT_ROWS = 0; VERSION = 1; broadcasts 0 |
| `test_rw_stored_registers` | RF-F2, RF-F3 | Write/read OPCODE/CONFIG/BUF_SEL/BUF_ADDR/dims; broadcast matches |
| `test_status_version_readonly` | RF-F4, RF-F5 | STATUS mirrors `0x06`; writes to STATUS/VERSION ignored |
| `test_reserved_addresses` | RF-F6 | Reserved R/W; OPCODE unchanged |
| `test_control_pulses` | RF-F7–F10 | START when idle; blocked when busy; SOFT_RESET+IRQ_CLEAR; regs preserved |
| `test_buffer_addr_inc` | RF-F11, RF-F12 | `0x20→0x21`; CPU write `0x55` wins over simultaneous inc |

---

## 6. How to run

```bash
# from repo root (venv with cocotb already created)
cd reg_file
make
```

Expected summary: `TESTS=6 PASS=6 FAIL=0`.

---

## 7. Pass / fail criteria

- **Pass:** all asserts succeed; cocotb regression reports 0 failures.
- **Fail:** any assert fails, or simulation error / timeout.

---

## 8. Coverage notes & gaps (V1)

Covered well: address map, pulses, broadcast, auto-inc priority.

Not covered here (deferred):

- Illegal concurrent MMIF timing beyond single-cycle helpers
- Random register stress / back-to-back START storms
- Integration with real Status Logic / MMIF (see control-block TB)

---

## 9. Maintenance

When the register map or CONTROL encoding changes, update:

1. This document (§4–§5)
2. `test_reg_file.py`
3. `README.md` / architecture spec if the contract changed
