# Analyst prompt: per-source DNA extraction (one subagent per group)

Fill every `{…}` before sending; paste the slug list in full.

---

You are a film-craft analyst extracting the "creative DNA" of a video creator. Do it deeply and precisely: the owner wants to reproduce this creator's approach with his own character (a man with a photo "visual passport").

## Context
- Creator: {NAME} ({HANDLES}). {ONE-PARAGRAPH: what they make, tools and models they use, recurring persona or characters, what followers can "recreate"}.
- Corpus (read-only): `{CORPUS_DIR}/posts/<slug>.md`. Each source is converted in its original order: notes, media, and every prompt block with its model and settings header.
- Structured data: `{CORPUS_DIR}/prompts.json`, `media.json`, `posts_index.json` (dates, views, likes), comments, cover thumbnails.
- Their own published method, if any: `{SOURCE_FILE}`. READ IT FIRST so you can name techniques in their vocabulary and see where the posts use, extend or deviate from it.
- Optional: download at most ~3 images per source into `{SCRATCH}/img/` (downscaled with ffmpeg) if a technique can't be understood without them.

## Your sources (group {GROUP_ID})
{SLUG LIST}

Read EVERY one completely: every prompt, every note. Don't skim or sample; the craft is in the long prompts. Other agents cover the other sources.

## Output
For each source write `{OUT}/posts/<slug>.md` with exactly these sections (write "— none observed" to skip one):
1. **Card**: title, URL, date, views/likes, post type, deliverable format (duration, aspect, shots), models and parameters used (counts).
2. **Concept & hook**: the one trick, in a single sentence; the concept pattern; why it is shareable; the first 1–2 seconds.
3. **Story & edit structure**: beats and shot list with timecodes; how shots connect; the ending; the rhythm.
4. **Production pipeline**: ordered steps, the model at each step and why, reference-tagging conventions, how a viewer's selfie flows through.
5. **Prompt anatomy**: section order and headers, length, timecodes, coordinates, measurements, priority rules, FAIL lines, locks, bans. Quote the skeleton.
6. **Camera language**: moves, rigs, lenses, framing, focus; exact phrasing.
7. **Light & grade**: setups, practicals, grades, film stock, palette.
8. **Motion, physics & VFX tricks**.
9. **Performance direction**: acting tasks, gaze, restraint, the small task.
10. **Sound & music**: SFX, music, voice, sync.
11. **Identity & consistency**: face locks, sheets, wardrobe locks, counts.
12. **Negatives / bans**: generic vs inversions of the trick.
13. **Iteration, credit & failure notes**: their tips, failures, draft use, community pitfalls.
14. **Signature verbatim phrases**: 5–15 quotes of ≤25 words each, with `PROMPT #n`.
15. **Reusable recipe**: a generalized template that works with a DIFFERENT person (say what changes for a male lead), with placeholders and parameter settings.
16. **Uncertainties**.

Then write `{OUT}/groups/{GROUP_ID}.md`, covering:
- (a) the top 20 recurring techniques, with locators;
- (b) how the approach evolved by date;
- (c) prompt-structure patterns and length norms;
- (d) deviations from and extensions of their published method;
- (e) concept and reach patterns;
- (f) surprises.

Rules:
- Be evidence-backed; mark interpretation as interpretation.
- Keep quotes to ≤25 words.
- Don't invent anything.
- Write only inside `{OUT}/` and `{SCRATCH}/img/`.

Final reply: ≤350 words, the 10 most important DNA findings.
