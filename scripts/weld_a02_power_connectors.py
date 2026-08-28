#!/usr/bin/env python3
"""Weld A02 power connectors into staged final_core GDS + patch LEF Metal2 pins.

Does not require a full reharden. For a clean hierarchical flow, also enable
MACROS in librelane/config_ai_byte_core.yaml and re-run make librelane-core.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path[:0] = ["/usr/lib/klayout/pymod"]
import klayout.db as db

REPO = Path(__file__).resolve().parents[1]


def patch_lef(lef_path: Path, placement: dict, conn_dir: Path) -> None:
    """Add Metal2 PORTs from connector LEFs onto ai_byte_top VDD/VSS pins."""
    text = lef_path.read_text()
    for cell, meta in placement.items():
        if cell.endswith(".json") or not isinstance(meta, dict) or "net" not in meta:
            continue
        net = meta["net"]
        ox, oy = meta["location"]
        clef = (conn_dir / "lef" / f"{cell}.lef").read_text()
        # local Metal2 rects from connector LEF
        rects = re.findall(
            r"LAYER Metal2\s*;\s*RECT\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*;",
            clef,
        )
        if not rects:
            raise SystemExit(f"no Metal2 rects in {cell}.lef")
        # Insert after first PORT of PIN net (keep existing M4/M5)
        pin_re = re.compile(
            rf"(PIN {net}\s.*?PORT\s*\n)",
            re.S,
        )
        m = pin_re.search(text)
        if not m:
            raise SystemExit(f"PIN {net} not found in {lef_path}")
        extra = []
        for x1, y1, x2, y2 in rects:
            X1 = float(x1) + ox
            Y1 = float(y1) + oy
            X2 = float(x2) + ox
            Y2 = float(y2) + oy
            extra.append("      LAYER Metal2 ;")
            extra.append(f"        RECT {X1:.3f} {Y1:.3f} {X2:.3f} {Y2:.3f} ;")
        insert = m.group(1) + "\n".join(extra) + "\n"
        # only once
        text = pin_re.sub(insert, text, count=1)
        print(f"LEF: added {len(rects)} Metal2 ports on {net}")
    lef_path.write_text(text)


def weld_gds(core_gds: Path, conn_dir: Path, placement: dict, out_gds: Path) -> None:
    layout = db.Layout()
    layout.read(str(core_gds))
    top = layout.top_cell()
    if top is None:
        raise SystemExit(f"no top cell in {core_gds}")

    for cell_name, meta in placement.items():
        if not isinstance(meta, dict) or "location" not in meta:
            continue
        gds = conn_dir / "gds" / f"{cell_name}.gds"
        if not gds.is_file():
            raise SystemExit(f"missing {gds}")
        # Load connector into a temporary layout then copy cell
        cl = db.Layout()
        cl.read(str(gds))
        ctop = cl.top_cell()
        # If cell already exists, remove old instances of it first
        existing = layout.cell(cell_name)
        if existing is not None:
            # delete instances referencing this cell from top
            insts = [i for i in top.each_inst() if i.cell.name == cell_name]
            for i in insts:
                i.delete()
        # copy cell tree
        new_cell = layout.create_cell(cell_name)
        new_cell.copy_tree(ctop)
        x, y = meta["location"]
        # DTrans in µm
        top.insert(db.DCellInstArray(new_cell.cell_index(), db.DTrans(db.DVector(x, y))))
        print(f"GDS: placed {cell_name} at ({x}, {y}) into {top.name}")

    out_gds.parent.mkdir(parents=True, exist_ok=True)
    layout.write(str(out_gds))
    print(f"wrote {out_gds}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--conn-dir", type=Path, default=REPO / "connectors")
    ap.add_argument("--core-gds", type=Path, default=REPO / "final_core/gds/ai_byte_top.gds")
    ap.add_argument("--core-lef", type=Path, default=REPO / "final_core/lef/ai_byte_top.lef")
    ap.add_argument(
        "--backup",
        action="store_true",
        default=True,
        help="backup GDS/LEF before modifying",
    )
    args = ap.parse_args()

    place_path = args.conn_dir / "placement.json"
    if not place_path.is_file():
        raise SystemExit("run scripts/build_a02_power_connectors.py first")
    placement = json.loads(place_path.read_text())
    # strip non-cell keys
    cells = {k: v for k, v in placement.items() if isinstance(v, dict) and "location" in v}

    if args.backup:
        for p in (args.core_gds, args.core_lef):
            bak = p.with_suffix(p.suffix + ".pre_power_conn")
            if p.is_file() and not bak.is_file():
                shutil.copy2(p, bak)
                print(f"backup {bak}")

    weld_gds(args.core_gds, args.conn_dir, cells, args.core_gds)
    patch_lef(args.core_lef, cells, args.conn_dir)
    print("done — final_core GDS/LEF now expose Metal2 VDD/VSS at A02 template columns")


if __name__ == "__main__":
    main()
