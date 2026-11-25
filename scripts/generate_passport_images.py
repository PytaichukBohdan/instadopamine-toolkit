#!/usr/bin/env python3
"""Generate clean passport reconstructions from atlas reference frames (Gemini image API or Codex CLI).

Each job names its reference atlas IDs and a prompt describing ONE item (garment,
accessory, object, setting or graphic layout) without people, text overlays or UI.
Outputs a PNG plus WebP thumbnail per item and updates generated-images.json with the
model, prompt hash and input-image hashes. Reconstructions are AI interpretations,
never proof or exact product replicas. `--engine gemini` reads GEMINI_API_KEY (billed);
`--engine codex` drives the logged-in Codex CLI's built-in image tool (its own plan/auth).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from instadna import gemini  # noqa: E402

RULES = ('Photorealistic. Show only the described item(s) — no person, face, body, hands, mannequin head, text, captions, logos, '
         'watermarks, app UI or story stickers. Match the colours, materials, proportions and details visible in the reference '
         'frames; where the frames are unclear keep the design plain rather than inventing ornament.')


def sha(data):
    return hashlib.sha256(data).hexdigest()


CODEX_IMAGES = Path.home() / '.codex' / 'generated_images'


def codex_image(prompt, refs, wiki):
    """One built-in image_gen call through `codex exec`; returns (PNG bytes, model label, provenance)."""
    with tempfile.TemporaryDirectory() as tmp:
        args = ['codex', 'exec', '--skip-git-repo-check', '-s', 'read-only', '-c', 'model_reasoning_effort="low"']
        for ref in refs:
            png = Path(tmp) / f"{ref['id']}.png"
            with Image.open(wiki / ref['image']) as img:
                img.convert('RGB').save(png)
            args += ['-i', str(png)]
        text = ('Use your built-in image generation tool exactly once, then reply DONE. The attached images are reference frames '
                'from a creator\'s published media. ' + prompt)
        run = subprocess.run(args, input=text, capture_output=True, text=True, timeout=1200, cwd=tmp)
    session = re.search(r'session id: ([0-9a-f-]{36})', run.stdout + run.stderr)
    folder = CODEX_IMAGES / session[1] if session else None
    files = sorted(folder.glob('*.png')) if folder and folder.exists() else []
    if not files:
        raise RuntimeError('Codex returned no image: ' + (run.stdout + run.stderr)[-300:])
    agent = re.search(r'model: (\S+)', run.stdout + run.stderr)
    return files[-1].read_bytes(), f"Codex CLI built-in image tool ({agent[1] if agent else 'unknown'} agent)", {'codex_session': session[1]}


def generate(job, wiki, atlas, model, recipes, engine='gemini'):
    refs = [atlas[a] for a in job['reference_ids']]
    prompt = f"{job['prompt'].strip()}\n\n{RULES}"
    if engine == 'codex':
        data, label, provenance = codex_image(prompt, refs, wiki)
        return {**save_image(job, wiki, recipes, prompt, refs, data, label), **provenance}
    parts = [{'text': prompt}]
    for ref in refs:
        parts.append({'text': f"Reference frame {ref['id']}: {ref['title']}"})
        parts.append({'inline_data': {'mime_type': 'image/webp', 'data': base64.b64encode((wiki / ref['image']).read_bytes()).decode()}})
    body = {'contents': [{'role': 'user', 'parts': parts}],
            'generationConfig': {'responseModalities': ['IMAGE'], 'imageConfig': {'aspectRatio': job.get('aspect', '1:1'), 'imageSize': '2K'}}}
    response = gemini._request('POST', f'{gemini.BASE}/v1beta/models/{model}:generateContent', json=body, timeout=(20, 900))
    payload = response.json()
    images = [p['inlineData'] for c in payload.get('candidates', []) for p in c.get('content', {}).get('parts', []) if 'inlineData' in p]
    if not images:
        raise RuntimeError(f"{job['id']}: no image returned")
    return save_image(job, wiki, recipes, prompt, refs, base64.b64decode(images[0]['data']), payload.get('modelVersion', model))


def save_image(job, wiki, recipes, prompt, refs, data, label):
    with Image.open(io.BytesIO(data)) as img:
        img = img.convert('RGB')
        png = wiki / 'generated' / f"item-{job['id']}.png"
        png.parent.mkdir(exist_ok=True)
        img.save(png, 'PNG', optimize=True)
        thumb = png.with_suffix('.webp')
        small = img.copy()
        small.thumbnail((640, 640), Image.LANCZOS)
        small.save(thumb, 'WEBP', quality=82, method=6)
        width, height = img.size
    recipes.mkdir(parents=True, exist_ok=True)
    (recipes / f"{job['id']}.txt").write_text(prompt + '\n')
    return {'path': f"generated/item-{job['id']}.png", 'thumbnail': f"generated/item-{job['id']}.webp",
            'sha256': sha(png.read_bytes()), 'thumbnail_sha256': sha(thumb.read_bytes()), 'width': width, 'height': height,
            'kind': 'ai_visual_synthesis', 'model': label, 'item_id': job['id'],
            'prompt_sha256': sha(prompt.encode()), 'reference_ids': job['reference_ids'],
            'reference_sha256': [ref['sha256'] for ref in refs], 'generated_at': datetime.now(timezone.utc).isoformat(),
            'label': 'AI reconstruction from published frames; not a product replica or proof of ownership'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jobs', type=Path, required=True)
    parser.add_argument('--wiki', type=Path, required=True)
    parser.add_argument('--recipes', type=Path, required=True)
    parser.add_argument('--model', default='gemini-3-pro-image')
    parser.add_argument('--engine', choices=['gemini', 'codex'], default='gemini')
    parser.add_argument('--only', help='Comma-separated job IDs to (re)generate')
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    atlas = {r['id']: r for r in json.loads((args.wiki / 'atlas.json').read_text())['references']}
    jobs = json.loads(args.jobs.read_text())
    manifest_path = args.wiki / 'generated-images.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {'images': []}
    done = {r['item_id']: r for r in manifest['images']}
    wanted = set(args.only.split(',')) if args.only else None
    todo = [j for j in jobs if (wanted and j['id'] in wanted) or (not wanted and j['id'] not in done)]

    def run(job):
        try:
            return generate(job, args.wiki, atlas, args.model, args.recipes, args.engine)
        except Exception as error:  # reported, retried on the next run
            print(json.dumps({'job': job['id'], 'error': str(error)[:300]}), flush=True)
            return None

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for row in pool.map(run, todo):
            if row:
                done[row['item_id']] = row
                print(json.dumps({'generated': row['item_id']}), flush=True)
    order = [j['id'] for j in jobs]
    manifest['images'] = sorted(done.values(), key=lambda r: order.index(r['item_id']) if r['item_id'] in order else len(order))
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps({'images': len(manifest['images'])}))


if __name__ == '__main__':
    main()
