# Buffer Controller — Cocotb Verification Plan

**DUT:** `buffer_ctrl.v` (`ai_byte_buffer_ctrl`)  
**TB:** `test_buffer_ctrl.py`  
**Simulator:** Icarus Verilog + cocotb 2.x  
**Level:** Unit (block-level directed) with behavioral stubs  
**Status:** 4/4 PASS

Related: architecture Buffer Controller section, `AI_BYTE_Verification_Plan.md` §6.6, `README.md`

---

## 1. Purpose

Verify that the Buffer Controller correctly:

- Performs CPU Mode (Mode 0) read/write to Act / Weight / Result SRAMs
- Flags invalid `BUFFER_SELECT` (`2'b11`) as `error`
- Clears error on `soft_reset`
- Runs Compute Mode (Mode 1): AGU-driven stream, CE I/O, result writeback
- Completes on `agu_done` + in-flight drain (`done` / `busy` / `*_ready`)

Out of scope: real AGU RTL (stubbed), real SRAM macros (modeled in Python), real compute engines (add stub).

---

## 2. Verification method

| Item | Choice |
|------|--------|
| Style | Directed + environment stubs |
| Language | Python (cocotb) |
| Clock | 10 ns |
| SRAM model | Sync CE/WE/RDATA arrays in a concurrent coroutine |
| CE model | `result = act + weight`, valid one cycle after both valids |
| AGU role | TB drives `addr_valid` / addresses / `agu_done` |

---

## 3. Test environment

```text
                    ┌─────────────────────────┐
  CPU helpers  ───► │  ai_byte_buffer_ctrl    │ ◄── AGU stub (TB)
                    │                         │
  CE stub     ◄───► │  act/weight/result ports│
                    │                         │
  SRAM stub   ◄───► │  sram_act/wt/res_*      │
                    └─────────────────────────┘
```

| Stub | Behavior |
|------|----------|
| SRAM | On `ce`: write `wdata` if `we`, else present `mem[addr]` on next-edge `rdata` |
| CE | Combinational-style registered: `result_valid <= act_valid & weight_valid` |
| AGU | `agu_send_addr()` / `agu_finish()` follow the BC AGU handshake protocol |

`_i()` helper treats `X`/`Z` as 0 so the SRAM coroutine is safe at time 0.

---

## 4. Features under test

| ID | Feature |
|----|---------|
| BC-F1 | Reset: not busy/done/error; all `*_ready=1` |
| BC-F2 | CPU write/read Act + Weight (sync read timing) |
| BC-F3 | Invalid select `2'b11` → `error=1` |
| BC-F4 | `soft_reset` clears `error` |
| BC-F5 | `bc_start` + `mode=1` → busy, ready low |
| BC-F6 | Multi-beat AGU stream + CE add + Result SRAM write |
| BC-F7 | After `agu_done` + drain → `done`, then idle (`busy=0`) |

---

## 5. Test case map

| Test function | Covers | Checks (summary) |
|---------------|--------|------------------|
| `test_reset` | BC-F1 | Idle status flags |
| `test_cpu_buffer_access` | BC-F2 | `act[0]=0x12`, `act[1]=0x34`, `wt[0]=0x03`, `wt[1]=0x05` |
| `test_invalid_buffer_select` | BC-F3, BC-F4 | Error set then cleared by soft_reset |
| `test_compute_streaming` | BC-F5–F7 | 4 beats; `res[i]=act[i]+wt[i]` (`0x15,0x39,0x17,0x29`) |

### CPU read timing assumed by TB

```text
  negedge: assert cpu_re
  posedge: SRAM CE issued
  posedge: rdata valid → sample cpu_rdata
  negedge: deassert cpu_re
```

Matches the sync SRAM timing used by the Buffer Controller.

---

## 6. Compute stream scenario (Test 4)

1. Preload Act/Weight via CPU path.
2. `start_compute()` → `mode=1`, pulse `bc_start`.
3. Send addresses `(0,0,0) … (3,3,3)`.
4. Pulse `agu_done`.
5. Wait for `done`.
6. Compare Result memory against golden sums.

This exercises: AGU handshake, SRAM read latency → `act_valid`/`weight_valid`, CE stub, result capture, completion FSM.

---

## 7. How to run

```bash
cd buffer_ctrl
make
```

Expected: `TESTS=4 PASS=4 FAIL=0`.

Run all three block suites:

```bash
make all
```

---

## 8. Pass / fail criteria

- All asserts pass; Result memory matches golden.
- Timeout waiting for `done` → fail.
- Unexpected `error` during legal compute → fail.

---

## 9. Coverage notes & gaps (V1)

Covered: Mode 0 R/W, invalid select, soft_reset, Mode 1 stream+done with stub AGU/CE/SRAM.

Not covered here:

- Result buffer CPU readback after compute (done in control-block integration TB)
- Real `ai_byte_agu` co-sim (use control block / future BC+AGU TB)
- Backpressure from CE / `result_valid` stalls
- `buffer_addr_inc` pulse observation (RF owns storage; lightly checked in RF TB)
- Exhaustive buffer depths / concurrent illegal Mode 0 during compute

---

## 10. Maintenance

Datapath or completion-rule changes require updates to this plan, `test_buffer_ctrl.py` stubs, and `README.md`.
