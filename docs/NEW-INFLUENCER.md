# Make a new influencer, end to end

This is the runbook for taking a new person, from a link to a finished piece of content in
their voice and style. It strings together every skill and harness in this repository, in
the order they were used on two real creators. Each stage says what goes in, what you run, what comes out, and what the owner
approves before the next stage starts.

**Skills:** Claude Code loads all five automatically when a session starts in this repo
(`.claude/skills/`). To use them elsewhere, run `python scripts/install_claude_skills.py`.

| Stage | Skill | Harness / tools |
|---|---|---|
| 1–4 Creator DNA and passport | `person-passport` | `instadna` CLI, `scripts/collect_*`, `analyze_*`, `build_atlas.py`, `build_phrase_bank.py` |
| 5 Visual identity (likeness pack) | `person-visual-passport` | `toolkits/passport/` |
| 6 Voice | `voice-clone-dna` | `scripts/create_elevenlabs_ivc.py`, `synthesize_elevenlabs.py`, `postprocess_voice.py` |
| 7 Script and storyboard | (this runbook) | `recipes/<person>-video/`, `generate_storyboard_frames.py`, `build_storyboard.py`, `video/` engine |
| 8 Video | `video-dna-make` (+ `video-dna-extract` for a new style) | `toolkits/video-dna/`, or `video/` + Higgsfield clips |
| 9 Publish and review | (this runbook) | `instadna edition`, `scripts/deploy_report.py` |

There are two routes to "make a new influencer":

- **A. A real creator** (the route used twice here): learn the person from their published
  content, then make new content as them, **with their consent** for voice and likeness.
- **B. A new synthetic persona** (not yet done in this repo): borrow the *format and
  production* DNA of one or more reference creators, and give the persona its own designed
  face and voice. Stages that change are marked **B:** below. Never copy a real person's
  face, voice, name or catchphrases into a synthetic persona.

---

## 0. Intake: who, consent, where the data lives

- Get the links (Instagram, Telegram, YouTube) and the goal (a DNA report only, or content as well).
- **Consent:** cloning a voice or generating a likeness of a real person needs that
  person's consent, confirmed by the owner. `create_elevenlabs_ivc.py` refuses to run without
  a `--consent` statement.
- Register one entity per person (`person:<slug>`). Never mix two people's evidence, phrases or voice.
- Put the private corpus outside the repository, on a large volume: `/private/<person>/` (chmod 700).
  A 17 GB download once filled the root disk and broke every session on the machine.
- Accounts you may need: Instagram browser session, Telegram user session, YouTube cookies,
  plus `OPENAI_API_KEY`, `GEMINI_API_KEY`, an ElevenLabs key, a Higgsfield login and Cloudflare.
  These are paid third-party services: say what a step will cost before running it. Claude
  itself runs on the subscription only.

**B:** pick one to three reference creators for format and style, and write a one-page persona
brief: who they are, what they talk about, audience, language, and the tone in three adjectives.

## 1. Collect

```bash
C=/private/<person>
# Instagram: public discovery (simple), or the logged-in grid capture (recovered 2,294 of 2,302 posts in one real run)
instadna collect https://www.instagram.com/<handle>/ --root $C/instagram
python scripts/collect_instagram_feed_browser.py --username <handle> --storage-state $C/ig-state.json --output $C/feed
python scripts/build_instagram_corpus.py --feed $C/feed --root $C/instagram --profile-posts <N shown on profile>
# Highlights (needs the owner's browser session)
python scripts/collect_highlights_browser.py --username <handle> --storage-state $C/ig-state.json --output $C/highlights
python scripts/download_highlight_media.py $C/highlights
# Telegram: public preview, then read-only MTProto for large media
python scripts/collect_telegram_public.py --channel <channel> --output $C/telegram/public
node scripts/fetch_telegram_media.cjs --channel <channel> --ids 12,34 --output $C/telegram/mtproto
# YouTube: listing works; media download can hit a bot check from a server (Gemini reads videos by URL)
python scripts/collect_youtube.py --handle <handle> --output $C/youtube
```

Out: a private corpus with SHA-256 per file, plus a coverage count (attempted, recovered, failed).

**B:** collect the reference creators' content in the same way. It is study material only and stays private.

## 2. Analyze

