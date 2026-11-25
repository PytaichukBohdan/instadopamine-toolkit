#!/usr/bin/env python3
"""Render an explicit audio-only edit plan to voice/music stems and a mastered mix."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

import numpy as np
import soundfile as sf
from scipy.ndimage import maximum_filter1d, gaussian_filter1d
from scipy.signal import butter, sosfilt


def decode(path, rate=48000, channels=1):
    raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'f32le',
                                   '-ar', str(rate), '-ac', str(channels), '-'])
    data = np.frombuffer(raw, dtype=np.float32).reshape(-1, channels)
    return data[:, 0].copy() if channels == 1 else data.copy()


def loudness(path, target=-15):
    result = subprocess.run(['ffmpeg', '-hide_banner', '-i', str(path), '-af',
                             f'loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json', '-f', 'null', '-'],
                            capture_output=True, text=True, check=True)
    return json.loads(re.search(r'{\s*"input_i".*?}', result.stderr, re.S)[0])


def master(source, dest, target=-15):
    m = loudness(source, target)
    filt = (f'loudnorm=I={target}:TP=-1.5:LRA=11:measured_I={m["input_i"]}:'
            f'measured_TP={m["input_tp"]}:measured_LRA={m["input_lra"]}:'
            f'measured_thresh={m["input_thresh"]}:offset={m["target_offset"]}:linear=true')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(source), '-af', filt,
                    '-ar', '48000', '-c:a', 'pcm_s16le', str(dest)], check=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--assets', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    root = a.assets.resolve(); plan = json.loads(a.plan.read_text())
    a.output.mkdir(parents=True, exist_ok=True)
    if any(a.output.iterdir()):
        p.error('Use an empty output directory')
    def asset(name):
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            raise ValueError('Asset path escapes root')
        return path
    rate, duration = 48000, plan['duration_s']
    n = round(rate * duration); voice = np.zeros(n); timeline = []; last_end = 0
    for item in plan['voice']:
        path = asset(item['path']); source = decode(path)
        begin, end = round(item['source_start']*rate), round(item['source_end']*rate)
        clip = source[begin:end].copy()
        if begin < 0 or end > len(source) or len(clip) < .08*rate:
            raise ValueError('Invalid source trim')
        clip = sosfilt(butter(2, 70, btype='highpass', fs=rate, output='sos'), clip)
        # Match phrase level gently; preserve microdynamics and limit correction to 3 dB.
        active = clip[np.abs(clip) > .02]
        rms = np.sqrt(np.mean(active**2)) if len(active) else 0
        if rms == 0:
            raise ValueError('Silent voice phrase')
        gain = np.clip(.13/rms, 10**(-3/20), 10**(3/20))
        clip *= gain
        fade = round(.006*rate)
        clip[:fade] *= np.linspace(0, 1, fade); clip[-fade:] *= np.linspace(1, 0, fade)
        start = round(item['timeline_start']*rate); stop = start+len(clip)
        if start < last_end or stop > n:
            raise ValueError('Voice overlap or timeline overflow')
        voice[start:stop] += clip; last_end = stop
        timeline.append({**item, 'timeline_end':stop/rate, 'gain_db':float(20*np.log10(gain)),
                         'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    music = decode(asset(plan['music']), channels=2)
    if len(music) < n:
        raise ValueError('Music is shorter than timeline')
    music = music[:n]
    # 10ms activity frames, 70ms hold and 40ms smooth attack/release for natural ducking.
    hop = 480
    rms = np.array([np.sqrt(np.mean(voice[i:i+hop]**2)) for i in range(0, n, hop)])
    activity = gaussian_filter1d(maximum_filter1d((rms > .013).astype(float), size=15), sigma=4)
    env = np.interp(np.arange(n)/hop, np.arange(len(activity)), activity)
    music_rms = np.sqrt(np.mean(music**2))
    target_music_rms = float(plan.get('music_rms', .065))
    if not 0 < target_music_rms <= 1 or music_rms == 0:
        raise ValueError('Music target must be positive and source music must be audible')
    music *= target_music_rms/music_rms
    music *= (1-.65*env)[:, None]
    t = np.arange(n)/rate; end_voice = last_end/rate
    music *= np.interp(t, [0, end_voice, min(end_voice+.18, duration), duration-.35, duration],
                       [1, 1, 1.9, 1.9, 0])[:, None]
    # Short synthesized tab/hiss punctuation after the everyday-life detail.
    sfx = np.zeros((n, 2)); rng = np.random.default_rng(872)
    for event in plan.get('sfx', []):
        length = round(.18*rate); tt = np.arange(length)/rate
        noise = sosfilt(butter(2, 2500, btype='highpass', fs=rate, output='sos'), rng.normal(size=length))
        pop = .022*noise*np.exp(-tt*28) + .035*np.sin(2*np.pi*620*tt)*np.exp(-tt*95)
        start = round(event['time']*rate); sfx[start:start+length] += pop[:, None]
    sf.write(a.output/'voice-unmastered.wav', voice, rate)
    sf.write(a.output/'music-stem.wav', music, rate)
    sf.write(a.output/'sfx-stem.wav', sfx, rate)
    sf.write(a.output/'mix-unmastered.wav', music+voice[:, None]+sfx, rate, subtype='FLOAT')
    master(a.output/'mix-unmastered.wav', a.output/'master.wav')
    master(a.output/'voice-unmastered.wav', a.output/'voice-only.wav', target=-16)
    results = {}
    for name in ['master', 'voice-only']:
        wav = a.output/(name+'.wav'); mp3 = a.output/(name+'.mp3')
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(wav), '-c:a', 'libmp3lame', '-b:a', '192k', str(mp3)], check=True)
        for file in [wav, mp3]:
            results[file.name] = dict(sha256=hashlib.sha256(file.read_bytes()).hexdigest(), loudness=loudness(file))
    (a.output/'timeline.json').write_text(json.dumps(dict(duration_s=duration, sample_rate=rate, voice=timeline,
                                                       music=plan['music'], music_rms=target_music_rms,
                                                       sfx=plan.get('sfx', [])), ensure_ascii=False, indent=2))
    (a.output/'verification.json').write_text(json.dumps(results, indent=2))
    print(json.dumps({name:{'LUFS':data['loudness']['input_i'], 'dBTP':data['loudness']['input_tp']} for name,data in results.items()}, indent=2))


if __name__ == '__main__':
    main()
