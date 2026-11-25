---
name: video-dna-make
description: Make a video in a chosen creator's DNA style (registered styles in toolkits/video-dna/STYLES.md), starring a person from a visual passport. Runs the stages Input → Preview passport (cast, frames, storyline; iterated with the requester) → Generation (Higgsfield) → optional packaging. Use when someone sends a video idea, asks for a reel / short / ad / music video, a storyboard or preview passport, or wants to re-cast a clip with a passported face. If no style is named, ASK which one before starting. Not for extracting a new creator's DNA (video-dna-extract), building a person's visual passport (person-visual-passport), or social-media identity analysis (person-passport).
---

# Make a video in a creator's DNA

Everything lives in `toolkits/video-dna/`. Read its `README.md` and `workflow/README.md` first, and run the tools from that folder.

## Step 0: which style?

- Styles are listed in `STYLES.md`. If none is registered, build one first with `video-dna-extract`.
- If the request does not name a style, ask before doing anything else. List the registered
  styles, plus the option to analyse a new creator first.
- Set `style: <id>` in `productions/<slug>/production.yaml`; the tools refuse to run without it.
- Read the style's `DNA.md` (the genes first) and `formats.md`. Also read its look rules
  (`finals/LOOK.md`) and channel notes (`youtube/`), if it has them.

## The stages (never skip stage 2)

1. **Input**: normalise the text, references and music into `productions/<slug>/`.
   - If there is a song, start from the music (beat grid).
   - Write a short storyline brief, a moodboard and a character bible.
   - Pick ONE format from the style's `formats.md` and write ONE trick sentence.
   - Ask only about real forks: destination (4:3 or 9:16), speaking on camera, real brands.
2. **Preview passport**:
   - Run `tools/assemble_prompts.py` and fix every unfilled-slot warning.
   - Make the costume sheet with `tools/preview_frames.py <yaml> sheet`, then every shot with `--jobs 3`.
     This uses the Codex CLI image tool: at most 5 references, about 1.5 MP.
   - Keep the golden take of the costume sheet. QA each frame for the face and for marks and accessories on the right side.
   - Build with `tools/build_preview.py`, publish noindex, verify the URL, and send it.
   - Iterate by shot id: feedback goes verbatim into `feedback:`, `version` goes up, and only the touched shots are regenerated.
3. **Generation**: **only after an explicit "go"**, because it spends Higgsfield credits.
   - Price it first with `tools/higgsfield.py estimate <yaml>` (free).
   - Draft at low settings, upscale the winners, QA every clip, keep a credit ledger, then run `tools/cut_from_production.py`.
   - API generation is `tools/higgsfield.py generate … --confirm-spend`; it refuses to run without the flag. Never buy credits.
4. **Packaging (optional)**: follow the style's distribution DNA.

## Working with the chatbot

Brief the model in plain language: the story, an emotional backstory, and a numbered camera
plan "as if holding the camera". Iterate by talking. Every prompt is assembled from the style's
blocks, and feedback is applied as plain-language changes.

## Rules

- **Identity:** cast blocks (`cast/<name>.md`) are pasted word for word, from that person's own
  visual passport and with their consent. Never paste the style creator's own persona text.
- **Creators' corpora** are private study material. Public pages may quote short excerpts, with links back.
- **Review pages:** noindex, with no raw inputs or credentials.
- **Scratch files:** keep heavy ones outside the repository.
