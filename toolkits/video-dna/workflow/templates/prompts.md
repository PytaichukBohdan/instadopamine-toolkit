# Prompt types: which blocks and settings to use

`tools/assemble_prompts.py` builds every prompt from `production.yaml`. For each kind of
generation, list block codes from your style's `blocks/` folder. Then study that style's own
originals for that type.

| Prompt type | Typical model · settings | What the prompt must carry |
|---|---|---|
| **Character sheet in costume** | Seedream v5 Pro · 16:9 · 2k | identity tag (`@face`), wardrobe line, panel layout, neutral backdrop |
| **Location plate**, empty | Soul Cinematic · 16:9 · 1080p | location, light, look, "no people" |
| **Start frame** | Seedream v5 Pro · 2k · delivery aspect | person / place / set / true scale / moment / shot (mm) / light + relight / look / avoid |
| **Single take from a start frame** (default) | Seedance · 1080p · 4–8 s | first-frame role, reference roles, camera, light, task, no freezing, sound, beats, inversions |
| **Multi-shot in one generation** | Seedance · 15–24 s | shot list, camera references, grade lock, match cuts |
| **Start + end frame one-take** | Seedance · 10 s | both frames and the motion between them |
| **Draft pass** | Seedance draft · 480p, then upscale | the same prompt as the final |
| **Re-cast** (face only, whole character, world only) | Higgsfield motion control · 1080p | source timeline + a preservation checklist |

**Always** include:
- the format line first, in numbers;
- every reference with its role, plus TAKE NOTHING ELSE;
- the cast FACE block word for word;
- the shot's trick inversions as bans;
- "no text, no logos" unless text is wanted.

Keep the header settings and the body text consistent.
