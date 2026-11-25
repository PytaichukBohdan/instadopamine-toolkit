#!/usr/bin/env python3
"""Signal measurements of a creator's recorded speech, per recording and aggregated.

Only recordings whose machine analysis attributes (nearly) all speech to the account
owner and finds no music bed are measured, so guests and soundtracks do not leak in.
Pitch comes from Praat (parselmouth) on the audio. Tempo and pauses come only from
Whisper word timestamps (an intensity threshold could not separate pauses in compressed
phone audio). Filler and question counts come from the best available transcript
(Whisper if present, otherwise the item's machine transcript). These describe this archive — they
are not a clinical or exhaustive voice profile. Requires praat-parselmouth and numpy.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_media_gemini import BUILDERS  # noqa: E402

VOWELS = re.compile(r'[аеёиоуыэюяіїєaeiouy]', re.I)
FILLERS = ['вот', 'ну', 'типа', 'короче', 'блин', 'как бы', 'да', 'то есть', 'в общем', 'просто', 'реально', 'кстати',
           'слушайте', 'смотрите', 'знаете', 'значит', 'кароче', 'ладно', 'окей']


LANGUAGES = {'rus': 'ru', 'russian': 'ru', 'ukr': 'uk', 'ukrainian': 'uk', 'eng': 'en', 'english': 'en'}


def owner_only(analysis):
    speakers = analysis.get('speakers') or []
    owner = sum((s.get('approx_share_pct') or 0) for s in speakers if s.get('role') == 'account_owner')
    others = [s for s in speakers if s.get('role') != 'account_owner' and (s.get('approx_share_pct') or 0) >= 5]
    audio = analysis.get('audio') if isinstance(analysis.get('audio'), dict) else {}
    music = audio.get('music') if isinstance(audio.get('music'), dict) else {}
    music = music.get('present')
    return owner >= 90 and not others and not music


def load(path):
    import numpy as np
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-vn', '-f', 's16le', '-ac', '1', '-ar', '16000', '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float64) / 32768


def measure(job):
    import numpy as np
    import parselmouth
    try:
        samples = load(job['path'])
    except subprocess.CalledProcessError:  # no decodable audio stream
        return None
    if len(samples) < 16000 * 3:
        return None
    sound = parselmouth.Sound(samples, sampling_frequency=16000)
    pitch = sound.to_pitch_ac(time_step=0.01, pitch_floor=110, pitch_ceiling=500)
    f0 = pitch.selected_array['frequency']
    f0 = f0[f0 > 0]
    if len(f0) < 100:
        return None
    semis = 12 * np.log2(f0 / np.median(f0))
    # Tempo and pauses need reliable word timing (Whisper); machine-transcript items get pitch and fillers only.
    words = [w for w in job.get('words') or [] if w.get('end', 0) > w.get('start', 0)]
    if len(words) >= 15:
        gaps = [b['start'] - a['end'] for a, b in zip(words, words[1:])]
        pauses = [g for g in gaps if g >= 0.25]
        voiced = sum(w['end'] - w['start'] for w in words) + sum(g for g in gaps if 0 < g < 0.25)
        span = words[-1]['end'] - words[0]['start']
    else:
        pauses, voiced, span = None, None, None
    text = job['text'].lower()
    tokens = re.findall(r"[\wʼ'’-]+", text)
    if len(tokens) < 15:
        return None
    syllables = sum(max(1, len(VOWELS.findall(t))) for t in tokens)
    fillers = {f: len(re.findall(r'(?<![\w])' + re.escape(f) + r'(?![\w])', text)) for f in FILLERS}
    return {'item_id': job['item_id'], 'platform': job['platform'], 'kind': job['kind'], 'published_at': job['published_at'],
            'language': job['language'], 'transcript_source': job['source'], 'duration_s': round(sound.duration, 2), 'words': len(tokens),
            'f0_median_hz': round(float(np.median(f0)), 1), 'f0_p10_hz': round(float(np.percentile(f0, 10)), 1),
            'f0_p90_hz': round(float(np.percentile(f0, 90)), 1),
            'f0_range_semitones_p10_p90': round(float(np.percentile(semis, 90) - np.percentile(semis, 10)), 2),
            'timing_source': 'word timestamps' if voiced else None,
            'words_per_minute_voiced': round(60 * len(words) / voiced, 1) if voiced else None,
            'syllables_per_second_voiced': round(sum(max(1, len(VOWELS.findall(w['word']))) for w in words) / voiced, 2) if voiced else None,
            'pauses_per_minute': round(60 * len(pauses) / span, 1) if voiced and span else None,
            'median_pause_s': round(statistics.median(pauses), 2) if pauses else None,
            'pauses_over_1s_per_minute': round(60 * sum(p >= 1 for p in pauses) / span, 2) if voiced and span else None,
            'fillers_per_100_words': {k: round(100 * v / len(tokens), 2) for k, v in fillers.items() if v},
            'questions_per_100_words': round(100 * text.count('?') / len(tokens), 2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', action='append', required=True, help='platform=path, e.g. instagram=/private/ig')
    parser.add_argument('--analysis', type=Path, required=True)
    parser.add_argument('--transcripts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='Private per-recording measurements')
    parser.add_argument('--summary', type=Path, required=True, help='Aggregates for the wiki')
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--regroup', action='store_true', help='Re-aggregate existing --output measurements without re-measuring')
    args = parser.parse_args()
    jobs = []
    for spec in args.corpus:
        platform, root = spec.split('=', 1)
        for item in BUILDERS[platform](Path(root), ''):
            timed = [m for m in item['media'] if m['kind'] in {'video', 'audio'}]
            record_path = args.analysis / (item['item_id'].replace(':', '/') + '.json')
            if len(timed) != 1 or not record_path.exists():
                continue
            record = json.loads(record_path.read_text())
            analysis = record.get('analysis') or {}
            if record.get('status') != 'ok' or not owner_only(analysis):
                continue
            base = args.transcripts / item['item_id'].replace(':', '/')
            whisper = base.with_name(f"{base.name}-{timed[0]['index']:02d}.json")
            w = json.loads(whisper.read_text()) if whisper.exists() else {}
            if w.get('status') == 'transcribed' and w.get('model', 'whisper-1').startswith(('whisper', 'faster-whisper')):
                text, source, language, words = w.get('text') or '', w.get('model', 'whisper-1'), w.get('language'), w.get('words')
            else:
                words = None
                text = ' '.join(s.get('text') or '' for s in analysis.get('transcript') or [] if s.get('speaker') is None or 'guest' not in str(s.get('speaker')).lower())
                source = record['provenance'].get('model', 'gemini') + ' item transcript'
                languages = analysis.get('languages')
                spoken = languages.get('spoken') if isinstance(languages, dict) else languages if isinstance(languages, list) else None
                language = (spoken or [None])[0]
            jobs.append({'item_id': item['item_id'], 'platform': record['platform'], 'kind': record['kind'], 'published_at': record.get('published_at'),
                         'path': timed[0]['path'], 'text': text, 'source': source, 'language': language, 'words': words})
    if args.regroup:
        rows = json.loads(args.output.read_text())
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            rows = [r for r in pool.map(measure, jobs, chunksize=4) if r]
        args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + '\n')
    groups = defaultdict(list)
    for r in rows:
        groups[('all', 'all')].append(r)
        groups[('platform', r['platform'])].append(r)
        groups[('format', f"{r['platform']}:{r['kind']}")].append(r)
        groups[('year', (r['published_at'] or 'undated')[:4])].append(r)
        language = str(r['language'] or 'unknown').lower()
        groups[('language', LANGUAGES.get(language, language))].append(r)

    def agg(items):
        def med(key):
            values = [x[key] for x in items if x.get(key) is not None]
            return round(statistics.median(values), 2) if values else None
        filler = Counter()
        for x in items:
            for k, v in x['fillers_per_100_words'].items():
                filler[k] += v * x['words'] / 100
        words = sum(x['words'] for x in items)
        return {'recordings': len(items), 'minutes': round(sum(x['duration_s'] for x in items) / 60, 1), 'words': words,
                **{k: med(k) for k in ['f0_median_hz', 'f0_p10_hz', 'f0_p90_hz', 'f0_range_semitones_p10_p90', 'words_per_minute_voiced',
                                       'syllables_per_second_voiced', 'pauses_per_minute', 'median_pause_s', 'pauses_over_1s_per_minute']},
                'timed_recordings': sum(1 for x in items if x.get('timing_source')),
                'questions_per_100_words_pooled': round(sum(x['questions_per_100_words'] * x['words'] for x in items) / max(1, words), 2),
                'fillers_per_100_words': {k: round(100 * v / max(1, words), 2) for k, v in filler.most_common(12)}}

    summary = {'method': 'Owner-only recordings without a music bed. Praat autocorrelation pitch 110–500 Hz at 10 ms on every recording. '
                         'Tempo and pauses (gaps ≥0.25 s between words) only where Whisper word timestamps exist. Filler and question '
                         'rates from automatic transcripts (Whisper where available, otherwise the per-item machine transcript). Machine measurements only.',
               'transcript_sources': dict(Counter(r['transcript_source'] for r in rows)),
               'groups': {f'{a}:{b}': agg(v) for (a, b), v in sorted(groups.items())}}
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps(summary['groups'].get('all:all'), ensure_ascii=False))


if __name__ == '__main__':
    main()
