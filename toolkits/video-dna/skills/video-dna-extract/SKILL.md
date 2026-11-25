---
name: video-dna-extract
description: Extract a video creator's complete production DNA (how they ideate, prompt, shoot or generate, light, edit, score, package and distribute their videos) from their public posts, prompts and videos, and register it as a new style in toolkits/video-dna/STYLES.md, so videos can later be made "in their DNA". Use when asked to analyse, study, break down or "extract the DNA" of another AI or video creator, or to add a new style. Not for making a video (video-dna-make), not for a person's identity or phrase passport from social media (person-passport), not for a visual passport of a person (person-visual-passport).
---

# Extract a creator's video DNA as a new style

The folder contract is in `toolkits/video-dna/STYLES.md`. Work on a branch of your private copy. Keep heavy scratch files and the corpus outside git (for example `/private/<style-id>/`).

## 1. Sources: collect everything public, and record coverage honestly

| Source | How (proven on the first style) |
|---|---|
| Higgsfield blog (prompts + settings) | `tools/scrape_higgsfield_blog.py <username> /private/<id> --media`. Public API plus Yjs decode; gives every prompt with model, aspect, resolution and duration. |
| YouTube | Metadata, chapters, descriptions and storyboards via a working Invidious instance (`/api/v1/videos/<id>`; storyboard sprites straight from `i.ytimg.com`). **YouTube may block a server** for audio and captions. Run the captions-only yt-dlp command in `tools/ingest_youtube.py` on an unblocked machine, then `--from-dir`. Partial audio → local faster-whisper (`small.en`, int8, CPU). |
| Instagram / TikTok | Public pages only. Logged-out IG is a login wall: stop and ask; never use account cookies without permission. Record follower counts when visible. |
| Other sites (Notion prompt pages, Gumroad, Patreon, personal sites) | Fetch only what is public; note anything paywalled. |
| Published tools (e.g. a `.skill` or prompt library) | Keep verbatim in `<id>/source/`; they are the strongest evidence of method. |

Write `<id>/corpus/` (Markdown per post, `prompts.json`, `media.json`, comments, YouTube `index.json` / `descriptions.md` / transcripts). For coverage, record separately what was attempted, recovered, read in full, transcribed, and only seen as storyboards.

## 2. Measure the finished work (numbers, not impressions)

- `ffprobe` every final: length, size, fps, aspect.
- Cut detection: `ffmpeg select='gt(scene,0.28)'`, then **frame-check the counts**. The detector under-counted 4 of 8 films in the first study.
- Beat alignment: a librosa beat tracker. Compute the share of cuts within ±60 ms of a beat against 2,000 random cut times, which separates beat-cut from phrase-cut editing.
- A grade window per film: mean luma, p1/p99, saturation, warm and green bias.
- Contact sheets plus per-shot strips (frames at 8%, 50% and 92% of each shot).
- Prompt-corpus statistics: models and settings per period, prompt-length trend, and the share of prompts containing each signature marker (regexes).

## 3. Read in parallel, with one fixed schema

Fan out general-purpose subagents (about 6, balanced by corpus size). The per-source prompt is `analyst-prompt.md`; fill its `{…}` slots and **paste the group's slugs in** (an unfilled template wastes an agent).
- Each subagent writes `<id>/posts/<slug>.md` in 16 sections and a group synthesis `<id>/groups/gN.md` (top-20 techniques with locators, evolution, dialects, deviations from the creator's own stated method, reach patterns, surprises).
- One more subagent does the frame breakdown of the finals (`finals-prompt.md`), producing `<id>/finals/<film>.md` and `<id>/finals/LOOK.md`.
- One more does the channel (`youtube-prompt.md`), producing `<id>/youtube/YOUTUBE.md` and `videos.md`.

Read the syntheses yourself, plus a sample of posts in full. Never summarise agent output you haven't read.

## 4. Synthesise the DNA (you, not an agent)

- **`DNA.md`:** a one-page list of genes, then numbered sections in this order: who they are and how they work · visual signature (measured rules) · story · edit (measured) · production pipeline (models, settings, ladder, costs) · prompt engineering (their rules, constants, dialects, precision, reference control, failure engineering) · camera · light and grade · tricks · performance · sound and music · identity and wardrobe · re-cast / motion control (if used) · community and reach · business (how they earn, estimated with sources) · evolution · where they break their own rules · pitfalls · **adaptation to your cast** (their passports) · gaps.
- Quote ≤25 words with locators (`slug #n`, `video id mm:ss`); mark interpretation; separate measured from inferred.
- **`formats.md`:** recipe cards (what it is, measured form, trick template, pipeline, blocks, reach, cast adaptation).
- **`stats.md`:** every number, with its method.
- **`blocks/`:**
  - the creator's own published blocks, verbatim (frontmatter `source: verbatim`);
  - blocks derived from their posts, with `evidence:` locators.
  
  Placeholders are written `[KEY]` or `[KEY — hint]`. `tools/assemble_prompts.py` warns about unfilled slots.
- **`business.md`** (optional): how they earn, with the official program terms behind it.

## 5. Register and validate

- Add a row to `video-dna/STYLES.md`: id, "<Name>'s approach", sources, status, what it's best for, entry points. Styles are called by the creator's name.
- Validate: copy `workflow/templates/production.yaml`, set `style: <id>`, list some of its blocks, and run `tools/assemble_prompts.py`. The result should have zero unfilled slots and no leftover creator-persona text.
- Optional: one worked preview example (`tools/preview_frames.py`, subscription only).

## 6. Report and deliver

- **Report:** a noindex static report. Show the creator's work only as small, credited strips with links. Never republish the corpus.
- **Commits:** in logical chunks; open a PR. Keep the style folder in your private copy.
