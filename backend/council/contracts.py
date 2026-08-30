from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..config import ROOT


ROLE_MANIFEST = ROOT / "skills" / "council-roles" / "manifest.json"
CapabilityState = Literal["verified", "stale", "unsupported", "unknown"]
PLANNING_REQUIRED_ROLE_IDS = (
    "audio-analyst", "visual-director", "storyboard-editor", "technical-director",
)
EXECUTION_REQUIRED_ROLE_IDS = (
    "scene-frame-designer", "prompt-engineer", "technical-qc", "av-sync-reviewer",
    "post-production-editor",
)
COUNCIL_REQUIRED_ROLE_IDS = PLANNING_REQUIRED_ROLE_IDS + EXECUTION_REQUIRED_ROLE_IDS


class SeatConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    label: str = Field(min_length=1, max_length=120)
    runtime: Literal["codex", "agy"]
    model: str = Field(min_length=1, max_length=160)
    effort: str = Field(min_length=1, max_length=32)
    role_ids: list[str] = Field(min_length=1)
    user_enabled_capabilities: list[str] = Field(default_factory=list)
    priority: int = Field(default=100, ge=0, le=10_000)
    active: bool = True
    custom_instructions: str = Field(default="", max_length=20_000)

    @field_validator("role_ids", "user_enabled_capabilities")
    @classmethod
    def unique_values(cls, value: list[str]) -> list[str]:
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("Values must not contain duplicates")
        return cleaned


class CouncilConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["solo", "multi"] = "multi"
    seats: list[SeatConfig] = Field(min_length=1, max_length=8)
    self_review_policy: Literal["allow", "require_user", "skip_optional"] = "require_user"
    required_role_ids: list[str] = Field(default_factory=list)
    revision_budget: int = Field(default=2, ge=0, le=10)

    @model_validator(mode="after")
    def validate_mode(self) -> "CouncilConfig":
        ids = [seat.id for seat in self.seats]
        if len(ids) != len(set(ids)):
            raise ValueError("Seat IDs must be unique")
        if self.mode == "solo" and len(self.seats) != 1:
            raise ValueError("Solo mode requires exactly one seat")
        if self.mode == "multi" and len(self.seats) < 2:
            raise ValueError("Multi-agent mode requires at least two seats")
        return self


class CapabilityEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: str
    state: CapabilityState
    source: str
    detail: str = ""


class VerifiedSeat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seat: SeatConfig
    effective_capabilities: list[str]
    evidence: list[CapabilityEvidence]


class CouncilValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    seats: list[VerifiedSeat]
    missing_roles: list[str] = Field(default_factory=list)
    capability_gaps: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CouncilEnvelope(BaseModel):
    """Canonical server-validated result for every Council role turn."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=20_000)
    decision: Literal["approve", "approve_with_notes", "revise", "escalate"]
    content: Any
    issues: list[dict[str, Any]] = Field(default_factory=list)
    next_action: str = Field(default="", max_length=20_000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    requires_user: bool = False

    @field_validator("decision", mode="before")
    @classmethod
    def normalize_decision(cls, value: Any) -> str:
        normalized = str(value or "").strip().lower().replace(" ", "_")
        aliases = {"approved": "approve", "approved_with_notes": "approve_with_notes", "regenerate": "revise"}
        return aliases.get(normalized, normalized)


@lru_cache(maxsize=1)
def role_manifest() -> dict[str, Any]:
    payload = json.loads(ROLE_MANIFEST.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "council-role-manifest.v1":
        raise RuntimeError("Unsupported council role manifest")
    roles = payload.get("roles")
    if not isinstance(roles, list) or not roles:
        raise RuntimeError("Council role manifest has no roles")
    return payload


def roles_by_id() -> dict[str, dict[str, Any]]:
    return {str(item["id"]): item for item in role_manifest()["roles"]}


def validate_role_ids(config: CouncilConfig) -> None:
    available = roles_by_id()
    unknown = sorted({role for seat in config.seats for role in seat.role_ids if role not in available})
    unknown.extend(role for role in config.required_role_ids if role not in available and role not in unknown)
    if unknown:
        raise ValueError(f"Unknown council roles: {', '.join(unknown)}")


def positive_generation_duration(value: Any) -> int:
    """Reject fractional generation durations instead of silently rounding."""
    if isinstance(value, bool):
        raise ValueError("Generation duration must be a positive whole number of seconds")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Generation duration must be a positive whole number of seconds") from exc
    if numeric <= 0 or not numeric.is_integer():
        raise ValueError("Generation duration must be a positive whole number of seconds")
    return int(numeric)


def load_role_skill(role_id: str) -> str:
    """Load a role skill body for compatibility with older callers.

    Runtime Council prompts use ``role_skill_path`` so the native project
    skill is read by the agent instead of being pasted into every turn.
    """
    return role_skill_path(role_id).read_text(encoding="utf-8")


def role_skill_path(role_id: str) -> Path:
    """Return the project-native role skill path with a safe fallback."""
    role = roles_by_id().get(role_id)
    if not role:
        raise KeyError(role_id)
    native = (ROOT / ".agents" / "skills" / role_id / "SKILL.md").resolve()
    if native.is_file():
        return native
    path = (ROLE_MANIFEST.parent / str(role["skill_path"])).resolve()
    if ROLE_MANIFEST.parent.resolve() not in path.parents or not path.is_file():
        raise RuntimeError("Council role skill escapes its package")
    return path
