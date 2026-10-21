import re
from dataclasses import dataclass


MAX_PIXELS = 2_000_000


def parse_resolution(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)x(\d+)", value)
    if not match:
        raise ValueError("Resolution must use WIDTHxHEIGHT")
    width, height = (int(item) for item in match.groups())
    if not 256 <= width <= 2048 or not 256 <= height <= 2048:
        raise ValueError("Resolution dimensions must be between 256 and 2048")
    if width % 32 or height % 32:
        raise ValueError("Resolution dimensions must be multiples of 32")
    if width * height > MAX_PIXELS:
        raise ValueError("Resolution is above the 2.0 megapixel safety limit")
    return width, height

TURBO_STEP_RANGE = (4, 12)
STANDARD_STEP_RANGE = (8, 30)
SPECTRUM_STEP_RANGE = (8, 30)
FUSED_SLA_STEP_RANGE = (4, 8)
FUSED_WORKFLOW_VARIANTS = ("direct", "i2v_fl2v", "ref2va", "ref2va_multiref", "derope", "dyrope")
# Ref2VA exposes the same 4–8 step sampler control as Direct SLA. The other
# official auxiliary graphs remain fixed at four steps because their graph
# topology is tied to the corresponding adapter/recovery pass.
FUSED_FIXED_VARIANTS = {"i2v_fl2v", "derope", "dyrope"}
# Per-job attention speed-ups. "standard" leaves the workflow untouched.
# Turbo accepts every mode; Fused SLA already runs sparse attention, so it only
# adds Sage. Standard and Spectrum stay on standard attention.
ATTENTION_MODES = ("standard", "sage", "sla", "sage_sla")
ENGINE_ATTENTION_MODES = {
    "turbo": ATTENTION_MODES,
    "fused_sla": ("standard", "sage"),
    "standard": ("standard",),
    "spectrum": ("standard",),
    "ltx": ("standard",),
}
# LTX-2.5 distilled: one pass of the 8-step distilled schedule. Reference mode
# uses Lightricks' Ingredients IC-LoRA with one reference sheet image.
LTX_STEPS = 8
LTX_MODES = ("text", "opening", "closing", "frames", "lip_sync", "reference")
LTX_DURATION_RANGE = (1.0, 10.0)
# Reference mode keeps only what the speed lab proved: landscape 1536x896
# (768x448 sheet grid upscaled x2), clips up to 5 s, one recipe per model.
LTX_REFERENCE_MODELS = ("2.5", "2.3")
LTX_REFERENCE_SIZE = (1536, 896)
LTX_REFERENCE_MAX_DURATION = 5.0
# Opt-in fixes for the other LTX video modes (not lip-sync): a seam-free
# decode and the plain euler sampler. Both were proven on opening-frame clips
# in the lab, so they stay off unless the user turns them on.
LTX_OPTION_MODES = ("text", "opening", "closing", "frames")
# Full-resolution single-pass sizes per aspect. "balanced" matches the tested
# 896x1600 run; "high" is the tested 1088x1920 run trimmed to the app's
# 2.0 MP safety limit. Every side is a multiple of 32.
LTX_SIZES = {
    "balanced": {"9:16": (896, 1600), "16:9": (1600, 896), "1:1": (1216, 1216),
                 "4:3": (1376, 1024), "3:4": (1024, 1376)},
    "high": {"9:16": (1056, 1888), "16:9": (1888, 1056), "1:1": (1408, 1408),
             "4:3": (1632, 1216), "3:4": (1216, 1632)},
}


@dataclass(frozen=True)
class GenerationSettings:
    engine: str
    steps: int
    width: int
    height: int
    encoder: str = "native"
    turbo_profile: str = "v1"
    megapixels: float = 0.31
    aspect_ratio: str = "16:9"
    workflow_variant: str = "direct"
    attention_mode: str = "standard"
    ltx_reference_model: str | None = None
    ltx_sharp_decode: bool = False
    ltx_calm_sampler: bool = False


