"""Safe stateless service wrapper around the online-support ADK agent."""
from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import uuid4

from google.adk.runners import InMemoryRunner
from google.genai import types

from app.agents.online_support.agent import build_online_support_agent
from app.agents.online_support.config import config
from app.agents.online_support.models import (
    ActionType,
    CardVariant,
    DecisionSummary,
    EvidenceSummary,
    GateState,
    GateSummary,
    MeasurementRequest,
    MemoryUpdateStatus,
    OnlineDecisionRequest,
    OnlineSupportCard,
    OnlineSupportDecision,
    Severity,
    TriggerSource,
)
from app.mcp_server.src.tool_adapters.calming_place_lookup import (
    calming_place_lookup,
)
from app.mcp_server.src.tool_adapters.insert_experience_event import (
    insert_experience_event,
)

APP_NAME = "online_support"


async def decide_online_support(
    request: OnlineDecisionRequest,
) -> OnlineSupportDecision:
    """Return one online-support card or route an outcome packet to memory."""
    if request.trigger_source == TriggerSource.outcome_check:
        return await _handle_outcome_check(request)

    severity_hint = _severity_hint(request)
    if not config.use_model:
        decision = _fallback_decision(request, severity_hint)
    else:
        try:
            decision = await asyncio.wait_for(
                _run_adk_agent(request, severity_hint),
                timeout=config.timeout_s,
            )
        except Exception as exc:
            decision = _fallback_decision(
                request,
                severity_hint,
                fallback_summary=(
                    "Model path failed; deterministic fallback used. "
                    f"{type(exc).__name__}: {str(exc)[:180]}"
                ),
            )

    decision = _apply_guardrails(request, severity_hint, decision)
    decision = await _enrich_location_change_card(request, decision)
    decision.measurement_request = _measurement_request(request, decision)
    return decision


async def _run_adk_agent(
    request: OnlineDecisionRequest,
    severity_hint: Severity,
) -> OnlineSupportDecision:
    runner = InMemoryRunner(agent=build_online_support_agent(), app_name=APP_NAME)
    session_id = f"online-{uuid4().hex}"

    await runner.session_service.create_session(
        app_name=APP_NAME,
        user_id=config.default_user_id,
        session_id=session_id,
        state={
            "online_request": request.model_dump(mode="json"),
            "severity_hint": severity_hint.value,
        },
    )

    prompt = {
        "task": "Choose exactly one online support card.",
        "severity_hint": severity_hint.value,
        "request": request.model_dump(mode="json"),
    }
    final_text = ""
    async for event in runner.run_async(
        user_id=config.default_user_id,
        session_id=session_id,
        new_message=types.Content(
            role="user",
            parts=[types.Part(text=json.dumps(prompt, ensure_ascii=True))],
        ),
    ):
        final_text = _event_text(event) or final_text

    session = await runner.session_service.get_session(
        app_name=APP_NAME,
        user_id=config.default_user_id,
        session_id=session_id,
    )
    state = session.state or {}
    payload = state.get("online_support_decision")
    if payload is not None:
        return _coerce_decision(payload)
    if final_text:
        return _coerce_decision(final_text)
    raise ValueError("Online support agent did not return a decision")


