# AI_Byte — Layout Review (Chipathon 2026)

Companion notes for the slide deck:

- **PDF:** [`ai_byte_layout_review.pdf`](ai_byte_layout_review.pdf)
- **HTML source:** [`ai_byte_layout_review.html`](ai_byte_layout_review.html)
- **Detailed metrics:** [`../dry-run-layout-report.md`](../dry-run-layout-report.md)

## Diagram assets

| File | Role |
|------|------|
| `ai_byte_toplevel_wrapper.png` | Crispi-style hierarchical RTL diagram (generated) |
| `gen_toplevel_diagram.py` | Regenerates the wrapper PNG |
| `ai_byte_top_layout.png` | LibreLane layout render |
| `ai_byte_architecture.png` | Earlier architecture figure (optional) |

```bash
python3 docs/layout_review/gen_toplevel_diagram.py
```

## Slide list

1. Title — Team AI_Byte layout review  
2. Design goal — accelerator summary + KPIs  
3. Top-level wrapper — `ai_byte_top` hierarchy diagram (Crispi-style)  
4. Yosys synthesis — cell/area + pre-PnR STA  
5. Floorplan / timing / optimizer config  
6. PDN and routing + layout render  
7. Final macro metrics + honest signoff status (WIP)  
8. Post-PnR STA (corners)  
9. Power / IR drop / antenna  
10. Padring pin mapping  
11. Padring + verification status  
12. Next steps roadmap  
13. Thank you  

## Regenerate PDF

```bash
cd docs/layout_review
google-chrome --headless --disable-gpu --no-pdf-header-footer \
  --print-to-pdf=ai_byte_layout_review.pdf \
  "file://$(pwd)/ai_byte_layout_review.html"
```

## Data source

Run `librelane/runs/RUN_2026-08-06_13-06-45` (`make librelane-core`), August 2026 dry-run.
