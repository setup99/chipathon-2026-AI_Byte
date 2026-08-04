# AI_BYTE Address Generation Unit (AGU)

**Version:** V1.0 — Option A (Linear stream)  
**Status:** RTL + cocotb — see VERIFICATION.md  
**RTL:** `agu.v` (`ai_byte_agu`)  
**TB (cocotb):** `test_agu.py` — see [VERIFICATION.md](VERIFICATION.md)

---

## Role

Generate Act / Weight / Result addresses for the Buffer Controller.  
No data movement. CONV/FC only (ALU/EML unused).

---

## V1 behavior (Linear)

```text
N = FEATURE_COLS   (programmed by software)

for i in 0 .. N-1:
    act_addr = weight_addr = result_addr = i
    handshake addr_valid / addr_ready

agu_done = 1  (held until agu_en falls)
```

| Item | V1 |
|------|-----|
| Length | `feature_cols_i` |
| CONV vs FC | Same path |
| Kernel / stride / pad | Ignored (reserved for V2) |
| Start | `agu_en` from BC |
| Abort | `agu_en` low → idle |

Full sliding-window CONV→GEMM mapping is deferred.

---

## Run

```bash
cd agu
make        # cocotb
```