async def _handle_outcome_check(
    request: OnlineDecisionRequest,
) -> OnlineSupportDecision:
    if request.outcome_context is None:
        memory_update = MemoryUpdateStatus(
            attempted=False,
            stored=False,
            autoschema_requested=config.outcome_run_autoschema,
            message="Outcome context was missing.",
        )
        return _outcome_ack_card(
            title="Could not save yet",
            message="I need the earlier card baseline to remember this.",
            stored=False,
            evidence="Outcome context was missing.",
            memory_update=memory_update,
        )

    direction = _outcome_direction(request)
    event = _experience_event_from_outcome(request, direction)
    stored = False
    error_summary = ""
    autoschema_summary = ""
    memory_update = MemoryUpdateStatus(
        attempted=True,
        stored=False,
        autoschema_requested=config.outcome_run_autoschema,
        outcome_direction=direction,
        message="Outcome memory update was attempted.",
    )
    try:
        result = await insert_experience_event(
            profile_id=request.profile_id,
            event=event,
            correlation_id=f"online-outcome-{uuid4().hex}",
            run_autoschema=config.outcome_run_autoschema,
        )
        stored = bool(result.get("success"))
        graph = result.get("graph") or {}
        event_payload = result.get("event") or {}
        autoschema = graph.get("autoschema") or {}
        if autoschema:
            autoschema_summary = (
                " AutoSchemaKG used."
                if autoschema.get("used")
                else f" AutoSchemaKG not used: {autoschema.get('message', 'unknown reason')}"
            )
        memory_update = MemoryUpdateStatus(
            attempted=True,
            stored=stored,
            autoschema_requested=config.outcome_run_autoschema,
            autoschema_used=bool(autoschema.get("used")),
            outcome_direction=direction,
            event_id=str(event_payload.get("event_id") or "") or None,
            graph_node_count=_optional_int(graph.get("node_count")),
            graph_edge_count=_optional_int(graph.get("edge_count")),
            graphml_path=str(graph.get("graphml_path") or "") or None,
            autoschema_graphml_path=str(autoschema.get("graphml_path") or "") or None,
            message=(
                "Outcome stored and AutoSchemaKG merged."
                if stored and autoschema.get("used")
                else autoschema.get("message")
                or ("Outcome stored." if stored else "Outcome memory update failed.")
            ),
        )
        if not stored:
            error_summary = str(result.get("error") or "")
    except Exception as exc:
        error_summary = f"{type(exc).__name__}: {exc}"
        memory_update = MemoryUpdateStatus(
            attempted=True,
            stored=False,
            autoschema_requested=config.outcome_run_autoschema,
            outcome_direction=direction,
            message="Outcome memory update failed.",
            error=error_summary,
        )

    return _outcome_ack_card(
        title="Saved what happened" if stored else "Outcome noted",
        message=(
            "We will use this next time."
            if stored
            else "The app could not update memory yet."
        ),
        stored=stored,
        evidence=(
            f"Outcome was classified as {direction}.{autoschema_summary}"
            if stored
            else f"Outcome was classified as {direction}. {error_summary}".strip()
        ),
        memory_update=memory_update,
    )


def _severity_hint(request: OnlineDecisionRequest) -> Severity:
    text = f"{request.caregiver_note} {request.trigger_source.value}".lower()
    if _is_child_caregiver_contact(request, text):
        return Severity.danger
    if any(
        term in text
        for term in ("lost", "unsafe", "danger", "separation", "alone", "urgent")
    ):
        return Severity.danger
    if request.trigger_source == TriggerSource.child_trigger:
        return Severity.bad
    if request.calming_place_request.requested:
        return Severity.bad

    gates = [request.audio_gate, request.visual_gate, request.sensory_gate]
    if any(gate and gate.state == GateState.trigger for gate in gates):
        return Severity.bad
    if any(gate and gate.score >= 0.75 for gate in gates):
        return Severity.bad
    return Severity.mild


def _is_child_caregiver_contact(
    request: OnlineDecisionRequest,
    text: str,
) -> bool:
    if request.trigger_source != TriggerSource.child_trigger:
        return False
    return any(
        term in text
        for term in (
            "contact caregiver",
            "caregiver contact",
            "caregiver help",
            "requested caregiver",
        )
    )


