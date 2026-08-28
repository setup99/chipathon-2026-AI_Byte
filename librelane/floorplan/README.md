# A02 core pin DEF (FP_DEF_TEMPLATE)

## D10-style (full organizer DEF) — preferred for Metal2 abutment

```bash
make build-a02-d10-style
make librelane-a02-macro-nodrc   # iterate
make librelane-a02-macro         # full flow (DRC + LVS + IR-drop; no skips)
```

| File | Role |
|------|------|
| `A02_A_full.def` | Organizer `A02_A.def` with UNITS 200→2000, all **146** pins |
| `../src/a02/A02_A.v` | Pad-control wrapper + `ai_byte_top` + power connectors |

## Legacy filtered 22-pin core

```bash
make build-a02-core-pins-def
# or: python3 scripts/build_a02_core_pins_def.py
```

| File | Role |
|------|------|
| `A02_A_core_pins.def` | LibreLane `FP_DEF_TEMPLATE` — 22 pins, Metal2, 1110×1110 µm |
| `A02_A_core_pins_map.json` | Which pad terminal each core pin used |

## Mapping policy (filtered path)

| Core port | Pad terminal used |
|-----------|-------------------|
| `VDD` / `VSS` | All DVDD / DVSS Metal2 rects |
| Inputs (`clk`, `addr`, `re`, `we`, `rst_n`) | **Y** |
| `irq`, `debug_state[*]` | **A** (`*_OUT`) |
| `data[*]` (inout) | **Y** (`data_IN`) — single abutment; OE/IE glue stays outside |

## Harden (filtered path)

```bash
make librelane-core-a02-setup
make librelane-core-nodrc CORE_SIDE=1110   # iterate
make librelane-core CORE_SIDE=1110         # signoff DRC/LVS
make audit-a02-pins
```
