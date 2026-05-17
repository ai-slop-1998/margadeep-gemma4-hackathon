"""Offline support orchestrator for intake, planning, and scenario research."""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any, Iterable

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event

from app.agents.shared.config import config
from app.agents.shared.stage_responses import build_stage_response
from app.agents.shared.sub_agents.clarifying import build_offline_support_clarifier
from app.agents.offline_prep.orchestrator_helpers import (
    apply_event_state_delta,
    can_emit_clarification_round,
    clarification_needs_user_response,
    clarification_stage_decided,
    ensure_clarification_state,
    enforce_plan_review_turn_limit,
    handle_structured_action,
    increment_clarification_rounds,
    initialize_reviewed_support_plan,
    increment_plan_review_turns,
    mark_clarified_if_ready_or_maxed,
    normalize_response_mode,
    pop_latest_user_action,
    should_run_clarifier,
    should_run_planner,
    should_run_research,
    should_run_text_plan_review,
    should_show_plan_review,
)
from app.agents.shared.sub_agents.planner import build_draft_support_planner
from app.agents.shared.sub_agents.plan_review import build_plan_review_agent
from app.agents.shared.sub_agents.research_pipeline import (
    build_scenario_research_orchestrator,
)

logger = logging.getLogger(__name__)


def _iter_user_texts_from_events(events: Any) -> Iterable[str]:
    """Yield user text parts from an ADK session event list."""

    if not isinstance(events, list):
        return

    for ev in events:
        try:
            content = getattr(ev, "content", None)
            author = getattr(ev, "author", None)
            role = getattr(content, "role", None)

            if author != "user" and role != "user":
                continue

            parts = getattr(content, "parts", None)
            if not isinstance(parts, list):
                continue

            for part in parts:
                text = getattr(part, "text", None)
                if isinstance(text, str) and text.strip():
                    yield text.strip()
        except Exception:
            continue


def extract_first_user_text_from_events(events: Any) -> str | None:
    """Return the first user message text found in an ADK session event list."""

    return next(iter(_iter_user_texts_from_events(events)), None)


def extract_latest_user_text_from_events(events: Any) -> str | None:
    """Return the latest user message text found in an ADK session event list."""

    if not isinstance(events, list) or not events:
        return None

    for text in _iter_user_texts_from_events(list(reversed(events))):
        return text
    return None


