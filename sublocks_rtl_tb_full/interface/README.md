# Memory-Mapped Interface (MMIF)

Chip-facing decode between host pins and the control path.

| Item | Detail |
|------|--------|
| RTL | `ai_byte_mmif.v` |
| Tests | `test_mmif.py` (cocotb) |
| Run | `make` from this folder |

## Ports

**Pins:** `clk`, `rst_n`, `addr[3:0]`, `data[7:0]` (inout), `we`, `re`, `irq`

**Internal:** `reg_*` → RF, `cpu_*` → BC, `buffer_select_i` / `buffer_addr_i` from RF broadcast, `irq_i` from control block.

## Decode

- `addr != 0x6` → Register File
- `addr == 0x6` (`BUFFER_DATA`) → Buffer Controller, using RF `BUFFER_SELECT` / `BUFFER_ADDR`

Single-cycle. `data` driven only when `re=1` and `we=0`; otherwise Hi-Z.

No chip top in this folder — wire MMIF to `control_block` + buffers at integration time.
