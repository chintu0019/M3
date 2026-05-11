"""
M3 — Identity system, rendered under the 'Quiet Networks' philosophy.

Outputs:
    M3_logo_plate_I.png     — primary identity, the canonical glyph
    M3_logo_plate_II.png    — alternates: constellation, wordmark, monogram
    M3_logo_plate_III.png   — dark mode + scale study (24→512px)
    icons/icon-{1024,512,256,128,64,32,16}.png  — production app icons
    icons/icon-1024-dark.png — dark variant
    icons/favicon.png       — 32px favicon

Geometry: three nodes + two edges form the inner V of an M. Outer nodes
carry short vertical descenders so the silhouette resolves as an M. The
glyph contains exactly three nodes — the '3'. It is the smallest geometry
that still names the thing.
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
from pathlib import Path
import math
import random

FONTS = Path(
    "/Users/mk/Library/Application Support/Claude/local-agent-mode-sessions/"
    "skills-plugin/c2841845-81fe-4f72-9061-dae41391b110/"
    "51dbc7d3-c43d-4187-b5fb-bbb488aac84e/skills/canvas-design/canvas-fonts"
)
OUT = Path("/Users/mk/Projects/M3/design")
ICONS = OUT / "icons"
OUT.mkdir(parents=True, exist_ok=True)
ICONS.mkdir(parents=True, exist_ok=True)

# ---- palette -----------------------------------------------------
PAPER  = (242, 238, 229)
INK    = (24, 25, 30)
GRAPH  = (18, 19, 23)           # darker than ink, for backgrounds
IVORY  = (236, 230, 218)        # paper inverted onto graphite
ACCENT = (179, 58, 42)

def font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)

# ---- the mark ----------------------------------------------------
def draw_mark(draw, cx, cy, size,
              ink=INK,
              node_ratio=0.105,       # node radius / size
              stroke_ratio=0.036,
              desc_ratio=0.86,        # descender length / size
              compress=0.78,
              terminal=True,
              descenders=True):
    """Draw the canonical mark centered at (cx, cy) with overall width ~size.

    The mark is composed of three filled nodes forming a point-down equilateral
    triangle (the inner V of M), plus two vertical descenders from the outer
    nodes ending in tiny serif caps.
    """
    s = size
    r = max(2, int(s * node_ratio))
    stroke = max(1, int(s * stroke_ratio))
    desc = int(s * desc_ratio) if descenders else 0
    tick = max(1, int(r * 0.55))

    half = s / 2
    height = s * math.sqrt(3) / 2 * compress
    top_y = cy - height / 2
    bot_y = cy + height / 2

    p_tl = (cx - half, top_y)
    p_tr = (cx + half, top_y)
    p_b  = (cx, bot_y)

    # descenders first, then edges, then nodes — clean overlap
    if descenders:
        draw.line((p_tl[0], p_tl[1], p_tl[0], p_tl[1] + desc), fill=ink, width=stroke)
        draw.line((p_tr[0], p_tr[1], p_tr[0], p_tr[1] + desc), fill=ink, width=stroke)
        if terminal:
            draw.line((p_tl[0] - tick, p_tl[1] + desc, p_tl[0] + tick, p_tl[1] + desc),
                      fill=ink, width=stroke)
            draw.line((p_tr[0] - tick, p_tr[1] + desc, p_tr[0] + tick, p_tr[1] + desc),
                      fill=ink, width=stroke)

    draw.line((p_tl[0], p_tl[1], p_b[0], p_b[1]), fill=ink, width=stroke)
    draw.line((p_tr[0], p_tr[1], p_b[0], p_b[1]), fill=ink, width=stroke)

    for (x, y) in (p_tl, p_tr, p_b):
        draw.ellipse((x - r, y - r, x + r, y + r), fill=ink)

    return dict(top_left=p_tl, top_right=p_tr, bottom=p_b,
                top_y=top_y, bottom_y=bot_y + (desc if descenders else 0))

# ---- paper background with subtle grain -------------------------
def paper_canvas(w, h, bg=PAPER, grain_density=18):
    img = Image.new("RGB", (w, h), bg)
    random.seed(7)
    noise = Image.new("L", (w, h), 0)
    np_ = noise.load()
    for _ in range(w * h // grain_density):
        x = random.randint(0, w - 1)
        y = random.randint(0, h - 1)
        np_[x, y] = random.randint(0, 20)
    noise = noise.filter(ImageFilter.GaussianBlur(0.6))
    shade = Image.new("RGB", (w, h), (0, 0, 0) if sum(bg) > 384 else (255, 255, 255))
    return Image.composite(shade, img, noise)

# ---- dot grid ---------------------------------------------------
def dot_grid(draw, w, h, spacing=60, ink=INK, alpha=22):
    for x in range(spacing, w, spacing):
        for y in range(spacing, h, spacing):
            draw.ellipse((x - 1, y - 1, x + 1, y + 1), fill=(*ink, alpha))

# ---- corner ticks + specimen chrome -----------------------------
def specimen_chrome(draw, w, h, margin, title, plate, footer_l, footer_r,
                    ink=INK, accent=ACCENT, accent_in_corner=True):
    f_label = font("GeistMono-Bold.ttf", 20)
    f_small = font("GeistMono-Regular.ttf", 22)
    # corner ticks
    def tick(cx, cy, dx, dy, length=24, thickness=2):
        # horizontal arm
        x0 = cx if dx >= 0 else cx - length
        x1 = cx + length if dx >= 0 else cx
        y0 = cy if dy >= 0 else cy - thickness
        y1 = cy + thickness if dy >= 0 else cy
        draw.rectangle((x0, y0, x1, y1), fill=ink)
        # vertical arm
        x0 = cx if dx >= 0 else cx - thickness
        x1 = cx + thickness if dx >= 0 else cx
        y0 = cy if dy >= 0 else cy - length
        y1 = cy + length if dy >= 0 else cy
        draw.rectangle((x0, y0, x1, y1), fill=ink)
    tick(margin, margin, 1, 1)
    tick(w - margin, margin, -1, 1)
    tick(margin, h - margin, 1, -1)
    tick(w - margin, h - margin, -1, -1)
    # header text
    draw.text((margin, margin - 60), title, font=f_label, fill=ink)
    bbox = draw.textbbox((0, 0), plate, font=f_label)
    draw.text((w - margin - (bbox[2] - bbox[0]), margin - 60), plate, font=f_label, fill=ink)
    # registration crosshair (vermilion) — single accent
    if accent_in_corner:
        rx, ry = w - margin - 80, margin + 12
        c = 14
        draw.line((rx - c, ry, rx + c, ry), fill=accent, width=2)
        draw.line((rx, ry - c, rx, ry + c), fill=accent, width=2)
        draw.ellipse((rx - 4, ry - 4, rx + 4, ry + 4), outline=accent, width=2)
    # footer
    draw.text((margin, h - margin + 24), footer_l, font=f_small, fill=ink)
    bbox = draw.textbbox((0, 0), footer_r, font=f_small)
    draw.text((w - margin - (bbox[2] - bbox[0]), h - margin + 24), footer_r,
              font=f_small, fill=ink)

# ---- left-edge ruler -------------------------------------------
def ruler(draw, x, y0, y1, ink=INK, ticks=24, label_every=4):
    f_tiny = font("GeistMono-Regular.ttf", 18)
    draw.line((x, y0, x, y1), fill=ink, width=1)
    for i in range(ticks + 1):
        y = y0 + (y1 - y0) * i / ticks
        long_t = (i % label_every == 0)
        L = 14 if long_t else 6
        draw.line((x, y, x + L, y), fill=ink, width=1)
        if long_t:
            draw.text((x - 60, y - 10), f"{i * 5:02d}", font=f_tiny, fill=(*ink, 200))

# =================================================================
# PLATE I — primary identity
# =================================================================
def render_plate_I():
    W, H = 2400, 3000
    img = paper_canvas(W, H, PAPER)
    draw = ImageDraw.Draw(img, "RGBA")
    dot_grid(draw, W, H)

    MARGIN = 140
    # construction guides — strictly only what proves the geometry
    CX, CY = W // 2, int(H * 0.40)
    S = 440
    # vertical centerline + top-node baseline drawn before mark
    half = S / 2
    h_ = S * math.sqrt(3) / 2 * 0.78
    top_y = CY - h_ / 2
    bot_y = CY + h_ / 2
    GUIDE = (24, 25, 30, 55)
    draw.line((CX, top_y - 80, CX, bot_y + 380 + 100), fill=GUIDE, width=1)
    draw.line((CX - half - 120, top_y, CX + half + 120, top_y), fill=GUIDE, width=1)

    draw_mark(draw, CX, CY, S)

    # wordmark
    f_word = font("Jura-Light.ttf", 220)
    f_cap  = font("InstrumentSerif-Italic.ttf", 34)
    WM_Y = int(H * 0.70)
    wm = "m3"
    bb = draw.textbbox((0, 0), wm, font=f_word)
    draw.text(((W - (bb[2] - bb[0])) // 2 - bb[0], WM_Y - bb[1]), wm, font=f_word, fill=INK)
    cap = "a quiet network for one"
    bb = draw.textbbox((0, 0), cap, font=f_cap)
    draw.text(((W - (bb[2] - bb[0])) // 2 - bb[0], WM_Y + 250),
              cap, font=f_cap, fill=(*INK, 200))

    # chrome
    specimen_chrome(draw, W, H, MARGIN,
                    "M3  /  IDENTITY MARK", "PLATE  I",
                    "QUIET NETWORKS  ·  PRIMARY GLYPH  ·  SPECIMEN 01",
                    "48.0°N  ·  GRAPHITE / IVORY  ·  REV 03")
    ruler(draw, MARGIN - 30, MARGIN + 80, H - MARGIN - 80)

    # mini echo, bottom-right
    ECX, ECY = W - MARGIN - 60, H - MARGIN - 140
    draw_mark(draw, ECX, ECY, 60)
    f_tiny = font("GeistMono-Regular.ttf", 18)
    draw.text((ECX - 36, ECY + 80), "16PX", font=f_tiny, fill=(*INK, 200))

    out = OUT / "M3_logo_plate_I.png"
    img.save(out, "PNG", dpi=(300, 300))
    print(f"wrote {out}")

# =================================================================
# PLATE II — alternates
# =================================================================
def render_plate_II():
    W, H = 2400, 3000
    img = paper_canvas(W, H, PAPER)
    draw = ImageDraw.Draw(img, "RGBA")
    dot_grid(draw, W, H)

    MARGIN = 140
    specimen_chrome(draw, W, H, MARGIN,
                    "M3  /  ALTERNATES", "PLATE  II",
                    "QUIET NETWORKS  ·  GLYPH STUDY  ·  SPECIMEN 02–05",
                    "MONOGRAM  ·  CONSTELLATION  ·  LOCKUP  ·  REV 02")

    # 2x2 grid of variants
    f_lbl = font("GeistMono-Bold.ttf", 22)
    f_dsc = font("InstrumentSerif-Italic.ttf", 28)
    f_idx = font("GeistMono-Regular.ttf", 18)

    cells = [
        (W * 0.28, H * 0.30, 360),  # top-left
        (W * 0.72, H * 0.30, 360),  # top-right
        (W * 0.28, H * 0.62, 360),  # bottom-left
        (W * 0.72, H * 0.62, 360),  # bottom-right
    ]

    # cell frames (very faint)
    for (cx, cy, _) in cells:
        cell_w, cell_h = 560, 560
        x0, y0 = cx - cell_w / 2, cy - cell_h / 2
        draw.rectangle((x0, y0, x0 + cell_w, y0 + cell_h),
                       outline=(*INK, 35), width=1)

    # II.a — Canonical glyph (the M with descenders)
    cx, cy, s = cells[0]
    draw_mark(draw, cx, cy - 30, 280)
    draw.text((cx - 270, cy - 230), "ii.a", font=f_idx, fill=(*INK, 200))
    label = "canonical"
    bb = draw.textbbox((0, 0), label, font=f_lbl)
    draw.text((cx - (bb[2] - bb[0]) / 2, cy + 200), label, font=f_lbl, fill=INK)
    dsc = "primary, signage, splash"
    bb = draw.textbbox((0, 0), dsc, font=f_dsc)
    draw.text((cx - (bb[2] - bb[0]) / 2, cy + 232), dsc, font=f_dsc, fill=(*INK, 180))

    # II.b — Constellation (no descenders, just the 3-node V)
    cx, cy, s = cells[1]
    draw_mark(draw, cx, cy, 280, descenders=False)
    draw.text((cx - 270, cy - 230), "ii.b", font=f_idx, fill=(*INK, 200))
    label = "constellation"
    bb = draw.textbbox((0, 0), label, font=f_lbl)
    draw.text((cx - (bb[2] - bb[0]) / 2, cy + 200), label, font=f_lbl, fill=INK)
    dsc = "favicon, small-scale, ui"
    bb = draw.textbbox((0, 0), dsc, font=f_dsc)
    draw.text((cx - (bb[2] - bb[0]) / 2, cy + 232), dsc, font=f_dsc, fill=(*INK, 180))

    # II.c — Horizontal lockup: mark + wordmark in a row
    cx, cy, s = cells[2]
    f_word_lock = font("Jura-Light.ttf", 150)
    # mark on the left, text on the right
    mark_size = 150
    gap = 60
    wm = "m3"
    bb = draw.textbbox((0, 0), wm, font=f_word_lock)
    text_w = bb[2] - bb[0]
    total = mark_size + gap + text_w
    mx = cx - total / 2 + mark_size / 2
    tx = cx - total / 2 + mark_size + gap - bb[0]
    # vertically center the mark with the cap-height
    cap_y = cy - 60
    draw_mark(draw, mx, cap_y + 10, mark_size)
    draw.text((tx, cap_y - bb[1] - 60), wm, font=f_word_lock, fill=INK)
    draw.text((cx - 270, cy - 230), "ii.c", font=f_idx, fill=(*INK, 200))
    label = "horizontal lockup"
    bb = draw.textbbox((0, 0), label, font=f_lbl)
    draw.text((cx - (bb[2] - bb[0]) / 2, cy + 200), label, font=f_lbl, fill=INK)
    dsc = "header, business card, footer"
    bb = draw.textbbox((0, 0), dsc, font=f_dsc)
    draw.text((cx - (bb[2] - bb[0]) / 2, cy + 232), dsc, font=f_dsc, fill=(*INK, 180))

    # II.d — Monogram in a rounded square (app icon proof)
    cx, cy, s = cells[3]
    sq = 360
    x0, y0 = cx - sq / 2, cy - sq / 2 - 30
    # icon background — deep graphite, rounded square
    icon_layer = Image.new("RGBA", (int(sq) + 20, int(sq) + 20), (0, 0, 0, 0))
    idraw = ImageDraw.Draw(icon_layer)
    idraw.rounded_rectangle((10, 10, sq + 10, sq + 10), radius=int(sq * 0.22), fill=GRAPH)
    img.paste(icon_layer, (int(x0 - 10), int(y0 - 10)), icon_layer)
    # draw the mark in ivory inside
    draw_mark(draw, cx, cy - 30, int(sq * 0.62), ink=IVORY)
    draw.text((cx - 270, cy - 230), "ii.d", font=f_idx, fill=(*INK, 200))
    label = "app monogram"
    bb = draw.textbbox((0, 0), label, font=f_lbl)
    draw.text((cx - (bb[2] - bb[0]) / 2, cy + 200), label, font=f_lbl, fill=INK)
    dsc = "macos / ios / dock"
    bb = draw.textbbox((0, 0), dsc, font=f_dsc)
    draw.text((cx - (bb[2] - bb[0]) / 2, cy + 232), dsc, font=f_dsc, fill=(*INK, 180))

    ruler(draw, MARGIN - 30, MARGIN + 80, H - MARGIN - 80)

    out = OUT / "M3_logo_plate_II.png"
    img.save(out, "PNG", dpi=(300, 300))
    print(f"wrote {out}")

# =================================================================
# PLATE III — dark mode + scale study
# =================================================================
def render_plate_III():
    W, H = 2400, 3000
    img = paper_canvas(W, H, GRAPH, grain_density=22)
    draw = ImageDraw.Draw(img, "RGBA")
    # faint grid in ivory
    for x in range(60, W, 60):
        for y in range(60, H, 60):
            draw.ellipse((x - 1, y - 1, x + 1, y + 1), fill=(*IVORY, 20))

    MARGIN = 140
    specimen_chrome(draw, W, H, MARGIN,
                    "M3  /  DARK + SCALE", "PLATE  III",
                    "QUIET NETWORKS  ·  INVERSION & RANGE  ·  SPECIMEN 06",
                    "24 → 512 PX  ·  IVORY ON GRAPHITE  ·  REV 01",
                    ink=IVORY)

    # large dark-mode mark, upper third
    CX = W // 2
    CY = int(H * 0.32)
    draw_mark(draw, CX, CY, 460, ink=IVORY)

    # scale study — same mark at descending sizes, on a baseline
    f_lbl = font("GeistMono-Regular.ttf", 22)
    sizes = [320, 200, 128, 80, 48, 24]
    bx_start = MARGIN + 80
    bx_end = W - MARGIN - 80
    base_y = int(H * 0.78)
    # distribute centers along baseline with each box width proportional
    total_w = sum(s * 1.7 for s in sizes)
    cur = bx_start
    for s in sizes:
        cell_w = (bx_end - bx_start) * (s * 1.7) / total_w
        cx = cur + cell_w / 2
        # align bottom of mark to baseline
        # mark extent below center: bottom_y + descender
        # we just center vertically with a small offset
        draw_mark(draw, cx, base_y - s * 0.25, s, ink=IVORY)
        # px label below baseline
        lbl = f"{s}px"
        bb = draw.textbbox((0, 0), lbl, font=f_lbl)
        draw.text((cx - (bb[2] - bb[0]) / 2, base_y + s * 0.6 + 24),
                  lbl, font=f_lbl, fill=(*IVORY, 200))
        cur += cell_w

    # baseline
    draw.line((bx_start, base_y + s * 0.6, bx_end, base_y + s * 0.6),
              fill=(*IVORY, 60), width=1)

    # ruler (light)
    f_tiny = font("GeistMono-Regular.ttf", 18)
    rx = MARGIN - 30
    y0, y1 = MARGIN + 80, H - MARGIN - 80
    draw.line((rx, y0, rx, y1), fill=IVORY, width=1)
    for i in range(25):
        y = y0 + (y1 - y0) * i / 24
        long_t = (i % 4 == 0)
        L = 14 if long_t else 6
        draw.line((rx, y, rx + L, y), fill=IVORY, width=1)
        if long_t:
            draw.text((rx - 60, y - 10), f"{i * 5:02d}", font=f_tiny, fill=(*IVORY, 200))

    out = OUT / "M3_logo_plate_III.png"
    img.save(out, "PNG", dpi=(300, 300))
    print(f"wrote {out}")

# =================================================================
# APP ICONS — production exports
# =================================================================
def render_app_icon(size, dark=False, transparent=False, rounded=True):
    """Render the M3 monogram as a square icon at the given size."""
    s = size
    if transparent:
        img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    else:
        img = Image.new("RGB", (s, s), GRAPH if dark else PAPER)
    draw = ImageDraw.Draw(img, "RGBA")

    # rounded square background if non-transparent
    if not transparent and rounded:
        radius = int(s * 0.22)
        # create mask to round corners
        mask = Image.new("L", (s, s), 0)
        mdraw = ImageDraw.Draw(mask)
        mdraw.rounded_rectangle((0, 0, s, s), radius=radius, fill=255)
        bg = Image.new("RGB", (s, s), GRAPH if dark else PAPER)
        rounded_bg = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        rounded_bg.paste(bg, (0, 0), mask)
        img = rounded_bg
        draw = ImageDraw.Draw(img, "RGBA")

    # mark scaled to ~58% of the icon
    mark_color = IVORY if dark else INK
    # smaller mark needs simplification — drop descenders below 48px
    use_descenders = s >= 48
    mark_size = int(s * (0.62 if use_descenders else 0.48))
    # nudge mark center upward when descenders present so the whole
    # silhouette is optically centered
    cy_offset = -int(s * 0.10) if use_descenders else 0
    # at tiny sizes, slightly fatten strokes for legibility
    node_r = 0.115 if s < 64 else 0.105
    stroke_r = 0.05 if s < 64 else 0.036
    draw_mark(draw, s / 2, s / 2 + cy_offset, mark_size,
              ink=mark_color,
              node_ratio=node_r,
              stroke_ratio=stroke_r,
              descenders=use_descenders,
              terminal=s >= 64)
    return img

def render_all_icons():
    for size in (1024, 512, 256, 128, 64, 32, 16):
        light = render_app_icon(size, dark=False)
        light.save(ICONS / f"icon-{size}.png", "PNG")
        dark = render_app_icon(size, dark=True)
        dark.save(ICONS / f"icon-{size}-dark.png", "PNG")
    # transparent monochrome marks (no background) for embedding
    for size in (1024, 512, 256, 128):
        light = render_app_icon(size, dark=False, transparent=True, rounded=False)
        light.save(ICONS / f"mark-{size}.png", "PNG")
        dark = render_app_icon(size, dark=True, transparent=True, rounded=False)
        dark.save(ICONS / f"mark-{size}-dark.png", "PNG")
    # favicon convenience copy
    fav = render_app_icon(32, dark=False)
    fav.save(ICONS / "favicon.png", "PNG")
    print(f"wrote icon set to {ICONS}")

# =================================================================
# SVG — vector mark for embedding in the React app
# =================================================================
def render_mark_svg(stroke_color="currentColor",
                    fill_color="currentColor",
                    with_descenders=True,
                    viewbox_size=120):
    """Emit an SVG of the canonical mark. The mark fits in the viewbox
    with a small padding margin. Uses currentColor so React consumers
    style it via CSS color.
    """
    vb = viewbox_size
    # canonical proportions match draw_mark(): everything is a ratio of the
    # triangle side length `s`. We pick s so the silhouette fits the viewbox
    # with comfortable padding on all sides.
    NODE_R  = 0.105       # node radius / s
    STROKE  = 0.036       # stroke width / s
    DESC_R  = 0.86        # descender length / s
    TICK_R  = 0.55        # terminal tick half-width / r
    COMPRESS = 0.78

    # extents in units of s, relative to top_y:
    #   x: [-s/2 - r, +s/2 + r]  → width  = s + 2r
    #   y: top:    -r
    #      bot:    height + r           (= s*sqrt3/2*compress + r)
    #      desc:   desc + stroke/2      (if descenders)
    # ymax is whichever is larger.
    height_r = math.sqrt(3) / 2 * COMPRESS   # in units of s
    bot_node_ext = height_r + NODE_R
    desc_ext     = DESC_R + STROKE / 2 if with_descenders else 0
    y_ext = max(bot_node_ext, desc_ext)        # in units of s, below top_y
    x_ext = 0.5 + NODE_R                       # in units of s, each side

    # fit: vb = max(width, top_extent + y_ext) * s with padding
    pad = 0.08 * vb
    fit = vb - 2 * pad
    s = fit / max(2 * x_ext, NODE_R + y_ext)

    r       = s * NODE_R
    stroke  = s * STROKE
    desc    = s * DESC_R if with_descenders else 0
    tick    = r * TICK_R
    half    = s / 2
    height  = s * height_r

    cx = vb / 2
    # center the silhouette vertically: midpoint of [top_y - r, top_y + y_ext*s]
    top_y = vb / 2 - (y_ext * s - r) / 2
    bot_y = top_y + height
    p_tl = (cx - half, top_y)
    p_tr = (cx + half, top_y)
    p_b  = (cx, bot_y)

    lines = []
    if with_descenders:
        lines.append(f'<line x1="{p_tl[0]:.3f}" y1="{p_tl[1]:.3f}" '
                     f'x2="{p_tl[0]:.3f}" y2="{p_tl[1] + desc:.3f}" />')
        lines.append(f'<line x1="{p_tr[0]:.3f}" y1="{p_tr[1]:.3f}" '
                     f'x2="{p_tr[0]:.3f}" y2="{p_tr[1] + desc:.3f}" />')
        lines.append(f'<line x1="{p_tl[0] - tick:.3f}" y1="{p_tl[1] + desc:.3f}" '
                     f'x2="{p_tl[0] + tick:.3f}" y2="{p_tl[1] + desc:.3f}" />')
        lines.append(f'<line x1="{p_tr[0] - tick:.3f}" y1="{p_tr[1] + desc:.3f}" '
                     f'x2="{p_tr[0] + tick:.3f}" y2="{p_tr[1] + desc:.3f}" />')

    lines.append(f'<line x1="{p_tl[0]:.3f}" y1="{p_tl[1]:.3f}" '
                 f'x2="{p_b[0]:.3f}" y2="{p_b[1]:.3f}" />')
    lines.append(f'<line x1="{p_tr[0]:.3f}" y1="{p_tr[1]:.3f}" '
                 f'x2="{p_b[0]:.3f}" y2="{p_b[1]:.3f}" />')

    circles = []
    for (x, y) in (p_tl, p_tr, p_b):
        circles.append(f'<circle cx="{x:.3f}" cy="{y:.3f}" r="{r:.3f}" />')

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb} {vb}" '
        f'fill="none" stroke="{stroke_color}" stroke-width="{stroke:.3f}" '
        f'stroke-linecap="butt" stroke-linejoin="miter" aria-label="M3">\n'
        f'  <g>\n    ' + '\n    '.join(lines) + '\n  </g>\n'
        f'  <g fill="{fill_color}" stroke="none">\n    '
        + '\n    '.join(circles) +
        '\n  </g>\n</svg>\n'
    )
    return svg

def render_all_svgs():
    # canonical mark — currentColor so consumers theme via CSS
    (OUT / "mark.svg").write_text(render_mark_svg())
    # constellation (no descenders) — for tight UI spots
    (OUT / "mark-constellation.svg").write_text(render_mark_svg(with_descenders=False))
    print(f"wrote svg marks to {OUT}")

# =================================================================
if __name__ == "__main__":
    render_plate_I()
    render_plate_II()
    render_plate_III()
    render_all_icons()
    render_all_svgs()
