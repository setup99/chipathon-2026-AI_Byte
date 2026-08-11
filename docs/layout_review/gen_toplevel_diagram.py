#!/usr/bin/env python3
"""Generate Crispi-style AI_BYTE top-level wrapper block diagram (PNG)."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1700, 1000
BG = (255, 255, 255)
INK = (25, 25, 25)
GRAY = (95, 95, 95)

ORANGE = (255, 214, 170)
GREEN = (186, 230, 186)
PURPLE = (210, 190, 230)
RED = (255, 180, 180)
YELLOW = (255, 235, 150)
BLUE = (180, 210, 235)
CREAM = (255, 248, 240)
CORE_BG = (250, 251, 253)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for p in paths:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def rr(draw, box, r, fill, outline=INK, width=2):
    draw.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def text_size(draw, text, fnt):
    b = draw.textbbox((0, 0), text, font=fnt)
    return b[2] - b[0], b[3] - b[1]


def center_text(draw, box, lines, fonts, fills):
    """Center one or more text lines inside box."""
    heights = []
    widths = []
    for line, fnt in zip(lines, fonts):
        w, h = text_size(draw, line, fnt)
        widths.append(w)
        heights.append(h)
    total_h = sum(heights) + 4 * (len(lines) - 1)
    cx = (box[0] + box[2]) / 2
    y = (box[1] + box[3]) / 2 - total_h / 2
    for line, fnt, fill, w, h in zip(lines, fonts, fills, widths, heights):
        draw.text((cx - w / 2, y), line, fill=fill, font=fnt)
        y += h + 4


def block(draw, box, title, fill, f_title, sub=None, f_sub=None):
    rr(draw, box, 10, fill)
    if sub and f_sub:
        center_text(draw, box, [title, sub], [f_title, f_sub], [INK, GRAY])
    else:
        center_text(draw, box, [title], [f_title], [INK])


def arrow(draw, x0, y0, x1, y1, width=2, head=8):
    draw.line((x0, y0, x1, y1), fill=INK, width=width)
    ang = math.atan2(y1 - y0, x1 - x0)
    p1 = (x1 + head * math.cos(ang + 2.6), y1 + head * math.sin(ang + 2.6))
    p2 = (x1 + head * math.cos(ang - 2.6), y1 + head * math.sin(ang - 2.6))
    draw.polygon([(x1, y1), p1, p2], fill=INK)


def biarrow(draw, x0, y0, x1, y1, width=2, head=7):
    arrow(draw, x0, y0, x1, y1, width, head)
    ang = math.atan2(y0 - y1, x0 - x1)
    p1 = (x0 + head * math.cos(ang + 2.6), y0 + head * math.sin(ang + 2.6))
    p2 = (x0 + head * math.cos(ang - 2.6), y0 + head * math.sin(ang - 2.6))
    draw.polygon([(x0, y0), p1, p2], fill=INK)


def bus_mark(draw, x, y, label, fnt):
    draw.line((x - 7, y + 9, x + 7, y - 9), fill=INK, width=2)
    draw.text((x + 9, y - 12), label, fill=GRAY, font=fnt)


def main():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    f_mod = font(17, True)
    f_blk = font(14, True)
    f_sig = font(13)
    f_small = font(11)
    f_tiny = font(10)
    f_head = font(18, True)

    # Outer module
    outer = (110, 55, 1585, 955)
    rr(d, outer, 4, (255, 255, 255), width=3)
    d.text((125, 62), "ai_byte_top.v", fill=INK, font=f_mod)
    d.text((360, 64), "hardened digital core · no IO pads inside macro", fill=GRAY, font=f_small)

    # -------- Left pins --------
    left_pins = [
        (130, "vdd"),
        (165, "vss"),
        (220, "clk"),
        (255, "rst_n"),
        (320, "addr[3:0]"),
        (365, "we"),
        (400, "re"),
        (470, "data[7:0]"),
    ]
    for y, name in left_pins:
        tw, _ = text_size(d, name, f_sig)
        d.text((18, y - 8), name, fill=INK, font=f_sig)
        x_end = outer[0]
        x_start = 18 + tw + 6
        if name.startswith("data"):
            biarrow(d, x_start, y, x_end, y)
        else:
            arrow(d, x_start, y, x_end, y)

    # -------- Right pins --------
    right_pins = [
        (220, "irq"),
        (265, "done_o"),
        (310, "error_o"),
        (365, "debug_state[2:0]"),
        (470, "data[7:0]"),
    ]
    for y, name in right_pins:
        d.text((1600, y - 8), name, fill=INK, font=f_sig)
        if name.startswith("data"):
            biarrow(d, outer[2], y, 1595, y)
        else:
            arrow(d, outer[2], y, 1595, y)

    # -------- MMIF --------
    mmif = (145, 120, 420, 560)
    rr(d, mmif, 8, CREAM, width=2)
    d.text((158, 128), "ai_byte_mmif.v", fill=INK, font=f_mod)

    block(d, (170, 175, 395, 280), "MMIF", ORANGE, f_blk, "host bus decoder", f_small)
    block(d, (170, 310, 395, 400), "REG PORT", GREEN, f_blk, "reg_addr/we/re/data", f_small)
    block(d, (170, 425, 395, 530), "BUF PORT", GREEN, f_blk, "cpu_buf_*  (addr 0x6)", f_small)

    # feed host into MMIF
    for y in (220, 255, 320, 365, 400, 470):
        arrow(d, outer[0] + 2, y, mmif[0], min(max(y, 200), 470))
    # clk/rst into top of mmif/core
    d.line((outer[0] + 15, 220, outer[0] + 15, 100), fill=INK, width=2)
    arrow(d, outer[0] + 15, 100, 280, 120)

    # Thick MMIF bus arrow
    d.polygon(
        [(430, 300), (500, 300), (500, 280), (555, 340), (500, 400), (500, 380), (430, 380)],
        fill=(255, 255, 255),
        outline=INK,
    )
    d.text((438, 320), "MMIF", fill=INK, font=f_small)
    d.text((435, 340), "PORTS", fill=INK, font=f_small)

    # -------- ai_byte_core --------
    core = (575, 110, 1555, 920)
    rr(d, core, 8, CORE_BG, width=3)
    d.text((590, 118), "ai_byte_core.v", fill=INK, font=f_mod)

    # control_wrap
    ctrl = (600, 160, 1040, 500)
    rr(d, ctrl, 8, (255, 255, 255), width=2)
    d.text((615, 168), "control_wrap.v", fill=INK, font=f_mod)

    block(d, (625, 210, 820, 300), "REG FILE", GREEN, f_blk, "OPCODE · CONFIG · CTRL", f_tiny)
    block(d, (850, 210, 1020, 300), "CONTROL UNIT", PURPLE, f_blk, "FSM", f_small)
    block(d, (625, 340, 1020, 470), "BUFFER CTRL", BLUE, f_blk, "CPU mode · compute mode · AGU", f_small)

    arrow(d, 820, 255, 850, 255)
    d.text((822, 235), "cfg", fill=GRAY, font=f_tiny)
    arrow(d, 935, 300, 935, 340)
    arrow(d, 720, 300, 720, 340)

    # SRAMs
    d.text((1070, 168), "ai_byte_sram_buffer.v", fill=INK, font=f_tiny)
    block(d, (1070, 195, 1280, 275), "ACT SRAM", YELLOW, f_blk, "64 × 8b", f_small)
    block(d, (1070, 300, 1280, 380), "WT SRAM", YELLOW, f_blk, "16 × 8b", f_small)
    block(d, (1070, 405, 1280, 485), "RES SRAM", YELLOW, f_blk, "16 × 8b", f_small)

    biarrow(d, 1020, 235, 1070, 235)
    biarrow(d, 1020, 340, 1070, 340)
    biarrow(d, 1020, 445, 1070, 445)
    bus_mark(d, 1040, 235, "[7:0]", f_tiny)

    # MMIF -> core ports
    arrow(d, 555, 330, 600, 255)
    d.text((560, 270), "reg_*", fill=GRAY, font=f_tiny)
    arrow(d, 555, 355, 600, 400)
    d.text((548, 372), "cpu_buf_*", fill=GRAY, font=f_tiny)

    # status to right
    arrow(d, 1020, 255, 1320, 255)
    d.line((1320, 255, 1320, 220), fill=INK, width=2)
    arrow(d, 1320, 220, core[2], 220)
    arrow(d, core[2], 220, outer[2], 220)
    d.text((1330, 230), "irq / done_o / error_o / debug_state", fill=GRAY, font=f_tiny)

    # also fan done/error/debug
    d.line((outer[2] - 20, 220, outer[2] - 20, 365), fill=INK, width=2)
    arrow(d, outer[2] - 20, 265, outer[2], 265)
    arrow(d, outer[2] - 20, 310, outer[2], 310)
    arrow(d, outer[2] - 20, 365, outer[2], 365)

    # Compute engines
    eng = (600, 540, 1525, 890)
    rr(d, eng, 8, (255, 255, 255), width=2)
    d.text((615, 548), "compute engines", fill=INK, font=f_mod)

    d.text((625, 580), "gemm_systolic_2d.v", fill=INK, font=f_tiny)
    block(d, (625, 598, 900, 760), "SYSTOLIC ARRAY", RED, f_blk, "4×4  ·  CONV / FC (INT8→INT16)", f_tiny)

    d.text((940, 580), "block_wrapper.v", fill=INK, font=f_tiny)
    block(d, (940, 598, 1210, 760), "ALU / POST", RED, f_blk, "Q8.8 · ReLU · pool · scale", f_tiny)

    d.text((1250, 580), "eml_wrapper_q88_serial.v", fill=INK, font=f_tiny)
    block(d, (1250, 598, 1505, 760), "EML ENGINE", RED, f_blk, "sigmoid · tanh · recip · sqrt · softmax", f_tiny)

    block(d, (625, 790, 900, 860), "SA CTRL", ORANGE, f_small, "start / busy / done / w_load", f_tiny)
    block(d, (940, 790, 1210, 860), "ALU CTRL", ORANGE, f_small, "valid / ready / busy / ovf", f_tiny)
    block(d, (1250, 790, 1505, 860), "EML CTRL", ORANGE, f_small, "opcode / start / result / busy", f_tiny)

    arrow(d, 760, 760, 760, 790)
    arrow(d, 1075, 760, 1075, 790)
    arrow(d, 1375, 760, 1375, 790)

    # control -> engines
    arrow(d, 820, 500, 820, 540)
    d.text((830, 508), "ce start / mux", fill=GRAY, font=f_tiny)

    # sram spine to engines
    arrow(d, 1175, 485, 1175, 520)
    d.line((760, 520, 1375, 520), fill=INK, width=2)
    arrow(d, 760, 520, 760, 598)
    arrow(d, 1075, 520, 1075, 598)
    arrow(d, 1375, 520, 1375, 598)
    bus_mark(d, 1185, 505, "act / wt / res data", f_tiny)

    # data bidir annotation near bottom of mmif
    d.text((150, 575), "data[7:0] is inout on package / MMIF", fill=GRAY, font=f_tiny)

    out = Path(
        "/home/aymen/Documents/AI_BYTE_accelerator/chipathon-2026-AI_Byte/"
        "docs/layout_review/ai_byte_toplevel_wrapper.png"
    )
    img.save(out, "PNG", optimize=True)
    print(f"wrote {out} ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    main()
