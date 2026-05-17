"""Backend draft generation for the mobile post-handoff review.

The child handoff already captures useful signals before the real-world memory
write exists: what the child reviewed, which practice choices they selected,
and which tools were packed. This module turns that packet into a caregiver
editable review draft. The deterministic draft is the default local path; a
model-generated draft can be enabled with GEMMA4_PREPARE_REVIEW_USE_MODEL.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.mcp_server.src.services.graph_memory.store import GraphMemoryStore
from app.mcp_server.src.services.profile_episode_store import create_episode

logger = logging.getLogger(__name__)


DEFAULT_PROFILE_ID = "profile_elliot"
DEFAULT_TIMEZONE = "America/New_York"
DEFAULT_CAREGIVER_ID = "local-caregiver"


class HandoffSimulationChoice(BaseModel):
    turn_number: int = 0
    scene: str = ""
    prompt: str = ""
    choice: str = ""
    feedback: str = ""


class ChildHandoffInteractionLog(BaseModel):
    completed_at: str | None = None
    map_step_titles: list[str] = Field(default_factory=list)
    recover_card_titles: list[str] = Field(default_factory=list)
    simulation_choices: list[HandoffSimulationChoice] = Field(default_factory=list)
    packed_tools: list[str] = Field(default_factory=list)


class PrepareReviewDraft(BaseModel):
    scenario: str = ""
    what_went_well: str = ""
    sensory_issues: str = ""
    needs_improvement: str = ""
    what_we_learned: str = ""


class PrepareReviewDraftRequest(BaseModel):
    profile_id: str = DEFAULT_PROFILE_ID
    session_id: str = ""
    scenario: str = ""
    timezone: str = DEFAULT_TIMEZONE
    bundle_outputs: Any | None = None
    interaction_log: ChildHandoffInteractionLog = Field(
        default_factory=ChildHandoffInteractionLog
    )
    client_draft: PrepareReviewDraft | None = None


class PrepareReviewDraftResponse(BaseModel):
    success: bool = True
    profile_id: str = DEFAULT_PROFILE_ID
    session_id: str = ""
    timezone: str = DEFAULT_TIMEZONE
    generated_at: str
    draft_source: str
    draft: PrepareReviewDraft
    interaction_summary: dict[str, Any] = Field(default_factory=dict)


class PrepareReviewSaveRequest(BaseModel):
    profile_id: str = DEFAULT_PROFILE_ID
    session_id: str = ""
    scenario: str = ""
    timezone: str = DEFAULT_TIMEZONE
    occurred_at: str | None = None
    bundle_outputs: Any | None = None
    interaction_log: ChildHandoffInteractionLog = Field(
        default_factory=ChildHandoffInteractionLog
    )
    review: PrepareReviewDraft
    draft_source: str = ""
    location_context: dict[str, Any] = Field(default_factory=dict)


class PrepareReviewSaveResponse(BaseModel):
    success: bool = True
    profile_id: str = DEFAULT_PROFILE_ID
    session_id: str = ""
    event_id: str = ""
    episode_id: str | None = None
    episode_error: str | None = None
    graph_event: dict[str, Any] | None = None
    graph: dict[str, Any] | None = None


async def build_prepare_review_draft(
    request: PrepareReviewDraftRequest,
) -> PrepareReviewDraftResponse:
    fallback = _deterministic_review_draft(request)
    draft = fallback
    draft_source = "deterministic"

    if _env_bool("GEMMA4_PREPARE_REVIEW_USE_MODEL", "false"):
        try:
            generated = await _model_review_draft(request, fallback)
            draft = _merge_drafts(fallback, generated)
            draft_source = "model"
        except Exception:
            logger.exception(
                "model prepare review draft failed; using deterministic fallback profile_id=%s session_id=%s",
                request.profile_id,
                request.session_id,
            )
            draft_source = "deterministic_fallback"

    return PrepareReviewDraftResponse(
        profile_id=request.profile_id or DEFAULT_PROFILE_ID,
        session_id=request.session_id,
        timezone=request.timezone or DEFAULT_TIMEZONE,
        generated_at=datetime.now(timezone.utc).isoformat(),
        draft_source=draft_source,
        draft=draft,
        interaction_summary=_interaction_summary(request),
    )


async def save_prepare_review(
    request: PrepareReviewSaveRequest,
) -> PrepareReviewSaveResponse:
    profile_id = request.profile_id or DEFAULT_PROFILE_ID
    occurred_at = _event_time(request.occurred_at or request.interaction_log.completed_at)
    summary = _review_summary_text(request.review)
    compact_bundles = _compact_jsonable(request.bundle_outputs)
    interaction = request.interaction_log.model_dump(mode="json")
    location = _clean_location_context(request.location_context)
    event_id = f"prepare_review_{uuid4().hex[:12]}"

    situation = {
        "surface": "prepare",
        "review_type": "post_child_handoff",
        "scenario": _clean(request.review.scenario)
        or _clean(request.scenario)
        or "Prepared child handoff",
        "session_id": request.session_id,
        "activity_location": location,
        "completed_at": request.interaction_log.completed_at,
        "summary": _clean(request.review.scenario) or _clean(request.scenario),
    }
    action_taken = {
        "action_type": "other",
        "label": "prepared_child_handoff_review",
        "details": {
            "draft_source": request.draft_source,
            "interaction_log": interaction,
            "review": request.review.model_dump(mode="json"),
            "bundle_outputs": compact_bundles,
        },
    }
    outcome = {
        "direction": "unknown",
        "summary": _join_non_empty(
            [
                request.review.what_went_well,
                request.review.sensory_issues,
                request.review.needs_improvement,
            ],
            separator=" ",
        )
        or "Caregiver saved a post-handoff review for future preparation.",
    }

    graph_result = await GraphMemoryStore().insert_event(
        event_payload={
            "event_id": event_id,
            "occurred_at": occurred_at,
            "situation": situation,
            "signals": {
                "reviewed_supports": {
                    "map_step_titles": request.interaction_log.map_step_titles,
                    "recover_card_titles": request.interaction_log.recover_card_titles,
                    "simulation_choices": interaction.get("simulation_choices", []),
                    "packed_tools": request.interaction_log.packed_tools,
                },
                "sensory_issues": request.review.sensory_issues,
                "needs_improvement": request.review.needs_improvement,
            },
            "location_context": location,
            "action_taken": action_taken,
            "outcome": outcome,
            "caregiver_feedback": summary,
            "next_time_adjustment": _join_non_empty(
                [
                    request.review.what_we_learned,
                    request.review.needs_improvement,
                ],
                separator="\n\n",
            ),
            "source": "prepare_review",
        },
        profile_id=profile_id,
        run_autoschema=_env_bool("GEMMA4_PREPARE_REVIEW_RUN_AUTOSCHEMA", "false"),
    )

    episode = None
    episode_error = None
    try:
        episode = await create_episode(
            profile_id=profile_id,
            caregiver_id=DEFAULT_CAREGIVER_ID,
            title=_episode_title(request.review, request.scenario),
            scenario_type="prepare_handoff_review",
            location_type=_clean(location.get("category") or location.get("source"))
            or None,
            episode_summary=summary,
            episode_json={
                "review": request.review.model_dump(mode="json"),
                "interaction_log": interaction,
                "bundle_outputs": compact_bundles,
                "session_id": request.session_id,
                "draft_source": request.draft_source,
                "location_context": location,
                "graph_event_id": event_id,
                "source": "prepare_review",
            },
            event_date=occurred_at,
        )
    except Exception as exc:
        episode_error = f"{type(exc).__name__}: {exc}"

    return PrepareReviewSaveResponse(
        success=episode_error is None,
        profile_id=profile_id,
        session_id=request.session_id,
        event_id=event_id,
        episode_id=episode.get("episode_id") if isinstance(episode, dict) else None,
        episode_error=episode_error,
        graph_event=graph_result.get("event"),
        graph=graph_result.get("graph"),
    )


def _deterministic_review_draft(
    request: PrepareReviewDraftRequest,
) -> PrepareReviewDraft:
    bundles = _bundle_map(request.bundle_outputs)
    map_steps = _unique(
        request.interaction_log.map_step_titles
        or _extract_map_step_titles(bundles.get("map"))
    )
    recover_cards = _unique(
        request.interaction_log.recover_card_titles
        or _extract_recover_titles(bundles.get("sensory"))
    )
    recover_details = _extract_recover_details(bundles.get("sensory"))
    equip_items = _extract_equip_items(bundles.get("equip"))
    packed_tools = _unique(request.interaction_log.packed_tools)
    choices = request.interaction_log.simulation_choices
    missed_tools = [item for item in equip_items if item not in set(packed_tools)]

    client = request.client_draft or PrepareReviewDraft()
    scenario = (
        _clean(request.scenario)
        or _clean(client.scenario)
        or _bundle_text(bundles.get("map"), "summary")
        or "Prepared child handoff"
    )

    return PrepareReviewDraft(
        scenario=scenario,
        what_went_well=_join_non_empty(
            [
                "The child completed the handoff through What to Expect, Recover, Practice, and Tools.",
                _count_sentence(
                    len(map_steps),
                    "what-to-expect step",
                    "what-to-expect steps",
                    "reviewed",
                ),
                _count_sentence(
                    len(choices),
                    "practice choice",
                    "practice choices",
                    "made",
                ),
                f"Packed tools: {', '.join(packed_tools)}." if packed_tools else "",
            ]
        ),
        sensory_issues=_join_non_empty(
            [
                _format_recover_details(recover_details or recover_cards),
            ]
        )
        or "No sensory issues were recorded yet. Add what happened during the real activity.",
        needs_improvement=_join_non_empty(
            [
                (
                    f"Make these tools easier to find next time: {', '.join(missed_tools)}."
                    if missed_tools
                    else ""
                ),
                "After the real activity, add what was still confusing, too loud, too crowded, or hard to recover from.",
                "Check whether the calmer-place options were realistic, open, and reachable.",
            ]
        ),
        what_we_learned=_join_non_empty(
            [
                _format_choice_learning(choices),
                (
                    f"The what-to-expect plan broke the situation into {len(map_steps)} steps."
                    if map_steps
                    else ""
                ),
                (
                    f"The recovery plan offered {len(recover_cards or recover_details)} supports or calmer-place options."
                    if (recover_cards or recover_details)
                    else ""
                ),
                "Caregiver should edit this after the real activity with what actually helped.",
            ]
        ),
    )


async def _model_review_draft(
    request: PrepareReviewDraftRequest,
    fallback: PrepareReviewDraft,
) -> PrepareReviewDraft:
    def _run() -> PrepareReviewDraft:
        from google import genai
        from google.genai import types

        model = os.getenv(
            "GEMMA4_PREPARE_REVIEW_MODEL",
            os.getenv("GEMMA4_REFLECT_MODEL", "gemini-2.5-flash"),
        )
        client = genai.Client()
        prompt = {
            "task": (
                "Draft a concise caregiver-editable post-handoff review for an "
                "autistic child support app. Do not diagnose. Use calm plain "
                "language. Return JSON only."
            ),
            "profile_id": request.profile_id,
            "scenario": request.scenario,
            "interaction_log": request.interaction_log.model_dump(mode="json"),
            "bundle_outputs": _compact_jsonable(request.bundle_outputs),
            "fallback_draft": fallback.model_dump(mode="json"),
            "required_fields": [
                "scenario",
                "what_went_well",
                "sensory_issues",
                "needs_improvement",
                "what_we_learned",
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
            return PrepareReviewDraft()
        return PrepareReviewDraft(**_clean_draft_dict(parsed))

    return await asyncio.to_thread(_run)


def _merge_drafts(
    fallback: PrepareReviewDraft,
    generated: PrepareReviewDraft,
) -> PrepareReviewDraft:
    return PrepareReviewDraft(
        scenario=_clean(generated.scenario) or fallback.scenario,
        what_went_well=_clean(generated.what_went_well) or fallback.what_went_well,
        sensory_issues=_clean(generated.sensory_issues) or fallback.sensory_issues,
        needs_improvement=_clean(generated.needs_improvement)
        or fallback.needs_improvement,
        what_we_learned=_clean(generated.what_we_learned) or fallback.what_we_learned,
    )


def _interaction_summary(request: PrepareReviewDraftRequest) -> dict[str, Any]:
    log = request.interaction_log
    return {
        "completed_at": log.completed_at,
        "map_steps_reviewed": len(log.map_step_titles),
        "recover_cards_reviewed": len(log.recover_card_titles),
        "practice_choices_made": len(log.simulation_choices),
        "packed_tools_count": len(log.packed_tools),
    }


def _review_summary_text(review: PrepareReviewDraft) -> str:
    return _join_non_empty(
        [
            f"Scenario: {review.scenario}" if review.scenario else "",
            f"What went well: {review.what_went_well}"
            if review.what_went_well
            else "",
            f"Sensory issues: {review.sensory_issues}"
            if review.sensory_issues
            else "",
            f"Needs improvement: {review.needs_improvement}"
            if review.needs_improvement
            else "",
            f"What we learned: {review.what_we_learned}"
            if review.what_we_learned
            else "",
        ]
    ) or "Caregiver saved a post-handoff review."


def _episode_title(review: PrepareReviewDraft, fallback_scenario: str) -> str:
    source = _clean(review.scenario) or _clean(fallback_scenario) or "child handoff"
    return f"Prepare review: {source[:72]}"


def _event_time(value: str | None) -> str:
    if value:
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat()
        except ValueError:
            pass
    return datetime.now(timezone.utc).isoformat()


def _clean_location_context(value: dict[str, Any]) -> dict[str, Any]:
    location = {
        key: child
        for key, child in (value or {}).items()
        if child is not None and str(child).strip()
    }
    return location


def _bundle_map(bundle_outputs: Any) -> dict[str, Any]:
    data = _parse_jsonish(bundle_outputs)
    bundles: dict[str, Any] = {}
    if isinstance(data, list):
        for item in data:
            key = _bundle_key(item)
            if key:
                item_map = _as_map(item)
                bundles[key] = item_map.get("content", item)
    elif isinstance(data, dict):
        for key in ("map", "sensory", "simulate", "equip"):
            direct = data.get(key) or data.get(key.upper())
            if direct is not None:
                direct_map = _as_map(direct)
                bundles[key] = direct_map.get("content", direct)
        for item in data.values():
            key = _bundle_key(item)
            if key:
                item_map = _as_map(item)
                bundles[key] = item_map.get("content", item)
    return bundles


def _bundle_key(value: Any) -> str:
    item = _as_map(value)
    raw = item.get("bundle") or item.get("id") or item.get("label") or ""
    key = str(raw).strip().lower()
    return key if key in {"map", "sensory", "simulate", "equip"} else ""


def _extract_map_step_titles(map_bundle: Any) -> list[str]:
    return [
        _first_text(step, ["title", "step_title", "step_detail", "detail", "summary"])
        for step in _as_list(_as_map(map_bundle).get("steps"))
    ]


def _extract_recover_titles(sensory_bundle: Any) -> list[str]:
    bundle = _as_map(sensory_bundle)
    titles = []
    for key in ("recovery_tools", "supports", "calming_places", "contact_options"):
        for item in _as_list(bundle.get(key)):
            titles.append(
                _first_text(
                    item,
                    [
                        "support_name",
                        "item_name",
                        "place_name",
                        "option_name",
                        "title",
                        "name",
                        "label",
                        "sensory_risk",
                    ],
                )
            )
    titles.extend(_clean(_text_from_value(item)) for item in _as_list(bundle.get("warning_points")))
    return titles


def _extract_recover_details(sensory_bundle: Any) -> list[str]:
    bundle = _as_map(sensory_bundle)
    details = []
    for item in _as_list(bundle.get("recovery_tools")) + _as_list(bundle.get("supports")):
        item_map = _as_map(item)
        name = _first_text(item_map, ["support_name", "item_name", "title"])
        body = _first_text(
            item_map,
            ["why_it_helps", "when_to_use", "support_timing", "child_specific_reason"],
        )
        script = _first_text(item_map, ["child_script"])
        details.append(
            _join_non_empty(
                [
                    name,
                    body,
                    f'Script: "{script}"' if script else "",
                ],
                separator=" - ",
            )
        )

    for item in _as_list(bundle.get("calming_places")):
        item_map = _as_map(item)
        name = _first_text(item_map, ["place_name", "name", "label"])
        category = _first_text(item_map, ["category"])
        distance = _clean(_text_from_value(item_map.get("distance_m")))
        why = _first_text(item_map, ["why_it_may_help", "why"])
        details.append(
            _join_non_empty(
                [
                    name or "Calmer place nearby",
                    category,
                    f"about {distance} m away" if distance else "",
                    why,
                ],
                separator=" - ",
            )
        )

    for item in _as_list(bundle.get("contact_options")):
        item_map = _as_map(item)
        details.append(
            _join_non_empty(
                [
                    _first_text(item_map, ["option_name", "title"]) or "Ask for help",
                    _first_text(item_map, ["when_to_use"]),
                    _first_text(item_map, ["caregiver_action", "child_script"]),
                ],
                separator=" - ",
            )
        )

    return _unique(details)


def _extract_equip_items(equip_bundle: Any) -> list[str]:
    bundle = _as_map(equip_bundle)
    raw_items = (
        _as_list(bundle.get("pack_items"))
        + _as_list(bundle.get("prepare_before_leaving"))
        + _as_list(bundle.get("backup_items"))
    )
    return _unique(
        _first_text(item, ["item_name", "title", "label"]) or _text_from_value(item)
        for item in raw_items
    )


def _format_recover_details(values: list[str]) -> str:
    values = _unique(values)
    if not values:
        return ""
    return "\n\n".join(values[:6])


def _format_choice_learning(choices: list[HandoffSimulationChoice]) -> str:
    notes = []
    for choice in choices[:6]:
        scene = _clean(choice.scene) or f"Practice {choice.turn_number}"
        selected = _clean(choice.choice)
        feedback = _clean(choice.feedback)
        if not selected:
            continue
        notes.append(
            _join_non_empty(
                [
                    f'Practice {choice.turn_number}: in "{scene}", the child chose "{selected}".',
                    feedback,
                ],
                separator=" ",
            )
        )
    return "\n\n".join(notes)


def _count_sentence(count: int, singular: str, plural: str, verb: str) -> str:
    if count <= 0:
        return ""
    label = singular if count == 1 else plural
    return f"{count} {label} {verb}."


def _clean_draft_dict(value: dict[str, Any]) -> dict[str, str]:
    fields = [
        "scenario",
        "what_went_well",
        "sensory_issues",
        "needs_improvement",
        "what_we_learned",
    ]
    return {field: _clean(value.get(field)) for field in fields}


def _compact_jsonable(value: Any) -> Any:
    text = json.dumps(value, ensure_ascii=True, default=str)
    if len(text) <= 12000:
        return _parse_jsonish(value)
    return {"truncated_json": text[:12000]}


def _first_text(value: Any, keys: list[str]) -> str:
    data = _as_map(value)
    for key in keys:
        text = _clean(_text_from_value(data.get(key)))
        if text:
            return text
    return ""


def _bundle_text(value: Any, key: str) -> str:
    return _clean(_text_from_value(_as_map(value).get(key)))


def _join_non_empty(values: list[str], *, separator: str = "\n\n") -> str:
    return separator.join(_clean(value) for value in values if _clean(value))


def _unique(values: Any) -> list[str]:
    seen = set()
    result = []
    for value in values:
        text = _clean(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _clean(value: Any) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _text_from_value(value: Any) -> str:
    plain = _parse_jsonish(value)
    if isinstance(plain, str):
        return plain.strip()
    if isinstance(plain, (int, float, bool)):
        return str(plain)
    if isinstance(plain, list):
        return ", ".join(_text_from_value(item) for item in plain if _text_from_value(item))
    if isinstance(plain, dict):
        return (
            _text_from_value(plain.get("label"))
            or _text_from_value(plain.get("title"))
            or _text_from_value(plain.get("summary"))
            or _text_from_value(plain.get("body"))
            or _text_from_value(plain.get("item_name"))
        )
    return ""


def _as_map(value: Any) -> dict[str, Any]:
    plain = _parse_jsonish(value)
    return dict(plain) if isinstance(plain, dict) else {}


def _as_list(value: Any) -> list[Any]:
    plain = _parse_jsonish(value)
    return plain if isinstance(plain, list) else []


def _parse_jsonish(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    trimmed = value.strip()
    if not trimmed or trimmed[0] not in "[{":
        return value
    try:
        return json.loads(trimmed)
    except json.JSONDecodeError:
        return value


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}
