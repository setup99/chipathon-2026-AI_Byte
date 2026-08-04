# AI_BYTE Buffers (Act / Weight / Result SRAM)

**RTL:** `ai_byte_sram_buffer.v`, `ai_byte_buffers.v`  
**Cocotb:** `test_sram_buffer.py`, `test_buffers.py`  
**Wrappers (DEPTH=16):** `sram_buffer_dut.v`, `buffers_dut.v`  
**Plan:** [VERIFICATION.md](VERIFICATION.md)

## Role

Three parameterized single-port sync SRAMs used by the Buffer Controller.  
Default size is 256×8; change with `.DEPTH` / `.DATA_W` at instantiation.

## Run

```bash
cd buffers
make              # both suites
make sram_buffer  # single cell only
make buffers      # bank only
```

Requires repo `.venv` with cocotb (`pip install -r requirements-cocotb.txt` from repo root).
