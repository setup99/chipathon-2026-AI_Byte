#!/usr/bin/env python3
"""Build A02 VDD/VSS Metal2→Metal5 power-connector cells (D10 / caravel pattern).

Reads organizer A02_A.def pin geometry (Metal2 on west edge) and writes:
  connectors/{lef,gds,verilog}/vss_conn.*
  connectors/{lef,gds,verilog}/vdd_conn.*

No hand layout — rectangles + via arrays only.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DBU_PER_UM = 200  # A02_A.def UNITS DISTANCE MICRONS 200
GDS_DBU = 1000  # 1 nm units in GDS (µm * 1000)

# gf180mcuD stream layers (klayout sealring_cells/layers.py)
LAYERS = {
    "Metal2": (36, 0),
    "Via2": (38, 0),
    "Metal3": (42, 0),
    "Via3": (40, 0),
    "Metal4": (46, 0),
    "Via4": (41, 0),
    "Metal5": (81, 0),
}

# Via cut size / pitch (µm) — same family as D10 / caravel-gf180mcu
VIA_W = 0.26
VIA_PITCH = 0.62  # 0.26 + 0.36
# West edge stays at x=0 for A02 Metal2 abutment. Width must cross CORE_AREA
# (~10.08 µm) so Metal5 overlaps stdcell PDN straps (PSM-0069 otherwise).
CONN_WIDTH = 20.0


def find_interface_def() -> Path:
    for root in ("A02.def (1)", "A02.def"):
        p = REPO / root / "A02/project_defs/A/A02_A.def"
        if p.is_file():
            return p
    raise SystemExit("A02_A.def not found under A02.def*/")


def parse_power_pins(def_path: Path) -> dict[str, list[tuple[float, float, float, float]]]:
    """Return {VDD|VSS: [(x1,y1,x2,y2) in µm, user-block coords]}."""
    text = def_path.read_text()
    out: dict[str, list[tuple[float, float, float, float]]] = {}
    for net in ("VSS", "VDD"):
        m = re.search(
            rf"- {net} \+ NET {net}.*?\+ FIXED.*?;",
            text,
            flags=re.M | re.S,
        )
        if not m:
            raise SystemExit(f"pin {net} not found in {def_path}")
        rects = []
        for rm in re.finditer(
            r"\+ LAYER Metal2 \(\s*(-?\d+)\s+(-?\d+)\s*\)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)",
            m.group(0),
        ):
            x1, y1, x2, y2 = (int(rm.group(i)) / DBU_PER_UM for i in range(1, 5))
            rects.append((min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)))
        if not rects:
            raise SystemExit(f"no Metal2 rects for {net}")
        out[net] = rects
    return out


def via_centers(x0: float, y0: float, x1: float, y1: float) -> list[tuple[float, float]]:
    """Place via array inside rect with enclosure margin."""
    margin = 0.08
    xa, xb = x0 + margin + VIA_W / 2, x1 - margin - VIA_W / 2
    ya, yb = y0 + margin + VIA_W / 2, y1 - margin - VIA_W / 2
    if xa > xb or ya > yb:
        return [((x0 + x1) / 2, (y0 + y1) / 2)]
    pts = []
    y = ya
    while y <= yb + 1e-9:
        x = xa
        while x <= xb + 1e-9:
            pts.append((x, y))
            x += VIA_PITCH
        y += VIA_PITCH
    return pts or [((x0 + x1) / 2, (y0 + y1) / 2)]


# --- minimal GDSII writer (rects only; no klayout dependency) ---
def _gds_record(rec_type: int, data_type: int, payload: bytes = b"") -> bytes:
    # GDS record: 2-byte length (incl. header) + type + datatype + data
    length = 4 + len(payload)
    return length.to_bytes(2, "big") + bytes([rec_type, data_type]) + payload


def _gds_int2(n: int) -> bytes:
    return int(n).to_bytes(2, "big", signed=True)


def _gds_int4(n: int) -> bytes:
    return int(n).to_bytes(4, "big", signed=True)


def _gds_ascii(s: str) -> bytes:
    b = s.encode("ascii")
    if len(b) % 2:
        b += b"\x00"
    return b


def write_gds(path: Path, cell: str, shapes: list[tuple[str, float, float, float, float]]) -> None:
    """shapes: (layer_name, x1,y1,x2,y2) in µm. dbu = 1 nm."""
    # Prefer klayout if its pymod works; otherwise pure-Python stream.
    try:
        import klayout.db as db  # type: ignore

        layout = db.Layout()
        layout.dbu = 0.001  # µm
        top = layout.create_cell(cell)
        for layer_name, x1, y1, x2, y2 in shapes:
            layer, datatype = LAYERS[layer_name]
            li = layout.layer(layer, datatype)
            top.shapes(li).insert(db.DBox(x1, y1, x2, y2))
        layout.write(str(path))
        return
    except Exception:
        pass

    dbu_per_um = GDS_DBU  # 1000 → 1 nm
    out = bytearray()
    out += _gds_record(0x00, 0x02, _gds_int2(600))  # HEADER
    out += _gds_record(0x01, 0x02, b"\x00" * 24)  # BGNLIB
    out += _gds_record(0x02, 0x06, _gds_ascii("LIB"))  # LIBNAME
    # UNITS: user unit 1e-3 m? Standard: 1um user / 1nm database
    # Real: 8-byte floats — use fixed known encoding for 0.001 and 1e-9
    import struct

    units = struct.pack(">dd", 1e-3, 1e-9)  # 1 user unit = 1 µm, dbu = 1 nm
    out += _gds_record(0x03, 0x05, units)  # UNITS
    out += _gds_record(0x05, 0x02, b"\x00" * 24)  # BGNSTR
    out += _gds_record(0x06, 0x06, _gds_ascii(cell))  # STRNAME

    for layer_name, x1, y1, x2, y2 in shapes:
        layer, datatype = LAYERS[layer_name]
        xa, ya = int(round(min(x1, x2) * dbu_per_um)), int(round(min(y1, y2) * dbu_per_um))
        xb, yb = int(round(max(x1, x2) * dbu_per_um)), int(round(max(y1, y2) * dbu_per_um))
        out += _gds_record(0x08, 0x00)  # BOUNDARY
        out += _gds_record(0x0D, 0x02, _gds_int2(layer))  # LAYER
        out += _gds_record(0x0E, 0x02, _gds_int2(datatype))  # DATATYPE
        # XY: 5 points closing the box
        xy = b"".join(
            _gds_int4(v)
            for v in (xa, ya, xb, ya, xb, yb, xa, yb, xa, ya)
        )
        out += _gds_record(0x10, 0x03, xy)  # XY
        out += _gds_record(0x11, 0x00)  # ENDEL

    out += _gds_record(0x07, 0x00)  # ENDSTR
    out += _gds_record(0x04, 0x00)  # ENDLIB
    path.write_bytes(out)

def write_lef(
    path: Path,
    cell: str,
    net: str,
    width: float,
    height: float,
    m2_rects_local: list[tuple[float, float, float, float]],
) -> None:
    lines = [
        "VERSION 5.7 ;",
        "NOWIREEXTENSIONATPIN ON ;",
        'DIVIDERCHAR "/" ;',
        'BUSBITCHARS "[]" ;',
        f"MACRO {cell}",
        "  CLASS BLOCK ;",
        f"  FOREIGN {cell} ;",
        "  ORIGIN 0.000 0.000 ;",
        f"  SIZE {width:.3f} BY {height:.3f} ;",
        f"  PIN {net}",
        "    DIRECTION INOUT ;",
        f"    USE {'POWER' if net == 'VDD' else 'GROUND'} ;",
        "    PORT",
    ]
    for x1, y1, x2, y2 in m2_rects_local:
        # widen Metal2 to full connector width for abutment + vias
        lines.append("      LAYER Metal2 ;")
        lines.append(f"        RECT 0.000 {y1:.3f} {width:.3f} {y2:.3f} ;")
        lines.append("      LAYER Metal5 ;")
        lines.append(f"        RECT 0.000 {y1:.3f} {width:.3f} {y2:.3f} ;")
    # Stitch all fingers into one node on each layer so one PDN overlap
    # connects the whole connector pin.
    lines.append("      LAYER Metal2 ;")
    lines.append(f"        RECT 0.000 0.000 {width:.3f} {height:.3f} ;")
    lines.append("      LAYER Metal5 ;")
    lines.append(f"        RECT 0.000 0.000 {width:.3f} {height:.3f} ;")
    lines += [
        "    END",
        f"  END {net}",
        "  OBS",
        "    LAYER Metal3 ;",
        f"      RECT 0.000 0.000 {width:.3f} {height:.3f} ;",
        "    LAYER Metal4 ;",
        f"      RECT 0.000 0.000 {width:.3f} {height:.3f} ;",
        "  END",
        f"END {cell}",
        "END LIBRARY",
        "",
    ]
    path.write_text("\n".join(lines))


def write_verilog(path: Path, cell: str, net: str) -> None:
    path.write_text(
        f"""(* blackbox *)
