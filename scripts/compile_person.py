#!/usr/bin/env python3
"""Join collector metadata, machine analyses and transcripts into one person-level corpus view.

Writes PRIVATE digests (one compact record per item) and mention lists for clustering,
plus WIKI-SAFE aggregates: a sanitized source inventory, coverage counts and chart series.
Aggregates count items in this archive; they are not real-life frequencies.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from datetime import datetime, timezone
from pathlib import Path

PLATFORM_LABEL = {'instagram': 'Instagram', 'instagram_highlight': 'Instagram Highlight', 'instagram_story': 'Instagram story',
                  'telegram': 'Telegram', 'youtube': 'YouTube'}
EMOJI = re.compile('[\U0001F300-\U0001FAFF☀-➿⭐✅‼⁉⤴⤵〰〽㊗㊙]')
# CTA code words: a capitalised word after a Russian or Ukrainian "write / comment / code word" trigger (optionally via
# "me" / "in DM"), or right before "в/у директ". Triggers ignore case; the code word itself must be in capitals («пиши СЕКРЕТ»).
CODE = r'([A-ZА-ЯЁІЇЄ0-9][A-ZА-ЯЁІЇЄ0-9+$€#]{2,})'
CTA_WORD = re.compile(r'(?i:пиши|напиши|пишите|напишите|пишіть|напишіть|написать|написати|комментари[йия]|в комментариях|коментар[іяю]?|'
                      r'у коментарях|кодовое слово|кодове слово|за словом|слово)\s*[:\-–—]?\s*(?:(?i:мне|мені|в директ|в дірект|у директ|у дірект)\s*)?'
                      r'[«"“]?' + CODE + r'|(?<![\w@])' + CODE + r'(?=\s+(?i:в|у)\s+(?i:директ|дірект))')


def cta_keywords(text):
    return sorted({(a or b).upper() for a, b in CTA_WORD.findall(text or '')})


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text().split('\n') if line.strip()] if path.exists() else []


def first_line(text, limit=140):
    line = next((x.strip() for x in (text or '').splitlines() if x.strip()), '')
    return line[:limit] + ('…' if len(line) > limit else '')


def month(value):
    return value[:7] if value else None


def analysis_for(root, item_id):
    path = root / (item_id.replace(':', '/') + '.json')
    if path.exists():
        record = json.loads(path.read_text())
        if record.get('status') == 'ok':
            return record
    return None


def transcripts_for(root, item_id):
    base = root / item_id.replace(':', '/')
    rows = []
    for path in sorted(base.parent.glob(base.name + '-[0-9][0-9].json')):
        t = json.loads(path.read_text())
        if t.get('status') == 'transcribed':
            rows.append(t)
    return rows


def collect_items(args):
    items = []
    ig = json.loads((args.instagram / 'manifest.json').read_text())
    for p in ig['posts']:
        items.append({'id': 'ig:' + p['shortcode'], 'platform': 'instagram', 'url': p['url'], 'published_at': p.get('published_at'),
                      'date_basis': p.get('date_basis'), 'kind': 'reel' if p.get('product_type') == 'clips' else p.get('type'),
                      'status': p['status'], 'text': p.get('caption') or '', 'owner': p.get('owner'), 'coauthors': p.get('coauthors'),
                      'usertags': p.get('usertags'), 'music': p.get('music'), 'location': (p.get('location') or {}).get('name'),
                      'paid_partnership': p.get('paid_partnership'), 'pinned': p.get('pinned'),
                      'media': [{k: a.get(k) for k in ['index', 'kind', 'duration', 'sha256', 'bytes', 'status', 'path', 'poster', 'width', 'height']} for a in p['assets']],
                      'snapshot_metrics': p.get('snapshot_metrics')})
    for folder, platform in [(args.highlights, 'instagram_highlight'), (args.stories, 'instagram_story')]:
        if not folder or not (folder / 'manifest.json').exists():
            continue
        for c in json.loads((folder / 'manifest.json').read_text())['collections']:
            for s in c['items']:
                taken = datetime.fromtimestamp(s['taken_at'], timezone.utc).isoformat() if s.get('taken_at') else None
                items.append({'id': ('igh:' if platform == 'instagram_highlight' else 'igs:') + s['story_id'], 'platform': platform,
                              'url': s['source_url'], 'published_at': taken, 'date_basis': 'Instagram story taken_at (UTC)' if taken else None,
                              'kind': 'story_' + s['kind'], 'status': 'downloaded' if any(a.get('status') == 'downloaded' for a in s.get('assets', [])) else 'metadata_only',
                              'text': '', 'collection': c.get('title'), 'collection_id': c['highlight_id'], 'position': s['index'] + 1,
                              'media': [{k: a.get(k) for k in ['kind', 'sha256', 'bytes', 'status', 'path']} for a in s.get('assets', [])]})
    tg = load_jsonl(args.telegram / 'messages.jsonl')
    for r in tg:
        kinds = sorted({m['kind'] for m in r['media']})
        items.append({'id': f"tg:{r['id']}", 'platform': 'telegram', 'url': r['source_url'], 'published_at': r['published_at'],
                      'date_basis': 'Telegram message date (UTC)', 'kind': '+'.join(kinds) if kinds else 'text', 'status': 'collected',
                      'text': r['text'] or '', 'forward': r.get('forward'), 'links': r.get('links'), 'views_text': r.get('views_text'),
                      'poll': r.get('poll'), 'link_preview': r.get('link_preview'), 'media': r['media']})
    for r in load_jsonl(args.youtube / 'videos.jsonl'):
        items.append({'id': 'yt:' + r['id'], 'platform': 'youtube', 'url': r.get('url') or f"https://www.youtube.com/watch?v={r['id']}",
                      'published_at': r.get('published_date'), 'date_basis': r.get('date_basis'),
                      'kind': 'youtube_short' if r.get('tab') == 'shorts' else 'youtube_video', 'status': r.get('status'),
                      'title': r.get('title'), 'text': r.get('description') or '', 'duration_s': r.get('duration_s'),
                      'view_count_snapshot': r.get('view_count_snapshot'), 'media': []})
    return items


def digest(item, record, transcripts):
    a = (record or {}).get('analysis') or {}
    visual, audio, narrative = a.get('visual') or {}, a.get('audio') or {}, a.get('narrative') or {}
    words = sum(len(t.get('words') or []) for t in transcripts)
    langs = sorted({t.get('language') for t in transcripts if t.get('language')})
    text = item.get('text') or ''
    return {'id': item['id'], 'platform': item['platform'], 'kind': item.get('kind'), 'url': item['url'], 'published_at': item.get('published_at'),
            'title': item.get('title') or first_line(text), 'text_chars': len(text), 'hashtags': sorted(set(re.findall(r'#[\w\d_]+', text))),
            'emoji_count': len(EMOJI.findall(text)), 'cta_keywords': cta_keywords(text),
            'music': item.get('music'), 'coauthors': item.get('coauthors'), 'usertags': [t.get('username') for t in item.get('usertags') or []],
            'collection': item.get('collection'), 'analysed': bool(record), 'duration_s': (record or {}).get('duration_s') or item.get('duration_s'),
            'summary': a.get('summary'), 'format': a.get('content_format'), 'languages': a.get('languages'),
            'speakers': [{'role': s.get('role'), 'share': s.get('approx_share_pct')} for s in a.get('speakers') or []],
            'topics': a.get('topics'), 'hook': narrative.get('hook'), 'cta': narrative.get('cta'), 'structure': narrative.get('structure'),
            'persuasion': narrative.get('persuasion_devices'), 'phrases': a.get('phrases'), 'offers': a.get('offers_products'),
            'claims': a.get('claims'), 'people_named': a.get('people_named'), 'appearance': visual.get('appearance'),
            'wardrobe': visual.get('wardrobe'), 'accessories': visual.get('accessories'), 'objects': visual.get('objects_props'),
            'settings': visual.get('setting'), 'gestures': visual.get('gestures_expressions'), 'framing': visual.get('camera_framing'),
            'lighting': visual.get('lighting_palette'), 'edit': visual.get('edit'), 'on_screen_text': a.get('on_screen_text'),
            'voice': audio.get('voice_delivery'), 'music_heard': audio.get('music'), 'asr_languages': langs, 'asr_words': words,
            'reference_moments': a.get('reference_moments')}


def mentions(digests):
    out = collections.defaultdict(list)
    for d in digests:
        base = {'id': d['id'], 'date': (d['published_at'] or '')[:10] or None, 'platform': d['platform']}
        for key in ['wardrobe', 'accessories', 'objects']:
            for row in d.get(key) or []:
                if isinstance(row, dict) and row.get('item'):
                    out[key].append({**base, 'item': row.get('item'), 'details': row.get('details') or row.get('colors'),
                                     'time': row.get('time'), 'asset_index': row.get('asset_index')})
        for row in d.get('settings') or []:
            if isinstance(row, dict) and row.get('description'):
                out['settings'].append({**base, 'item': row['description'], 'time': row.get('time'), 'asset_index': row.get('asset_index')})
        for row in d.get('gestures') or []:
            if isinstance(row, dict) and row.get('description'):
                out['gestures'].append({**base, 'item': row['description'], 'time': row.get('time')})
        for t in d.get('topics') or []:
            out['topics'].append({**base, 'item': t})
        for row in d.get('phrases') or []:
            if isinstance(row, dict) and row.get('text'):
                out['phrases'].append({**base, 'item': row['text'], 'function': row.get('function'), 'time': row.get('time'), 'speaker': row.get('speaker')})
        for key in ['offers', 'claims', 'people_named']:
            for row in d.get(key) or []:
                if isinstance(row, dict):
                    out[key].append({**base, **{k: v for k, v in row.items() if v is not None}})
        if d.get('hook') and isinstance(d['hook'], dict) and d['hook'].get('text'):
            out['hooks'].append({**base, 'item': d['hook']['text'], 'technique': d['hook'].get('technique')})
        if d.get('cta') and isinstance(d['cta'], dict) and d['cta'].get('text'):
            out['ctas'].append({**base, 'item': d['cta']['text'], 'mechanism': d['cta'].get('mechanism')})
    return out


def series(rows, key, categories, names):
    counts = collections.Counter((r[0], r[1]) for r in rows)
    return [{'name': names.get(n, n), 'values': [counts.get((c, n), 0) for c in categories]} for n in key]


def charts(items, digests):
    dated = [i for i in items if i.get('published_at')]
    years = sorted({i['published_at'][:4] for i in dated})
    platform_names = {'instagram': 'Instagram feed', 'telegram': 'Telegram', 'youtube': 'YouTube', 'stories': 'Instagram stories (saved/current)'}
    rows = [(i['published_at'][:4], 'stories' if i['platform'].startswith('instagram_') else i['platform']) for i in dated]
    by_id = {d['id']: d for d in digests}
    ig = [i for i in dated if i['platform'] == 'instagram']
    fmt = [(i['published_at'][:4], i.get('kind') or 'other') for i in ig]
    fmt_names = {'reel': 'Reels', 'carousel': 'Carousels', 'image': 'Single photos', 'video': 'Feed videos (non-reel)'}
    lang_rows = []
    code = {'russian': 'ru', 'ukrainian': 'uk', 'english': 'en', 'ru': 'ru', 'uk': 'uk', 'en': 'en'}
    for d in digests:
        if not d['published_at']:
            continue
        if d['asr_languages'] and d['asr_words'] >= 20:
            lang = d['asr_languages'][0]
        else:
            # Model-detected spoken language of the item; only items where the owner speaks.
            langs = d.get('languages')
            spoken = langs.get('spoken') if isinstance(langs, dict) else langs if isinstance(langs, list) else []
            owner = any(s.get('role') == 'account_owner' for s in d.get('speakers') or [])
            if not spoken or not owner:
                continue
            lang = str(spoken[0]).lower()
        lang_rows.append((d['published_at'][:4], code.get(lang, 'other')))
    lang_names = {'ru': 'Russian', 'uk': 'Ukrainian', 'en': 'English', 'other': 'Other / mixed'}
    out = [{'id': 'cadence', 'type': 'stacked', 'title': 'Published items per year, by platform', 'category_label': 'Year',
            'subtitle': 'Everything recovered in this archive, by publication year', 'categories': years,
            'series': series(rows, ['instagram', 'stories', 'telegram', 'youtube'], years, platform_names),
            'note': 'Counts recovered items, not reach or real-life activity. Stories are only those saved to Highlights or live on the retrieval day.'},
           {'id': 'instagram-formats', 'type': 'stacked', 'title': 'Instagram feed formats per year', 'category_label': 'Year',
            'subtitle': 'Product type reported by Instagram for each recovered post', 'categories': sorted({r[0] for r in fmt}),
            'series': series(fmt, ['reel', 'carousel', 'image', 'video'], sorted({r[0] for r in fmt}), fmt_names),
            'note': 'Instagram reclassified older feed videos over time; treat the 2016–2020 split as approximate.'},
           {'id': 'spoken-language', 'type': 'stacked', 'title': 'Language of recorded speech per year', 'category_label': 'Year',
            'subtitle': 'Dominant spoken language of items where she speaks (Whisper detection where available, else the media model)', 'categories': sorted({r[0] for r in lang_rows}),
            'series': series(lang_rows, ['ru', 'uk', 'en', 'other'], sorted({r[0] for r in lang_rows}), lang_names),
            'note': 'One label per item; mixed Russian/Ukrainian speech is labelled by its dominant language. Instagram posts without media analysis are not included.'}]
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['instagram', 'highlights', 'stories', 'telegram', 'youtube', 'analysis', 'transcripts', 'private', 'wiki']:
        parser.add_argument('--' + name, type=Path, required=name not in {'stories'})
    parser.add_argument('--as-of', required=True)
    args = parser.parse_args()
    items = collect_items(args)
    digests = []
    for item in items:
        record = analysis_for(args.analysis, item['id'])
        digests.append(digest(item, record, transcripts_for(args.transcripts, item['id'])))
    args.private.mkdir(parents=True, exist_ok=True, mode=0o700)
    (args.private / 'items.jsonl').write_text(''.join(json.dumps(i, ensure_ascii=False) + '\n' for i in items))
    (args.private / 'digests.jsonl').write_text(''.join(json.dumps(d, ensure_ascii=False) + '\n' for d in digests))
    for key, rows in mentions(digests).items():
        (args.private / 'mentions').mkdir(exist_ok=True, mode=0o700)
        (args.private / 'mentions' / f'{key}.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
    inventory = [{'id': i['id'], 'platform': i['platform'], 'url': i['url'], 'published_at': i.get('published_at'), 'kind': i.get('kind'),
                  'status': i.get('status'), 'analysed': d['analysed'], 'media': [{k: m.get(k) for k in ['kind', 'sha256', 'status']} for m in i.get('media') or [] if m.get('sha256') or m.get('status')]}
                 for i, d in zip(items, digests)]
    counts = collections.Counter((i['platform'], i.get('status')) for i in items)
    coverage = {'as_of': args.as_of, 'items_by_platform': dict(collections.Counter(i['platform'] for i in items)),
                'analysed_by_platform': dict(collections.Counter(d['platform'] for d in digests if d['analysed'])),
                'status_by_platform': {f'{p}:{s}': n for (p, s), n in sorted(counts.items(), key=str)},
                'transcribed_words': sum(d['asr_words'] for d in digests),
                'analysed_media_minutes': round(sum((d['duration_s'] or 0) for d in digests if d['analysed']) / 60, 1),
                'first_publication': min((i['published_at'] for i in items if i.get('published_at')), default=None),
                'last_publication': max((i['published_at'] for i in items if i.get('published_at')), default=None),
                'account_complete': False}
    args.wiki.mkdir(parents=True, exist_ok=True)
    (args.wiki / 'source-inventory.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=0) + '\n')
    (args.wiki / 'coverage.json').write_text(json.dumps(coverage, ensure_ascii=False, indent=1) + '\n')
    (args.wiki / 'charts.json').write_text(json.dumps({'schema': 'instadna.charts/v1', 'charts': charts(items, digests)}, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps(coverage, ensure_ascii=False))


if __name__ == '__main__':
    main()
