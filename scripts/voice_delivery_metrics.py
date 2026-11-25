#!/usr/bin/env python3
"""Delivery metrics for a synthetic voice take: how high, how sing-song, how assertive and how forceful it sounds.

Per line (from the word alignment written by align_script_words.py): pitch median, the 95th-percentile pitch ("line
peak"), the swing inside the line (95th minus 5th percentile, semitones) and how the line ends (slope of the last
0.35 s of voiced pitch: falling below -4 st/s, rising above +4 st/s). A confident declarative ends falling; the
"talking to children" contour has high peaks, wide swings and rising ends.

For the whole take, on voiced frames: spectral balance (energy 1-4 kHz minus 0-1 kHz, dB; higher means a brighter,
more effortful voice) and loudness contrast (90th minus 10th percentile of frame intensity, dB; higher means more
emphasis). Praat autocorrelation pitch, 110-500 Hz, 10 ms steps. Automatic measurements, not a listening test.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import parselmouth


def line_metrics(times, f0, lines):
    rows = []
    for line in lines:
        a, b = line['start'], line['end']
        v = f0[(times >= a) & (times <= b) & (f0 > 0)]
        if len(v) < 5:
            continue
        st = 12 * np.log2(v / 100)
        tail = (times >= b - 0.35) & (times <= b) & (f0 > 0)
        slope = float(np.polyfit(times[tail], 12 * np.log2(f0[tail] / 100), 1)[0]) if tail.sum() >= 4 else 0.0
        rows.append({'line': line['i'] + 1, 'text': line['text'], 'f0_median_hz': round(float(np.median(v)), 1),
                     'line_peak_hz': round(float(np.percentile(v, 95)), 1),
                     'swing_st': round(float(np.percentile(st, 95) - np.percentile(st, 5)), 1),
                     'end_slope_st_s': round(slope, 1), 'end': 'falling' if slope < -4 else 'rising' if slope > 4 else 'level'})
    return rows


def take_metrics(sound, pitch):
    intensity = sound.to_intensity(time_step=0.01)
    x, rate = sound.values[0], sound.sampling_frequency
    n = int(0.04 * rate)
    balance, level = [], []
    for t, f in zip(pitch.xs(), pitch.selected_array['frequency']):
        if f <= 0:
            continue
        i = int(t * rate)
        seg = x[max(0, i - n // 2): i + n // 2]
        if len(seg) < n:
            continue
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2
        freqs = np.fft.rfftfreq(len(seg), 1 / rate)
        low = spec[(freqs >= 80) & (freqs < 1000)].sum() + 1e-12
        high = spec[(freqs >= 1000) & (freqs < 4000)].sum() + 1e-12
        balance.append(10 * np.log10(high / low))
        db = intensity.get_value(t)
        if db == db:
            level.append(db)
    return {'spectral_balance_db': round(float(np.median(balance)), 2),
            'loudness_contrast_db': round(float(np.percentile(level, 90) - np.percentile(level, 10)), 2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--lyrics', type=Path, help='Word alignment of this exact audio (align_script_words.py); enables per-line metrics')
    args = parser.parse_args()
    sound = parselmouth.Sound(str(args.audio)).convert_to_mono()
    pitch = sound.to_pitch_ac(time_step=0.01, pitch_floor=110, pitch_ceiling=500)
    out = {'audio': args.audio.name, **take_metrics(sound, pitch)}
    if args.lyrics:
        rows = line_metrics(pitch.xs(), pitch.selected_array['frequency'], json.loads(args.lyrics.read_text())['lines'])
        statements = [r for r in rows if not r['text'].rstrip().endswith('?')]
        out.update({'mean_line_peak_hz': round(float(np.mean([r['line_peak_hz'] for r in rows])), 1),
                    'mean_swing_st': round(float(np.mean([r['swing_st'] for r in rows])), 2),
                    'statements_ending_falling': sum(r['end'] == 'falling' for r in statements),
                    'statements_ending_rising': sum(r['end'] == 'rising' for r in statements),
                    'statements': len(statements), 'lines': rows})
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
