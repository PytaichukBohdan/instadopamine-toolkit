#!/usr/bin/env python3
"""Archive statistics for a person edition, counted from metadata and analysis records (no new model calls).

Adds chart series (formats per platform and year, written language, CTA code words) to
charts.json and writes stats.json: music metadata, collaborators/co-authors, code words,
caption habits and posting hours. Every number counts items in this archive with their
publication dates; none is a measure of reach, income or real-life frequency.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

EMOJI = re.compile('[\U0001F300-\U0001FAFF☀-➿⭐✅]')


def load_jsonl(path):
    return [json.loads(l) for l in path.read_text().split('\n') if l.strip()]


def series(rows, keys, categories, names):
    counts = Counter(rows)
    return [{'name': names.get(k, k), 'values': [counts.get((c, k), 0) for c in categories]} for k in keys]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private', type=Path, required=True)
    parser.add_argument('--text-analysis', type=Path, required=True)
    parser.add_argument('--wiki', type=Path, required=True)
    parser.add_argument('--handle', help="The creator's own Instagram handle (default: the wiki folder name)")
    args = parser.parse_args()
    handle = (args.handle or args.wiki.resolve().name).lower()
    items = load_jsonl(args.private / 'items.jsonl')
    digests = {d['id']: d for d in load_jsonl(args.private / 'digests.jsonl')}
    texts = {}
    for path in sorted(args.text_analysis.glob('batch-*.json')):
        if path.name.endswith('.error.json'):
            continue
        for row in json.loads(path.read_text())['items']:
            texts[row['id']] = row
    year = lambda i: (i.get('published_at') or '')[:4]
    charts = json.loads((args.wiki / 'charts.json').read_text())
    charts['charts'] = [c for c in charts['charts'] if c['id'] in {'cadence', 'instagram-formats', 'spoken-language'}]

    tg = [i for i in items if i['platform'] == 'telegram' and year(i)]
    def tg_kind(i):
        k = set(i.get('kind', 'text').split('+'))
        return 'voice' if 'voice' in k else 'round_video' if 'round_video' in k else 'video' if 'video' in k else 'document' if 'document' in k else 'photo' if 'photo' in k else 'text'
    tg_years = sorted({year(i) for i in tg})
    charts['charts'].append({'id': 'telegram-formats', 'type': 'stacked', 'title': 'Telegram posts per year by format', 'category_label': 'Year',
                             'subtitle': 'Surviving channel messages; albums count once per message ID', 'categories': tg_years,
                             'series': series([(year(i), tg_kind(i)) for i in tg], ['text', 'photo', 'round_video', 'voice', 'video'], tg_years,
                                              {'text': 'Text only', 'photo': 'Photos', 'round_video': 'Round videos', 'voice': 'Voice notes', 'video': 'Videos'}),
                             'note': 'Documents (PDF decks, checklists, files) are counted with text posts in this chart and listed on the Telegram page.'})
    yt = [i for i in items if i['platform'] == 'youtube' and year(i)]
    yt_years = sorted({year(i) for i in yt})
    charts['charts'].append({'id': 'youtube-formats', 'type': 'grouped', 'title': 'YouTube uploads per year', 'category_label': 'Year',
                             'subtitle': 'Long videos vs Shorts, by watch-page publish date', 'categories': yt_years,
                             'series': series([(year(i), i['kind']) for i in yt], ['youtube_video', 'youtube_short'], yt_years,
                                              {'youtube_video': 'Long videos', 'youtube_short': 'Shorts'}),
                             'note': 'Shorts that repeat an Instagram reel are still counted here; the platform pages discuss cross-posting.'})
    written = [(year(i), texts[i['id']].get('language')) for i in items if i['id'] in texts and year(i) and texts[i['id']].get('own_voice', True)]
    w_years = sorted({y for y, _ in written})
    charts['charts'].append({'id': 'written-language', 'type': 'stacked', 'title': 'Language of her own captions and posts per year', 'category_label': 'Year',
                             'subtitle': 'Model-labelled language of each caption, post or video title/description', 'categories': w_years,
                             'series': series([(y, l if l in {'ru', 'uk', 'en', 'mixed'} else 'none') for y, l in written], ['ru', 'uk', 'mixed', 'en'], w_years,
                                              {'ru': 'Russian', 'uk': 'Ukrainian', 'mixed': 'Mixed', 'en': 'English'}),
                             'note': 'Forwarded and quoted posts excluded. Emoji-only captions are omitted.'})
    words = Counter()
    by_word_year = defaultdict(Counter)
    for i in items:
        for w in (digests.get(i['id']) or {}).get('cta_keywords') or []:
            words[w] += 1
            by_word_year[w][year(i)] += 1
    top_words = [w for w, _ in words.most_common(5)]
    k_years = sorted({y for w in top_words for y in by_word_year[w]})
    if top_words:
        charts['charts'].append({'id': 'code-words', 'type': 'stacked', 'title': 'Comment code words in captions and posts', 'category_label': 'Year',
                                 'subtitle': 'Capitalised words after "пиши / напиши / кодовое слово", five most frequent', 'categories': k_years,
                                 'series': [{'name': w, 'values': [by_word_year[w].get(y, 0) for y in k_years]} for w in top_words],
                                 'note': 'Counts posts that ask for a code word, not responses or conversions.'})
    voice = args.wiki / 'voice-metrics.json'
    if voice.exists():
        groups = json.loads(voice.read_text())['groups']
        v_years = sorted(k.split(':', 1)[1] for k, g in groups.items() if k.startswith('year:') and g.get('timed_recordings', 0) >= 5)
        if v_years:
            charts['charts'].append({'id': 'voice-tempo', 'type': 'line', 'title': 'Speaking tempo in her own recordings', 'category_label': 'Year',
                                     'subtitle': 'Median words per minute of voiced time, owner-only recordings with word timestamps',
                                     'categories': v_years, 'unit_suffix': '',
                                     'series': [{'name': 'Words per minute', 'values': [groups[f'year:{y}']['words_per_minute_voiced'] for y in v_years]}],
                                     'note': 'Machine measurement; years with fewer than five timed recordings are omitted. Mostly Telegram voice notes and round videos.'})
    (args.wiki / 'charts.json').write_text(json.dumps(charts, ensure_ascii=False, indent=1) + '\n')

    ig = [i for i in items if i['platform'] == 'instagram' and year(i)]
    music = [i for i in ig if (i.get('music') or {}).get('type')]
    tracks = Counter((m['music'].get('title'), m['music'].get('artist')) for m in music if m['music'].get('type') == 'licensed_music')
    track_dates = defaultdict(list)
    for i in music:
        if i['music'].get('type') == 'licensed_music':
            track_dates[(i['music'].get('title'), i['music'].get('artist'))].append(i['published_at'][:10])
    original = Counter(year(i) for i in music if i['music'].get('type') != 'licensed_music')
    licensed = Counter(year(i) for i in music if i['music'].get('type') == 'licensed_music')
    collab = defaultdict(lambda: {'coauthor': 0, 'tagged': 0, 'dates': []})
    for i in ig:
        for name in i.get('coauthors') or []:
            if name != handle:
                collab[name]['coauthor'] += 1
                collab[name]['dates'].append(i['published_at'][:10])
        if i.get('owner') and i['owner'] != handle:
            collab[i['owner']]['coauthor'] += 1
            collab[i['owner']]['dates'].append(i['published_at'][:10])
        for t in i.get('usertags') or []:
            if t.get('username') and t['username'] != handle:
                collab[t['username']]['tagged'] += 1
                collab[t['username']]['dates'].append(i['published_at'][:10])
    captions = defaultdict(list)
    for i in ig + tg:
        if i.get('text'):
            captions[(i['platform'], year(i))].append(i['text'])
    hours = Counter()
    for i in ig:
        hours[datetime.fromisoformat(i['published_at']).hour] += 1
    functions = defaultdict(Counter)
    for i in items:
        t = texts.get(i['id'])
        if t and t.get('own_voice', True):
            functions[i['platform']][t.get('function') or 'other'] += 1
    stats = {
        'note': 'Counts of items in this archive by publication date. Not reach, income or real-life frequency.',
        'instagram_music': {'with_metadata': len(music), 'licensed_by_year': dict(sorted(licensed.items())), 'original_audio_by_year': dict(sorted(original.items())),
                            'top_licensed': [{'title': t, 'artist': a, 'posts': n, 'first': min(track_dates[(t, a)]), 'last': max(track_dates[(t, a)])}
                                             for (t, a), n in tracks.most_common(40)]},
        'collaborators': sorted([{'account': k, 'coauthor_posts': v['coauthor'], 'tagged_posts': v['tagged'], 'first': min(v['dates']), 'last': max(v['dates'])}
                                 for k, v in collab.items()], key=lambda r: -(r['coauthor_posts'] * 3 + r['tagged_posts']))[:80],
        'code_words': [{'word': w, 'posts': n, 'by_year': dict(sorted(by_word_year[w].items()))} for w, n in words.most_common(30)],
        'caption_habits': {f'{p}:{y}': {'posts': len(v), 'median_chars': int(statistics.median(len(t) for t in v)),
                                        'emoji_per_post': round(sum(len(EMOJI.findall(t)) for t in v) / len(v), 1)}
                           for (p, y), v in sorted(captions.items())},
        'instagram_posting_hour_utc': dict(sorted(hours.items())),
        'post_functions': {p: dict(c.most_common()) for p, c in functions.items()},
    }
    (args.wiki / 'stats.json').write_text(json.dumps(stats, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps({'charts': [c['id'] for c in charts['charts']], 'tracks': len(tracks), 'collaborators': len(collab), 'code_words': top_words}, ensure_ascii=False))


if __name__ == '__main__':
    main()