def normalize_generation_settings(
    mode: str,
    engine: str | None = None,
    steps: int | None = None,
    resolution: str | None = None,
    encoder: str | None = None,
    turbo_profile: str | None = None,
    megapixels: float | None = None,
    aspect_ratio: str | None = None,
    workflow_variant: str | None = None,
    attention_mode: str | None = None,
    ltx_quality: str | None = None,
    ltx_reference_model: str | None = None,
    ltx_sharp_decode: bool = False,
    ltx_calm_sampler: bool = False,
) -> GenerationSettings:
    resolved_engine = engine or ("standard" if mode in ("reference", "lip_sync") else "turbo")
    if resolved_engine not in ("turbo", "standard", "spectrum", "fused_sla", "ltx"):
        raise ValueError("Engine must be turbo, standard, spectrum, fused_sla or ltx")
    if resolved_engine == "ltx":
        return _normalize_ltx(mode, steps, encoder, turbo_profile, aspect_ratio,
                              workflow_variant, attention_mode, ltx_quality,
                              ltx_reference_model, ltx_sharp_decode, ltx_calm_sampler)
    if ltx_quality is not None:
        raise ValueError("LTX quality is only available with the ltx engine")
    if ltx_reference_model is not None or ltx_sharp_decode or ltx_calm_sampler:
        raise ValueError("LTX options are only available with the ltx engine")
    resolved_variant = workflow_variant or ("ref2va" if mode == "reference" and resolved_engine == "fused_sla" else "direct")
    if resolved_variant not in FUSED_WORKFLOW_VARIANTS:
        raise ValueError("Fused workflow must be direct, i2v_fl2v, ref2va, ref2va_multiref, derope or dyrope")
    if resolved_engine != "fused_sla" and resolved_variant != "direct":
        raise ValueError("Fused workflow variants require the Fused SLA engine")
    if resolved_engine == "fused_sla" and mode == "reference" and resolved_variant not in {"ref2va", "ref2va_multiref"}:
        raise ValueError("Fused reference mode requires the Ref2VA or Ref2VA Multi-reference workflow")
    if resolved_engine == "fused_sla" and resolved_variant in {"ref2va", "ref2va_multiref"} and mode != "reference":
        raise ValueError("The Fused Ref2VA workflows require Reference mode")
    if resolved_engine == "fused_sla" and resolved_variant == "i2v_fl2v" and mode not in {"opening", "closing", "frames"}:
        raise ValueError("The Fused I2V/FL2V workflow requires an image-to-video mode")
    if resolved_engine == "fused_sla" and resolved_variant in {"derope", "dyrope"} and mode not in {"text", "opening", "closing", "frames"}:
        raise ValueError("Fused de-rope workflows use text or image-to-video mode")
    if resolved_engine == "fused_sla" and mode == "lip_sync" and resolved_variant != "direct":
        raise ValueError("Fused lip-sync uses the Direct SLA workflow")
    if resolved_engine == "turbo":
        step_min, step_max, default_steps = (*TURBO_STEP_RANGE, 4)
    elif resolved_engine == "spectrum":
        step_min, step_max, default_steps = (*SPECTRUM_STEP_RANGE, 16)
    elif resolved_engine == "fused_sla":
        if resolved_variant in FUSED_FIXED_VARIANTS:
            step_min, step_max, default_steps = (4, 4, 4)
        else:
            step_min, step_max, default_steps = (*FUSED_SLA_STEP_RANGE, 4)
    else:
        step_min, step_max, default_steps = (*STANDARD_STEP_RANGE, 20)
    resolved_steps = default_steps if steps is None else steps
    if isinstance(resolved_steps, bool) or not isinstance(resolved_steps, int):
        raise ValueError("Steps must be a whole number")
    if not step_min <= resolved_steps <= step_max:
        raise ValueError(f"{resolved_engine.capitalize()} steps must be between {step_min} and {step_max}")

    resolved_aspect = aspect_ratio or "16:9"
    if resolved_aspect not in {"1:1", "16:9", "9:16", "4:3", "3:4"}:
        raise ValueError("Aspect ratio must be one of 1:1, 16:9, 9:16, 4:3 or 3:4")
    if megapixels is None:
        resolved_resolution = resolution or "736x416"
        width, height = parse_resolution(resolved_resolution)
        resolved_megapixels = 0.31
    else:
        try:
            resolved_megapixels = float(megapixels)
        except (TypeError, ValueError):
            raise ValueError("Megapixels must be a number") from None
        if not 0.1 <= resolved_megapixels <= 2.0:
            raise ValueError("Megapixels must be between 0.1 and 2.0")
        # Compatibility metadata only. The workflow passes megapixels and
        # aspect_ratio to ResolutionSelector, which owns final dimensions.
        ratios = {"1:1": 1.0, "16:9": 16 / 9, "9:16": 9 / 16, "4:3": 4 / 3, "3:4": 3 / 4}
        ratio = ratios[resolved_aspect]
        width = max(256, round((resolved_megapixels * 1_000_000 * ratio) ** 0.5 / 32) * 32)
        height = max(256, round((resolved_megapixels * 1_000_000 / ratio) ** 0.5 / 32) * 32)
        if width * height > MAX_PIXELS:
            raise ValueError("Megapixels produce a resolution above the 2.0 megapixel safety limit")
    resolved_encoder = encoder or "native"
    if resolved_encoder not in ("native", "clipproj"):
        raise ValueError("Text encoder must be native or clipproj")
    if mode == "lip_sync" and resolved_engine not in ("standard", "turbo", "fused_sla"):
        raise ValueError("Lip-sync supports the Standard, Turbo or Fused SLA engine")
    if resolved_engine == "fused_sla" and resolved_encoder != "native":
        raise ValueError("H3 Fused SLA uses the native 32B text encoder")
    if mode == "lip_sync" and resolved_encoder != "native":
        raise ValueError("Lip-sync uses the native 32B encoder")
    resolved_turbo_profile = turbo_profile or "v1"
    if resolved_turbo_profile not in ("v1", "v4"):
        raise ValueError("Turbo profile must be v1 or v4")
    if resolved_engine != "turbo" and turbo_profile not in (None, "v1"):
        raise ValueError("Turbo profile is only available with the turbo engine")
    if resolved_engine == "turbo" and resolved_turbo_profile == "v4" and resolved_steps > 8:
        raise ValueError("Turbo v4 supports 4 to 8 useful steps")
    if mode == "reference" and resolved_engine == "turbo" and not 4 <= resolved_steps <= 8:
        raise ValueError("Ref2VA Turbo steps must be between 4 and 8")
    if resolved_engine != "turbo":
        resolved_turbo_profile = "v1"
    resolved_attention = attention_mode or "standard"
    if resolved_attention not in ATTENTION_MODES:
        raise ValueError("Attention mode must be standard, sage, sla or sage_sla")
    if resolved_attention not in ENGINE_ATTENTION_MODES[resolved_engine]:
        allowed = ", ".join(ENGINE_ATTENTION_MODES[resolved_engine])
        raise ValueError(f"The {resolved_engine} engine supports attention modes: {allowed}")
    return GenerationSettings(
        resolved_engine, resolved_steps, width, height,
        resolved_encoder, resolved_turbo_profile, resolved_megapixels, resolved_aspect,
        resolved_variant, resolved_attention,
    )


