#!/usr/bin/env python3
"""Cut the final edit from generated clips, following the shot list in production.yaml.

Usage:
    python3 cut_from_production.py ../productions/<slug>/production.yaml [--no-music]

Expects <production dir>/clips/<shot id>.mp4 (one accepted take per shot). For each shot it takes
`clip_in` (default 0) for `end - start` seconds, scales/crops to the delivery frame, conforms to the
delivery fps, then concatenates in shot order. If `music.file` is set (relative to the production
dir), the track is laid under the cut from `music.offset` seconds, with the clips' own sound
ducked to `music.clip_gain` (default 0.35). Output: <production dir>/renders/<slug>-v<version>.mp4
"""
import os
import shutil
import subprocess
import sys
import tempfile

import yaml

FRAMES = {"4:3": (1664, 1248), "9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1440, 1440), "4:5": (1080, 1350)}


def run(cmd):
    subprocess.run(cmd, check=True)


def main():
    path = sys.argv[1]
    base = os.path.dirname(os.path.abspath(path))
    prod = yaml.safe_load(open(path))
    w, h = FRAMES[prod["delivery"]["aspect"]]
    fps = prod["delivery"].get("fps", 24)
    os.makedirs(os.path.join(base, "renders"), exist_ok=True)
    tmp = tempfile.mkdtemp(prefix=".cut-", dir=os.path.join(base, "renders"))  # same disk as the output; / may be full
    parts = []
    for shot in prod["shots"]:
        clip = os.path.join(base, "clips", shot["id"] + ".mp4")
        if not os.path.exists(clip):
            sys.exit(f"missing clip for {shot['id']}: {clip}")
        length = float(shot["end"]) - float(shot["start"])
        out = os.path.join(tmp, shot["id"] + ".mp4")
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps},setsar=1"
        frames = round(length * fps)  # exact frame count per shot keeps the concatenated timeline clean
        run(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(shot.get("clip_in", 0)), "-i", clip,
             "-f", "lavfi", "-t", f"{frames / fps:.4f}", "-i", "anullsrc=r=48000:cl=stereo",
             "-filter_complex", f"[0:v]{vf}[v];[0:a][1:a]amix=inputs=2:duration=longest[a]" if has_audio(clip) else f"[0:v]{vf}[v];[1:a]anull[a]",
             "-map", "[v]", "-map", "[a]", "-frames:v", str(frames), "-r", str(fps), "-video_track_timescale", str(fps * 1000),
             "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-ar", "48000", "-t", f"{frames / fps:.4f}", out])
        parts.append(out)
    concat = os.path.join(tmp, "list.txt")
    open(concat, "w").write("".join(f"file '{p}'\n" for p in parts))
    cut = os.path.join(tmp, "cut.mp4")
    run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", concat, "-c", "copy", cut])

    final = os.path.join(base, "renders", f"{prod.get('slug', 'cut')}-v{prod.get('version', 1)}.mp4")
    music = (prod.get("music") or {})
    if music.get("file") and "--no-music" not in sys.argv:
        gain = music.get("clip_gain", 0.35)
        run(["ffmpeg", "-loglevel", "error", "-y", "-i", cut, "-ss", str(music.get("offset", 0)), "-i", os.path.join(base, music["file"]),
             "-filter_complex", f"[0:a]volume={gain}[c];[1:a]volume=1.0[m];[c][m]amix=inputs=2:duration=first:normalize=0[a]",
             "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", final])
    else:
        shutil.move(cut, final)
    shutil.rmtree(tmp, ignore_errors=True)
    print(final)


def has_audio(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    return bool(out)


if __name__ == "__main__":
    main()
