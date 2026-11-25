#!/usr/bin/env python3
"""Mix the voice-over with the music bed: the music ducks under speech and swells in the pauses.

The music is trimmed to the voice's length and lowered by `--music-gain`; `--layer` can first copy a slice of the
music (an impact) onto a later moment. A sidechain compressor keyed by the voice
ducks it while she speaks. The sum is brought to `--lufs` integrated loudness and `--true-peak` with ffmpeg's two-pass
loudnorm (linear gain, so the dynamics stay). The voice itself is never processed apart from that overall gain.
Writes mix.wav (48 kHz / 24-bit) and a receipt with input hashes, settings and measurements. The measurements are:
loudness and true peak, how far the voice stands above the music in the speech band (300 Hz-4 kHz) while she speaks,
and the levels a phone speaker can play (300 Hz-8 kHz): the voice, the music under it and the music in the pauses.
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


def pcm(path, flt=None):
    args = ['ffmpeg', '-v', 'error', '-i', str(path)] + (['-af', flt] if flt else []) + ['-ac', '1', '-ar', str(RATE), '-f', 'f32le', '-']
    return np.frombuffer(subprocess.run(args, capture_output=True, check=True).stdout, np.float32)


def db(x):
    return float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12))


def phone_band(voice, music, speech):
    """Levels a phone speaker can play (300 Hz-8 kHz): the voice while she speaks, the music under her and in the pauses."""
    flt = 'highpass=f=300:poles=2,highpass=f=300:poles=2,lowpass=f=8000'
    v, m = pcm(voice, flt), pcm(music, flt)
    n = min(len(v), len(m), len(speech))
    s = speech[:n]
    return {'voice_db': round(db(v[:n][s]), 1), 'music_under_voice_db': round(db(m[:n][s]), 1), 'music_in_pauses_db': round(db(m[:n][~s]), 1)}


def loudness(path):
    log = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(path), '-af', 'ebur128=peak=true', '-f', 'null', '-'],
                         capture_output=True, text=True).stderr
    return {'integrated_lufs': float(re.findall(r'I:\s+(-?[\d.]+) LUFS', log)[-1]),
            'true_peak_dbfs': float(re.findall(r'Peak:\s+(-?[\d.]+) dBFS', log)[-1])}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--voice', type=Path, required=True)
    p.add_argument('--music', type=Path, required=True)
    p.add_argument('--lyrics', type=Path, required=True, help='Word alignment of the voice (for the speech-band check)')
    p.add_argument('--music-gain', type=float, default=-6.0)
    p.add_argument('--layer', action='append', default=[],
                   help='SRC:DUR@AT:GAIN_DB - copy DUR seconds of the music from SRC and add them at AT (e.g. reuse an impact '
                        'on a later cut); 5 ms fade in, 150 ms fade out')
    p.add_argument('--duck-ratio', type=float, default=12.0)
    p.add_argument('--duck-threshold', type=float, default=0.015)
    p.add_argument('--lufs', type=float, default=-14.0)
    p.add_argument('--true-peak', type=float, default=-1.0)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    length = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(a.voice)]))
    duck = f'sidechaincompress=threshold={a.duck_threshold}:ratio={a.duck_ratio}:attack=10:release=380:knee=3:makeup=1'
    music_in = a.music
    if a.layer:
        raw_music = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(a.music), '-ac', '2', '-ar', str(RATE), '-f', 'f32le', '-'],
                                   capture_output=True, check=True).stdout
        x = np.frombuffer(raw_music, np.float32).reshape(-1, 2).copy()  # stereo, so the bed keeps its width
        for spec in a.layer:
            src, rest = spec.split(':', 1)
            dur, rest = rest.split('@', 1)
            at, gain = rest.split(':')
            i, k, j = int(float(src) * RATE), int(float(dur) * RATE), int(float(at) * RATE)
            piece = x[i:i + k].copy() * 10 ** (float(gain) / 20)
            fi, fo = int(0.005 * RATE), int(0.15 * RATE)
            piece[:fi] *= np.linspace(0, 1, fi)[:, None]
            piece[-fo:] *= np.linspace(1, 0, fo)[:, None]
            end = min(len(x), j + len(piece))
            x[j:end] += piece[:end - j]
        music_in = a.out / 'music-layered.wav'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'f32le', '-ar', str(RATE), '-ac', '2', '-i', '-', '-c:a', 'pcm_s24le',
                        str(music_in)], input=x.astype(np.float32).tobytes(), check=True)
    graph = (f'[1:a]aresample={RATE},volume={a.music_gain}dB,atrim=0:{length:.3f},apad=whole_dur={length:.3f}[m];'
             f'[0:a]aresample={RATE},asplit=2[v][sc];[m][sc]{duck}[md];[md]asplit=2[md1][md2];'
             '[v][md1]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix]')
    raw, ducked = a.out / 'mix-unnormalised.wav', a.out / 'music-ducked.wav'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(a.voice), '-i', str(music_in), '-filter_complex', graph,
                    '-map', '[mix]', '-c:a', 'pcm_s24le', str(raw), '-map', '[md2]', '-c:a', 'pcm_s24le', str(ducked)], check=True)
    first = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(raw), '-af',
                            f'loudnorm=I={a.lufs}:TP={a.true_peak}:LRA=20:print_format=json', '-f', 'null', '-'],
                           capture_output=True, text=True).stderr
    m = json.loads(first[first.rindex('{'):first.rindex('}') + 1])
    second = (f"loudnorm=I={a.lufs}:TP={a.true_peak}:LRA=20:linear=true:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
              f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}")
    mix = a.out / 'mix.wav'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(raw), '-af', f'{second},aresample={RATE}', '-c:a', 'pcm_s24le', str(mix)], check=True)
    band = 'highpass=f=300,lowpass=f=4000'
    v, mu = pcm(a.voice, band), pcm(ducked, band)
    speech = np.zeros(min(len(v), len(mu)), bool)
    for line in json.loads(a.lyrics.read_text())['lines']:
        speech[int(line['start'] * RATE):int(line['end'] * RATE)] = True
    n = len(speech)
    receipt = {'voice': a.voice.name, 'voice_sha256': hashlib.sha256(a.voice.read_bytes()).hexdigest(),
               'music': a.music.name, 'music_sha256': hashlib.sha256(a.music.read_bytes()).hexdigest(),
               'music_gain_db': a.music_gain, 'ducking': duck, 'layers': a.layer, 'loudnorm_target': {'lufs': a.lufs, 'true_peak': a.true_peak, 'linear': True},
               'voice_above_music_speech_band_db': round(db(v[:n][speech]) - db(mu[:n][speech]), 1),
               'music_in_pauses_db': round(db(pcm(ducked)[:n][~speech]), 1),
               'phone_band': phone_band(a.voice, ducked, speech),
               'mix': {'sha256': hashlib.sha256(mix.read_bytes()).hexdigest(), 'duration_s': round(length, 3), **loudness(mix)}}
    (a.out / 'mix-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    main()
