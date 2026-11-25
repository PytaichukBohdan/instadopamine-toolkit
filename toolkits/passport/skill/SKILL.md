---
name: person-visual-passport
description: Build a photorealistic visual "digital passport" (identity character sheets) of a real person from owner-supplied inputs — face selfies, a full-body turnaround video, an emotion and speech video, close photos of tattoos and marks — generated with the Codex CLI built-in image tool (gpt-image) on the ChatGPT subscription and published as a noindex review page. Use whenever the owner asks for a digital passport, character sheet, identity reference set, likeness pack or "паспорт" of a person, including himself. Not for social-media creative-DNA analysis (that is the person-passport skill).
---

# Person visual passport

> The toolkit is in `toolkits/` (`toolkits/passport/`, `toolkits/people/_template/`). Run the commands below from `toolkits/`. Person folders with real inputs stay private and are never committed.

Owner-approved method (10 October 2026). The toolkit is in `passport/`, the starting skeleton in `people/_template/` and the operating notes in `passport/README.md`.

## Owner rules (do not bend)

- **Subscription only.** Generate images with `codex exec` and the built-in `image_gen` tool, signed in with ChatGPT (the `/usr/local/bin/codex` wrapper strips `OPENAI_API_KEY`). Never use the gpt-image API/CLI with an API key, and never fall back to it. If Codex returns no image, stop and report it.
- **Neutral baseline clothing everywhere:** plain white fitted crew-neck T-shirt, plain black straight-leg trousers, barefoot. No costumes, prints, logos or art variants unless the owner asks. The passport is a reference and must not steer later styles. The body sheet uses minimal neutral clothing to show marks.
- **Hair and real-life corrections from the person win over the photos** (e.g. "more well-rounded but natural", "teeth are whiter in real life").
- **One person, one entity.** Register `person:<slug>` in your private entity registry and never reuse another person's identity, media or phrases.
- **Privacy.** Raw inputs and the reference pack stay private (gitignored, never published). Publish only generated images and prompts, marked noindex, with no login (owner rule 2026-10-07).
- **Pronouns.** Use the person's stated pronouns; default to they/them (`person.json`).

## What to ask for (when missing)

1. 15–25 face photos: front, both three-quarters, both profiles, back three-quarter; even light; current hair.
2. A 20–40 s full-body 360° turnaround video in fitted clothes.
3. A 30–60 s emotion + speech video facing the camera at eye level (ideally shot by someone else at 1.5–2 m on the 2× lens). Expressions: neutral, soft smile, big smile with teeth, real laugh, serious, thinking (glance aside), surprised, skeptical raised brow, smirk, mid-word on ah/oh/ee/m/f; optionally concerned, annoyed, sad, excited, determined, eyes closed, and gaze left/right/up/down. Then 30–60 s of just talking.
4. A close photo plus a wider placement photo of every tattoo, scar, birthmark and always-worn accessory, and which side it's on. Check orientation yourself: phone photos of one's own arm are often upside down, and selfies may be mirrored.
5. Optional: a real smile photo, and real-life notes (teeth colour, hair goal).

## Steps

1. **Set up.** `cp -r people/_template people/<slug>`, fill in `person.json` (name, slug, pronouns, inputs dir, `work/<slug>/refpack`, `data/<Name>/passport`, publish branch), and register the entity.
2. **Prepare references** with `python passport/prep_refs.py --person people/<slug> …`:
   - `convert`: convert the photos and open the contact sheet yourself.
   - `frames <turnaround>.MOV --fps 2`: pick front, side and back timestamps.
   - `frames <emotion>.MOV --fps 4 --box …` and `transcribe <emotion>.MOV` (local faster-whisper, no API). Spoken labels locate the segments, but **label every frame by what the face shows**: people misname their own expressions.
   - Write `picks.json` (crops plus boards `face_angles`, `body_turn`, `emo_core`, `emo_speaking`), then run `picks`.
3. **Write the identity** in `prompts/_identity.md` from the evidence, using the template's fields: face, facial hair, skin marks with the person's own left/right, the hair goal, build, every permanent mark (lettering spelled letter by letter), teeth and expressiveness. Keep `_baseline.md`.
4. **Generate** with `python passport/gen.py --person people/<slug> <job> …` (3–4 jobs in parallel, about 2–5 min each).
   - Start with `id-portrait`.
   - Once approved, add it to `picks.json` as `passport_portrait` (`"src": "generated:id-portrait-vN.png"`), since later sheets use it as the look anchor.
   - Next: `headshot-34`, `head-rotation`, `head-back`, `fullbody-front`, `sheet-baseline`.
   - Then: `sheet-body`, `details`, `expressions`, `speaking`, `scene-street`.
   - Edit the template prompts where the person differs (marks, columns, refs).
5. **Review every image yourself** against the references and regenerate with one targeted change. Check:
   - the likeness;
   - the profiles face opposite ways;
   - every mark is on the correct side and hidden under clothing where covered, with no invented tattoos;
   - lettering is exact;
   - clothing is neutral and the hair is as specified.
6. **Build the page.** Fill `selection.json` with an honest note per image, plus pending items, method and limits, then:
   - run `python passport/build_site.py --person people/<slug>`;
   - check it with local Browser Use, desktop and 390 px;
   - deploy with `wrangler pages deploy work/<slug>/site --project-name <publish.pages_project> --branch <publish.branch>`;
   - curl every link and confirm the `x-robots-tag: noindex` header.
7. **Deliver.** Keep only the selected versions in the output folder (git history keeps the rest), commit, push to the private repo, and report with links at the end.

## Known model quirks (Codex image tool, Oct 2026)

- At most 5 reference images per call; combine the rest into boards. Output is about 1.5 MP with no size control, so add single-image anchors next to the multi-view sheets.
- 2×3 head grids repeat the same profile direction. Use the 1×5 rotation strip with each head pinned to a reference image in order.
- Side views drift to face right. Put the side with no marks toward the camera, or state explicitly which arm is visible and that it is clean.
- Tattoos covered by a T-shirt leak onto the arms. State "hidden under the T-shirt, never moved".
- Hair copies the selfies' texture unless the description is decisive. Column 1 of a sheet is often cropped tight on the left.

## Host gotchas

- The root disk is often 100% full. Keep `work/` on `/mnt/data` (symlink) and redirect long command output to files.
- Never `pkill -f <pattern>` when the pattern appears in your own command line; it kills your shell. Kill by PID.
- Check that a port is free (`ss -ltn`) before serving a local preview.
- Deploy review pages as a branch alias of one Pages project, to stay under the account's project limit.
