#!/usr/bin/env python3
"""Precise local word timing with faster-whisper for selected recordings (no API, no upload).

Writes the same private transcript layout as transcribe_media.py into its own
directory, so cloud and local passes never overwrite each other. Intended for
phrase-excerpt sources and other recordings where boundaries matter; CPU speed is
roughly realtime for large-v3. Requires faster-whisper and FFmpeg; set HF_HOME to the
model cache (e.g. on a data volume).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_media_gemini import BUILDERS  # noqa: E402
from transcribe_media import has_audio, save  # noqa: E402


def now():
    return datetime.now(timezone.utc).isoformat()


def decode(path):
    import numpy as np
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-vn', '-f', 's16le', '-ac', '1', '-ar', '16000', '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', action='append', required=True, help='platform=path')
    parser.add_argument('--ids', type=Path, required=True, help='File with one item ID per line, in priority order')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--model', default='Systran/faster-whisper-large-v3')
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--beam', type=int, default=1)
    args = parser.parse_args()
    os.umask(0o077)
    from faster_whisper import WhisperModel
    wanted = [line.strip() for line in args.ids.read_text().splitlines() if line.strip()]
    media = {}
    for spec in args.corpus:
        platform, root = spec.split('=', 1)
        for item in BUILDERS[platform](Path(root), ''):
            if item['item_id'] in wanted:
                media[item['item_id']] = [m for m in item['media'] if m['kind'] in {'video', 'audio'}]
    model = WhisperModel(args.model, device='cpu', compute_type='int8', cpu_threads=args.threads)
    label = 'faster-whisper-' + args.model.split('/')[-1].removeprefix('faster-whisper-')
    for n, item_id in enumerate(wanted, 1):
        for m in media.get(item_id, []):
            target = args.out / item_id.replace(':', '/')
            target = target.with_name(f"{target.name}-{m['index']:02d}.json")
            if target.exists() and json.loads(target.read_text()).get('source_sha256') == m['sha256']:
                continue
            if not has_audio(Path(m['path'])):
                save(target, {'status': 'no_audio', 'item_id': item_id, 'media_index': m['index'], 'source_sha256': m['sha256'], 'at': now()})
                continue
            segments, info = model.transcribe(decode(m['path']), beam_size=args.beam, word_timestamps=True, vad_filter=True,
                                              condition_on_previous_text=False)
            segments = list(segments)
            words = [{'word': w.word.strip(), 'start': round(float(w.start), 3), 'end': round(float(w.end), 3), 'probability': round(float(w.probability), 3)}
                     for s in segments for w in (s.words or []) if w.word.strip()]
            save(target, {'status': 'transcribed', 'item_id': item_id, 'media_index': m['index'], 'source_sha256': m['sha256'],
                          'model': label, 'language': info.language, 'language_probability': round(info.language_probability, 3),
                          'duration': round(info.duration, 3), 'text': ' '.join(w['word'] for w in words),
                          'segments': [{'start': round(s.start, 3), 'end': round(s.end, 3), 'text': s.text.strip(), 'avg_logprob': round(s.avg_logprob, 3)} for s in segments],
                          'words': words, 'retrieved_at': now(),
                          'reliability': 'Local automatic transcription with word timing; verify wording before quotation'})
        print(json.dumps({'done': n, 'of': len(wanted), 'last': item_id}), flush=True)


if __name__ == '__main__':
    main()
