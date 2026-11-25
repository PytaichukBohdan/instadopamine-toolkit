#!/usr/bin/env python3
"""Build a person's static passport review page from people/<slug>/selection.json.

usage: build_site.py --person people/<slug> [--out work/<slug>/site]

Publishes only the selected version of each job (WebP preview + original PNG), the expanded prompt
texts and the identity spec. Owner reference photos/videos are never copied into the site.
"""
import argparse, html, json, shutil, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen import REPO, Person  # noqa: E402


def esc(s):
    return html.escape(s, quote=True)


def spec_html(person):
    rows = []
    for line in (person.prompts / '_identity.md').read_text().strip().splitlines():
        head, sep, body = line.partition(': ')
        if not sep or head.upper() == person.cfg['name'].upper():
            continue
        head = head.split(' (')[0]
        rows.append(f'<div class="spec-row"><dt>{esc(head.title())}</dt><dd>{esc(body)}</dd></div>')
    return '\n'.join(rows)


def card(item, row):
    stem = Path(item['file']).stem
    notes = ''.join(f'<li>{esc(n)}</li>' for n in item.get('notes', []))
    return f'''
<article class="card {esc(item.get('size', ''))}" id="{esc(row['job'])}">
  <a class="shot" href="full/{esc(item['file'])}"><img src="img/{esc(stem)}.webp" alt="{esc(item['title'])} (AI-generated likeness)" loading="lazy" width="{row['width']}" height="{row['height']}"></a>
  <div class="meta">
    <h3>{esc(item['title'])}</h3>
    <p class="use"><strong>Use for:</strong> {esc(item['use'])}</p>
    <ul class="notes">{notes}</ul>
    <p class="small"><a href="full/{esc(item['file'])}">Full PNG {row['width']}×{row['height']}</a> · <a href="prompts/{esc(row['job'])}.txt">Prompt</a></p>
  </div>
</article>'''


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--person', required=True)
    ap.add_argument('--out')
    a = ap.parse_args()
    person = Person(a.person)
    sel = json.loads((person.dir / 'selection.json').read_text())
    rows = {json.loads(l)['file']: json.loads(l) for l in (person.out / 'manifest.jsonl').read_text().splitlines() if l.strip()}
    site = REPO / (a.out or f"work/{person.cfg['slug']}/site")
    if site.exists():
        shutil.rmtree(site)
    for d in ('img', 'full', 'prompts'):
        (site / d).mkdir(parents=True)
    selected = [i['file'] for sec in sel['sections'] for i in sec['items']]
    jobs = set()
    for f in selected:
        row = rows[f]
        shutil.copy2(person.out / f, site / 'full' / f)
        shutil.copy2(person.out / row['thumbnail'], site / 'img' / row['thumbnail'])
        jobs.add(row['job'])
    for job in jobs:
        (site / 'prompts' / f'{job}.txt').write_text(person.render(person.jobs[job]['prompt']) + '\n')
    sections = []
    for sec in sel['sections']:
        if not sec['items']:
            continue
        cards = ''.join(card(i, rows[i['file']]) for i in sec['items'])
        sections.append(f'<section id="{esc(sec["id"])}"><h2>{esc(sec["title"])}</h2><p class="lede">{esc(sec["lede"])}</p><div class="grid">{cards}</div></section>')
    nav = ''.join(f'<a href="#{esc(s["id"])}">{esc(s["nav"])}</a>' for s in sel['sections'] if s['items'])
    lis = lambda key, raw=False: ''.join(f'<li>{m if raw else esc(m)}</li>' for m in sel.get(key, []))
    hero = rows[sel['hero']]
    page = (REPO / 'passport' / 'site_template.html').read_text()
    for k, v in {'{{NAME}}': esc(person.cfg['name']), '{{VERSION}}': esc(sel.get('version', 'v1')),
                 '{{SUMMARY}}': esc(sel['summary']), '{{NAV}}': nav, '{{HERO_IMG}}': 'img/' + esc(hero['thumbnail']),
                 '{{HERO_FULL}}': 'full/' + esc(hero['file']), '{{SPEC}}': spec_html(person), '{{SECTIONS}}': '\n'.join(sections),
                 '{{METHOD}}': lis('method', raw=True), '{{LIMITS}}': lis('limits'), '{{PENDING}}': lis('pending') or '<li>Nothing pending.</li>',
                 '{{COUNT}}': str(len(selected)), '{{TOTAL}}': str(len(rows)), '{{DATE}}': esc(sel['date'])}.items():
        page = page.replace(k, v)
    (site / 'index.html').write_text(page)
    (site / 'robots.txt').write_text('User-agent: *\nDisallow: /\n')
    (site / '_headers').write_text('/*\n  X-Robots-Tag: noindex, nofollow, noarchive\n  Referrer-Policy: no-referrer\n')
    print(f'site: {site} ({len(selected)} images, {len(jobs)} prompts)')


if __name__ == '__main__':
    main()
