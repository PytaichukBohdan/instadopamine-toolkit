#!/usr/bin/env python3
"""Generate a reviewed Ukrainian script with an existing ElevenLabs voice.

Keep outputs and API credentials outside the repository/publication directory.
This does not create or verify a voice, upgrade a plan, or retry paid requests.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from instadna.pronunciation import check_text, make_ledger, validate_ledger


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--script', type=Path, required=True)
    p.add_argument('--bases', type=Path, required=True)
    p.add_argument('--voice-id', required=True)
    p.add_argument('--key-file', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--model', default='eleven_v4')
    p.add_argument('--stability', type=float, default=.5)
    p.add_argument('--similarity', type=float, default=.85)
    p.add_argument('--seed', type=int, default=4101)
    p.add_argument('--stress', choices=['marked', 'plain'], default='marked')
    p.add_argument('--join-lines', action='store_true',
                   help='Send one continuous performance with paragraph breaks')
    p.add_argument('--format', default='mp3_44100_192')
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    if not 0 <= a.stability <= 1 or not 0 <= a.similarity <= 1:
        p.error('Stability and similarity must be between zero and one')
    if not 0 <= a.seed <= 4294967295:
        p.error('Seed must fit an unsigned 32-bit integer')
    script = json.loads(a.script.read_text())
    lines = script['lines']
    marked = [line['marked_text'] for line in lines]
    for line in lines:
        errors = check_text(line['marked_text'], line['text'])
        if errors:
            p.error('; '.join(errors))
    inputs = []
    for line in lines:
        text = line['marked_text'] if a.stress == 'marked' else line['text']
        if line.get('delivery_tag'):
            text = f"[{line['delivery_tag']}] {text}"
        inputs.append({'text': text, 'voice_id': a.voice_id})
    if a.join_lines:
        inputs = [{'text': '\n\n'.join(row['text'] for row in inputs), 'voice_id': a.voice_id}]
    if sum(len(row['text']) for row in inputs) > 2000:
        p.error('Split into contextual batches below the documented 2000-character recommendation')
    settings = dict(stability=a.stability)
    if not a.model.startswith('eleven_v3'):
        settings['similarity'] = a.similarity
    payload = dict(inputs=inputs, model_id=a.model, language_code='uk',
                   settings=settings,
                   seed=a.seed, apply_text_normalization='off')
    request = dict(endpoint='https://api.elevenlabs.io/v1/text-to-dialogue',
                   params={'output_format': a.format}, payload=payload,
                   pronunciation_mode=a.stress, expected_sections=marked)
    raw = json.dumps(request, ensure_ascii=False, indent=2).encode()
    bases = json.loads(a.bases.read_text())
    ledger = make_ledger(raw, marked, bases, 'Supplied per-occurrence contextual review bases')
    validate_ledger(raw, marked, ledger)
    a.output.mkdir(mode=0o700, parents=True, exist_ok=True)
    if any(a.output.iterdir()):
        p.error('Use an empty private output directory; paid requests are not repeated automatically')
    (a.output / 'request.json').write_bytes(raw)
    (a.output / 'pronunciation-ledger.json').write_text(json.dumps(ledger, ensure_ascii=False, indent=2))
    if a.dry_run:
        print('Pronunciation preflight passed; no API request sent')
        return
    key = os.environ.get('ELEVENLABS_API_KEY')
    if a.key_file:
        for line in a.key_file.read_text().splitlines():
            if line.startswith('ELEVENLABS_API_KEY='):
                key = line.split('=', 1)[1].strip().strip('"').strip("'")
    if not key:
        p.error('Set ELEVENLABS_API_KEY or provide a private key file')
    started = time.time()
    response = requests.post(request['endpoint'], params=request['params'], json=payload,
                             headers={'xi-api-key': key}, timeout=(20, 240))
    receipt = dict(http_status=response.status_code, elapsed_s=round(time.time()-started, 3),
                   request_id=response.headers.get('request-id'),
                   character_cost=response.headers.get('character-cost'),
                   content_type=response.headers.get('content-type'),
                   request_sha256=hashlib.sha256(raw).hexdigest())
    if not response.ok:
        receipt['error'] = response.text.replace(key, '[redacted]')[:3000]
        (a.output / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
        raise SystemExit(f"ElevenLabs HTTP {response.status_code}; see private receipt. No automatic retry.")
    suffix = 'mp3' if a.format.startswith('mp3') else 'wav' if a.format.startswith('wav') else 'bin'
    path = a.output / f'voice.{suffix}'
    path.write_bytes(response.content)
    receipt['sha256'] = hashlib.sha256(response.content).hexdigest()
    receipt['bytes'] = len(response.content)
    if suffix in {'mp3', 'wav'}:
        probe = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
            'format=duration:stream=codec_name,sample_rate,channels', '-of', 'json', str(path)])
        receipt['audio'] = json.loads(probe)
    (a.output / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    main()
