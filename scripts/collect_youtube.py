#!/usr/bin/env python3
"""Inventory a YouTube channel and read each video's public watch-page metadata.

Uses yt-dlp's flat channel listing and the watch page's initial data (title, date,
description, view/like counts). No media is downloaded: this host can receive a
bot check for playback, so content analysis happens separately by URL. Optional
cookies come from a private Netscape cookie file. Requires yt-dlp.
"""
import argparse
import hashlib
import http.cookiejar
import json
import os
import random
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36'


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.chmod(0o600)
    tmp.replace(path)


def walk(value, key):
    found = []
    stack = [value]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            for k, v in x.items():
                if k == key:
                    found.append(v)
                stack.append(v)
        elif isinstance(x, list):
            stack.extend(x)
    return found


def listing(handle, cookies):
    import yt_dlp
    options = {'extract_flat': True, 'quiet': True, 'no_warnings': True, 'skip_download': True}
    if cookies:
        options['cookiefile'] = str(cookies)
    tabs = {}
    with yt_dlp.YoutubeDL(options) as ydl:
        for tab in ['videos', 'shorts', 'streams']:
            try:
                info = ydl.extract_info(f'https://www.youtube.com/@{handle}/{tab}', download=False)
            except yt_dlp.utils.DownloadError as error:
                tabs[tab] = {'status': 'unavailable', 'reason': str(error)[-160:]}
                continue
            tabs[tab] = {'status': 'ok', 'channel': {k: info.get(k) for k in ['channel', 'channel_id', 'channel_follower_count', 'description', 'tags', 'uploader_id']},
                         'entries': [{k: e.get(k) for k in ['id', 'title', 'duration', 'view_count']} for e in info.get('entries', [])]}
    return tabs


