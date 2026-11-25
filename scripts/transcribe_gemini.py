#!/usr/bin/env python3
"""Word-timed transcripts from Gemini when Whisper is unavailable (same output layout as transcribe_media.py).

Audio is extracted privately (mono 16 kHz) and sent in windows of at most five
minutes; times are shifted back to the full recording. Model word timings are
approximate: excerpts cut from them need a listening check. Reads GEMINI_API_KEY.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from instadna import gemini  # noqa: E402
from analyze_media_gemini import BUILDERS  # noqa: E402
from transcribe_media import has_audio, save  # noqa: E402

WINDOW = 300
PROMPT = """Transcribe ALL speech in this audio verbatim, in the original language(s) (Russian, Ukrainian, English; keep
surzhyk, slang and fillers exactly as spoken). Do not translate or tidy. Return JSON:
{"language": ISO code of the dominant spoken language or null, "words": [{"w": word with attached punctuation, "start": seconds, "end": seconds}]}
Times are seconds from the start of THIS audio clip. Return {"language": null, "words": []} if there is no speech (music only)."""


def now():
    return datetime.now(timezone.utc).isoformat()


def duration(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def segments(words, gap=0.7, longest=12.0):
    out, current = [], []
    for w in words:
        if current and (w['start'] - current[-1]['end'] > gap or w['end'] - current[0]['start'] > longest):
            out.append(current)
            current = []
        current.append(w)
    if current:
        out.append(current)
    return [{'start': c[0]['start'], 'end': c[-1]['end'], 'text': ' '.join(x['word'] for x in c)} for c in out]


def run(job, out, model):
    item_id, index, source, digest = job
    base = out / item_id.replace(':', '/')
    target = base.with_name(f'{base.name}-{index:02d}.json')
    if target.exists():
        old = json.loads(target.read_text())
        if old.get('source_sha256') == digest and old.get('status') in {'transcribed', 'no_audio'}:
            return 'cached', item_id
    try:
        if not has_audio(source):
            save(target, {'status': 'no_audio', 'item_id': item_id, 'media_index': index, 'source_sha256': digest, 'at': now()})
            return 'no_audio', item_id
        audio = target.with_suffix('.mp3')
        audio.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(source), '-vn', '-ac', '1', '-ar', '16000', '-b:a', '40k', str(audio)], check=True)
        total = duration(audio)
        words, languages, usage = [], [], []
        for start in range(0, int(total) + 1, WINDOW):
            if total - start < 0.3:
                break
            clip = audio.with_name(f'{audio.stem}.w{start}.mp3')
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(start), '-t', str(WINDOW), '-i', str(audio), '-c', 'copy', str(clip)], check=True)
            try:
                part, _ = gemini.media_part(clip, 'audio/mpeg')
                result, meta = gemini.generate(model, [{'text': PROMPT}, part], max_output_tokens=32768, timeout=600)
            finally:
                clip.unlink(missing_ok=True)
            usage.append(meta.get('usage'))
            if result.get('language'):
                languages.append(result['language'])
            limit = min(WINDOW, total - start) + 1.5
            for w in result.get('words') or []:
                s, e = w.get('start'), w.get('end')
                if isinstance(s, (int, float)) and isinstance(e, (int, float)) and 0 <= s <= e <= limit and str(w.get('w', '')).strip():
                    words.append({'word': str(w['w']).strip(), 'start': round(start + s, 3), 'end': round(start + e, 3)})
        words.sort(key=lambda w: w['start'])
        save(target, {'status': 'transcribed', 'item_id': item_id, 'media_index': index, 'source_sha256': digest,
                      'audio': audio.name, 'audio_sha256': hashlib.sha256(audio.read_bytes()).hexdigest(), 'model': model,
                      'language': max(set(languages), key=languages.count) if languages else None, 'duration': round(total, 3),
                      'text': ' '.join(w['word'] for w in words), 'segments': segments(words), 'words': words,
                      'usage': usage, 'retrieved_at': now(),
                      'reliability': 'Automatic LLM transcription with approximate word timing; verify before quotation or cutting'})
        return 'transcribed', item_id
    except Exception as error:
        save(target.with_suffix('.error.json'), {'item_id': item_id, 'media_index': index, 'error': str(error)[:400], 'at': now()})
        return 'failed', item_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--platform', choices=['instagram', 'telegram', 'highlights'], required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--model', default='gemini-3.8-flash')
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    os.umask(0o077)
    jobs = [(item['item_id'], m['index'], Path(m['path']), m['sha256'])
            for item in BUILDERS[args.platform](args.root.resolve(), '') for m in item['media'] if m['kind'] in {'video', 'audio'}]
    counts = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run, job, args.out.resolve(), args.model) for job in jobs]
        for i, future in enumerate(as_completed(futures), 1):
            status, item_id = future.result()
            counts[status] = counts.get(status, 0) + 1
            if status == 'failed' or i % 25 == 0 or i == len(jobs):
                print(json.dumps({'done': i, 'of': len(jobs), 'last': item_id, **counts}), flush=True)


if __name__ == '__main__':
    main()
