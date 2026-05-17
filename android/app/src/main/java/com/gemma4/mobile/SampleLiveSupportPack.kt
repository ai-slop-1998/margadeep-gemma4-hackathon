package com.gemma4.mobile

fun sampleLiveSupportPack(): LiveSupportPack =
    LiveSupportPack(
        scenarioId = "clinic_waiting_room_demo",
        scenarioTitle = "Clinic waiting room",
        currentSteps = listOf(
            "Walk inside",
            "Check in",
            "Wait nearby",
            "Follow caregiver",
        ),
        knownTriggers = listOf(
            "loud noise",
            "uncertain waiting",
            "crowded room",
            "bright lights",
        ),
        preferredSupports = listOf(
            "headphones",
            "short countdown",
            "quiet corner",
            "simple map",
        ),
        approvedCards = listOf(
            ApprovedSupportCard(
                id = "headphones",
                title = "Too loud",
                triggerIds = setOf(LiveTrigger.NoiseHigh.id),
                action = SupportAction.PutOnHeadphones,
                childMessage = "Put on headphones.",
                caregiverMessage = "Offer headphones and pause extra talking.",
            ),
            ApprovedSupportCard(
                id = "break",
                title = "Break",
                triggerIds = setOf(LiveTrigger.BreakRequested.id, LiveTrigger.CrowdHigh.id),
                action = SupportAction.AskForBreak,
                childMessage = "Ask for a quiet break.",
                caregiverMessage = "Guide toward the quietest nearby spot.",
            ),
            ApprovedSupportCard(
                id = "map",
                title = "Where next",
                triggerIds = setOf(LiveTrigger.WaitingHard.id),
                action = SupportAction.LookAtMap,
                childMessage = "Look at the next step.",
                caregiverMessage = "Show the waiting step and a short countdown.",
            ),
            ApprovedSupportCard(
                id = "breath",
                title = "One breath",
                triggerIds = setOf(LiveTrigger.WaitingHard.id, LiveTrigger.NoiseHigh.id),
                action = SupportAction.OneBreath,
                childMessage = "Take one slow breath.",
                caregiverMessage = "Model one quiet breath, then stop prompting.",
            ),
            ApprovedSupportCard(
                id = "continue",
                title = "Ready",
                triggerIds = setOf(LiveTrigger.Ready.id),
                action = SupportAction.ContinueStep,
                childMessage = "Follow caregiver to the next step.",
                caregiverMessage = "Move slowly and keep language simple.",
            ),
        ),
    )
