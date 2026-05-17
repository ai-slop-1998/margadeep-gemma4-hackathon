"""ADK tool wrappers for online support."""
from __future__ import annotations

from typing import Any

from app.mcp_server.src.tool_adapters.calming_place_lookup import (
    calming_place_lookup,
)
from app.mcp_server.src.tool_adapters.knowledge_graph_context import (
    knowledge_graph_context,
)
from app.mcp_server.src.tool_adapters.past_experience_lookup import (
    past_experience_lookup,
)
from app.mcp_server.src.tool_adapters.profile_context import profile_context


async def profile_context_tool(
    profile_id: str,
    correlation_id: str = "",
) -> dict[str, Any]:
    """Read the child profile context for live support."""
    return await profile_context(profile_id=profile_id, correlation_id=correlation_id)


async def past_experience_lookup_tool(
    profile_id: str,
    scenario_hint: str = "",
    correlation_id: str = "",
    top_k: int = 3,
) -> dict[str, Any]:
    """Retrieve similar prior child-support episodes."""
    return await past_experience_lookup(
        profile_id=profile_id,
        scenario_hint=scenario_hint,
        correlation_id=correlation_id,
        top_k=top_k,
    )


async def knowledge_graph_context_tool(
    profile_id: str,
    query: str,
    signals: dict[str, Any] | None = None,
    candidate_actions: list[str] | None = None,
    correlation_id: str = "",
    top_k: int = 3,
) -> dict[str, Any]:
    """Retrieve action-outcome graph memory for the current support moment."""
    return await knowledge_graph_context(
        profile_id=profile_id,
        query=query,
        signals=signals,
        candidate_actions=candidate_actions,
        correlation_id=correlation_id,
        top_k=top_k,
    )


async def calming_place_lookup_tool(
    latitude: float,
    longitude: float,
    radius_m: int = 700,
    max_results: int = 3,
    sensory_need: str = "quiet",
    correlation_id: str = "",
) -> dict[str, Any]:
    """Find nearby calmer place candidates for caregiver-confirmed movement."""
    return await calming_place_lookup(
        latitude=latitude,
        longitude=longitude,
        radius_m=radius_m,
        max_results=max_results,
        sensory_need=sensory_need,
        correlation_id=correlation_id,
    )
