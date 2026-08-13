from dataclasses import dataclass


RESOLUTION_PRESETS = {
    "512x288": (512, 288),
    "736x416": (736, 416),
    "864x480": (864, 480),
}

TURBO_STEP_RANGE = (4, 12)
STANDARD_STEP_RANGE = (8, 30)
SPECTRUM_STEP_RANGE = (8, 30)


@dataclass(frozen=True)
class GenerationSettings:
    engine: str
    steps: int
    width: int
    height: int
    encoder: str = "native"
    turbo_profile: str = "v1"


def normalize_generation_settings(
    mode: str,
    engine: str | None = None,
    steps: int | None = None,
    resolution: str | None = None,
    encoder: str | None = None,
    turbo_profile: str | None = None,
) -> GenerationSettings:
    resolved_engine = engine or ("standard" if mode == "reference" else "turbo")
    if resolved_engine not in ("turbo", "standard", "spectrum"):
        raise ValueError("Engine must be turbo, standard or spectrum")
    if mode == "reference" and resolved_engine == "turbo":
        raise ValueError("Reference mode is available with the standard or spectrum engine only")

    if resolved_engine == "turbo":
        step_min, step_max, default_steps = (*TURBO_STEP_RANGE, 4)
    elif resolved_engine == "spectrum":
        step_min, step_max, default_steps = (*SPECTRUM_STEP_RANGE, 16)
    else:
        step_min, step_max, default_steps = (*STANDARD_STEP_RANGE, 20)
    resolved_steps = default_steps if steps is None else steps
    if isinstance(resolved_steps, bool) or not isinstance(resolved_steps, int):
        raise ValueError("Steps must be a whole number")
    if not step_min <= resolved_steps <= step_max:
        raise ValueError(f"{resolved_engine.capitalize()} steps must be between {step_min} and {step_max}")

    resolved_resolution = resolution or "736x416"
    if resolved_resolution not in RESOLUTION_PRESETS:
        raise ValueError("Resolution must be 512x288, 736x416 or 864x480")
    width, height = RESOLUTION_PRESETS[resolved_resolution]
    resolved_encoder = encoder or "native"
    if resolved_encoder not in ("native", "clipproj"):
        raise ValueError("Text encoder must be native or clipproj")
    resolved_turbo_profile = turbo_profile or "v1"
    if resolved_turbo_profile not in ("v1", "v4"):
        raise ValueError("Turbo profile must be v1 or v4")
    if resolved_engine != "turbo" and turbo_profile not in (None, "v1"):
        raise ValueError("Turbo profile is only available with the turbo engine")
    if resolved_engine == "turbo" and resolved_turbo_profile == "v4" and resolved_steps > 8:
        raise ValueError("Turbo v4 supports 4 to 8 useful steps")
    if resolved_engine != "turbo":
        resolved_turbo_profile = "v1"
    return GenerationSettings(
        resolved_engine, resolved_steps, width, height,
        resolved_encoder, resolved_turbo_profile,
    )
