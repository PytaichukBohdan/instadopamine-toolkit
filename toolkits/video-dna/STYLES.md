# Video styles: one creator's DNA per style

Each style is one creator's video-making DNA, extracted with `skills/video-dna-extract/SKILL.md`,
in its own folder `video-dna/<style-id>/`. The pipeline (`workflow/`, `tools/`, `cast/`) is the same
for every style. Each production picks exactly one style in `production.yaml` (`style: <id>`).
The tools refuse to run without one. If a video idea arrives without a style, ask which one to use.

| id | Name | Creator | Sources studied | Status | Best for | Entry points |
|---|---|---|---|---|---|---|
| *(none yet: add your first style with video-dna-extract)* | | | | | | |

## Folder contract for a style

```
video-dna/<style-id>/
  DNA.md          genes (one page) + numbered sections: look, story, edit, pipeline, prompts, camera,
                  light, tricks, acting, sound, identity, reach, evolution, rule-breaking, pitfalls,
                  adaptation to your cast, gaps
  formats.md      the creator's repeatable formats as recipe cards
  stats.md        measured evidence (models/settings, lengths, cuts, beat alignment…)
  blocks/         prompt blocks (<CODE>.md with frontmatter: code, group, title, source, evidence)
  finals/         frame-level breakdowns of finished films + LOOK.md
  posts/ groups/  per-source analyses and cross-source syntheses
  youtube/        (if any) channel analysis
  business.md     (optional) how the creator earns
  corpus/         the scraped originals (private study material; never republished)
```

`tools/assemble_prompts.py` reads blocks from `<style>/blocks/`, so one production cannot mix two creators' blocks by accident.
