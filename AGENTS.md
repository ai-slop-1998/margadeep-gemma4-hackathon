# Margadeep Agent Guide

Margadeep is an agent-assisted support project for autistic children and caregivers.

Margadeep helps autistic children and caregivers turn unpredictable real-world moments into supported, learnable experiences.

The core idea is not to "fix" the child, but to act as an external cognitive and sensory support system that improves predictability, independence, self-advocacy, and caregiver support.

Current product pivot: Margadeep should be understood as an embodied reasoning system. It learns from the child-caregiver-environment loop by tracking what support action was tried, what happened in the real world, what helped, what failed, and what should be done differently next time. The app's knowledge graph should become the durable action-outcome memory that informs future MAP, SIMULATE, EQUIP, NAVIGATE, and RECOVER recommendations.

When working in this repo, keep this 5-step product framework in mind:
- `MAP`: reduce ambiguity by deconstructing upcoming situations
- `SIMULATE`: rehearse safely through stories, roleplay, and guided practice
- `EQUIP`: prepare sensory tools, energy checks, and self-advocacy supports
- `NAVIGATE`: provide in-the-moment real-world guidance with minimal cognitive load
- `RECOVER`: support decompression and learn from outcomes over time

Read this first for product intent and language:
- [agent-docs/product/systemic-framework-real-world-adjustment-autism.md](<repo-root>/agent-docs/product/systemic-framework-real-world-adjustment-autism.md)

Read this next for the technical product shape and component flow:
- [agent-docs/components/system-overview.md](<repo-root>/agent-docs/components/system-overview.md)

Then use these component docs depending on the work:
- [agent-docs/components/offline-support/README.md](<repo-root>/agent-docs/components/offline-support/README.md) for preparation before the event
- [agent-docs/components/offline-support/bundle-improvement.md](<repo-root>/agent-docs/components/offline-support/bundle-improvement.md) when iterating on MAP, sensory, simulate, or derived equip bundle quality
- [agent-docs/components/online-support/README.md](<repo-root>/agent-docs/components/online-support/README.md) for live in-the-moment support
- [agent-docs/components/personalization-layer/README.md](<repo-root>/agent-docs/components/personalization-layer/README.md) for durable child context, episode history, and learning
- [agent-docs/components/caregiver-surface/README.md](<repo-root>/agent-docs/components/caregiver-surface/README.md) for caregiver control, review, and reflection
- [agent-docs/api/](<repo-root>/agent-docs/api/) for MCP tool wiring, profile/episode API contracts, and transport-level validation notes
- [agent-docs/memory/](<repo-root>/agent-docs/memory/) to review durable app memory and feature status notes
- [agent-docs/whats-next.md](<repo-root>/agent-docs/whats-next.md) to track the current next implementation steps across sessions

Working norms:
- Prefer the current code over stale README text when they disagree.
- Keep changes aligned with the child-support and caregiver-support goals above.
- Favor calm, structured, low-friction user experiences.
- Treat personalization, predictability, and sensory safety as first-class concerns.
- Keep docs and implementation aligned as the project evolves.
- Keep writing important durable app context and implementation status into `agent-docs/memory/`.
- Keep reading `agent-docs/memory/` for context when needed, especially before changing an important feature or system area.
- Store memory as multiple focused files, with one memory file per important feature or system area.
- Be explicit about whether a flow is currently implemented, scaffolded, or still conceptual.
- Avoid framing passive sensing or support suggestions as medical diagnosis.

Repo orientation:
- `apps/backend/app/agents/offline_prep/`: thin offline-support entry package and re-exports
- `apps/backend/app/agents/shared/sub_agents/`: current offline orchestration, clarification, draft planning, `research_pipeline.py` for feature-flagged per-bundle research plus per-bundle synthesis, `report_composer.py` as a legacy path, and placeholder UI-spec generation
- `apps/backend/app/agents/shared/prompts/`: prompt templates for clarification, planning, per-bundle research, bundle synthesis, and legacy report composition
- `apps/backend/app/agents/online_support/`: live-support package; now includes a real stateless online-support decision agent/service plus the separate generic `live_summary.py` helper, while the older long-running `root.py` / `orchestrator.py` path is still not the main implementation target
- `apps/backend/app/agents/shared/`: shared prompts, models, callbacks, config, and common agent scaffolding
- `apps/backend/app/api_gateway.py`: local Prepare API gateway that bridges the React caregiver workspace to ADK Web over session creation plus SSE streaming, and also exposes `POST /online/decision`, `POST /online/calming-places`, `GET /reflect/day`, `POST /reflect/action`, and `WS /online/ws` for current online-support, reflection, and local live-summary flows
- `apps/frontend/app/src/features/prepare/api/prepareBffClient.js`: frontend API gateway client for prepare session creation, streamed scenario runs, and backend action round-trips
- `apps/frontend/app/src/features/live-summary/`: standalone live-summary WebSocket + A2UI POC
- `apps/frontend/app/src/features/navigate/`: desktop `Navigate` shell, separate `#child-live` web surface, and phone-framed mobile demo around the live-summary POC
- `apps/frontend/app/src/features/shared/AppNav.jsx`: shared left-nav shell used by Prepare and Navigate
- `apps/backend/app/mcp_server/`: MCP server with context tools, prompt/resource registration, tool metadata, and ARASAAC-backed visual lookup services
- `apps/frontend/app/`: runnable React caregiver workspace and current app entry point, now centered on the `PreparePage` offline-support POC
- `apps/mobile_flutter/`: current mobile client path; Flutter Android app that talks to the same local API gateway for Prepare, stateless online-support decisions, mobile Reflect, and live-summary flows
- `apps/android/`: older native Android local-LLM/live-card scaffold; still useful as an experiment, but no longer the primary mobile path
- `apps/frontend/mocs/`: concept-only mock work, not the production frontend source of truth
- `agent-docs/`: product, architecture, and API notes
- `infra/`: deployment notes
- `packages/`: shared contracts and future shared types

