# Margadeep Android

Native Android prototype for Margadeep live support cards.

This app is intentionally Android-first:

- Kotlin + Jetpack Compose UI
- ML Kit GenAI Prompt API for on-device generation through AICore
- deterministic fallback cards when the local model is unavailable
- a swappable `LocalCardGenerator` boundary for a future direct LiteRT-LM Gemma 4 E2B/E4B runner

## Current State

Implemented:

- child-facing live card surface
- sample `LiveSupportPack` derived from Gemma4 MAP / sensory / equip intent
- local cue buttons such as `Too loud`, `Need a break`, and `Crowded`
- local prompt builder that asks the on-device model for strict JSON
- schema validation before a generated card is shown
- fallback support card selection if AICore, Gemini Nano, or the prompt API is unavailable

Not implemented yet:

- pulling a real `live_support_pack` from the Gemma4 backend
- direct Gemma 4 open-weight inference with LiteRT-LM
- camera, mic, wearable, or location cue extraction
- caregiver companion sync
- durable episode write-back

## Run

Open `apps/android` in Android Studio and run the `app` configuration on a physical Android device.

The ML Kit GenAI Prompt API requires Android API 26 or higher, and local model availability depends on the device and AICore state. Unsupported devices still run the app through deterministic fallback cards.

This workspace does not currently include a Gradle wrapper, and the local machine did not have `gradle` installed when this scaffold was created. Android Studio can import the project and use its managed Gradle tooling.

## Model Path

The first model path is:

```text
Android app -> ML Kit GenAI Prompt API -> AICore -> local Gemini Nano / edge model
```

For Gemma4 product behavior, the app should keep the LLM tightly boxed:

```text
prepared live support pack
+ current cue packet
+ local LLM
+ validator
= one child-facing support card
```

The LLM should not invent a support plan. It should select or rewrite one approved support card from a caregiver-reviewed pack.

## Next Integration Step

Add a backend export endpoint that turns final `bundle_outputs` into a compact `live_support_pack`, then replace `sampleLiveSupportPack()` in the Android app with a repository that downloads and caches that pack.
