#!/usr/bin/env python3
"""Read a PUBLIC Telegram channel through its t.me/s web preview, without any account.

Pages, signed CDN URLs and media stay in the private output. Voice notes, round
videos and photos exposed by the preview can be downloaded and hash-verified.
Videos the preview marks as unsupported are inventoried, not fetched; another
authorized route must supply them. Requires beautifulsoup4 and lxml.
"""
import argparse
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36'
CDN = ('telesco.pe', 'cdn-telegram.org', 'telegram-cdn.org')


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.chmod(0o600)
    tmp.replace(path)


def background(node):
    match = re.search(r"background-image:url\('([^']+)'\)", (node or {}).get('style', '') if node else '')
    return match[1] if match else None


def seconds(text):
    if not text:
        return None
    parts = [int(x) for x in re.findall(r'\d+', text)]
    total = 0
    for part in parts:
        total = total * 60 + part
    return total


def plain(node):
    if not node:
        return ''
    for br in node.find_all('br'):
        br.replace_with('\n')
    return node.get_text().strip()


def parse_message(wrap, channel):
    msg = wrap.select_one('.tgme_widget_message')
    post = msg.get('data-post', '')
    if not re.fullmatch(re.escape(channel) + r'/\d+', post, flags=re.I):
        return None
    mid = int(post.split('/')[1])
    text_node = msg.select_one('.tgme_widget_message_text')
    links = sorted({a['href'] for a in text_node.find_all('a', href=True)}) if text_node else []
    stamp = msg.select_one('.tgme_widget_message_date time')
    views = msg.select_one('.tgme_widget_message_views')
    forward = msg.select_one('.tgme_widget_message_forwarded_from')
    reply = msg.select_one('a.tgme_widget_message_reply')
    record = {'id': mid, 'source_url': f'https://t.me/{channel}/{mid}', 'published_at': stamp.get('datetime') if stamp else None,
              'retrieved_at': now(), 'text': plain(text_node), 'links': links,
              'author_signature': plain(msg.select_one('.tgme_widget_message_from_author')) or None,
              'views_text': views.get_text(strip=True) if views else None,
              'edited': bool(msg.select_one('.tgme_widget_message_meta') and 'edited' in msg.select_one('.tgme_widget_message_meta').get_text()),
              'forward': {'from': plain(forward.select_one('.tgme_widget_message_forwarded_from_name')) or plain(forward),
                          'url': (forward.select_one('a[href]') or {}).get('href') if forward.select_one('a[href]') else None} if forward else None,
              'reply_to': int(re.search(r'/(\d+)(?:\?|$)', reply['href'])[1]) if reply and re.search(r'/(\d+)(?:\?|$)', reply.get('href', '')) else None,
              'media': []}
    for photo in msg.select('a.tgme_widget_message_photo_wrap'):
        target = re.search(r'/(\d+)(?:\?|$)', photo.get('href', ''))
        record['media'].append({'kind': 'photo', 'message_id': int(target[1]) if target else mid, 'url': background(photo)})
    for voice in msg.select('audio.tgme_widget_message_voice'):
        record['media'].append({'kind': 'voice', 'message_id': mid, 'url': voice.get('src'),
                                'duration_s': seconds(plain(msg.select_one('.tgme_widget_message_voice_duration')))})
    for rv in msg.select('video.tgme_widget_message_roundvideo'):
        record['media'].append({'kind': 'round_video', 'message_id': mid, 'url': rv.get('src'),
                                'duration_s': seconds(plain(msg.select_one('.tgme_widget_message_roundvideo_duration')))})
    for player in msg.select('a.tgme_widget_message_video_player'):
        target = re.search(r'/(\d+)(?:\?|$)', player.get('href', ''))
        video = player.select_one('video')
        record['media'].append({'kind': 'video', 'message_id': int(target[1]) if target else mid,
                                'url': video.get('src') if video else None,
                                'preview_supported': 'not_supported' not in player.get('class', []),
                                'thumbnail_url': background(player.select_one('.tgme_widget_message_video_thumb')),
                                'duration_s': seconds(plain(player.select_one('.message_video_duration')))})
    for doc in msg.select('.tgme_widget_message_document'):
        record['media'].append({'kind': 'document', 'message_id': mid, 'url': None,
                                'title': plain(doc.select_one('.tgme_widget_message_document_title')),
                                'size_text': plain(doc.select_one('.tgme_widget_message_document_extra'))})
    poll = msg.select_one('.tgme_widget_message_poll')
    if poll:
        record['poll'] = {'question': plain(poll.select_one('.tgme_widget_message_poll_question')),
                          'options': [plain(o.select_one('.tgme_widget_message_poll_option_text')) for o in poll.select('.tgme_widget_message_poll_option')]}
    preview = msg.select_one('.tgme_widget_message_link_preview')
    if preview:
        record['link_preview'] = {'url': preview.get('href'), 'site': plain(preview.select_one('.link_preview_site_name')),
                                  'title': plain(preview.select_one('.link_preview_title')),
                                  'description': plain(preview.select_one('.link_preview_description'))}
    if msg.select_one('.tgme_widget_message_sticker_wrap'):
        record['media'].append({'kind': 'sticker', 'message_id': mid, 'url': None})
    return record


