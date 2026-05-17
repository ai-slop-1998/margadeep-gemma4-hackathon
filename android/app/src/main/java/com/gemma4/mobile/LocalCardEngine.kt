package com.gemma4.mobile

interface LocalCardGenerator {
    suspend fun generate(
        supportPack: LiveSupportPack,
        cuePacket: LiveCuePacket,
    ): GenerationResult
}

class DeterministicCardGenerator : LocalCardGenerator {
    override suspend fun generate(
        supportPack: LiveSupportPack,
        cuePacket: LiveCuePacket,
    ): GenerationResult {
        val matched = supportPack.approvedCards.firstOrNull { cuePacket.triggerId in it.triggerIds }
            ?: supportPack.approvedCards.first()

        return GenerationResult(
            card = matched.toLiveSupportCard(source = "approved fallback"),
            engineStatus = "Using approved fallback card.",
            usedFallback = true,
        )
    }
}

fun ApprovedSupportCard.toLiveSupportCard(source: String): LiveSupportCard =
    LiveSupportCard(
        title = title,
        childMessage = childMessage,
        action = action,
        caregiverMessage = caregiverMessage,
        nextCheckSeconds = 90,
        source = source,
    )
