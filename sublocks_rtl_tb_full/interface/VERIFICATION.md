# MMIF verification

## Scope

Unit-test `ai_byte_mmif` decode and inout behaviour with stubbed RF/BC responses (no control_block, no SRAMs, no chip top).

## Suite (`make`)

| Test | Intent |
|------|--------|
| `test_rf_write_decode` | Non-0x6 write → `reg_we`, not BC |
| `test_rf_read_decode` | Non-0x6 read → `reg_re`, `data` = `reg_rdata` |
| `test_buffer_data_write` | 0x6 write → `cpu_*` + select/addr context |
| `test_buffer_data_read` | 0x6 read → `data` = `cpu_rdata` |
| `test_data_hiz_when_idle` | Hi-Z when idle / write |
| `test_irq_passthrough` | `irq` = `irq_i` |
| `test_reserved_addr_not_buffer` | Reserved RF addr never hits BC |
| `test_we_priority_over_re` | `we`+`re` → no MMIF drive on `data` |
| `test_buffer_select_low_bits` | `cpu_buf_sel` = `buffer_select_i[1:0]` |

## Out of scope

- RF / BC / CU / SRAM behaviour
- Chip top (MMIF + control_block + buffers)
- Multi-cycle / READY protocols (none by design)
