"""Build a readable director's storyboard board from the existing pilot refs.

This is a review artifact, not a video-generation step. The board combines
large visual keyframes with the intended performance, camera, lighting and
edit beat so the creative direction can be approved before new frames are
generated.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps


W, H = 3840, 2160
BG = (8, 12, 12)
CARD = (18, 25, 22)
TEXT = (231, 241, 233)
MUTED = (143, 164, 149)
GREEN = (130, 214, 146)
AMBER = (224, 185, 103)
RED = (237, 126, 116)


PANELS = [
    ("01", "P01", "COLD CONCRETE", "Identity-checkable instrumental beat: the singer starts a grounded dance in the frozen city before the rave energy arrives. Empty hands are fine.", "cyan / ultraviolet", "opening"),
    ("02", "P02", "FIRST VOCAL LOCK", "Close performance anchor. Hold the face, blue eyes, paint and hair in a controlled frame while the first vocal phrase lands.", "neon street bokeh", "opening"),
    ("03", "P03", "ROOFTOP CYPHER", "Identity-checkable beat-driven dance with a small group of distinct ravers. The camera stays planted; the cut supplies the new angle.", "midnight blue / magenta", "opening"),
    ("04", "P04", "UNDERPASS PRESSURE", "Frontal performance under a hard cyan/red split. The singer can perform with or without the microphone.", "red / cyan shafts", "opening"),
    ("05", "P05", "ALLEY MOMENTUM", "Three-quarter angle and wet reflections. A motivated light whip or body movement can hide the editorial cut between shots.", "hot red / electric blue", "opening"),
    ("06", "P06", "LIGHT-SHAFT LIFT", "Low angle as the energy rises. Eyes stay visible; the singer looks above the block while the oud-inspired light language begins.", "cool blue / violet", "opening"),
    ("07", "P09", "WAREHOUSE IMPACT", "Repaired medium-close candidate: focused performance on wet concrete with dancers in the distance. Blue eyes and the hair silhouette stay readable.", "magenta / steel blue", "rebuild"),
    ("08", "P15", "RAIN REFLECTION", "Repaired identity-checkable performance in reflective puddles: hands free, restrained movement, open blue eyes and no forced microphone prop.", "dusk blue / amber", "hold"),
    ("09", "P19", "STORM CODE", "Repaired aggressive close candidate with controlled handheld energy and luminous symbols. The blue-eye lock remains visible in the storm light.", "cyan / acid green", "rebuild"),
    ("10", "P23", "COLLECTIVE RELEASE", "Repaired crowd-performance candidate: the group dances in the same rave language without cloning the singer, while his blue eyes remain readable.", "neon city spectrum", "rebuild"),
    ("11", "P27", "WARM EXIT", "Repaired warm performance candidate: electric color transitions into amber while a cool rim keeps the blue eyes visible. The singer finishes empty-handed.", "amber / deep blue", "rebuild"),
    ("12", "ARC", "STREET → SIGNAL → TRANSFORMATION", "Final editorial intention: cold concrete becomes living neon through light, bodies and beat-motivated cuts. This is the target language for the full clip.", "full-spectrum crescendo", "concept"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production-dir", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    return parser.parse_args()


def font(path: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [Path(path), Path("C:/Windows/Fonts/segoeui.ttf"), Path("C:/Windows/Fonts/arial.ttf")]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def wrap(draw: ImageDraw.ImageDraw, text: str, face: ImageFont.ImageFont, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        words = paragraph.split()
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and draw.textbbox((0, 0), candidate, font=face)[2] > width:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
    return lines or [""]


def gradient(size: tuple[int, int], colors: tuple[tuple[int, int, int], tuple[int, int, int]]) -> Image.Image:
    image = Image.new("RGB", size)
    pixels = image.load()
    start, end = colors
    for y in range(size[1]):
        ratio = y / max(1, size[1] - 1)
        value = tuple(int(start[index] * (1 - ratio) + end[index] * ratio) for index in range(3))
        for x in range(size[0]):
            pixels[x, y] = value
    return image


def concept_keyframe(size: tuple[int, int]) -> Image.Image:
    image = gradient(size, ((9, 15, 24), (24, 9, 31)))
    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    for offset, color in enumerate(((21, 225, 247, 170), (245, 42, 196, 160), (156, 255, 57, 140), (255, 179, 65, 130))):
        points = []
        for x in range(-30, size[0] + 40, 12):
            y = int(size[1] * (0.28 + offset * 0.12) + 55 * __import__("math").sin(x / 85 + offset))
            points.append((x, y))
        draw.line(points, fill=color, width=12)
    glow = glow.filter(ImageFilter.GaussianBlur(9))
    image = Image.alpha_composite(image.convert("RGBA"), glow)
    sharp = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(sharp)
    for offset, color in enumerate(((71, 235, 255, 245), (255, 76, 218, 235), (176, 255, 75, 220), (255, 198, 89, 215))):
        points = []
        for x in range(-30, size[0] + 40, 16):
            y = int(size[1] * (0.28 + offset * 0.12) + 55 * __import__("math").sin(x / 85 + offset))
            points.append((x, y))
        draw.line(points, fill=color, width=4)
    return Image.alpha_composite(image, sharp).convert("RGB")


def fit_frame(path: Path, size: tuple[int, int], accent: tuple[int, int, int]) -> Image.Image:
    if not path.is_file():
        return Image.new("RGB", size, (25, 31, 28))
    source = Image.open(path).convert("RGB")
    # Preserve the portrait performer rather than cropping away the identity.
    canvas = Image.new("RGB", size, (7, 11, 10))
    fitted = ImageOps.contain(source, size, Image.Resampling.LANCZOS)
    canvas.paste(fitted, ((size[0] - fitted.width) // 2, (size[1] - fitted.height) // 2))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, size[0] - 1, size[1] - 1), outline=accent, width=4)
    return canvas


def build_board(production_dir: Path, destination: Path) -> Path:
    frame_dir = production_dir / "references" / "pilot_opening_frames"
    repair_dir = production_dir / "references" / "qc_fix_v002"
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    title_font = font("C:/Windows/Fonts/seguilb.ttf", 54)
    subtitle_font = font("C:/Windows/Fonts/segoeui.ttf", 24)
    label_font = font("C:/Windows/Fonts/seguisb.ttf", 22)
    heading_font = font("C:/Windows/Fonts/seguilb.ttf", 31)
    body_font = font("C:/Windows/Fonts/segoeui.ttf", 23)
    small_font = font("C:/Windows/Fonts/segoeui.ttf", 18)

    draw.rectangle((0, 0, W, 174), fill=(13, 24, 18))
    draw.rectangle((0, 171, W, 174), fill=GREEN)
    draw.text((42, 26), "SHADOW ON THE BLOCK", fill=TEXT, font=title_font)
    draw.text((42, 101), "DIRECTOR'S STORYBOARD  /  VISUAL INTENTION BOARD  /  PRE-GENERATION REVIEW", fill=MUTED, font=subtitle_font)
    draw.text((W - 665, 44), "PSYCHEDELIC DUBSTEP-REGGAE", fill=(184, 228, 194), font=small_font)
    draw.text((W - 665, 80), "LIGHT · MOVEMENT · IDENTITY · CUT", fill=(118, 173, 130), font=small_font)

    margin_x, top, gap_x, gap_y = 38, 204, 24, 20
    cols, rows = 3, 4
    cell_w = (W - margin_x * 2 - gap_x * (cols - 1)) // cols
    cell_h = (H - top - 44 - gap_y * (rows - 1)) // rows
    image_w, inner_pad = 338, 16
    paths = {path.stem.split("_")[0].upper(): path for path in frame_dir.glob("*.png")}
    # Put the newly repaired candidate in the director board when one exists;
    # the old rejected frame remains in the review gallery as evidence.
    for path in repair_dir.glob("*.png"):
        paths[path.stem.split("_")[0].upper()] = path

    accent_by_status = {"opening": GREEN, "hold": AMBER, "rebuild": RED, "concept": (133, 191, 247)}
    status_text = {"opening": "ANCHOR", "hold": "CHECK", "rebuild": "REBUILD", "concept": "TARGET"}
    for index, (number, shot, heading, description, palette, status) in enumerate(PANELS):
        column, row = index % cols, index // cols
        x, y = margin_x + column * (cell_w + gap_x), top + row * (cell_h + gap_y)
        accent = accent_by_status[status]
        draw.rounded_rectangle((x, y, x + cell_w, y + cell_h), radius=16, fill=CARD, outline=(48, 67, 55), width=2)
        draw.rectangle((x, y, x + 9, y + cell_h), fill=accent)

        visual_size = (image_w, cell_h - inner_pad * 2)
        if shot == "ARC":
            visual = concept_keyframe(visual_size)
        else:
            visual = fit_frame(paths.get(shot), visual_size, accent)
        image.paste(visual, (x + inner_pad + 9, y + inner_pad))

        text_x = x + image_w + 43
        text_width = cell_w - image_w - 65
        draw.text((text_x, y + 21), f"{number}  /  {shot}", fill=accent, font=label_font)
        draw.text((text_x, y + 59), heading, fill=TEXT, font=heading_font)
        rendered_status = "REPAIR CANDIDATE" if shot != "ARC" and paths.get(shot) and shot in {"P01", "P03", "P09", "P15", "P19", "P23", "P27"} else status_text[status]
        draw.text((text_x, y + 106), rendered_status, fill=accent, font=small_font)
        description_lines = wrap(draw, description, body_font, text_width)
        cursor_y = y + 151
        for line in description_lines:
            draw.text((text_x, cursor_y), line, fill=(177, 193, 181), font=body_font)
            cursor_y += 31
        draw.text((text_x, y + cell_h - 40), palette.upper(), fill=(107, 139, 116), font=small_font)

    footer_y = H - 27
    draw.text((margin_x, footer_y), "Storyboard intention only · repair candidates are unapproved until user review · exact timing remains Whisper-backed", fill=(99, 122, 105), font=small_font)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, quality=95, subsampling=0)
    return destination


if __name__ == "__main__":
    args = parse_args()
    print(build_board(args.production_dir.resolve(), args.destination.resolve()))
