# Fraunhofer device declaration — `A02_A` (Exp8c)

Source run: `librelane/runs/RUN_2026-08-28_10-25-59/`  
Layout: `gds/A02_A.gds` · Top: `A02_A` · Stdcell: `gf180mcu_fd_sc_mcu7t5v0`

This note maps **tapeout-form device names** (Fraunhofer GF180 configuration) to **open-source PDK / extraction names** so organizers can aggregate the project.

## Declared on GF180 configuration form (4 primitives only)

| Form group | Fraunhofer name | Checked |
|------------|-----------------|---------|
| MOSFET | **5V NMOS (Outside DNWELL)** `nmos_5p0` | Yes |
| MOSFET | **5V PMOS (Outside DNWELL)** `pmos_5p0` | Yes |
| Diode | **5V/6V N+/LVPWELL diode** `np_6p0` | Yes |
| Diode | **5V/6V P+/Nwell diode** `pn_6p0` | Yes |

**Not used:** 3.3 V / 6 V / 10 V devices, DNWELL-isolated NMOS, BJT, standalone resistors, MOS-cap layout primitives, SAB ESD FETs, MIM/metal resistors, fuse/MTP, **IO pad cells** (`gf180mcu_fd_io`).

Full form answers: `docs/tapeout_form/chipathon_2026_form_draft.md` (page 9).

## Open-source PDK name mapping

| Fraunhofer (form) | Magic / Netgen / SPICE (gf180mcuD) | Where it appears |
|-------------------|-----------------------------------|------------------|
| `nmos_5p0` | `nfet_05v0` | All `mcu7t5v0` logic, fill, decap (`fillcap_*`) |
| `pmos_5p0` | `pfet_05v0` | All `mcu7t5v0` logic, fill, decap |
| `np_6p0` | `diode_nd2ps_06v0` | `gf180mcu_fd_sc_mcu7t5v0__antenna` (post-route repair) |
| `pn_6p0` | `diode_pd2nw_06v0` | `gf180mcu_fd_sc_mcu7t5v0__antenna` |

Netgen LVS also references `nfet_06v0` / `pfet_06v0` inside antenna diode subcircuits; these are **not** separate form checkboxes — they are absorbed under the **diode** entries above.

**Metal-only macros (no semiconductors):** `vss_conn`, `vdd_conn` — power abutment bridges only.

## Extraction / LVS artifacts (in this directory)

| File | Role |
|------|------|
| `A02_A.spice` | Magic layout extraction netlist (`Magic.SpiceExtraction`, step 111) |
| `magic_extraction.log` | Magic extraction log |
| `lvs.report` | Netgen LVS log (`Netgen.LVS`, step 113) — device/net summary |
| `lvs.netgen.rpt` | Netgen LVS detailed report |
| `stdcell_instance_counts.txt` | Instance counts per extracted subcircuit |

## LVS summary (from `lvs.report`)

| Metric | Value |
|--------|-------|
| Layout devices | **28 621** |
| Source (Verilog) devices | **28 621** |
| Device count difference | **0** |
| Unmatched devices | **0** |
| Nets | **28 610** |
| Result | **Circuits match uniquely** |

`gf180mcu_fd_sc_mcu7t5v0__antenna` instances in extracted netlist: **14** (antenna repair diodes).

## Design composition (high level)

- **Digital stdcell only** — no custom transistor layout, no analog, no SRAM hard macro, no on-die pad ring.
- **SCL:** `gf180mcu_fd_sc_mcu7t5v0` (5 V, 7-track).
- **Top cells in extraction:** `A02_A` → `ai_byte_top` + `vss_conn` + `vdd_conn` + stdcell instances (see `stdcell_instance_counts.txt`).

## Reproduce

```bash
make librelane-a02-macro
# Artifacts: final_a02_macro/spice/A02_A.spice
#            librelane/runs/<tag>/113-netgen-lvs/netgen-lvs.log
```

Copy refreshed files into `docs/signoff_a02_macro/` before pushing to `main`.
