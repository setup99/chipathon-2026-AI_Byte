# AGU — Cocotb Verification Plan

**DUT:** `agu.v` (`ai_byte_agu`)  
**TB:** `test_agu.py`  
**Simulator:** Icarus Verilog + cocotb 2.x  
**Level:** Unit (block-level directed)  
**Status:** 6/6 PASS  
**Variant:** V1 Option A — **linear stream**

Related: architecture AGU section, `AI_BYTE_Verification_Plan.md` §6.5, `README.md`

---

## 1. Purpose

Verify that the V1 AGU:

- Emits `N = feature_cols_i` address beats
- Sets `act_addr = weight_addr = result_addr = i` for `i = 0 .. N-1`
- Handshakes correctly on `addr_valid` / `addr_ready`
- Asserts `agu_done` after the last beat and holds it until `agu_en` falls
- Respects backpressure, edge cases `N=0` / `N=1`, and mid-stream abort

Out of scope: real CONV sliding-window addressing (kernel / stride / pad), FC vs CONV distinction (same path in V1).

---

## 2. Verification method

| Item | Choice |
|------|--------|
| Style | Directed protocol tests |
| Language | Python (cocotb) |
| Clock | 10 ns |
| Handshake helper | `accept_beat()` — wait valid, pulse ready one cycle, sample addr |
| Scoreboard | Expected index `i` vs sampled `act_addr` |

---

## 3. Test environment

```text
  test_agu.py
       │  drives: agu_en, addr_ready, feature_cols_i, soft_reset
       ▼
  ai_byte_agu
       │  observes: act/weight/result_addr, addr_valid, agu_done
```

No Buffer Controller is connected; the TB plays the BC role for the handshake.

---

## 4. Features under test

| ID | Feature |
|----|---------|
| AGU-F1 | Idle after reset (`addr_valid=0`, `agu_done=0`) |
| AGU-F2 | Linear N-beat stream with equal Act/Wt/Res addresses |
| AGU-F3 | `agu_done` after last beat; held while `agu_en=1` |
| AGU-F4 | Return to idle when `agu_en` deasserted |
| AGU-F5 | Backpressure: hold beat 0 while `addr_ready=0` |
| AGU-F6 | `N=1` single-beat completion |
| AGU-F7 | `N=0` → done, no beats |
| AGU-F8 | Mid-stream `agu_en` drop → idle (abort) |

---

## 5. Test case map

| Test function | Covers | Stimulus / expected |
|---------------|--------|---------------------|
| `test_reset_idle` | AGU-F1 | After reset: not valid, not done |
| `test_n4_stream` | AGU-F2–F4 | `N=4`; beats 0..3; done held; clear on `agu_en=0` |
| `test_backpressure` | AGU-F5 | Stall 5 cycles on beat 0; then complete 0,1,2 |
| `test_n1` | AGU-F6 | One beat at 0, then done |
| `test_n0_immediate_done` | AGU-F7 | Done with no `addr_valid` |
| `test_agu_en_drop_midstream` | AGU-F8 | Accept 2 of 8, drop `agu_en` → idle |

---

## 6. Protocol timing (what the TB assumes)

```text
  cycle:   wait valid → negedge set ready=1 → posedge FIRE → sample → clear ready
```

Fire condition: `addr_valid & addr_ready` on a rising clock edge (matches DUT).

---

## 7. How to run

```bash
cd agu
make
```

Expected: `TESTS=6 PASS=6 FAIL=0`.

---

## 8. Pass / fail criteria

- Every beat address equals the expected linear index.
- Done / valid / abort behavior matches the table in §5.
- Any assert failure or hang → fail.

---

## 9. Coverage notes & gaps (V1)

Covered: linear stream, stall, N=0/1, abort, done hold.

Deferred to V2 / integration:

- Kernel / stride / padding address math
- Coupling to real Buffer Controller + FEATURE_ROWS / channels
- Max-length streams (`N=255`) soak
- Formal properties on handshake (optional)

---

## 10. Maintenance

Address-map or handshake changes require updates to this plan, `test_agu.py`, and `README.md`.
