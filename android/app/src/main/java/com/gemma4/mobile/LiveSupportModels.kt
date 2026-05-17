package com.gemma4.mobile

import org.json.JSONArray
import org.json.JSONObject

enum class LiveTrigger(
    val id: String,
    val label: String,
) {
    NoiseHigh("noise_high", "Too loud"),
    BreakRequested("break_requested", "Need a break"),
    CrowdHigh("crowd_high", "Crowded"),
    WaitingHard("waiting_hard", "Waiting is hard"),
    Ready("ready", "Ready"),
}

enum class SupportAction(val id: String) {
    PutOnHeadphones("put_on_headphones"),
    AskForBreak("ask_for_break"),
    LookAtMap("look_at_map"),
    OneBreath("one_breath"),
    WaitWithCountdown("wait_with_countdown"),
    ContinueStep("continue_step"),
}

data class ApprovedSupportCard(
    val id: String,
    val title: String,
    val triggerIds: Set<String>,
    val action: SupportAction,
    val childMessage: String,
    val caregiverMessage: String,
)

data class LiveSupportPack(
    val scenarioId: String,
    val scenarioTitle: String,
    val currentSteps: List<String>,
    val knownTriggers: List<String>,
    val preferredSupports: List<String>,
    val approvedCards: List<ApprovedSupportCard>,
) {
    val allowedActionIds: Set<String> = approvedCards.map { it.action.id }.toSet()
}

data class LiveCuePacket(
    val currentStep: String,
    val trigger: LiveTrigger,
    val caregiverNote: String,
) {
    val triggerId: String = trigger.id
}

data class LiveSupportCard(
    val title: String,
    val childMessage: String,
    val action: SupportAction,
    val caregiverMessage: String,
    val nextCheckSeconds: Int,
    val source: String,
)

data class GenerationResult(
    val card: LiveSupportCard,
    val engineStatus: String,
    val usedFallback: Boolean,
)

fun String.asSupportActionOrNull(): SupportAction? =
    SupportAction.entries.firstOrNull { it.id == this }

fun LiveSupportPack.toPromptJson(): String {
    val root = JSONObject()
        .put("scenario_id", scenarioId)
        .put("scenario_title", scenarioTitle)
        .put("current_steps", JSONArray(currentSteps))
        .put("known_triggers", JSONArray(knownTriggers))
        .put("preferred_supports", JSONArray(preferredSupports))
        .put("allowed_actions", JSONArray(allowedActionIds.toList()))

    val cards = JSONArray()
    approvedCards.forEach { card ->
        cards.put(
            JSONObject()
                .put("id", card.id)
                .put("title", card.title)
                .put("trigger_ids", JSONArray(card.triggerIds.toList()))
                .put("action", card.action.id)
                .put("child_message", card.childMessage)
                .put("caregiver_message", card.caregiverMessage),
        )
    }
    root.put("approved_cards", cards)
    return root.toString(2)
}

fun LiveCuePacket.toPromptJson(): String =
    JSONObject()
        .put("current_step", currentStep)
        .put("trigger_id", triggerId)
        .put("trigger_label", trigger.label)
        .put("caregiver_note", caregiverNote.ifBlank { JSONObject.NULL })
        .toString(2)
