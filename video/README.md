# Vertical caption engine (adapted from pdoom-video)

This folder adapts the engine of [mexicat/pdoom-video](https://github.com/mexicat/pdoom-video)
(commit `bdbad537a7b7af3213475651774030c47568c181`, MIT, see `LICENSE.pdoom-video`) to a vertical,
word-synced self-presentation reel. Everything it renders is a pure function of time in the voice
track, so a preview, a still and a final render agree frame for frame.

## What changed from pdoom-video

| Area | pdoom-video | This engine |
|---|---|---|
| Canvas | 1920×1080 | 1080×1920 (`src/engine/gl.ts`) |
| Fonts | Archivo, Cormorant Garamond, IBM Plex Mono, plotter fonts | Cormorant Garamond, IBM Plex Mono, Montserrat, Marck Script, subset to Latin and Cyrillic |
| Timeline | hand-made scene windows over song lyrics | one entry per storyboard shot, resolved at runtime from word anchors in `lyrics.json` (`src/timeline.ts`) |
| Scenes | 17 music-video plates | `face`: a start frame (or a clip), a slow camera move and the caption; `card`: the end card |
| Renderer | `stills`, `sheet`, `plates`, `perf`, `video` | `board` (one styled still per shot) and `video`; Chrome with SwiftShader when there is no GPU |

The karaoke rule is unchanged: a word appears on its sung start, never ahead of the voice.
Choose the caption style with `?captions=`: `fp` (one key word at a time, red serif capitals),
`block` (bold white block) or `mix` (script word over sans).

## Inputs

A project file `projects/<name>.json` maps the edit's inputs from wherever you keep them.
Nothing is copied. Select it with `VIDEO_PROJECT=<name>`.

```json
{
  "data": {
    "lyrics.json": "path/to/round/data/lyrics.json",
    "audio.json": "path/to/round/data/audio.json",
    "storyboard.json": "wiki/<handle>/storyboard.json",
    "voice.mp3": "wiki/<handle>/audio/<take>.mp3"
  },
  "plates": "wiki/<handle>/storyboard/<round>"
}
```

| Input | Made by |
|---|---|
| `lyrics.json`, `audio.json` | `scripts/align_script_words.py --snap-db -45`: word timing for a known script, plus the voice envelope |
| `storyboard.json` | `scripts/build_storyboard.py` from a `shots.json` spec |
| `voice.mp3` | the approved take (`voice-clone-dna`), optionally spaced with `scripts/arrange_voice_lines.py` |
| `plates/<shot>.webp` | `scripts/generate_storyboard_frames.py` |

## Run

Requires bun, Google Chrome and, for video, ffmpeg.

```sh
cd video/app
bun install
VIDEO_PROJECT=<name> bunx vite                                    # preview at http://localhost:5173
VIDEO_PROJECT=<name> bun scripts/render.ts board --out ../out/board
VIDEO_PROJECT=<name> VIDEO_CLIPS=<frames dir> bun scripts/render.ts video --fps 25 --noaudio --out ../out/edit.mp4
```

## Video stage

1. **Music:** `scripts/compose_music_elevenlabs.py --plan <music-plan.json>` composes an instrumental bed timed to the voice.
2. **Cuts on the music:** `scripts/align_cuts_to_music.py` moves each cut onto a named hit or the nearest beat, within caption-safe limits.
3. **Clips:** `scripts/generate_clips_higgsfield.py` animates each approved start frame through the Higgsfield CLI.
   `scripts/prepare_clips.py` then cuts each clip to its shot window.
4. **Render:** `render.ts video` plays the clips as video plates. A shot without a clip falls back to its still.
5. **Mix and mux:** `scripts/mix_voice_music.py` ducks the music under the voice to −14 LUFS / −1 dBTP; ffmpeg then muxes the mix with the render.