def _apply_guardrails(
    request: OnlineDecisionRequest,
    severity_hint: Severity,
    decision: OnlineSupportDecision,
) -> OnlineSupportDecision:
    if severity_hint == Severity.danger:
        decision.decision.severity = Severity.danger
        decision.decision.action_type = ActionType.caregiver_alert
        decision.card.variant = CardVariant.caregiver_alert
        decision.card.title = decision.card.title or "Caregiver help now"
        decision.card.primary_message = (
            "Stay where you are if you can. Help is coming."
        )
        decision.card.steps = _clean_steps(
            decision.card.steps
            or ["Stop walking", "Look for caregiver", "Hold your support item"]
        )
        decision.card.caregiver_alert = {
            "urgency": "urgent",
            "message": "Please check in now. Support may be needed.",
            "include_location": request.location is not None
            and request.location.has_coordinates,
        }

    if decision.card.variant == CardVariant.location_change:
        decision.card.steps = _clean_steps(["Stay with caregiver", *decision.card.steps])
        if not decision.card.caregiver_note:
            decision.card.caregiver_note = (
                "Confirm route, crowd level, weather, and safety before moving."
            )

    decision.card.steps = _clean_steps(decision.card.steps)
    if not decision.card.measure_outcome:
        decision.card.measure_outcome = {
            "after_seconds": 120,
            "prompt": "Did this help?",
            "options": ["helped", "same", "harder"],
        }
    return decision


def _measurement_request(
    request: OnlineDecisionRequest,
    decision: OnlineSupportDecision,
) -> MeasurementRequest:
    after_seconds = decision.card.measure_outcome.get("after_seconds", 120)
    return MeasurementRequest(
        send_after_seconds=int(after_seconds),
        card_id=decision.card.card_id,
        action_type=decision.decision.action_type,
        card_variant=decision.card.variant,
        baseline={
            "audio_gate": _model_dump(request.audio_gate),
            "visual_gate": _model_dump(request.visual_gate),
            "sensory_gate": _model_dump(request.sensory_gate),
            "location": _model_dump(request.location),
        },
        support_card_snapshot=_support_card_snapshot(decision),
    )


def _support_card_snapshot(decision: OnlineSupportDecision) -> dict[str, Any]:
    card = decision.card
    return {
        "card_id": card.card_id,
        "variant": card.variant.value if hasattr(card.variant, "value") else str(card.variant),
        "title": card.title,
        "primary_message": card.primary_message,
        "steps": list(card.steps),
        "visual": dict(card.visual or {}),
        "location": dict(card.location or {}),
        "caregiver_alert": dict(card.caregiver_alert or {}),
        "caregiver_note": card.caregiver_note,
        "why_this": card.why_this,
        "actions": [dict(action) for action in card.actions],
        "measure_outcome": dict(card.measure_outcome or {}),
        "decision": {
            "severity": decision.decision.severity.value
            if hasattr(decision.decision.severity, "value")
            else str(decision.decision.severity),
            "action_type": decision.decision.action_type.value
            if hasattr(decision.decision.action_type, "value")
            else str(decision.decision.action_type),
            "reason": decision.decision.reason,
        },
        "evidence": {
            "profile_used": decision.evidence.profile_used,
            "past_experience_used": decision.evidence.past_experience_used,
            "kg_memory_used": decision.evidence.kg_memory_used,
            "calming_place_used": decision.evidence.calming_place_used,
            "summary": decision.evidence.summary,
        },
    }


