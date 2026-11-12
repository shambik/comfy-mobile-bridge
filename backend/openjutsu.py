"""Openjutsu character swap (issue #58): D3voz/openjutsu's Advanced swap as a third swap engine.

The graph is D3voz's own export (`workflows/openjutsu/advanced.api.json`, D3voz/openjutsu 7fe118b, MIT). Per clip
(6 s pieces, 39 frames of overlap, chained by the MiniMax H3 Context Loop pack) SAM 3.1 tracks every person, the
Qwen3-VL 8B describer labels which track is the role, H3 redraws only that person's mask (+40 px) from the
character picture, copying the motion from a grey mannequin of the source person.

This module applies the same pruning as Openjutsu's app (lib/advanced.ts with its defaults: one picture, hat fix
off, lip-sync on, normal margin, 512 px motion reference) plus two fixes measured in the lab on 2026-11-12
(D:/h3-omnilab/tests/openjutsu/RESULTS.md):

1. A clip where the person is off screen has an empty mask; upstream MiniMaxH3FantasticVideoEditLatent then raises
   "The mask is empty on every frame" and the whole chain stops. `patches/fantastic-promptbuilder-empty-mask.patch`
   keeps such a clip instead (the worker checks that the patch is installed).
2. A character whose hair differs (bald) inherits the source hair silhouette from the mannequin. With
   `remove_hair`, everyone but the replaced person is greyed out, SAM 3.1 detects "hair" per frame on them alone
   and that area is filled from its surroundings in the mannequin (custom_nodes/ComfyUI-H3-OpenjutsuHelpers). A
   whole-frame SAM hair track locked on another person's hair and missed the man who entered later.

Tested limits: 1-3 characters (user: "Allow 3" after the 2026-11-12 multi test: boxing 2/2, beach party 3/3; with 4
one person started wrong for 2-4 s), one clean picture each (a poster of several faces made the describer take the
wrong face), up to 15.1 s (The Last Fold), 480p (864x480 for 16:9) and 736p (1312x736).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

GRAPH_FILE = Path(__file__).resolve().parents[1] / "workflows" / "openjutsu" / "advanced.api.json"
TEXT_ENCODER = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"   # the app's; Openjutsu ships int4 convrot
DESCRIBER = "qwen3vl_8b_int8_convrot.safetensors"
from .video_edit import DMAD_LORA, EDIT_LORA_DIR, edit_lora_name   # the app's DMAD LoRA lives in loras/h3_edit

MODELS = [("diffusion_models", "minimax_h3_ref2va_pruned_int8_convrot.safetensors"),
          (f"loras/{EDIT_LORA_DIR}", DMAD_LORA),
          ("text_encoders", TEXT_ENCODER), ("text_encoders", DESCRIBER),
          ("vae", "minimax_h3_video_vae_int8_convrot.safetensors"), ("vae", "minimax_h3_audio_vae_fp32.safetensors"),
          ("checkpoints", "sam3.1_multiplex_fp16.safetensors")]
RESOLUTIONS = {"480p": 480, "736p": 736}
MAX_CHARACTERS = 3
MAX_SECONDS = 15.1          # the longest tested clip (The Last Fold, 15.08 s)
CLIP_SECONDS = 6            # Openjutsu's default piece length
STEPS = 6                   # Openjutsu's default (DMAD speed LoRA)
MARGIN = 40                 # Openjutsu's "normal" mask margin
MOTION_SIZE = 512           # Openjutsu's default motion reference
MINUTES_PER_SECOND = {"480p": 1.0, "736p": 1.9}   # measured: 15 s in 13-15 min (480p), 27 min (736p)
PLAN = "Swap Plan (roles, seed, size)"
VIDEO = "Source video (people get replaced)"
HELPER_NODES = ("H3KeepMaskedArea", "H3MaskMultiply", "H3InpaintArea")
NO_LIP_SYNC = {"No lip-sync in the prompt", "SAM: faces", "SAM 3.1 track faces", "Faces (shown on the mannequin)",
               "Faces (shown on the mannequins)"}


def canvas(width: int, height: int, resolution: str) -> tuple[int, int]:
    """The render size, as Openjutsu's canvasSize(): the short side to the preset, each side rounded to 32."""
    scale = RESOLUTIONS[resolution] / min(width, height)
    return tuple(max(32, round(side * scale / 32) * 32) for side in (width, height))


def _link(value) -> bool:
    return isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], int)


