"""Second ASR pass with anonymous, per-recording speaker labels; private output only."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import re
from pathlib import Path
import requests
from datetime import datetime, timezone


def recheck(root, code):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', code):
        raise ValueError('Invalid Instagram shortcode')
    audio = root / 'posts' / code / 'asset-00' / 'audio.mp3'
    digest = hashlib.sha256(audio.read_bytes()).hexdigest()
    out = audio.parent / 'transcript-diarized.json'
    if out.exists() and json.loads(out.read_text()).get('audio_sha256') == digest:
        return code, 'cached'
    with audio.open('rb') as f:
        response = requests.post('https://api.openai.com/v1/audio/transcriptions',
            headers={'Authorization': 'Bearer ' + os.environ['OPENAI_API_KEY']},
            files={'file': ('audio.mp3', f, 'audio/mpeg')},
            data={'model': 'gpt-4o-transcribe-diarize', 'response_format': 'diarized_json', 'chunking_strategy': 'auto'}, timeout=(20, 300))
    response.raise_for_status()
    result = response.json()
    result.update(model='gpt-4o-transcribe-diarize', audio_sha256=digest,
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        reliability='Automatic second transcription. Speaker labels are local to this recording, not biometric identities; overlaps and cuts can confuse attribution.')
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return code, len(result.get('segments', []))

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('shortcodes', nargs='+')
    a = p.parse_args()
    with ThreadPoolExecutor(max_workers=3) as pool:
        for code, result in pool.map(lambda c: recheck(a.root, c), a.shortcodes):
            print(code, result, flush=True)
