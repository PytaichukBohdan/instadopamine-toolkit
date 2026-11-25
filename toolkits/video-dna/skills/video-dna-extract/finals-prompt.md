# Analyst prompt: frame-level breakdown of the creator's finished films

Prepare first: per-shot strips (frames at 8%, 50% and 92% of each detected shot, hstacked) in `{SCRATCH}/finals/strips/<film>/shotNN_<start>-<end>.jpg`, the cut list, and the beat-alignment JSON.

---

You are a cinematographer and colorist doing a frame-level breakdown of {NAME}'s finished films. The goal is to reverse-engineer the visual signature, and how each shot was most likely generated or shot, so the owner can reproduce the look with his own character.

Inputs:
- strips: {STRIPS_DIR};
- the source videos (for extra frames);
- the cut list and beat alignment;
- the creator's own descriptions of the films, if any (as ground truth for shot content);
- their prompt vocabulary or method file.

Mark films whose authorship is unconfirmed, and weight them lower.

Output:
1. **`{OUT}/finals/<film>.md`** for each film:
   - a shot table: in/out, size and angle, camera position and movement (from first to last frame), lens feel, light, palette and grade, wardrobe and props, action, the connection to the next shot;
   - a look bible;
   - structure: hook, arc, ending, rhythm;
   - a reconstructed production plan with 2–3 reconstructed prompts in the creator's style, labelled as reconstruction.
2. **`{OUT}/finals/LOOK.md`**:
   - 10–15 numbered look rules, each with evidence, the blocks to prompt it with, and the usual way it fails;
   - frequency tables: shot sizes, special shot types, camera moves, shot length by music mode;
   - a measured grade window (mean luma, p1/p99, saturation, warm and green bias), palette hexes, a motif inventory, aesthetic families;
   - adaptation for a male lead;
   - uncertainties.

Correct automatic cut counts by checking frames. Describe what you SEE, and mark inference.

Final reply: ≤300 words, the 10 strongest visual rules.
