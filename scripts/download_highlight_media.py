#!/usr/bin/env python3
"""Download the selected CDN candidates from a private Highlight capture."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse
import requests


def download(root, story_id, kind, candidates):
    candidate = max(candidates, key=lambda x: (x.get('width', 0) * x.get('height', 0), x.get('type', 0)))
    url = candidate['url']
    host = urlparse(url).hostname or ''
    if urlparse(url).scheme != 'https' or not any(host.endswith('.'+d) for d in ('cdninstagram.com', 'fbcdn.net')):
        return {'kind': kind, 'status': 'failed', 'error': 'Unsupported media host'}
    suffix = '.mp4' if kind == 'video' else '.jpg'
    name = 'media/' + story_id + suffix
    path = root / name
    if not path.exists():
        try:
            with requests.get(url, headers={'Referer': 'https://www.instagram.com/'}, timeout=(20, 120), stream=True) as response:
                response.raise_for_status()
                expected = 'video/' if kind == 'video' else 'image/'
                if not response.headers.get('Content-Type', '').startswith(expected):
                    raise ValueError('Unexpected media content type')
                with path.with_suffix(suffix+'.part').open('wb') as f:
                    for chunk in response.iter_content(1024*1024):
                        f.write(chunk)
                path.with_suffix(suffix+'.part').replace(path)
        except Exception as error:
            return {'kind': kind, 'status': 'failed', 'error': type(error).__name__}
    with path.open('rb') as media:
        digest = hashlib.file_digest(media, 'sha256').hexdigest()
    return {'kind': kind, 'status': 'downloaded', 'path': name, 'bytes': path.stat().st_size,
            'sha256': digest}


def main(root):
    os.umask(0o077)
    manifest = json.loads((root/'manifest.json').read_text())
    (root/'media').mkdir(exist_ok=True, mode=0o700)
    jobs = {}
    for c in manifest['collections']:
        for item in c['items']:
            for kind, key in [('image', 'image_candidates'), ('video', 'video_candidates')]:
                if item[key]:
                    jobs[(item['story_id'], kind)] = item[key]
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(download, root, sid, kind, candidates): (sid, kind) for (sid, kind), candidates in jobs.items()}
        for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
            results[futures[future]] = future.result()
            if i % 25 == 0 or i == len(jobs):print(f'{i}/{len(jobs)} media assets processed', flush=True)
    for c in manifest['collections']:
        for item in c['items']:
            item['assets'] = [results[(item['story_id'], kind)] for kind in ('image', 'video') if (item['story_id'], kind) in results]
    (root/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'assets': len(results), 'downloaded': sum(x['status']=='downloaded' for x in results.values()),
                      'bytes': sum(x.get('bytes', 0) for x in results.values())}))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('root', type=Path)
    main(p.parse_args().root)