Current implementation note:
- Offline support has the clearest backend path today through `offline_prep/agent.py`, which sets default Vertex AI env vars and delegates into a shared clarification -> draft planner -> optional parallel bundle-research orchestrator.
- `offline_prep/agent.py` currently sets `GOOGLE_GENAI_USE_VERTEXAI=True`, `GOOGLE_CLOUD_LOCATION=us-central1`, and sets `GOOGLE_CLOUD_PROJECT` only when `GEMMA4_DEFAULT_GCP_PROJECT` is provided and the environment has not already set it.
- The shared offline config currently exposes `OFFLINE_SUPPORT_ENABLE_CLARIFICATION`, `OFFLINE_SUPPORT_CLARIFICATION_MAX_ROUNDS`, `OFFLINE_SUPPORT_ENABLE_PLAN_REVIEW`, `OFFLINE_SUPPORT_PLAN_REVIEW_MAX_TURNS`, `OFFLINE_SUPPORT_RESPONSE_MODE`, `OFFLINE_SUPPORT_ENABLE_RESEARCH_AFTER_PLANNING`, `RESEARCH_ENABLE_LOOP`, `RESEARCH_MAX_ITERATIONS`, `RESEARCH_SKIP_PLANNER`, `MCP_SERVER_URL`, and model selectors including `RESEARCH_PLANNER_MODEL`.
- The safest executable offline contract today is still `draft_support_plan`, but current shared config defaults both plan review and post-planning research to enabled, so the normal Prepare flow usually continues into approved-plan research and final `bundle_outputs`.
- The draft planner emits a structured `DraftSupportPlan` with ordered bundle priorities plus four downstream bundle briefs: `map`, `sensory`, `simulate`, and `equip`.
- The shared orchestrator now includes a real optional plan-review stage via `plan_review.py`; it stores `reviewed_support_plan`, `approved_support_plan`, `plan_review_result`, `plan_review_required`, `plan_review_status`, `plan_review_turns`, and `latest_user_message` alongside the earlier planning state.
- `OFFLINE_SUPPORT_PLAN_REVIEW_MAX_TURNS` is exposed in shared config, but the current orchestrator still only tracks `plan_review_turns`; it does not yet hard-stop review automatically at that limit.
- `OFFLINE_SUPPORT_RESPONSE_MODE` now controls whether the shared orchestrator emits plain text or deterministic A2UI stage responses; shared config defaults to `text`, while the local Prepare API gateway creates sessions with `response_mode="a2ui"`.
- Current state handoff in the shared orchestrator uses `scenario_intake`, `clarified_request`, `clarification_rounds`, `draft_support_plan`, the plan-review state keys above when review is enabled, and, when research is enabled, `bundle_research_results` plus `bundle_outputs`.
- The optional research stage is implemented in `research_pipeline.py`; it opens the MCP server over Streamable HTTP, runs one parallel research pipeline per bundle, and can optionally add evaluator-driven loop refinement before each bundle synthesizer.
- The research tool connection is driven by `MCP_SERVER_URL`, with `IR_MCP_TIMEOUT_S` and `IR_MCP_TERMINATE_ON_CLOSE` affecting the Streamable HTTP client behavior.
- During bundle research, `bundle_latest_findings_batch` is only the newest per-pass output, while `bundle_findings` is the canonical accumulated findings set for that bundle; later evaluator/follow-up passes append and dedupe rather than overwriting earlier findings.
- MAP bundle finding merges are slightly richer than the other bundles: duplicate MAP findings preserve newly discovered `visuals` so visual candidates can accumulate across passes.
- The MCP layer is concrete enough to use for `geocode_place`, `place_context`, `route_lookup`, `weather_context`, `calming_place_lookup`, ARASAAC symbol/material lookup, local POC-backed `get_profile_details`, `profile_context`, and `past_experience_lookup`, plus graph-memory-backed `knowledge_graph_context` and `insert_experience_event`. Dense personalization reads currently come from `profile_episode_store.py`, which shells out to local `psql`, reads/writes the `margadeep_poc` Postgres + `pgvector` store, and uses the local `google/embeddinggemma-300m` model for episode embeddings. Graph memory currently writes profile-scoped `events.jsonl` / `triples.jsonl` / GraphML under `GEMMA4_KG_MEMORY_DIR`, can retrieve through ATLAS/HippoRAG2 when available, and otherwise falls back to local PageRank-style retrieval. `transit_context` is still stub-backed.
- There are local validation entry points for the MCP layer in `apps/backend/test_http.py`, `apps/backend/tests/smoke_tests/visuals.py`, and `apps/backend/tests/smoke_tests/personalization_https.py`, so docs can treat the MCP surface as testable infrastructure rather than only a conceptual dependency.
- There are now bundle-scoped smoke harnesses in `apps/backend/tests/smoke_tests/map_bundle.py`, `sensory_bundle.py`, and `simulate_bundle.py` to validate individual bundle pipelines and, for MAP, inspect merged visual candidates in both findings and synthesized output.
- The caregiver-facing local POC path now includes profile and episode REST routes in `apps/backend/app/mcp_server/src/api/__init__.py`; these are the intended write path for caregiver CRUD, while agents should keep reading through MCP, and auth/ownership checks are still missing.
- Online support now has a real implemented stateless backend path in `apps/backend/app/agents/online_support/agent.py`, `models.py`, `service.py`, `tools.py`, and `prompts.py`, exposed through `POST /online/decision` in the BFF. The older long-running `root.py` / `orchestrator.py` path is still not the live orchestration path.
- `report_composer.py` is still present as a legacy transitional path, while `ui_spec_generator.py` is placeholder-only; neither is the main contract to build against, and there is no standalone checked-in `synthesis.py` module in the current repo tree.
- The runnable frontend today is `apps/frontend/app`, which mounts `src/features/prepare/PreparePage.jsx` as the main app surface.
- There is now a local Prepare API gateway in `apps/backend/app/api_gateway.py` with `GET /health`, `POST /prepare/session`, `POST /prepare/stream`, and `POST /prepare/action`; it bridges the frontend to ADK Web and forwards frontend-ready `a2ui_stage`, `agent_text`, and `error` SSE events.
- That API gateway currently defaults `GEMMA4_ADK_BASE_URL=http://127.0.0.1:8082`, `GEMMA4_ADK_APP_NAME=offline_prep`, and `GEMMA4_PREPARE_USER_ID=local-caregiver` unless the environment overrides them.
- The same API gateway now exposes a stateless online-support decision endpoint at `POST /online/decision`; callers send a bounded packet with `profile_id`, `surface`, `trigger_source`, caregiver note, compact audio/visual/sensory gate summaries, location context, an optional calming-place request, and, for follow-up checks, `outcome_context`.
- Normal online-support requests return one `OnlineSupportDecision` with a single card (`support_card`, `location_change`, or `caregiver_alert`), evidence flags, and a `measurement_request` baseline that the client can later round-trip as an `outcome_check`.
- `trigger_source=outcome_check` routes the same endpoint into memory write-back: the service compares the stored baseline against current signals, classifies the direction (`improved`, `dropped`, `no_change`, or `unknown`), and calls `insert_experience_event` so online support can feed graph action-outcome memory.
- `GEMMA4_ONLINE_OUTCOME_RUN_AUTOSCHEMA` currently defaults to `true`, so online outcome writes request immediate AutoSchemaKG extraction/merge unless the environment disables it for faster local runs.
- `GEMMA4_ONLINE_SUPPORT_USE_MODEL=false` keeps the stateless online-support flow deterministic for local testing, while the ADK/Vertex model path remains available and has smoke coverage.
- `POST /online/calming-places` is a direct helper path for nearby calmer-place lookup, and the online decision service can also enrich chosen `location_change` cards through `calming_place_lookup` when foreground coordinates are available.
- The same API gateway also now exposes `WS /online/ws` for a generic live-summary POC; it accepts `live_snapshot` payloads, stores a short rolling session history, emits transport events including `session_started`, `session_ready`, and `snapshot_received`, and returns frontend-ready `a2ui_stage` messages for the `live-summary-surface`.
- The live-summary backend helper currently lives in `apps/backend/app/agents/online_support/live_summary.py`; it defaults `GEMMA4_LIVE_SUMMARY_MODEL=gemini-2.5-flash`, respects `GEMMA4_LIVE_SUMMARY_USE_MODEL` plus Google GenAI credentials, and uses `GEMMA4_LIVE_SUMMARY_TIMEOUT_S` for model-call timeout before falling back to a deterministic metadata-only summary card.
- The same API gateway now also exposes a real mobile-first Reflect slice through `GET /reflect/day` and `POST /reflect/action`; the backend turns same-day graph-memory events into a `gemma4.reflectForm` A2UI surface, then saves caregiver-approved reflection both as an episode and as a `caregiver_reflection` graph-memory event.
- That `PreparePage` is a caregiver-facing offline-support POC built with `@a2ui/react/v0_8`, a custom Gemma4 theme, and a mixed live/local A2UI flow: intake, clarification, draft-plan review, research progress, and final bundle cards stream from the backend through the BFF, while the frontend still owns shell layout, detail-opening behavior, and child-stage progression state.
- The runnable frontend app now has multiple hash-routed surfaces in `apps/frontend/app/src/App.jsx`: default `Prepare`, standalone `#live-summary`, desktop `#navigate`, separate child live web surface at `#child-live`, and phone-framed `#mobile` / `#navigate-mobile`.
- The caregiver-stage progression exposed in the main step rail is `intake` -> `clarify` -> `plan` -> `research` -> `bundle` -> `handoff`; `plan_loading` exists only as a short internal transition before the page advances into the visible `plan` stage.
- After caregiver handoff, the frontend also has a separate internal `child` stage that renders the child journey for MAP, sensory, simulate, and equip.
- The current frontend POC includes a real scenario-intake shell, live BFF-backed session creation and SSE streaming, backend-connected `submit_clarification_form` / `save_draft_plan` / `approve_draft_plan` actions, research/bundle detail drill-down, backend-driven caregiver handoff, and child-stage progression across MAP, sensory, simulate, and equip from backend `bundle_outputs`.
- Backend bundle visuals are now part of that handoff path: final bundle cards, detail overlays, caregiver handoff summaries, and child-journey cards can all render backend `image_url` previews when bundle payloads include them.
- The handoff and child path is now strict about backend completeness: if required MAP, sensory, simulate, or equip payloads are missing, the UI shows a backend-data-missing state instead of falling back to local sample content.
- `Navigate` is now a runnable desktop caregiver shell that can use the stateless `POST /online/decision` flow for Live/Recover support cards while still exposing the separate generic live-summary WebSocket/A2UI loop and linking into a separate `#child-live` web surface.
- `apps/mobile_flutter` is now the real first mobile client slice: it uses the same API gateway session and SSE contracts as the web app for Prepare, posts Live and Recover packets to `POST /online/decision`, supports Android-native caregiver handoff plus child progression from backend `bundle_outputs`, includes a real Reflect tab backed by `GET /reflect/day` and `POST /reflect/action`, still supports the generic live-summary/WebSocket POC, and currently keeps `Library` as a local first-pass surface.
- The Flutter client is the preferred mobile direction for A2UI/GenUI work; `pubspec.yaml` already includes `genui`, but the current API gateway still emits Gemma4-specific SSE/WebSocket envelopes, so the app uses a small allowlisted renderer for the current custom components rather than a full A2A/A2UI connector path. The older `apps/android` Kotlin/Compose local-LLM scaffold should be described as an exploratory alternate path rather than the main implementation target.
- There is now closed-loop backend smoke coverage for online support in `apps/backend/tests/smoke_tests/online_support_e2e_memory.py`, so the support-card -> `measurement_request` -> `outcome_check` -> graph-memory update path should be described as implemented-and-testable, not only aspirational.
- The remaining frontend gap is narrower now: detail overlays and the caregiver handoff / child surfaces are still assembled by frontend A2UI helpers over backend payloads, child progression still uses local UI state on top of backend handoff data, backend bundle schema stability still needs tightening, and the profile/episode APIs are still not wired into the caregiver workspace.
- Important current nuance: the backend personalization layer is real enough to read through MCP (`get_profile_details`, `profile_context`, `past_experience_lookup`) and to write through the profile/episode REST API plus Reflect save flow, but the live prepare frontend still includes mocked personalization copy in `src/features/prepare/a2ui/prepareSpecs.js` during its research-progress surface rather than showing real profile/history context.
- The older `src/poc/OfflineClarificationPoc.jsx` remains in the repo as a narrower earlier experiment; `PreparePage.jsx` is the current frontend reference point.
- Online support should still be described carefully: there is now a real stateless domain-specific decision path with graph-memory outcome write-back, but the larger long-running live loop with rolling buffers, fast risk gates, queued summaries, and caregiver alert delivery is still not implemented. The separate live-summary transport + A2UI proof of concept remains useful for media-capture and rendering validation, not as the final autism-specific support loop.
