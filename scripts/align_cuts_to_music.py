#!/usr/bin/env python3
"""Move storyboard cuts onto the music: named hits first, then the nearest beat, within caption-safe limits.

Reads a storyboard spec (shots.json), the word alignment of the voice it is cut to, and the music bed. Beats come from
librosa's beat tracker on the percussive part of the music; a named hit (`--hit S04:3.60`) moves that shot's cut to the
strongest onset within `--hit-window` (0.3 s) of the given time. Every other cut moves to the nearest beat, or half-beat when no beat
fits, but only if:
  - the shot's first caption word does not start more than `--max-caption-lag` before the new cut (no late captions);
  - the previous shot keeps its last caption on screen for at least `--min-caption-hold`;
  - every shot stays at least `--min-shot` long.
Otherwise the cut stays where the words put it. Writes a spec whose cuts are absolute times ({"at": s}) with the
original anchor kept for traceability, and prints a per-cut report. Nothing here calls a model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def music_grid(path):
    import librosa
    y, sr = librosa.load(str(path), sr=22050, mono=True)
    _, percussive = librosa.effects.hpss(y)
    tempo, beats = librosa.beat.beat_track(y=percussive, sr=sr, units='time')
    env = librosa.onset.onset_strength(y=y, sr=sr)
    times = librosa.times_like(env, sr=sr)
    return float(np.atleast_1d(tempo)[0]), np.asarray(beats, float), times, env, len(y) / sr


def word_times(lyrics):
    lines = lyrics['lines']
    return lambda a: lines[a[0]]['words'][a[1]]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--spec', type=Path, required=True)
    p.add_argument('--lyrics', type=Path, required=True)
    p.add_argument('--music', type=Path, required=True)
    p.add_argument('--hit', action='append', default=[], help='SHOT:seconds, a cut placed on the strongest onset near this time')
    p.add_argument('--max-caption-lag', type=float, default=0.12)
    p.add_argument('--min-caption-hold', type=float, default=0.3)
    p.add_argument('--min-shot', type=float, default=0.45)
    p.add_argument('--window', type=float, default=0.35, help='How far a cut may move to reach a beat (s)')
    p.add_argument('--hit-window', type=float, default=0.3, help='How far from a named hit time to look for its onset (s)')
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()

    spec = json.loads(a.spec.read_text())
    lyrics = json.loads(a.lyrics.read_text())
    word = word_times(lyrics)
    tempo, beats, times, env, music_len = music_grid(a.music)
    period = 60 / tempo
    halves = np.sort(np.concatenate([beats, beats[:-1] + np.diff(beats) / 2]))
    hits = {k: float(v) for k, v in (h.split(':') for h in a.hit)}

    shots = [s for s in spec['shots'] if s['type'] not in ('anchor', 'card')]
    card = spec['format']['end_card']
    card_start = lyrics['lines'][card['start_after_line']]['end'] + card['gap_s']

    def planned(s, i):
        cut = s['cut']
        if i == 0 or not cut:
            return 0.0
        if isinstance(cut, dict):
            return word(cut['after'])['end'] + cut.get('plus', 0.0)
        return word(cut)['start'] - s['lead']

    def first_caption(s):
        return min((word(c['at'])['start'] for c in s['captions']), default=None)

    def last_caption(s):
        return max((word(c['at'])['start'] for c in s['captions']), default=None)

    plan = [planned(s, i) for i, s in enumerate(shots)]
    new, report = [0.0], [{'shot': shots[0]['id'], 'planned': 0.0, 'cut': 0.0, 'snap': 'start'}]
    for i in range(1, len(shots)):
        s, t0 = shots[i], plan[i]
        nxt = plan[i + 1] if i + 1 < len(shots) else card_start
        fc, prev_last = first_caption(s), last_caption(shots[i - 1])

        def ok(t):
            if t - new[-1] < a.min_shot or nxt - t < a.min_shot:
                return False
            if fc is not None and t - fc > a.max_caption_lag:
                return False
            if prev_last is not None and t - prev_last < a.min_caption_hold:
                return False
            return True

        choice, how = t0, 'kept'
        if s['id'] in hits:
            near = (times >= hits[s['id']] - a.hit_window) & (times <= hits[s['id']] + a.hit_window)
            t_hit = float(times[near][np.argmax(env[near])])
            if t_hit - new[-1] >= a.min_shot:
                choice, how = t_hit, 'hit'
        else:
            for grid, label in ((beats, 'beat'), (halves, 'half-beat')):
                cands = sorted((g for g in grid if abs(g - t0) <= a.window and ok(g)), key=lambda g: abs(g - t0))
                if cands:
                    choice, how = float(cands[0]), label
                    break
        new.append(choice)
        report.append({'shot': s['id'], 'planned': round(t0, 3), 'cut': round(choice, 3), 'moved': round(choice - t0, 3), 'snap': how})

    # the end card on the nearest beat after the last line (not earlier than planned - 0.25 s)
    card_beats = [b for b in beats if b >= card_start - 0.25 and b - new[-1] >= a.min_shot]
    card_at = float(card_beats[0]) if card_beats else card_start
    report.append({'shot': 'card', 'planned': round(card_start, 3), 'cut': round(card_at, 3), 'moved': round(card_at - card_start, 3),
                   'snap': 'beat' if card_beats else 'kept'})

    out = json.loads(json.dumps(spec))
    by_id = {s['id']: s for s in out['shots']}
    for s, t, r in zip(shots, new, report):
        row = by_id[s['id']]
        if row['cut'] is not None or t:
            row['cut'] = {'at': round(t, 3), 'from': s['cut'], 'snap': r['snap']}
    card_row = next(s for s in out['shots'] if s['type'] == 'card')
    card_row['cut'] = {'at': round(card_at, 3), 'from': None, 'snap': report[-1]['snap']}
    out['music'] = {'path': str(a.music.name), 'sha256': hashlib.sha256(a.music.read_bytes()).hexdigest(),
                    'tempo_bpm': round(tempo, 2), 'beat_period_s': round(period, 4), 'first_beat_s': round(float(beats[0]), 3),
                    'duration_s': round(music_len, 3), 'hits': hits,
                    'rules': {'max_caption_lag_s': a.max_caption_lag, 'min_caption_hold_s': a.min_caption_hold,
                              'min_shot_s': a.min_shot, 'window_s': a.window}}
    a.out.write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
    on_beat = sum(1 for r in report[1:] if r['snap'] in ('beat', 'hit', 'half-beat'))
    print(json.dumps({'tempo_bpm': round(tempo, 2), 'cuts': len(report) - 1, 'on_beat_or_hit': on_beat,
                      'report': report}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
