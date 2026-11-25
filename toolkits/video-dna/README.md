# video-dna: make videos in a creator's DNA

The pipeline has four stages:
1. **Input**: text, idea, references, music.
2. **Preview passport**: cast, frames, storyline and approach, iterated with you.
3. **Generation**: Higgsfield (Seedream, Seedance, motion control).
4. **Packaging** (optional).

A **style** is one creator's video-making DNA: how they ideate, prompt, shoot or generate, light,
edit, score and publish. Build one with `skills/video-dna-extract/SKILL.md`, then make videos in it
with `skills/video-dna-make/SKILL.md`. No style ships with this toolkit. A style is a study of a
real creator's work, so keep it in your private copy and quote their material only briefly, with credit.

## Layout

```
video-dna/
  STYLES.md        registry of your styles + the folder contract every style follows
  <style-id>/      one creator's DNA (DNA.md, formats.md, stats.md, blocks/, finals/, posts/ …); private
  cast/<name>.md   identity blocks (FACE / BODY / MARKS) for each person you cast, from their visual passport; private
  skills/          video-dna-extract (add a style) · video-dna-make (make a video in a style)
  workflow/        README.md (the four stages) + templates (brief.md, production.yaml, prompts.md)
  tools/
    scrape_higgsfield_blog.py   scrape a Higgsfield creator's public blog (prompts + settings)
    ingest_youtube.py           YouTube captions/metadata, or local Whisper transcripts
    assemble_prompts.py         production.yaml → every image and video prompt, in the style's block order
    preview_frames.py           costume sheet + one preview frame per shot via the Codex image tool
    build_preview.py            production.yaml → static preview-passport page (noindex)
    higgsfield.py               Higgsfield API: check / estimate (free) and generate (needs --confirm-spend)
    cut_from_production.py      accepted clips + music → final cut
  productions/<slug>/           one folder per video; private
```

## Quick start

```bash
cd toolkits/video-dna
mkdir -p productions/<slug>/refs && cp workflow/templates/production.yaml productions/<slug>/
# set style: <id> and cast: [<name>], fill the brief and the shot list (workflow/README.md)
python3 tools/assemble_prompts.py productions/<slug>/production.yaml
python3 tools/preview_frames.py productions/<slug>/production.yaml sheet
python3 tools/preview_frames.py productions/<slug>/production.yaml --jobs 3
python3 tools/build_preview.py productions/<slug>/production.yaml
# after an explicit go: price it (free), then generate and cut
python tools/higgsfield.py estimate productions/<slug>/production.yaml
python3 tools/cut_from_production.py productions/<slug>/production.yaml
```

Python deps: `pyyaml`. For the Higgsfield API, install `tools/requirements.txt` and put
`HF_KEY=<key-id>:<key-secret>` in a git-ignored `.env.local`. Beat analysis also needs `librosa soundfile numpy`.
For the scraper: `cd tools && npm install`.

## Rules

- Higgsfield generation spends money. Run `check` and `estimate` first (both free); `generate` refuses to run without `--confirm-spend`.
- Preview pages are noindex. Never publish raw inputs, credentials or a creator's corpus.
- A person's face goes into a video only from their own visual passport, and only with their consent.
