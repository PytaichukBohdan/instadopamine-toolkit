#!/usr/bin/env python3
"""Word-level timing for a known script, in pdoom-video's data/lyrics.json layout.

The script text is authoritative: local faster-whisper word timestamps only supply the
times. ASR tokens are matched to script tokens after normalisation; script tokens the
recogniser heard differently (numerals, hyphenation) take their time from the unmatched
ASR span between the matched neighbours, split by character length, and are flagged
`interp`. Standalone punctuation joins the preceding token, so every `w` is a display
token. Runs offline (no API); set HF_HOME to the model cache. Also writes a small
envelope file in the engine's data/audio.json layout: voice RMS at 100 fps, word onsets
and a provisional beat grid (there is no music bed yet).
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

PUNCT_ONLY = re.compile(r'^[\W_]+$')


def norm(token):
    return re.sub(r'[^\w-]', '', token.lower().replace('ё', 'е')).strip('-')


def script_tokens(lines):
    out = []
    for li, line in enumerate(lines):
        words = []
        for raw in line['text'].split():
            if PUNCT_ONLY.match(raw) and words:
                words[-1] += ' ' + raw
            else:
                words.append(raw)
        out.extend({'line': li, 'w': w, 'key': norm(w)} for w in words)
    return out


def decode(path, rate=16000):
    import numpy as np
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-vn', '-f', 's16le', '-ac', '1', '-ar', str(rate), '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def recognise(audio, model_name, language, threads):
    from faster_whisper import WhisperModel
    model = WhisperModel(model_name, device='cpu', compute_type='int8', cpu_threads=threads)
    segments, _ = model.transcribe(audio, language=language, beam_size=5, word_timestamps=True,
                                   condition_on_previous_text=False)
    heard = []
    for seg in segments:
        for w in seg.words:
            text = w.word.strip()
            # split hyphen-free multiword tokens are rare; keep ASR tokens as they come
            heard.append({'w': text, 'key': norm(text), 'start': float(w.start), 'end': float(w.end), 'p': float(w.probability)})
    return [h for h in heard if h['key']]


def align(tokens, heard):
    """Assign start/end to every script token; returns (tokens, stats)."""
    match = difflib.SequenceMatcher(a=[t['key'] for t in tokens], b=[h['key'] for h in heard], autojunk=False)
    stats = {'matched': 0, 'interpolated': 0, 'asr_tokens': len(heard), 'script_tokens': len(tokens), 'diffs': []}
    for op, i1, i2, j1, j2 in match.get_opcodes():
        if op == 'equal':
            for k in range(i2 - i1):
                h = heard[j1 + k]
                tokens[i1 + k].update(start=h['start'], end=h['end'], conf=round(h['p'], 3))
                stats['matched'] += 1
            continue
        if op == 'insert':
            stats['diffs'].append({'script': '', 'heard': ' '.join(h['w'] for h in heard[j1:j2])})
            continue
        span = tokens[i1:i2]
        stats['diffs'].append({'script': ' '.join(t['w'] for t in span), 'heard': ' '.join(h['w'] for h in heard[j1:j2])})
        if j2 > j1:
            t0, t1 = heard[j1]['start'], heard[j2 - 1]['end']
        else:  # nothing heard: squeeze between neighbours
            t0 = heard[j1 - 1]['end'] if j1 > 0 else 0.0
            t1 = heard[j1]['start'] if j1 < len(heard) else t0 + 0.3 * len(span)
        weights = [max(1, len(t['key'])) for t in span]
        total, acc = sum(weights), 0
        for t, wgt in zip(span, weights):
            t['start'] = t0 + (t1 - t0) * acc / total
            acc += wgt
            t['end'] = t0 + (t1 - t0) * acc / total
            t['conf'] = 0.0
            t['interp'] = True
            stats['interpolated'] += 1
    return tokens, stats


def snap_to_voice(tokens, audio, rate, floor_db, frame=0.01):
    """Move word edges that ASR placed inside silence onto the nearest voiced 10 ms frame.

    Whisper word timestamps often span a pause (a word "starts" where the previous one ended), which would
    show a caption before the word is spoken. Starts move forward and ends move back, within the word's own
    span; a word that contains a pause of 120 ms or more keeps only its more voiced side. Words stay in
    order and at least 60 ms long. Returns how many edges moved."""
    import numpy as np
    n = int(frame * rate)
    count = len(audio) // n
    db = 20 * np.log10(np.sqrt(np.mean(audio[:count * n].reshape(count, n) ** 2, axis=1)) + 1e-9)
    voiced = db >= floor_db
    moved, previous_end = 0, 0.0
    for t in tokens:
        a, b = int(t['start'] / frame), min(int(t['end'] / frame), count - 1)
        if a < b and not voiced[a]:
            hit = next((k for k in range(a, b) if voiced[k]), None)
            if hit is not None:
                t['start'], moved = hit * frame, moved + 1
        a = int(t['start'] / frame)
        if a < b and not voiced[b]:
            hit = next((k for k in range(b, a, -1) if voiced[k]), None)
            if hit is not None:
                t['end'], moved = (hit + 1) * frame, moved + 1
        # a word never contains a pause of 120 ms or more: keep the side of the pause with more voice
        a, b = int(t['start'] / frame), min(int(t['end'] / frame), count - 1)
        runs, k = [], a
        while k < b:
            if not voiced[k]:
                j = k
                while j < b and not voiced[j]:
                    j += 1
                if (j - k) * frame >= 0.12:
                    runs.append((k, j))
                k = j
            else:
                k += 1
        if runs:
            first, last = runs[0][0], runs[-1][1]
            if voiced[last:b + 1].sum() >= voiced[a:first].sum():
                t['start'] = last * frame
            else:
                t['end'] = first * frame
            moved += 1
        t['start'] = max(t['start'], previous_end)
        t['end'] = max(t['end'], t['start'] + 0.06)
        previous_end = t['end']
    return moved


def envelopes(audio, rate, fps=100):
    import numpy as np
    hop = rate // fps
    win = int(rate * 0.046)
    padded = np.pad(audio, (win // 2, win // 2))
    n = len(audio) // hop
    rms = np.array([np.sqrt(np.mean(padded[i * hop:i * hop + win] ** 2)) for i in range(n)])
    smooth = np.zeros_like(rms)
    up, down = 1 - np.exp(-1 / (0.010 * fps)), 1 - np.exp(-1 / (0.090 * fps))
    for i, v in enumerate(rms):
        prev = smooth[i - 1] if i else 0.0
        smooth[i] = prev + (v - prev) * (up if v > prev else down)
    ref = np.percentile(smooth, 99) or 1.0
    return [round(float(x), 3) for x in np.clip(smooth / ref, 0, 1)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--script', type=Path, required=True, help='JSON with lines[].text (the authoritative words)')
    parser.add_argument('--lyrics', type=Path, required=True, help='Output: engine lyrics.json')
    parser.add_argument('--envelope', type=Path, help='Output: engine audio.json (voice envelope, provisional grid)')
    parser.add_argument('--bpm', type=float, default=120.0, help='Provisional beat grid until a music bed exists')
    parser.add_argument('--language', default='ru')
    parser.add_argument('--model', default='Systran/faster-whisper-large-v3')
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--snap-db', type=float, help='Snap word edges out of silence below this level (e.g. -45); off by default')
    args = parser.parse_args()

    script = json.loads(args.script.read_text())
    lines = script['lines']
    audio = decode(args.audio)
    heard = recognise(audio, args.model, args.language, args.threads)
    tokens, stats = align(script_tokens(lines), heard)
    if args.snap_db is not None:
        stats['snapped_edges'] = snap_to_voice(tokens, audio, 16000, args.snap_db)
    out_lines = []
    for li, line in enumerate(lines):
        words = [{'w': t['w'], 'start': round(t['start'], 3), 'end': round(t['end'], 3), 'conf': t['conf'], **({'interp': True} if t.get('interp') else {})}
                 for t in tokens if t['line'] == li]
        out_lines.append({'i': li, 'text': line['text'], 'start': words[0]['start'], 'end': words[-1]['end'], 'words': words})
    duration = len(audio) / 16000
    source = {'audio': args.audio.name, 'audio_sha256': hashlib.sha256(args.audio.read_bytes()).hexdigest(),
              'script': args.script.name, 'model': args.model, 'language': args.language,
              'generated_at': datetime.now(timezone.utc).isoformat(), 'duration_s': round(duration, 3)}
    notes = ('Script words are authoritative; times from local faster-whisper word timestamps. '
             f"{stats['matched']} of {stats['script_tokens']} tokens matched directly, {stats['interpolated']} interpolated "
             '(flagged interp) inside the unmatched recognised span. Automatic timing, not a forced aligner: '
             'word edges can be off by tens of milliseconds.'
             + (f" Word edges inside silence (< {args.snap_db:g} dBFS, 10 ms frames) were snapped to the nearest voiced frame "
                f"({stats['snapped_edges']} edges)." if args.snap_db is not None else ''))
    args.lyrics.parent.mkdir(parents=True, exist_ok=True)
    args.lyrics.write_text(json.dumps({'lines': out_lines, 'extras': [], 'notes': notes, 'source': source, 'diffs': stats['diffs']},
                                      ensure_ascii=False, indent=1) + '\n')
    print(json.dumps({k: v for k, v in stats.items() if k != 'diffs'} | {'diffs': len(stats['diffs'])}, ensure_ascii=False))
    if args.envelope:
        first = out_lines[0]['words'][0]['start']
        period = 60 / args.bpm
        beats = [round(first + k * period, 3) for k in range(int((duration - first) / period) + 1)]
        rms = envelopes(audio, 16000)
        onsets = [[w['start'], 1.0] for line in out_lines for w in line['words']]
        sections = [{'name': f"line{line['i'] + 1:02d}", 'start': line['start'], 'end': line['end']} for line in out_lines]
        zeros = [0.0] * len(rms)
        args.envelope.write_text(json.dumps({
            'duration': round(duration, 3), 'bpm': args.bpm, 'beat_period': round(period, 5), 'time_signature': 4,
            'beats': beats, 'downbeats': beats[::4], 'sections': sections, 'fps': 100,
            'rms': rms, 'vocal': rms, 'low': zeros, 'mid': rms, 'high': zeros, 'drums': zeros, 'bass': zeros, 'other': zeros,
            'onsets': {'vocal': onsets, 'kick': [], 'snare': [], 'hat': []},
            'notes': (f'Voice-only analysis of {args.audio.name}. rms/vocal/mid = voice RMS (46 ms window, 10/90 ms smoothing, '
                      f'normalised to the 99th percentile). Beat grid is PROVISIONAL ({args.bpm:g} BPM from the first word) until '
                      'a music bed is chosen; vocal onsets are word starts.'),
        }) + '\n')


if __name__ == '__main__':
    main()
