# Signoff reports — `A02_A` user macro @ 140 ns (Exp8c)

Source run: `librelane/runs/RUN_2026-08-28_10-25-59/`  
Clock: 140 ns (~7.14 MHz) · Config: `librelane/config_a02_user_macro.yaml`  
Top: `A02_A` (1110×1110 µm D10-style organizer DEF + power connectors)

**Summary:** DRC / LVS / antenna **clean** · setup / hold **PASS** (9 GF180 corners) · post-PnR max slew @ `max_ss_125C_4v50`: **58** (worst **4.85 ns** vs SDC 4 ns; **0** cap / fanout)

| File | Check |
|------|-------|
| `drc.magic.rpt` | Magic DRC |
| `drc.klayout.json` | KLayout DRC |
| `lvs.netgen.rpt` | Netgen LVS |
| `irdrop.rpt` | OpenROAD PDN IR drop |
| `manufacturability.rpt` | Antenna / LVS / DRC summary |
| `metrics.csv` / `metrics.json` | LibreLane final metrics |
| `sta_summary.rpt` | Post-PnR STA (9 corners) |

**Tapeout deliverables (repo root):**

| Path | Role |
|------|------|
| `gds/A02_A.gds` | Submission GDS (`lvs_config.json` → `LAYOUT_FILE`) |
| `verilog/gl/A02_A.v` | Gate-level netlist (`lvs_config.json` → `LVS_VERILOG_FILES`) |
| `info.yaml` | 146-pin A02_A abutment list (DEF order) |
| `lvs_config.json` | `TOP_SOURCE` / `TOP_LAYOUT` = `A02_A` |

Signoff reports and `metrics.csv` / `metrics.json` for this run are in **this directory** (`docs/signoff_a02_macro/`). LibreLane also writes a local `final_a02_macro/` tree when you run the flow; that folder is gitignored.

## How to reproduce

```bash
make clone-pdk && make check-pdk

# Phase 1 — synth → GRT → hub upsize repair (step 41)
make librelane-a02-macro-rerun-postgrt

# Phase 2 — DR → DRC/LVS → signoff (or resume if interrupted)
make librelane-a02-macro-rerun-postgrt-signoff

# If only manufacturability report was interrupted:
make librelane-a02-macro-resume FROM=Misc.ReportManufacturability
```

Fresh full run from scratch:

```bash
make librelane-a02-macro-fresh
```

## PnR / repair strategy (Exp8c)

| Knob | Value |
|------|-------|
| `CLOCK_PERIOD` | 140 ns |
| `MAX_TRANSITION_CONSTRAINT` | 4 ns |
| Post-GRT repair | `AIByte.RepairDesignPostGRTSizeFirst` (replaces stock step) |
| Hub upsize | 12 named `buf_1 → buf_2` slew hubs before generic upsize |
| RSZ-0074 | Tolerated with GRT refresh (6 retries) |

Compared to Exp8a (stock post-GRT repair only): max slew **173 → 58** @ `max_ss_125C_4v50`.

## Residual post-PnR items (accepted for tapeout)

| Item | Count | Notes |
|------|-------|-------|
| Max slew | 58 @ `max_ss`, 6 @ `nom_ss` / `min_ss` | SDC 4 ns limit; setup/hold still clean |
| Unannotated nets | 757 | 753 `clkload*` + 4 unused inputs (`debug_state_IN`, `irq_IN`) |
| Disconnected pins | 4 | Optional top-level inputs; **0 critical** |
| Floating nets | 2 | `VDD` / `VSS` at connector black-box boundary |
| Lint warnings | 393 | Verilog style; **0** errors |

Real signoff criterion for Chipathon macro: **DRC + LVS + antenna clean + timing closed**, which this run satisfies.
