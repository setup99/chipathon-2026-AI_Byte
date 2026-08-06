# AI_BYTE dry-run layout report (2026-08-06)

Status: **WIP checkpoint for Chipathon DRC dry-run / system test**.  
Not a DRC/LVS-clean tapeout candidate. Final submission still requires a clean workshop `chip_top` GDS.

| Item | Value |
|------|--------|
| Run tag | `librelane/runs/RUN_2026-08-06_13-06-45` |
| Top | `ai_byte_top` (digital **core only**, no padframe) |
| Flow command | `make librelane-core` |
| Config | `librelane/config_ai_byte_core.yaml` (+ Makefile density/die override) |
| GDS (for dry-run push) | `gds/ai_byte_top.gds` ← copy of `…/final/gds/ai_byte_top.gds` |
| PDK / SCL | GF180MCU 1.8.0 (`gf180mcuD`), `gf180mcu_fd_sc_mcu9t5v0` |

---

## 1. Config used

### Floorplan / density / clock

| Parameter | Value | Notes |
|-----------|--------|--------|
| `DIE_AREA` | 1100 × 1100 µm | Absolute FP |
| `CORE_AREA` | 10 … 1090 µm (margin 10 µm) | |
| `PL_TARGET_DENSITY_PCT` | 55 | |
| `CLOCK_PORT` / `CLOCK_NET` | `clk` | Bare MMIF (no pads) |
| `CLOCK_PERIOD` | **100 ns (10 MHz)** | 40 ns / 25 MHz fails SS pre-PnR (~73 ns `period_min`) |
| `GRT_ALLOW_CONGESTION` | true | |
| Hold margins | PL 0.35 / GRT 0.3 | |

### Routing / antenna (deliberately capped for turnaround)

| Parameter | Value | Effect |
|-----------|------:|--------|
| `DRT_OPT_ITERS` | **15** | Max TritonRoute iters **per** `detailed_route` (default 64) |
| `DRT_ANTENNA_REPAIR_ITERS` | **0** | No post-DRT antenna → DRT re-runs |
| `ERROR_ON_MAGIC_DRC` | False | Magic DRC does not hard-fail the flow |

PDN: core ring on, pads not connected (`PDN_CORE_RING_CONNECT_TO_PADS: False`), M2/M3 straps.

Full chip + workshop padring still uses `librelane/config.yaml` + `SLOT=workshop make librelane` (not this run).

---

## 2. Synthesis (Yosys) — basic results

From `06-yosys-synthesis` on this run:

| Metric | Value |
|--------|------:|
| Mapped cells (`ai_byte_top`) | **~19 020** |
| Flip-flops | **3 178** (`dffq` 2532 + `dffrnq` 643 + `dffsnq` 3) |
| Chip area (synth report) | **~0.645 mm²** (645 175 µm²) |
| Sequential share of that area | ~40% |
| Synth check errors | **0** |

Pre-PnR STA (`12-openroad-staprepnr`), `clk` `period_min` / `fmax`:

| Corner | period_min | fmax |
|--------|----------:|-----:|
| nom_ss_125C_4v50 | **72.61 ns** | ~13.8 MHz |
| nom_tt_025C_5v00 | 36.72 ns | ~27.2 MHz |
| nom_ff_n40C_5v50 | 7.88 ns | ~127 MHz |

That is why the target clock is 10 MHz (100 ns), not 25 MHz.

---

## 3. Post-PnR snapshot

| Metric | Value |
|--------|------:|
| Die / core area | 1.21 / 1.165 mm² |
| Instance count (all) | 50 734 (incl. fill/tap) |
| Stdcell count | 29 915 |
| Sequential cells | 3 178 |
| Stdcell utilization | ~82% |
| Routed wirelength | ~2.19e6 µm |
| Vias | ~198 675 |

Post-route setup worst slack (max_ss): **≈ −19.8 ns** (still failing SS at 100 ns target after incomplete/messy routing). Hold WS positive on reported corners.

---

## 4. Errors at end of flow — and why

LibreLane finished all steps and wrote `final/`, then exited with **deferred** checker failures (`error.log`):

| Check | Count | Why |
|-------|------:|-----|
| **Routing DRC** (TritonRoute) | **706** | DRT stopped at iter **15** with shorts/spacing still open (`15893 → … → 706`). Root cause of most downstream noise. |
| **KLayout DRC** | **134** | Physical violations on a layout that never finished clean routing. |
| **Magic DRC** | **146** | Same; warned only (`ERROR_ON_MAGIC_DRC: false`). |
| **XOR** | **3** | Magic vs KLayout streamout mismatch (often secondary to DRC/extraction issues). |
| **LVS** | **323** | Netlist ↔ layout mismatch driven by unfinished/broken routes and extraction. |
| Antennas (post-route) | 17 nets | Post-DRT antenna repair was **disabled** (`DRT_ANTENNA_REPAIR_ITERS: 0`). |

`ERROR_ON_TR_DRC`, `ERROR_ON_KLAYOUT_DRC`, `ERROR_ON_LVS_ERROR`, and `ERROR_ON_XOR_ERROR` are true by default → flow reports failure even though GDS was produced.

### Intentional trade-off

We capped `DRT_OPT_ITERS=15` and turned off post-DRT antenna loops so a dry-run GDS could be produced in one day. Earlier uncapped runs spent many hours in DRT (still not fully clean). **This GDS proves the RTL→LibreLane→GDS path; it is not manufacturable.**

---

## 5. What to fix before final / Channel Partner

1. Raise routing budget (`DRT_OPT_ITERS` toward 64) and/or re-enable limited `DRT_ANTENNA_REPAIR_ITERS`.
2. Ease congestion: larger die and/or lower `PL_TARGET_DENSITY_PCT`, keep `GRT_ALLOW_CONGESTION` only as needed.
3. Recover SS timing (pipelining / multi-cycle / period) once routes are clean.
4. Integrate into workshop padframe: `SLOT=workshop make librelane` → submit **`chip_top.gds`**, not bare `ai_byte_top`.

---

## 6. Artifacts

| Path | Role |
|------|------|
| `gds/ai_byte_top.gds` | Dry-run layout pointed to by `lvs_config.json` |
| `librelane/runs/RUN_2026-08-06_13-06-45/final/` | Full views + `metrics.json` / `metrics.csv` (local; `final/` gitignored) |
| `librelane/runs/…/final/render/ai_byte_top.png` | Quick visual |
| `info.yaml` / `lvs_config.json` | Chipathon metadata (`TOP_SOURCE=ai_byte_top`) |
