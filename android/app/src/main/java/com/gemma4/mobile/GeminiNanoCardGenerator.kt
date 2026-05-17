package com.gemma4.mobile

import com.google.mlkit.genai.common.DownloadStatus
import com.google.mlkit.genai.common.FeatureStatus
import com.google.mlkit.genai.prompt.Generation
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

class GeminiNanoCardGenerator(
    private val fallback: LocalCardGenerator = DeterministicCardGenerator(),
) : LocalCardGenerator {
    private val generativeModel = Generation.getClient()

    override suspend fun generate(
        supportPack: LiveSupportPack,
        cuePacket: LiveCuePacket,
    ): GenerationResult = withContext(Dispatchers.Default) {
        val readiness = runCatching { ensureReady() }
            .getOrElse { "Local model status check failed: ${it.safeMessage()}" }
        if (readiness != null) {
            return@withContext fallback.generate(supportPack, cuePacket).copy(
                engineStatus = readiness,
                usedFallback = true,
            )
        }

        try {
            val response = generativeModel.generateContent(buildPrompt(supportPack, cuePacket))
            val raw = response.candidates.firstOrNull()?.text.orEmpty()
            val parsed = parseGeneratedCard(raw, supportPack)
            if (parsed == null) {
                fallback.generate(supportPack, cuePacket).copy(
                    engineStatus = "Local model answered, but validation failed. Showing approved fallback.",
                    usedFallback = true,
                )
            } else {
                GenerationResult(
                    card = parsed,
                    engineStatus = "Generated locally with ML Kit GenAI Prompt API.",
                    usedFallback = false,
                )
            }
        } catch (error: Throwable) {
            fallback.generate(supportPack, cuePacket).copy(
                engineStatus = "Local generation failed: ${error.safeMessage()}",
                usedFallback = true,
            )
        }
    }

    private suspend fun ensureReady(): String? {
        return when (generativeModel.checkStatus()) {
            FeatureStatus.AVAILABLE -> {
                runCatching { generativeModel.warmup() }
                null
            }

            FeatureStatus.DOWNLOADABLE -> {
                var downloadFailure: String? = null
                generativeModel.download().collect { status ->
                    if (status is DownloadStatus.DownloadFailed) {
                        downloadFailure = status.e.safeMessage()
                    }
                }
                if (downloadFailure != null) {
                    "On-device model download failed: $downloadFailure"
                } else if (generativeModel.checkStatus() == FeatureStatus.AVAILABLE) {
                    runCatching { generativeModel.warmup() }
                    null
                } else {
                    "On-device model download did not complete yet. Try again shortly."
                }
            }

            FeatureStatus.DOWNLOADING ->
                "On-device model is still downloading. Try again shortly."

            else ->
                "On-device generation is unavailable on this device. Showing approved fallback."
        }
    }

    private fun buildPrompt(
        supportPack: LiveSupportPack,
        cuePacket: LiveCuePacket,
    ): String =
        """
        You are Margadeep's Android live support card composer.

        The app supports an autistic child during a real-world moment. The goal is not diagnosis.
        Produce exactly one calm support card. Use only the approved support pack.

        Rules:
        - Return JSON only. No markdown.
        - Use one of the approved action ids only.
        - Do not use medical or diagnostic language.
        - Do not claim overload was detected.
        - child_message must be 8 words or fewer.
        - caregiver_message must be 16 words or fewer.
        - Prefer predictable, concrete language.

        Required JSON keys:
        {
          "title": "short label",
          "child_message": "one short child-facing instruction",
          "action": "approved_action_id",
          "caregiver_message": "one caregiver action",
          "next_check_seconds": 30
        }

        Approved support pack:
        ${supportPack.toPromptJson()}

        Current cue packet:
        ${cuePacket.toPromptJson()}
        """.trimIndent()

    private fun parseGeneratedCard(
        rawText: String,
        supportPack: LiveSupportPack,
    ): LiveSupportCard? {
        val jsonText = rawText.extractJsonObject() ?: return null
        val json = runCatching { JSONObject(jsonText) }.getOrNull() ?: return null
        val title = json.optString("title").clean(max = 34)
        val childMessage = json.optString("child_message").clean(max = 72)
        val action = json.optString("action").asSupportActionOrNull() ?: return null
        val caregiverMessage = json.optString("caregiver_message").clean(max = 120)
        val nextCheck = json.optInt("next_check_seconds", 90).coerceIn(30, 300)

        if (action.id !in supportPack.allowedActionIds) return null
        if (title.isBlank() || childMessage.isBlank() || caregiverMessage.isBlank()) return null
        if (childMessage.wordCount() > 8) return null
        if (caregiverMessage.wordCount() > 16) return null
        if (containsDiagnosticLanguage("$title $childMessage $caregiverMessage")) return null

        return LiveSupportCard(
            title = title,
            childMessage = childMessage,
            action = action,
            caregiverMessage = caregiverMessage,
            nextCheckSeconds = nextCheck,
            source = "on-device model",
        )
    }
}

private fun String.extractJsonObject(): String? {
    val start = indexOf('{')
    val end = lastIndexOf('}')
    return if (start >= 0 && end > start) substring(start, end + 1) else null
}

private fun String.clean(max: Int): String =
    replace(Regex("\\s+"), " ")
        .trim()
        .take(max)

private fun String.wordCount(): Int =
    trim()
        .split(Regex("\\s+"))
        .filter { it.isNotBlank() }
        .size

private fun containsDiagnosticLanguage(value: String): Boolean {
    val lowered = value.lowercase()
    val blocked = listOf(
        "diagnose",
        "diagnosis",
        "meltdown detected",
        "overload detected",
        "disorder",
        "symptom",
    )
    return blocked.any { it in lowered }
}

private fun Throwable.safeMessage(): String =
    message?.take(180) ?: this::class.simpleName.orEmpty().ifBlank { "unknown error" }
