"""Build a review-only gallery and storyboard package for the current pilot.

The production folder is intentionally treated as evidence. This script does
not alter shot status, approve footage, or start a generation job. It copies
the supplied singer reference into the review package, indexes every existing
image artifact, and creates deterministic contact sheets for fast inspection.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from math import ceil
from pathlib import Path
from typing import Any


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
SHOT_PATTERN = re.compile(r"(?i)(P\d{2})")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--production-dir",
        type=Path,
        default=Path("state/productions/shadow_on_the_block_20260901"),
    )
    parser.add_argument("--reference", type=Path, required=True)
    return parser.parse_args()


def parse_shot_manifest(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| P"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 7:
            continue
        rows.append(
            {
                "shot": cells[0],
                "editorial_window": cells[1],
                "generation_window": cells[2],
                "mode": cells[3],
                "seed": cells[4],
                "job": cells[5],
                "status": cells[6],
            }
        )
    return rows


def shot_from_path(path: Path) -> str | None:
    match = SHOT_PATTERN.search(path.as_posix())
    return match.group(1).upper() if match else None


def status_class(status: str) -> str:
    value = status.casefold()
    if "rejected" in value:
        return "rejected"
    if "approved" in value:
        return "approved"
    if "completed" in value:
        return "completed"
    if "retry" in value:
        return "retry"
    if "queued" in value:
        return "queued"
    return "evidence"


def category_for(path: Path) -> str:
    parts = {part.casefold() for part in path.parts}
    if "pilot_opening_frames" in parts or "qc_fix_v002" in parts:
        return "opening"
    if "pilot_qc" in parts or "qc" in parts or "qc_fix_inspect" in parts:
        return "evidence"
    return "other"


def identity_audit() -> dict[str, Any]:
    """Human-reviewed identity gate for the existing frame evidence.

    This is deliberately explicit rather than pretending that a contact sheet
    can certify every pixel. The page exposes the evidence and the unresolved
    checks so the user can approve or reject the next production gate.
    """
    return {
        "status": "hold",
        "scope": "11 original opening frames plus 7 new repair candidates and all indexed still-image evidence",
        "method": (
            "Full-resolution inspection of the original opening-frame set and the new repair candidates, "
            "plus contact-sheet inspection of the indexed QC/retry evidence. Lip-sync and mouth-motion are "
            "not certified from stills."
        ),
        "anchor": [
            "dark-skinned, muscular male singer",
            "long blue/teal dreadlocks with fluorescent beads",
            "vivid geometric neon face paint",
            "bright blue eyes when visible",
            "short beard, black mesh vest, layered beads and triangular pendant",
            "fluorescent arm wraps; microphone optional and never an identity requirement",
        ],
        "findings": [
            {
                "shot": "P02",
                "status": "pass",
                "note": "Strong close performance anchor; face paint, hair, wardrobe and blue-eye read are clear.",
            },
            {
                "shot": "P04",
                "status": "pass",
                "note": "Strong frontal identity match with clear eyes and repeated wardrobe details.",
            },
            {
                "shot": "P05",
                "status": "pass",
                "note": "Profile/three-quarter variation preserves the same dreadlocks, paint and costume language.",
            },
            {
                "shot": "P06",
                "status": "pass",
                "note": "Low-angle variation preserves the singer; blue eyes remain readable in the cool light.",
            },
            {
                "shot": "P01",
                "status": "hold",
                "note": "Good full-body dance identity, but the eyes are too small for a definitive color check.",
            },
            {
                "shot": "P03",
                "status": "hold",
                "note": "Good performance/dance identity; wide framing makes eye-color certification weak.",
            },
            {
                "shot": "P09",
                "status": "reject",
                "note": "Existing user rejection stands: eyes read dark and the hair/identity drift is visible.",
            },
            {
                "shot": "P15",
                "status": "hold",
                "note": "Face and wardrobe are close, but the opening pose has closed eyes; do not use as an identity anchor.",
            },
            {
                "shot": "P19",
                "status": "reject",
                "note": "Eyes read dark instead of the reference blue; replace before production use.",
            },
            {
                "shot": "P23",
                "status": "reject",
                "note": "Eyes do not preserve the reference blue; reject this frame until the identity is relit or regenerated.",
            },
            {
                "shot": "P27",
                "status": "reject",
                "note": "Warm lighting makes the eyes read dark; replace or relight to preserve the blue-eye anchor.",
            },
        ],
        "next_gate": (
            "Seven repair candidates now exist for P01, P03, P09, P15, P19, P23 and P27. User review is still required "
            "before replacing the original frames or assembling a final master."
        ),
    }


def make_contact_sheet(
    entries: list[dict[str, Any]],
    destination: Path,
    *,
    title: str,
    columns: int,
    tile_width: int = 250,
    tile_height: int = 330,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not entries:
        raise ValueError(f"Cannot build an empty contact sheet: {title}")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is required to build the review contact sheets")

    rows = max(1, ceil(len(entries) / columns))
    inputs: list[str] = []
    filters: list[str] = []
    layouts: list[str] = []
    inner_width = tile_width - 16
    inner_height = tile_height - 64
    for index, entry in enumerate(entries):
        inputs.extend(["-i", str(Path(entry["absolute_path"]).resolve())])
        filters.append(
            f"[{index}:v]scale={inner_width}:{inner_height}:force_original_aspect_ratio=decrease,"
            f"pad={inner_width}:{inner_height}:(ow-iw)/2:(oh-ih)/2:color=0x19202a,"
            f"setsar=1[v{index}]"
        )
        x = (index % columns) * tile_width
        y = (index // columns) * tile_height
        layouts.append(f"{x}_{y}")
    stacked_inputs = "".join(f"[v{index}]" for index in range(len(entries)))
    filter_graph = ";".join(filters) + ";" + stacked_inputs + (
        f"xstack=inputs={len(entries)}:layout={'|'.join(layouts)}:fill=black[outv]"
    )
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        *inputs,
        "-filter_complex",
        filter_graph,
        "-map",
        "[outv]",
        "-frames:v",
        "1",
        str(destination),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(f"ffmpeg contact sheet failed for {title}: {result.stderr.strip()}")


def build_review(production_dir: Path, reference: Path) -> Path:
    production_dir = production_dir.resolve()
    if not production_dir.is_dir():
        raise SystemExit(f"Production directory not found: {production_dir}")
    reference = reference.resolve()
    if not reference.is_file():
        raise SystemExit(f"Reference image not found: {reference}")

    review_dir = production_dir / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    reference_copy = review_dir / "singer_reference.jpg"
    shutil.copy2(reference, reference_copy)

    source_images: list[dict[str, Any]] = []
    for path in sorted(production_dir.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file() or path.suffix.casefold() not in IMAGE_EXTENSIONS:
            continue
        relative = path.relative_to(production_dir)
        if relative.parts and relative.parts[0].casefold() == "review":
            continue
        # Ignore ad-hoc inspection exports at the production root. The
        # production frame evidence lives under references, pilot_qc, or
        # pilot_outputs; this keeps a temporary test sheet out of the audit.
        if len(relative.parts) == 1:
            continue
        shot = shot_from_path(relative)
        category = category_for(relative)
        source_images.append(
            {
                "path": relative.as_posix(),
                "absolute_path": str(path),
                "shot": shot,
                "category": category,
                "label": path.stem,
                "revision": (
                    "repair_candidate" if "qc_fix_v002" in relative.as_posix().casefold()
                    else "retry" if "retry" in relative.as_posix().casefold()
                    else "original"
                ),
                "status": "evidence",
            }
        )

    shot_rows = parse_shot_manifest(production_dir / "pilot_outputs" / "pilot_batch_manifest_v001.md")
    status_by_shot = {row["shot"].upper(): row["status"] for row in shot_rows}
    for image in source_images:
        source_status = status_by_shot.get(str(image.get("shot") or "").upper())
        if image["revision"] == "repair_candidate":
            image["status"] = "repair candidate · pending user approval"
        else:
            image["status"] = source_status or ("retry evidence" if image["revision"] == "retry" else "evidence only")

    reference_entry = {
        "absolute_path": str(reference_copy),
        "shot": "REF",
        "label": "Singer identity anchor",
        "status": "approved reference",
    }
    opening_entries = [item for item in source_images if item["category"] == "opening"]
    make_contact_sheet(
        opening_entries,
        review_dir / "opening_frames_contact.jpg",
        title="Singer reference + all available opening frames",
        columns=4,
        tile_width=250,
        tile_height=350,
    )

    contact_sheets: list[str] = ["review/opening_frames_contact.jpg"]
    evidence_entries = [item for item in source_images if item["category"] != "opening"]
    for index in range(0, len(evidence_entries), 16):
        chunk = evidence_entries[index : index + 16]
        filename = f"frame_evidence_{index // 16 + 1:02d}.jpg"
        make_contact_sheet(
            chunk,
            review_dir / filename,
            title=f"Generated frame evidence {index // 16 + 1}",
            columns=4,
            tile_width=250,
            tile_height=330,
        )
        contact_sheets.append(f"review/{filename}")

    preferred_storyboard_shots = ["P01", "P02", "P04", "P06", "P09", "P15", "P19", "P23", "P27"]
    opening_by_shot: dict[str, dict[str, Any]] = {}
    for item in source_images:
        if item["category"] != "opening" or not item.get("shot"):
            continue
        current = opening_by_shot.get(item["shot"])
        if current is None or item["revision"] == "repair_candidate":
            opening_by_shot[item["shot"]] = item
    storyboard_entries = [opening_by_shot[shot] for shot in preferred_storyboard_shots if shot in opening_by_shot]
    make_contact_sheet(
        storyboard_entries,
        review_dir / "storyboard_contact_sheet.jpg",
        title="Editorial arc storyboard from actual opening-frame references",
        columns=3,
        tile_width=360,
        tile_height=300,
    )
    # The director previsualization board is the storyboard deliverable. Keep
    # the old thumbnail contact sheet out of the review page so it cannot be
    # mistaken for the approved storyboard presentation.
    if not list(review_dir.glob("storyboard_board_v*.jpg")):
        contact_sheets.append("review/storyboard_contact_sheet.jpg")

    videos = [
        path.relative_to(production_dir).as_posix()
        for path in sorted(production_dir.rglob("*.mp4"), key=lambda item: item.as_posix().casefold())
        if path.is_file()
    ]
    videos_by_shot: dict[str, list[str]] = {}
    for path in videos:
        shot = shot_from_path(Path(path))
        if shot:
            videos_by_shot.setdefault(shot, []).append(path)

    shots: list[dict[str, Any]] = []
    for row in shot_rows:
        shot = row["shot"].upper()
        shots.append(
            {
                **row,
                "shot": shot,
                "status_class": status_class(row["status"]),
                "images": [item["path"] for item in source_images if item.get("shot") == shot],
                "video_files": videos_by_shot.get(shot, []),
            }
        )

    public_images = [{key: value for key, value in item.items() if key != "absolute_path"} for item in source_images]
    storyboard_boards = sorted(review_dir.glob("storyboard_board_v*.jpg"))
    storyboard_board = storyboard_boards[-1] if storyboard_boards else None
    storyboard_image = (
        f"review/{storyboard_board.name}" if storyboard_board else "review/storyboard_contact_sheet.jpg"
    )
    manifest = {
        "schema": "shadow_on_the_block.frame_review.v1",
        "title": "Shadow on the Block — frame and storyboard review",
        "production_id": production_dir.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "review_only": True,
        "reference_image": "review/singer_reference.jpg",
        "storyboard_image": storyboard_image,
        "storyboard_image_kind": "director_previsualization_board" if storyboard_board else "opening_frame_contact_sheet",
        "contact_sheets": contact_sheets,
        "source_documents": [
            "analysis/whisper_timeline_v001.md",
            "storyboard_v001.md",
            "treatment_v001.md",
            "pilot_outputs/pilot_batch_manifest_v001.md",
        ],
        "summary": {
            "planned_shots": len(shots),
            "available_opening_frames": sum(1 for item in source_images if item["category"] == "opening"),
            "available_image_evidence": len(source_images),
            "available_video_clips": len(videos),
            "final_master_exists": any("final" in Path(path).stem.casefold() for path in videos),
            "user_rejected_shots": [shot for shot, status in status_by_shot.items() if "rejected" in status.casefold()],
        },
        "identity_audit": identity_audit(),
        "shots": shots,
        "images": public_images,
        "videos": videos,
    }
    manifest_path = review_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


if __name__ == "__main__":
    args = parse_args()
    print(build_review(args.production_dir, args.reference))
