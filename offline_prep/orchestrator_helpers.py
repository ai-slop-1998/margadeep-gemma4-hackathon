"""State helpers for the offline-support orchestrator."""
from __future__ import annotations

from typing import Any

from google.adk.agents.invocation_context import InvocationContext

from app.agents.shared.config import config
from app.agents.shared.stage_responses import coerce_plain_data


def _state_int(ctx: InvocationContext, key: str, default: int = 0) -> int:
    value = ctx.session.state.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        ctx.session.state[key] = default
        return default


def _positive_config_int(value: Any, default: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(parsed, 0)


def normalize_response_mode(value: Any) -> str:
    mode = str(value or config.default_response_mode or "text").strip().lower()
    return mode if mode in {"text", "a2ui"} else "text"


def pop_latest_user_action(ctx: InvocationContext) -> dict[str, Any] | None:
    action = ctx.session.state.get("latest_user_action")
    if action:
        ctx.session.state["latest_user_action"] = None
    if hasattr(action, "model_dump"):
        action = action.model_dump()
    return action if isinstance(action, dict) else None


def action_context(action: dict[str, Any]) -> dict[str, Any]:
    context = action.get("context") or {}
    if hasattr(context, "model_dump"):
        context = context.model_dump()
    return context if isinstance(context, dict) else {}


def apply_event_state_delta(ctx: InvocationContext, event: Any) -> None:
    actions = getattr(event, "actions", None)
    if actions is None:
        return

    state_delta = getattr(actions, "state_delta", None)
    if not isinstance(state_delta, dict):
        return

    for key, value in state_delta.items():
        ctx.session.state[key] = coerce_plain_data(value)


def render_answers_as_text(answers: dict[str, Any]) -> str:
    lines = ["Clarification answers:"]
    for key, value in answers.items():
        rendered: Any = value
        if isinstance(value, list):
            rendered = ", ".join(str(item) for item in value)
        elif isinstance(value, dict):
            rendered = ", ".join(
                f"{child_key}={child_value}" for child_key, child_value in value.items()
            )
        lines.append(f"- {key}: {rendered}")
    return "\n".join(lines)


def append_clarification_answers(ctx: InvocationContext, answers: dict[str, Any]) -> None:
    existing = ctx.session.state.get("clarification_answers")
    if not isinstance(existing, list):
        existing = []
    existing.append(coerce_plain_data(answers))
    ctx.session.state["clarification_answers"] = existing


def merge_dictish(base: Any, patch: Any) -> dict[str, Any]:
    base_data = coerce_plain_data(base)
    patch_data = coerce_plain_data(patch)
    if not isinstance(base_data, dict):
        base_data = {}
    if not isinstance(patch_data, dict):
        patch_data = {}
    return {**base_data, **patch_data}


def extract_reviewed_plan_from_action(
    ctx: InvocationContext,
    action: dict[str, Any],
) -> dict[str, Any]:
    context = action_context(action)
    explicit_plan = context.get("reviewed_support_plan")
    if explicit_plan is not None:
        return coerce_plain_data(explicit_plan)
    return merge_dictish(
        ctx.session.state.get("reviewed_support_plan")
        or ctx.session.state.get("draft_support_plan"),
        context,
    )


def handle_structured_action(ctx: InvocationContext, action: dict[str, Any]) -> None:
    name = str(action.get("name", "") or "")

    if name == "submit_clarification_form":
        answers = action_context(action)
        append_clarification_answers(ctx, answers)
        ctx.session.state["latest_user_message"] = render_answers_as_text(answers)
        ctx.session.state["clarification_waiting_for_response"] = True
        return

    if name == "save_draft_plan":
        ctx.session.state["reviewed_support_plan"] = extract_reviewed_plan_from_action(
            ctx, action
        )
        ctx.session.state["plan_review_status"] = "pending"
        ctx.session.state["plan_review_required"] = True
        ctx.session.state["plan_review_waiting_for_response"] = False
        increment_plan_review_turns(ctx)
        enforce_plan_review_turn_limit(ctx)
        return

    if name == "approve_draft_plan":
        reviewed_plan = extract_reviewed_plan_from_action(ctx, action)
        ctx.session.state["reviewed_support_plan"] = reviewed_plan
        ctx.session.state["approved_support_plan"] = reviewed_plan
        ctx.session.state["plan_review_status"] = "approved"
        ctx.session.state["plan_review_required"] = False
        ctx.session.state["plan_review_waiting_for_response"] = False


def ensure_clarification_state(ctx: InvocationContext) -> None:
    """Initialize planner-ready state when clarification is disabled."""

    if config.enable_clarification:
        return
    if ctx.session.state.get("clarified") is True:
        return
    if ctx.session.state.get("draft_support_plan") is not None:
        return
    ctx.session.state["clarified"] = True
    if not ctx.session.state.get("clarified_request"):
        ctx.session.state["clarified_request"] = build_fallback_clarified_request(ctx)


def plan_review_turns(ctx: InvocationContext) -> int:
    return _state_int(ctx, "plan_review_turns")


def increment_plan_review_turns(ctx: InvocationContext) -> int:
    turns = plan_review_turns(ctx) + 1
    ctx.session.state["plan_review_turns"] = turns
    return turns


def enforce_plan_review_turn_limit(ctx: InvocationContext) -> bool:
    """Approve the latest reviewed plan when review has reached its turn budget."""

    if not config.enable_plan_review:
        return False
    if ctx.session.state.get("approved_support_plan") is not None:
        return False
    if ctx.session.state.get("draft_support_plan") is None:
        return False
    max_turns = _positive_config_int(config.plan_review_max_turns)
    if max_turns == 0 or plan_review_turns(ctx) < max_turns:
        return False

    reviewed_plan = (
        ctx.session.state.get("reviewed_support_plan")
        or ctx.session.state.get("draft_support_plan")
    )
    ctx.session.state["reviewed_support_plan"] = reviewed_plan
    ctx.session.state["approved_support_plan"] = reviewed_plan
    ctx.session.state["plan_review_status"] = "approved_after_max_turns"
    ctx.session.state["plan_review_required"] = False
    ctx.session.state["plan_review_waiting_for_response"] = False
    return True


def build_fallback_clarified_request(ctx: InvocationContext) -> dict[str, Any]:
    scenario = str(ctx.session.state.get("scenario_intake", "") or "")
    answer_notes: list[str] = []
    for answer_round in ctx.session.state.get("clarification_answers") or []:
        if isinstance(answer_round, dict):
            answer_notes.extend(
                f"{key}: {value}" for key, value in answer_round.items()
            )
    return {
        "scenario_summary": scenario,
        "timing_context": None,
        "location_context": None,
        "caregiver_goals": [],
        "known_child_needs": answer_notes,
        "open_questions": [],
        "is_ready_for_planning": bool(scenario),
    }


def should_run_clarifier(ctx: InvocationContext) -> bool:
    if not config.enable_clarification:
        return False
    if ctx.session.state.get("clarified") is True:
        return False
    if ctx.session.state.get("draft_support_plan") is not None:
        return False
    if ctx.session.state.get("clarification_waiting_for_response"):
        return True
    rounds = _state_int(ctx, "clarification_rounds")
    return rounds < _positive_config_int(config.clarification_max_rounds)


def clarification_needs_user_response(ctx: InvocationContext) -> bool:
    if ctx.session.state.get("clarified") is True:
        return False
    question_set = coerce_plain_data(ctx.session.state.get("clarification_questions")) or {}
    if not isinstance(question_set, dict):
        return False
    if question_set.get("is_enough") is True:
        return False
    questions = question_set.get("question_specs") or question_set.get(
        "clarifying_questions"
    ) or []
    return bool(questions)


def clarification_stage_decided(ctx: InvocationContext) -> bool:
    question_set = coerce_plain_data(ctx.session.state.get("clarification_questions")) or {}
    return isinstance(question_set, dict) and isinstance(question_set.get("is_enough"), bool)


def can_emit_clarification_round(ctx: InvocationContext) -> bool:
    rounds = _state_int(ctx, "clarification_rounds")
    return rounds < _positive_config_int(config.clarification_max_rounds)


def increment_clarification_rounds(ctx: InvocationContext) -> int:
    rounds = _state_int(ctx, "clarification_rounds") + 1
    ctx.session.state["clarification_rounds"] = rounds
    return rounds


def mark_clarified_if_ready_or_maxed(ctx: InvocationContext) -> None:
    if ctx.session.state.get("clarified") is True:
        if not ctx.session.state.get("clarified_request"):
            ctx.session.state["clarified_request"] = build_fallback_clarified_request(ctx)
        return

    question_set = coerce_plain_data(ctx.session.state.get("clarification_questions")) or {}
    if isinstance(question_set, dict) and question_set.get("is_enough") is True:
        ctx.session.state["clarified"] = True

    if not can_emit_clarification_round(ctx):
        ctx.session.state["clarified"] = True

    if ctx.session.state.get("clarified") is True and not ctx.session.state.get(
        "clarified_request"
    ):
        ctx.session.state["clarified_request"] = build_fallback_clarified_request(ctx)


def should_run_planner(ctx: InvocationContext) -> bool:
    return (
        ctx.session.state.get("clarified") is True
        and ctx.session.state.get("draft_support_plan") is None
    )


def initialize_reviewed_support_plan(ctx: InvocationContext) -> None:
    draft_plan = ctx.session.state.get("draft_support_plan")
    if draft_plan is None:
        return
    if ctx.session.state.get("reviewed_support_plan") is None:
        ctx.session.state["reviewed_support_plan"] = draft_plan
    if not ctx.session.state.get("plan_review_status"):
        ctx.session.state["plan_review_status"] = "pending"
    ctx.session.state["plan_review_required"] = (
        ctx.session.state.get("approved_support_plan") is None
    )
    if not config.enable_plan_review and ctx.session.state.get("approved_support_plan") is None:
        ctx.session.state["approved_support_plan"] = draft_plan
        ctx.session.state["plan_review_status"] = "approved"
        ctx.session.state["plan_review_required"] = False


def should_run_text_plan_review(
    ctx: InvocationContext,
    action: dict[str, Any] | None,
) -> bool:
    return (
        action is None
        and config.enable_plan_review
        and ctx.session.state.get("response_mode") == "text"
        and ctx.session.state.get("plan_review_waiting_for_response") is True
        and ctx.session.state.get("draft_support_plan") is not None
        and ctx.session.state.get("approved_support_plan") is None
    )


def should_show_plan_review(ctx: InvocationContext) -> bool:
    return (
        config.enable_plan_review
        and ctx.session.state.get("draft_support_plan") is not None
        and ctx.session.state.get("approved_support_plan") is None
    )


def should_run_research(ctx: InvocationContext) -> bool:
    return (
        config.enable_research_after_planning
        and ctx.session.state.get("approved_support_plan") is not None
        and ctx.session.state.get("bundle_outputs") is None
    )
