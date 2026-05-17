"""Offline support root agent entry point."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure apps/backend is on sys.path so `app.agents.shared.*` imports resolve
_backend_dir = str(Path(__file__).resolve().parents[3])
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")

if default_gcp_project := os.getenv("GEMMA4_DEFAULT_GCP_PROJECT"):
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", default_gcp_project)

from app.agents.offline_prep.orchestrator import build_offline_support_orchestrator

root_agent = build_offline_support_orchestrator()