class OfflineSupportOrchestrator(BaseAgent):
    """Runs the offline-support preparation stages in sequence."""

    def __init__(
        self,
        name: str,
        offline_support_clarifier_agent,
        draft_support_planner_agent,
        plan_review_agent,
        scenario_research_orchestrator_agent,
    ):
        super().__init__(
            name=name,
            sub_agents=[
                offline_support_clarifier_agent,
                draft_support_planner_agent,
                plan_review_agent,
                scenario_research_orchestrator_agent,
            ],
        )
        # Pydantic-backed ADK agents do not always allow direct attribute assignment.
        try:
            self.offline_support_clarifier_agent = offline_support_clarifier_agent
            self.draft_support_planner_agent = draft_support_planner_agent
            self.plan_review_agent = plan_review_agent
            self.scenario_research_orchestrator_agent = scenario_research_orchestrator_agent
        except Exception:
            object.__setattr__(
                self, "offline_support_clarifier_agent", offline_support_clarifier_agent
            )
            object.__setattr__(self, "draft_support_planner_agent", draft_support_planner_agent)
            object.__setattr__(self, "plan_review_agent", plan_review_agent)
            object.__setattr__(
                self,
                "scenario_research_orchestrator_agent",
                scenario_research_orchestrator_agent,
            )

    async def _run_plan_review(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        async for event in self.plan_review_agent.run_async(ctx):
            apply_event_state_delta(ctx, event)
            yield event

        review_result = ctx.session.state.get("plan_review_result")
        if hasattr(review_result, "model_dump"):
            review_result = review_result.model_dump()

        if not isinstance(review_result, dict):
            return

        reviewed_plan = review_result.get("reviewed_support_plan")
        review_status = str(review_result.get("review_status", "pending") or "pending")

        if reviewed_plan is not None:
            ctx.session.state["reviewed_support_plan"] = reviewed_plan

        ctx.session.state["plan_review_status"] = review_status
        ctx.session.state["plan_review_required"] = review_status != "approved"
        turns = increment_plan_review_turns(ctx)

        if review_status == "approved" and reviewed_plan is not None:
            ctx.session.state["approved_support_plan"] = reviewed_plan
        elif enforce_plan_review_turn_limit(ctx):
            logger.info(
                "Plan review max turns reached; approving latest reviewed plan turns=%s max=%s",
                turns,
                config.plan_review_max_turns,
            )

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        logger.info("Starting OfflineSupportOrchestrator run_async")

        initial_user_question = ctx.session.state.get("scenario_intake")
        if not initial_user_question:
            initial_user_question = extract_first_user_text_from_events(ctx.session.events)
            if initial_user_question:
                ctx.session.state["scenario_intake"] = initial_user_question
        logger.info("Initial user question: %s", initial_user_question)

        latest_user_message = extract_latest_user_text_from_events(ctx.session.events)
        if latest_user_message:
            ctx.session.state["latest_user_message"] = latest_user_message
        ctx.session.state["response_mode"] = normalize_response_mode(
            ctx.session.state.get("response_mode")
        )

        latest_action = pop_latest_user_action(ctx)
        if latest_action:
            handle_structured_action(ctx, latest_action)
        ensure_clarification_state(ctx)

        if should_run_text_plan_review(ctx, latest_action):
            async for event in self._run_plan_review(ctx):
                yield event

            if ctx.session.state.get("approved_support_plan") is None:
                yield build_stage_response(
                    ctx,
                    stage="draft_plan_review",
                    payload=ctx.session.state.get("reviewed_support_plan")
                    or ctx.session.state.get("draft_support_plan"),
                    author=self.name,
                    invocation_id=getattr(ctx, "invocation_id", ""),
                )
                ctx.session.state["plan_review_waiting_for_response"] = True
                return
            logger.info("Text plan review resolved; continuing to research if enabled")

        if should_run_clarifier(ctx):
            was_waiting_for_response = bool(
                ctx.session.state.get("clarification_waiting_for_response")
            )
            ctx.session.state["clarification_waiting_for_response"] = False

            async for _event in self.offline_support_clarifier_agent.run_async(ctx):
                # Let the clarifier update session state. User-facing output is
                # emitted below as a deterministic stage response.
                apply_event_state_delta(ctx, _event)
                if clarification_stage_decided(ctx):
                    logger.info("Clarification stage decision captured; pausing clarifier agent")
                    break
                continue

            if clarification_needs_user_response(ctx):
                if can_emit_clarification_round(ctx):
                    increment_clarification_rounds(ctx)
                    ctx.session.state["clarification_waiting_for_response"] = True
                    yield build_stage_response(
                        ctx,
                        stage="clarification",
                        payload=ctx.session.state.get("clarification_questions"),
                        author=self.name,
                        invocation_id=getattr(ctx, "invocation_id", ""),
                    )
                    return
                logger.info(
                    "Clarification max rounds reached after waiting=%s; continuing with fallback.",
                    was_waiting_for_response,
                )

            mark_clarified_if_ready_or_maxed(ctx)

        if should_run_planner(ctx):
            if ctx.session.state.get("clarified_request") and not ctx.session.state.get(
                "clarifying_questions"
            ):
                ctx.session.state["clarifying_questions"] = ctx.session.state["clarified_request"]
            elif ctx.session.state.get("scenario_intake") and not ctx.session.state.get(
                "clarifying_questions"
            ):
                ctx.session.state["clarifying_questions"] = ctx.session.state[
                    "scenario_intake"
                ]

            logger.info(
                "Planner starting with clarified=%s clarification_rounds=%s",
                ctx.session.state.get("clarified"),
                ctx.session.state.get("clarification_rounds"),
            )
            async for _event in self.draft_support_planner_agent.run_async(ctx):
                apply_event_state_delta(ctx, _event)

            draft_support_plan = ctx.session.state.get("draft_support_plan")
            logger.info("Planner completed. draft_support_plan=%s", draft_support_plan)
            initialize_reviewed_support_plan(ctx)

        initialize_reviewed_support_plan(ctx)
        if enforce_plan_review_turn_limit(ctx):
            logger.info(
                "Plan review turn budget already exhausted; continuing with reviewed plan"
            )

        if should_show_plan_review(ctx):
            yield build_stage_response(
                ctx,
                stage="draft_plan_review",
                payload=ctx.session.state.get("reviewed_support_plan")
                or ctx.session.state.get("draft_support_plan"),
                author=self.name,
                invocation_id=getattr(ctx, "invocation_id", ""),
            )
            ctx.session.state["plan_review_waiting_for_response"] = True
            return

        if should_run_research(ctx):
            async for event in self.scenario_research_orchestrator_agent.run_async(ctx):
                yield event
            ctx.session.state["offline_support_flow_complete"] = True
            return


def build_offline_support_orchestrator() -> OfflineSupportOrchestrator:
    offline_support_clarifier_agent = build_offline_support_clarifier()
    draft_support_planner_agent = build_draft_support_planner()
    plan_review_agent = build_plan_review_agent()
    scenario_research_orchestrator_agent = build_scenario_research_orchestrator()

    return OfflineSupportOrchestrator(
        name="offline_support_orchestrator",
        offline_support_clarifier_agent=offline_support_clarifier_agent,
        draft_support_planner_agent=draft_support_planner_agent,
        plan_review_agent=plan_review_agent,
        scenario_research_orchestrator_agent=scenario_research_orchestrator_agent,
    )
