# passport/: person visual passport toolkit

Builds a photorealistic identity reference set ("digital passport") of a real person from owner-supplied photos and videos. Images come from the Codex CLI built-in image tool on the ChatGPT subscription, with no API key and no fallback. The full workflow and the owner's rules are in [`skill/SKILL.md`](skill/SKILL.md). This file covers the mechanics.

```
passport/
  gen.py            one Codex image call per job; manifest with hashes + revised prompt
  prep_refs.py      photos/videos -> contact sheets, frames, local transcript, refpack crops + boards
  build_site.py     selection.json -> static noindex review page (selected images + prompts only)
  site_template.html
  skill/SKILL.md    the reusable workflow (installed as the person-visual-passport skill)
people/
  _template/        skeleton for a new person (generic prompts with {{NAME}} and pronoun placeholders)
data/<Name>/passport/   generated PNG + WebP + manifest.jsonl   (committed)
data/<Name>/live_references/  raw owner inputs                 (never committed)
work/<slug>/        refpack, frames, transcripts, site build   (gitignored; symlink to /mnt/data on this host)
```

## Person folder

- `person.json`: name, slug, pronouns (`{{he}}/{{his}}/{{him}}…`; default they/them), `inputs`, `refpack`, `output`, `publish` (Pages project and branch).
- `refs.json`: one label per reference id. It tells the model what to take from each image and what to ignore.
- `picks.json`: how the refpack is cut from the raw inputs (crops by fraction boxes or video timestamps, plus boards).
- `jobs.json`: job id → prompt file + up to 5 reference ids, in the order the prompt refers to them.
- `prompts/`: one file per job. Shared blocks such as `_identity.md` and `_baseline.md` are pulled in with `{{identity}}` and `{{baseline}}`.
- `selection.json`: which version of each job is published, the per-image notes, and the pending, method and limits lists.

## Commands

```bash
VENV=work/.venv/bin/python        # pillow + pillow-heif
P=people/<slug>
$VENV passport/prep_refs.py --person $P convert
$VENV passport/prep_refs.py --person $P frames IMG_0001.MOV --fps 2
$VENV passport/prep_refs.py --person $P frames IMG_0002.MOV --fps 4 --start 2 --end 30 --box 0.2,0.15,0.95,0.6 --tag emotions
python3 passport/prep_refs.py --person $P transcribe IMG_0002.MOV     # system faster-whisper, offline model cache
$VENV passport/prep_refs.py --person $P picks
$VENV passport/gen.py --person $P --render-only id-portrait           # inspect the expanded prompt
$VENV passport/gen.py --person $P id-portrait headshot-34             # generate (runs sequentially; launch several processes for parallel)
$VENV passport/build_site.py --person $P
wrangler pages deploy work/<slug>/site --project-name <your-pages-project> --branch <slug>-passport
```

Versions are numbered from the manifest, so retired files can be deleted from the output folder without their names being reused.