async def _enrich_location_change_card(
    request: OnlineDecisionRequest,
    decision: OnlineSupportDecision,
) -> OnlineSupportDecision:
    if decision.card.variant != CardVariant.location_change:
        return decision
    if request.location is None or not request.location.has_coordinates:
        return decision

    location = decision.card.location or {}
    if _has_real_place(location):
        decision.evidence.calming_place_used = True
        return decision

    try:
        lookup = await calming_place_lookup(
            latitude=float(request.location.latitude),
            longitude=float(request.location.longitude),
            radius_m=request.calming_place_request.radius_m,
            max_results=request.calming_place_request.max_results,
            sensory_need=request.calming_place_request.sensory_need,
            correlation_id=f"online-location-{uuid4().hex}",
        )
    except Exception as exc:
        decision.card.caregiver_note = _append_note(
            decision.card.caregiver_note,
            f"Calming-place lookup failed: {type(exc).__name__}. Confirm the safest nearby option manually.",
        )
        return decision

    best_place = lookup.get("best_place")
    if not lookup.get("success") or not isinstance(best_place, dict):
        fallback_note = str(lookup.get("agent_context") or "").strip()
        decision.card.caregiver_note = _append_note(
            decision.card.caregiver_note,
            fallback_note
            or "No nearby quieter place was found. Confirm the safest nearby option manually.",
        )
        return decision

    decision.card.location = {
        "place_name": str(best_place.get("name") or "Nearby calmer place"),
        "category": str(best_place.get("category") or "place"),
        "distance_m": _optional_int(best_place.get("distance_m")) or 0,
        "latitude": best_place.get("latitude"),
        "longitude": best_place.get("longitude"),
        "why": best_place.get("why") or [],
        "tradeoffs": best_place.get("tradeoffs") or [],
    }
    decision.card.caregiver_note = _append_note(
        decision.card.caregiver_note,
        str(lookup.get("caregiver_note") or "")
        or "Caregiver confirms route, crowd level, weather, and safety before moving.",
    )
    decision.card.why_this = _append_note(
        decision.card.why_this,
        str(lookup.get("agent_context") or "Nearby calming-place lookup found a candidate."),
    )
    decision.evidence.calming_place_used = True
    return decision


def _fallback_decision(
    request: OnlineDecisionRequest,
    severity: Severity,
    fallback_summary: str | None = None,
) -> OnlineSupportDecision:
    if severity == Severity.danger:
        decision = _caregiver_alert_fallback(request)
    elif request.calming_place_request.requested and request.location:
        decision = _location_change_fallback(request)
    elif _should_try_location_change(request, severity):
        decision = _location_change_fallback(request)
    else:
        decision = _support_card_fallback(request, severity)

    if fallback_summary:
        decision.evidence.summary = fallback_summary
    return decision


def _support_card_fallback(
    request: OnlineDecisionRequest,
    severity: Severity,
) -> OnlineSupportDecision:
    note = request.caregiver_note.lower()
    audio_gate = request.audio_gate
    visual_gate = request.visual_gate
    sensory_gate = request.sensory_gate

    if _audio_support_needed(request):
        variant = CardVariant.sensory_tool
        title = "Use headphones"
        primary_message = "Put on headphones and stay close."
        steps = [
            "Find headphones",
            "Put them on",
            "Stay near caregiver",
        ]
        visual = {"type": "icon", "image_url": "", "label": "headphones"}
        caregiver_note = (
            "Offer the headphones without extra questions, then reduce talking."
        )
        reason = "Audio support was selected from noise and caregiver context."
    elif _visual_support_needed(request):
        variant = CardVariant.coping_support
        title = "Find one calm thing"
        primary_message = "Look at one still thing with your caregiver."
        steps = [
            "Turn toward a calmer view",
            "Look at one still thing",
            "Take three slow breaths",
        ]
        visual = {"type": "icon", "image_url": "", "label": "calm-view"}
        caregiver_note = "Reduce visual demand and avoid pointing out many things."
        reason = "Visual support was selected from motion, brightness, or clutter."
    elif "wait" in note or "transition" in note:
        variant = CardVariant.coping_support
        title = "Make waiting smaller"
        primary_message = "We can wait one small piece at a time."
        steps = [
            "Check the timer",
            "Choose one quiet activity",
            "Ask caregiver for a break",
        ]
        visual = {"type": "icon", "image_url": "", "label": "timer"}
        caregiver_note = "Use concrete time language and offer a small choice."
        reason = "Waiting support was selected from caregiver context."
    else:
        variant = CardVariant.coping_support
        title = "Take three slow breaths"
        primary_message = "Choose one calm next step."
        steps = [
            "Take three slow breaths",
            "Move to a quiet place",
            "Contact caregiver if you are overwhelmed",
        ]
        visual = {"type": "icon", "image_url": "", "label": "support"}
        caregiver_note = "Use short language and offer the support without extra questions."
        reason = "A low-demand support card was selected."

    signal_reason = _fallback_signal_reason(audio_gate, visual_gate, sensory_gate)
    return OnlineSupportDecision(
        decision=DecisionSummary(
            severity=severity,
            action_type=ActionType.support_card,
            reason=reason,
        ),
        card=OnlineSupportCard(
            variant=variant,
            title=title,
            primary_message=primary_message,
            steps=steps,
            visual=visual,
            caregiver_alert={
                "urgency": "none",
                "message": "",
                "include_location": False,
            },
            caregiver_note=caregiver_note,
            why_this=signal_reason or "Deterministic support selected from live signals.",
            actions=[
                {"id": "mark_helped", "label": "Helped"},
                {"id": "need_more", "label": "Need more"},
            ],
            measure_outcome={
                "after_seconds": 120,
                "prompt": "Did this help?",
                "options": ["helped", "same", "harder"],
            },
        ),
        evidence=EvidenceSummary(summary="Deterministic fallback used."),
    )


