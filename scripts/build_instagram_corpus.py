#!/usr/bin/env python3
"""Turn recorded feed pages into an instadna corpus and download the media privately.

Input is the private output of collect_instagram_feed_browser.py. The result keeps
the `instadna` manifest layout (posts/<shortcode>/asset-NN.*) so the existing frame
sampling and transcription steps apply. Engagement numbers are retained only as
dated snapshots, never as identity evidence.
"""
import argparse
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

CONNECTION = 'xdt_api__v1__feed__user_timeline_graphql_connection'
KIND = {1: 'image', 2: 'video', 8: 'carousel'}


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.chmod(0o600)
    tmp.replace(path)


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts else None


def best(candidates):
    return max(candidates, key=lambda c: (c.get('width') or 0) * (c.get('height') or 0)) if candidates else None


def music(node):
    meta = node.get('clips_metadata') or {}
    info = (meta.get('music_info') or {}).get('music_asset_info') or {}
    original = meta.get('original_sound_info') or {}
    if info:
        return {'type': meta.get('audio_type'), 'title': info.get('title'), 'artist': info.get('display_artist'),
                'audio_id': info.get('audio_asset_id') or info.get('audio_cluster_id'), 'explicit': info.get('is_explicit')}
    if original:
        owner = (original.get('ig_artist') or {}).get('username')
        return {'type': meta.get('audio_type') or 'original_sound', 'title': original.get('original_audio_title'),
                'artist': owner, 'audio_id': original.get('audio_asset_id'), 'original_owner': owner}
    return {'type': meta.get('audio_type')} if meta.get('audio_type') else None


def normalize(node, username):
    children = node.get('carousel_media') or [node]
    caption = (node.get('caption') or {}).get('text') or ''
    owner = (node.get('user') or {}).get('username', '').lower()
    coauthors = sorted({(c.get('username') or '').lower() for c in node.get('coauthor_producers') or [] if c.get('username')})
    tags = []
    for i, child in enumerate(children):
        for tag in ((child.get('usertags') or {}).get('in') or []):
            user = tag.get('user') or {}
            tags.append({'asset_index': i, 'username': user.get('username'), 'full_name': user.get('full_name')})
    assets = []
    for i, child in enumerate(children):
        video = child.get('media_type') == 2
        source = best(child.get('video_versions') or []) if video else best((child.get('image_versions2') or {}).get('candidates') or [])
        assets.append({'index': i, 'kind': 'video' if video else 'image', 'duration': child.get('video_duration'),
                       'width': (source or {}).get('width'), 'height': (source or {}).get('height'),
                       'accessibility_caption': child.get('accessibility_caption'), 'status': 'missing_url',
                       '_url': (source or {}).get('url'),
                       '_poster': best((child.get('image_versions2') or {}).get('candidates') or []) if video else None})
    location = node.get('location') or None
    return {'shortcode': node['code'], 'url': f"https://www.instagram.com/p/{node['code']}/", 'media_pk': str(node.get('pk')),
            'discovered_via': ['authenticated_profile_grid'], 'owner': owner, 'coauthors': coauthors,
            'associated': owner == username or username in coauthors,
            'published_at': iso(node.get('taken_at')), 'date_basis': 'Instagram taken_at (publication timestamp, UTC)',
            'archive': {'createdAt': iso(node.get('taken_at'))}, 'type': KIND.get(node.get('media_type')),
            'product_type': node.get('product_type'), 'caption': caption, 'caption_edited': node.get('caption_is_edited'),
            'usertags': tags, 'music': music(node), 'has_audio': node.get('has_audio'),
            'location': {'name': location.get('name')} if location else None,
            'paid_partnership': bool(node.get('is_paid_partnership')), 'pinned': bool(node.get('timeline_pinned_user_ids')),
            'snapshot_metrics': {'like_count': node.get('like_count'), 'comment_count': node.get('comment_count'),
                                 'view_count': node.get('view_count') or node.get('play_count'), 'as_of': None},
            'assets': assets}


