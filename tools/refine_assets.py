"""Refine both character packs and build app-ready assets.

Pipeline: alpha-aware foreground decontamination (pymatting) -> 1px fringe
trim + feather -> 640 canvas -> avatar, icon and QA contact sheet.
Run from the project root: python tools/refine_assets.py
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pymatting import estimate_foreground_ml

ROOT = Path(__file__).resolve().parent.parent
SPRITES = ROOT / "assets" / "sprites"
AVATARS = ROOT / "assets" / "avatars"
ICONS = ROOT / "assets" / "icons"
DOCS = ROOT / "docs"

HUAHUA_SRC = ROOT / "桌面小工具图片"
XIXI_SRC = ROOT / "熙熙小胖墩" / "形象-gpt-image-2-V2" / "原图"

STATES = [
    "idle", "greet", "hover", "drag", "blush", "heart", "peace", "wink", "shades",
    "thinking", "tool", "waiting", "sleep", "success", "failure", "react-head", "react-belly",
]

PALETTES = {
    "huahua": {"ring": (237, 163, 137, 255), "bg": (255, 247, 239, 255), "accent": (91, 184, 175, 255)},
    "xixi": {"ring": (240, 100, 75, 255), "bg": (255, 247, 232, 255), "accent": (255, 197, 86, 255)},
}


def refine(im: Image.Image) -> Image.Image:
    """Remove white/green fringe colours from a pre-cut RGBA sprite."""
    im = im.convert("RGBA")
    a = np.asarray(im).astype(np.float64) / 255.0
    alpha = a[..., 3]
    if alpha.max() <= 0:
        return im
    fg = estimate_foreground_ml(
        a[..., :3], alpha, n_small_iterations=8, n_big_iterations=3
    )
    a_img = Image.fromarray((alpha * 255).astype(np.uint8), "L")
    # Kill the 1px composite rim, then restore a soft antialiased edge.
    a_img = a_img.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.55))
    arr = np.asarray(a_img).copy()
    arr[arr < 14] = 0
    a_img = Image.fromarray(arr, "L")
    out = np.dstack([np.clip(fg * 255.0, 0, 255), np.asarray(a_img)]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def normalize_huahua(im: Image.Image) -> Image.Image:
    return refine(im).crop((40, 40, 984, 984)).resize((640, 640), Image.Resampling.LANCZOS)


def normalize_xixi(im: Image.Image) -> Image.Image:
    return refine(im).resize((640, 640), Image.Resampling.LANCZOS)


def make_avatar(sprite: Image.Image, key: str, out: Path) -> Image.Image:
    """Head-and-shoulders circular avatar with the character's own accent ring."""
    pal = PALETTES[key]
    # Head area: the pack is consistently centred at x=320.
    head = sprite.crop((165, 5, 475, 315)).resize((430, 430), Image.Resampling.LANCZOS)
    # Fade the bottom of the head crop into the cream disc instead of cutting
    # a hard horizontal line across the shoulders.
    fade = Image.new("L", (430, 430), 255)
    fd = ImageDraw.Draw(fade)
    for y in range(365, 430):
        v = int(255 * max(0.0, (430 - y) / 65.0))
        fd.line([(0, y), (430, y)], fill=v)
    head.putalpha(Image.composite(head.getchannel("A"), Image.new("L", (430, 430), 0), fade))
    S = 640
    avatar = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(avatar)
    for r in range(300, 0, -1):
        t = r / 300
        base = pal["bg"]
        col = (int(base[0] - 8 * t), int(base[1] - 18 * t), int(base[2] - 26 * t), 255)
        d.ellipse((S / 2 - r, S / 2 - r, S / 2 + r, S / 2 + r), fill=col)
    d.ellipse((18, 18, S - 18, S - 18), outline=pal["ring"], width=14)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).ellipse((34, 34, S - 34, S - 34), fill=255)
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    layer.alpha_composite(head, ((S - 430) // 2, 64))
    avatar.alpha_composite(Image.composite(layer, Image.new("RGBA", (S, S), (0, 0, 0, 0)), mask))
    avatar.save(out, optimize=True)
    return avatar


def make_icon(avatar: Image.Image, key: str, png: Path, ico: Path):
    pal = PALETTES[key]
    icon = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    d = ImageDraw.Draw(icon)
    d.rounded_rectangle((16, 16, 496, 496), radius=118, fill=pal["bg"], outline=pal["ring"], width=10)
    face = avatar.resize((440, 440), Image.Resampling.LANCZOS)
    icon.alpha_composite(face, (36, 42))
    icon.save(png, optimize=True)
    icon.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def checker(size: int, cell: int = 24) -> Image.Image:
    im = Image.new("RGB", (size, size), (255, 252, 248))
    d = ImageDraw.Draw(im)
    for y in range(0, size, cell):
        for x in range(0, size, cell):
            if (x // cell + y // cell) % 2 == 0:
                d.rectangle([x, y, x + cell - 1, y + cell - 1], fill=(238, 228, 221))
    return im


def contact_sheet(images: dict[str, dict[str, Image.Image]]):
    cols, cell, gap, label_h = 6, 180, 12, 38
    rows = math.ceil(len(STATES) / cols)
    W = gap + cols * (cell + gap)
    H = 90 + 2 * (label_h + rows * (cell + label_h + gap))
    sheet = Image.new("RGB", (W, H), (255, 249, 243))
    d = ImageDraw.Draw(sheet)
    try:
        f_title = ImageFont.truetype("C:/Windows/Fonts/msyhbd.ttc", 30)
        f_name = ImageFont.truetype("C:/Windows/Fonts/msyhbd.ttc", 20)
        f_label = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 14)
    except OSError:
        f_title = f_name = f_label = ImageFont.load_default()
    d.text((gap + 2, 18), "华华 / 熙熙 · 17 表情精修预览", font=f_title, fill=(78, 54, 46))
    y0 = 68
    for key, label in (("huahua", "华华 · 温柔小织女"), ("xixi", "熙熙 · 元气小胖墩")):
        d.text((gap + 4, y0 + 2), label, font=f_name, fill=(214, 120, 92) if key == "huahua" else (224, 98, 70))
        y0 += label_h
        for i, state in enumerate(STATES):
            r, c = divmod(i, cols)
            x = gap + c * (cell + gap)
            y = y0 + r * (cell + label_h + gap)
            bg = checker(cell)
            im = images[key][state].resize((cell, cell), Image.Resampling.LANCZOS)
            bg.paste(im, (0, 0), im)
            sheet.paste(bg, (x, y))
            d.rectangle([x, y, x + cell - 1, y + cell - 1], outline=(224, 204, 192), width=1)
            d.text((x + 2, y + cell + 4), state, font=f_label, fill=(130, 105, 94))
        y0 += rows * (cell + label_h + gap) + 6
    out = DOCS / "characters.png"
    sheet.save(out)
    print("sheet", out)


def main():
    for d in (SPRITES / "huahua", SPRITES / "xixi", AVATARS, ICONS, DOCS):
        d.mkdir(parents=True, exist_ok=True)
    images: dict[str, dict[str, Image.Image]] = {"huahua": {}, "xixi": {}}
    for key, src_dir, normalize in (
        ("huahua", HUAHUA_SRC, normalize_huahua),
        ("xixi", XIXI_SRC, normalize_xixi),
    ):
        for state in STATES:
            candidates = [src_dir / f"{state}.webp", src_dir / f"{state}.png"]
            src = next((p for p in candidates if p.exists()), None)
            if not src:
                raise FileNotFoundError(f"{key}/{state}")
            with Image.open(src) as raw:
                im = normalize(raw)
            im.save(SPRITES / key / f"{state}.png", optimize=True)
            images[key][state] = im
            bbox = im.getchannel("A").point(lambda x: 255 if x > 8 else 0).getbbox()
            print(f"{key:7s} {state:12s} bbox={bbox}")

    for key in ("huahua", "xixi"):
        avatar = make_avatar(images[key]["idle"], key, AVATARS / f"{key}.png")
        make_icon(avatar, key, ICONS / f"{key}.png", ICONS / f"{key}.ico")
        # Backwards-compatible defaults: 华华 is the app's lead character.
        if key == "huahua":
            import shutil

            avatar.save(ROOT / "assets" / "avatar.png", optimize=True)
            shutil.copy2(ICONS / "huahua.ico", ROOT / "assets" / "icon.ico")
            shutil.copy2(ICONS / "huahua.png", ROOT / "assets" / "icon.png")
    contact_sheet(images)
    print("done")


if __name__ == "__main__":
    main()