def _audio_support_needed(request: OnlineDecisionRequest) -> bool:
    note = request.caregiver_note.lower()
    reasons = " ".join(request.audio_gate.reasons if request.audio_gate else []).lower()
    return (
        "loud" in note
        or "noise" in note
        or "covering ears" in note
        or "headphone" in note
        or "noise" in reasons
        or request.audio_gate is not None
        and request.audio_gate.state in {GateState.elevated, GateState.trigger}
    )


def _visual_support_needed(request: OnlineDecisionRequest) -> bool:
    note = request.caregiver_note.lower()
    reasons = " ".join(request.visual_gate.reasons if request.visual_gate else []).lower()
    return (
        "bright" in note
        or "busy" in note
        or "crowd" in note
        or "motion" in reasons
        or "bright" in reasons
        or "clutter" in reasons
        or request.visual_gate is not None
        and request.visual_gate.state in {GateState.elevated, GateState.trigger}
    )


def _should_try_location_change(
    request: OnlineDecisionRequest,
    severity: Severity,
) -> bool:
    if severity != Severity.bad:
        return False
    if request.location is None or not request.location.has_coordinates:
        return False
    note = request.caregiver_note.lower()
    sensory_score = request.sensory_gate.score if request.sensory_gate else 0
    return (
        sensory_score >= 0.82
        or "overwhelming" in note
        or "crowded" in note
        or "quieter" in note
        or "move" in note
    )


def _fallback_signal_reason(
    audio_gate: GateSummary | None,
    visual_gate: GateSummary | None,
    sensory_gate: GateSummary | None,
) -> str:
    parts = []
    if audio_gate is not None and audio_gate.state != GateState.ok:
        parts.append(f"audio {audio_gate.state.value}")
    if visual_gate is not None and visual_gate.state != GateState.ok:
        parts.append(f"visual {visual_gate.state.value}")
    if sensory_gate is not None and sensory_gate.state != GateState.ok:
        parts.append(f"sensory {sensory_gate.state.value}")
    if not parts:
        return ""
    return "Selected because " + ", ".join(parts) + "."


def _location_change_fallback(request: OnlineDecisionRequest) -> OnlineSupportDecision:
    label = request.location.label if request.location else "nearby quieter place"
    return OnlineSupportDecision(
        decision=DecisionSummary(
            severity=Severity.bad,
            action_type=ActionType.location_change,
            reason="Caregiver requested help finding a quieter place.",
        ),
        card=OnlineSupportCard(
            variant=CardVariant.location_change,
            title="Try a quieter place",
            primary_message="Stay with your caregiver. Let's find more space.",
            steps=[
                "Stay with caregiver",
                "Move toward a quieter edge",
                "Pause before deciding what next",
            ],
            visual={"type": "icon", "image_url": "", "label": "location"},
            location={
                "place_name": label or "",
                "distance_m": 0,
                "latitude": request.location.latitude if request.location else None,
                "longitude": request.location.longitude if request.location else None,
                "why": "Caregiver requested a quieter place.",
            },
            caregiver_alert={
                "urgency": "none",
                "message": "",
                "include_location": False,
            },
            caregiver_note=(
                "Confirm route, crowd level, weather, and safety before moving."
            ),
            why_this="Location support was requested and coordinates were available.",
            actions=[
                {"id": "start_move", "label": "Start moving"},
                {"id": "not_safe", "label": "Not safe"},
            ],
            measure_outcome={
                "after_seconds": 120,
                "prompt": "Did this help?",
                "options": ["helped", "same", "harder"],
            },
        ),
        evidence=EvidenceSummary(summary="Deterministic location fallback used."),
    )


