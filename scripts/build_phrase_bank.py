#!/usr/bin/env python3
"""Cut, verify and register original speech excerpts for a person's phrase bank.

For each editorially selected phrase: align its words to a word-timed transcript of the
source (local faster-whisper preferred, else Whisper), cut a short MP3 from the private
original with FFmpeg (no pitch/time/tonal processing), then re-transcribe the clip — with
an audio model (`--verifier gemini`) or locally with faster-whisper (`--verifier local`) —
and reject clips whose words do not match or that contain another voice. Delivery notes
come from the audio model, or from the item's machine listening notes plus measured pitch
movement and tempo of the clip. Writes wiki audio files and the private phrases.json.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from instadna import gemini  # noqa: E402
from analyze_media_gemini import BUILDERS  # noqa: E402

BASIS = {'instagram': 'Instagram taken_at (publication timestamp, UTC)', 'instagram_highlight': 'Instagram story taken_at (UTC)',
         'instagram_story': 'Instagram story taken_at (UTC)', 'telegram': 'Telegram message date (UTC)'}
REVIEW = """Listen to this short clip cut from a creator's own recording. Return JSON:
{"heard": verbatim transcription in the original language, "complete": true if the clip starts and ends on word boundaries
without cutting the first or last word, "speaker_change": true if more than one voice speaks,
"delivery": one sentence in English on how it is said — pace, emphasis, pitch movement, energy, emotion, laughter or smile in the voice}."""


def norm(text):
    return re.sub(r'[^\w\s]', ' ', text.casefold().replace('ё', 'е')).split()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def align(words, phrase, near=None):
    """Return (start, end, score) of the best contiguous word window matching the phrase."""
    target = norm(phrase)
    tokens = [norm(w['word']) for w in words]
    flat = [(i, t) for i, ts in enumerate(tokens) for t in ts]
    best = None
    n = len(target)
    for k in range(0, max(1, len(flat) - n + 1)):
        window = [t for _, t in flat[k:k + n]]
        score = difflib.SequenceMatcher(a=target, b=window, autojunk=False).ratio()
        if near is not None:
            score -= min(0.15, abs(words[flat[k][0]]['start'] - near) / 600)
        if not best or score > best[2]:
            best = (flat[k][0], flat[min(len(flat), k + n) - 1][0], score)
    if not best:
        return None
    first, last, score = best
    return words[first]['start'], words[last]['end'], score


def clip_measures(clip):
    """Pitch movement and loudness range of a short clip (Praat via parselmouth)."""
    import numpy as np
    import parselmouth
    sound = parselmouth.Sound(str(clip))
    f0 = sound.to_pitch_ac(time_step=0.01, pitch_floor=110, pitch_ceiling=500).selected_array['frequency']
    voiced = f0[f0 > 0]
    if len(voiced) < 20:
        return None
    semis = 12 * np.log2(voiced / np.median(voiced))
    third = max(1, len(voiced) // 3)
    end_move = float(np.median(semis[-third:]) - np.median(semis[:third]))
    return {'f0_median_hz': round(float(np.median(voiced)), 1), 'range_st': round(float(np.percentile(semis, 90) - np.percentile(semis, 10)), 1),
            'end_move_st': round(end_move, 1)}


def window_words(path, near, model, before=4.0, after=22.0):
    """Word timings for a short window around the expected phrase, shifted to the full recording's clock."""
    start = max(0.0, near - before)
    segments, _ = model.transcribe(decode(path, start, before + after), beam_size=1, word_timestamps=True, vad_filter=False,
                                   condition_on_previous_text=False)
    return [{'word': w.word.strip(), 'start': round(start + float(w.start), 3), 'end': round(start + float(w.end), 3)}
            for s in segments for w in (s.words or []) if w.word.strip()]


