"""Mobile-first caregiver reflection service.

This service turns graph-memory events from a single local day into an editable
A2UI reflection form, then persists the caregiver-approved reflection back to
episode history and graph memory.
"""
from __future__ import annotations

import json
import os
import asyncio
from datetime import date as date_type
from datetime import datetime, time, timedelta, timezone
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.mcp_server.src.services.graph_memory.models import ExperienceEvent
from app.mcp_server.src.services.graph_memory.store import GraphMemoryStore
from app.mcp_server.src.services.profile_episode_store import create_episode

REFLECT_SURFACE_ID = "reflect-surface"
DEFAULT_TIMEZONE = "America/New_York"
DEFAULT_CAREGIVER_ID = "local-caregiver"
REFLECT_SOURCE_TYPES = {"all", "online", "offline", "custom"}


async def build_reflect_experiences_response(
    *,
    profile_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
    source_type: str = "all",
    timezone_name: str = DEFAULT_TIMEZONE,
) -> dict[str, Any]:
    """Return normalized online/offline/custom experience cards for Reflect."""
    local_tz = _safe_zoneinfo(timezone_name)
    start_local, end_local = _parse_local_range(start_date, end_date, local_tz)
    normalized_source = _normalize_source_filter(source_type)
    events = _events_for_local_range(profile_id, start_local, end_local, local_tz)
    experiences = [
        _experience_card(event, local_tz)
        for event in events
        if _source_matches(event, normalized_source)
    ]
    experiences = sorted(
        experiences,
        key=lambda item: str(item.get("occurred_at") or ""),
        reverse=True,
    )
    source_counts = {"online": 0, "offline": 0, "custom": 0}
    for item in experiences:
        current_source = item.get("source_type")
        if current_source in source_counts:
            source_counts[current_source] += 1

    return {
        "success": True,
        "profile_id": profile_id,
        "start_date": start_local.isoformat(),
        "end_date": end_local.isoformat(),
        "timezone": getattr(local_tz, "key", timezone_name),
        "source_type": normalized_source,
        "experience_count": len(experiences),
        "source_counts": source_counts,
        "experiences": experiences,
    }