def collect(channel, root, delay, max_pages):
    os.umask(0o077)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest_path = root / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {
        'version': 1, 'source': 'telegram_public_preview', 'channel': channel, 'channel_url': f'https://t.me/{channel}',
        'started_at': now(), 'pages': 0, 'next_before': None, 'history_scan_exhausted': False, 'account_complete': False,
        'limits': 'Public web preview only: deleted posts, edits history, comments and preview-unsupported videos are not recovered.'}
    if manifest['channel'] != channel:
        raise ValueError('Corpus belongs to another channel')
    messages_path = root / 'messages.jsonl'
    records = {}
    if messages_path.exists():
        for line in filter(str.strip, messages_path.read_text().split('\n')):
            row = json.loads(line)
            records[row['id']] = row
    session = requests.Session()
    session.headers.update({'User-Agent': UA, 'Accept-Language': 'en-US,en;q=0.9'})
    while not manifest['history_scan_exhausted'] and manifest['pages'] < max_pages:
        before = manifest['next_before']
        url = f'https://t.me/s/{channel}' + (f'?before={before}' if before else '')
        response = session.get(url, timeout=(15, 60))
        response.raise_for_status()
        number = manifest['pages'] + 1
        page_path = root / 'pages' / f'page-{number:04d}.html'
        page_path.parent.mkdir(exist_ok=True, mode=0o700)
        page_path.write_text(response.text)
        soup = BeautifulSoup(response.text, 'lxml')
        if number == 1:
            info = {'title': plain(soup.select_one('.tgme_channel_info_header_title')),
                    'description': plain(soup.select_one('.tgme_channel_info_description')),
                    'counters': {plain(c.select_one('.counter_type')): plain(c.select_one('.counter_value')) for c in soup.select('.tgme_channel_info_counter')}}
            manifest['channel_info'] = info
        found = [parse_message(w, channel) for w in soup.select('.tgme_widget_message_wrap')]
        found = [r for r in found if r]
        new = [r for r in found if r['id'] not in records]
        with messages_path.open('a') as out:
            for row in new:
                out.write(json.dumps(row, ensure_ascii=False) + '\n')
                records[row['id']] = row
        manifest['pages'] = number
        ids = [r['id'] for r in found]
        if not ids or min(ids) <= 1 or (before and min(ids) >= before):
            manifest['history_scan_exhausted'] = True
        else:
            manifest['next_before'] = min(ids)
        manifest['messages_retrieved'] = len(records)
        save(manifest_path, manifest)
        print(json.dumps({'page': number, 'messages': len(records), 'oldest': min(ids) if ids else None}), flush=True)
        time.sleep(delay)
    rows = sorted(records.values(), key=lambda r: r['id'])
    media = [m for r in rows for m in r['media']]
    manifest.update(messages_retrieved=len(rows), first_publication=min((r['published_at'] for r in rows if r['published_at']), default=None),
                    last_publication=max((r['published_at'] for r in rows if r['published_at']), default=None),
                    text_messages=sum(bool(r['text'].strip()) for r in rows), forwarded_messages=sum(bool(r['forward']) for r in rows),
                    media_counts={k: sum(m['kind'] == k for m in media) for k in sorted({m['kind'] for m in media})},
                    preview_unsupported_videos=sum(m['kind'] == 'video' and not m.get('url') for m in media),
                    id_gaps=len(set(range(rows[0]['id'], rows[-1]['id'] + 1)) - {r['id'] for r in rows} - {m['message_id'] for m in media}) if rows else 0,
                    finished_at=now())
    save(manifest_path, manifest)
    return manifest, rows


