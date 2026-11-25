#!/usr/bin/env python3
"""Create one ElevenLabs Instant Voice Clone from private, attributed reference files.

Requires an explicit consent statement: cloning makes a real person say new words, so
the owner must confirm the speaker agreed. Uploads only the listed files, never
retries, and writes the voice ID and a receipt to a private directory. It does not
verify, share or publish the voice, and never upgrades a plan.
"""
import argparse
import hashlib
import json
import os
import time
from pathlib import Path

import requests

ENDPOINT = 'https://api.elevenlabs.io/v1/voices/add'


def key_from(path):
    key = os.environ.get('ELEVENLABS_API_KEY')
    if path:
        for line in Path(path).read_text().splitlines():
            if line.startswith('ELEVENLABS_API_KEY='):
                key = line.split('=', 1)[1].strip().strip('"').strip("'")
    return key


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--name', required=True)
    p.add_argument('--files', type=Path, nargs='+', required=True)
    p.add_argument('--description', default='')
    p.add_argument('--language', required=True, help='Label only, e.g. ru')
    p.add_argument('--consent', required=True, help='Who confirmed the speaker agreed, and when')
    p.add_argument('--key-file', type=Path)
    p.add_argument('--output', type=Path, required=True, help='Empty private directory for the receipt')
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    if len(a.consent.strip()) < 10:
        p.error('State who confirmed the speaker consented to cloning')
    if not 1 <= len(a.files) <= 25:
        p.error('Instant cloning accepts 1 to 25 reference files')
    a.output.mkdir(mode=0o700, parents=True, exist_ok=True)
    if any(a.output.iterdir()):
        p.error('Use an empty private output directory; voice creation is never repeated automatically')
    files = [{'name': f.name, 'sha256': hashlib.sha256(f.read_bytes()).hexdigest(), 'bytes': f.stat().st_size} for f in a.files]
    request = {'endpoint': ENDPOINT, 'name': a.name, 'description': a.description, 'labels': {'language': a.language},
               'remove_background_noise': False, 'files': files, 'consent': a.consent.strip()}
    (a.output / 'request.json').write_text(json.dumps(request, ensure_ascii=False, indent=2))
    if a.dry_run:
        print(json.dumps({'dry_run': True, 'files': len(files)}))
        return
    key = key_from(a.key_file)
    if not key:
        p.error('Set ELEVENLABS_API_KEY or provide a private key file')
    started = time.time()
    handles = [open(f, 'rb') for f in a.files]
    try:
        response = requests.post(ENDPOINT, headers={'xi-api-key': key}, timeout=(20, 300),
                                 data={'name': a.name, 'description': a.description, 'labels': json.dumps({'language': a.language}),
                                       'remove_background_noise': 'false'},
                                 files=[('files', (f.name, h, 'audio/wav')) for f, h in zip(a.files, handles)])
    finally:
        for h in handles:
            h.close()
    receipt = {'http_status': response.status_code, 'elapsed_s': round(time.time() - started, 3),
               'request_id': response.headers.get('request-id'),
               'request_sha256': hashlib.sha256((a.output / 'request.json').read_bytes()).hexdigest()}
    if not response.ok:
        receipt['error'] = response.text.replace(key, '[redacted]')[:3000]
        (a.output / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
        raise SystemExit(f'ElevenLabs HTTP {response.status_code}; see private receipt. No automatic retry.')
    body = response.json()
    receipt.update(voice_id=body.get('voice_id'), requires_verification=body.get('requires_verification'))
    (a.output / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    (a.output / 'receipt.json').chmod(0o600)
    print(json.dumps({'created': True, 'requires_verification': receipt['requires_verification']}))


if __name__ == '__main__':
    main()