def ltx_quality_for_size(width: int, height: int) -> str:
    """Recover the LTX quality preset from a stored job size."""
    for quality, sizes in LTX_SIZES.items():
        if (width, height) in sizes.values():
            return quality
    return "balanced"


def _normalize_ltx(mode, steps, encoder, turbo_profile, aspect_ratio,
                   workflow_variant, attention_mode, ltx_quality,
                   reference_model=None, sharp_decode=False, calm_sampler=False) -> GenerationSettings:
    if mode not in LTX_MODES:
        raise ValueError("Unsupported mode for LTX 2.5")
    if steps not in (None, LTX_STEPS):
        raise ValueError(f"LTX 2.5 uses the fixed {LTX_STEPS}-step distilled schedule")
    if (encoder or "native") != "native":
        raise ValueError("LTX 2.5 uses its own Gemma text encoder")
    if turbo_profile not in (None, "v1"):
        raise ValueError("Turbo profile is only available with the turbo engine")
    if (workflow_variant or "direct") != "direct":
        raise ValueError("Fused workflow variants require the Fused SLA engine")
    if (attention_mode or "standard") != "standard":
        raise ValueError("The ltx engine supports attention modes: standard")
    quality = ltx_quality or "balanced"
    if quality not in LTX_SIZES:
        raise ValueError("LTX quality must be balanced or high")
    if mode != "reference" and reference_model is not None:
        raise ValueError("The LTX reference model is only used in reference mode")
    if (sharp_decode or calm_sampler) and mode not in LTX_OPTION_MODES:
        raise ValueError("Sharp decode and calm sampler apply to LTX text and image-to-video modes only")
    if mode == "reference":
        model = reference_model or "2.5"
        if model not in LTX_REFERENCE_MODELS:
            raise ValueError("LTX reference model must be 2.5 or 2.3")
        aspect = aspect_ratio or "16:9"
        if aspect != "16:9":
            raise ValueError("LTX reference mode is landscape only (16:9)")
        width, height = LTX_REFERENCE_SIZE
        return GenerationSettings(
            "ltx", LTX_STEPS, width, height, "native", "v1",
            round(width * height / 1_000_000, 2), aspect, "direct", "standard", model,
        )
    aspect = aspect_ratio or "9:16"
    if aspect not in LTX_SIZES[quality]:
        raise ValueError("Aspect ratio must be one of 1:1, 16:9, 9:16, 4:3 or 3:4")
    width, height = LTX_SIZES[quality][aspect]
    return GenerationSettings(
        "ltx", LTX_STEPS, width, height, "native", "v1",
        round(width * height / 1_000_000, 2), aspect, "direct", "standard",
        None, bool(sharp_decode), bool(calm_sampler),
    )
