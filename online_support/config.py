"""Configuration for the online-support agent POC."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


DEFAULT_MODEL = "gemini-2.5-flash"


def _env_bool(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _model_env(name: str) -> str:
    return os.getenv(
        name,
        os.getenv("GEMMA4_VERTEX_EVAL_MODEL", DEFAULT_MODEL),
    )


@dataclass(frozen=True)
class OnlineSupportConfig:
    model: str = field(
        default_factory=lambda: _model_env("GEMMA4_ONLINE_SUPPORT_MODEL")
    )
    timeout_s: float = field(
        default_factory=lambda: float(
            os.getenv("GEMMA4_ONLINE_SUPPORT_TIMEOUT_S", "20")
        )
    )
    use_model: bool = field(
        default_factory=lambda: _env_bool("GEMMA4_ONLINE_SUPPORT_USE_MODEL")
    )
    default_user_id: str = field(
        default_factory=lambda: os.getenv(
            "GEMMA4_ONLINE_SUPPORT_USER_ID",
            "online-support",
        )
    )
    outcome_run_autoschema: bool = field(
        default_factory=lambda: _env_bool(
            "GEMMA4_ONLINE_OUTCOME_RUN_AUTOSCHEMA",
            "true",
        )
    )


config = OnlineSupportConfig()
