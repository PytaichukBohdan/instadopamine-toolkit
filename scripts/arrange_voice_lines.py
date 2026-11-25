#!/usr/bin/env python3
"""Space an approved synthetic take into a montage rhythm by inserting silence between its lines.

The voice itself is never stretched, pitched, compressed or regenerated: the take is cut only at the
centre of the longest measured silence (below -50 dBFS) between two aligned lines, silence is inserted
there with 8 ms fades, and the tail is padded or trimmed to an exact total.
Gain stays constant. Writes a 48 kHz / 24-bit mono WAV, a 192 kbit/s MP3 and a receipt with the
source hash, every cut (source and output time), and measured duration, loudness and true peak of
both files. Needs the line alignment written by align_script_words.py for the same source.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

import numpy as np

RATE = 48000


def decode(path):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-ac', '1', '-ar', str(RATE), '-f', 'f32le', '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).copy()


def silence_center(audio, t0, t1, floor_db=-50.0, frame=0.01):
    """Centre of the longest run of 10 ms frames below floor_db in [t0, t1]; else the quietest frame.

    ASR word edges are approximate, so the window is generous and the cut lands in measured silence,
    never on a decaying word tail."""
    a, b, n = int(t0 * RATE), int(t1 * RATE), int(frame * RATE)
    frames = [(a + i * n, 20 * np.log10(np.sqrt(np.mean(audio[a + i * n:a + (i + 1) * n] ** 2)) + 1e-9)) for i in range((b - a) // n)]
    best, run = [], []
    for start, db in frames:
        run = run + [start] if db < floor_db else []
        if len(run) > len(best):
            best = run
    if best:
        return (best[0] + best[-1] + n) // 2
    return min(frames, key=lambda f: f[1])[0] + n // 2


def measure(path):
    log = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(path), '-af', 'ebur128=peak=true', '-f', 'null', '-'],
                         capture_output=True, text=True).stderr
    duration = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)]))
    return {'duration_s': round(duration, 3), 'integrated_lufs': float(re.findall(r'I:\s+(-?[\d.]+) LUFS', log)[-1]),
            'true_peak_dbfs': float(re.findall(r'Peak:\s+(-?[\d.]+) dBFS', log)[-1])}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--audio', type=Path, required=True)
    p.add_argument('--lyrics', type=Path, required=True, help='Alignment of this exact source (align_script_words.py)')
    p.add_argument('--insert', required=True, help='after_line:seconds pairs, 1-based lines, e.g. 2:0.5,4:0.35')
    p.add_argument('--lead', type=float, default=0.0, help='Silence before the first word')
    p.add_argument('--total', type=float, required=True, help='Exact output length in seconds (tail padded or trimmed in silence)')
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    audio = decode(a.audio)
    lines = json.loads(a.lyrics.read_text())['lines']
    plan = sorted((int(k), float(v)) for k, v in (x.split(':') for x in a.insert.split(',')))
    fade = int(0.008 * RATE)
    pieces, cursor, shift, cuts = [np.zeros(int(a.lead * RATE), np.float32)], 0, a.lead, []
    for after, seconds in plan:
        if not 1 <= after < len(lines):
            raise SystemExit(f'No gap after line {after}')
        end, start = lines[after - 1]['end'], lines[after]['start']
        at = silence_center(audio, max(end - 0.3, 0), start + 0.45)
        if at <= cursor:
            raise SystemExit(f'Cut after line {after} is out of order')
        seg = audio[cursor:at].copy()
        seg[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
        if cursor:
            seg[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
        pieces += [seg, np.zeros(int(seconds * RATE), np.float32)]
        cuts.append({'after_line': after, 'inserted_s': seconds, 'source_s': round(at / RATE, 3), 'output_s': round(at / RATE + shift, 3)})
        shift += seconds
        cursor = at
    rest = audio[cursor:].copy()
    rest[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
    pieces.append(rest)
    out = np.concatenate(pieces)
    target = int(round(a.total * RATE))
    last_word = lines[-1]['end'] + shift
    if target / RATE < last_word + 0.1:
        raise SystemExit(f'Total {a.total} s would cut the last word (ends at {last_word:.2f} s)')
    out = np.pad(out, (0, max(0, target - len(out))))[:target]
    a.out.mkdir(parents=True, exist_ok=True)
    wav, mp3 = a.out / 'master.wav', a.out / 'master.mp3'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'f32le', '-ar', str(RATE), '-ac', '1', '-i', '-', '-c:a', 'pcm_s24le', str(wav)],
                   input=out.astype(np.float32).tobytes(), check=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(wav), '-c:a', 'libmp3lame', '-b:a', '192k', str(mp3)], check=True)
    receipt = {'source': a.audio.name, 'source_sha256': hashlib.sha256(a.audio.read_bytes()).hexdigest(),
               'lead_s': a.lead, 'total_s': a.total, 'cuts': cuts, 'gain': 'constant (unchanged)',
               'processing': 'silence inserted between lines with 8 ms fades; no stretching, pitch, EQ, compression or limiting',
               'wav': {'sha256': hashlib.sha256(wav.read_bytes()).hexdigest(), **measure(wav)},
               'mp3': {'sha256': hashlib.sha256(mp3.read_bytes()).hexdigest(), **measure(mp3)}}
    (a.out / 'arrangement.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    main()