def by_title(graph: dict, title: str) -> str:
    ids = [i for i, n in graph.items() if n.get("_meta", {}).get("title") == title]
    if len(ids) != 1:
        raise ValueError(f"Openjutsu graph: expected one {title!r} node, found {len(ids)}")
    return ids[0]


def _drop_no_lip_sync(graph: dict) -> None:
    """Openjutsu's dropNoLipSync: lip-sync on, so H3 hears the soundtrack; the mute nodes pass their audio on."""
    through = {}
    for i, node in list(graph.items()):
        title = node.get("_meta", {}).get("title", "")
        if re.fullmatch(r"Mute the (clip|reference) audio H3 hears", title):
            through[i] = node["inputs"]["audio"]
        elif title in NO_LIP_SYNC:
            through[i] = None
    for i in through:
        del graph[i]
    for i, node in graph.items():
        for key, value in list(node["inputs"].items()):
            if _link(value) and value[0] in through:
                if through[value[0]] is not None:
                    node["inputs"][key] = through[value[0]]
                elif key in ("no_lip_sync", "faces", "face_size"):
                    del node["inputs"][key]
                else:
                    raise ValueError(f"Openjutsu graph: {i}.{key} still links to removed {value[0]}")


def _prune(graph: dict, resolution: str, roles: list[str], seed: int) -> dict:
    """Openjutsu's pruneAdvanced for len(roles) pictures with its defaults."""
    removed, bypass = set(), {}
    for k in range(len(roles) + 1, 5):
        load = by_title(graph, f"Picture {k}")
        shrink = next((i for i, n in graph.items() if n["class_type"] == "ImageScaleToMaxDimension"
                       and n["inputs"].get("image") == [load, 0]), None)
        removed |= {x for x in (load, shrink, by_title(graph, f"Describe picture {k}")) if x}
    for i, node in graph.items():                                   # hat fix off
        if re.search(r"\bhats?\b", node.get("_meta", {}).get("title", ""), re.I):
            removed.add(i)
            if node["class_type"] == "MaskComposite" and node["inputs"].get("operation") == "add":
                bypass[i] = node["inputs"]["destination"]
    for i in removed:
        del graph[i]
    for i, node in graph.items():
        for key, value in list(node["inputs"].items()):
            if _link(value) and value[0] in removed:
                if value[0] in bypass:
                    node["inputs"][key] = bypass[value[0]]
                elif re.match(r"picture_\d", key) or key.startswith("ref_images."):
                    del node["inputs"][key]
                else:
                    raise ValueError(f"Openjutsu graph: {i}.{key} still links to removed {value[0]}")
    _drop_no_lip_sync(graph)
    for node in graph.values():
        if node["class_type"] == "GrowMaskWithBlur" and " grow mask " in node.get("_meta", {}).get("title", ""):
            node["inputs"]["expand"] = MARGIN
        if node["class_type"] == "ImageScaleToMaxDimension" and "motion reference" in node.get("_meta", {}).get("title", "").lower():
            node["inputs"]["largest_size"] = MOTION_SIZE
        if node["class_type"] == "CLIPLoader" and node["inputs"].get("type") == "minimax":
            node["inputs"]["clip_name"] = TEXT_ENCODER
        if node["class_type"] == "LoraLoaderModelOnly" and node["inputs"].get("lora_name", "").endswith(DMAD_LORA):
            node["inputs"]["lora_name"] = edit_lora_name(DMAD_LORA)
    graph[by_title(graph, PLAN)]["inputs"].update(
        {"resolution": resolution, "seed": seed % 2 ** 32, "clip_seconds": CLIP_SECONDS, "steps": STEPS,
         "roles": "\n".join(roles)})
    return graph


