#!/usr/bin/env python3
"""Validate the hard invariants of the realistic rap-video POC manifest.

The validator is intentionally conservative. It checks planning/assembly metadata
without trying to infer creative intent from filenames or lyric text.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


INTEGER_FIELDS = {
    "editorial_duration",
    "audio_duration",
    "model_audio_duration",
    "generation_duration",
    "overlap_seconds",
    "trim_in_seconds",
    "trim_out_seconds",
}

REQUIRED_SHOT_FIELDS = {
    "id",
    "section",
    "editorial_start",
    "editorial_end",
    "editorial_duration",
    "model_audio_start",
    "model_audio_end",
    "model_audio_duration",
    "generation_duration",
    "overlap_seconds",
    "trim_in_seconds",
    "trim_out_seconds",
    "model",
    "performance_owner",
    "opening_frame_path",
    "previous_shot_id",
    "next_shot_id",
    "transition_in",
    "transition_out",
}


def is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def validate_shots(data: dict[str, Any], errors: list[str]) -> None:
    shots = data.get("shots")
    if not isinstance(shots, list) or not shots:
        fail(errors, "manifest.shots must be a non-empty array")
        return

    profile = data.get("execution_profile", {})
    if not isinstance(profile, dict):
        fail(errors, "execution_profile must be an object")
        profile = {}

    if profile.get("aspect_ratio") != "1:1":
        fail(errors, "execution_profile.aspect_ratio must be 1:1")
    if profile.get("target_megapixels") not in (1, 1.0):
        fail(errors, "execution_profile.target_megapixels must be 1")
    if profile.get("raw_generation_duration") != 5:
        fail(errors, "execution_profile.raw_generation_duration must be exactly 5")

    for index, shot in enumerate(shots, start=1):
        label = str(shot.get("id", f"shot[{index}]")) if isinstance(shot, dict) else f"shot[{index}]"
        if not isinstance(shot, dict):
            fail(errors, f"{label}: shot must be an object")
            continue

        missing = sorted(REQUIRED_SHOT_FIELDS - set(shot))
        if missing:
            fail(errors, f"{label}: missing required fields: {', '.join(missing)}")

        for field in INTEGER_FIELDS:
            if field in shot and not is_integer(shot[field]):
                fail(errors, f"{label}: {field} must be an integer")

        if shot.get("generation_duration") != 5:
            fail(errors, f"{label}: generation_duration must be exactly 5")

        if shot.get("aspect_ratio", profile.get("aspect_ratio")) not in (None, "1:1"):
            fail(errors, f"{label}: aspect_ratio must be 1:1")
        megapixels = shot.get("target_megapixels", profile.get("target_megapixels"))
        if megapixels not in (None, 1, 1.0):
            fail(errors, f"{label}: target_megapixels must be 1")

        owner = shot.get("performance_owner")
        if owner not in {"main_mc", "phantom", "instrumental_only", "both_nonvocal"}:
            fail(errors, f"{label}: performance_owner is missing or invalid")

        mode = shot.get("model")
        lip_sync = mode in {"turbo_lipsync", "Turbo Lip-sync", "turbo lip-sync"}
        if lip_sync:
            for field in ("model_audio_start", "model_audio_end", "overlap_seconds", "trim_in_seconds"):
                if field not in shot:
                    fail(errors, f"{label}: lip-sync shot is missing {field}")
            for field in ("overlap_seconds", "trim_in_seconds"):
                value = shot.get(field)
                if value is not None and is_integer(value) and value < 0:
                    fail(errors, f"{label}: {field} cannot be negative")
            if "overlap_seconds" in shot and "trim_in_seconds" in shot:
                if shot["overlap_seconds"] != shot["trim_in_seconds"]:
                    fail(errors, f"{label}: overlap_seconds must equal trim_in_seconds")

        raw_path = shot.get("raw_clip") or shot.get("approved_raw_clip")
        if raw_path:
            path_text = str(raw_path).lower()
            if any(token in path_text for token in ("rejected", "superseded", "latest", "fallback", "generic")):
                fail(errors, f"{label}: raw clip points at a rejected/superseded/generic artifact")
            if shot.get("artifact_status") != "user_approved":
                fail(errors, f"{label}: a raw clip may enter the manifest only after user approval")
            if not shot.get("approved_artifact_id"):
                fail(errors, f"{label}: approved_artifact_id is required for a raw clip")


def validate_assembly(data: dict[str, Any], errors: list[str]) -> None:
    clips = data.get("clips") or data.get("segments")
    if not isinstance(clips, list) or not clips:
        return

    for index, clip in enumerate(clips, start=1):
        label = str(clip.get("id", f"clip[{index}]")) if isinstance(clip, dict) else f"clip[{index}]"
        if not isinstance(clip, dict):
            fail(errors, f"{label}: clip must be an object")
            continue
        method = str(clip.get("gap_fill_method", "")).lower()
        if any(token in method for token in ("hold", "freeze", "duplicate", "tpad", "still")):
            fail(errors, f"{label}: frame-hold/duplicate gap filling is forbidden")
        if clip.get("artifact_status") and clip["artifact_status"] != "user_approved":
            fail(errors, f"{label}: assembly clip is not user_approved")

    ledger = data.get("approval_ledger")
    if ledger is not None and not isinstance(ledger, (dict, list)):
        fail(errors, "approval_ledger must be an object or array")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()

    try:
        data = json.loads(args.manifest.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - CLI error path
        print(f"ERROR: cannot read {args.manifest}: {exc}", file=sys.stderr)
        return 2

    if not isinstance(data, dict):
        print("ERROR: manifest root must be an object", file=sys.stderr)
        return 2

    errors: list[str] = []
    validate_shots(data, errors)
    validate_assembly(data, errors)

    if errors:
        print("POC manifest FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print("POC manifest PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
