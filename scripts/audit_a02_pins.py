#!/usr/bin/env python3
"""Audit ai_byte_top LEF pins vs A02_A_core_pins.def (Metal2 abutment).

PASS if each core pin has Metal2 geometry overlapping the template site.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEF = ROOT / "librelane" / "floorplan" / "A02_A_core_pins.def"
DEFAULT_LEF = ROOT / "final_core" / "lef" / "ai_byte_top.lef"


def parse_def_pins(path: Path) -> dict[str, list[tuple[str, float, float, float, float]]]:
    """name -> list of (layer, x1,y1,x2,y2) in microns."""
    text = path.read_text()
    um = re.search(r"UNITS DISTANCE MICRONS\s+(\d+)", text)
    units = int(um.group(1)) if um else 200
    pins: dict[str, list] = {}
    # Pin blocks: - NAME ... ;
    for block in re.finditer(
        r"-\s+(\S+)\s+\+ NET .*?(?=\n- |\nEND PINS)", text, re.S
    ):
        name = block.group(1)
        body = block.group(0)
        rects = []
        for m in re.finditer(
            r"\+\s+LAYER\s+(\S+)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*"
            r"\(\s*(-?\d+)\s+(-?\d+)\s*\)",
            body,
        ):
            layer = m.group(1)
            x1, y1, x2, y2 = (int(m.group(i)) / units for i in range(2, 6))
            rects.append((layer, x1, y1, x2, y2))
        pins[name] = rects
    return pins


def parse_lef_pins(path: Path) -> dict[str, list[tuple[str, float, float, float, float]]]:
    text = path.read_text()
    # Restrict to MACRO ai_byte_top if present
    macro = re.search(r"MACRO\s+ai_byte_top\b(.*?)END\s+ai_byte_top\b", text, re.S)
    body = macro.group(1) if macro else text
    pins: dict[str, list] = {}
    for block in re.finditer(r"PIN\s+(\S+)\s+(.*?)END\s+\1\b", body, re.S):
        name = block.group(1)
        pbody = block.group(2)
        rects = []
        for m in re.finditer(
            r"LAYER\s+(\S+)\s*;\s*RECT\s+"
            r"([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s*;",
            pbody,
        ):
            layer = m.group(1)
            x1, y1, x2, y2 = (float(m.group(i)) for i in range(2, 6))
            rects.append((layer, x1, y1, x2, y2))
        pins[name] = rects
    return pins


def overlap_area(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    return (ix2 - ix1) * (iy2 - iy1)


def area(r: tuple[float, float, float, float]) -> float:
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--def", dest="def_path", type=Path, default=DEFAULT_DEF)
    ap.add_argument("--lef", dest="lef_path", type=Path, default=DEFAULT_LEF)
    ap.add_argument(
        "--min-overlap-pct",
        type=float,
        default=25.0,
        help="min overlap vs template rect area (%%) to PASS one site",
    )
    args = ap.parse_args()

    if not args.def_path.is_file():
        print(f"MISSING DEF: {args.def_path}", file=sys.stderr)
        return 2
    if not args.lef_path.is_file():
        print(f"MISSING LEF: {args.lef_path}", file=sys.stderr)
        print("Run harden + stage first, or pass --lef", file=sys.stderr)
        return 2

    tmpl = parse_def_pins(args.def_path)
    lef = parse_lef_pins(args.lef_path)

    print(f"template: {args.def_path}  ({len(tmpl)} pins)")
    print(f"lef:      {args.lef_path}  ({len(lef)} pins)")
    print(f"{'PIN':16s} {'STATUS':8s}  detail")

    fails = 0
    for name, trects in sorted(tmpl.items()):
        lrects = lef.get(name)
        if not lrects:
            print(f"{name:16s} FAIL      missing in LEF")
            fails += 1
            continue

        # Prefer Metal2 on both sides
        t_m2 = [(r[1], r[2], r[3], r[4]) for r in trects if r[0] == "Metal2"]
        l_m2 = [(r[1], r[2], r[3], r[4]) for r in lrects if r[0] == "Metal2"]
        if not t_m2:
            print(f"{name:16s} FAIL      no Metal2 in template")
            fails += 1
            continue
        if not l_m2:
            layers = sorted({r[0] for r in lrects})
            print(f"{name:16s} FAIL      no Metal2 in LEF (have {layers})")
            fails += 1
            continue

        # Each template rect must get some LEF overlap (power has many)
        bad = []
        for i, tr in enumerate(t_m2):
            ta = area(tr)
            best = max((overlap_area(tr, lr) for lr in l_m2), default=0.0)
            pct = 100.0 * best / ta if ta > 0 else 0.0
            if pct < args.min_overlap_pct:
                bad.append(f"rect{i}@{tr} overlap={pct:.1f}%")
        if bad:
            print(f"{name:16s} FAIL      " + "; ".join(bad[:2]))
            fails += 1
        else:
            print(
                f"{name:16s} PASS      "
                f"Metal2 sites={len(t_m2)} lef_m2={len(l_m2)}"
            )

    extra = sorted(set(lef) - set(tmpl))
    if extra:
        print(f"\nLEF-only pins (ignored): {', '.join(extra[:12])}"
              + ("…" if len(extra) > 12 else ""))

    print(f"\n{len(tmpl) - fails}/{len(tmpl)} PASS, {fails} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