def _remove_hair(graph: dict) -> None:
    """Erase the replaced person's hair from the grey mannequin before H3 sees it (the edit mask is unchanged)."""
    sam = next(i for i, n in graph.items() if n["class_type"] == "CheckpointLoaderSimple")
    frames = by_title(graph, "SAM frames for this clip")
    mannequins = [i for i, n in graph.items() if n["class_type"] == "H3GreyMannequins"]
    if len(mannequins) != 1:
        raise ValueError(f"Openjutsu graph: expected one mannequin node, found {len(mannequins)}")
    mannequin = mannequins[0]
    person = graph[mannequin]["inputs"]["mask"]
    graph["hair_text"] = {"class_type": "CLIPTextEncode", "inputs": {"text": "hair", "clip": [sam, 1]},
                          "_meta": {"title": "Bridge: SAM hair"}}
    graph["hair_area"] = {"class_type": "GrowMaskWithBlur", "inputs": {
        "expand": 20, "incremental_expandrate": 0, "tapered_corners": True, "flip_input": False, "blur_radius": 0,
        "lerp_alpha": 1, "decay_factor": 1, "fill_holes": True, "mask": person},
        "_meta": {"title": "Bridge: replaced person + 20 px"}}
    graph["hair_alone"] = {"class_type": "H3KeepMaskedArea", "inputs": {
        "images": [frames, 0], "mask": ["hair_area", 0], "grow_px": 24},
        "_meta": {"title": "Bridge: only the replaced person"}}
    graph["hair_detect"] = {"class_type": "SAM3_Detect", "inputs": {
        "model": [sam, 0], "image": ["hair_alone", 0], "conditioning": ["hair_text", 0], "threshold": 0.3,
        "refine_iterations": 2, "individual_masks": False}, "_meta": {"title": "Bridge: their hair (per frame)"}}
    graph["hair_mask"] = {"class_type": "H3MaskMultiply", "inputs": {"a": ["hair_detect", 0], "b": ["hair_area", 0]},
                          "_meta": {"title": "Bridge: only their hair"}}
    graph["hair_erased"] = {"class_type": "H3InpaintArea", "inputs": {
        "images": [mannequin, 0], "mask": ["hair_mask", 0], "grow_px": 6, "radius": 9},
        "_meta": {"title": "Bridge: erase their hair from the mannequin"}}
    for i, node in graph.items():
        if i == "hair_erased":
            continue
        for key, value in node["inputs"].items():
            if value == [mannequin, 0]:
                node["inputs"][key] = ["hair_erased", 0]


def build_graph(source: str, people: list[tuple[str, str]], seed: int, resolution: str, remove_hair: bool) -> dict:
    """The API graph for one swap job. `people`: (picture in ComfyUI's input folder, role) per character, Picture 1
    first. Final Video's MP4 is loaded and saved again, so the bridge files it."""
    if resolution not in RESOLUTIONS:
        raise ValueError("Openjutsu renders at 480p or 736p (the tested sizes)")
    if not 1 <= len(people) <= MAX_CHARACTERS:
        raise ValueError(f"Openjutsu swaps 1-{MAX_CHARACTERS} characters per render (the tested counts)")
    graph = json.loads(GRAPH_FILE.read_text(encoding="utf-8"))
    graph[by_title(graph, VIDEO)]["inputs"]["video"] = source
    for k, (picture, _role) in enumerate(people, 1):
        graph[by_title(graph, f"Picture {k}")]["inputs"]["image"] = picture
    graph = _prune(graph, resolution, [role for _picture, role in people], seed)
    if remove_hair:
        _remove_hair(graph)
    final = next(i for i, n in graph.items() if n["class_type"] == "MiniMaxH3ChainAssemble")
    graph["final_load"] = {"class_type": "VHS_LoadVideoPath", "inputs": {
        "video": [final, 0], "force_rate": 0, "custom_width": 0, "custom_height": 0, "frame_load_cap": 0,
        "skip_first_frames": 0, "select_every_nth": 1, "format": "AnimateDiff"}, "_meta": {"title": "Bridge: load Final Video"}}
    graph["final_video"] = {"class_type": "CreateVideo", "inputs": {"images": ["final_load", 0], "audio": ["final_load", 2],
                                                                    "fps": 24.0}}
    graph["final_save"] = {"class_type": "SaveVideo", "inputs": {
        "video": ["final_video", 0], "filename_prefix": "openjutsu", "format": "mp4", "format.codec": "h264",
        "format.codec.encoding": "re-encode", "format.codec.encoding.crf": 12.0}}
    for i, node in graph.items():
        for key, value in node["inputs"].items():
            if _link(value) and value[0] not in graph:
                raise ValueError(f"Openjutsu graph: {i}.{key} links to missing node {value[0]}")
    return graph


def role_text(description: str, who: str = "the person") -> str:
    """Openjutsu reads roles as "who - looks": only "who" reaches H3 (clothing words leak into the result), the looks
    help the describer pick the right track. The sheet's description becomes the looks; with several characters
    "who" says where each one is (as in the tested roles: "the boxer on the left - ...")."""
    return f"{who} - " + " ".join(description.split())


def positions(xs: list[float]) -> list[str]:
    """A distinct "who" per character from where they were tapped, left to right."""
    if len(xs) == 1:
        return ["the person"]
    names = (["the person on the left", "the person on the right"] if len(xs) == 2 else
             ["the person on the left", "the person in the middle", "the person on the right"])
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [""] * len(xs)
    for rank, i in enumerate(order):
        out[i] = names[rank]
    return out
