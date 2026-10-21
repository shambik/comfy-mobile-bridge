"""Detect LTX reference clips that show the reference sheet itself.

LTX's Ingredients IC-LoRA sometimes opens a clip on the sheet (or on a collage
or zoomed piece of it) before cutting to the scene. Two cues catch those frames:

- Region match: the frame is split into a grid and compared, cell by cell, with
  the same cells of the sheet letterboxed exactly as the workflow feeds it.
  Whole-sheet and collage frames leave several cells nearly identical to the
  sheet; real scenes leave none, even when they borrow its colours.
- Panel gutters: a zoomed piece of the sheet keeps its straight black gutters,
  which run the full width or height of the frame away from the edges. Black
  letterbox bars along the top and bottom edges are ignored, because the model
  also renders genuine scenes with cinema bars.

Speed-lab calibration on 29 clips (9 broken, 20 clean, two different sheets):
broken frames left 10-40 cells within 18 of the sheet or 8-20 interior gutter
lines; clean frames left no such cells and no interior gutter lines.
"""
from pathlib import Path

import av
import numpy as np
from PIL import Image

# The grid the workflow letterboxes the sheet onto (workflows.LTX_REFERENCE_GRID).
SHEET_GRID = (768, 448)
_CELL_SIZE = (256, 150)
_CELLS = (8, 5)
CELL_MATCH_DIFF = 18.0
CELL_MATCH_COUNT = 4
_GUTTER_SIZE = (1536, 896)
_GUTTER_DARK = 25
_GUTTER_COVERAGE = 0.88
GUTTER_LINE_COUNT = 4


def _letterboxed_sheet(sheet: Path) -> np.ndarray:
    with Image.open(sheet) as image:
        image = image.convert("RGB")
        scale = min(SHEET_GRID[0] / image.width, SHEET_GRID[1] / image.height)
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        canvas = Image.new("RGB", SHEET_GRID)
        canvas.paste(image.resize(size, Image.LANCZOS),
                     ((SHEET_GRID[0] - size[0]) // 2, (SHEET_GRID[1] - size[1]) // 2))
    return np.asarray(canvas.resize(_CELL_SIZE, Image.BILINEAR)).astype(np.float32)


def _sheet_cells(sheet: np.ndarray) -> list[tuple[slice, slice, np.ndarray]]:
    """Grid cells of the sheet, skipping pure-black letterbox cells that match any dark frame."""
    width, height = _CELL_SIZE
    cells = []
    for row in range(_CELLS[1]):
        for column in range(_CELLS[0]):
            ys = slice(row * height // _CELLS[1], (row + 1) * height // _CELLS[1])
            xs = slice(column * width // _CELLS[0], (column + 1) * width // _CELLS[0])
            if sheet[ys, xs].max() >= 20:
                cells.append((ys, xs, sheet[ys, xs]))
    return cells


def _matching_cells(frame: np.ndarray, cells) -> int:
    return sum(float(np.abs(frame[ys, xs] - reference).mean()) < CELL_MATCH_DIFF for ys, xs, reference in cells)


def _interior_lines(flags: np.ndarray) -> int:
    """Count flagged lines left after dropping runs that touch either edge (letterbox bars)."""
    flags = flags.copy()
    start = 0
    while start < len(flags) and flags[start]:
        flags[start] = False
        start += 1
    end = len(flags) - 1
    while end >= 0 and flags[end]:
        flags[end] = False
        end -= 1
    return int(flags.sum())


def _gutter_lines(gray: np.ndarray) -> int:
    dark = gray < _GUTTER_DARK
    return (_interior_lines(dark.mean(axis=1) > _GUTTER_COVERAGE)
            + _interior_lines(dark.mean(axis=0) > _GUTTER_COVERAGE))


def sheet_frames(video: Path, sheet: Path) -> dict:
    """Return which frames of ``video`` show the reference ``sheet``."""
    cells = _sheet_cells(_letterboxed_sheet(sheet))
    flagged: list[int] = []
    best_cells = best_lines = 0
    total = 0
    with av.open(str(video)) as container:
        for index, frame in enumerate(container.decode(video=0)):
            total += 1
            image = frame.to_image().convert("RGB")
            matching = _matching_cells(np.asarray(image.resize(_CELL_SIZE, Image.BILINEAR)).astype(np.float32), cells)
            lines = _gutter_lines(np.asarray(image.convert("L").resize(_GUTTER_SIZE, Image.BILINEAR)))
            best_cells = max(best_cells, matching)
            best_lines = max(best_lines, lines)
            if matching >= CELL_MATCH_COUNT or lines >= GUTTER_LINE_COUNT:
                flagged.append(index)
    return {
        "frames": total,
        "sheet_frames": flagged,
        "shows_sheet": bool(flagged),
        "max_matching_cells": best_cells,
        "max_gutter_lines": best_lines,
    }
