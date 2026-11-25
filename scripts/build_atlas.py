#!/usr/bin/env python3
"""Extract reviewed source frames into a person wiki's evidence atlas (atlas.json + WebP files).

Input is an editorial selection: one row per screenshot with the source item, asset
index and time (or still), plus title/category/description/use/limit. Frames are cut
from the PRIVATE originals with FFmpeg and stored as a 1080 px WebP plus a thumbnail;
both hashes and the original media hash are recorded so the builder can verify them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_media_gemini import BUILDERS  # noqa: E402

PLATFORM = {'ig': 'instagram', 'igh': 'instagram_highlight', 'igs': 'instagram_story', 'tg': 'telegram', 'yt': 'youtube'}
BASIS = {'instagram': 'Instagram taken_at (publication timestamp, UTC)', 'instagram_highlight': 'Instagram story taken_at (UTC)',
         'instagram_story': 'Instagram story taken_at (UTC)', 'telegram': 'Telegram message date (UTC)',
         'youtube': 'YouTube watch page publish date (day precision)'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--corpus', action='append', required=True, help='builder=path (instagram, highlights, telegram, youtube)')
    parser.add_argument('--stories', type=Path, help='Current-stories capture (highlights layout)')
    parser.add_argument('--youtube-thumbnails', type=Path, help='YouTube metadata directory with thumbnails.json')
    parser.add_argument('--wiki', type=Path, required=True)
    parser.add_argument('--as-of', required=True)
    args = parser.parse_args()
    items = {}
    for spec in args.corpus:
        name, root = spec.split('=', 1)
        for item in BUILDERS[name](Path(root), ''):
            items[item['item_id']] = item
    if args.stories:
        for item in BUILDERS['highlights'](args.stories, ''):
            item['item_id'] = 'igs:' + item['item_id'].split(':', 1)[1]
            item['platform'] = 'instagram_story'
            items[item['item_id']] = item
    thumbs = json.loads((args.youtube_thumbnails / 'thumbnails.json').read_text()) if args.youtube_thumbnails else {}
    selection = json.loads(args.selection.read_text())
    out = args.wiki / 'references'
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for sel in selection:
        prefix = sel['source_id'].split(':', 1)[0]
        platform = PLATFORM[prefix]
        if platform == 'youtube':
            entry = thumbs[sel['source_id'][3:]][sel.get('variant', 'cover')]
            media_path, kind, url = args.youtube_thumbnails / entry['path'], 'image', f"https://www.youtube.com/watch?v={sel['source_id'][3:]}"
            published = sel.get('published_at')
        else:
            item = items[sel['source_id']]
            media = next(m for m in item['media'] if m['index'] == sel['asset_index'])
            media_path, kind, url, published = Path(media['path']), media['kind'], item['source_url'], item['published_at']
        with tempfile.TemporaryDirectory() as tmp:
            still = Path(tmp) / 'frame.png'
            if kind == 'video':
                if not isinstance(sel.get('time_seconds'), (int, float)):
                    raise ValueError(f"{sel['id']}: a video source needs time_seconds")
                subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(sel['time_seconds']), '-i', str(media_path), '-frames:v', '1', str(still)],
                               check=True, capture_output=True)
            else:
                still = media_path
            with Image.open(still) as img:
                img = ImageOps.exif_transpose(img).convert('RGB')
                full = img.copy()
                full.thumbnail((1080, 1350), Image.LANCZOS)
                small = img.copy()
                small.thumbnail((540, 675), Image.LANCZOS)
        image, thumb = out / f"{sel['id']}.webp", out / f"{sel['id']}-thumb.webp"
        full.save(image, 'WEBP', quality=86, method=6)
        small.save(thumb, 'WEBP', quality=78, method=6)
        rows.append({'id': sel['id'], 'platform': platform, 'source_id': sel['source_id'], 'source_url': url,
                     'published_at': published, 'date_basis': BASIS[platform] if published else None,
                     'asset_index': sel['asset_index'], 'time_seconds': sel['time_seconds'] if kind == 'video' else None,
                     'kind': 'video_frame' if kind == 'video' else 'image',
                     **{k: sel[k] for k in ['title', 'category', 'description', 'use', 'limit']},
                     'image': f"references/{sel['id']}.webp", 'thumbnail': f"references/{sel['id']}-thumb.webp",
                     'width': full.width, 'height': full.height, 'sha256': sha(image), 'thumbnail_sha256': sha(thumb),
                     'source_media_sha256': sha(media_path)})
    (args.wiki / 'atlas.json').write_text(json.dumps({'schema': 'instadna.atlas/v1', 'as_of': args.as_of,
                                                      'generated_at': datetime.now(timezone.utc).isoformat(), 'references': rows},
                                                     ensure_ascii=False, indent=1) + '\n')
    print(json.dumps({'references': len(rows)}))


if __name__ == '__main__':
    main()
