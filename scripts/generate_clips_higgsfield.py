#!/usr/bin/env python3
"""Animate each approved storyboard start frame into a short clip with an image-to-video model on Higgsfield.

Uses the logged-in Higgsfield CLI (`higgsfield auth login`; no API key passes through this script). For every shot in
the clips plan: the start frame (WebP) is converted to PNG, a job is created with the plan's style and the shot's motion
prompt plus the given model parameters (`--param resolution=480p` and so on), the CLI waits for it, and the result MP4
is downloaded into private storage. One paid job per shot and run: a shot that already has a clip is skipped, a failure
is recorded and never retried automatically. `--estimate` only asks the CLI for the cost. The private manifest records
the model, parameters, prompt hash, job id, output hash, duration and size; clips are AI-generated planning material.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

LOCK = threading.Lock()


def cli(args, timeout=1800):
    run = subprocess.run(['higgsfield', '--json', '--no-color', *args], capture_output=True, text=True, timeout=timeout)
    if run.returncode != 0:
        raise RuntimeError((run.stderr or run.stdout).strip()[-600:])
    out = run.stdout.strip()
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        start = min((i for i in (out.find('{'), out.find('[')) if i >= 0), default=-1)
        return json.loads(out[start:]) if start >= 0 else {'raw': out}


def urls(obj):
    found = []
    if isinstance(obj, dict):
        for v in obj.values():
            found += urls(v)
    elif isinstance(obj, list):
        for v in obj:
            found += urls(v)
    elif isinstance(obj, str) and re.match(r'https://\S+\.(mp4|mov|webm)(\?\S*)?$', obj):
        found.append(obj)
    return found


def job_id(obj):
    if isinstance(obj, dict):
        for key in ('job_id', 'id', 'jobId'):
            if isinstance(obj.get(key), str):
                return obj[key]
        for v in obj.values():
            j = job_id(v)
            if j:
                return j
    if isinstance(obj, list):
        for v in obj:
            j = job_id(v)
            if j:
                return j
    return None


def probe(path):
    info = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)]))
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    return {'duration_s': round(float(info['format']['duration']), 3), 'width': video['width'], 'height': video['height'],
            'audio': any(s['codec_type'] == 'audio' for s in info['streams'])}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--frames-dir', type=Path, required=True, help='Folder with the approved <shot>.webp start frames')
    p.add_argument('--model', required=True, help='Higgsfield job_set_type of the image-to-video model')
    p.add_argument('--param', action='append', default=[], help='name=value passed as --name value')
    p.add_argument('--image-flag', default='image', help='Media flag for the start frame (image or start-image)')
    p.add_argument('--out', type=Path, required=True, help='Private folder for the clips and the manifest')
    p.add_argument('--only', help='Comma-separated shot IDs')
    p.add_argument('--workers', type=int, default=3)
    p.add_argument('--estimate', action='store_true', help='Only estimate the cost; nothing is generated')
    a = p.parse_args()
    plan = json.loads(a.plan.read_text())
    params = [x for kv in a.param for x in (f"--{kv.split('=', 1)[0]}", kv.split('=', 1)[1])]
    a.out.mkdir(parents=True, exist_ok=True)
    manifest_path = a.out / 'clips-manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {'clips': []}
    done = {r['shot'] for r in manifest['clips'] if r.get('sha256')}
    wanted = set(a.only.split(',')) if a.only else None
    todo = [s for s in plan['shots'] if (not wanted or s['shot'] in wanted) and s['shot'] not in done]

    def prompt_of(s):
        return f"{s['prompt']} {plan['style']}"

    if a.estimate:
        total = []
        for s in todo[:1]:
            frame = a.frames_dir / f"{s['shot']}.webp"
            with tempfile.TemporaryDirectory() as tmp:
                png = Path(tmp) / f"{s['shot']}.png"
                Image.open(frame).convert('RGB').save(png)
                total.append(cli(['generate', 'cost', a.model, '--prompt', prompt_of(s), f'--{a.image_flag}', str(png), *params]))
        print(json.dumps({'shots': len(todo), 'one_shot_cost': total[0] if total else None}, ensure_ascii=False))
        return

    def run(s):
        shot, frame = s['shot'], a.frames_dir / f"{s['shot']}.webp"
        prompt = prompt_of(s)
        row = {'shot': shot, 'model': a.model, 'params': dict(kv.split('=', 1) for kv in a.param), 'prompt_sha256':
               hashlib.sha256(prompt.encode()).hexdigest(), 'start_frame_sha256': hashlib.sha256(frame.read_bytes()).hexdigest(),
               'requested_at': datetime.now(timezone.utc).isoformat()}
        try:
            with tempfile.TemporaryDirectory() as tmp:
                png = Path(tmp) / f'{shot}.png'
                Image.open(frame).convert('RGB').save(png)
                res = cli(['generate', 'create', a.model, '--prompt', prompt, f'--{a.image_flag}', str(png), *params,
                           '--wait', '--wait-timeout', '25m', '--wait-interval', '5s'])
            row['job_id'] = job_id(res)
            found = urls(res)
            if not found:
                raise RuntimeError('no video URL in the response: ' + json.dumps(res)[:400])
            dest = a.out / f'{shot}.mp4'
            urllib.request.urlretrieve(found[0], dest)
            row.update(path=dest.name, sha256=hashlib.sha256(dest.read_bytes()).hexdigest(), **probe(dest),
                       finished_at=datetime.now(timezone.utc).isoformat())
            (a.out / f'{shot}.response.json').write_text(json.dumps(res, ensure_ascii=False, indent=1))
            print(json.dumps({'generated': shot, 'duration_s': row['duration_s'], 'size': [row['width'], row['height']]}), flush=True)
        except Exception as error:  # recorded, never retried automatically
            row['error'] = str(error)[:600]
            print(json.dumps({'shot': shot, 'error': row['error'][:200]}, ensure_ascii=False), flush=True)
        with LOCK:
            manifest['clips'] = [r for r in manifest['clips'] if r['shot'] != shot] + [row]
            manifest['clips'].sort(key=lambda r: r['shot'])
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + '\n')
        return row

    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        rows = list(pool.map(run, todo))
    print(json.dumps({'requested': len(todo), 'ok': sum(1 for r in rows if r.get('sha256')), 'failed': sum(1 for r in rows if r.get('error'))}))


if __name__ == '__main__':
    main()
