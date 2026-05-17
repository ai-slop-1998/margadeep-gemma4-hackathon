package com.gemma4.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            Gemma4MobileTheme {
                Gemma4LiveSupportApp()
            }
        }
    }
}

@Composable
private fun Gemma4LiveSupportApp() {
    val supportPack = remember { sampleLiveSupportPack() }
    val generator = remember { GeminiNanoCardGenerator() }
    val scope = rememberCoroutineScope()

    var selectedStepIndex by remember { mutableIntStateOf(2) }
    var caregiverNote by remember { mutableStateOf("Waiting is taking longer than expected.") }
    var selectedTrigger by remember { mutableStateOf(LiveTrigger.WaitingHard) }
    var result by remember {
        mutableStateOf(
            GenerationResult(
                card = supportPack.approvedCards[2].toLiveSupportCard(source = "approved starter"),
                engineStatus = "Ready. Tap a cue to generate locally.",
                usedFallback = true,
            ),
        )
    }
    var isGenerating by remember { mutableStateOf(false) }

    fun generate(trigger: LiveTrigger) {
        selectedTrigger = trigger
        val cue = LiveCuePacket(
            currentStep = supportPack.currentSteps[selectedStepIndex],
            trigger = trigger,
            caregiverNote = caregiverNote,
        )
        isGenerating = true
        scope.launch {
            result = generator.generate(supportPack, cue)
            isGenerating = false
        }
    }

    Scaffold { innerPadding ->
        Surface(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding),
            color = MaterialTheme.colorScheme.background,
        ) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(18.dp),
            ) {
                Header(supportPack)

                CurrentStepPicker(
                    steps = supportPack.currentSteps,
                    selectedStepIndex = selectedStepIndex,
                    onSelected = { selectedStepIndex = it },
                )

                OutlinedTextField(
                    modifier = Modifier.fillMaxWidth(),
                    value = caregiverNote,
                    onValueChange = { caregiverNote = it },
                    label = { Text("Caregiver note") },
                    minLines = 2,
                )

                CueButtons(
                    selectedTrigger = selectedTrigger,
                    isGenerating = isGenerating,
                    onCue = ::generate,
                )

                LiveCard(result.card)

                StatusPanel(
                    result = result,
                    isGenerating = isGenerating,
                    onRegenerate = { generate(selectedTrigger) },
                )
            }
        }
    }
}

@Composable
private fun Header(supportPack: LiveSupportPack) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(
            text = "Margadeep Live",
            color = MaterialTheme.colorScheme.primary,
            fontSize = 32.sp,
            fontWeight = FontWeight.Bold,
        )
        Text(
            text = supportPack.scenarioTitle,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            fontSize = 16.sp,
        )
    }
}

@Composable
@OptIn(ExperimentalLayoutApi::class)
private fun CurrentStepPicker(
    steps: List<String>,
    selectedStepIndex: Int,
    onSelected: (Int) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(
            text = "Current step",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
        )
        FlowRow(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            steps.forEachIndexed { index, step ->
                FilterChip(
                    selected = selectedStepIndex == index,
                    onClick = { onSelected(index) },
                    label = { Text(step) },
                )
            }
        }
    }
}

@Composable
@OptIn(ExperimentalLayoutApi::class)
private fun CueButtons(
    selectedTrigger: LiveTrigger,
    isGenerating: Boolean,
    onCue: (LiveTrigger) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(
            text = "Cue",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
        )
        FlowRow(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            LiveTrigger.entries.forEach { trigger ->
                Button(
                    enabled = !isGenerating,
                    onClick = { onCue(trigger) },
                ) {
                    Text(
                        text = if (trigger == selectedTrigger) "${trigger.label} selected" else trigger.label,
                        textAlign = TextAlign.Center,
                    )
                }
            }
        }
    }
}

@Composable
private fun LiveCard(card: LiveSupportCard) {
    ElevatedCard(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.elevatedCardColors(
            containerColor = MaterialTheme.colorScheme.surface,
        ),
    ) {
        Column(
            modifier = Modifier.padding(22.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = card.title,
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.primary,
                )
                Spacer(modifier = Modifier.weight(1f))
                AssistChip(
                    onClick = {},
                    label = { Text(card.action.id.replace('_', ' ')) },
                )
            }

            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 10.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = card.childMessage,
                    color = MaterialTheme.colorScheme.onSurface,
                    fontSize = 34.sp,
                    fontWeight = FontWeight.Bold,
                    lineHeight = 40.sp,
                    textAlign = TextAlign.Center,
                )
            }

            Text(
                text = card.caregiverMessage,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyLarge,
            )

            Text(
                text = "Check again in ${card.nextCheckSeconds} seconds",
                color = MaterialTheme.colorScheme.secondary,
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.SemiBold,
            )
        }
    }
}

@Composable
private fun StatusPanel(
    result: GenerationResult,
    isGenerating: Boolean,
    onRegenerate: () -> Unit,
) {
    ElevatedCard(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.elevatedCardColors(
            containerColor = MaterialTheme.colorScheme.secondaryContainer,
        ),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(
                text = if (isGenerating) "Generating local card..." else result.engineStatus,
                color = MaterialTheme.colorScheme.onSecondaryContainer,
                style = MaterialTheme.typography.bodyMedium,
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                AssistChip(
                    onClick = {},
                    label = {
                        Text(
                            if (result.usedFallback) {
                                "Fallback"
                            } else {
                                "On-device LLM"
                            },
                        )
                    },
                )
                Spacer(modifier = Modifier.width(10.dp))
                Text(
                    text = "Source: ${result.card.source}",
                    color = MaterialTheme.colorScheme.onSecondaryContainer,
                    style = MaterialTheme.typography.bodySmall,
                )
                Spacer(modifier = Modifier.weight(1f))
                TextButton(
                    enabled = !isGenerating,
                    onClick = onRegenerate,
                ) {
                    Text("Try again")
                }
            }
        }
    }

    Spacer(modifier = Modifier.height(8.dp))
}
