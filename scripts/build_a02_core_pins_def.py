#!/usr/bin/env python3
"""Build LibreLane FP_DEF_TEMPLATE for ai_byte_top from A02_A organizer pins.

Keeps only the 22 core ports (info.yaml / ai_byte_top), on Metal2, in user-block
coordinates matching A02_A.def DIEAREA (1110 x 1110 um @ 200 dbu/um).

Terminal policy (one geometry set per core port):
  VDD/VSS     — all DVDD/DVSS rectangles
  inputs      — IO cell Y  (clk, addr, re, we, rst_n)
  outputs     — IO cell A  (irq, debug_state)  [project_pin *_OUT]
  bidir data  — IO cell Y  (data_IN) as the single inout abutment site
                (organizers wire A/OE/IE with glue; see README / chip_top)

Writes:
  librelane/floorplan/A02_A_core_pins.def
  librelane/floorplan/A02_A_core_pins_map.json
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

try:
    import yaml
except ImportError:
    print("need PyYAML: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[1]
IFACE = ROOT / "A02.def (1)/A02/project_defs/A/A02_A_interface.yaml"
OUT_DIR = ROOT / "librelane" / "floorplan"
OUT_DEF = OUT_DIR / "A02_A_core_pins.def"
OUT_MAP = OUT_DIR / "A02_A_core_pins_map.json"

SRC_UNITS = 200   # translated_user units in A02_A_interface.yaml
UNITS = 2000      # DEF dbu/um expected by OpenROAD in this flow
DIE_UM = 1110
DIE_DBU = DIE_UM * UNITS

# Core port -> which interface entry to keep (by cell_terminal).
# data / irq / debug: see module docstring.
TERMINAL_POLICY = {
    "VSS": "DVSS",
    "VDD": "DVDD",
    "clk": "Y",
    "rst_n": "Y",
    "re": "Y",
    "we": "Y",
    "addr[0]": "Y",
    "addr[1]": "Y",
    "addr[2]": "Y",
    "addr[3]": "Y",
    "data[0]": "Y",
    "data[1]": "Y",
    "data[2]": "Y",
    "data[3]": "Y",
    "data[4]": "Y",
    "data[5]": "Y",
    "data[6]": "Y",
    "data[7]": "Y",
    "irq": "A",
    "debug_state[0]": "A",
    "debug_state[1]": "A",
    "debug_state[2]": "A",
}

CORE_PIN_ORDER = [
    "VSS",
    "VDD",
    "clk",
    "data[7]",
    "data[5]",
    "data[6]",
    "data[4]",
    "data[0]",
    "data[1]",
    "data[2]",
    "data[3]",
    "addr[0]",
    "addr[1]",
    "addr[2]",
    "addr[3]",
    "irq",
    "re",
    "debug_state[0]",
    "debug_state[2]",
    "debug_state[1]",
    "we",
    "rst_n",
]


def def_direction(core_name: str, iface_dir: str) -> str:
    if core_name in ("VDD", "VSS"):
        return "INOUT"
    if core_name.startswith("data["):
        return "INOUT"
    if core_name in ("irq",) or core_name.startswith("debug_state"):
        return "OUTPUT"
    return "INPUT"


def def_use(core_name: str) -> str:
    if core_name == "VDD":
        return "POWER"
    if core_name == "VSS":
        return "GROUND"
    return "SIGNAL"


def main() -> None:
    if not IFACE.is_file():
        print(f"missing {IFACE}", file=sys.stderr)
        sys.exit(1)

    data = yaml.safe_load(IFACE.read_text())
    by_user: dict[str, list] = defaultdict(list)
    for pin in data["pins"]:
        by_user[pin["user_pin_name"]].append(pin)

    size = data.get("size_microns") or [str(DIE_UM), str(DIE_UM)]
    if float(size[0]) != DIE_UM or float(size[1]) != DIE_UM:
        print(
            f"warning: interface size_microns={size} but script DIE_UM={DIE_UM}",
            file=sys.stderr,
        )

    selected = []
    mapping = []
    missing = []

    for core_name in CORE_PIN_ORDER:
        want_term = TERMINAL_POLICY[core_name]
        cands = by_user.get(core_name, [])
        match = [p for p in cands if p.get("cell_terminal") == want_term]
        if not match:
            missing.append((core_name, want_term))
            continue
        # Prefer project_pin == core_name when present (clk, addr, re, …)
        match.sort(
            key=lambda p: (
                0 if p.get("project_pin") == core_name else 1,
                p.get("project_pin") or "",
            )
        )
        pin = match[0]
        rects = []
        for r in pin["rectangles"]:
            if r.get("routing_layer") != "Metal2":
                continue
            tu = r["translated_user"]
            scale = UNITS / SRC_UNITS
            rects.append(
                [
                    int(round(tu[0] * scale)),
                    int(round(tu[1] * scale)),
                    int(round(tu[2] * scale)),
                    int(round(tu[3] * scale)),
                ]
            )
        if not rects:
            missing.append((core_name, want_term + ":no_M2"))
            continue

        selected.append(
            {
                "name": core_name,
                "direction": def_direction(core_name, pin["direction"]),
                "use": def_use(core_name),
                "rects": rects,
            }
        )
        mapping.append(
            {
                "core_pin": core_name,
                "cell_terminal": want_term,
                "project_pin": pin["project_pin"],
                "padring_instance": pin["padring_instance"],
                "cell": pin["cell"],
                "n_rects": len(rects),
                "rects_dbu": rects,
            }
        )

    if missing:
        print("ERROR: missing pin selections:", missing, file=sys.stderr)
        sys.exit(1)
    if len(selected) != 22:
        print(f"ERROR: expected 22 pins, got {len(selected)}", file=sys.stderr)
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    lines = [
        "VERSION 5.8 ;",
        'DIVIDERCHAR "/" ;',
        'BUSBITCHARS "[]" ;',
        "DESIGN ai_byte_top ;",
        f"UNITS DISTANCE MICRONS {UNITS} ;",
        f"DIEAREA ( 0 0 ) ( {DIE_DBU} {DIE_DBU} ) ;",
        f"PINS {len(selected)} ;",
    ]
    for p in selected:
        lines.append(
            f"- {p['name']} + NET {p['name']} + DIRECTION {p['direction']} "
            f"+ USE {p['use']}"
        )
        for x1, y1, x2, y2 in p["rects"]:
            lines.append(f"  + LAYER Metal2 ( {x1} {y1} ) ( {x2} {y2} )")
        lines.append("  + FIXED ( 0 0 ) N ;")
    lines.append("END PINS")
    lines.append("END DESIGN")
    OUT_DEF.write_text("\n".join(lines) + "\n")

    OUT_MAP.write_text(
        json.dumps(
            {
                "die_um": [DIE_UM, DIE_UM],
                "units_dbu_per_um": UNITS,
                "source_units_dbu_per_um": SRC_UNITS,
                "source_interface": str(IFACE.relative_to(ROOT)),
                "policy": {
                    "inputs": "Y",
                    "outputs_irq_debug": "A",
                    "data_bidir": "Y (data_IN)",
                    "power": "all DVDD/DVSS rects",
                },
                "pins": mapping,
            },
            indent=2,
        )
        + "\n"
    )

    print(f"wrote {OUT_DEF.relative_to(ROOT)}  ({len(selected)} pins, {DIE_UM} µm)")
    print(f"wrote {OUT_MAP.relative_to(ROOT)}")
    for m in mapping:
        um = [
            [c / UNITS for c in m["rects_dbu"][0][:2]],
            [c / UNITS for c in m["rects_dbu"][0][2:]],
        ]
        print(
            f"  {m['core_pin']:16s} <- {m['project_pin']:20s} "
            f"term={m['cell_terminal']:4s}  "
            f"first_rect_um={um[0]}-{um[1]}  n={m['n_rects']}"
        )


if __name__ == "__main__":
    main()
