"""Offline-support configuration exports.

The config object still lives in ``app.agents.shared.config`` because several
offline sub-agent builders import it directly. New offline package callers can
import from here without reaching through ``shared``.
"""
from __future__ import annotations

from app.agents.shared.config import DEFAULT_MODEL, ResearchConfig, config

__all__ = ["DEFAULT_MODEL", "ResearchConfig", "config"]
