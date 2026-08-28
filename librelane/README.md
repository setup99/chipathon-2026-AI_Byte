# LibreLane — setup and run

Place-and-route for **AI_BYTE** on GF180MCU (`gf180mcuD`).  
Run all commands from the **repo root** (`chipathon-2026-AI_Byte/`), not from this folder.


| Flow                                     | Config                                     | Top           | Output                   |
| ---------------------------------------- | ------------------------------------------ | ------------- | ------------------------ |
| **A02 tapeout macro** — organizer block  | `config_a02_user_macro.yaml`               | `A02_A`       | `final_a02_macro/`       |
| **Step A** — harden core macro           | `config_ai_byte_core.yaml`                 | `ai_byte_top` | `final_core/`            |
| **Step B** — place macro + workshop pads | `config.yaml` + `slots/slot_workshop.yaml` | `chip_top`    | `final/gds/chip_top.gds` |
| Alternate — flat (no macro)              | `config_flat.yaml`                         | `chip_top`    | `final/`                 |


Default full-chip slot: **workshop**. Default core die: **1100 × 1100 µm**, density **55%**, clock **10 MHz** (100 ns).

---



## Required stdcell library: `mcu7t5v0`

**All team LibreLane runs must use** `gf180mcu_fd_sc_mcu7t5v0`**.**  
Do **not** use `gf180mcu_fd_sc_mcu9t5v0` unless you are deliberately comparing libraries.


| Item            | Value                                                               |
| --------------- | ------------------------------------------------------------------- |
| PDK             | `gf180mcuD`                                                         |
| Stdcell (SCL)   | `gf180mcu_fd_sc_mcu7t5v0`                                           |
| Where it is set | Repo root `Makefile` (`STD_CELL_LIBRARY := …`)                      |
| How to confirm  | `make help` → must print `STD_CELL_LIBRARY=gf180mcu_fd_sc_mcu7t5v0` |


`make librelane`, `make librelane-core`, and the `*-nodrc` variants all pass `--scl gf180mcu_fd_sc_mcu7t5v0` automatically. Pull the latest Makefile so everyone’s runs match.

---



## 1. Clone the repo

```bash
git clone <repo-url> chipathon-2026-AI_Byte
cd chipathon-2026-AI_Byte
```

---



## 2. One-time host setup



### Requirements