```bash
instadna analyze --root $C/instagram --workers 2                 # frames every 3 s + full-audio ASR (OpenAI)
instadna analyze --root $C/instagram --asr local                 # or local faster-whisper for the audio
python scripts/analyze_media_gemini.py --platform instagram --root $C/instagram --out $C/analysis --creator "<name>"
python scripts/transcribe_telegram.py --root $C/telegram --workers 4
python scripts/analyze_telegram.py --root $C/telegram --kind text   # and --kind audio
python scripts/analyze_texts_gemini.py --private $C/compiled --out $C/analysis/text
```

If a provider fails mid-run (credit, permission), finish with the analyses you have and with
local models. Do not borrow keys from other projects; report the gap.

## 3. Compile the DNA wiki

```bash
instadna compile --root $C/instagram --wiki wiki/<handle>         # Instagram-only path
python scripts/compile_person.py --instagram … --wiki wiki/<handle> --as-of <YYYY-MM-DD>   # multi-platform path
python scripts/person_stats.py --private $C/compiled --text-analysis $C/analysis/text --wiki wiki/<handle>
python scripts/write_source_notes.py --wiki wiki/<handle> --private $C/compiled --owner-marks "<name stems>" --own-handles "<handle>,<channel>" --allow "…"
instadna lint --wiki wiki/<handle> --root $C/instagram
```

Out: `wiki/<handle>/`: index, identity core, narrative, vocabulary, production, people,
sources, coverage, questions, log. Follow `wiki/AGENTS.md`: every claim links to a source,
there is no face recognition, guests' views are not the host's, and coverage is honest.

## 4. Passport: assets, phrases, time (skill `person-passport`)

```bash
python scripts/build_atlas.py --selection atlas-selection.json --corpus $C --wiki wiki/<handle> --as-of <date>
python scripts/generate_passport_images.py --engine codex --jobs recipes/<handle>-passport/jobs.json --wiki wiki/<handle> --recipes recipes/<handle>-passport
python scripts/build_phrase_bank.py --verifier local --selection … --corpus $C --transcripts … --families … --wiki wiki/<handle> --as-of <date>
python scripts/motifs.py … ; python scripts/expression_stats.py … ; python scripts/measure_voice.py …
```

Out: dated, separate visual items (image, description and use context each), an evidence
atlas, a phrase bank with original audio excerpts, and recency kept apart from recurrence.
`instadna run` alone is research, not a finished passport.

**Owner approves:** the DNA and passport.

## 5. Visual identity (skill `person-visual-passport`)

Use this when the person supplies inputs: 15–25 face photos, a 360° turnaround video, an
emotion and speech video, and close photos of every mark. Run it from `toolkits/`:

```bash
cd toolkits && cp -r people/_template people/<slug>     # person folders with real inputs are never committed
python passport/prep_refs.py --person people/<slug> convert
python passport/gen.py --person people/<slug> id-portrait     # then headshot-34, head-rotation, … (Codex image tool, subscription)
python passport/build_site.py --person people/<slug>
```

Without such inputs (as in one past run), anchor the image model on her real atlas photos plus a
four-view character sheet, and tell it "identity only, not pose". Otherwise it copies the
reference photos' pose.

**B:** design the face instead of capturing it. Make one approved portrait, then a multi-view
sheet from it (Codex image tool, or `higgsfield-soul-id` for a reusable identity). Check that it
does not resemble any real person in the reference set.

## 6. Voice (skill `voice-clone-dna`)

```bash
python scripts/create_elevenlabs_ivc.py --name "<Name> — InstaDopamine" --files $C/voice-refs/*.wav --language <lang> --consent "<who confirmed, when>" --output $C/voice/ivc.json
python scripts/synthesize_elevenlabs.py --script recipes/<handle>-audio/script-eleven.json --voice-id <private id> --output $C/voice/take-A
python scripts/align_script_words.py --audio <take>.mp3 --script <script> --lyrics <lyrics.json> --snap-db -45
python scripts/voice_delivery_metrics.py --audio <take>.mp3     # pitch peaks, endings, force: compare takes with numbers
python scripts/postprocess_voice.py --source <approved take> --recipe recipes/<handle>-audio/postprocess.json --output $C/voice/post
```

Lessons that cost rounds before:
- Use attributed references in the right speaking register (vlog, not interviews with guests).
- Review the stress of every word occurrence in Ukrainian and Russian (`за́пуски`: first syllable).
- "Serious, expert" came from full stops instead of exclamation marks, tags like matter-of-fact
  and firm, and stability 0.45. Calm takes read as flat, and energetic ones as "talking to children".
- Postprocess gently, with a loudness-matched before/after. Never regenerate an approved take automatically.