def _caregiver_alert_fallback(request: OnlineDecisionRequest) -> OnlineSupportDecision:
    return OnlineSupportDecision(
        decision=DecisionSummary(
            severity=Severity.danger,
            action_type=ActionType.caregiver_alert,
            reason="Safety guardrail requested caregiver check-in.",
        ),
        card=OnlineSupportCard(
            variant=CardVariant.caregiver_alert,
            title="Caregiver help now",
            primary_message="Stay where you are if you can. Help is coming.",
            steps=["Stop walking", "Look for caregiver", "Hold your support item"],
            visual={"type": "icon", "image_url": "", "label": "caregiver"},
            caregiver_alert={
                "urgency": "urgent",
                "message": "Please check in now.",
                "include_location": request.location is not None
                and request.location.has_coordinates,
            },
            caregiver_note="Check in directly and confirm the child is safe.",
            why_this="Fallback safety card.",
            actions=[{"id": "alert_sent", "label": "Alert sent"}],
            measure_outcome={
                "after_seconds": 120,
                "prompt": "Did this help?",
                "options": ["helped", "same", "harder"],
            },
        ),
        evidence=EvidenceSummary(summary="Deterministic safety fallback used."),
    )


def _outcome_ack_card(
    *,
    title: str,
    message: str,
    stored: bool,
    evidence: str,
    memory_update: MemoryUpdateStatus | None = None,
) -> OnlineSupportDecision:
    return OnlineSupportDecision(
        decision=DecisionSummary(
            severity=Severity.mild,
            action_type=ActionType.support_card,
            reason="Outcome check handled.",
        ),
        card=OnlineSupportCard(
            variant=CardVariant.recovery_check,
            title=title,
            primary_message=message,
            steps=["Rest now", "No more talking needed"],
            visual={"type": "icon", "image_url": "", "label": "check"},
            caregiver_alert={
                "urgency": "none",
                "message": "",
                "include_location": False,
            },
            caregiver_note=(
                "Outcome memory was updated."
                if stored
                else "Outcome memory update can be retried later."
            ),
            why_this="Outcome check response.",
            actions=[{"id": "done", "label": "Done"}],
            measure_outcome={},
        ),
        evidence=EvidenceSummary(
            kg_memory_used=stored,
            summary=evidence,
        ),
        system={"memory_update": memory_update} if memory_update else {},
    )


def _outcome_direction(request: OnlineDecisionRequest) -> str:
    baseline = request.outcome_context.baseline if request.outcome_context else {}
    before = _best_score(
        baseline.get("sensory_gate"),
        baseline.get("audio_gate"),
        baseline.get("visual_gate"),
    )
    after = _best_score(request.sensory_gate, request.audio_gate, request.visual_gate)
    if before is None or after is None:
        return "unknown"
    delta = after - before
    if delta <= -0.15:
        return "improved"
    if delta >= 0.15:
        return "dropped"
    return "no_change"