def parse_date(text):
    for fmt in ('%b %d, %Y', '%d %b %Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(text.replace('Premiered ', '').replace('Streamed live on ', ''), fmt).date().isoformat()
        except (ValueError, AttributeError):
            continue
    return None


def watch_metadata(opener, video_id):
    with opener.open(f'https://www.youtube.com/watch?v={video_id}', timeout=40) as response:
        page = response.read().decode('utf-8', 'replace')
    match = re.search(r'var ytInitialData = (\{.*?\});</script>', page)
    if not match:
        raise ValueError('Watch page has no initial data')
    data = json.loads(match[1])
    dates = [d.get('simpleText') for d in walk(data, 'publishDate') + walk(data, 'dateText') if isinstance(d, dict)]
    description = next((d.get('content') for d in walk(data, 'attributedDescription') if isinstance(d, dict) and d.get('content')), None)
    views = next((v['videoViewCountRenderer'].get('originalViewCount') for v in walk(data, 'viewCount')
                  if isinstance(v, dict) and 'videoViewCountRenderer' in v), None)
    likes = None
    for group in walk(data, 'factoid'):
        for f in group if isinstance(group, list) else [group]:
            r = f.get('factoidRenderer') if isinstance(f, dict) else None
            if r and r.get('label', {}).get('simpleText') == 'Likes':
                likes = r.get('value', {}).get('simpleText')
    chapters = [{'title': m.get('title', {}).get('simpleText'), 'time': m.get('timeDescription', {}).get('simpleText')}
                for m in walk(data, 'macroMarkersListItemRenderer')]
    player = re.search(r'"playabilityStatus":\{"status":"([A-Z_]+)"', page)
    return {'id': video_id, 'url': f'https://www.youtube.com/watch?v={video_id}', 'date_text': dates[0] if dates else None,
            'published_date': parse_date(dates[0]) if dates else None,
            'date_basis': 'YouTube watch page publish date (day precision, UTC not stated)' if dates else None,
            'description': description, 'hashtags': sorted(set(re.findall(r'#[\w\d_]+', description or ''))),
            'view_count_snapshot': int(views) if views and views.isdigit() else None, 'likes_snapshot_text': likes,
            'chapters': chapters, 'playability_on_this_host': player[1] if player else None,
            'retrieved_at': now(), 'page_sha256': hashlib.sha256(page.encode()).hexdigest()}


def thumbnails(root, ids, delay=0.3):
    """Creator-chosen cover (maxres, else hq) plus YouTube's three automatic frames, stored privately."""
    import requests
    folder = root / 'thumbnails'
    folder.mkdir(exist_ok=True, mode=0o700)
    index_path = root / 'thumbnails.json'
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    for video_id in ids:
        if video_id in index:
            continue
        entry = {}
        for label, names in [('cover', ['maxresdefault', 'sddefault', 'hqdefault']), ('auto1', ['hq1']), ('auto2', ['hq2']), ('auto3', ['hq3'])]:
            for name in names:
                r = requests.get(f'https://i.ytimg.com/vi/{video_id}/{name}.jpg', timeout=30)
                if r.ok and len(r.content) > 2000:
                    path = folder / f'{video_id}-{label}.jpg'
                    path.write_bytes(r.content)
                    entry[label] = {'path': str(path.relative_to(root)), 'variant': name, 'sha256': hashlib.sha256(r.content).hexdigest()}
                    break
        index[video_id] = entry
        time.sleep(delay)
    save(index_path, index)
    return index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--handle', required=True, help='Channel handle without @')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cookies', type=Path, help='Private Netscape cookie file')
    parser.add_argument('--delay', type=float, default=2.0)
    parser.add_argument('--thumbnails-only', action='store_true', help='Fetch covers and automatic frames for listed videos')
    args = parser.parse_args()
    handle = args.handle.removeprefix('@')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{3,30}', handle):
        parser.error('Invalid channel handle')
    os.umask(0o077)
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    channel_path = root / 'channel.json'
    if channel_path.exists():
        channel = json.loads(channel_path.read_text())
    else:
        channel = {'handle': handle, 'url': f'https://www.youtube.com/@{handle}', 'retrieved_at': now(), 'tabs': listing(handle, args.cookies),
                   'method': 'yt-dlp flat channel tabs', 'account_complete': False}
        save(channel_path, channel)
    if args.thumbnails_only:
        ids = [e['id'] for tab in channel['tabs'].values() for e in tab.get('entries', [])]
        print(json.dumps({'thumbnails': len(thumbnails(root, ids))}))
        return
    jar = http.cookiejar.MozillaCookieJar()
    if args.cookies:
        jar.load(str(args.cookies), ignore_discard=True, ignore_expires=True)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [('User-Agent', UA), ('Accept-Language', 'en-US,en;q=0.9')]
    records_path = root / 'videos.jsonl'
    done = {json.loads(line)['id'] for line in records_path.read_text().split('\n') if line.strip()} if records_path.exists() else set()
    entries = [(tab, e) for tab in ['videos', 'shorts', 'streams'] for e in channel['tabs'].get(tab, {}).get('entries', [])]
    for i, (tab, entry) in enumerate(entries, 1):
        if entry['id'] in done:
            continue
        try:
            record = watch_metadata(opener, entry['id'])
            record.update(tab=tab, title=entry['title'], duration_s=entry.get('duration'), status='ok')
        except Exception as error:
            record = {'id': entry['id'], 'tab': tab, 'title': entry['title'], 'status': 'failed', 'error': type(error).__name__, 'retrieved_at': now()}
        with records_path.open('a') as out:
            out.write(json.dumps(record, ensure_ascii=False) + '\n')
        done.add(entry['id'])
        if i % 20 == 0 or i == len(entries):
            print(json.dumps({'metadata': i, 'of': len(entries)}), flush=True)
        time.sleep(random.uniform(args.delay, args.delay * 1.6))
    rows = [json.loads(line) for line in records_path.read_text().split('\n') if line.strip()]
    channel['metadata_summary'] = {'videos': len(rows), 'ok': sum(r['status'] == 'ok' for r in rows),
                                   'dated': sum(bool(r.get('published_date')) for r in rows), 'finished_at': now()}
    save(channel_path, channel)
    print(json.dumps(channel['metadata_summary']))


if __name__ == '__main__':
    main()
