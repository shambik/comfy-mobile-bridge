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
    width, height = parse_resolution(resolved_resolution)
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
    if mode == "reference" and resolved_engine == "turbo" and resolved_steps != 4:
        raise ValueError("Ref2VA Turbo uses exactly 4 steps")
    if resolved_engine != "turbo":
        resolved_turbo_profile = "v1"
    return GenerationSettings(
        resolved_engine, resolved_steps, width, height,
        resolved_encoder, resolved_turbo_profile,
    )