def fetch(root, post, asset):
    url = asset.pop('_url', None)
    poster = asset.pop('_poster', None)
    suffix = '.mp4' if asset['kind'] == 'video' else '.jpg'
    path = root / 'posts' / post['shortcode'] / f"asset-{asset['index']:02d}{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.exists():
        host = urlparse(url or '').hostname or ''
        if not url or not any(host.endswith('.' + d) for d in ('cdninstagram.com', 'fbcdn.net')):
            return asset
        try:
            with requests.get(url, headers={'Referer': 'https://www.instagram.com/'}, timeout=(20, 180), stream=True) as r:
                r.raise_for_status()
                part = path.with_suffix(suffix + '.part')
                with part.open('wb') as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            if part.stat().st_size < 500:
                raise ValueError('Media response too small')
            part.replace(path)
        except (requests.RequestException, ValueError, OSError) as error:
            asset.update(status='failed', error=type(error).__name__)
            return asset
    if poster and asset['kind'] == 'video':
        cover = path.with_name(f"poster-{asset['index']:02d}.jpg")
        if not cover.exists():
            try:
                r = requests.get(poster['url'], headers={'Referer': 'https://www.instagram.com/'}, timeout=(20, 60))
                r.raise_for_status()
                cover.write_bytes(r.content)
            except requests.RequestException:
                pass
        if cover.exists():
            asset['poster'] = str(cover.relative_to(root))
    asset.update(status='downloaded', path=str(path.relative_to(root)), bytes=path.stat().st_size,
                 sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    return asset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feed', type=Path, required=True, help='Private feed capture directory')
    parser.add_argument('--root', type=Path, required=True, help='Private instadna corpus directory')
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--no-download', action='store_true')
    parser.add_argument('--profile-posts', type=int, help='Profile post count observed separately, e.g. from the public embed')
    args = parser.parse_args()
    os.umask(0o077)
    capture = json.loads((args.feed / 'feed-manifest.json').read_text())
    username = capture['username']
    nodes = {}
    for page in sorted((args.feed / 'feed').glob('page-*.json')):
        for edge in json.loads(page.read_text())['data'][CONNECTION].get('edges', []):
            nodes.setdefault(edge['node']['code'], (edge['node'], page.name))
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    posts = []
    for code, (node, page) in nodes.items():
        post = normalize(node, username)
        post['capture_page'] = page
        post['snapshot_metrics']['as_of'] = capture['pages'][int(page[5:9]) - 1]['retrieved_at']
        posts.append(post)
        save(root / 'posts' / code / 'media.json', node)
    posts.sort(key=lambda p: p['published_at'] or '', reverse=True)
    if not args.no_download:
        jobs = [(p, a) for p in posts for a in p['assets']]
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for i, _ in enumerate(pool.map(lambda job: fetch(root, *job), jobs), 1):
                if i % 100 == 0 or i == len(jobs):
                    print(json.dumps({'assets': i, 'of': len(jobs)}), flush=True)
    for p in posts:
        for a in p['assets']:
            a.pop('_url', None)
            a.pop('_poster', None)
        ok = sum(a['status'] == 'downloaded' for a in p['assets'])
        p['status'] = 'downloaded' if ok == len(p['assets']) else 'partial' if ok else 'metadata_only'
        if not p['associated']:
            p['status'] = 'excluded_owner_mismatch'
    manifest = {'username': username, 'profile_url': f'https://www.instagram.com/{username}/', 'retrieved_at': capture['started_at'],
                'capture_finished_at': capture.get('finished_at'), 'profile_posts_reported': args.profile_posts or capture.get('profile_posts_reported'),
                'feed_exhausted': capture.get('feed_exhausted'), 'account_complete': False,
                'attempts': [{'source': 'authenticated_profile_grid', 'status': 'ok', 'records': len(posts)}], 'posts': posts}
    save(root / 'manifest.json', manifest)
    print(json.dumps({'posts': len(posts), 'downloaded': sum(p['status'] == 'downloaded' for p in posts),
                      'assets': sum(len(p['assets']) for p in posts)}))


if __name__ == '__main__':
    main()
