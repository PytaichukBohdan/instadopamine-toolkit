# Production mechanics

## Reference pack and private continuity

Use a private task directory outside the repository and publication output. Keep original source, selected windows, exact transcript, speaker-attribution evidence, hashes and recording conditions. Store a compact phrase map and reuse metadata beside the provider voice ID or local profile. Check the supplied speaker attribution from the video context; do not identify an unknown person from their voice.

Choose coherent, single-speaker excerpts. Begin with clean source if available; use gentle isolation on references with music only after comparing consonant/breath detail. Save the original and isolated versions. Several short, well-attributed samples in the intended speaking style can be more useful than a larger mixed conversation. The benchmark used roughly two minutes, not a magic minimum.

Current provider documentation/API access governs supported models, languages, cloning sample limits and verification. Create/reuse an IVC through the available supported interface; the packaged TTS helper expects an existing private voice ID and does not create one. Retain provider requirements; never manufacture a verification recording. A request for cloning does not automatically authorize publishing private source material or spending on unrelated subscriptions.

Provider references to recheck when executing:
- https://elevenlabs.io/docs/api-reference/voices/ivc/create
- https://elevenlabs.io/docs/api-reference/text-to-dialogue/convert
- https://elevenlabs.io/docs/overview/capabilities/text-to-speech/eleven-v4

## Bundled helpers and dependencies

The scripts are local snapshots of the approved implementation so the skill does not depend on a temporary worktree. Commands below run from the **skill directory**, not from an unrelated repository. Use a suitable virtual environment; no key is needed for `--help`, dry-run validation or local postprocessing.

- `scripts/synthesize_elevenlabs.py`: Ukrainian request and pronunciation ledger; one paid request, no automatic retries; private output only. It is Ukrainian-specific (`language_code='uk'` and Ukrainian stress validation). For another language, adapt the request and use that language's pronunciation review rather than pretending this helper is multilingual.
- `scripts/postprocess_voice.py`: hash-pinned tone correction, bounded de-essing, matched gain, measured WAV/MP3 outputs. Source rate is converted to 48 kHz mono. Before control must have the exact same sample count.
- `scripts/mix_reel.py`: shared decoding/loudness utilities and the historical configurable mix helper. Its mastering route uses dynamics processing; the approved gentle postprocessing route does **not** call that mastering function.
- `scripts/transfer_prosody.py`: optional legacy same-phrase pitch transfer. It contains fixed 65–400 Hz limits suitable for its source example; adapt them only with evidence, otherwise do not use on other speakers. Optional duration matching changes timing. Not used for the approved ElevenLabs final.
- `scripts/instadna/pronunciation.py`: per-occurrence stress validation, request hash and ledger checks.

Dependencies: Python 3.11+, requests, numpy, scipy, soundfile; FFmpeg/ffprobe on PATH. Optional phrase transfer additionally needs praat-parselmouth. The benchmark postprocessing environment used FFmpeg 6.1.1, numpy 2.4.6, scipy 1.17.1 and soundfile 0.14.0. These are reproduction details, not a reason to upgrade another environment blindly.

## Ukrainian script and request

Prepare `script.json` with `lines`: each line has `text`, `marked_text`, and optionally a short `delivery_tag`. Keep both versions identical apart from combining acute accents. Prepare `bases.json` as a list of lists: one contextual review basis per lexical token in each corresponding marked line, including repeated words and monosyllables. Use `instadna.pronunciation.words` when enumerating tokens. Resolve ambiguous stresses in context; a structural ledger cannot prove a linguistic choice.

```sh
python scripts/synthesize_elevenlabs.py \
  --script /private/script.json --bases /private/bases.json \
  --voice-id "$PRIVATE_ELEVEN_VOICE_ID" \
  --key-file /private/elevenlabs.env --output /private/new-dry-run \
  --model eleven_v4 --stability .35 --similarity .93 --seed 4401 \
  --stress plain --join-lines --dry-run
```

After reviewing the dry-run request, use a **different empty output directory** and omit `--dry-run` for the authorized paid call. Model/catalog/schema may have changed; check before execution. If comparing marked and plain text, only change that factor initially. Never keep regenerating after the owner has approved the performance just to win a model rating.

Review the full take and small ambiguous windows. Check names, numbers, clipped beginnings/endings, “і / де / я”-like word boundaries, omitted words and stress. Preserve contradictions between ASR and audio review rather than silently rewriting the spoken claim. Rewrite or resynthesize only for a concrete problem that the current brief allows.

## Postprocess an approved source

Copy `references/postprocess-template.json` to the private task directory. Set `source_sha256` to the hash of the **new task's approved generator output**. It is intentionally null in the template; the helper refuses a mismatch. Start with the two case presets as auditions, then adjust to the source if measurements/listening warrant it. No vocal or credential file is included in the skill.

```sh
python scripts/postprocess_voice.py \
  --source /private/approved-generation.mp3 \
  --before /private/previous-delivered-voice.wav \
  --recipe /private/postprocess.json --output /private/new-postprocess
```

Omit `--before` when no previous master exists; the raw control is still produced. Supply an existing correctly ducked, exactly 60-second stereo music stem using `--music-stem` only when the brief matches the helper's 60-second/0.15-second layout. For another length or alignment, adapt that explicit arrangement instead of stretching the speaker to fit it.

The receipt retains source/recipe hashes, parameters and measured exports. In FFmpeg's measurement JSON, `input_i`, `input_tp` and `input_lra` describe the actual supplied export; its hypothetical `output_*` values from a null sink are not measurements of a newly saved file. For publication use only sanitized measurements and selected outputs, never the whole private work directory.

## Review and reuse contract

Compare before / conservative / softer at the same integrated loudness. Check actual true peaks after MP3 encoding, sample count, silence and endings. Gain-only matching may choose a quieter common target to preserve peaks. Reject processing that dulls speech or introduces watery/lispy details. If a model cannot distinguish options, say so; actual owner choice is the selection criterion.

Deliver a listening page with native playback, matching MP3/WAV downloads and optional same-position switching. Check range requests and actual browser seeking on the deployed host; a generic local static server may not support them. Save source/processed hashes, the selected preset, measured outputs and the exact feedback. Record whether the owner chose a specific preset or approved the set generally.

A durable handoff should contain: source-window index; phrase/prosody map; private profile locator; exact TTS request; plain/stressed text with bases; approved raw hash; DSP recipe; dry voice and optional stems/mix; measurements; comparison decision; owner feedback; known limits. Credentials and trained profiles remain in private storage, not in this skill or public reports.
