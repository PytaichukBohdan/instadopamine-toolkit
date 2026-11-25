# The four stages

Every video is made in one style (`../STYLES.md`) and stars people from `../cast/`. Each stage
writes into `productions/<slug>/`. You approve each stage before the next one starts.

## 1. Input: from an idea to a brief

- Keep the idea **verbatim** in `input.idea`.
- Save references under `refs/`. Give each one line of **TAKE** (what it supplies) and **DO NOT TAKE**
  (people, faces, light, grade, depth of field, framing, props) to stop contamination.
- Reference video: measure it (ffprobe, scene cuts, a 30-frame contact sheet). Decide whether it is
  a *style* reference (re-shoot in your own world) or a *source* to re-cast (motion control).
- Music: save it as `refs/music.*` and build a beat grid. When there is a song, start from it: it
  sets the length, the sections and the edit mode.
  - **beat-cut** (energetic montage): cuts land on beats or downbeats.
  - **phrase-cut** (calm slice of life): cuts follow phrases, actions and breaths.
- Pre-production: a few-sentence storyline, a moodboard (with take / don't-take notes), and a
  character bible (name, one-word trait, signature prop, world).
- Pick **one format** from the style's `formats.md` and write **one trick sentence**: the single
  technique the film is built around.
- Ask only real forks: destination (4:3 or 9:16), speaking on camera, real brands in frame.

Output: `brief.md` (from `templates/brief.md`), `refs/`, and a first `production.yaml`.

## 2. Preview passport: see the film before any paid generation

1. **Story**: the logline, the trick and the shot list. Per shot, fill in:
   - id, in and out times, camera, lens and block codes;
   - timecoded beats, the acting task and sound;
   - the transition, and the Stage-3 model and duration.
2. **Cast sheet in costume** (the "golden take"): 2–3 sheets from the person's passport portrait
   and baseline sheet. Keep the best one. Check the face, the marks and the costume details.
3. **Location plates**: one empty plate per location ("no people"), referenced by every frame.
4. **Preview frames**: one start frame per shot (`tools/preview_frames.py`, Codex image tool, at most 5 references).
5. **Prompts**: `tools/assemble_prompts.py`. It warns about any unfilled `[SLOT]`.
6. **Page**: `tools/build_preview.py` → `site/`. Publish it noindex and check the URL before sharing it.

Write each shot as a director would brief it:
- Give a one-line emotional backstory in `acting:`.
- Write the camera as a numbered plan ("1. start low on the feet… 2. slowly rise…").
- Keep generated clips to about 8 s or less, and split a one-take that keeps failing into shots.

Iteration: feedback arrives by shot id ("s03: make it night"). Then:
- bump `version` and append the words verbatim to `feedback:`;
- regenerate only the touched frames, and keep the superseded versions;
- republish at the same URL.

## 3. Generation (only after an explicit go)

This is a ladder: spend only on what has already been approved as a still.

| Step | What | Typical model · settings |
|---|---|---|
| 1 | Final character sheet in costume | Seedream v5 Pro · 16:9 · 2k |
| 2 | Empty location plates | Soul Cinematic · 16:9 · 1080p |
| 3 | Start frames (or the approved preview frames), relit to each scene | Seedream v5 Pro · 2k |
| 4 | Draft pass, pick winners | Seedance draft · 480p |
| 5 | Final clips | Seedance · delivery aspect · 1080p · 4–10 s |
| 6 | Re-cast shots, if the format uses a source video | Higgsfield motion control |
| 7 | Edit, sound, grade match, export | `tools/cut_from_production.py` |

- Price first with `tools/higgsfield.py estimate` (free). Generate with
  `tools/higgsfield.py generate <yaml> <shot> --resolution 480p --confirm-spend`.
- QA every clip against the shot's FAIL lines and the cast's identity (face, marks, which side).
- Keep a ledger of every take and what it cost. Never buy credits or change plans on your own.

## 4. Packaging (optional)

Publish in the style's own distribution DNA: its titles, hooks, series names, cover frames and
making-of posts, as recorded in the style's `DNA.md` (reach section).
