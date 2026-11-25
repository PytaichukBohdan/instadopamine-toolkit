"""Selected original speech excerpts: separate from generated speech exports."""
import hashlib
import html
import json
import math
import re
import subprocess
from .temporal import summarize_time, render_time


def load_phrases(wiki, public=False):
    manifest = wiki / 'phrase-bank.json'
    if not manifest.exists():
        return None
    data = json.loads(manifest.read_text())
    if data.get('schema') != 'instadna.phrases/v1' or data.get('audience') != 'private':
        raise ValueError('Phrase sources require a private phrase manifest')
    if public:
        raise ValueError('Source phrase audio is private; use a protected build')
    sources = {s['id']: s for s in data['sources']}
    if len(sources) != len(data['sources']):
        raise ValueError('Duplicate phrase source')
    for source in sources.values():
        if not re.fullmatch(r'sources/[A-Za-z0-9_-]+\.md', source['page']) or not (wiki/source['page']).is_file():
            raise ValueError('Phrase source page is missing')
        if source.get('source_id') != source['id'] or not source.get('date_basis'):
            raise ValueError('Phrase source identity/date basis is missing')
        if not re.fullmatch(r'https://www\.instagram\.com/(?:p/[A-Za-z0-9_-]+/|stories/highlights/[0-9]+/\?story_media_id=[0-9]+)', source['url']):
            raise ValueError('Phrase URL must be its original Instagram source')
        if not re.fullmatch(r'[a-f0-9]{64}', source['audio_sha256']):
            raise ValueError('Phrase source audio requires a hash')
        duration = source['duration_s']
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
            raise ValueError('Invalid phrase source duration')
        summarize_time([source], data['as_of'])
    seen, files = set(), set()
    families = {f['id']: f for f in data['families']}
    if len(families) != len(data['families']):
        raise ValueError('Duplicate phrase family')
    for row in data['phrases']:
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', row['id']) or row['id'] in seen:
            raise ValueError('Invalid or duplicate phrase ID')
        seen.add(row['id'])
        if row.get('origin') != 'source_excerpt' or row.get('publish') is not True:
            raise ValueError('Only selected original excerpts enter the phrase bank')
        if row['source_id'] not in sources or row['family'] not in families:
            raise ValueError('Unknown phrase source or family')
        for field in ['text', 'language', 'attribution', 'delivery', 'context', 'review_method', 'limitations']:
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError('Phrase is missing ' + field)
        start, end, duration = (row[k] for k in ['start_s', 'end_s', 'duration_s'])
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in [start, end, duration]):
            raise ValueError('Invalid phrase time')
        if not 0 <= start < end <= sources[row['source_id']]['duration_s'] or end-start > 15:
            raise ValueError('Phrase window must fit its source and be at most 15 seconds')
        if abs(duration - (end-start)) > .12:
            raise ValueError('Excerpt duration does not match source window')
        name = row['path']
        if not re.fullmatch(r'audio/phrase-[a-z0-9-]+\.mp3', name) or name in files:
            raise ValueError('Phrase excerpt requires its own allowlisted path')
        files.add(name)
        path = wiki/name
        if path.is_symlink() or not path.resolve().is_relative_to(wiki.resolve()) or path.stat().st_size >= 25*1024*1024:
            raise ValueError('Invalid phrase audio path/size')
        if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('Phrase audio hash mismatch')
        probe = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)]))
        if len(probe['streams']) != 1 or probe['streams'][0]['codec_type'] != 'audio':
            raise ValueError('Phrase export must contain only one audio stream')
        if abs(float(probe['format']['duration'])-duration) > .1:
            raise ValueError('Phrase audio duration mismatch')
    for family in families.values():
        rows = [r for r in data['phrases'] if r['family'] == family['id']]
        if not rows or family['temporal'] != summarize_time([sources[r['source_id']] for r in rows], data['as_of']):
            raise ValueError('Phrase family temporal summary mismatch')
    return data


def render_phrases(data):
    if not data:
        return ''
    esc = html.escape
    sources = {s['id']: s for s in data['sources']}
    cards, summaries = [], []
    options = '<option value="all">All speaking patterns</option>'
    for f in data['families']:
        options += f'<option value="{esc(f["id"])}">{esc(f["title"])}</option>'
        summaries.append(f'<details><summary>{esc(f["title"])}</summary><p>{esc(f["context"])}</p>{render_time(f["temporal"])}<p>Counts describe this speaking pattern, not repetition of every exact quote.</p></details>')
    for r in sorted(data['phrases'], key=lambda row: sources[row['source_id']].get('published_at') or '', reverse=True):
        s = sources[r['source_id']]
        temporal = summarize_time([s], data['as_of'])
        # Exact-word recurrence counts distinct recordings, not separate crops.
        normalize = lambda text: re.sub(r'[^\w\s]', '', text.casefold()).split()
        matches = {x['source_id'] for x in data['phrases'] if normalize(x['text']) == normalize(r['text']) and x['language'] == r['language']}
        exact = f'Exact wording: {len(matches)} distinct source(s) in this selected bank.'
        exact_history = render_time(summarize_time([sources[ident] for ident in matches], data['as_of'])) if len(matches) > 1 else ''
        cards.append(f'''<section class="phrase-card audio-card" id="{esc(r['id'])}" data-family="{esc(r['family'])}" data-recency="{temporal['recency']}">
<span class="eyebrow">ORIGINAL AUDIO · {esc(r['language'])} · {r['duration_s']:.1f}s</span><h2><a href="#{esc(r['id'])}">{esc(r['text'])}</a></h2>
<p>{esc(r['context'])}</p><audio controls preload="none" src="{esc(r['path'])}" aria-label="{esc(r['text'])}"></audio>
<p class="phrase-delivery"><strong>Delivery:</strong> {esc(r['delivery'])}</p>
{render_time(temporal)}<details><summary>Source, timing & confidence</summary>
<p><a href="{esc(s['page'].replace('.md', '.html'))}">{esc(s['label'])}</a> · original {r['start_s']:.2f}–{r['end_s']:.2f}s · <a href="{esc(s['url'])}">Instagram</a></p>
<p>{esc(exact)} {esc(s['date_basis'])}</p>{exact_history}<p>{esc(r['attribution'])}</p><p>{esc(r['review_method'])} {esc(r['limitations'])}</p><p>{esc(r.get('crop_review_note', ''))}</p></details>
<p><a href="{esc(r['path'])}" download>Download selected MP3 excerpt ↗</a></p></section>''')
    return f'''<details class="phrase-pattern-history"><summary>Explore the history of {len(summaries)} speaking patterns</summary><div class="phrase-families">{''.join(summaries)}</div></details><div class="phrase-toolbar"><label for="phrase-search">Find a phrase</label><input id="phrase-search" type="search" placeholder="Greeting, catchphrase, invitation…"><label for="phrase-family">Speaking pattern</label><select id="phrase-family">{options}</select><label for="phrase-recency">Latest evidence</label><select id="phrase-recency"><option value="all">All dates</option><option value="recent">Recent · ≤180 days</option><option value="older">Older · 181–730 days</option><option value="historical">Historical · over 730 days</option><option value="unknown">Date unknown</option></select></div><p id="phrase-count" aria-live="polite">{len(cards)} original audio excerpts</p><div class="phrase-grid">{''.join(cards)}</div>'''
