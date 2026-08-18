"""Portable local configuration for the H3 bridge.

The repository contains only safe defaults.  A user's ignored
``config.local.json`` may point at another local runtime during migration.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_config_override = os.environ.get("H3_CONFIG_PATH")
CONFIG_PATH = Path(_config_override) if _config_override else ROOT / "config.local.json"
if not CONFIG_PATH.is_absolute():
    CONFIG_PATH = (ROOT / CONFIG_PATH).resolve()
APP_VERSION = "0.1.0"


def _read_local_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid local configuration: {CONFIG_PATH}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Local configuration must contain a JSON object")
    return payload


LOCAL_CONFIG = _read_local_config()


def _as_path(value: str | None, default: Path, *, relative_to: Path = ROOT) -> Path:
    if not value:
        return default.resolve()
    path = Path(value)
    if not path.is_absolute():
        path = relative_to / path
    return path.resolve()


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _local_host(value: Any, name: str) -> str:
    host = str(value)
    # The bridge may bind on all interfaces so a phone can reach it over
    # Tailscale/LAN. ComfyUI itself remains loopback-only.
    if name == "app.host" and host == "0.0.0.0":
        return host
    if host != "127.0.0.1":
        raise RuntimeError(f"{name} must be 127.0.0.1 (or app.host may be 0.0.0.0)")
    return host


def _port(value: Any, default: int, name: str) -> int:
    port = _as_int(value, default)
    if not 1 <= port <= 65535:
        raise RuntimeError(f"{name} must be between 1 and 65535")
    return port


runtime_value = LOCAL_CONFIG.get("runtime_root", ".runtime")
RUNTIME_ROOT = _as_path(str(runtime_value), ROOT / ".runtime")
profile = str(LOCAL_CONFIG.get("profile", "full")).lower()
PROFILE = profile if profile in {"full"} else "full"

app_config = LOCAL_CONFIG.get("app", {})
comfy_config = LOCAL_CONFIG.get("comfy", {})
tailscale_config = LOCAL_CONFIG.get("tailscale", {})
if not isinstance(app_config, dict) or not isinstance(comfy_config, dict) or not isinstance(tailscale_config, dict):
    raise RuntimeError("app, comfy, and tailscale configuration sections must be objects")

APP_HOST = _local_host(os.environ.get("H3_APP_HOST", app_config.get("host", "127.0.0.1")), "app.host")
APP_PORT = _port(os.environ.get("H3_APP_PORT", app_config.get("port")), 8787, "app.port")
COMFY_HOST = _local_host(os.environ.get("H3_COMFY_HOST", comfy_config.get("host", "127.0.0.1")), "comfy.host")
COMFY_PORT = _port(os.environ.get("H3_COMFY_PORT", comfy_config.get("port")), 8190, "comfy.port")
COMFY_URL = f"http://{COMFY_HOST}:{COMFY_PORT}"

STATE = ROOT / "state"
LOGS = STATE / "logs"
SEQUENCES = STATE / "sequences"
PRODUCTIONS = STATE / "productions"
PROJECTS = _as_path(LOCAL_CONFIG.get("projects_dir"), STATE / "projects")
MANAGED_SKILLS = STATE / "skills"
DB_PATH = STATE / "jobs.sqlite3"
REFERENCE_10S_MARKER = STATE / "reference-10s-verified"

# The optional explicit paths make it possible to adopt an existing local
# install without copying 65+ GB before the new runtime is ready.  Bootstrap
# creates the portable layout when these overrides are not present.
COMFY_CODE = _as_path(
    comfy_config.get("root"), RUNTIME_ROOT / "comfyui", relative_to=RUNTIME_ROOT
)
COMFY_PYTHON = _as_path(
    comfy_config.get("python"), RUNTIME_ROOT / "python" / "Scripts" / "python.exe", relative_to=RUNTIME_ROOT
)
MODELS = _as_path(
    comfy_config.get("models"), RUNTIME_ROOT / "models", relative_to=RUNTIME_ROOT
)
# Use the existing ComfyUI runtime directories by default.  The bridge keeps
# its own database/log/sequence state above, while ComfyUI shares the same
# user, input, output, and temp locations as a direct ComfyUI launch.
INPUT = _as_path(comfy_config.get("input"), COMFY_CODE / "input", relative_to=COMFY_CODE)
OUTPUT = _as_path(comfy_config.get("output"), COMFY_CODE / "output", relative_to=COMFY_CODE)
TEMP = _as_path(comfy_config.get("temp"), COMFY_CODE / "temp", relative_to=COMFY_CODE)
USER = _as_path(comfy_config.get("user"), COMFY_CODE / "user", relative_to=COMFY_CODE)
SPECTRUM_NODE_DIR = COMFY_CODE / "custom_nodes" / "ComfyUI-Spectrum-MiniMax-H3"
CLIPPROJ_NODE_DIR = COMFY_CODE / "custom_nodes" / "ComfyUI-ClipProj"
AUDIOLOCK_NODE_DIR = COMFY_CODE / "custom_nodes" / "ComfyUI-H3-NativeAudioLock"
CLIPPROJ_NODE_COMMIT = "ca9b325e83cb02cb5e652570569c6f3f20fee342"
SPECTRUM_NODE_VERSION = "v0.2.5"
TURBO_LORAS = {
    "v1": "minimax_h3_turbo_4step_ema_ckpt850.safetensors",
    "v4": "minimax_h3_turbo_v4_step600_ema.safetensors",
}
REF2VA_TURBO_LORA = "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"
TURBO_LORA = TURBO_LORAS["v1"]
FL2VA_MODEL = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
REF2VA_MODEL = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
TEXT_ENCODER = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
CLIPPROJ_TEXT_ENCODER = "qwen3vl_4b_fp8_scaled.safetensors"
CLIPPROJ_PROJECTION = "h3_qwen3vl_4b_tap24.safetensors"
VIDEO_VAE = "minimax_h3_video_vae_fp16.safetensors"
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"

TAILSCALE_ENABLED = bool(tailscale_config.get("enabled", True))
TAILSCALE_SCOPE = str(tailscale_config.get("scope", "tailnet"))
TAILSCALE_HOSTNAME = str(tailscale_config.get("hostname") or "").strip()
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]
if TAILSCALE_HOSTNAME and TAILSCALE_HOSTNAME not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(TAILSCALE_HOSTNAME)

WORKSPACE = ROOT

agents_config = LOCAL_CONFIG.get("agents", {})
if not isinstance(agents_config, dict):
    raise RuntimeError("agents configuration must be an object")
CODEX_COMMAND = str(agents_config.get("codex_command") or "codex").strip()
AGY_COMMAND = str(agents_config.get("agy_command") or "agy").strip()
AGENT_TIMEOUT_SECONDS = max(30, _as_int(agents_config.get("timeout_seconds"), 600))
PRODUCTION_CONCURRENCY = max(1, min(8, _as_int(agents_config.get("production_concurrency"), 3)))
CODEX_DEFAULT_RUNTIME = str(agents_config.get("codex_runtime") or "codex").strip()
CODEX_DEFAULT_MODEL = str(agents_config.get("codex_model") or "gpt-5.6-sol").strip()
CODEX_DEFAULT_EFFORT = str(agents_config.get("codex_effort") or "high").strip()
AGY_DEFAULT_RUNTIME = str(agents_config.get("agy_runtime") or "agy").strip()
AGY_DEFAULT_MODEL = str(agents_config.get("agy_model") or "gemini-3.1-pro-high").strip()
AGY_DEFAULT_EFFORT = str(agents_config.get("agy_effort") or "high").strip()

for path in (STATE, INPUT, OUTPUT, TEMP, USER, LOGS, SEQUENCES, PRODUCTIONS, PROJECTS, MANAGED_SKILLS):
    path.mkdir(parents=True, exist_ok=True)
