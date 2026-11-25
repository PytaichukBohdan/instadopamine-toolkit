#!/usr/bin/env python3
"""Count recurring words and multi-word expressions in a creator's own speech and writing.

Document frequency (distinct items), publication-year spread and platform spread are
computed for 1–5-word expressions, separately for SPEECH (owner speech in transcripts)
and WRITING (own captions/posts, forwards excluded). A distinctiveness score compares
each expression's rate with its rate in the other mode and penalises expressions made of
stop-words only. Counts describe this archive, not real-life frequency. No model calls.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

STOP = set('''и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее мне было вот от меня еще нет о из ему
теперь когда даже ну вдруг ли если уже или ни быть был него до вас нибудь опять уж вам ведь там потом себя ничего ей может они тут где есть надо
ней для мы тебя их чем была сам чтоб без будто чего раз тоже себе под будет ж тогда кто этот того потому этого какой совсем ним здесь этом один
почти мой тем чтобы нее сейчас были куда зачем всех никогда можно при наконец два об другой хоть после над больше тот через эти нас про всего них
какая много разве три эту моя впрочем хорошо свою этой перед иногда лучше чуть том нельзя такой им более всегда конечно всю между это эта эти
і та й що не на в у з до як за від по це ти ви ми він вона вони мене мені його її їх так але ж же би бо чи або щоб коли де там тут вже ще теж
the a an and or of to in is it for on with this that you i we be are was'''.split())
WORD = re.compile(r"[a-zа-яёіїєґ0-9ʼ'’-]+", re.I)


def tokens(text):
    return [t.strip("'’ʼ-").replace('ё', 'е') for t in WORD.findall(text.lower()) if t.strip("'’ʼ-")]


def owner_text(record, transcript_dir):
    """Owner speech: Whisper text when the item is owner-only, else owner-labelled machine segments."""
    a = record.get('analysis') or {}
    speakers = a.get('speakers') or []
    owner_labels = {s.get('label') for s in speakers if s.get('role') == 'account_owner'}
    others = [s for s in speakers if s.get('role') != 'account_owner' and (s.get('approx_share_pct') or 0) >= 5]
    if not owner_labels:
        return ''
    if not others:
        base = transcript_dir / record['item_id'].replace(':', '/')
        texts = [json.loads(p.read_text()).get('text') or '' for p in sorted(base.parent.glob(base.name + '-[0-9][0-9].json'))
                 if json.loads(p.read_text()).get('status') == 'transcribed']
        if any(texts):
            return ' '.join(texts)
    return ' '.join(s.get('text') or '' for s in a.get('transcript') or [] if s.get('speaker') in owner_labels or (not others and s.get('speaker') is None))


def ngrams(toks, n):
    return {' '.join(toks[i:i + n]) for i in range(len(toks) - n + 1)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private', type=Path, required=True)
    parser.add_argument('--analysis', type=Path, required=True)
    parser.add_argument('--transcripts', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--top', type=int, default=400)
    args = parser.parse_args()
    items = {i['id']: i for i in map(json.loads, filter(str.strip, (args.private / 'items.jsonl').read_text().split('\n')))}
    docs = {'speech': [], 'writing': []}
    for item in items.values():
        year = (item.get('published_at') or '')[:4] or 'undated'
        if item.get('text') and not item.get('forward'):
            docs['writing'].append((item['id'], item['platform'], year, tokens((item.get('title') or '') + ' ' + item['text'])))
        record_path = args.analysis / (item['id'].replace(':', '/') + '.json')
        if record_path.exists():
            record = json.loads(record_path.read_text())
            if record.get('status') == 'ok':
                speech = owner_text(record, args.transcripts)
                if speech.strip():
                    docs['speech'].append((item['id'], item['platform'], year, tokens(speech)))
    result = {'method': __doc__.strip().split('\n\n')[1].replace('\n', ' '), 'modes': {}}
    df = {mode: Counter() for mode in docs}
    meta = {mode: defaultdict(lambda: {'years': Counter(), 'platforms': Counter(), 'examples': []}) for mode in docs}
    for mode, rows in docs.items():
        for item_id, platform, year, toks in rows:
            seen = set()
            for n in range(1, 6):
                seen |= ngrams(toks, n)
            for g in seen:
                df[mode][g] += 1
                m = meta[mode][g]
                m['years'][year] += 1
                m['platforms'][platform] += 1
                if len(m['examples']) < 12:
                    m['examples'].append(item_id)
    for mode in docs:
        other = 'writing' if mode == 'speech' else 'speech'
        n_docs, n_other = max(1, len(docs[mode])), max(1, len(docs[other]))
        rows = []
        for g, count in df[mode].items():
            words = g.split()
            if count < 4 or all(w in STOP for w in words) or (len(words) == 1 and (len(g) < 4 or g.isdigit())):
                continue
            rate, other_rate = count / n_docs, (df[other][g] + 0.5) / n_other
            m = meta[mode][g]
            rows.append({'expression': g, 'words': len(words), 'items': count, 'share_of_items': round(rate, 4),
                         'years': dict(sorted(m['years'].items())), 'platforms': dict(m['platforms']),
                         'other_mode_items': df[other][g], 'lift_vs_other_mode': round(rate / other_rate, 2),
                         'score': round(count * (1 + 0.6 * (len(words) - 1)) * math.log(2 + len(m['years'])), 1), 'examples': m['examples']})
        rows.sort(key=lambda r: -r['score'])
        # Drop sub-expressions that almost always occur inside a longer kept expression.
        kept = []
        for r in rows:
            if any(r['expression'] in k['expression'] and k['items'] >= 0.85 * r['items'] for k in kept if k['words'] > r['words']):
                continue
            kept.append(r)
            if len(kept) >= args.top:
                break
        by_length = {}
        for n, label in [(1, 'words'), (2, 'two_word'), (3, 'three_word'), (4, 'four_plus')]:
            pool = [r for r in rows if (r['words'] == n if n < 4 else r['words'] >= 4)]
            by_length[label] = sorted(pool, key=lambda r: (-r['items'], r['expression']))[:150]
        result['modes'][mode] = {'documents': len(docs[mode]), 'top': kept, 'by_length': by_length}
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps({m: {'documents': v['documents'], **{k: [r['expression'] for r in rows[:15]] for k, rows in v['by_length'].items() if k != 'words'}}
                      for m, v in result['modes'].items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