async def build_reflect_day_response(
    *,
    profile_id: str,
    reflect_date: str | None = None,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> dict[str, Any]:
    """Return today timeline data plus A2UI messages for the mobile Reflect tab."""
    local_tz = _safe_zoneinfo(timezone_name)
    local_date = _parse_local_date(reflect_date, local_tz)
    events = _events_for_local_date(profile_id, local_date, local_tz)
    timeline = [_timeline_item(event, local_tz) for event in events]
    draft, draft_source = await _generate_reflection_draft(timeline, local_date)
    source_event_ids = [item["event_id"] for item in timeline if item.get("event_id")]

    payload = {
        "success": True,
        "profile_id": profile_id,
        "date": local_date.isoformat(),
        "timezone": getattr(local_tz, "key", timezone_name),
        "event_count": len(timeline),
        "source_event_ids": source_event_ids,
        "timeline": timeline,
        "reflection": draft,
        "draft_source": draft_source,
    }
    return {
        **payload,
        "messages": build_reflect_a2ui_messages(payload),
    }


async def save_reflection_action(
    *,
    profile_id: str,
    reflect_date: str,
    timezone_name: str,
    reflection: dict[str, Any],
    source_event_ids: list[str],
) -> dict[str, Any]:
    """Persist an approved reflection to episode history and graph memory."""
    local_tz = _safe_zoneinfo(timezone_name)
    local_date = _parse_local_date(reflect_date, local_tz)
    cleaned = _clean_reflection(reflection)
    summary = _reflection_summary_text(cleaned)
    event_date = datetime.combine(local_date, time(hour=12), tzinfo=local_tz).astimezone(timezone.utc).isoformat()

    episode = None
    episode_error = None
    try:
        episode = await create_episode(
            profile_id=profile_id,
            caregiver_id=DEFAULT_CAREGIVER_ID,
            title=f"Reflection for {local_date.isoformat()}",
            scenario_type="caregiver_reflection",
            location_type=None,
            episode_summary=summary,
            episode_json={
                "reflection": cleaned,
                "source_event_ids": source_event_ids,
                "reflect_date": local_date.isoformat(),
                "timezone": getattr(local_tz, "key", timezone_name),
                "source": "reflect_page",
            },
            event_date=event_date,
        )
    except Exception as exc:  # Keep graph-memory persistence useful in local POC runs.
        episode_error = f"{type(exc).__name__}: {exc}"

    graph_result = await GraphMemoryStore().insert_event(
        event_payload={
            "event_id": f"reflection_{uuid4().hex[:12]}",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "situation": {
                "surface": "reflect",
                "date": local_date.isoformat(),
                "summary": cleaned.get("what_happened", ""),
            },
            "signals": {},
            "location_context": {},
            "action_taken": {
                "action_type": "other",
                "label": "caregiver_reflection",
                "details": {
                    "source_event_ids": source_event_ids,
                    "reflection": cleaned,
                    "episode_id": episode.get("episode_id") if isinstance(episode, dict) else None,
                },
            },
            "outcome": {
                "direction": "unknown",
                "summary": cleaned.get("what_should_change_next_time", "")
                or "Caregiver reflection saved for future support planning.",
            },
            "caregiver_feedback": summary,
            "next_time_adjustment": cleaned.get("what_should_change_next_time", ""),
            "source": "caregiver_reflection",
        },
        profile_id=profile_id,
        run_autoschema=False,
    )

    return {
        "success": episode_error is None,
        "profile_id": profile_id,
        "date": local_date.isoformat(),
        "episode": episode,
        "episode_error": episode_error,
        "graph_event": graph_result.get("event"),
        "graph": graph_result.get("graph"),
    }


async def save_custom_experience_action(
    *,
    profile_id: str,
    timezone_name: str,
    experience: dict[str, Any],
) -> dict[str, Any]:
    """Persist a caregiver-entered experience to episode history and graph memory."""
    local_tz = _safe_zoneinfo(timezone_name)
    cleaned = _clean_custom_experience(experience)
    occurred_at = _parse_custom_experience_time(cleaned.get("occurred_at"), local_tz)
    event_id = f"custom_experience_{uuid4().hex[:12]}"
    summary = _custom_experience_summary_text(cleaned)

    graph_result = await GraphMemoryStore().insert_event(
        event_payload={
            "event_id": event_id,
            "occurred_at": occurred_at,
            "situation": {
                "surface": "reflect",
                "scenario": cleaned["scenario"],
                "summary": cleaned["summary"] or cleaned["scenario"],
                "title": cleaned["title"],
            },
            "signals": {
                "friction_points": cleaned["friction_points"],
            },
            "location_context": {},
            "action_taken": {
                "action_type": "other",
                "label": "caregiver_custom_experience",
                "details": {
                    "source": "reflect_experiences",
                    "experience": cleaned,
                },
            },
            "outcome": {
                "direction": "unknown",
                "summary": cleaned["learned_about_child"]
                or cleaned["what_helped"]
                or "Caregiver added a custom experience.",
            },
            "caregiver_feedback": summary,
            "next_time_adjustment": cleaned["learned_about_child"],
            "source": "custom_experience",
        },
        profile_id=profile_id,
        run_autoschema=False,
    )

    episode = None
    episode_error = None
    try:
        episode = await create_episode(
            profile_id=profile_id,
            caregiver_id=DEFAULT_CAREGIVER_ID,
            title=cleaned["title"] or "Custom caregiver experience",
            scenario_type="custom_experience",
            location_type=None,
            episode_summary=summary,
            episode_json={
                "experience": cleaned,
                "graph_event_id": event_id,
                "source": "reflect_experiences",
            },
            event_date=occurred_at,
        )
    except Exception as exc:
        episode_error = f"{type(exc).__name__}: {exc}"

    return {
        "success": episode_error is None,
        "profile_id": profile_id,
        "event_id": event_id,
        "episode": episode,
        "episode_error": episode_error,
        "graph_event": graph_result.get("event"),
        "graph": graph_result.get("graph"),
    }


def build_reflect_a2ui_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a small A2UI v0.8 form for the mobile allowlisted renderer."""
    event_count = int(payload.get("event_count") or 0)
    return [
        {
            "surfaceUpdate": {
                "surfaceId": REFLECT_SURFACE_ID,
                "components": [
                    {
                        "id": "reflect-form-root",
                        "component": {
                            "gemma4.reflectForm": {
                                "title": "Reflect Experiences",
                                "description": (
                                    "Review online, offline, and custom experiences, "
                                    "then save what should help next time."
                                ),
                                "empty": event_count == 0,
                                "date": payload.get("date", ""),
                                "draftPath": "/reflection",
                                "timelinePath": "/timeline",
                                "primaryActionLabel": "Save reflection",
                                "primaryAction": {
                                    "name": "save_reflection",
                                    "context": [
                                        {"key": "profile_id", "value": {"literalString": payload.get("profile_id", "")}},
                                        {"key": "date", "value": {"literalString": payload.get("date", "")}},
                                        {"key": "timezone", "value": {"literalString": payload.get("timezone", DEFAULT_TIMEZONE)}},
                                        {"key": "reflection", "value": {"path": "/reflection"}},
                                        {"key": "source_event_ids", "value": {"path": "/source_event_ids"}},
                                    ],
                                },
                            }
                        },
                    }
                ],
            }
        },
        {
            "dataModelUpdate": {
                "surfaceId": REFLECT_SURFACE_ID,
                "path": "/",
                "contents": [
                    _to_value_map("timeline", payload.get("timeline", [])),
                    _to_value_map("reflection", payload.get("reflection", {})),
                    _to_value_map("source_event_ids", payload.get("source_event_ids", [])),
                    _to_value_map(
                        "meta",
                        {
                            "profile_id": payload.get("profile_id", ""),
                            "date": payload.get("date", ""),
                            "timezone": payload.get("timezone", DEFAULT_TIMEZONE),
                            "event_count": event_count,
                        },
                    ),
                ],
            }
        },
        {
            "beginRendering": {
                "surfaceId": REFLECT_SURFACE_ID,
                "root": "reflect-form-root",
            }
        },
    ]


def _events_for_local_date(
    profile_id: str,
    local_date: date_type,
    local_tz: ZoneInfo,
) -> list[ExperienceEvent]:
    return _events_for_local_range(profile_id, local_date, local_date, local_tz)


def _events_for_local_range(
    profile_id: str,
    start_local: date_type,
    end_local: date_type,
    local_tz: ZoneInfo,
) -> list[ExperienceEvent]:
    start = datetime.combine(start_local, time.min, tzinfo=local_tz).astimezone(timezone.utc)
    end = datetime.combine(end_local, time.max, tzinfo=local_tz).astimezone(timezone.utc)
    events = []
    for event in GraphMemoryStore().load_events(profile_id):
        occurred_at = _parse_event_time(event.occurred_at)
        if start <= occurred_at <= end:
            events.append(event)
    return sorted(events, key=lambda item: _parse_event_time(item.occurred_at))


def _experience_card(event: ExperienceEvent, local_tz: ZoneInfo) -> dict[str, Any]:
    action = event.normalized_action()
    outcome = event.normalized_outcome()
    source_type = _experience_source_type(event)
    snapshot = action.details.get("support_card_snapshot") if isinstance(action.details, dict) else {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    details = action.details if isinstance(action.details, dict) else {}
    custom = _as_dict(details.get("experience"))
    review = _as_dict(details.get("review"))
    situation = _as_dict(event.situation)
    occurred_at = _parse_event_time(event.occurred_at).astimezone(local_tz)
    title = _experience_title(event, action.label, outcome.direction, snapshot, review, custom)
    scenario = _experience_scenario(event, situation, review, custom)
    friction_points = _experience_friction_points(event, review, custom)
    what_helped = _experience_what_helped(event, action, outcome, snapshot, review, custom)
    what_did_not_help = _experience_what_did_not_help(event, outcome, review, custom)
    learned = _experience_learning(event, outcome, review, custom)
    summary = _first_non_empty(
        custom.get("summary"),
        snapshot.get("primary_message"),
        outcome.summary,
        event.caregiver_feedback,
        scenario,
    )

    return {
        "id": event.event_id,
        "event_id": event.event_id,
        "source": event.source,
        "source_type": source_type,
        "source_label": _source_label(source_type),
        "occurred_at": event.occurred_at,
        "date_label": occurred_at.strftime("%b %-d"),
        "time_label": occurred_at.strftime("%-I:%M %p"),
        "title": title,
        "summary": summary,
        "scenario": scenario,
        "friction_points": friction_points,
        "what_helped": what_helped,
        "what_did_not_help": what_did_not_help,
        "learned_about_child": learned,
        "support_label": action.label.replace("_", " ") if action.label else "",
        "outcome": outcome.direction,
        "outcome_label": _outcome_label(outcome.direction),
        "card_title": str(snapshot.get("title") or "").strip(),
        "card_message": str(snapshot.get("primary_message") or "").strip(),
        "source_event_ids": [event.event_id],
    }


def _experience_source_type(event: ExperienceEvent) -> str:
    source = str(event.source or "").lower()
    situation = _as_dict(event.situation)
    surface = str(situation.get("surface") or "").lower()
    if source in {"online_support", "live_support"} or surface in {"live", "navigate", "recover"}:
        return "online"
    if source in {"prepare_review", "offline_support"} or surface == "prepare":
        return "offline"
    return "custom"


def _source_matches(event: ExperienceEvent, source_type: str) -> bool:
    return source_type == "all" or _experience_source_type(event) == source_type


def _source_label(source_type: str) -> str:
    return {
        "online": "Online",
        "offline": "Offline",
        "custom": "Custom",
    }.get(source_type, "Memory")


def _outcome_label(direction: str) -> str:
    return {
        "improved": "Helped",
        "dropped": "Adjust",
        "no_change": "Review",
        "unknown": "Learn",
    }.get(direction, "Learn")


def _experience_title(
    event: ExperienceEvent,
    label: str,
    direction: str,
    snapshot: dict[str, Any],
    review: dict[str, Any],
    custom: dict[str, Any],
) -> str:
    prepare_title = ""
    if _experience_source_type(event) == "offline":
        prepare_title = _prefix_title(
            "Prepare review",
            review.get("scenario") or _as_dict(event.situation).get("scenario"),
        )
    return _first_non_empty(
        custom.get("title"),
        snapshot.get("title"),
        prepare_title,
        _event_title(event, label or "support", direction),
    )


def _prefix_title(prefix: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return f"{prefix}: {text}"


def _experience_scenario(
    event: ExperienceEvent,
    situation: dict[str, Any],
    review: dict[str, Any],
    custom: dict[str, Any],
) -> str:
    if custom:
        return _first_non_empty(custom.get("scenario"), custom.get("summary"))
    if review:
        return _first_non_empty(review.get("scenario"), situation.get("scenario"), situation.get("summary"))
    return _first_non_empty(
        situation.get("scenario"),
        situation.get("summary"),
        situation.get("place"),
        situation.get("caregiver_note"),
        event.caregiver_feedback,
    )


def _experience_friction_points(
    event: ExperienceEvent,
    review: dict[str, Any],
    custom: dict[str, Any],
) -> list[str]:
    if custom:
        return _split_points(custom.get("friction_points"))
    points = []
    if review:
        points.extend(_split_points(review.get("sensory_issues")))
        points.extend(_split_points(review.get("needs_improvement")))
    signals = event.signals or {}
    points.extend(_split_points(signals.get("sensory_issues")))
    points.extend(_split_points(signals.get("needs_improvement")))
    before = signals.get("before")
    if isinstance(before, dict):
        for key, value in before.items():
            if isinstance(value, dict) and value.get("score") is not None:
                label = str(value.get("label") or value.get("summary") or key).replace("_", " ")
                points.append(label)
    return _unique(points)[:5]


def _experience_what_helped(
    event: ExperienceEvent,
    action: Any,
    outcome: Any,
    snapshot: dict[str, Any],
    review: dict[str, Any],
    custom: dict[str, Any],
) -> list[str]:
    if custom:
        return _split_points(custom.get("what_helped"))
    points = []
    if review:
        points.extend(_split_points(review.get("what_went_well")))
    if outcome.direction == "improved" and action.label:
        points.append(action.label.replace("_", " "))
    if isinstance(snapshot.get("steps"), list):
        points.extend(str(step) for step in snapshot["steps"] if str(step).strip())
    signals = event.signals or {}
    reviewed = signals.get("reviewed_supports")
    if isinstance(reviewed, dict):
        points.extend(str(item) for item in reviewed.get("packed_tools", []) if str(item).strip())
    return _unique(points)[:5]


def _experience_what_did_not_help(
    event: ExperienceEvent,
    outcome: Any,
    review: dict[str, Any],
    custom: dict[str, Any],
) -> list[str]:
    if custom:
        return _split_points(custom.get("what_did_not_help"))
    points = []
    if review:
        points.extend(_split_points(review.get("needs_improvement")))
        points.extend(_split_points(review.get("sensory_issues")))
    if outcome.direction in {"dropped", "no_change"} and outcome.summary:
        points.append(outcome.summary)
    signals = event.signals or {}
    points.extend(_split_points(signals.get("needs_improvement")))
    return _unique(points)[:5]


def _experience_learning(
    event: ExperienceEvent,
    outcome: Any,
    review: dict[str, Any],
    custom: dict[str, Any],
) -> str:
    return _first_non_empty(
        custom.get("learned_about_child"),
        review.get("what_we_learned"),
        event.next_time_adjustment,
        outcome.summary,
        event.caregiver_feedback,
    )


def _timeline_item(event: ExperienceEvent, local_tz: ZoneInfo) -> dict[str, Any]:
    action = event.normalized_action()
    outcome = event.normalized_outcome()
    snapshot = action.details.get("support_card_snapshot") if isinstance(action.details, dict) else {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    occurred_at = _parse_event_time(event.occurred_at).astimezone(local_tz)
    before = _best_signal_score((event.signals or {}).get("before"))
    after = _best_signal_score((event.signals or {}).get("after"))
    caregiver_note = _extract_caregiver_note(event)
    label = action.label or action.action_type or "support"
    title = _event_title(event, label, outcome.direction)
    return {
        "event_id": event.event_id,
        "occurred_at": event.occurred_at,
        "time_label": occurred_at.strftime("%-I:%M %p"),
        "source": event.source,
        "title": title,
        "support_label": label.replace("_", " "),
        "card_title": str(snapshot.get("title") or "").strip(),
        "card_message": str(snapshot.get("primary_message") or "").strip(),
        "card_steps": [str(step) for step in snapshot.get("steps", []) if str(step).strip()]
        if isinstance(snapshot.get("steps"), list)
        else [],
        "card_why_this": str(snapshot.get("why_this") or "").strip(),
        "action_type": action.action_type,
        "outcome_direction": outcome.direction,
        "outcome_summary": outcome.summary,
        "caregiver_note": caregiver_note,
        "before_score": before,
        "after_score": after,
        "score_delta": round(after - before, 3) if before is not None and after is not None else None,
    }


async def _generate_reflection_draft(
    timeline: list[dict[str, Any]],
    local_date: date_type,
) -> tuple[dict[str, Any], str]:
    fallback = _draft_reflection(timeline, local_date)
    if not _env_bool("GEMMA4_REFLECT_USE_MODEL", "false"):
        return fallback, "deterministic"

    try:
        generated = await _draft_reflection_with_model(timeline, local_date)
    except Exception:
        return fallback, "deterministic_fallback"
    return {**fallback, **_clean_reflection(generated)}, "model"


async def _draft_reflection_with_model(
    timeline: list[dict[str, Any]],
    local_date: date_type,
) -> dict[str, Any]:
    def _run() -> dict[str, Any]:
        from google import genai
        from google.genai import types

        model = os.getenv(
            "GEMMA4_REFLECT_MODEL",
            os.getenv("GEMMA4_VERTEX_EVAL_MODEL", "gemini-2.5-flash"),
        )
        client = genai.Client()
        prompt = {
            "task": (
                "Draft a concise caregiver reflection from today's Gemma4 support memories. "
                "Do not diagnose. Use calm, plain language. Return JSON only."
            ),
            "date": local_date.isoformat(),
            "timeline": timeline,
            "required_fields": [
                "what_happened",
                "what_went_well",
                "what_helped",
                "what_did_not_help",
                "what_should_change_next_time",
                "caregiver_notes",
            ],
        }
        response = client.models.generate_content(
            model=model,
            contents=json.dumps(prompt, ensure_ascii=True, default=str),
            config=types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )
        text = getattr(response, "text", "") or "{}"
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            return {}
        return parsed

    return await asyncio.to_thread(_run)


def _draft_reflection(timeline: list[dict[str, Any]], local_date: date_type) -> dict[str, Any]:
    if not timeline:
        return {
            "what_happened": f"No saved support memories were found for {local_date.isoformat()} yet.",
            "what_went_well": "",
            "what_helped": "",
            "what_did_not_help": "",
            "what_should_change_next_time": "",
            "caregiver_notes": "",
        }

    improved = [item for item in timeline if item.get("outcome_direction") == "improved"]
    harder = [item for item in timeline if item.get("outcome_direction") in {"dropped", "no_change"}]
    supports = _unique(item.get("support_label", "") for item in timeline)
    helpful = _unique(item.get("support_label", "") for item in improved)
    card_titles = _unique(item.get("card_title", "") for item in timeline)
    notes = _unique(item.get("caregiver_note", "") for item in timeline)

    return {
        "what_happened": (
            f"{len(timeline)} support moment{'s' if len(timeline) != 1 else ''} were saved today: "
            f"{', '.join(card_titles or supports) if (card_titles or supports) else 'support actions'}."
        ),
        "what_went_well": (
            f"{len(improved)} support moment{'s' if len(improved) != 1 else ''} showed settling or improvement."
            if improved
            else "No clear improvement was saved yet."
        ),
        "what_helped": (
            f"Helpful supports today: {', '.join(_unique(item.get('card_title') or item.get('support_label') for item in improved))}."
            if improved
            else "No specific helpful support has been confirmed yet."
        ),
        "what_did_not_help": (
            f"{len(harder)} moment{'s' if len(harder) != 1 else ''} still need review."
            if harder
            else "No saved support was marked as harder or unchanged."
        ),
        "what_should_change_next_time": (
            "Use the supports that helped today earlier in the next similar moment."
            if improved
            else "Ask one low-demand follow-up question next time so Gemma4 can learn what helped."
        ),
        "caregiver_notes": "\n".join(notes[:4]),
    }


def _clean_reflection(reflection: dict[str, Any]) -> dict[str, str]:
    fields = [
        "what_happened",
        "what_went_well",
        "what_helped",
        "what_did_not_help",
        "what_should_change_next_time",
        "caregiver_notes",
    ]
    return {field: str(reflection.get(field) or "").strip() for field in fields}


def _reflection_summary_text(reflection: dict[str, str]) -> str:
    parts = [
        reflection.get("what_happened", ""),
        reflection.get("what_went_well", ""),
        reflection.get("what_helped", ""),
        reflection.get("what_did_not_help", ""),
        reflection.get("what_should_change_next_time", ""),
        reflection.get("caregiver_notes", ""),
    ]
    return " ".join(part for part in parts if part).strip() or "Caregiver reflection saved."


def _clean_custom_experience(experience: dict[str, Any]) -> dict[str, str]:
    fields = [
        "title",
        "summary",
        "scenario",
        "friction_points",
        "what_helped",
        "what_did_not_help",
        "learned_about_child",
        "occurred_at",
    ]
    cleaned = {field: str(experience.get(field) or "").strip() for field in fields}
    if not cleaned["title"]:
        cleaned["title"] = cleaned["summary"] or cleaned["scenario"] or "Custom caregiver experience"
    return cleaned


def _custom_experience_summary_text(experience: dict[str, str]) -> str:
    parts = [
        experience.get("summary", ""),
        experience.get("scenario", ""),
        experience.get("friction_points", ""),
        experience.get("what_helped", ""),
        experience.get("what_did_not_help", ""),
        experience.get("learned_about_child", ""),
    ]
    return " ".join(part for part in parts if part).strip() or experience.get("title") or "Custom caregiver experience."


def _parse_custom_experience_time(value: str | None, local_tz: ZoneInfo) -> str:
    if value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=local_tz)
            return parsed.astimezone(timezone.utc).isoformat()
        except ValueError:
            try:
                local_date = date_type.fromisoformat(value[:10])
                return datetime.combine(local_date, time(hour=12), tzinfo=local_tz).astimezone(timezone.utc).isoformat()
            except ValueError:
                pass
    return datetime.now(timezone.utc).isoformat()


def _safe_zoneinfo(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name or DEFAULT_TIMEZONE)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_TIMEZONE)


def _parse_local_date(value: str | None, local_tz: ZoneInfo) -> date_type:
    if value:
        return date_type.fromisoformat(value[:10])
    return datetime.now(local_tz).date()


def _parse_local_range(
    start_value: str | None,
    end_value: str | None,
    local_tz: ZoneInfo,
) -> tuple[date_type, date_type]:
    today = datetime.now(local_tz).date()
    start = date_type.fromisoformat(start_value[:10]) if start_value else today - timedelta(days=6)
    end = date_type.fromisoformat(end_value[:10]) if end_value else today
    if end < start:
        return end, start
    return start, end


def _normalize_source_filter(value: str | None) -> str:
    source = str(value or "all").strip().lower()
    return source if source in REFLECT_SOURCE_TYPES else "all"


def _parse_event_time(value: str) -> datetime:
    normalized = str(value or "").replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _best_signal_score(signals: Any) -> float | None:
    if not isinstance(signals, dict):
        return None
    scores = []
    for value in signals.values():
        if isinstance(value, dict) and value.get("score") is not None:
            try:
                scores.append(float(value["score"]))
            except (TypeError, ValueError):
                continue
    return round(max(scores), 3) if scores else None


def _extract_caregiver_note(event: ExperienceEvent) -> str:
    if event.caregiver_feedback:
        return event.caregiver_feedback
    situation = event.situation
    if isinstance(situation, dict):
        return str(situation.get("caregiver_note") or "").strip()
    return ""


def _event_title(event: ExperienceEvent, label: str, direction: str) -> str:
    if event.source == "caregiver_reflection":
        return "Reflection saved"
    if direction == "improved":
        return f"{label.replace('_', ' ').title()} helped"
    if direction == "dropped":
        return f"{label.replace('_', ' ').title()} may need changing"
    if direction == "no_change":
        return f"{label.replace('_', ' ').title()} stayed about the same"
    return label.replace("_", " ").title()


def _unique(values: Any) -> list[str]:
    seen = set()
    result = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _split_points(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, dict):
        return [str(item).strip() for item in value.values() if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    separators = ["\n", ";"]
    parts = [text]
    for separator in separators:
        if separator in text:
            parts = text.split(separator)
            break
    return [part.strip(" -•\t") for part in parts if part.strip(" -•\t")]


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _to_value_map(key: str, value: Any, *, _depth: int = 1) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if isinstance(value, list):
        if _depth >= 5:
            return {"key": key, "valueString": json.dumps(value, ensure_ascii=True, default=str)}
        return {
            "key": key,
            "valueMap": [
                _to_value_map(str(index), item, _depth=_depth + 1)
                for index, item in enumerate(value)
            ],
        }
    if isinstance(value, dict):
        if _depth >= 5:
            return {"key": key, "valueString": json.dumps(value, ensure_ascii=True, default=str)}
        return {
            "key": key,
            "valueMap": [
                _to_value_map(str(child_key), child_value, _depth=_depth + 1)
                for child_key, child_value in value.items()
            ],
        }
    if isinstance(value, str):
        return {"key": key, "valueString": value}
    if isinstance(value, bool):
        return {"key": key, "valueBoolean": value}
    if isinstance(value, (int, float)):
        return {"key": key, "valueNumber": value}
    return {"key": key, "valueString": ""}
