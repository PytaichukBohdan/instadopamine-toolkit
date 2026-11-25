#!/usr/bin/env python3
"""Write a short machine note for every item a person wiki cites as `sources/<platform>-<id>.md`.

Each note gives the publication date and basis, the original link, format, duration and
languages, a redacted two-sentence machine summary, topics and offers, and up to three
short quotes attributed to the creator. Names of other people that the item analysis
lists (clients, students, attendees) and their @handles are withheld unless allow-listed
as public collaborators. Summaries about private relationships or medical detail are
withheld entirely. Notes are machine observations, labelled as such.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

LINK = re.compile(r'\]\(sources/([a-z]+)-([A-Za-z0-9_-]+)\.md')
PREFIX = {'ig': 'instagram', 'igh': 'instagram_highlight', 'igs': 'instagram_story', 'tg': 'telegram', 'yt': 'youtube'}
LABEL = {'instagram': 'Instagram post', 'instagram_highlight': 'Instagram Highlight story', 'instagram_story': 'Instagram story',
         'telegram': 'Telegram message', 'youtube': 'YouTube video'}
PRIVATE = re.compile(r'(?i)\b(?:romantic|abusive|toxic|past|personal|her)\s+relationships?|relationship history|gaslight|divorc|'
                     r'ex-(?:husband|wife|boyfriend|girlfriend|partner)|break-?up|cheat(?:ed|ing)|pregnan|miscarr|diagnos(?:is|ed)\b|'
                     r'hospital|surgery|sexual|prenup|trauma')
CYR = dict(zip('абвгґдеєжзиіїйклмнопрстуфхцчшщьюяыэёъ',
               ['a', 'b', 'v', 'h', 'g', 'd', 'e', 'ie', 'zh', 'z', 'y', 'i', 'i', 'i', 'k', 'l', 'm', 'n', 'o', 'p', 'r', 's', 't', 'u', 'f',
                'kh', 'ts', 'ch', 'sh', 'shch', '', 'iu', 'ia', 'y', 'e', 'e', '']))


def latin(text):
    return ''.join(CYR.get(c.lower(), c.lower()) for c in text)


def is_owner(entry, owner_marks):
    blob = ' '.join(str(entry.get(k) or '') for k in ('name_or_handle', 'basis', 'role')).lower()
    return any(m in blob for m in owner_marks) or 'account owner' in blob or 'account_owner' in blob


def redaction_terms(digest, owner_marks, allow):
    terms = set()
    for entry in digest.get('people_named') or []:
        if not isinstance(entry, dict) or is_owner(entry, owner_marks):
            continue
        name = str(entry.get('name_or_handle') or '')
        if any(a in name.lower() or a in latin(name) for a in allow):
            continue
        for handle in re.findall(r'@[\w.]+', name):
            terms.add(handle)
        plain = re.sub(r'\(.*?\)|@[\w.]+', ' ', name).strip()
        for token in re.findall(r'[A-ZА-ЯЁІЇЄҐ][\w\'’-]{2,}', plain):
            terms.update({token, latin(token).capitalize()})
    return sorted(terms, key=len, reverse=True)


def redact(text, terms, own_handles, allow):
    for term in terms:
        text = re.sub(r'(?<![\w@])' + re.escape(term) + r'(?![\w])', '[name withheld]', text)
    keep = lambda m: m[0] if m[0].lower().lstrip('@') in own_handles or any(a in m[0].lower() for a in allow) else '[account withheld]'
    return re.sub(r'@[\w.]+', keep, text)


def sentences(text, n=2):
    parts = re.split(r'(?<=[.!?])\s+', (text or '').strip())
    return ' '.join(parts[:n])


def words(text, limit=20):
    w = (text or '').split()
    return ' '.join(w[:limit]) + ('…' if len(w) > limit else '')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wiki', type=Path, required=True)
    parser.add_argument('--private', type=Path, required=True, help='Directory with items.jsonl and digests.jsonl')
    parser.add_argument('--owner-marks', required=True, help='Comma-separated lower-case markers of the creator (name stems in each script, e.g. "name,имя")')
    parser.add_argument('--own-handles', help="Comma-separated handles of the creator's own accounts (default: the wiki folder name)")
    parser.add_argument('--allow', default='', help='Comma-separated lower-case names/handles of public collaborators that may be named')
    parser.add_argument('--withhold', default='', help='Comma-separated extra names to withhold everywhere (found on review)')
    args = parser.parse_args()
    extra = [w.strip() for w in args.withhold.split(',') if w.strip()]
    owner_marks = [m.strip() for m in args.owner_marks.split(',') if m.strip()]
    own_handles = {h.strip().lower() for h in (args.own_handles or args.wiki.resolve().name).split(',') if h.strip()}
    allow = [a.strip() for a in args.allow.split(',') if a.strip()]
    load = lambda name: {r['id']: r for r in map(json.loads, filter(str.strip, (args.private / name).read_text().split('\n')))}
    items, digests = load('items.jsonl'), load('digests.jsonl')
    cited = set()
    for page in args.wiki.glob('*.md'):
        cited |= {f'{p}:{i}' for p, i in LINK.findall(page.read_text())}
    out = args.wiki / 'sources'
    out.mkdir(exist_ok=True)
    missing = []
    for item_id in sorted(cited):
        item, d = items.get(item_id), digests.get(item_id)
        if not item or not d:
            missing.append(item_id)
            continue
        terms = sorted(set(redaction_terms(d, owner_marks, allow)) | set(extra), key=len, reverse=True)
        clean = lambda t: redact(t, terms, own_handles, allow)
        langs = d.get('languages') if isinstance(d.get('languages'), dict) else {}
        summary = d.get('summary') or ''
        lines = [f"# {item_id} · {LABEL[item['platform']]} ({item.get('kind') or 'item'})", '',
                 f"[Original]({item['url']}) · [Data room](../data-room.md) · [Overview](../index.md)", '',
                 f"**Published:** {item.get('published_at') or 'unknown'} · {item.get('date_basis') or ''}"]
        facts = []
        if d.get('duration_s'):
            facts.append(f"**Duration:** {round(d['duration_s'])} s")
        if langs.get('spoken'):
            facts.append('**Spoken:** ' + ', '.join(map(str, langs['spoken'])))
        if langs.get('written'):
            facts.append('**Written:** ' + ', '.join(map(str, langs['written'])))
        if item.get('collection'):
            facts.append(f"**Highlight:** {item['collection']}")
        if facts:
            lines += ['', ' · '.join(facts)]
        lines += ['', '**Review status:** machine observations from the media and written-voice analysis. Speech is attributed from the '
                  'account, narration and host role, not by voice or face. Names of other private people are withheld. Check the original before reuse.']
        if item.get('title'):
            lines += ['', f"**Title:** {clean(item['title'])}"]
        private = bool(PRIVATE.search(summary))
        lines += ['', '## Machine summary', '']
        if not summary:
            lines.append('No media analysis for this item; see the original and the data room.')
        elif private:
            lines.append('Withheld: the item touches private matters. Only the facts used on the wiki pages are relied on.')
        else:
            lines.append(clean(sentences(summary)))
        topics = [] if private else [str(t) for t in d.get('topics') or []][:6]
        offers = [str(o.get('name')) for o in d.get('offers') or [] if isinstance(o, dict) and o.get('name')][:4]
        if topics or offers:
            lines += ['', '## Topics and offers', '']
            if topics:
                lines.append('* Topics: ' + ', '.join(topics))
            if offers:
                lines.append('* Offers named: ' + clean('; '.join(offers)))
        quotes = [] if private else [p for p in d.get('phrases') or [] if isinstance(p, dict) and p.get('text')
                                     and any(m in str(p.get('speaker') or '').lower() for m in owner_marks + ['owner'])][:3]
        text = (item.get('text') or '').strip()
        if quotes or text:
            lines += ['', '## Her words (short excerpts)', '']
            if text:
                lines.append(f"* Text: «{clean(words(text))}»")
            for q in quotes:
                at = f" ({q['time']:.0f} s)" if isinstance(q.get('time'), (int, float)) else ''
                lines.append(f"* Speech{at}: «{clean(words(q['text']))}»")
        (out / f"{item_id.replace(':', '-')}.md").write_text('\n'.join(lines) + '\n')
    print(json.dumps({'notes': len(cited) - len(missing), 'missing': missing}, ensure_ascii=False))


if __name__ == '__main__':
    main()
