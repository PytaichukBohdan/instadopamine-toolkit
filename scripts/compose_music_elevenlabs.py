#!/usr/bin/env python3
"""Compose an instrumental music bed with ElevenLabs Music from a timed composition plan.

The plan file holds `model_id` and `composition_plan` (for `music_v2`/`music_v2_5`: `chunks`, each with `text`,
`duration_ms`, `positive_styles` and optional `negative_styles`; their durations are enforced, so hits can be placed on
a voice timeline). One paid request per run: the output directory must be empty, nothing is retried, and the receipt
records the request hash, the provider's request id, the audio hash and its measured length. `--dry-run` writes only the
request. Keep outputs and the API key outside the repository and the publication directory. Do not condition on, or
describe, a copyrighted reference track by name: describe its musical traits instead.
"""
import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

import requests


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True, help='JSON with model_id, composition_plan and optional seed')
    p.add_argument('--key-file', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--format', default='mp3_48000_192')
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    plan = json.loads(a.plan.read_text())
    chunks = plan['composition_plan']['chunks']
    for chunk in chunks:
        if not 3000 <= chunk['duration_ms'] <= 120000:
            p.error(f"Chunk durations must be 3000-120000 ms: {chunk['text'][:40]}")
    total = sum(c['duration_ms'] for c in chunks)
    if plan.get('total_ms') and total != plan['total_ms']:
        p.error(f'Chunks add up to {total} ms, not the planned {plan["total_ms"]} ms')
    payload = {'composition_plan': plan['composition_plan'], 'model_id': plan['model_id']}
    if plan.get('seed') is not None:
        payload['seed'] = plan['seed']
    request = {'endpoint': 'https://api.elevenlabs.io/v1/music', 'params': {'output_format': a.format}, 'payload': payload}
    raw = json.dumps(request, ensure_ascii=False, indent=2).encode()
    a.output.mkdir(mode=0o700, parents=True, exist_ok=True)
    if any(a.output.iterdir()):
        p.error('Use an empty private output directory; paid requests are not repeated automatically')
    (a.output / 'request.json').write_bytes(raw)
    if a.dry_run:
        print(json.dumps({'dry_run': True, 'chunks': len(chunks), 'total_ms': total}))
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
                             headers={'xi-api-key': key}, timeout=(20, 600))
    receipt = {'http_status': response.status_code, 'elapsed_s': round(time.time() - started, 3),
               'request_id': response.headers.get('request-id'), 'character_cost': response.headers.get('character-cost'),
               'content_type': response.headers.get('content-type'), 'request_sha256': hashlib.sha256(raw).hexdigest()}
    if not response.ok:
        receipt['error'] = response.text.replace(key, '[redacted]')[:3000]
        (a.output / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
        raise SystemExit(f'ElevenLabs HTTP {response.status_code}; see the private receipt. No automatic retry.')
    path = a.output / ('music.mp3' if a.format.startswith('mp3') else 'music.bin')
    path.write_bytes(response.content)
    receipt['sha256'] = hashlib.sha256(response.content).hexdigest()
    receipt['bytes'] = len(response.content)
    if path.suffix == '.mp3':
        receipt['duration_s'] = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                                               '-of', 'csv=p=0', str(path)]))
    (a.output / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    main()
