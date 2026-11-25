#!/usr/bin/env python3
"""Ingest a creator's YouTube channel into the DNA corpus: metadata, chapters, captions or transcripts.

YouTube may block a server's IP ("Sign in to confirm you're not a bot"), for yt-dlp and for a real
browser alike. So there are two modes:

1) On a machine YouTube doesn't block (e.g. a laptop), fetch captions + metadata only (tiny,
   no video download), then copy the folder to the server:
       pip install yt-dlp
       yt-dlp --skip-download --write-info-json --write-auto-subs --sub-langs en --sub-format vtt \
              -o "%(id)s.%(ext)s" "https://www.youtube.com/@<creator>/videos" "https://www.youtube.com/@<creator>/shorts"
   then on the server:
       python3 ingest_youtube.py --from-dir <that folder> --out ../<style>/corpus/youtube

2) If only audio files are available (<id>.m4a / .webm / .mp3), transcribe them locally with
   faster-whisper (no API, CPU is fine; small.en ≈ 5–15× real time on 8 cores):
       python3 ingest_youtube.py --transcribe <audio dir> --out ../<style>/corpus/youtube

Output in --out: transcripts/<id>.txt ("[mm:ss.ss] text" per line), index.json (one row per video:
id, title, date, seconds, views, likes, chapters, linked URLs, transcript coverage).
"""
import argparse
import glob
import json
import os
import re
import time


def vtt_to_rows(path):
    """Collapse YouTube auto-caption VTT (rolling, duplicated lines) into clean timed rows."""
    rows, last = [], ""
    for block in open(path, encoding="utf-8").read().split("\n\n"):
        m = re.search(r"(\d+):(\d+):([\d.]+) --> ", block)
        if not m:
            continue
        start = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
        text = " ".join(l for l in block.splitlines()[1:] if "-->" not in l)
        text = re.sub(r"<[^>]+>", "", text).strip()
        if text and text != last and not last.endswith(text):
            new = text[len(last):].strip() if text.startswith(last) else text
            if new:
                rows.append({"start": round(start, 2), "text": new})
            last = text
    return rows


def write_txt(rows, path):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(f"[{int(r['start'] // 60):02d}:{r['start'] % 60:05.2f}] {r['text']}\n")


def chapters(desc):
    return [{"t": m[0], "title": m[1].strip()} for m in re.findall(r"^\s*(\d{1,2}:\d{2}(?::\d{2})?)\s*[-–—]?\s*(.+)$", desc or "", re.M)]


def from_dir(src, out):
    os.makedirs(os.path.join(out, "transcripts"), exist_ok=True)
    index = []
    for info in sorted(glob.glob(os.path.join(src, "*.info.json"))):
        m = json.load(open(info, encoding="utf-8"))
        vid = m["id"]
        subs = sorted(glob.glob(os.path.join(src, f"{vid}*.vtt")))
        rows = vtt_to_rows(subs[0]) if subs else []
        if rows:
            write_txt(rows, os.path.join(out, "transcripts", f"{vid}.txt"))
        index.append({"id": vid, "title": m.get("title"), "date": m.get("upload_date"), "seconds": m.get("duration"),
                      "views": m.get("view_count"), "likes": m.get("like_count"), "chapters": chapters(m.get("description")),
                      "links": re.findall(r"https?://\S+", m.get("description") or ""),
                      "transcript": "youtube captions" if rows else "none"})
    json.dump(index, open(os.path.join(out, "index.json"), "w"), indent=1, ensure_ascii=False)
    print(f"{len(index)} videos, {sum(1 for r in index if r['transcript'] != 'none')} with captions → {out}")


def transcribe(src, out, model_name="small.en"):
    from faster_whisper import WhisperModel   # local model, no API
    os.makedirs(os.path.join(out, "transcripts"), exist_ok=True)
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    for a in sorted(glob.glob(os.path.join(src, "*.*"))):
        vid, ext = os.path.splitext(os.path.basename(a))
        if ext not in (".m4a", ".webm", ".mp3", ".wav", ".opus") or os.path.exists(os.path.join(out, "transcripts", f"{vid}.txt")):
            continue
        t0 = time.time()
        segs, info = model.transcribe(a, language="en", vad_filter=True, beam_size=1, condition_on_previous_text=False)
        rows = [{"start": round(s.start, 2), "text": s.text.strip()} for s in segs]
        write_txt(rows, os.path.join(out, "transcripts", f"{vid}.txt"))
        print(f"{vid}: {info.duration:.0f} s of audio in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-dir")
    ap.add_argument("--transcribe")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.from_dir:
        from_dir(a.from_dir, a.out)
    if a.transcribe:
        transcribe(a.transcribe, a.out)
