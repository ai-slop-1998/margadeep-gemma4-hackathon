"""Typed request and response models for stateless online support."""
from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Surface(str, Enum):
    live = "live"
    recover = "recover"
    test = "test"


class TriggerSource(str, Enum):
    manual_support = "manual_support"
    gate_trigger = "gate_trigger"
    child_trigger = "child_trigger"
    caregiver_trigger = "caregiver_trigger"
    outcome_check = "outcome_check"


class GateState(str, Enum):
    ok = "ok"
    elevated = "elevated"
    trigger = "trigger"
    missing = "missing"


class Severity(str, Enum):
    mild = "mild"
    bad = "bad"
    danger = "danger"


class ActionType(str, Enum):
    support_card = "support_card"
    location_change = "location_change"
    caregiver_alert = "caregiver_alert"


class CardVariant(str, Enum):
    sensory_tool = "sensory_tool"
    coping_support = "coping_support"
    location_change = "location_change"
    caregiver_alert = "caregiver_alert"
    recovery_check = "recovery_check"


class GateSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    gate_name: str = ""
    state: GateState = GateState.missing
    score: float = 0.0
    reasons: list[str] = Field(default_factory=list)
    features: dict[str, Any] = Field(default_factory=dict)
    timestamp: str | None = None

    @field_validator("score", mode="before")
    @classmethod
    def clamp_score(cls, value: Any) -> float:
        if value is None:
            return 0.0
        return max(0.0, min(float(value), 1.0))


class LocationContext(BaseModel):
    model_config = ConfigDict(extra="allow")

    label: str | None = None
    source: str | None = None
    service_enabled: bool | None = None
    permission_status: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    accuracy_m: float | None = None
    timestamp: str | None = None

    @property
    def has_coordinates(self) -> bool:
        return self.latitude is not None and self.longitude is not None


class CalmingPlaceRequest(BaseModel):
    requested: bool = False
    radius_m: int = Field(default=700, ge=50, le=1500)
    max_results: int = Field(default=3, ge=1, le=10)
    sensory_need: str = "quiet"


class OutcomeContext(BaseModel):
    card_id: str
    action_type: ActionType
    card_variant: CardVariant
    baseline: dict[str, Any] = Field(default_factory=dict)
    support_card_snapshot: dict[str, Any] = Field(default_factory=dict)


class OnlineDecisionRequest(BaseModel):
    profile_id: str
    surface: Surface = Surface.live
    caregiver_note: str = ""
    trigger_source: TriggerSource
    audio_gate: GateSummary | None = None
    visual_gate: GateSummary | None = None
    sensory_gate: GateSummary | None = None
    location: LocationContext | None = None
    calming_place_request: CalmingPlaceRequest = Field(
        default_factory=CalmingPlaceRequest
    )
    outcome_context: OutcomeContext | None = None

    @model_validator(mode="before")
    @classmethod
    def default_nested_nulls(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if normalized.get("calming_place_request") is None:
            normalized["calming_place_request"] = {}
        return normalized


class DecisionSummary(BaseModel):
    severity: Severity
    action_type: ActionType
    reason: str = ""


class OnlineSupportCard(BaseModel):
    card_id: str = Field(default_factory=lambda: f"online-card-{uuid4().hex}")
    variant: CardVariant
    title: str
    primary_message: str
    steps: list[str] = Field(default_factory=list, max_length=3)
    visual: dict[str, Any] = Field(default_factory=dict)
    location: dict[str, Any] = Field(default_factory=dict)
    caregiver_alert: dict[str, Any] = Field(default_factory=dict)
    caregiver_note: str = ""
    why_this: str = ""
    actions: list[dict[str, str]] = Field(default_factory=list)
    measure_outcome: dict[str, Any] = Field(default_factory=dict)

    @field_validator("steps")
    @classmethod
    def require_steps(cls, value: list[str]) -> list[str]:
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return cleaned[:3] or ["Take one small step"]


class MeasurementRequest(BaseModel):
    send_after_seconds: int = 120
    card_id: str
    action_type: ActionType
    card_variant: CardVariant
    baseline: dict[str, Any]
    support_card_snapshot: dict[str, Any] = Field(default_factory=dict)


class EvidenceSummary(BaseModel):
    profile_used: bool = False
    past_experience_used: bool = False
    kg_memory_used: bool = False
    calming_place_used: bool = False
    summary: str = ""


class MemoryUpdateStatus(BaseModel):
    attempted: bool = False
    stored: bool = False
    autoschema_requested: bool = False
    autoschema_used: bool = False
    outcome_direction: str = ""
    event_id: str | None = None
    graph_node_count: int | None = None
    graph_edge_count: int | None = None
    graphml_path: str | None = None
    autoschema_graphml_path: str | None = None
    message: str = ""
    error: str | None = None


class OnlineSupportSystemTrace(BaseModel):
    memory_update: MemoryUpdateStatus | None = None


class OnlineSupportDecision(BaseModel):
    decision: DecisionSummary
    card: OnlineSupportCard
    measurement_request: MeasurementRequest | None = None
    evidence: EvidenceSummary = Field(default_factory=EvidenceSummary)
    system: OnlineSupportSystemTrace = Field(default_factory=OnlineSupportSystemTrace)
