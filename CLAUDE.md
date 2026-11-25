# InstaDopamine toolkit: instructions for Claude

@AGENTS.md

## Start here

- Making a new influencer from a link to finished content: `docs/NEW-INFLUENCER.md`.
- Skills (auto-loaded from `.claude/skills/`): `person-passport`, `voice-clone-dna`,
  `person-visual-passport`, `video-dna-extract`, `video-dna-make`. See `harness/SKILLS.md`.
- Evidence rules for the wikis: `docs/WIKI-RULES.md`.

## Working rules

- **Claude on a subscription.** OpenAI, Gemini, ElevenLabs and Higgsfield are paid
  third-party APIs: state the cost before a run, and never buy credits or loop paid retries.
- **One person, one entity.** Never mix two people's media, phrases, voice or likeness.
  The voice and likeness of a real person need their consent.
- **Private stays private.** Raw media, transcripts, cookies, voice IDs and keys live outside
  this repository (for example `/private/<person>/`), never in git or on a site. Person
  editions are built with `instadna edition` and deployed behind a login. Never write a
  password into a report or a pull request.
- **Browser work:** use a local, scriptable browser (for example the `browser-use` CLI).
- **Git:** work on a branch, merge by pull request, and never force-push.
- **Before saying done:** `python -m unittest discover -s tests`,
  `node --test` on each `tests/*.test.*js`, and `instadna lint --wiki wiki/<handle>`. Then check
  the deployed page itself, not localhost.