(* keep *)
module {cell} (
    inout wire {net}
);
endmodule
"""
    )


def build_one(net: str, cell: str, rects_um: list[tuple[float, float, float, float]], out_dir: Path) -> tuple[float, float]:
    """Build one connector. Returns (place_x, place_y) in macro microns."""
    ys = [r[1] for r in rects_um] + [r[3] for r in rects_um]
    y_min, y_max = min(ys), max(ys)
    height = y_max - y_min
    width = CONN_WIDTH
    # local rects relative to cell origin at (0, y_min)
    local = [(0.0, r[1] - y_min, width, r[3] - y_min) for r in rects_um]

    shapes: list[tuple[str, float, float, float, float]] = []
    for x1, y1, x2, y2 in local:
        shapes.append(("Metal2", x1, y1, x2, y2))
        shapes.append(("Metal3", x1, y1, x2, y2))
        shapes.append(("Metal4", x1, y1, x2, y2))
        shapes.append(("Metal5", x1, y1, x2, y2))
        for cx, cy in via_centers(x1, y1, x2, y2):
            hx = VIA_W / 2
            for via in ("Via2", "Via3", "Via4"):
                shapes.append((via, cx - hx, cy - hx, cx + hx, cy + hx))

    # Add continuous spines to electrically stitch all finger islands.
    shapes.append(("Metal2", 0.0, 0.0, width, height))
    shapes.append(("Metal5", 0.0, 0.0, width, height))

    (out_dir / "gds").mkdir(parents=True, exist_ok=True)
    (out_dir / "lef").mkdir(parents=True, exist_ok=True)
    (out_dir / "verilog").mkdir(parents=True, exist_ok=True)

    write_gds(out_dir / "gds" / f"{cell}.gds", cell, shapes)
    write_lef(out_dir / "lef" / f"{cell}.lef", cell, net, width, height, local)
    write_verilog(out_dir / "verilog" / f"{cell}.v", cell, net)

    place = (0.0, y_min)
    print(f"{cell}: {len(rects_um)} M2 pins, size {width:.3f} x {height:.3f} µm, place at {place}")
    return place


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        type=Path,
        default=REPO / "connectors",
        help="output directory",
    )
    args = ap.parse_args()
    def_path = find_interface_def()
    pins = parse_power_pins(def_path)
    print(f"source: {def_path}")

    places = {}
    places["vss_conn"] = build_one("VSS", "vss_conn", pins["VSS"], args.out)
    places["vdd_conn"] = build_one("VDD", "vdd_conn", pins["VDD"], args.out)

    import json

    (args.out / "placement.json").write_text(
        json.dumps(
            {
                "vss_conn": {"location": list(places["vss_conn"]), "orientation": "N", "net": "VSS"},
                "vdd_conn": {"location": list(places["vdd_conn"]), "orientation": "N", "net": "VDD"},
                "width_um": CONN_WIDTH,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"wrote {args.out / 'placement.json'}")
    print("done (LEF/GDS/verilog under connectors/)")


if __name__ == "__main__":
    main()
