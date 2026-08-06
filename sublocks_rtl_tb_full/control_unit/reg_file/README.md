# AI_BYTE Register File (RF)

**Version:** V1.0  
**Status:** RTL + cocotb — see VERIFICATION.md  
**RTL:** `reg_file.v` (`ai_byte_reg_file`)  
**TB (cocotb):** `test_reg_file.py` — see [VERIFICATION.md](VERIFICATION.md)

---

## Role

Shared 8-bit configuration bank. Continuously broadcasts to FSM, AGU, and Buffer Controller.

Does **not** store `BUFFER_DATA`, generate STATUS bits, or decode instructions.

---

## Design (V1)

- One Verilog module, no internal FSM, no hierarchy
- Registered writes, combinational read mux
- CONTROL bits are **pulse-only**; CONTROL always reads `0x00`
- STATUS is an external mirror (`status_i`)
- VERSION hardwired `0x01`
- `BUFFER_ADDR` auto-increments on `buffer_addr_inc` (CPU write wins same cycle)

---

## Run tests

```bash
cd reg_file
make        # cocotb
```

---

## Directed coverage

| Test | Result |
|------|--------|
| Reset / VERSION | PASS |
| R/W + broadcast | PASS |
| STATUS / VERSION RO | PASS |
| Reserved addrs | PASS |
| CONTROL pulses (START / SOFT_RESET / IRQ_CLEAR) | PASS |
| START ignored when busy | PASS |
| Soft-reset preserves storage | PASS |
| `buffer_addr_inc` + write priority | PASS |
