# Skills and harnesses

All five skills ship with this repository. Claude Code loads them from `.claude/skills/`
(links to the folders below) whenever a session starts inside the repo. To install them
for every project:

```bash
python scripts/install_claude_skills.py --check   # missing / same / different, per skill
python scripts/install_claude_skills.py           # copies missing skills; never overwrites a changed copy without --force
python scripts/install_voice_skill.py --check     # Codex copy of voice-clone-dna
python scripts/install_passport_skill.py --check  # Codex copy of person-passport
```

| Skill | Source folder | What it does |
|---|---|---|
| `person-passport` | `harness/person-passport/` | Creator DNA of a published person: dated clean visual items, a phrase bank with original audio, recency kept apart from recurrence. |
| `voice-clone-dna` | `harness/voice-clone-dna/` | Voice clone (ElevenLabs IVC), phrase and prosody map, per-occurrence stress review, gentle postprocessing with loudness-matched comparisons. Ships its own helper scripts. |
| `person-visual-passport` | `toolkits/passport/skill/` | Photoreal identity sheets of a real person from their own photos and videos. |
| `video-dna-extract` | `toolkits/video-dna/skills/video-dna-extract/` | Learn a video creator's production DNA and register it as a style. |
| `video-dna-make` | `toolkits/video-dna/skills/video-dna-make/` | Make a video in a registered style, starring a passported person: input → preview passport → generation → packaging. |

## Third-party skills the workflow can call (install them from their vendors)

| Skill | Vendor | Used for |
|---|---|---|
| `browser-use` | Browser Use | Logged-in Instagram feed and Highlights capture; page checks and screenshots |
| `higgsfield-generate`, `higgsfield-soul-id` | Higgsfield | Image-to-video clips; a reusable identity for a synthetic persona |
| `hyperframes` family, `media-use` | HeyGen HyperFrames | Alternative HTML video compositions and media sourcing |

ElevenLabs, OpenAI, Gemini and Higgsfield are paid APIs: state the cost before spending.
