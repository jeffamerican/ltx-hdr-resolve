#!/usr/bin/env python3
"""Build repository art from the generated background."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "source" / "ltx-hdr-background.png"
SOCIAL = ROOT / "assets" / "social" / "github-social-preview.png"
README = ROOT / "assets" / "readme" / "hero.png"

FONT_BOLD = Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")
FONT_REGULAR = Path("/System/Library/Fonts/Supplemental/Arial.ttf")


def font(path, size):
    if path.exists():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def cover_crop(image, size):
    target_w, target_h = size
    src_w, src_h = image.size
    scale = max(target_w / src_w, target_h / src_h)
    resized = image.resize((round(src_w * scale), round(src_h * scale)), Image.Resampling.LANCZOS)
    left = max(0, (resized.width - target_w) // 2)
    top = max(0, (resized.height - target_h) // 2)
    return resized.crop((left, top, left + target_w, top + target_h))


def add_left_readability(image, strength=225):
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    width, height = image.size
    for x in range(width):
        alpha = int(max(0, 1 - x / (width * 0.68)) ** 1.7 * strength)
        draw.line([(x, 0), (x, height)], fill=(2, 8, 13, alpha))
    return Image.alpha_composite(image.convert("RGBA"), overlay)


def rounded_rect(draw, xy, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def draw_lockup(image, variant):
    draw = ImageDraw.Draw(image)
    w, h = image.size

    if variant == "social":
        left = 82
        top = 92
        title_size = 78
        subtitle_size = 33
        tag_size = 24
        badge_size = 24
        title_gap = 14
        max_title_width = 570
    else:
        left = 78
        top = 74
        title_size = 66
        subtitle_size = 28
        tag_size = 21
        badge_size = 21
        title_gap = 12
        max_title_width = 650

    title_font = font(FONT_BOLD, title_size)
    subtitle_font = font(FONT_REGULAR, subtitle_size)
    tag_font = font(FONT_REGULAR, tag_size)
    badge_font = font(FONT_BOLD, badge_size)

    badge = "LOCAL AI HDR ROUNDTRIP"
    badge_box = draw.textbbox((0, 0), badge, font=badge_font)
    badge_w = badge_box[2] - badge_box[0] + 30
    badge_h = badge_box[3] - badge_box[1] + 18
    rounded_rect(
        draw,
        (left, top, left + badge_w, top + badge_h),
        10,
        fill=(19, 236, 217, 42),
        outline=(119, 255, 236, 115),
    )
    draw.text((left + 15, top + 8), badge, fill=(205, 255, 247, 255), font=badge_font)

    title_y = top + badge_h + 34
    title_lines = ["LTX HDR", "Resolve"]
    for line in title_lines:
        draw.text((left + 3, title_y + 3), line, fill=(0, 0, 0, 145), font=title_font)
        draw.text((left, title_y), line, fill=(248, 252, 255, 255), font=title_font)
        title_y += title_size + title_gap

    subtitle = "SDR video to HDR EXR sequences for color grading"
    subtitle_y = title_y + 12
    draw.text((left, subtitle_y), subtitle, fill=(202, 226, 233, 255), font=subtitle_font)

    rule_y = subtitle_y + subtitle_size + 34
    draw.line((left, rule_y, left + max_title_width, rule_y), fill=(255, 190, 79, 170), width=3)

    tags = ["DaVinci Resolve", "ACEScct", "EXR", "Local GPU"]
    x = left
    tag_y = rule_y + 30
    for tag in tags:
        bbox = draw.textbbox((0, 0), tag, font=tag_font)
        tag_w = bbox[2] - bbox[0] + 26
        tag_h = bbox[3] - bbox[1] + 16
        rounded_rect(draw, (x, tag_y, x + tag_w, tag_y + tag_h), 8, fill=(255, 255, 255, 24), outline=(255, 255, 255, 55))
        draw.text((x + 13, tag_y + 7), tag, fill=(228, 238, 241, 235), font=tag_font)
        x += tag_w + 12

    # Subtle bottom vignette keeps GitHub's preview crop from feeling washed out.
    vignette = Image.new("RGBA", image.size, (0, 0, 0, 0))
    vdraw = ImageDraw.Draw(vignette)
    for y in range(h):
        alpha = int(max(0, (y - h * 0.58) / (h * 0.42)) ** 2 * 150)
        vdraw.line([(0, y), (w, y)], fill=(0, 0, 0, alpha))
    image.alpha_composite(vignette)

    return image


def save_asset(size, out_path, variant):
    image = Image.open(SOURCE).convert("RGB")
    image = cover_crop(image, size)
    image = image.filter(ImageFilter.UnsharpMask(radius=1.0, percent=112, threshold=4))
    image = add_left_readability(image, strength=238 if variant == "social" else 222)
    image = draw_lockup(image, variant)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(out_path, quality=94, optimize=True)


def main():
    save_asset((1280, 640), SOCIAL, "social")
    save_asset((1600, 520), README, "readme")
    print(SOCIAL)
    print(README)


if __name__ == "__main__":
    main()
