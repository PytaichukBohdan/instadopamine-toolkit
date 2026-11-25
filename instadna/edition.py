"""Multi-platform person edition: one protected, allowlisted static report per person.

The edition is driven by small reviewed manifests inside a person's wiki folder:
`edition.json` (navigation, labels, headline numbers), `atlas.json` (selected source
screenshots), `generated-images.json` (AI reconstructions, validated by
`generated_images`), `passport.json` (separate reusable items), `phrases.json`
(original speech excerpts and written phrases), `charts.json` (aggregate series) and
`storyboard.json` (AI start frames for a video, timed to a disclosed synthetic voice).
Recency and recurrence badges are computed here from dated evidence, so a manifest
cannot assert counts it does not support. A private data room produced from the
corpus may be attached at build time; it never lives in the repository.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import re
import shutil
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

from PIL import Image

from .audio_assets import load_audio
from .video_assets import load_video, files as video_files
from .generated_images import load_generated_images
from .site import safe_markdown

WEB = Path(__file__).parent / 'web'
SOURCE_URL = {
    'instagram': r'https://www\.instagram\.com/p/[A-Za-z0-9_-]+/',
    'instagram_highlight': r'https://www\.instagram\.com/stories/highlights/[0-9]+/\?story_media_id=[0-9]+',
    'instagram_story': r'https://www\.instagram\.com/stories/[a-z0-9_.]+/[0-9]+/',
    'telegram': r'https://t\.me/[A-Za-z0-9_]{4,32}/[0-9]+',
    'youtube': r'https://www\.youtube\.com/watch\?v=[A-Za-z0-9_-]{11}',
}
SOURCE_ID = {'instagram': 'ig:', 'instagram_highlight': 'igh:', 'instagram_story': 'igs:', 'telegram': 'tg:', 'youtube': 'yt:'}
PLATFORM_LABEL = {'instagram': 'Instagram', 'instagram_highlight': 'Instagram Highlight', 'instagram_story': 'Instagram story',
                  'telegram': 'Telegram', 'youtube': 'YouTube'}
RECENCY = {'recent': 'Recent · within 180 days', 'older': 'Older · 181–730 days',
           'historical': 'Historical · over 730 days', 'unknown': 'Date unknown'}
RECURRENCE = {'across_occasions': 'Across documented occasions', 'one_occasion': 'One documented occasion',
              'not_established': 'Independent occasions not established'}
ID = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')
esc = html.escape


# ---------- time ----------

def parse_time(value):
    if value is None:
        return None
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return datetime.fromisoformat(value + 'T00:00:00+00:00')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.utcoffset() is None:
        raise ValueError('Evidence time needs a timezone or a plain date')
    return parsed


def summarize_time(observations, as_of):
    """Recency of the latest dated source, separate from documented-occasion recurrence."""
    cutoff = date.fromisoformat(as_of)
    sources, days, occasions, undated, ungrouped = {}, set(), set(), set(), set()
    for row in observations:
        source = row.get('source_id')
        if not isinstance(source, str) or not source:
            raise ValueError('Temporal evidence needs a source ID')
        moment = parse_time(row.get('published_at'))
        day = moment.astimezone(timezone.utc).date() if moment else None
        if day and day > cutoff:
            raise ValueError('Evidence cannot postdate the analysis')
        if day:
            days.add(day)
        else:
            undated.add(source)
        occasion = row.get('occasion_id')
        if occasion:
            if not row.get('occasion_basis'):
                raise ValueError('An occasion grouping needs an evidence basis')
            occasions.add(occasion)
        else:
            ungrouped.add(source)
        identity = (day, occasion)
        if source in sources and sources[source] != identity:
            raise ValueError('Duplicate source has conflicting temporal metadata')
        sources[source] = identity
    last = max(days) if days else None
    age = (cutoff - last).days if last else None
    recency = 'unknown' if age is None else 'recent' if age <= 180 else 'older' if age <= 730 else 'historical'
    recurrence = 'across_occasions' if len(occasions) >= 2 else 'one_occasion' if occasions and not ungrouped else 'not_established'
    return {'as_of': as_of, 'first_observed': min(days).isoformat() if days else None, 'last_observed': last.isoformat() if last else None,
            'age_days': age, 'recency': recency, 'distinct_sources': len(sources), 'distinct_publication_days': len(days),
            'known_occasions': len(occasions), 'ungrouped_sources': len(ungrouped), 'undated_sources': len(undated),
            'recurrence': recurrence}


def render_time(s):
    span = f"{s['first_observed']} → {s['last_observed']}" if s['first_observed'] else 'Unknown'
    undated = f" · {s['undated_sources']} undated" if s['undated_sources'] else ''
    return (f'<div class="temporal"><span class="badge badge-{s["recency"]}">{esc(RECENCY[s["recency"]])}</span>'
            f'<span class="badge">{esc(RECURRENCE[s["recurrence"]])}</span>'
            f'<p>Published {esc(span)}{undated} · {s["distinct_sources"]} source(s) · {s["distinct_publication_days"]} day(s) · '
            f'{s["known_occasions"]} documented occasion(s). Assessed {s["as_of"]}.</p>'
            '<small>Publication dates in this archive — not filming dates, real-life frequency or proof of a current habit.</small></div>')


# ---------- shared validation ----------

def _inside(wiki, name, pattern, digest=None, max_bytes=25 * 1024 * 1024):
    if not re.fullmatch(pattern, name or ''):
        raise ValueError(f'File is not on the allowlist pattern: {name}')
    path = wiki / name
    if path.is_symlink() or not path.resolve().is_relative_to(wiki.resolve()) or not path.is_file():
        raise ValueError(f'File is missing, a symlink or escapes the wiki: {name}')
    if path.stat().st_size >= max_bytes:
        raise ValueError(f'File exceeds the Pages asset limit: {name}')
    if digest is not None and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError(f'Hash mismatch: {name}')
    return path


def check_source(row, prefix=''):
    platform = row.get('platform')
    if platform not in SOURCE_URL:
        raise ValueError(f'{prefix}unknown platform {platform}')
    if not re.fullmatch(SOURCE_URL[platform], row.get('source_url') or row.get('url') or ''):
        raise ValueError(f'{prefix}source URL does not match its platform')
    source_id = row.get('source_id') or row.get('id')
    if not isinstance(source_id, str) or not source_id.startswith(SOURCE_ID[platform]):
        raise ValueError(f'{prefix}source ID does not match its platform')
    parse_time(row.get('published_at'))
    if row.get('published_at') and not row.get('date_basis'):
        raise ValueError(f'{prefix}dated evidence needs a date basis')


# ---------- atlas: original screenshots ----------

def load_atlas(wiki):
    path = wiki / 'atlas.json'
    if not path.exists():
        return {'references': []}
    data = json.loads(path.read_text())
    if data.get('schema') != 'instadna.atlas/v1':
        raise ValueError('Unsupported atlas manifest')
    seen = set()
    for row in data['references']:
        if not re.fullmatch(r'A[0-9]{3,4}', row['id']) or row['id'] in seen:
            raise ValueError('Invalid or duplicate atlas ID')
        seen.add(row['id'])
        check_source(row, f"{row['id']}: ")
        t = row.get('time_seconds')
        if row['kind'] == 'video_frame':
            if type(t) not in (int, float) or not math.isfinite(t) or t < 0:
                raise ValueError(f"{row['id']}: video frame needs a timestamp")
        elif row['kind'] != 'image' or t is not None:
            raise ValueError(f"{row['id']}: still image must not have a timestamp")
        if type(row.get('asset_index')) is not int or row['asset_index'] < 0:
            raise ValueError(f"{row['id']}: invalid asset index")
        for field in ['title', 'category', 'description', 'use', 'limit']:
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f"{row['id']}: missing {field}")
        image = _inside(wiki, row['image'], r'references/[A-Za-z0-9_.-]+\.webp', row['sha256'])
        _inside(wiki, row['thumbnail'], r'references/[A-Za-z0-9_.-]+\.webp', row['thumbnail_sha256'])
        with Image.open(image) as img:
            if img.size != (row['width'], row['height']):
                raise ValueError(f"{row['id']}: dimensions do not match")
        if not re.fullmatch(r'[a-f0-9]{64}', row.get('source_media_sha256', '')):
            raise ValueError(f"{row['id']}: needs the hash of the private source media")
    return data


def _locator(row):
    where = f"asset {row['asset_index']}"
    return where + (f" · {row['time_seconds']:.1f}s" if row['time_seconds'] is not None else ' · still')


def render_atlas(data):
    refs = data['references']
    categories = list(dict.fromkeys(r['category'] for r in refs))
    buttons = '<button type="button" data-filter="all" aria-pressed="true">All</button>' + ''.join(
        f'<button type="button" data-filter="{esc(c)}" aria-pressed="false">{esc(c.capitalize())}</button>' for c in categories)
    cards = []
    for r in refs:
        day = parse_time(r.get('published_at'))
        cards.append(f'''<figure class="ref-card" id="{r['id']}" data-category="{esc(r['category'])}">
<a class="ref-image" href="{esc(r['image'])}"><img src="{esc(r['thumbnail'])}" alt="{esc(r['title'])}" loading="lazy" width="{r['width']}" height="{r['height']}"></a>
<figcaption><span class="eyebrow">{r['id']} · {esc(r['category'])} · {esc(PLATFORM_LABEL[r['platform']])}</span><h3>{esc(r['title'])}</h3>
<p>{esc(r['description'])}</p><p><strong>Use:</strong> {esc(r['use'])}</p><p class="muted">{esc(r['limit'])}</p>
<p class="meta">Published {esc(day.date().isoformat() if day else 'date unknown')} · {esc(_locator(r))}<br>
<a href="{esc(r['source_url'])}" rel="noreferrer">Original post ↗</a> · <a href="{esc(r['image'])}" download>Download frame</a></p></figcaption></figure>''')
    return (f'<div class="filters" data-target="ref-card" role="group" aria-label="Filter screenshots">{buttons}</div>'
            f'<p class="count" aria-live="polite">{len(refs)} source screenshots</p><div class="ref-grid">{"".join(cards)}</div>')


# ---------- passport: separate reusable items ----------

def load_passport(wiki, atlas, generated):
    path = wiki / 'passport.json'
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if data.get('schema') != 'instadna.passport/v1':
        raise ValueError('Unsupported passport manifest')
    refs = {r['id']: r for r in atlas['references']}
    synthetic = {r['path']: r for r in generated}
    seen = set()
    for item in data['items']:
        if not ID.fullmatch(item['id']) or item['id'] in seen:
            raise ValueError('Invalid or duplicate passport item ID')
        seen.add(item['id'])
        for field in ['title', 'category', 'description', 'context', 'usage_brief', 'limit', 'recurrence_note']:
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f"{item['id']}: missing {field}")
        if item['image_kind'] == 'ai_reconstruction':
            if item['image'] not in synthetic or item.get('thumbnail') != synthetic[item['image']].get('thumbnail'):
                raise ValueError(f"{item['id']}: reconstruction must be a validated generated image")
        elif item['image_kind'] == 'source_reference':
            if item['image'] not in {refs[a]['image'] for a in item.get('atlas_ids', []) if a in refs}:
                raise ValueError(f"{item['id']}: source image must come from its own atlas evidence")
        else:
            raise ValueError(f"{item['id']}: unknown image kind")
        if not item['evidence']:
            raise ValueError(f"{item['id']}: needs dated evidence")
        for ev in item['evidence']:
            check_source(ev, f"{item['id']}: ")
            if not ev.get('locator'):
                raise ValueError(f"{item['id']}: evidence needs a locator")
            if ev.get('atlas_id') and ev['atlas_id'] not in refs:
                raise ValueError(f"{item['id']}: unknown atlas reference")
        item['temporal'] = summarize_time(item['evidence'], data['as_of'])
    return data


def render_passport(data, generated):
    items = data['items']
    synthetic = {r['path']: r for r in generated}
    categories = list(dict.fromkeys(i['category'] for i in items))
    buttons = '<button type="button" data-filter="all" aria-pressed="true">All items</button>' + ''.join(
        f'<button type="button" data-filter="{esc(c)}" aria-pressed="false">{esc(c.capitalize())}</button>' for c in categories)
    cards = []
    for i in items:
        ai = i['image_kind'] == 'ai_reconstruction'
        model = synthetic[i['image']]['model'] if ai else None
        evidence = ''.join(
            f'<li><a href="{esc(e["source_url"])}" rel="noreferrer">{esc(PLATFORM_LABEL[e["platform"]])} · {esc(e["source_id"])}</a> · '
            f'{esc((parse_time(e.get("published_at")) or datetime.min).date().isoformat() if e.get("published_at") else "date unknown")} · {esc(e["locator"])}'
            + (f' · <a href="visual-atlas.html#{esc(e["atlas_id"])}">{esc(e["atlas_id"])}</a>' if e.get('atlas_id') else '') + '</li>'
            for e in i['evidence'])
        cards.append(f'''<article class="item" id="{esc(i['id'])}" data-category="{esc(i['category'])}" data-recency="{i['temporal']['recency']}">
<a class="item-image" href="{esc(i['image'])}"><img src="{esc(i.get('thumbnail') or i['image'])}" alt="{esc(i['title'])}" loading="lazy" width="640" height="640"></a>
<div class="item-copy"><span class="eyebrow">{esc(i['category'])} · {'AI reconstruction · ' + esc(model) if ai else 'Original source frame'}</span>
<h3><a href="#{esc(i['id'])}">{esc(i['title'])}</a></h3><p>{esc(i['description'])}</p>
<p class="context"><strong>Where to use it</strong>{esc(i['context'])}</p>{render_time(i['temporal'])}
<details><summary>Scene brief</summary><p class="brief">{esc(i['usage_brief'])}</p><button type="button" class="copy">Copy brief</button></details>
<details><summary>Evidence & limits</summary><p>{esc(i['recurrence_note'])}</p><ul>{evidence}</ul><p class="muted">{esc(i['limit'])}</p></details>
<p class="actions"><a href="{esc(i['image'])}" download>Download image ↗</a></p></div></article>''')
    return (f'<div class="toolbar"><label for="item-search">Find an item</label><input id="item-search" type="search" placeholder="Object, place, phrase…" data-search="item">'
            f'<label for="item-recency">Latest evidence</label><select id="item-recency" data-recency="item"><option value="all">All dates</option>'
            + ''.join(f'<option value="{k}">{esc(v)}</option>' for k, v in RECENCY.items()) +
            f'</select><div class="filters" data-target="item" role="group" aria-label="Filter items">{buttons}</div></div>'
            f'<p class="count" aria-live="polite">{len(items)} separate items</p><div class="items">{"".join(cards)}</div><p class="copy-status" role="status" aria-live="polite"></p>')


# ---------- phrases: original speech and written lines ----------

def load_phrases(wiki, public=False):
    path = wiki / 'phrases.json'
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if data.get('schema') != 'instadna.phrases/v2' or data.get('audience') != 'private':
        raise ValueError('Phrase sources require a private v2 phrase manifest')
    if public and data['spoken']:
        raise ValueError('Original speech excerpts are private; build with authentication')
    sources = {}
    for s in data['sources']:
        check_source(s, f"{s['id']}: ")
        if s['id'] in sources:
            raise ValueError('Duplicate phrase source')
        sources[s['id']] = s
    families = {f['id']: f for f in data['families']}
    seen, files = set(), set()
    for row in data['spoken'] + data['written']:
        if not ID.fullmatch(row['id']) or row['id'] in seen:
            raise ValueError('Invalid or duplicate phrase ID')
        seen.add(row['id'])
        if row['source_id'] not in sources or row['family'] not in families:
            raise ValueError(f"{row['id']}: unknown source or family")
        for field in ['text', 'gloss', 'language', 'context']:
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f"{row['id']}: missing {field}")
    for row in data['spoken']:
        source = sources[row['source_id']]
        for field in ['delivery', 'attribution', 'review_method', 'limitations']:
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f"{row['id']}: missing {field}")
        start, end, length = row['start_s'], row['end_s'], row['duration_s']
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (start, end, length)):
            raise ValueError(f"{row['id']}: invalid time")
        if not 0 <= start < end <= source['duration_s'] + .05 or end - start > 20 or abs(length - (end - start)) > .15:
            raise ValueError(f"{row['id']}: window must fit its source and last at most 20 s")
        if not re.fullmatch(r'[a-f0-9]{64}', source.get('audio_sha256', '')):
            raise ValueError(f"{row['id']}: source audio needs a hash")
        if row['path'] in files:
            raise ValueError('Each excerpt needs its own file')
        files.add(row['path'])
        audio = _inside(wiki, row['path'], r'audio/phrase-[a-z0-9-]+\.mp3', row['sha256'])
        probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(audio)]))
        if len(probe['streams']) != 1 or probe['streams'][0]['codec_type'] != 'audio':
            raise ValueError(f"{row['id']}: excerpt must be one audio stream")
        if abs(float(probe['format']['duration']) - length) > .12:
            raise ValueError(f"{row['id']}: excerpt duration mismatch")
    for family in families.values():
        rows = [r for r in data['spoken'] + data['written'] if r['family'] == family['id']]
        if not rows:
            raise ValueError(f"Phrase family {family['id']} is empty")
        family['temporal'] = summarize_time([{**sources[r['source_id']], 'source_id': r['source_id']} for r in rows], data['as_of'])
    return data


def _normal(text):
    return re.sub(r'[^\w\s]', '', text.casefold()).split()


def render_phrases(data):
    sources = {s['id']: s for s in data['sources']}
    options = '<option value="all">All functions</option>' + ''.join(f'<option value="{esc(f["id"])}">{esc(f["title"])}</option>' for f in data['families'])
    families = ''.join(f'<details class="family"><summary>{esc(f["title"])}</summary><p>{esc(f["context"])}</p>{render_time(f["temporal"])}</details>'
                       for f in data['families'])
    cards = []
    for kind, rows in [('spoken', data['spoken']), ('written', data['written'])]:
        for r in sorted(rows, key=lambda x: sources[x['source_id']].get('published_at') or '', reverse=True):
            s = sources[r['source_id']]
            same = {x['source_id'] for x in data['spoken'] + data['written'] if _normal(x['text']) == _normal(r['text'])}
            t = summarize_time([{**sources[i], 'source_id': i} for i in same], data['as_of'])
            audio = (f'<audio controls preload="none" src="{esc(r["path"])}" aria-label="{esc(r["text"])}"></audio>'
                     f'<p class="delivery"><strong>Delivery:</strong> {esc(r["delivery"])}</p>') if kind == 'spoken' else ''
            window = f" · {r['start_s']:.2f}–{r['end_s']:.2f}s" if kind == 'spoken' else ''
            extra = (f'<p>{esc(r["attribution"])}</p><p>{esc(r["review_method"])} {esc(r["limitations"])}</p>'
                     f'<p><a href="{esc(r["path"])}" download>Download MP3 excerpt</a></p>') if kind == 'spoken' else ''
            cards.append(f'''<section class="phrase" id="{esc(r['id'])}" data-family="{esc(r['family'])}" data-kind="{kind}" data-recency="{t['recency']}">
<span class="eyebrow">{'ORIGINAL AUDIO' if kind == 'spoken' else 'SPOKEN · TRANSCRIPT ONLY' if r.get('mode') == 'transcript' else 'WRITTEN'} · {esc(r['language'])} · {esc(PLATFORM_LABEL[s['platform']])}{f" · {r['duration_s']:.1f}s" if kind == 'spoken' else ''}</span>
<h3 lang="{esc(r['language'])}"><a href="#{esc(r['id'])}">{esc(r['text'])}</a></h3><p class="gloss">{esc(r['gloss'])}</p>{audio}
<p>{esc(r['context'])}</p>{render_time(t)}
<details><summary>Source & confidence</summary><p><a href="{esc(s['url'])}" rel="noreferrer">{esc(s['id'])}</a>{window} · {esc(s.get('date_basis') or 'date unknown')}</p>
<p>Exact wording in {len(same)} distinct source(s) of this bank.</p>{extra}</details></section>''')
    return (f'<details class="families"><summary>{len(data["families"])} speaking and writing functions — history</summary>{families}</details>'
            f'<div class="toolbar"><label for="phrase-search">Find a phrase</label><input id="phrase-search" type="search" placeholder="Phrase, keyword…" data-search="phrase">'
            f'<label for="phrase-family">Function</label><select id="phrase-family" data-family="phrase">{options}</select>'
            f'<label for="phrase-kind">Evidence</label><select id="phrase-kind" data-kind="phrase"><option value="all">Spoken and written</option><option value="spoken">Original audio</option><option value="written">Written</option></select></div>'
            f'<p class="count" aria-live="polite">{len(cards)} phrases</p><div class="phrases">{"".join(cards)}</div>')


# ---------- charts: inline SVG with table fallback ----------

# Series colours come from CSS classes: the report CSP forbids inline style attributes.
SERIES = ['s1', 's2', 's3', 's4', 's5']


def _nice(top):
    if top <= 0:
        return 1
    step = 10 ** math.floor(math.log10(top))
    for m in (1, 2, 2.5, 5, 10):
        if top <= m * step:
            return m * step
    return 10 * step


def render_chart(chart):
    """Grouped/stacked columns or lines over ordered categories, plus an accessible table."""
    cats, series = chart['categories'], chart['series']
    width, height, left, bottom, top_pad = 760, 300, 48, 46, 16
    plot_w, plot_h = width - left - 12, height - bottom - top_pad
    stacked = chart['type'] == 'stacked'
    totals = [sum(s['values'][i] or 0 for s in series) for i in range(len(cats))] if stacked else [max((s['values'][i] or 0) for s in series) for i in range(len(cats))]
    top = chart.get('max') or _nice(max(totals or [1]) * 1.05)
    y = lambda v: top_pad + plot_h - plot_h * (v / top)
    band = plot_w / max(1, len(cats))
    marks, labels = [], []
    for k in range(5):
        v = top * k / 4
        marks.append(f'<line class="grid" x1="{left}" x2="{width - 12}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
                     f'<text class="tick" x="{left - 8}" y="{y(v) + 4:.1f}" text-anchor="end">{v:,.0f}{chart.get("unit_suffix", "")}</text>')
    every = max(1, math.ceil(len(cats) / 12))
    for i, c in enumerate(cats):
        if i % every == 0 or i == len(cats) - 1:
            labels.append(f'<text class="tick" x="{left + band * (i + .5):.1f}" y="{height - bottom + 18}" text-anchor="middle">{esc(str(c))}</text>')
    if chart['type'] in {'stacked', 'grouped'}:
        bar = min(24, band * (.7 if stacked else .8) / (1 if stacked else len(series)))
        for i, c in enumerate(cats):
            base = 0
            for j, s in enumerate(series):
                v = s['values'][i] or 0
                if v <= 0:
                    continue
                x = left + band * (i + .5) - (bar / 2 if stacked else bar * len(series) / 2 - bar * j)
                y0, y1 = (y(base), y(base + v)) if stacked else (y(0), y(v))
                h = max(0, y0 - y1 - (2 if stacked else 0))
                tip = f'{c} · {s["name"]}: {v:,}{chart.get("unit_suffix", "")}'
                marks.append(f'<rect x="{x:.1f}" y="{y1:.1f}" width="{bar - (0 if stacked else 2):.1f}" height="{h:.1f}" rx="2" '
                             f'class="bar {SERIES[j]}" tabindex="0" data-tip="{esc(tip)}"><title>{esc(tip)}</title></rect>')
                base += v if stacked else 0
    else:
        for j, s in enumerate(series):
            points = [(left + band * (i + .5), y(v)) for i, v in enumerate(s['values']) if v is not None]
            marks.append(f'<polyline class="line {SERIES[j]}" fill="none" points="{" ".join(f"{px:.1f},{py:.1f}" for px, py in points)}"/>')
            for i, v in enumerate(s['values']):
                if v is not None:
                    tip = f'{cats[i]} · {s["name"]}: {v:,}{chart.get("unit_suffix", "")}'
                    marks.append(f'<circle cx="{left + band * (i + .5):.1f}" cy="{y(v):.1f}" r="4" class="dot {SERIES[j]}" tabindex="0" data-tip="{esc(tip)}"><title>{esc(tip)}</title></circle>')
    marks.append(f'<line class="axis" x1="{left}" x2="{width - 12}" y1="{y(0):.1f}" y2="{y(0):.1f}"/>')
    legend = '' if len(series) == 1 else '<ul class="legend">' + ''.join(
        f'<li><span class="key {SERIES[j]}"></span>{esc(s["name"])}</li>' for j, s in enumerate(series)) + '</ul>'
    head = ''.join(f'<th scope="col">{esc(s["name"])}</th>' for s in series)
    body = ''.join(f'<tr><th scope="row">{esc(str(c))}</th>' + ''.join(f'<td>{"" if s["values"][i] is None else f"{s["values"][i]:,}"}</td>' for s in series) + '</tr>'
                   for i, c in enumerate(cats))
    return (f'<figure class="chart" id="chart-{esc(chart["id"])}"><figcaption><strong>{esc(chart["title"])}</strong><span>{esc(chart.get("subtitle", ""))}</span></figcaption>{legend}'
            f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{esc(chart["title"])}">{"".join(marks)}{"".join(labels)}</svg>'
            f'<div class="tip" hidden></div><details><summary>Table view</summary><table><thead><tr><th scope="col">{esc(chart.get("category_label", ""))}</th>{head}</tr></thead><tbody>{body}</tbody></table></details>'
            f'<p class="muted">{esc(chart.get("note", ""))}</p></figure>')


def load_charts(wiki):
    path = wiki / 'charts.json'
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if data.get('schema') != 'instadna.charts/v1':
        raise ValueError('Unsupported chart manifest')
    charts = {}
    for chart in data['charts']:
        if not ID.fullmatch(chart['id']) or chart['id'] in charts or chart['type'] not in {'stacked', 'grouped', 'line'}:
            raise ValueError('Invalid chart')
        if not 1 <= len(chart['series']) <= 5:
            raise ValueError('Charts carry one to five series; fold the rest into Other')
        for s in chart['series']:
            if len(s['values']) != len(chart['categories']):
                raise ValueError(f"{chart['id']}: series length mismatch")
            if any(v is not None and (type(v) not in (int, float) or v < 0) for v in s['values']):
                raise ValueError(f"{chart['id']}: invalid value")
        charts[chart['id']] = chart
    return charts


# ---------- generated (synthetic) speech ----------

def load_generated_audio(wiki):
    """Hash-checked generated audio from `audio-manifest.json`; a disclosure is mandatory."""
    rows = load_audio(wiki)
    if not rows:
        return [], ''
    disclosure = (json.loads((wiki / 'audio-manifest.json').read_text()).get('disclosure') or '').strip()
    if 'synthetic' not in disclosure.lower():
        raise ValueError('Generated speech needs a disclosure that names it as synthetic')
    return rows, disclosure


def render_generated_audio(rows, disclosure, page=None):
    cards = []
    for row in rows:
        if row.get('download_only') or row.get('page') not in (None, page):
            continue
        extra = [r for r in rows if r.get('download_for') == row['id']]
        links = f'<a href="{esc(row["path"])}" download>Download {esc(Path(row["path"]).suffix[1:].upper())}</a>' + ''.join(
            f' · <a href="{esc(r["path"])}" download>{esc(r.get("download_label") or Path(r["path"]).suffix[1:].upper())}</a>' for r in extra)
        cards.append(f'''<section class="audio-card" id="{esc(row['id'])}"><span class="eyebrow">{esc(row['label'])} · {row['duration_s']:.1f} s</span>
<h3>{esc(row['title'])}</h3><p>{esc(row['description'])}</p>
<audio controls preload="metadata" src="{esc(row['path'])}" aria-label="{esc(row['title'])}"></audio>
<p class="audio-downloads">{links}</p></section>''')
    return f'<p class="disclosure"><strong>Synthetic speech.</strong> {esc(disclosure)}</p><div class="audio-grid">{"".join(cards)}</div>'


def render_generated_audio_pinned(rows, page=None):
    """Compact players for the top of a page: its newest take (`"latest": true`), then any take pinned to it from another
    page (`"pinned": [page]`, ordered by `pin_order`, labelled by `pin_label`). The full lists stay where they are."""
    chosen = [r for r in rows if not r.get('download_only')
              and ((r.get('latest') and r.get('page') in (None, page)) or page in (r.get('pinned') or []))]
    chosen.sort(key=lambda r: (not r.get('latest'), r.get('pin_order', 0)))
    cards = []
    for row in chosen:
        details = f'#{row["id"]}' if row.get('page') in (None, page) else f'{row["page"]}.html#{row["id"]}'
        label = 'Latest' if row.get('latest') else row.get('pin_label', 'Pinned')
        note = row.get('pin_note') or 'AI-generated: a synthetic voice, not a recording she made.'
        link = row.get('pin_link_text') or 'Details and the other takes'
        cards.append(f'<section class="audio-card audio-latest" id="pinned-{esc(row["id"])}"><span class="eyebrow">{esc(label)} · '
                     f'{esc(row["label"])} · {row["duration_s"]:.1f} s</span><h3>{esc(row["title"])}</h3>'
                     f'<audio controls preload="metadata" src="{esc(row["path"])}" aria-label="{esc(row["title"])}"></audio>'
                     f'<p class="audio-note">{esc(note)} <a href="{esc(details)}">{esc(link)}</a></p></section>')
    return ''.join(cards)


def render_generated_video(rows, disclosure, page=None):
    cards = []
    for row in rows:
        if row.get('page') not in (None, page):
            continue
        poster = f' poster="{esc(row["poster"])}"' if row.get('poster') else ''
        cards.append(f'''<figure class="video-card" id="{esc(row['id'])}"><span class="eyebrow">{esc(row['label'])} · {row['duration_s']:.1f} s · {row['width']}×{row['height']}</span>
<video controls playsinline preload="metadata"{poster} aria-label="{esc(row['title'])}"><source src="{esc(row['path'])}" type="video/mp4"></video>
<figcaption><h3>{esc(row['title'])}</h3><p>{esc(row['description'])}</p><p class="audio-downloads"><a href="{esc(row['path'])}" download>Download MP4</a></p></figcaption></figure>''')
    return f'<p class="disclosure"><strong>AI-generated video.</strong> {esc(disclosure)}</p><div class="video-grid">{"".join(cards)}</div>'


# ---------- storyboard: AI start frames timed to the synthetic voice ----------

SHOT_TYPES = {'talking-head': 'Talking head', 'studio': 'White studio', 'world': 'World', 'insert': 'Insert', 'card': 'End card'}
SUBJECTS = {'facing': 'Her, posed to the lens', 'angle': 'Her, other pose or angle', 'partial': 'Her hands, lips or details',
            'people': 'Other people from her world', 'object': 'Objects and places'}
STYLED_MODES = {'fp': 'Reference-reel serif', 'block': 'Her bold white block (A008)', 'mix': 'Her yellow script + white sans (A015)'}


def _clock(t):
    return f'{int(t // 60)}:{t % 60:05.2f}'


FRAME_PATH = r'storyboard/(?:round[0-9]+/)?[A-Za-z0-9_.-]+\.webp'
STYLED_PATH = r'storyboard/(?:round[0-9]+/|video/)?styled/[A-Za-z0-9_.-]+\.webp'


def load_storyboard(wiki, generated_audio, passport, name='storyboard.json'):
    """Hash-checked storyboard of AI frames; it must be disclosed, contiguous and cover its published audio."""
    if not re.fullmatch(r'storyboard(?:-round[0-9]+|-video)?\.json', name):
        raise ValueError(f'Storyboard manifest is not on the allowlist: {name}')
    path = wiki / name
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if data.get('schema') != 'instadna.storyboard/v1':
        raise ValueError('Unsupported storyboard manifest')
    if 'ai-generated' not in (data.get('disclosure') or '').lower():
        raise ValueError('A storyboard of a real person needs an AI-generated disclosure')
    if data['audio']['path'] not in {r['path'] for r in generated_audio}:
        raise ValueError('Storyboard audio must be a published, disclosed generated audio asset')
    items = {i['id'] for i in (passport or {}).get('items', [])}
    images = set()

    def frame(row, where):
        if row.get('kind') != 'ai_storyboard_frame' or not row.get('model') or 'AI-generated' not in (row.get('label') or ''):
            raise ValueError(f'{where}: frame must be labelled as an AI-generated storyboard frame with its model')
        image = _inside(wiki, row['path'], FRAME_PATH, row['sha256'])
        _inside(wiki, row['thumbnail'], FRAME_PATH, row['thumbnail_sha256'])
        with Image.open(image) as img:
            if img.size != (row['width'], row['height']):
                raise ValueError(f'{where}: frame dimensions do not match')
        images.update({row['path'], row['thumbnail']})

    if data.get('identity_anchor', {}).get('frame'):
        frame(data['identity_anchor']['frame'], 'identity anchor')
    seen, clock = set(), 0.0
    for shot in data['shots']:
        sid = shot['id']
        if not re.fullmatch(r'S[0-9]{2,3}', sid) or sid in seen:
            raise ValueError('Invalid or duplicate shot ID')
        seen.add(sid)
        if shot['type'] not in SHOT_TYPES:
            raise ValueError(f'{sid}: unknown shot type')
        if abs(shot['start'] - clock) > 0.002 or shot['end'] <= shot['start']:
            raise ValueError(f'{sid}: shots must be contiguous and in time order')
        clock = shot['end']
        if shot['type'] != 'card':
            if not shot.get('frame'):
                raise ValueError(f'{sid}: shot has no start frame')
            frame(shot['frame'], sid)
        for mode, row in shot.get('styled', {}).items():
            if mode not in STYLED_MODES:
                raise ValueError(f'{sid}: unknown caption style {mode}')
            _inside(wiki, row['path'], STYLED_PATH, row['sha256'])
            images.add(row['path'])
            if row.get('thumbnail'):
                _inside(wiki, row['thumbnail'], STYLED_PATH, row['thumbnail_sha256'])
                images.add(row['thumbnail'])
        for c in shot['captions']:
            if not (shot['start'] - 1e-6 <= c['start'] < shot['end']) or not c['text'].strip():
                raise ValueError(f'{sid}: caption outside its shot')
        for item in shot['passport']:
            if item['id'] not in items:
                raise ValueError(f"{sid}: unknown passport item {item['id']}")
    if abs(clock - data['audio']['duration_s']) > 0.05:
        raise ValueError('Storyboard must cover the whole audio')
    data['images'] = images
    data['file'] = name
    return data


def render_storyboard_history(storyboards, board_map, page, nav, generated_audio=()):
    """The other storyboard pages' start frames, plain (no captions), in time order, newest round first after this page's."""
    labels = dict(nav)
    blocks = []
    for other, name in board_map.items():
        board = storyboards.get(name)
        if other in ('*', page) or not board:
            continue
        shots = [s for s in board['shots'] if s['type'] != 'card' and s.get('frame')]
        frames = ''.join(f'<a class="history-frame" href="{esc(other)}.html#{esc(s["id"])}" title="{esc(s["id"])} · {esc(s["title"])}">'
                         f'<img src="{esc(s["frame"]["thumbnail"])}" alt="{esc(s["id"])} · {esc(s["title"])} (AI-generated start frame)" loading="lazy">'
                         f'<span>{esc(s["id"])}</span></a>' for s in shots)
        track = next((r for r in generated_audio if r['path'] == board['audio']['path']), None)
        player = (f'<div class="history-audio"><span>{esc(track["title"])}</span>'
                  f'<audio controls preload="none" src="{esc(track["path"])}" aria-label="{esc(track["title"])}"></audio></div>') if track else ''
        blocks.append(f'<section class="history-round"><h3><a href="{esc(other)}.html">{esc(labels.get(other, other))}</a></h3>'
                      f'<p class="history-meta">{len(shots)} start frames · {board["audio"]["duration_s"]:.1f} s · AI-generated</p>'
                      f'{player}<div class="history-grid">{frames}</div></section>')
    return f'<div class="storyboard-history">{"".join(blocks)}</div>' if blocks else ''


def _ref_link(ref):
    kind, _, name = ref.partition(':')
    if kind == 'atlas':
        return f'<a href="visual-atlas.html#{esc(name)}">{esc(name)}</a>'
    if kind == 'item':
        return f'<a href="visual-passport.html#{esc(name)}">passport · {esc(name)}</a>'
    if kind == 'frame':
        return f'<a href="#anchor">identity anchor {esc(name)}</a>'
    return f'{esc(name)} (private reference)'


def _shot_card(s, end_card_text, group=None):
    styled = s.get('styled', {})
    main = styled.get('fp') or s.get('frame')
    caps = ''.join(f'<li><b lang="ru" class="cap cap-{esc(c["style"])}">{esc(c["text"])}</b> <span>{c["start"]:.2f} s</span></li>'
                   for c in s['captions'])
    chips = ''.join(f'<a class="chip" href="visual-passport.html#{esc(p["id"])}">{esc(p["title"])}</a>' for p in s['passport'])
    refs = ' · '.join(_ref_link(r) for r in s['references']) or 'none'
    links = ([f'<a href="{esc(s["frame"]["path"])}" download>Clean start frame</a>'] if s.get('frame') else []) + [
        f'<a href="{esc(row["path"])}">{esc(STYLED_MODES[m])}</a>' for m, row in styled.items()]
    model = ''
    if s.get('frame'):
        when = s['frame']['generated_at'][:16].replace('T', ' ')
        model = (f'<p class="muted">{esc(s["frame"]["model"])} · generated {esc(when)} UTC · '
                 f'prompt sha256 {esc(s["frame"]["prompt_sha256"][:12])}…</p>')
    if main:
        picture = (f'<a class="shot-image" href="{esc(main["path"])}"><img src="{esc(main.get("thumbnail") or main["path"])}" '
                   f'alt="{esc(s["id"])}: {esc(s["title"])}" loading="lazy" width="{main["width"]}" height="{main["height"]}"></a>')
    else:
        picture = f'<div class="shot-image shot-card-black"><span lang="ru">{esc(end_card_text)}</span></div>'
    what = ' · ' + SUBJECTS[s['subject']] if s.get('subject') in SUBJECTS else ''
    view = f' · {s["view"]}' if s.get('view') and s['view'] != 'n/a' else ''
    head = (f'{s["n"]:02d} · {SHOT_TYPES[s["type"]]}{what}{view} · {_clock(s["start"])}–{_clock(s["end"])} · {s["duration"]:.2f} s'
            + (' · 30 s cut' if s['short_cut'] else ''))
    vo = f'<p class="vo" lang="ru">«{esc(s["vo"])}»</p>' if s['vo'] else ''
    cap_list = f'<ul class="caps">{caps}</ul>' if caps else ''
    return (f'<li class="shot" id="{esc(s["id"])}" data-category="{esc(group or s["type"])}" data-short="{str(s["short_cut"]).lower()}">{picture}'
            f'<div class="shot-copy"><span class="eyebrow">{esc(head)}</span><h3>{esc(s["title"])}</h3>{vo}{cap_list}'
            f'<p class="chips">{chips}</p>'
            f'<button type="button" class="shot-play" data-seek="{s["start"]:.3f}">▶ Play from {_clock(s["start"])}</button>'
            f'<details><summary>Frame, motion &amp; sources</summary><p><strong>Start frame</strong> {esc(s["scene"])}</p>'
            f'<p><strong>For image-to-video</strong> {esc(s["motion"])} Preview camera: {esc(s["camera"])}.</p>'
            f'<p><strong>Why this shot</strong> {esc(s["basis"])}</p><p><strong>References</strong> {refs}</p>{model}'
            f'<p class="actions">{" · ".join(links)}</p></details></div></li>')


def render_storyboard(data):
    shots = data['shots']
    total = data['audio']['duration_s']
    first = shots[0]
    poster = (first.get('styled', {}).get('fp') or first['frame'])['path']
    by_subject = any(s.get('subject') in SUBJECTS for s in shots)
    group = lambda s: 'card' if s['type'] == 'card' else (f'subj-{s["subject"]}' if by_subject else s['type'])
    segs = []
    for s in shots:
        cls = f'seg seg-{group(s)}' + (' seg-short' if s['short_cut'] else '')
        x, w = s['start'] / total * 1000, max(0.5, (s['end'] - s['start']) / total * 1000 - 1.2)
        segs.append(f'<a href="#{esc(s["id"])}"><rect class="{esc(cls)}" data-shot="{esc(s["id"])}" x="{x:.2f}" y="0" width="{w:.2f}" '
                    f'height="28" rx="2"><title>{esc(s["id"])} · {_clock(s["start"])}–{_clock(s["end"])} · {esc(s["title"])}</title></rect></a>')
    label = lambda g: SUBJECTS[g[5:]] if g.startswith('subj-') else SHOT_TYPES[g]
    groups = sorted(dict.fromkeys(group(s) for s in shots), key=lambda g: (g == 'card', list(SUBJECTS).index(g[5:]) if g.startswith('subj-') else 0))
    buttons = '<button type="button" data-filter="all" aria-pressed="true">All shots</button>' + ''.join(
        f'<button type="button" data-filter="{esc(g)}" aria-pressed="false">{esc(label(g))}</button>' for g in groups)
    cut = data['stats'].get('short_cut')
    legend = ''.join(f'<span class="key seg-{g}"></span>{esc(label(g))} ' for g in groups)
    cards = ''.join(_shot_card(s, data['format']['end_card']['text'], group(s)) for s in shots)
    short = ('' if not cut else f'<p class="board-options"><label><input type="checkbox" class="board-short"> Play only the 30-second cut '
             f'({cut["shots"]} shots, about {cut["duration_s"]:.0f} s)</label></p>')
    return (f'<div class="board" data-src="{esc(data["file"])}"><div class="board-player">'
            f'<figure class="board-screen"><img class="board-current" src="{esc(poster)}" alt="Current shot" width="540" height="960">'
            f'<figcaption class="board-now" aria-live="polite">{esc(first["id"])} · {esc(first["title"])}</figcaption></figure>'
            f'<div class="board-side"><p class="disclosure"><strong>AI-generated.</strong> {esc(data["disclosure"])}</p>'
            f'<audio class="board-audio" controls preload="auto" src="{esc(data["audio"]["path"])}" '
            f'aria-label="Synthetic self-presentation in Russian, {total:.0f} seconds"></audio>'
            f'{short}'
            f'<svg class="board-strip" viewBox="0 0 1000 28" preserveAspectRatio="none" role="img" '
            f'aria-label="Shot timeline: {len(shots)} shots over {total:.0f} seconds">{"".join(segs)}</svg>'
            f'<p class="board-legend">{legend}</p><p class="board-vo" lang="ru" aria-live="polite"></p></div></div>'
            f'<div class="filters" data-target="shot" role="group" aria-label="Filter shots">{buttons}</div>'
            f'<p class="count" aria-live="polite">{len(shots)} shots</p><ol class="shots">{cards}</ol></div>')


def render_storyboard_anchor(data):
    anchor = data.get('identity_anchor') or {}
    row = anchor.get('frame')
    if not row:
        return ''
    refs = ' · '.join(_ref_link(r) for r in anchor['references'])
    return (f'<figure class="anchor" id="anchor"><a href="{esc(row["path"])}"><img src="{esc(row["thumbnail"])}" '
            f'alt="Identity anchor: {esc(anchor["title"])}" loading="lazy" width="{row["width"]}" height="{row["height"]}"></a>'
            f'<figcaption><span class="eyebrow">Identity anchor · {esc(row["model"])}</span><h3>{esc(anchor["title"])}</h3>'
            f'<p>{esc(anchor["scene"])}</p><p><strong>Made from</strong> {refs}</p>'
            '<p class="muted">Every frame that shows her face was generated from this anchor plus her own published frames.</p></figcaption></figure>')


def render_storyboard_types(data):
    rows = []
    for s in data['shots']:
        styled = s.get('styled', {})
        if len(styled) < 2:
            continue
        figs = ''.join(
            f'<figure><a href="{esc(row["path"])}"><img src="{esc(row.get("thumbnail") or row["path"])}" '
            f'alt="{esc(s["id"])} with {esc(STYLED_MODES[m])}" loading="lazy" width="{row["width"]}" height="{row["height"]}"></a>'
            f'<figcaption>{esc(STYLED_MODES[m])}</figcaption></figure>' for m, row in styled.items())
        rows.append(f'<div class="type-row"><h3>{esc(s["id"])} · {esc(s["title"])}</h3><div class="type-figs">{figs}</div></div>')
    return ''.join(rows)


# ---------- data room: private corpus export ----------

def check_data_room(directory):
    """The data room is generated from the private corpus: JSON shards plus WebP thumbnails only."""
    directory = Path(directory).resolve()
    index = json.loads((directory / 'index.json').read_text())
    if index.get('schema') != 'instadna.dataroom/v1':
        raise ValueError('Unsupported data room')
    for path in directory.rglob('*'):
        if path.is_symlink() or (path.is_file() and path.suffix not in {'.json', '.webp'}):
            raise ValueError(f'Data room may contain only JSON and WebP: {path.name}')
        if path.is_file() and path.stat().st_size >= 25 * 1024 * 1024:
            raise ValueError(f'Data room file too large: {path.name}')
    for row in index['items']:
        check_source({**row, 'source_url': row['url'], 'source_id': row['id'], 'date_basis': row.get('date_basis') or 'collector'}, f"{row['id']}: ")
    return index


# ---------- build ----------

def page_shell(edition, title, content, prefix, current, nav, stats, body_class=''):
    def link(name, label):
        page, _, anchor = name.partition('#')  # 'page#section' links into a page (e.g. its newest take)
        href = f'{prefix}{page}.html' + (f'#{anchor}' if anchor else '')
        return f'<a class="{"active" if page == current and not anchor else ""}" href="{href}">{esc(label)}</a>'
    menu = ''.join(link(name, label) if not name.startswith('#') else f'<span class="nav-group">{esc(label)}</span>' for name, label in nav)
    tiles = ''.join(f'<div><b>{esc(str(value))}</b><span>{esc(label)}</span></div>' for value, label in stats)
    person = edition['person']
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">
<title>{esc(title)} · {esc(person['display_name'])} DNA</title><link rel="stylesheet" href="{prefix}edition.css"><script src="{prefix}edition.js" defer></script></head>
<body class="{body_class}"><a class="skip" href="#content">Skip to content</a><aside><a class="brand" href="{prefix}index.html"><span class="mark">{esc(person['monogram'])}</span><span>{esc(person['display_name'])}<small>{esc(person['subtitle'])}</small></span></a>
<label for="search">Search the report</label><input id="search" type="search" placeholder="Wardrobe, keyword, place, voice…" data-root="{prefix}"><div id="search-results" aria-live="polite"></div>
<nav aria-label="Report sections">{menu}</nav><p class="aside-note">{esc(edition['footer_note'])}</p></aside>
<main id="content"><header><span class="eyebrow">{esc(edition['eyebrow'])}</span><span class="status">{esc(edition['status'])}</span></header>
<div class="stats">{tiles}</div><article>{content}</article><footer>{esc(edition['footer'])}</footer></main></body></html>'''


def build_edition(wiki: Path, output: Path, data_room: Path | None = None):
    wiki, output = wiki.resolve(), output.resolve()
    if output == wiki or output.is_relative_to(wiki) or wiki.is_relative_to(output):
        raise ValueError('Site output and wiki must be separate directories')
    policy = json.loads((wiki / 'publication-policy.json').read_text())
    if policy != {'version': 1, 'requires_authentication': True}:
        raise ValueError('A person edition is always protected; publication policy must require authentication')
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError('Use an empty prepared output directory; never deploy a repository root')
    edition = json.loads((wiki / 'edition.json').read_text())
    if edition.get('schema') != 'instadna.edition/v1':
        raise ValueError('Unsupported edition manifest')
    atlas = load_atlas(wiki)
    generated = load_generated_images(wiki)
    passport = load_passport(wiki, atlas, generated)
    phrases = load_phrases(wiki)
    charts = load_charts(wiki)
    generated_audio, disclosure = load_generated_audio(wiki)
    generated_video, video_disclosure = load_video(wiki)
    board_map = edition.get('storyboards') or ({'*': 'storyboard.json'} if (wiki / 'storyboard.json').exists() else {})
    storyboards = {name: load_storyboard(wiki, generated_audio, passport, name) for name in sorted(set(board_map.values()))}
    storyboards = {k: v for k, v in storyboards.items() if v}
    room = check_data_room(data_room) if data_room else None
    images = {r[k] for r in atlas['references'] for k in ('image', 'thumbnail')} | {r[k] for r in generated for k in ('path', 'thumbnail') if k in r}
    for board in storyboards.values():
        images |= board['images']
    nav = [tuple(x) for x in edition['nav']]
    search = []
    for source in sorted(wiki.rglob('*.md')):
        rel = source.relative_to(wiki)
        if rel.name == 'AGENTS.md':
            continue
        text = source.read_text()
        title = (re.search(r'^# (.+)$', text, re.M) or [None, source.stem])[1]
        linked = re.sub(r'\]\(([^)\s]+)\.md(#[^)]*)?\)', lambda m: '](' + m[1] + '.html' + (m[2] or '') + ')', text)
        content = safe_markdown(linked, frozenset(images))
        storyboard = storyboards.get(board_map.get(source.stem) or board_map.get('*') or '')
        widgets = {'<div id="evidence-atlas"></div>': lambda: render_atlas(atlas),
                   '<div id="passport-items"></div>': lambda: render_passport(passport, generated) if passport else '',
                   '<div id="phrase-bank"></div>': lambda: render_phrases(phrases) if phrases else '',
                   '<div id="generated-audio"></div>': lambda: render_generated_audio(generated_audio, disclosure, source.stem) if generated_audio else '',
                   '<div id="generated-video"></div>': lambda: render_generated_video(generated_video, video_disclosure, source.stem) if generated_video else '',
                   '<div id="generated-audio-latest"></div>': lambda: render_generated_audio_pinned(generated_audio, source.stem) if generated_audio else '',
                   '<div id="storyboard"></div>': lambda: render_storyboard(storyboard) if storyboard else '',
                   '<div id="storyboard-anchor"></div>': lambda: render_storyboard_anchor(storyboard) if storyboard else '',
                   '<div id="storyboard-types"></div>': lambda: render_storyboard_types(storyboard) if storyboard else '',
                   '<div id="storyboard-history"></div>': lambda: render_storyboard_history(storyboards, board_map, source.stem, [*nav, *edition.get('storyboard_labels', {}).items()], generated_audio),
                   '<div id="data-room"></div>': lambda: '<div id="room" data-src="data/index.json"><p>Loading every collected item…</p></div>' if room else '<p>The data room is attached only to the protected deployment.</p>'}
        for marker, render in widgets.items():
            if marker in content:
                content = content.replace(marker, render())
        for chart_id, chart in charts.items():
            marker = f'<div id="chart-{chart_id}"></div>'
            if marker in content:
                content = content.replace(marker, render_chart(chart))
        if re.search(r'<div id="(chart-[a-z0-9-]+|evidence-atlas|passport-items|phrase-bank|generated-audio|generated-audio-latest|generated-video|storyboard-history|storyboard|storyboard-anchor|storyboard-types|data-room)"></div>', content):
            raise ValueError(f'{rel}: unresolved widget placeholder')
        prefix = '../' * (len(rel.parts) - 1)
        body = 'wide' if source.stem in edition.get('wide_pages', []) else ''
        document = page_shell(edition, title, content, prefix, source.stem, nav, edition['stats'], body)
        dest = output / rel.with_suffix('.html')
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(document)
        search.append({'title': title, 'url': str(rel.with_suffix('.html')), 'text': re.sub(r'[#*|\[\]()<>]', ' ', text)[:40000]})
    (output / 'search-index.json').write_text(json.dumps(search, ensure_ascii=False))
    for name in ['edition.css', 'edition.js', '_worker.js', '_routes.json']:
        shutil.copyfile(WEB / name, output / name)
    for name in sorted(images):
        (output / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(wiki / name, output / name)
    for row in (phrases or {}).get('spoken', []) + generated_audio:
        (output / 'audio').mkdir(exist_ok=True)
        shutil.copyfile(wiki / row['path'], output / row['path'])
    for name in video_files(generated_video):
        (output / 'video').mkdir(exist_ok=True)
        shutil.copyfile(wiki / name, output / name)
    for name in ['coverage.json', 'source-inventory.json', 'atlas.json', 'passport.json', 'phrases.json', 'charts.json', 'generated-images.json', 'voice-metrics.json', 'lexicon.json', 'audio-manifest.json', 'video-manifest.json', *storyboards]:
        if (wiki / name).exists():
            shutil.copyfile(wiki / name, output / name)
    if room:
        shutil.copytree(Path(data_room).resolve(), output / 'data')
    return {'pages': len(search), 'images': len(images), 'phrases': len((phrases or {}).get('spoken', [])), 'generated_audio': len(generated_audio),
            'generated_video': len(generated_video),
            'storyboard_shots': sum(len(b['shots']) for b in storyboards.values()),
            'data_room_items': len(room['items']) if room else 0}
