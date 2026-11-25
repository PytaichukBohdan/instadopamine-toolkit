# InstaDopamine toolkit

Turn a creator's public accounts into a **creator DNA** (a source-linked wiki of how they
look, talk, dress, film and edit), then make new content in their voice and style: a
cloned voice, a likeness pack, a storyboard, a soundtrack and a video.

This is the public toolkit: code, agent skills and guides. It contains **no person's data**.
Every wiki, recording, image and analysis you produce stays in your own private storage.

```
Instagram / Telegram / YouTube link
   │  collect (private corpus: media + SHA-256)
   ▼
analyze (frames every 3 s + full-audio ASR; OpenAI, Gemini or local Whisper)
   ▼
compile → wiki/<handle>/ (passport, atlas, phrase bank, sources, coverage, log)
   ├─ instadna build / edition → static site, login-protected by default → Cloudflare Pages
   ├─ voice-clone-dna  → ElevenLabs clone, stress review, gentle postprocessing
   ├─ person-visual-passport → identity sheets from the person's own photos and videos
   └─ storyboard → frames → video/ engine or video-dna-make → soundtrack / video
```

## Start here

- **End to end, a new influencer:** [docs/NEW-INFLUENCER.md](docs/NEW-INFLUENCER.md)
- **Skills for Claude Code and Codex:** [harness/SKILLS.md](harness/SKILLS.md). Claude Code loads all
  five from `.claude/skills/` when you open this repo.
- **Rules for the evidence wiki:** [docs/WIKI-RULES.md](docs/WIKI-RULES.md)
- **Instructions for agents:** [CLAUDE.md](CLAUDE.md), [AGENTS.md](AGENTS.md)

## Install and check

Requires Python 3.11+ and FFmpeg. Node 22+ is needed for the Telegram collector and the
tests; bun and Chrome for the video engine.

```bash
uv venv && uv pip install -e . && source .venv/bin/activate   # '.[local-asr]' adds faster-whisper
uv pip install numpy scipy soundfile                          # voice and audio scripts
python -m unittest discover -s tests
for t in tests/*.test.mjs tests/*.test.cjs; do node --test "$t"; done
python scripts/install_claude_skills.py --check               # skills for every Claude Code project
```

## First run

```bash
instadna run https://www.instagram.com/<handle>/ --root /private/<handle>/run-1 --wiki ./wiki/<handle> --workers 2
instadna lint --wiki ./wiki/<handle> --root /private/<handle>/run-1
instadna build --wiki ./wiki/<handle> --output ./dist            # protected by default; see below
```

`collect`, `analyze`, `compile`, `lint`, `build` and `edition` also run separately. Re-running
on the same corpus resumes cached work. The README of each folder and the runbook cover
Highlights, Telegram, YouTube, the phrase bank, the voice and the video.

## Keys and accounts (bring your own)

| Need | Used for |
|---|---|
| `OPENAI_API_KEY` | default analysis model (`--model`), Whisper ASR |
| `GEMINI_API_KEY` | large-scale media and text analysis, YouTube by URL |
| ElevenLabs key | voice clone, TTS, music bed |
| Telegram API id, hash and user session | reading channels your account already belongs to |
| Instagram browser session (storage state) | logged-in feed and Highlights capture |
| Higgsfield login | image-to-video clips |
| Cloudflare token | Pages deploys |

All of these are paid or rate-limited services: a run costs money. Nothing here stores a key.

## What the code enforces

- **Honest coverage.** A partial scrape is never called a full archive; failed retrievals are logged.
- **No face recognition.** People are linked only by textual attribution. There are no passports
  for incidental minors and no inferred private traits. Guests' views are not the host's.
- **One person, one entity.** Evidence, phrases, voices and likenesses are never mixed between people.
- **Consent.** Cloning a real person's voice requires a recorded consent statement
  (`scripts/create_elevenlabs_ivc.py --consent`), and so does generating their likeness.
- **Allowlist publication.** Sites contain only selected, hash-checked derivatives. A wiki whose
  `publication-policy.json` requires a login cannot be built public. The Cloudflare Pages worker
  fails closed: 503 without its secrets, 401 without a login, on every path.
- **Synthetic media is labelled** as synthetic.

## Layout

| Path | What |
|---|---|
| `instadna/` | Python package and CLI: collect, analyze, compile, lint, build, edition; site renderer and Pages workers |
| `scripts/` | Collectors (Instagram browser, Highlights, Telegram, YouTube), analysis, atlas, phrase bank, passport images, voice, storyboard, music, clips, mixing, protected deploy |
| `harness/` | `person-passport` and `voice-clone-dna` skills, and `SKILLS.md` |
| `toolkits/passport/`, `toolkits/people/_template/` | Visual identity sheets (`person-visual-passport`) |
| `toolkits/video-dna/` | Learn a video creator's style and make videos in it (`video-dna-extract`, `video-dna-make`) |
| `video/` | Vertical, word-synced caption engine (bun + WebGL, adapted from pdoom-video, MIT) |
| `tests/` | Python and Node tests |

## License

No license has been chosen yet: all rights reserved by the author until one is added.
`video/` contains code adapted from [mexicat/pdoom-video](https://github.com/mexicat/pdoom-video)
under its MIT license (`video/LICENSE.pdoom-video`).
