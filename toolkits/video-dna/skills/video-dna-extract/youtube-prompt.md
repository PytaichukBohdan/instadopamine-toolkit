# Analyst prompt: channel / tutorial layer (YouTube or similar)

Prepare first: `descriptions.md` (titles, dates, views, likes, keywords, descriptions with chapters), resolved campaign or affiliate links, partial transcripts (local Whisper), and storyboard sprites for every video.

---

You are analysing {NAME}'s channel ({CHANNEL}) to add the channel layer to an existing DNA study (`{DNA_MD}`). Skim its genes first and add NEW information, not repeats. Full audio or captions may be unavailable: never claim content from audio you haven't heard.

Produce `{OUT}/youtube/YOUTUBE.md`:
- **Channel facts:** cadence, formats, the distribution of views and likes, what got reach (views per day), title formulas, the description template, keywords.
- **Tutorial anatomy:** the spoken hook formula with quotes, chapter skeletons, what the storyboards show over time (talking head, screen recording, results, graphics), sets, overlay devices, pace, how results are shown, end screens.
- **Process knowledge NOT in the posts:** prompting, pre-production, models and tools with the stated reasons, lighting rules, cost numbers, iteration doctrine, creative philosophy.
- **Shorts:** categories, phases, best performers.
- **Funnel and business model:** campaign or affiliate links, sponsorships, products.
- **What this adds to the DNA:** numbered additions and corrections, each with evidence.
- **Gaps:** a priority list for full transcription.

Produce `{OUT}/youtube/videos.md`: one entry per long video (chapters, hook, a storyboard timeline, the linked post, key teachings) and a table of the Shorts.

Locators: `id mm:ss` (storyboard tile) and `(tr id mm:ss)` (transcript). Words read on screen are "read, not heard".

Final reply: ≤300 words, the 10 most important new findings.
