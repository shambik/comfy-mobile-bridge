from __future__ import annotations

import shutil
from typing import Any

from ..agents import model_catalog
from .contracts import (COUNCIL_REQUIRED_ROLE_IDS, CapabilityEvidence, CouncilConfig, CouncilValidation,
                        VerifiedSeat, roles_by_id,
                        validate_role_ids)


# Conservative adapter truth. Codex CLI accepts text and image inputs in this
# bridge; AGY is the media-analysis runtime. Do not infer audio/video support
# from a model name or a client checkbox.
RUNTIME_BASELINE = {
    "codex": {"text", "image"},
    "agy": {"text", "image", "audio", "video"},
}
RUNTIME_COMMAND = {"codex": "codex", "agy": "agy"}


def _catalog_entry(catalog: dict[str, Any], runtime: str, model: str) -> dict[str, Any] | None:
    return next((item for item in catalog.get(runtime, []) if str(item.get("id")) == model), None)


def verify_council_config(config: CouncilConfig, *, catalog: dict[str, Any] | None = None) -> CouncilValidation:
    validate_role_ids(config)
    catalog = catalog or model_catalog()
    roles = roles_by_id()
    verified_seats: list[VerifiedSeat] = []
    capability_gaps: list[dict[str, Any]] = []
    assigned_roles: set[str] = set()

    for seat in config.seats:
        assigned_roles.update(seat.role_ids if seat.active else [])
        executable = shutil.which(RUNTIME_COMMAND[seat.runtime])
        model = _catalog_entry(catalog, seat.runtime, seat.model)
        effort_ok = bool(model and seat.effort in (model.get("efforts") or []))
        runtime_ready = bool(executable and model and effort_ok)
        enabled = set(seat.user_enabled_capabilities or RUNTIME_BASELINE[seat.runtime])
        effective = sorted(RUNTIME_BASELINE[seat.runtime] & enabled) if runtime_ready and seat.active else []
        evidence = [
            CapabilityEvidence(
                capability=capability,
                state="verified" if capability in effective else "unsupported",
                source=f"{seat.runtime}-adapter",
                detail=("CLI installed, model discovered, and effort supported" if capability in effective else
                        "Disabled, unsupported by the adapter, or runtime/model unavailable"),
            )
            for capability in sorted(RUNTIME_BASELINE[seat.runtime] | enabled)
        ]
        if not executable:
            capability_gaps.append({"seat_id": seat.id, "reason": f"{seat.runtime} CLI is not installed"})
        elif not model:
            capability_gaps.append({"seat_id": seat.id, "reason": f"Model {seat.model} is not in the live {seat.runtime} catalog"})
        elif not effort_ok:
            capability_gaps.append({"seat_id": seat.id, "reason": f"Effort {seat.effort} is unsupported by {seat.model}"})
        for role_id in seat.role_ids:
            missing = sorted(set(roles[role_id].get("required_capabilities", [])) - set(effective))
            if missing:
                capability_gaps.append({"seat_id": seat.id, "role_id": role_id, "missing_capabilities": missing})
        verified_seats.append(VerifiedSeat(seat=seat, effective_capabilities=effective, evidence=evidence))

    # Required pipeline coverage is server-owned. A client may require extra
    # roles, but it cannot make the planning graph runnable by omitting one.
    required = set(COUNCIL_REQUIRED_ROLE_IDS) | set(config.required_role_ids)
    missing_roles = sorted(required - assigned_roles)
    warnings: list[str] = []
    if config.mode == "solo" and config.self_review_policy == "allow":
        warnings.append("Solo review is self-review and is not independent consensus")
    return CouncilValidation(
        valid=not missing_roles and not capability_gaps,
        seats=verified_seats,
        missing_roles=missing_roles,
        capability_gaps=capability_gaps,
        warnings=warnings,
    )
