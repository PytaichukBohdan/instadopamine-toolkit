#!/usr/bin/env python3
"""Export every collected item into a browsable data room for the PROTECTED report only.

Reads the private corpus view written by compile_person.py plus machine analyses and
transcripts. Writes JSON shards and small WebP thumbnails into a private directory
that `instadna edition --data-room` attaches to the prepared site. Nothing here is
committed: it contains full captions, posts and automatic transcripts.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from instadna.media_analysis import timed_transcript  # noqa: E402

LABEL = {'instagram': 'Instagram', 'instagram_highlight': 'Instagram Highlight', 'instagram_story': 'Instagram story',
         'telegram': 'Telegram', 'youtube': 'YouTube'}
SHARD = 150


def clock(seconds):
    seconds = int(seconds or 0)
    return f'{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}' if seconds >= 3600 else f'{seconds // 60:02d}:{seconds % 60:02d}'


def thumb(source, target, size=(360, 450)):
    if target.exists():
        return True
    try:
        if source.suffix.lower() in {'.mp4', '.mov'}:
            frame = target.with_suffix('.jpg')
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', '1', '-i', str(source), '-frames:v', '1', '-vf', 'scale=480:-2', str(frame)],
                           check=True, capture_output=True)
            source = frame
        with Image.open(source) as img:
            img = ImageOps.fit(ImageOps.exif_transpose(img).convert('RGB'), size, Image.LANCZOS)
            img.save(target, 'WEBP', quality=72, method=5)
        if source.suffix == '.jpg' and source.parent == target.parent:
            source.unlink(missing_ok=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def media_sources(item, roots):
    """Local image/video files that can stand for the item, in display order."""
    out = []
    if item['platform'] == 'instagram':
        for m in item.get('media') or []:
            if m.get('status') != 'downloaded':
                continue
            path = roots['instagram'] / (m.get('poster') or m['path'])
            out.append(path)
    elif item['platform'] in {'instagram_highlight', 'instagram_story'}:
        root = roots['highlights' if item['platform'] == 'instagram_highlight' else 'stories']
        images = [m for m in item.get('media') or [] if m.get('status') == 'downloaded' and m.get('kind') == 'image']
        videos = [m for m in item.get('media') or [] if m.get('status') == 'downloaded' and m.get('kind') == 'video']
        out += [root / m['path'] for m in images or videos]
    elif item['platform'] == 'telegram':
        downloads = roots['telegram_downloads']
        for i, m in enumerate(item.get('media') or []):
            d = downloads.get(f"{item['id'][3:]}-{i}")
            if d and d.get('status') == 'downloaded' and d['kind'] in {'photo', 'round_video', 'video'}:
                out.append(roots['telegram'] / d['path'])
    elif item['platform'] == 'youtube':
        entry = roots['youtube_thumbs'].get(item['id'][3:], {})
        out += [roots['youtube'] / entry[k]['path'] for k in ['cover', 'auto1', 'auto2', 'auto3'] if k in entry]
    return out


def transcript(item_id, record, transcripts):
    base = transcripts / item_id.replace(':', '/')
    rows, source = [], None
    for path in sorted(base.parent.glob(base.name + '-[0-9][0-9].json')):
        t = json.loads(path.read_text())
        if t.get('status') == 'transcribed' and t.get('segments'):
            rows += [[clock(s['start']), s['text'].strip()] for s in t['segments'] if s.get('text', '').strip()]
            source = t.get('model')
    if not rows and record:
        segments, rescaled = timed_transcript(record)
        rows = [[clock(s.get('start')), (f"{s['speaker']}: " if s.get('speaker') else '') + (s.get('text') or '')]
                for s in segments if s.get('text')]
        source = (record.get('provenance') or {}).get('model', 'gemini') + ' (machine transcript in the item analysis)'
        if rescaled:
            source += '; times in ' + ', '.join(f'{clock(a)}–{clock(b)}' for a, b, _ in rescaled) + ' rescaled to the true length'
    return rows, source


def facts(item, d):
    # Model outputs are not perfectly uniform: accept dicts, lists or plain strings.
    def join(rows, key='item', limit=6):
        rows = rows if isinstance(rows, list) else []
        return '; '.join(str(r.get(key)) for r in rows[:limit] if isinstance(r, dict) and r.get(key)) or None
    def text_of(value):
        return value.get('text') if isinstance(value, dict) else value if isinstance(value, str) else None
    langs = d.get('languages')
    spoken = langs.get('spoken') if isinstance(langs, dict) else langs if isinstance(langs, list) else []
    m = item.get('music') or {}
    heard = d.get('music_heard')
    out = [('Format', d.get('format')), ('Languages', ', '.join(str(x) for x in spoken or []) or None),
           ('Topics', ', '.join(str(t) for t in d.get('topics') or []) or None),
           ('Hook', text_of(d.get('hook'))), ('Call to action', text_of(d.get('cta'))),
           ('Music (Instagram metadata)', ' — '.join(x for x in [m.get('title'), m.get('artist')] if x) or None),
           ('Music heard', heard.get('description') if isinstance(heard, dict) else None),
           ('Wardrobe', join(d.get('wardrobe'))), ('Accessories', join(d.get('accessories'))), ('Objects', join(d.get('objects'))),
           ('Setting', join(d.get('settings'), 'description', 3)),
           ('Collaborators / tags', ', '.join(sorted(set((item.get('coauthors') or []) + [t.get('username') for t in item.get('usertags') or [] if t.get('username')]))) or None),
           ('People named', join(d.get('people_named'), 'name_or_handle')), ('Offers & products', join(d.get('offers'), 'name')),
           ('Self-reported claims (dated)', join(d.get('claims'), 'claim', 4)), ('Highlight', item.get('collection')),
           ('Forwarded from', (item.get('forward') or {}).get('from') if item.get('forward') else None),
           ('Links', ', '.join(item.get('links') or []) or None)]
    metrics = item.get('snapshot_metrics') or {}
    if metrics.get('like_count') is not None:
        out.append(('Likes / comments as Instagram returned them (snapshot; may be hidden or partial; not DNA)',
                    f"{metrics.get('like_count')} / {metrics.get('comment_count')} as of {(metrics.get('as_of') or '')[:10]}"))
    if item.get('view_count_snapshot') is not None:
        out.append(('Views (snapshot, not DNA)', str(item['view_count_snapshot'])))
    return [[k, str(v)] for k, v in out if v]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['private', 'analysis', 'transcripts', 'instagram', 'highlights', 'stories', 'telegram', 'youtube', 'out']:
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    items = [json.loads(l) for l in (args.private / 'items.jsonl').read_text().split('\n') if l.strip()]
    digests = {d['id']: d for d in map(json.loads, filter(str.strip, (args.private / 'digests.jsonl').read_text().split('\n')))}
    roots = {'instagram': args.instagram, 'highlights': args.highlights, 'stories': args.stories, 'telegram': args.telegram, 'youtube': args.youtube,
             'telegram_downloads': json.loads((args.telegram / 'downloads.json').read_text()),
             'youtube_thumbs': json.loads((args.youtube / 'thumbnails.json').read_text()) if (args.youtube / 'thumbnails.json').exists() else {}}
    out = args.out.resolve()
    (out / 'thumbs').mkdir(parents=True, exist_ok=True, mode=0o700)
    (out / 'items').mkdir(exist_ok=True, mode=0o700)
    index, shards = [], defaultdict(dict)
    jobs = []
    counters = defaultdict(int)
    for item in sorted(items, key=lambda i: i.get('published_at') or '', reverse=True):
        d = digests[item['id']]
        record_path = args.analysis / (item['id'].replace(':', '/') + '.json')
        record = json.loads(record_path.read_text()) if record_path.exists() else None
        safe = item['id'].replace(':', '-')
        sources = media_sources(item, roots)[:6]
        thumbs = [f'thumbs/{safe}-{k}.webp' for k in range(len(sources))]
        jobs += list(zip(sources, [out / t for t in thumbs]))
        shard = f"items/{item['platform']}-{counters[item['platform']] // SHARD:03d}.json"
        counters[item['platform']] += 1
        rows, source = transcript(item['id'], record, args.transcripts)
        text = (item.get('title') + '\n\n' if item.get('title') else '') + (item.get('text') or '')
        shards[shard][item['id']] = {'text': text.strip(), 'summary': d.get('summary'), 'facts': facts(item, d),
                                     'transcript': rows, 'transcript_source': source, 'thumbs': thumbs[1:]}
        spoken = ' '.join(r[1] for r in rows or [])[:240]
        search = ' '.join(x for x in [item['id'], item.get('title'), (item.get('text') or '')[:360], (d.get('summary') or '')[:160], spoken] if x).lower()
        index.append({'id': item['id'], 'platform': item['platform'], 'platform_label': LABEL[item['platform']], 'kind': item.get('kind') or 'item',
                      'url': item['url'], 'published_at': item.get('published_at'), 'date_basis': item.get('date_basis'),
                      'duration_s': d.get('duration_s'), 'title': (item.get('title') or d.get('title') or '')[:160],
                      'snippet': (d.get('summary') or '')[:160], 'thumb': thumbs[0] if thumbs else None, 'shard': shard,
                      'search': search[:900]})
    with ThreadPoolExecutor(max_workers=6) as pool:
        made = list(pool.map(lambda job: thumb(*job), jobs))
    missing = {str(t.relative_to(out)) for (s, t), ok in zip(jobs, made) if not ok}
    for row in index:
        if row['thumb'] in missing:
            row['thumb'] = None
    for shard, rows in shards.items():
        for value in rows.values():
            value['thumbs'] = [t for t in value['thumbs'] if t not in missing]
        (out / shard).write_text(json.dumps(rows, ensure_ascii=False))
    (out / 'index.json').write_text(json.dumps({'schema': 'instadna.dataroom/v1', 'items': index}, ensure_ascii=False))
    print(json.dumps({'items': len(index), 'thumbnails': sum(made), 'missing_thumbnails': len(missing), 'shards': len(shards)}))


if __name__ == '__main__':
    main()
