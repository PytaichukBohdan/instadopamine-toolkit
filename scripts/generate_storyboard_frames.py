#!/usr/bin/env python3
"""Generate storyboard start frames (one per shot) with the logged-in Codex CLI's built-in image tool.

Each shot in the storyboard spec names its reference images:
  atlas:A004            an atlas frame (wiki/references/A004.webp)
  item:<passport id>    a passport item image (wiki/generated/item-<id>.png)
  frame:<shot id>       an earlier frame of this storyboard, e.g. its identity anchor
  wiki:<path>           any file in the wiki, e.g. another round's frame
  private:<name>        a private file passed with --private-ref name=path (never copied into the wiki)
The prompt is the spec's shared style and identity blocks, the shot's scene text, its caption zone and the
rules. Outputs per shot: the original PNG in private storage, a 9:16 WebP frame and a thumbnail under
wiki/<frames dir>, and a row in the frames manifest with the model, prompt hash and every reference hash.
Frames are AI illustrations for planning a video, never evidence of anything that happened.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

CODEX_IMAGES = Path.home() / '.codex' / 'generated_images'
ASPECT = 9 / 16
MAX_REFS = 5  # Codex image_gen: `referenced_image_paths` must contain at most 5 paths
LOCK = threading.Lock()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def resolve_ref(ref, wiki, frames_dir, private):
    kind, _, name = ref.partition(':')
    if kind == 'atlas':
        return wiki / 'references' / f'{name}.webp'
    if kind == 'item':
        return wiki / 'generated' / f'item-{name}.png'
    if kind == 'frame':
        return wiki / frames_dir / f'{name}.webp'
    if kind == 'wiki':
        return wiki / name
    if kind == 'private':
        return Path(private[name])
    raise ValueError(f'Unknown reference {ref}')


def build_prompt(spec, shot):
    parts = [spec['style'], spec['identity'] if shot.get('person', True) else '', shot['scene'].strip()]
    if shot.get('caption_zone'):
        parts.append(f"Leave the {shot['caption_zone']} of the frame calm and low-detail: one large caption word will be "
                     'added there later in post. Do not draw that word or any other text.')
    parts.append(spec['rules'] if not shot.get('rules') else shot['rules'])
    return '\n\n'.join(p.strip() for p in parts if p and p.strip())


def codex_image(prompt, refs, effort):
    """One built-in image_gen call through `codex exec`; returns (PNG bytes, model label, session id)."""
    with tempfile.TemporaryDirectory() as tmp:
        args = ['codex', 'exec', '--skip-git-repo-check', '-s', 'read-only', '-c', f'model_reasoning_effort="{effort}"']
        listing = []
        for n, (label, path) in enumerate(refs, 1):
            png = Path(tmp) / f'ref-{n:02d}.png'
            with Image.open(path) as img:
                img.convert('RGB').save(png)
            args += ['-i', str(png)]
            listing.append(f'Attached image {n}: {label}')
        text = ('Use your built-in image generation tool exactly once to create ONE vertical portrait image '
                '(9:16 or the tallest portrait size available), then reply DONE. Do not write files or run commands.\n\n'
                + '\n'.join(listing) + '\n\n' + prompt)
        run = subprocess.run(args, input=text, capture_output=True, text=True, timeout=1500, cwd=tmp)
    log = run.stdout + run.stderr
    session = re.search(r'session id: ([0-9a-f-]{36})', log)
    folder = CODEX_IMAGES / session[1] if session else None
    files = sorted(folder.glob('*.png')) if folder and folder.exists() else []
    if not files:
        raise RuntimeError('Codex returned no image: ' + log[-400:])
    agent = re.search(r'model: (\S+)', log)
    return files[-1].read_bytes(), f"Codex CLI built-in image tool ({agent[1] if agent else 'unknown'} agent)", session[1]


def crop_vertical(img):
    w, h = img.size
    if w / h > ASPECT:  # too wide: trim the sides
        nw = round(h * ASPECT)
        x = (w - nw) // 2
        return img.crop((x, 0, x + nw, h))
    nh = round(w / ASPECT)  # too tall: trim top and bottom evenly
    y = (h - nh) // 2
    return img.crop((0, y, w, y + nh))


def save_frame(shot, data, wiki, frames_dir, private_out, prompt, refs, label, session):
    private_out.mkdir(parents=True, exist_ok=True)
    original = private_out / f"{shot['id']}.png"
    original.write_bytes(data)
    out_dir = wiki / frames_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(original) as img:
        source_size = img.size
        frame = crop_vertical(img.convert('RGB'))
        path = out_dir / f"{shot['id']}.webp"
        frame.save(path, 'WEBP', quality=86, method=6)
        thumb = out_dir / f"{shot['id']}-thumb.webp"
        small = frame.copy()
        small.thumbnail((360, 640), Image.LANCZOS)
        small.save(thumb, 'WEBP', quality=80, method=6)
        width, height = frame.size
    return {'shot': shot['id'], 'path': f"{frames_dir}/{shot['id']}.webp", 'thumbnail': f"{frames_dir}/{shot['id']}-thumb.webp",
            'sha256': sha(path.read_bytes()), 'thumbnail_sha256': sha(thumb.read_bytes()), 'width': width, 'height': height,
            'source_width': source_size[0], 'source_height': source_size[1], 'original_sha256': sha(data),
            'kind': 'ai_storyboard_frame', 'model': label, 'codex_session': session,
            'prompt_sha256': sha(prompt.encode()), 'references': [{'ref': r, 'sha256': sha(Path(p).read_bytes())} for r, p in refs],
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'label': 'AI-generated storyboard frame (synthetic likeness for planning); not a photograph or evidence'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--wiki', type=Path, required=True)
    parser.add_argument('--frames-dir', default='storyboard')
    parser.add_argument('--manifest', type=Path, required=True, help='Frames manifest JSON (inside the wiki)')
    parser.add_argument('--private-out', type=Path, required=True, help='Private directory for original PNGs and prompts')
    parser.add_argument('--private-ref', action='append', default=[], help='name=path for private references')
    parser.add_argument('--only', help='Comma-separated shot IDs to (re)generate')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--effort', default='low')
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text())
    private = dict(item.split('=', 1) for item in args.private_ref)
    manifest = json.loads(args.manifest.read_text()) if args.manifest.exists() else {'schema': 'instadna.storyboard-frames/v1', 'frames': []}
    done = {r['shot']: r for r in manifest['frames']}
    wanted = set(args.only.split(',')) if args.only else None
    shots = [s for s in spec['shots'] if s.get('generate', True)]
    todo = [s for s in shots if (wanted and s['id'] in wanted) or (not wanted and s['id'] not in done)]

    def run(shot):
        prompt = build_prompt(spec, shot)
        if len(shot.get('refs', [])) > MAX_REFS:
            raise ValueError(f"{shot['id']}: the image tool accepts at most {MAX_REFS} reference images")
        refs = []
        for ref in shot.get('refs', []):
            path = resolve_ref(ref, args.wiki, args.frames_dir, private)
            if not path.exists():
                raise FileNotFoundError(f"{shot['id']}: missing reference {ref}")
            refs.append((ref, path))
        labels = [(spec.get('ref_labels', {}).get(r.split(':')[0], r) + f' ({r})', p) for r, p in refs]
        try:
            data, label, session = codex_image(prompt, labels, args.effort)
        except Exception as error:  # reported; rerun picks it up
            print(json.dumps({'shot': shot['id'], 'error': str(error)[:300]}, ensure_ascii=False), flush=True)
            return None
        args.private_out.mkdir(parents=True, exist_ok=True)
        (args.private_out / f"{shot['id']}.prompt.txt").write_text(prompt + '\n')
        row = save_frame(shot, data, args.wiki, args.frames_dir, args.private_out, prompt, refs, label, session)
        with LOCK:
            done[row['shot']] = row
            order = [s['id'] for s in spec['shots']]
            manifest['frames'] = sorted(done.values(), key=lambda r: order.index(r['shot']) if r['shot'] in order else len(order))
            args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + '\n')
        print(json.dumps({'generated': row['shot'], 'size': [row['source_width'], row['source_height']]}), flush=True)
        return row

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(run, todo))
    print(json.dumps({'frames': len(manifest['frames']), 'requested': len(todo)}))


if __name__ == '__main__':
    main()
