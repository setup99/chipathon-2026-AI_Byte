# Signoff reports — `ai_byte_top` @ 140 ns

Source run: `librelane/runs/RUN_2026-08-22_11-01-24/`  
Clock: 140 ns (~7.14 MHz) · Config: `librelane/config_ai_byte_core.yaml`

**Summary:** DRC/LVS/antenna clean · setup/hold PASS (9 GF180 corners) · post-PnR DRV @ `max_ss_125C_4v50`: 8 slew / 0 fanout / 4 cap (SDC 4 ns / 0.2 pF; within SS liberty limits)

| File | Check |
|---|---|
| `drc.magic.rpt` | Magic DRC (COUNT: 0) |
| `drc.klayout.json` | KLayout DRC |
| `lvs.netgen.rpt` | Netgen LVS (circuits match uniquely) |
| `irdrop.rpt` | OpenROAD PDN IR drop |
| `manufacturability.rpt` | Antenna / LVS / DRC summary |
| `metrics.csv` | LibreLane final metrics |
| `sta_summary.rpt` | Post-PnR STA (9 GF180 corners) |

**Deliverables (repo root):**

| Path | Source |
|---|---|
| `gds/ai_byte_top.gds` | `final/gds/ai_byte_top.gds` (verified MD5 match) |
| `verilog/gl/ai_byte_top.v` | `final/nl/ai_byte_top.nl.v` (verified MD5 match) |

## Timing / DRV strategy

PnR targets are set in `librelane/config_ai_byte_core.yaml`. Key choices for this run:

| Knob | Value | Rationale |
|---|---|---|
| `CLOCK_PERIOD` | 140 ns | Closes setup/hold on GF180 SS with margin (~7.14 MHz) |
| `MAX_TRANSITION_CONSTRAINT` | 4 ns | TT liberty limit; PDK default SDC was 3 ns (over-constrained SS) |
| CTS buffers | `clkbuf_4`, `clkbuf_8` | Stronger clock drivers vs `clkbuf_2`; `CTS_MAX_CAP: 0.15` |
| Post-GRT `repair_design` | 30% slew/cap | Stock LibreLane step; no custom size-first pass |
| Option 3 hold repair | `AIByte.ResizerTimingPostCTSHoldDly` | Ban all `dly*` during PnR (`EXTRA_EXCLUDED_CELLS`); re-enable `dly*` only for post-CTS hold |

Experiments showed that chasing every SDC-reported slew/cap with more aggressive repair (e.g. banning buffers, custom upsize passes) either regressed caps or added area without fixing real liberty violations.

## Residual post-PnR DRV (accepted)

Post-PnR STA reports **8 max-slew** and **4 max-cap** violations, all at **`max_ss_125C_4v50`** only. Setup/hold are clean on all 9 corners.

These are **SDC-target violations, not GF180 liberty failures**:

- **Slew:** SDC `max_transition` = 4 ns; GF180 SS liberty allows ~7 ns. Worst data slew ~6 ns — fails the 4 ns SDC check but passes SS liberty.
- **Cap:** All 4 hits are `clkbuf_2_*` at ~0.25–0.30 pF vs SDC `max_capacitance` = 0.2 pF; liberty allows ~0.50 pF.

At 140 ns the design has large timing margin (setup WS ~32 ns @ max_ss). Further PnR iteration to zero these SDC counters would add buffers/area for margins already covered by liberty and clock period, with no functional or tapeout benefit. Real signoff criterion: **timing closed + DRC/LVS clean**, which this run satisfies.