**B:** use ElevenLabs Voice Design (a described voice), not a clone, and keep its settings in `recipes/`.

**Owner approves:** the take. Record it by name, for example "take K".

## 7. Script and storyboard

1. Script: short lines in the person's own phrasing (from the phrase bank), about 30–60 s.
   Round 1 was rejected for long narrative text, so write short lines.
2. Measure the reference reels' shot mix before planning (one past run: 58 % the person, mostly
   non-frontal; 42 % people and objects).
3. Write the spec: `recipes/<handle>-video/roundN/make_spec.py` → `shots.json` (word anchors,
   prompts, caption zones). Keep one folder per round, so earlier rounds stay comparable.
4. Frames: `python scripts/generate_storyboard_frames.py --spec shots.json --wiki wiki/<handle> --manifest … --private-out …`
   (Codex image tool, at most 5 references). Regenerate a single shot with `--only Sxx`.
5. Compile and preview in the engine:
   ```bash
   python scripts/build_storyboard.py --spec … --lyrics … --envelope … --frames … --wiki wiki/<handle> --out wiki/<handle>/storyboard-roundN.json
   cd video/app && bun install && VIDEO_PROJECT=<project> bunx vite       # http://localhost:5173
   bun scripts/render.ts board --out ../out/board                            # one styled still per shot
   ```

Keep captions off the face. Snap word edges after inserting silence (`--snap-db -45`), or the captions run ahead of the voice.

**Owner approves:** the storyboard round, likeness included.

## 8. Video

Two routes. Pick one with the owner.

**8a. This repo's engine (vertical, word-synced captions):**
```bash
python scripts/compose_music_elevenlabs.py --plan recipes/<handle>-video/video/music-plan.json --output $C/video/music.mp3
python scripts/align_cuts_to_music.py --spec … --lyrics … --music $C/video/music.mp3 --out recipes/<handle>-video/video/shots.json
python scripts/generate_clips_higgsfield.py --plan clips-plan.json --frames-dir … --model <cheapest i2v> --out $C/video/clips   # needs: higgsfield auth login (owner)
python scripts/prepare_clips.py --storyboard … --clips $C/video/clips --out $C/video/frames
VIDEO_PROJECT=<project> VIDEO_CLIPS=$C/video/frames bun scripts/render.ts video --noaudio --out $C/video/edit.mp4
python scripts/mix_voice_music.py --voice <take>.mp3 --music $C/video/music.mp3 --lyrics … --out $C/video/mix.wav   # −14 LUFS / −1 dBTP
```
The music must be audible on phone speakers: check the 300 Hz–8 kHz band.

**8b. A creator's style (skill `video-dna-make`, toolkit `toolkits/video-dna/`):**
Input → **preview passport** (cast, frames, storyline; iterated with the owner) →
generation on Higgsfield only after his explicit "go" (`tools/higgsfield.py estimate` first,
which is free) → packaging. No style ships with the toolkit (a style is a study of a real creator, kept private). Build
one with `video-dna-extract` first. The cast block for the new person goes in
`toolkits/video-dna/cast/<name>.md`.

## 9. Publish, review, iterate

```bash
instadna edition --wiki wiki/<handle> --output /tmp/edition-<handle>          # refuses unless publication-policy requires a login
python scripts/deploy_report.py --directory /tmp/edition-<handle> --private-config $C/report-access.json --project instadopamine-<handle>-<session> --account-id <cf account>
```

- Person editions stay behind a login: production, preview and direct URLs are all checked.
  Give the owner the URL and say it needs the owner login; never write the password in a reply or report.
- Put the newest version at the top of the page, with each soundtrack next to its own frames.
- Every round: the owner's words verbatim → a new round folder → only the touched shots regenerated.

## 10. Deliver and remember

- Commit on a branch, open a PR, and merge after review. Never force-push.
- Keep the wiki's `log.md` and `coverage.md` current, and record the run in your private notes.
- Keep raw media, transcripts, voice IDs, cookies and keys out of git and off every site.

## Checklist

- [ ] Consent recorded (voice, likeness), entity registered
- [ ] Corpus on `/mnt/data`, coverage counted honestly
- [ ] DNA wiki lints clean; passport items, atlas and phrase bank done
- [ ] Likeness approved
- [ ] Voice take approved by name; stresses checked by ear
- [ ] Storyboard round approved
- [ ] Video or soundtrack delivered; music audible on a phone
- [ ] Protected site verified; PR merged; notes updated
