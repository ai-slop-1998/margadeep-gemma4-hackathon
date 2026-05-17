"""ADK root agent for stateless online-support decisions."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from google.adk.agents import LlmAgent
from google.genai import types

_backend_dir = str(Path(__file__).resolve().parents[3])
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")

if default_gcp_project := os.getenv("GEMMA4_DEFAULT_GCP_PROJECT"):
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", default_gcp_project)

from app.agents.online_support.config import config
from app.agents.online_support.models import OnlineSupportDecision
from app.agents.online_support.prompts import ONLINE_SUPPORT_AGENT_PROMPT
from app.agents.online_support.tools import (
    calming_place_lookup_tool,
    knowledge_graph_context_tool,
    past_experience_lookup_tool,
    profile_context_tool,
)
from app.agents.shared.model_provider import resolve_adk_model


def build_online_support_agent() -> LlmAgent:
    return LlmAgent(
        name="online_support_agent",
        model=resolve_adk_model(config.model),
        description=(
            "Chooses one live support card using child profile, memory, "
            "signals, and location context."
        ),
        instruction=ONLINE_SUPPORT_AGENT_PROMPT,
        tools=[
            profile_context_tool,
            past_experience_lookup_tool,
            knowledge_graph_context_tool,
            calming_place_lookup_tool,
        ],
        output_schema=OnlineSupportDecision,
        output_key="online_support_decision",
        generate_content_config=types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json",
        ),
    )


root_agent = build_online_support_agent()
