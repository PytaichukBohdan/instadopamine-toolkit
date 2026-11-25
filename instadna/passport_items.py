"""Standalone passport images with source evidence and a practical usage brief."""
import html
import json
import re
from datetime import datetime
from .temporal import summarize_time, render_time


RECURRENCE = {'repeated': 'Across publications', 'sequence': 'Within one sequence', 'single': 'One observation'}


def evidence_date(value):
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.utcoffset() is None:
            raise ValueError('Publication date must include a timezone')
        return parsed.date().isoformat()
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError('Invalid passport publication date') from exc


def load_passport_items(wiki, references, generated_images):
    path = wiki / 'passport-items.json'
    if not path.exists():
        return []
    manifest = json.loads(path.read_text())
    rows = manifest['items']
    refs = {r['id']: r for r in references}
    generated = {r['path']: r for r in generated_images}
    seen = set()
    for row in rows:
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', row['id']) or row['id'] in seen:
            raise ValueError('Invalid or duplicate passport item ID')
        seen.add(row['id'])
        if not row['reference_ids'] or any(ref not in refs for ref in row['reference_ids']):
            raise ValueError('Passport item requires existing source references')
        if row['kind'] == 'ai_visual_synthesis':
            if row['image'] not in generated:
                raise ValueError('Passport illustration must be hash-validated')
            if row.get('thumbnail') and row['thumbnail'] != generated[row['image']].get('thumbnail'):
                raise ValueError('Passport thumbnail must match its validated image')
        elif row['kind'] == 'source_reference':
            if row['image'] not in {refs[r]['image'] for r in row['reference_ids']}:
                raise ValueError('Passport source image must match its evidence')
        else:
            raise ValueError('Unknown passport image kind')
        for field in ['title', 'category', 'description', 'context', 'usage_brief', 'limit']:
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError('Passport item is missing ' + field)
        if manifest.get('version', 1) >= 3 and row['category'] == 'phrases' and row.get('phrase_evidence') not in {'spoken','written_only'}:
            raise ValueError('Graphic phrases must distinguish written and spoken evidence')
        if manifest.get('version', 1) >= 2:
            if row.get('recurrence') not in RECURRENCE or not row.get('recurrence_note', '').strip():
                raise ValueError('Passport item requires a recurrence boundary')
            appearances = row.get('appearances', [])
            if [r.get('reference_id') for r in appearances] != row['reference_ids']:
                raise ValueError('Passport timing must cover every source reference in order')
            for appearance in appearances:
                ref = refs[appearance['reference_id']]
                for key in ['published_at', 'time_seconds']:
                    if appearance.get(key) != ref.get(key):
                        raise ValueError('Passport timing does not match source evidence')
                evidence_date(appearance.get('published_at'))
                if not appearance.get('locator') or not appearance.get('date_basis'):
                    raise ValueError('Passport timing requires a locator and date basis')
                if manifest.get('version', 1) >= 3:
                    if appearance.get('source_id') != str(ref.get('story_id') or ref['shortcode']):
                        raise ValueError('Temporal source must match the original publication')
            if manifest.get('version', 1) >= 3:
                if row.get('temporal') != summarize_time(appearances, manifest['as_of']):
                    raise ValueError('Passport temporal summary does not match observations')
    return rows


def render_passport_items(rows):
    esc = html.escape
    categories = list(dict.fromkeys(r['category'] for r in rows))
    buttons = '<button type="button" data-category="all" aria-pressed="true">All items</button>'
    buttons += ''.join(f'<button type="button" data-category="{esc(c)}" aria-pressed="false">{esc(c.title())}</button>' for c in categories)
    cards = []
    for r in rows:
        synthetic = r['kind'] == 'ai_visual_synthesis'
        label = 'Phrase asset' if r['category'] == 'phrases' else 'AI reconstruction' if synthetic else 'Original source reference'
        if r.get('phrase_evidence') == 'written_only':
            label = 'Written phrase · pronunciation unverified'
        elif r.get('phrase_evidence') == 'spoken':
            label = 'Phrase with spoken evidence'
        sources = ' · '.join(f'<a href="visual-atlas.html#{esc(ref)}">{esc(ref)}</a>' for ref in r['reference_ids'])
        appearances = r.get('appearances', [])
        dates = sorted({evidence_date(a.get('published_at')) for a in appearances if a.get('published_at')})
        date_label = ' → '.join(dict.fromkeys([dates[0], dates[-1]])) if dates else 'Publication date unknown'
        if dates and any(a.get('published_at') is None for a in appearances):
            date_label += ' · some dates unknown'
        strength = RECURRENCE.get(r.get('recurrence'), 'Source-linked')
        timing = ''.join(f'<li><a href="visual-atlas.html#{esc(a["reference_id"])}">{esc(a["reference_id"])}</a> · {esc(evidence_date(a.get("published_at")) or "Date unknown")} · {esc(a["locator"])}<br><small>{esc(a["date_basis"])}</small></li>' for a in appearances)
        cards.append(f'''<article class="passport-item" id="{esc(r['id'])}" data-category="{esc(r['category'])}" data-recurrence="{esc(r.get('recurrence', 'single'))}" data-recency="{esc(r.get('temporal', {}).get('recency', 'unknown'))}">
<a class="item-image" href="{esc(r['image'])}"><img src="{esc(r.get('thumbnail', r['image']))}" alt="{esc(r['title'])}" loading="lazy" width="1024" height="1024"></a>
<div class="item-copy"><span class="eyebrow">{esc(r['category'])} · {label}</span>
<h2><a href="#{esc(r['id'])}">{esc(r['title'])}</a></h2>
<p>{esc(r['description'])}</p><p class="item-context"><strong>Where to use it</strong>{esc(r['context'])}</p>
<p class="item-timing"><span class="recurrence-badge">{esc(strength)}</span><span>Published · {esc(date_label)}</span></p>
{render_time(r.get('temporal'))}
<details><summary>Usage brief</summary><p class="item-brief">{esc(r['usage_brief'])}</p><button type="button" class="copy-brief">Copy brief</button></details>
<details class="item-evidence"><summary>Timing & evidence</summary><p>{esc(r.get('recurrence_note', ''))}</p><ul>{timing}</ul><p class="item-limit">{esc(r['limit'])}</p></details>
<div class="item-actions"><a href="{esc(r['image'])}" download>Download image ↗</a><span>Evidence: {sources}</span></div></div></article>''')
    return f'''<div class="item-toolbar"><label for="item-search">Find an asset</label><input id="item-search" type="search" placeholder="Object, clothing, place, phrase…"><label for="item-recurrence">Evidence</label><select id="item-recurrence"><option value="all">All observations</option><option value="repeated">Across publications</option><option value="sequence">Within one sequence</option><option value="single">One observation</option></select><label for="item-recency">Latest known evidence</label><select id="item-recency"><option value="all">All dates</option><option value="recent">Recent · ≤180 days</option><option value="older">Older · 181–730 days</option><option value="historical">Historical · over 730 days</option><option value="unknown">Date unknown</option></select><div class="item-filters">{buttons}</div></div>
<p id="item-count" aria-live="polite">{len(rows)} separate items</p><div class="passport-items">{''.join(cards)}</div><p id="item-copy-status" role="status" aria-live="polite"></p>'''
