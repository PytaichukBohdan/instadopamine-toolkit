---
name: voice-clone-dna
description: Clone a person's voice, preserve characteristic phrasing and prosody, generate speech, or postprocess an approved synthetic take using the owner's approved ElevenLabs and gentle DSP workflow. Applies to voice DNA and Ukrainian stress review; ordinary stock-voice narration does not require cloning.
---

# Voice cloning and performance DNA

The owner approved the InstaDopamine voice and its postprocessing on 1 October 2026 and requested this workflow as the default across projects. Follow the method for a **new speaker's own** voice and delivery. The first approved case is a measured example, not a universal identity, language, EQ curve or promise of identical quality. An explicit current brief takes priority.

## Choose the relevant route

- **New speaker or new script:** collect attributed voice references, build a phrase/prosody map, condition the clone on the appropriate speaking register, then synthesize and review.
- **Approved generation sounds harsh/robotic:** preserve the exact source take. Begin with gentle local postprocessing and a loudness-matched comparison; do not automatically regenerate or change pitch/time.
- **Same known speaker, new text:** reuse the private approved profile and source map; review the new wording, stresses and performed phrases again.

Read [the approved case](references/approved-case.md) for the precise settings, evidence and rejected alternatives. Read [production mechanics](references/production.md) when collecting references, calling TTS, or using the bundled helpers. The installation has no credentials, trained voices or raw speaker recordings.

## Capture the performance before choosing settings

Use actual audio, not captions alone. Separate attributable speech from guests, voiceovers, music, laughter and overlapping dialogue. Prefer several useful passages in the desired register to a long contaminated reel. Where useful, preserve separate conversational, vlog/direct-address and energetic samples. Clean reference noise only when that improves detail; always retain the original. Do not flatten pitch or speed before cloning.

Make a compact evidence map: phrase verbatim, source and time window, language, attribution basis, pauses/lengthening, emphasis, pitch direction, onset/ending and confidence. Mark written catchphrases without an audio example as **unverified pronunciation**. Measure pitch/rhythm only as descriptive evidence; F0 similarity is not speaker identification. Separate a format reference's music/editing/narrative structure from the target person's voice and character.

Translate this map into the new script's performance: conversational setup, quicker clarification, quiet aside, numeric emphasis, energetic exit, as supported by that speaker. Use sparse local directions instead of one generic “confident deep voice” instruction. Do not import one person's catchphrases or mannerisms into another.

## Generate and review

Prefer the owner's approved **ElevenLabs cloned-voice route** when credentials, language and account capabilities permit. The successful case used IVC with v4; verify the provider's current model catalog, API schema, verification requirements and available output format before spending. Do not label a directed stock voice as a clone or IVC as PVC. Existing authorization should be used; this preference does not authorize unrelated purchases, plan upgrades, or verification bypasses.

For Ukrainian, maintain plain text plus a stress-reviewed version with combining acute accents and a basis for **each occurrence**, including repeated words. Context decides ambiguous stress. Preserve the original letters and words. Use marked versus plain auditions if useful: reviewed plain text won the approved full performance. Accent markup is a tool, not an obligation to send every accent to the model. Verify rendered pronunciation in short windows and full context.

Prefer a coherent full take for a short reel when supported; excessive sentence stitching, tags, compression and stretching can harm delivery. Begin with a small comparison that answers a concrete uncertainty; expand only for a named defect, not to recreate the historical count of 17 attempts. Save exact request, settings, voice ID privately, costs, output hash and decision. Paid retries are distinct decisions, never automatic loops. Do not substitute a different provider silently if access blocks the preferred route.

Review **text, timbre and prosody separately**. ASR can miss merged words; a correct transcript does not prove natural stress. Compare distinctive phrases against their reference windows. Whole-take and cropped model reviews can disagree; record uncertainty rather than inventing consensus. Owner feedback outranks model preference. Do not claim human listening or phoneme-perfect cloning without that evidence.

## Preserve the approved take in postproduction

Start from the original approved generator output before heavy previous mastering. Pin its SHA-256. Inspect clipping, harshness, sibilance and existing dynamics before choosing processing.

The successful default was broad, shallow midrange EQ plus bounded, smoothed dynamic de-essing, followed by **constant gain**. Offer a conservative treatment and a softer alternative when useful. Keep a before control at the same integrated loudness. Retain sample count, pauses and endings. The case presets are initial audition points; adapt thresholds/frequencies to the new voice rather than forcing its spectrum into the first case's.

Do not default to neural denoising, voice conversion, reverb, fabricated breaths, global pitch shifts, time stretching or another hard limiter. They were unnecessary or detrimental in the approved case. Use them only to address an evidenced issue, audition against the untouched take, and reject them when they alter desirable voice detail. Tonal cleanup cannot restore missing synthesis detail.

Measured phrase-contour transfer is an **optional archival technique**, not part of the approved final ElevenLabs chain. Use it only for a specific same-phrase prosody problem with good source boundaries; it can change duration/articulation. Never apply the archived fixed pitch limits blindly to another speaker.

## Deliver a useful listening result

Deliver the dry processed voice, before/after comparison and editing WAV; include a music mix/stems when the brief calls for them. Match comparison loudness and, where practical, preserve play position when switching. Measure actual durations, LUFS and true peaks for **both WAV and encoded MP3**; test seeking/downloads on the actual host. Identify PCM exports from lossy sources honestly.

Keep source recordings, voice profiles, provider IDs, keys and raw receipts private. A prior project's public-report exception is not permission to publish a new person's private assets. Label authored synthetic speech as such. Keep the approved original, processing recipe, measurements, source map and owner feedback for reuse. State what remains uncertain without underselling the owner's actual approval.