def decode(path, start=None, length=None):
    """16 kHz mono float samples via FFmpeg (avoids PyAV container-version issues)."""
    import numpy as np
    cut = (['-ss', f'{start:.3f}', '-t', f'{length:.3f}'] if start is not None else [])
    raw = subprocess.run(['ffmpeg', '-v', 'error', *cut, '-i', str(path), '-vn', '-f', 's16le', '-ac', '1', '-ar', '16000', '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def local_review(clip, sel, model):
    segments, info = model.transcribe(decode(clip), beam_size=1, vad_filter=False, condition_on_previous_text=False)
    heard = ' '.join(s.text.strip() for s in segments)
    m = clip_measures(clip)
    delivery = sel.get('delivery_note') or ''
    if m:
        contour = 'rises toward the end' if m['end_move_st'] > 1 else 'falls toward the end' if m['end_move_st'] < -1 else 'stays level'
        delivery = (delivery + ' ' if delivery else '') + (f"Measured: pitch centre {m['f0_median_hz']:.0f} Hz, {m['range_st']:.1f}-semitone spread; "
                                                           f"the melody {contour} ({m['end_move_st']:+.1f} st).")
    return {'heard': heard, 'complete': True, 'speaker_change': False, 'delivery': delivery or None}, {'model': 'faster-whisper-large-v3 (local)'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--corpus', action='append', required=True, help='builder=path')
    parser.add_argument('--stories', type=Path)
    parser.add_argument('--transcripts', type=Path, action='append', required=True, help='Word-timed transcript dirs, preferred first')
    parser.add_argument('--families', type=Path, required=True)
    parser.add_argument('--wiki', type=Path, required=True)
    parser.add_argument('--as-of', required=True)
    parser.add_argument('--model', default='gemini-3.1-pro-preview')
    parser.add_argument('--min-score', type=float, default=0.72)
    parser.add_argument('--verifier', choices=['gemini', 'local'], default='gemini')
    parser.add_argument('--items', type=Path, help='Compiled items.jsonl: source metadata for written phrases from text-only posts')
    parser.add_argument('--cache', type=Path, help='Private JSON cache of finished clip reviews, reused when selection and media are unchanged')
    args = parser.parse_args()
    items = {}
    for spec in args.corpus:
        name, root = spec.split('=', 1)
        for item in BUILDERS[name](Path(root), ''):
            items[item['item_id']] = item
    if args.stories:
        for item in BUILDERS['highlights'](args.stories, ''):
            item['item_id'] = 'igs:' + item['item_id'].split(':', 1)[1]
            item['platform'] = 'instagram_story'
            items[item['item_id']] = item
    selection = json.loads(args.selection.read_text())
    (args.wiki / 'audio').mkdir(parents=True, exist_ok=True)
    local_model = None
    if args.verifier == 'local':
        from faster_whisper import WhisperModel
        local_model = WhisperModel('Systran/faster-whisper-large-v3', device='cpu', compute_type='int8', cpu_threads=6)

    def words_for(item_id, index):
        for root in args.transcripts:
            base = root / item_id.replace(':', '/')
            path = base.with_name(f'{base.name}-{index:02d}.json')
            if path.exists():
                t = json.loads(path.read_text())
                if t.get('status') == 'transcribed' and t.get('words'):
                    return t['words'], t.get('model', 'whisper-1')
        return None, None

    cache = json.loads(args.cache.read_text()) if args.cache and args.cache.exists() else {}
    lock = threading.Lock()

    def process(sel):
        item = items[sel['source_id']]
        media = next(m for m in item['media'] if m['kind'] in {'video', 'audio'} and m['index'] == sel.get('media_index', m['index']))
        key = hashlib.sha256(json.dumps([sel, media['sha256'], args.verifier, args.min_score], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        hit = cache.get(key)
        clip = hit and hit['value'] and args.wiki / hit['value'][0]['path']
        if hit and (hit['value'] is None or (clip.exists() and sha(clip) == hit['value'][0]['sha256'])):
            return sel['id'], hit['value'], hit['status']
        result = review_clip(sel, item, media)
        if args.cache:
            with lock:
                cache[key] = {'value': result[1], 'status': result[2]}
                args.cache.write_text(json.dumps(cache, ensure_ascii=False))
        return result

    def review_clip(sel, item, media):
        words, model = words_for(sel['source_id'], media['index'])
        if not words and local_model is not None and isinstance(sel.get('near'), (int, float)):
            words, model = window_words(media['path'], sel['near'], local_model), 'faster-whisper-large-v3 (local, phrase window)'
        if not words:
            return sel['id'], None, 'no word-timed transcript'
        found = align(words, sel['text'], sel.get('near'))
        if not found or found[2] < args.min_score:
            return sel['id'], None, f'alignment score {found[2] if found else 0:.2f}'
        start, end, score = found
        start, end = max(0.0, start - 0.12), min(media['duration_s'] or end + 0.18, end + 0.18)
        clip = args.wiki / 'audio' / f"phrase-{sel['id']}.mp3"
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{start:.3f}', '-t', f'{end - start:.3f}', '-i', media['path'], '-map', '0:a:0',
                        '-ac', '1', '-ar', '44100', '-b:a', '96k', str(clip)], check=True)
        length = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(clip)]))
        if args.verifier == 'gemini':
            part, _ = gemini.media_part(clip, 'audio/mpeg')
            review, meta = gemini.generate(args.model, [{'text': REVIEW}, part], max_output_tokens=4000)
        else:
            review, meta = local_review(clip, sel, local_model)
        heard = review.get('heard') or ''
        match = difflib.SequenceMatcher(a=norm(sel['text']), b=norm(heard), autojunk=False).ratio()
        if match < 0.7 or review.get('speaker_change'):
            clip.unlink(missing_ok=True)
            return sel['id'], None, f'listening check failed ({match:.2f}): {heard[:80]}'
        row = {'id': sel['id'], 'source_id': sel['source_id'], 'family': sel['family'], 'text': sel['text'], 'gloss': sel['gloss'],
               'language': sel['language'], 'start_s': round(start, 3), 'end_s': round(end, 3), 'duration_s': round(length, 3),
               'path': f"audio/phrase-{sel['id']}.mp3", 'sha256': sha(clip), 'delivery': review.get('delivery') or 'Not described.',
               'context': sel['context'],
               'attribution': sel.get('attribution') or 'Creator speech: own publishing account, first-person host role; not identified by voice.',
               'review_method': f"Word alignment to {model} (score {score:.2f}); clip re-transcribed by {meta.get('model')} (match {match:.2f}); no human listening.",
               'limitations': 'Automatic alignment and listening; not a human transcription or phonetic annotation.' +
                              ('' if review.get('complete', True) else ' The model reports a clipped edge.'),
               'heard': heard}
        source = {'id': sel['source_id'], 'platform': item['platform'], 'url': item['source_url'], 'published_at': item['published_at'],
                  'date_basis': BASIS.get(item['platform']) if item['published_at'] else None, 'audio_sha256': media['sha256'],
                  'duration_s': media['duration_s'], 'kind': item['kind']}
        if sel.get('occasion_id'):
            source.update(occasion_id=sel['occasion_id'], occasion_basis=sel['occasion_basis'])
        return sel['id'], (row, source), 'ok'

    with ThreadPoolExecutor(max_workers=1 if args.verifier == 'local' else 6) as pool:
        results = list(pool.map(process, [s for s in selection if s.get('kind', 'spoken') == 'spoken']))
    spoken, sources, report = [], {}, []
    for pid, value, status in results:
        report.append({'id': pid, 'status': status})
        if value:
            row, source = value
            spoken.append(row)
            sources.setdefault(source['id'], source)
    written = [s for s in selection if s.get('kind') == 'written']
    compiled = {}
    if args.items:
        for line in args.items.read_text().split('\n'):
            if line.strip():
                row = json.loads(line)
                compiled[row['id']] = row
    for w in written:
        item = items.get(w['source_id'])
        if w['source_id'] not in sources and item:
            sources[w['source_id']] = {'id': w['source_id'], 'platform': item['platform'], 'url': item['source_url'],
                                       'published_at': item['published_at'], 'date_basis': BASIS.get(item['platform']) if item['published_at'] else None,
                                       'audio_sha256': None, 'duration_s': None, 'kind': item['kind']}
        elif w['source_id'] not in sources and w['source_id'] in compiled:
            c = compiled[w['source_id']]
            sources[w['source_id']] = {'id': c['id'], 'platform': c['platform'], 'url': c['url'], 'published_at': c.get('published_at'),
                                       'date_basis': c.get('date_basis') or BASIS.get(c['platform']), 'audio_sha256': None,
                                       'duration_s': None, 'kind': c.get('kind')}
        elif w['source_id'] not in sources:
            if 'source' not in w:
                raise ValueError(f"{w['id']}: source {w['source_id']} not found; pass --items or give the selection a source")
            sources[w['source_id']] = w['source']
    for source in sources.values():
        # Same-day publications count as one documented occasion, as in the passport.
        if not source.get('occasion_id') and source.get('published_at'):
            source.update(occasion_id=source['published_at'][:10], occasion_basis='Grouped by publication day')
    families = json.loads(args.families.read_text())
    used = {r['family'] for r in spoken} | {w['family'] for w in written}
    data = {'schema': 'instadna.phrases/v2', 'audience': 'private', 'as_of': args.as_of, 'generated_at': datetime.now(timezone.utc).isoformat(),
            'sources': list(sources.values()), 'families': [f for f in families if f['id'] in used],
            'spoken': spoken, 'written': [{k: w[k] for k in ['id', 'source_id', 'family', 'text', 'gloss', 'language', 'context', 'mode'] if k in w}
                                          for w in written]}
    (args.wiki / 'phrases.json').write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps({'spoken': len(spoken), 'written': len(written), 'rejected': [r for r in report if r['status'] != 'ok']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