def download(root, rows, kinds, workers=4):
    from concurrent.futures import ThreadPoolExecutor
    downloads_path = root / 'downloads.json'
    done = json.loads(downloads_path.read_text()) if downloads_path.exists() else {}
    jobs = []
    for row in rows:
        for index, m in enumerate(row['media']):
            if m['kind'] in kinds and m.get('url'):
                key = f"{row['id']}-{index}"
                old = done.get(key)
                if old and old.get('status') == 'downloaded' and (root / old['path']).exists():
                    continue
                jobs.append((key, row['id'], m))

    def fetch(job):
        key, mid, m = job
        host = urlparse(m['url']).hostname or ''
        if urlparse(m['url']).scheme != 'https' or not any(host == d or host.endswith('.' + d) for d in CDN):
            return key, {'status': 'failed', 'error': 'Unsupported media host', 'kind': m['kind']}
        ext = {'voice': '.ogg', 'round_video': '.mp4', 'video': '.mp4', 'photo': '.jpg'}[m['kind']]
        relative = f"media/{m['kind']}/{key}{ext}"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            with requests.get(m['url'], headers={'User-Agent': UA, 'Referer': 'https://t.me/'}, timeout=(20, 180), stream=True) as r:
                r.raise_for_status()
                part = path.with_suffix(ext + '.part')
                with part.open('wb') as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            if part.stat().st_size < 200:
                raise ValueError('Media response too small')
            part.replace(path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            return key, {'status': 'downloaded', 'kind': m['kind'], 'message_id': m['message_id'], 'path': relative,
                         'bytes': path.stat().st_size, 'sha256': digest, 'retrieved_at': now()}
        except (requests.RequestException, ValueError, OSError) as error:
            return key, {'status': 'failed', 'kind': m['kind'], 'error': type(error).__name__}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, (key, result) in enumerate(pool.map(fetch, jobs), 1):
            done[key] = result
            if i % 25 == 0 or i == len(jobs):
                save(downloads_path, done)
                print(json.dumps({'downloaded': i, 'of': len(jobs)}), flush=True)
    save(downloads_path, done)
    return done


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--channel', required=True, help='Public channel username, e.g. durov')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--download', default='voice,round_video,video,photo', help='Comma-separated media kinds; empty to skip')
    parser.add_argument('--delay', type=float, default=1.2)
    parser.add_argument('--max-pages', type=int, default=1000)
    args = parser.parse_args()
    channel = args.channel.removeprefix('@').removeprefix('https://t.me/').strip('/')
    if not re.fullmatch(r'[A-Za-z0-9_]{4,32}', channel):
        parser.error('Use a public channel username')
    if args.delay < 0.5:
        parser.error('Use a delay of at least 0.5 seconds')
    manifest, rows = collect(channel, args.output.resolve(), args.delay, args.max_pages)
    kinds = {k for k in args.download.split(',') if k}
    if kinds:
        result = download(args.output.resolve(), rows, kinds)
        manifest['downloads'] = {k: sum(1 for r in result.values() if r['kind'] == k and r['status'] == 'downloaded') for k in kinds}
        save(args.output.resolve() / 'manifest.json', manifest)
    print(json.dumps({k: v for k, v in manifest.items() if k != 'channel_info'}, ensure_ascii=False))
