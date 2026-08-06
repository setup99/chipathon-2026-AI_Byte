# SRAM Buffers — Cocotb Verification Plan

**DUT (cell):** `ai_byte_sram_buffer.v` (`ai_byte_sram_buffer`)  
**DUT (bank):** `ai_byte_buffers.v` (`ai_byte_buffers`)  
**TB wrappers:** `sram_buffer_dut.v`, `buffers_dut.v` (**DEPTH=16** for speed)  
**Tests:** `test_sram_buffer.py`, `test_buffers.py`  
**Status:** `sram_buffer` **6/6 PASS**, `buffers` **3/3 PASS**

Related: architecture § buffers (3× single-port INT8 SRAM), `../buffer_ctrl/README.md`

---

## 1. Purpose

Provide synthesizable behavioral models of the three accelerator buffers with **parameterized size**, and verify:

- Sync single-port write / read timing expected by the Buffer Controller
- Chip-enable gating
- Independence of Act / Weight / Result banks

Production depth defaults to **256**; tests use **16** via wrappers so size stays easy to change without editing the TB each time.

---

## 2. How to change buffer size later

At the top-level (or control-block) instantiation:

```verilog
ai_byte_buffers #(
    .DEPTH  (512),   // entries per buffer
    .DATA_W (8)      // INT8
) u_buffers ( ... );
```

Also update Buffer Controller to match:

```verilog
ai_byte_buffer_ctrl #(
    .BUFFER_DEPTH  (512),
    .BUFFER_ADDR_W (9)     // $clog2(512)
) u_bc ( ... );
```

`ADDR_W` defaults to `$clog2(DEPTH)` if omitted.

For foundry SRAM: keep the same ports (`clk, ce, we, addr, wdata, rdata`) and swap the body of `ai_byte_sram_buffer`.

---

## 3. Timing contract

```text
Write:  ce=1, we=1  → mem[addr] updated on posedge clk
Read:   ce=1, we=0  → rdata    updated on posedge clk (sync)
Idle:   ce=0        → no write; rdata holds
```

Soft-reset does **not** clear memory (architecture rule).

---

## 4. Features under test

| ID | Feature |
|----|---------|
| BUF-F1 | Power-on / initial `rdata=0`, mem zeroed |
| BUF-F2 | Write then readback (sparse addresses) |
| BUF-F3 | Full DEPTH walking pattern |
| BUF-F4 | `ce=0` blocks writes |
| BUF-F5 | `ce=0` holds `rdata` |
| BUF-F6 | Overwrite same address |
| BUF-F7 | Three banks are independent |
| BUF-F8 | Parallel same-address writes to Act/Wt/Res (no crosstalk) |
| BUF-F9 | Per-bank unique fill across DEPTH |

---

## 5. Test case map

### `test_sram_buffer.py` → `sram_buffer_dut`

| Test | Covers |
|------|--------|
| `test_reset_rdata_zero` | BUF-F1 |
| `test_write_readback` | BUF-F2 |
| `test_full_walking_pattern` | BUF-F3 |
| `test_ce_low_no_write` | BUF-F4 |
| `test_ce_low_holds_rdata` | BUF-F5 |
| `test_overwrite` | BUF-F6 |

### `test_buffers.py` → `buffers_dut`

| Test | Covers |
|------|--------|
| `test_three_buffers_independent` | BUF-F7 |
| `test_parallel_same_address` | BUF-F8 |
| `test_bank_fill_unique_patterns` | BUF-F9 |

---

## 6. How to run

```bash
cd buffers
make sram_buffer   # single cell
make buffers       # Act+Weight+Result bank
```

---

## 7. Gaps (V1)

- Not co-sim’d here with Buffer Controller (BC TB still uses Python SRAM stub)
- No GF180 macro timing / BIST
- No intentional out-of-range address stress beyond `addr < DEPTH` guard
- Default DEPTH=256 not sweep-tested (wrapper uses 16); change wrapper localparam to re-run at 256 if needed

---

## 8. Next integration step

Wire `ai_byte_buffers` to `ai_byte_control_block` / BC `sram_*` ports and retire the Python memory model in the control-block TB.