def _experience_event_from_outcome(
    request: OnlineDecisionRequest,
    direction: str,
) -> dict[str, Any]:
    context = request.outcome_context
    action_type = {
        ActionType.support_card: "support_card",
        ActionType.location_change: "location_change",
        ActionType.caregiver_alert: "alert_caregiver",
    }[context.action_type]
    observed_after_seconds = _observed_after_seconds(context.baseline)
    snapshot = context.support_card_snapshot or {}
    action_label = (
        str(snapshot.get("title") or "").strip()
        or str(snapshot.get("variant") or "").strip()
        or context.card_variant.value
    )
    return {
        "profile_id": request.profile_id,
        "situation": {
            "surface": request.surface.value,
            "caregiver_note": request.caregiver_note,
        },
        "location_context": _model_dump(request.location) or {},
        "signals": {
            "before": context.baseline,
            "after": {
                "audio_gate": _model_dump(request.audio_gate),
                "visual_gate": _model_dump(request.visual_gate),
                "sensory_gate": _model_dump(request.sensory_gate),
            },
        },
        "action_taken": {
            "action_type": action_type,
            "label": action_label,
            "details": {
                "card_id": context.card_id,
                "card_variant": context.card_variant.value,
                "support_card_snapshot": snapshot,
            },
        },
        "outcome": {
            "direction": direction,
            "summary": f"Outcome was {direction} after {action_label}.",
            "observed_after_seconds": observed_after_seconds,
            "signal_delta": _signal_delta(context.baseline, request),
        },
        "caregiver_feedback": request.caregiver_note,
        "source": "online_support",
    }


def _signal_delta(
    baseline: dict[str, Any],
    request: OnlineDecisionRequest,
) -> dict[str, Any]:
    return {
        "audio_score_delta": _score_delta(baseline.get("audio_gate"), request.audio_gate),
        "visual_score_delta": _score_delta(
            baseline.get("visual_gate"),
            request.visual_gate,
        ),
        "sensory_score_delta": _score_delta(
            baseline.get("sensory_gate"),
            request.sensory_gate,
        ),
    }


def _score_delta(before: Any, after: Any) -> float | None:
    before_score = _score(before)
    after_score = _score(after)
    if before_score is None or after_score is None:
        return None
    return round(after_score - before_score, 3)


def _best_score(*items: Any) -> float | None:
    scores: list[float] = []
    for item in items:
        score = _score(item)
        if score is not None:
            scores.append(score)
    return max(scores) if scores else None


def _score(item: Any) -> float | None:
    if item is None:
        return None
    if isinstance(item, GateSummary):
        return item.score
    if isinstance(item, dict) and isinstance(item.get("score"), (int, float)):
        return float(item["score"])
    return None


def _observed_after_seconds(baseline: dict[str, Any]) -> int | None:
    value = baseline.get("observed_after_seconds")
    return int(value) if isinstance(value, int) else None


def _coerce_decision(payload: Any) -> OnlineSupportDecision:
    if isinstance(payload, OnlineSupportDecision):
        return payload
    if isinstance(payload, str):
        return OnlineSupportDecision.model_validate_json(payload)
    return OnlineSupportDecision.model_validate(payload)


def _event_text(event: Any) -> str:
    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) if content is not None else None
    if parts is None and isinstance(content, dict):
        parts = content.get("parts")
    parts = parts or []

    text_parts = []
    for part in parts:
        text = getattr(part, "text", None)
        if text is None and isinstance(part, dict):
            text = part.get("text")
        if text:
            text_parts.append(str(text))
    return "\n".join(text_parts)


def _clean_steps(steps: list[str]) -> list[str]:
    cleaned = []
    for step in steps:
        text = str(step).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned[:3] or ["Take one small step"]


def _model_dump(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    return None


def _has_real_place(location: dict[str, Any]) -> bool:
    place_name = str(location.get("place_name") or location.get("name") or "").strip()
    distance = _optional_int(location.get("distance_m"))
    return bool(place_name) and distance is not None and distance > 0


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value)
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _append_note(existing: str, note: str) -> str:
    existing = existing.strip()
    note = note.strip()
    if not note:
        return existing
    if not existing:
        return note
    if note in existing:
        return existing
    return f"{existing} {note}"
