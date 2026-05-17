"""Live summary POC helpers for the online-support WebSocket demo."""
from __future__ import annotations

import asyncio
import base64
import json
import os
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


LIVE_SUMMARY_SURFACE_ID = "live-summary-surface"
LIVE_SUMMARY_ROOT_ID = "live-summary-root"
DEFAULT_LIVE_SUMMARY_MODEL = os.getenv(
    "GEMMA4_LIVE_SUMMARY_MODEL",
    os.getenv("GEMMA4_VERTEX_EVAL_MODEL", "gemini-2.5-flash"),
)


class LiveAudioSummary(BaseModel):
    noise_level: str = "unknown"
    rms: float | None = None
    db_estimate: float | None = None
    duration_ms: int | None = None
    byte_size: int | None = None
    clip_available: bool = False


class LiveLocationContext(BaseModel):
    label: str | None = None
    source: str = "unknown"
    service_enabled: bool | None = None
    permission_status: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    accuracy_m: float | None = None
    altitude_m: float | None = None
    heading_deg: float | None = None
    speed_mps: float | None = None
    is_mocked: bool | None = None
    timestamp: str | None = None
    error: str | None = None

    @property
    def has_coordinates(self) -> bool:
        return self.latitude is not None and self.longitude is not None


class LiveSnapshot(BaseModel):
    session_id: str
    timestamp: str | None = None
    image_frame: str | None = None
    image_mime_type: str = "image/jpeg"
    audio_clip: str | None = None
    audio_mime_type: str = "audio/webm"
    audio_summary: LiveAudioSummary = Field(default_factory=LiveAudioSummary)
    audio_gate: dict[str, Any] = Field(default_factory=dict)
    location: LiveLocationContext | None = None
    location_label: str | None = None
    note: str | None = None
    synthetic_sensory_gate: dict[str, Any] = Field(default_factory=dict)
    trigger_source: str | None = None
    visual_gate: dict[str, Any] = Field(default_factory=dict)


class LiveSummaryCard(BaseModel):
    title: str = "Live scene summary"
    summary: str
    observations: list[str] = Field(default_factory=list)
    audio_note: str = "Audio level unavailable."
    confidence_note: str = "POC summary only; verify with the live scene."
    generated_at: str
    model_label: str = "deterministic fallback"


async def summarize_live_snapshot(snapshot: LiveSnapshot) -> LiveSummaryCard:
    """Return a concise card summary for the latest live snapshot."""

    if _should_try_model():
        try:
            return await _summarize_with_gemini(snapshot)
        except Exception as exc:
            detail = str(exc).strip()
            error_note = f"{type(exc).__name__}: {detail[:180]}" if detail else type(exc).__name__
            return _fallback_summary(
                snapshot,
                confidence_note=(
                    "Model summary failed, so this fallback card uses local "
                    f"media metadata only. Error: {error_note}"
                ),
            )

    return _fallback_summary(snapshot)


def build_live_summary_a2ui_messages(card: LiveSummaryCard) -> list[dict[str, Any]]:
    """Build a small A2UI surface for the live summary card."""

    return [
        {
            "surfaceUpdate": {
                "surfaceId": LIVE_SUMMARY_SURFACE_ID,
                "components": [
                    {
                        "id": LIVE_SUMMARY_ROOT_ID,
                        "component": {
                            "gemma4.liveSummaryCard": card.model_dump(),
                        },
                    }
                ],
            }
        },
        {
            "beginRendering": {
                "surfaceId": LIVE_SUMMARY_SURFACE_ID,
                "root": LIVE_SUMMARY_ROOT_ID,
            }
        },
    ]


def _should_try_model() -> bool:
    mode = os.getenv("GEMMA4_LIVE_SUMMARY_USE_MODEL", "auto").strip().lower()
    if mode in {"0", "false", "no", "off"}:
        return False
    if mode in {"1", "true", "yes", "on"}:
        return True

    has_api_key = bool(os.getenv("GOOGLE_API_KEY"))
    use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    has_vertex = use_vertex and bool(os.getenv("GOOGLE_CLOUD_PROJECT"))
    return has_api_key or has_vertex


