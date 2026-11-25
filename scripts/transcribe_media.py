#!/usr/bin/env python3
"""Word-timed Whisper transcripts for every audio-bearing media file in a private corpus.

Audio is extracted with FFmpeg (mono 16 kHz) next to the transcript; both stay
private. Word timings support phrase excerpts and speech-rate measurement; they
are automatic and must be checked before quotation. Reads OPENAI_API_KEY.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_media_gemini import BUILDERS  # noqa: E402

LIMIT = 24_000_000


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.chmod(0o600)
    tmp.replace(path)


def has_audio(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index', '-of', 'csv=p=0', str(path)],
                         capture_output=True, text=True).stdout
    return bool(out.strip())


def whisper(path, key, prompt=None):
    for attempt in range(5):
        with path.open('rb') as audio:
            data = [('model', 'whisper-1'), ('response_format', 'verbose_json'),
                    ('timestamp_granularities[]', 'word'), ('timestamp_granularities[]', 'segment')]
            if prompt:
                data.append(('prompt', prompt))
            response = requests.post('https://api.openai.com/v1/audio/transcriptions', headers={'Authorization': 'Bearer ' + key},
                                     files={'file': (path.name, audio, 'audio/mpeg')}, data=data, timeout=(20, 600))
        if response.status_code in {429, 500, 502, 503, 504} and attempt < 4:
            time.sleep(5 * 2 ** attempt)
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError('Whisper did not complete')


def run(job, out, key, prompt):
    item_id, index, source, digest = job
    base = out / item_id.replace(':', '/')
    target = base.with_name(f'{base.name}-{index:02d}.json')
    if target.exists() and json.loads(target.read_text()).get('source_sha256') == digest:
        return 'cached', item_id
    try:
        if not has_audio(source):
            save(target, {'status': 'no_audio', 'item_id': item_id, 'media_index': index, 'source_sha256': digest, 'at': now()})
            return 'no_audio', item_id
        audio = target.with_suffix('.mp3')
        audio.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(source), '-vn', '-ac', '1', '-ar', '16000', '-b:a', '40k', str(audio)], check=True)
        if audio.stat().st_size > LIMIT:
            raise ValueError('Audio exceeds the single-request limit; chunk it first')
        data = whisper(audio, key, prompt)
        save(target, {'status': 'transcribed', 'item_id': item_id, 'media_index': index, 'source_sha256': digest,
                      'audio': audio.name, 'audio_sha256': hashlib.sha256(audio.read_bytes()).hexdigest(), 'model': 'whisper-1',
                      'language': data.get('language'), 'duration': data.get('duration'), 'text': data.get('text'),
                      'segments': [{k: s.get(k) for k in ['start', 'end', 'text', 'avg_logprob', 'no_speech_prob']} for s in data.get('segments', [])],
                      'words': data.get('words', []), 'retrieved_at': now(),
                      'reliability': 'Automatic transcription; words, names, language and speaker are unverified'})
        return 'transcribed', item_id
    except Exception as error:
        save(target.with_suffix('.error.json'), {'item_id': item_id, 'media_index': index, 'error': str(error)[:400], 'at': now()})
        return 'failed', item_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--platform', choices=['instagram', 'telegram', 'highlights'], required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--prompt', help='Optional spelling hint, e.g. names and domain terms')
    args = parser.parse_args()
    os.umask(0o077)
    key = os.environ.get('OPENAI_API_KEY')
    if not key:
        parser.error('OPENAI_API_KEY is required')
    jobs = [(item['item_id'], m['index'], Path(m['path']), m['sha256'])
            for item in BUILDERS[args.platform](args.root.resolve(), '') for m in item['media'] if m['kind'] in {'video', 'audio'}]
    counts = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run, job, args.out.resolve(), key, args.prompt) for job in jobs]
        for i, future in enumerate(as_completed(futures), 1):
            status, item_id = future.result()
            counts[status] = counts.get(status, 0) + 1
            if status == 'failed' or i % 25 == 0 or i == len(jobs):
                print(json.dumps({'done': i, 'of': len(jobs), 'last': item_id, **counts}), flush=True)


if __name__ == '__main__':
    main()
