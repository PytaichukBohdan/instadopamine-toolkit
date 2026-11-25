# Approved benchmark (first case, October 2026)

The method in this skill was approved on its first real case: a Ukrainian creator's
60-second self-introduction in their cloned voice. This page keeps the technical settings
and lessons from that case. It deliberately leaves out the person, their recordings and
their phrases.

The owner's approval was positive feedback on the delivered result. It was **not an
explicit choice between the clean and soft presets**, not a controlled listening panel, and
not verified phoneme identity.

## Reference and generation choices

Four IVC profiles were compared: interview speech, and vlog/direct-address speech, including
cleaned references. About **114 seconds of cleaned vlog speech** won. Use the same speaker's
unforced cadence in the register you need. Neither that duration nor four profiles is a
requirement for a new voice.

| Field | Observed value |
|---|---|
| Provider / voice class | ElevenLabs Instant Voice Clone; not PVC |
| Endpoint | `/v1/text-to-dialogue` |
| Model | `eleven_v4` |
| Language | `uk` |
| Payload | One joined input, 126-word script, plain text with sparse delivery tags |
| Settings | stability 0.35; similarity 0.93; a fixed seed |
| Text normalization | off |
| Provider output | MP3 44.1 kHz, 192 kbps |
| Decoded duration | 51.920 seconds |

A seed is a receipt detail, not a quality guarantee across speakers. The 17 successful outputs
were experiments, not a budget for the next task. Verify the provider's current request schema
before a paid call.

Plain continuous speech beat accent-heavy variants in model review. A stress dictionary
entry turned out wrong and was corrected. Short crops and whole-output reviews disagreed on
some words. Treat no stress dictionary, ASR or model judge as infallible.

## Performance detail that mattered

- Conversational speech had quick links between words, small hesitations and falling endings.
  Vlog introductions had a brighter address to the audience.
- The greeting invited the viewer in; it did not announce a trailer hero.
- A short internal aside needed a lower ending, and its separate words had to stay distinct.
- The jump from months of failure to millions of views needed a local numeric emphasis,
  not declamation of the whole paragraph.
- The closing launch line was short and stressed, with room left for the beat.

Build this map from each new person's own evidence. Never carry one person's catchphrases into another.

## The approved postprocessing family

The source MP3 was preserved. No clipping was found, so aggressive cleanup was unnecessary.
The final processor did not regenerate speech, shift pitch or stretch time. The exact two
presets are in `postprocess-template.json`.

| Setting | Clean (default delivery) | Soft (alternative) |
|---|---|---|
| High-pass | 55 Hz, 2 poles | same |
| Broad EQ | 3100 Hz, Q 1.1, −1.5 dB | 3100 Hz, Q 1, −2.2 dB; shelf 5800 Hz −0.6 dB |
| De-esser detector / energy-fraction threshold | 4200 Hz / 0.12 | 4000 Hz / 0.09 |
| Ratio / maximum cut | 2.5 / 3.5 dB | 3 / 5 dB |
| Attack / release | 3 / 65 ms | 3 / 80 ms |
| Shelf transition | 3500–5300 Hz | 3300–5200 Hz |

Implementation:
- STFT of 2048 samples, hop 256 at 48 kHz.
- Energy-fraction detector, smoothed gain and a raised-cosine frequency transition.
- Spectral phase preserved within the de-esser, and the exact original sample count after
  reconstruction. IIR EQ has its own phase response, so the chain is not phase-neutral.

Comparisons use constant gain to −19 LUFS, lower if the peaks need headroom. There is no new
compressor or limiter. Before, clean and soft measured −19.00, −19.01 and −19.02 LUFS.
High-frequency-dominant windows showed about 4–6 dB less 4.5–8 kHz energy.

WAV exports are 24-bit/48 kHz; MP3 exports are 320 kbps. A larger container cannot recover
detail missing from the lossy generator output.

## What not to repeat automatically

- An Audio Isolation pass on the synthetic take changed details and was rejected. It is still
  useful for noisy *reference* recordings.
- Model judges disagreed on clean versus soft. The owner approved the delivery without choosing.
- Phrase-level F0 transfer (Praat overlap-add) was an experiment and is not part of the final
  chain. Older stock voices, StyleTTS2, OmniVoice and Voice Changer are exploratory history.