async def _summarize_with_gemini(snapshot: LiveSnapshot) -> LiveSummaryCard:
    from google import genai
    from google.genai import types

    client = genai.Client()
    prompt = _model_prompt(snapshot)
    contents: list[Any] = [prompt]
    image_bytes = _decode_image(snapshot.image_frame)
    if image_bytes:
        contents.append(
            types.Part.from_bytes(
                data=image_bytes,
                mime_type=snapshot.image_mime_type or "image/jpeg",
            )
        )
    audio_bytes = _decode_data_url(snapshot.audio_clip)
    if audio_bytes:
        contents.append(
            types.Part.from_bytes(
                data=audio_bytes,
                mime_type=snapshot.audio_mime_type or "audio/webm",
            )
        )

    response = await asyncio.to_thread(
        client.models.generate_content,
        model=DEFAULT_LIVE_SUMMARY_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2,
        ),
    )
    payload = _parse_model_json(getattr(response, "text", "") or "")
    generated_at = datetime.now(timezone.utc).isoformat()
    return LiveSummaryCard(
        title=str(payload.get("title") or "Live scene summary")[:80],
        summary=str(payload.get("summary") or "The live scene was summarized.")[:700],
        observations=[
            str(item)[:160]
            for item in payload.get("observations", [])
            if str(item).strip()
        ][:5],
        audio_note=str(payload.get("audio_note") or _audio_note(snapshot))[:240],
        confidence_note=str(
            payload.get("confidence_note")
            or "POC summary from a sampled frame and audio metadata."
        )[:260],
        generated_at=generated_at,
        model_label=DEFAULT_LIVE_SUMMARY_MODEL,
    )


def _model_prompt(snapshot: LiveSnapshot) -> str:
    audio = snapshot.audio_summary
    audio_clip_status = (
        f"{audio.byte_size} bytes, {audio.duration_ms} ms"
        if audio.clip_available
        else "not provided"
    )
    location_note = _location_note(snapshot)
    return f"""
You are summarizing a live browser POC snapshot.

Use the image if provided, the short audio clip if provided, and the audio
metadata below. If speech is audible, summarize it briefly instead of writing a
full transcript. If the audio is unclear, say that. Do not invent precise facts
that are not visible or audible. Return only JSON with these keys:
title, summary, observations, audio_note, confidence_note.

Audio metadata:
- noise_level: {audio.noise_level}
- rms: {audio.rms}
- db_estimate: {audio.db_estimate}
- audio_clip: {audio_clip_status}
- audio_mime_type: {snapshot.audio_mime_type}

Location/context:
{location_note}

Trigger source:
{snapshot.trigger_source or "unknown"}

User note:
{snapshot.note or "none"}
""".strip()


def _fallback_summary(
    snapshot: LiveSnapshot,
    *,
    confidence_note: str | None = None,
) -> LiveSummaryCard:
    image_status = "an image snapshot was received" if snapshot.image_frame else "no image snapshot was received"
    audio_status = "an audio clip was received" if snapshot.audio_clip else "no audio clip was received"
    audio_note = _audio_note(snapshot)
    observations = [
        f"Snapshot status: {image_status}.",
        f"Audio clip status: {audio_status}.",
        audio_note,
    ]
    location_note = _location_note(snapshot)
    if location_note != "not provided":
        observations.append(location_note)
    if snapshot.note:
        observations.append(f"User note: {snapshot.note}")

    return LiveSummaryCard(
        title="Live snapshot received",
        summary=(
            "The backend received a live browser snapshot. Configure "
            "`GEMMA4_LIVE_SUMMARY_USE_MODEL=true` with Google GenAI credentials "
            f"to generate visual scene summaries with {DEFAULT_LIVE_SUMMARY_MODEL}."
        ),
        observations=observations,
        audio_note=audio_note,
        confidence_note=confidence_note
        or "Deterministic fallback; no visual model was called.",
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def _audio_note(snapshot: LiveSnapshot) -> str:
    audio = snapshot.audio_summary
    clip_note = ""
    if audio.clip_available:
        if audio.duration_ms is not None:
            clip_note = f" A {audio.duration_ms / 1000:.1f}s audio clip was attached."
        else:
            clip_note = " An audio clip was attached."
    if audio.db_estimate is not None:
        return f"Audio summary reports {audio.noise_level} sound, about {audio.db_estimate:.1f} dB estimate.{clip_note}"
    if audio.rms is not None:
        return f"Audio summary reports {audio.noise_level} sound, RMS {audio.rms:.4f}.{clip_note}"
    return f"Audio summary reports {audio.noise_level} sound.{clip_note}"


def _location_note(snapshot: LiveSnapshot) -> str:
    location = snapshot.location
    if location is None:
        if snapshot.location_label:
            return f"Location label: {snapshot.location_label}."
        return "not provided"
    label = location.label or snapshot.location_label or "current phone location"
    if location.has_coordinates:
        accuracy = (
            f", accuracy about {location.accuracy_m:.0f} m"
            if location.accuracy_m is not None
            else ""
        )
        return (
            f"Foreground location: {label} at "
            f"{location.latitude:.5f}, {location.longitude:.5f}{accuracy}."
        )
    if location.error:
        return f"Location unavailable for {label}: {location.error}"
    return f"Location context for {label} was provided without coordinates."


def _decode_image(image_frame: str | None) -> bytes | None:
    return _decode_data_url(image_frame)


def _decode_data_url(value: str | None) -> bytes | None:
    if not value:
        return None
    data = value
    if "," in data and data.startswith("data:"):
        data = data.split(",", 1)[1]
    try:
        return base64.b64decode(data, validate=False)
    except Exception:
        return None


def _parse_model_json(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(text[start : end + 1])
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
    return {}