- Linux (x86_64 or aarch64)
- ~20 GB free disk (tools + PDK + run artifacts)
- [Nix](https://nixos.org/download/) with flakes enabled

```bash
# Install Nix (if needed)
curl -L https://nixos.org/nix/install | sh

# Enable flakes
mkdir -p ~/.config/nix
echo 'experimental-features = nix-command flakes' >> ~/.config/nix/nix.conf
```

Accept the Fossi-Foundation binary cache the first time you enter `nix-shell` (configured in `flake.nix`). That keeps the first tool fetch to minutes instead of hours.

---



## 3. Enter the tool environment

```bash
nix-shell
```

This gives you LibreLane **3.0.0**, OpenROAD, Yosys, KLayout, Magic, etc. Stay in this shell for the steps below.

---



## 4. Install the PDK (once)

```bash
make clone-pdk
make check-pdk
```

PDK lands at `~/.cache/ai-byte/pdk/gf180mcu` (tag **1.8.0**).  
It is **not** deleted by normal LibreLane runs. To wipe and re-clone:

```bash
make force-clone-pdk
```

---



## 5. Run the flow (Crispi-style: core macro → padring)

Same approach as Team Crispi’s layout review:

1. Harden the digital core as a standalone macro (no pads).
2. Place that macro inside the **chipathon workshop padring** (`SLOT=workshop`).

```text
make librelane-core          →  final_core/  (ai_byte_top GDS/LEF/nl/lib)
SLOT=workshop make librelane →  final/gds/chip_top.gds
        │
        └─ chip_top pads + chip_core + MACROS[ai_byte_top]
```



### Step A — Harden the core (`config_ai_byte_core.yaml`)

```bash
make librelane-core-nodrc          # fast iteration (skip DRC)
# make librelane-core              # + DRC when you want a cleaner macro
```

Optional floorplan overrides:

```bash
make librelane-core-nodrc CORE_SIDE=1200 PL_DENSITY=55
```


| Variable      | Default | Meaning                       |
| ------------- | ------- | ----------------------------- |
| `CORE_SIDE`   | `1110`  | Die side length in µm (A02_A block) |
| `PL_DENSITY`  | `55`    | Target placement density (%)  |
| `CORE_MARGIN` | `10`    | Core inset from die edge (µm) |


Views land in `final_core/` (`gds/`, `lef/`, `nl/`, `lib/<corner>/`).  
`make librelane` will refuse to start until those views exist (`make check-core-macro`).

### Step B — Integrate macro into workshop padring (`config.yaml`)

Uses this repo’s chipathon-2026 padframe (`chip_top` + `slot_workshop.yaml`).  
Only `chip_top.sv` + `chip_core.sv` are synthesized; `ai_byte_top` is a **blackboxed macro** from `final_core/`.

```bash
make check-core-macro              # optional sanity check
SLOT=workshop make librelane-nodrc # iterate without DRC
SLOT=workshop make librelane       # full Chip flow → submit this GDS
```

Macro instance: `i_chip_core.u_ai_byte` at **[500, 500] µm** (edit `MACROS.ai_byte_top.instances` in `config.yaml` to move it).  
PDN hooks: `PDN_MACRO_CONNECTIONS` → `.*u_ai_byte.* VDD VSS VDD VSS`.

Output: `final/gds/chip_top.gds`.

Expect on the order of **~2+ hours** for a full chip run on a modern laptop.

### Alternate — flat chip (re-synth all RTL, no macro)

```bash
make librelane-flat
# make librelane-flat-nodrc
```

Uses `config_flat.yaml`. Prefer the hierarchical path above for Crispi-style integration.

---



## 6. Check results


| What                                  | Where                                                                           |
| ------------------------------------- | ------------------------------------------------------------------------------- |
| A02 tapeout macro GDS / LEF / NL      | `final_a02_macro/`                                                              |
| A02 signoff reports                   | `docs/signoff_a02_macro/`                                                       |
| Core macro GDS / LEF / netlist / libs | `final_core/`                                                                   |
| Full-chip GDS (submission)            | `final/gds/chip_top.gds`                                                        |
| Metrics                               | `final/metrics.csv` or `final_core/…` / last `librelane/runs/*/final/metrics.*` |
| Flow log                              | `librelane/runs/<RUN_TAG>/flow.log`                                             |


Open the last run:

```bash
make librelane-openroad   # OpenROAD GUI
make librelane-klayout    # KLayout
```

---



## What’s in this folder

```text
librelane/
├── config_a02_user_macro.yaml # A02 tapeout macro (A02_A, organizer DEF)
├── config_ai_byte_core.yaml   # Step A: Classic — harden ai_byte_top
├── config.yaml                # Step B: Chip — place core macro + workshop pads
├── config_flat.yaml           # Alternate: flat Chip (all RTL re-synth)
├── A02_A.sdc                  # A02 macro timing constraints
├── ai_byte_top.sdc            # core timing constraints
├── chip_top.sdc               # full-chip timing constraints
├── scripts/repair_design_postgrt_size_first.tcl
├── pdn_cfg.tcl                # power grid
├── slots/                     # padframe slot definitions (incl. workshop)
└── runs/                      # LibreLane run directories (generated)
```

---



## Common targets

```bash
make help                  # list all Makefile targets
make clone-pdk             # install PDK once
make check-pdk             # verify PDK is present
make librelane-core-nodrc  # Step A: core macro, no DRC
make librelane-core        # Step A: core macro + DRC
make check-core-macro      # verify final_core views before Step B
make librelane             # Step B: hierarchical chip + pads
make librelane-nodrc        # Step B without DRC
make librelane-flat         # alternate flat chip (no macro)
make librelane-padring      # generate padring only
```

---



## Troubleshooting


| Problem                    | Fix                                                                              |
| -------------------------- | -------------------------------------------------------------------------------- |
| `MISSING PDK`              | `make clone-pdk` then `make check-pdk`                                           |
| Incomplete PDK tree        | `make force-clone-pdk` (slow)                                                    |
| Want a different PDK path  | `make librelane-core PDK_ROOT=/other/path/gf180mcu`                              |
| `check-core-macro` fails   | Run `make librelane-core` (or `-nodrc`) first; need 7t views in `final_core/`    |
| Accidentally still on 9t   | Pull latest Makefile; `make help` must show `mcu7t5v0`                           |
| Need faster turnaround     | Use `*-nodrc` targets while exploring                                            |
| Full signoff for chipathon | Hierarchical: Step A then `SLOT=workshop make librelane` → submit `chip_top.gds` |


More detail: `[docs/reproducing-native.md](../docs/reproducing-native.md)`.  
Docker inspection path (not the pinned build): `[docs/reproducing-docker.md](../docs/reproducing-docker.md)`.