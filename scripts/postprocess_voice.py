#!/usr/bin/env python3
"""Postprocess an approved take without resynthesis, pitch shifts or retiming.

Auditions use linear loudness matching only: no hidden limiter or noise gate.
Only the supplied synthetic audio is processed; this tool makes no API calls.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np
from scipy import signal
import soundfile as sf

from mix_reel import decode, loudness


def deess(samples, rate, config):
    """Smoothly reduce a treble shelf on sibilant-heavy frames; retain FFT phase."""
    size, hop = 2048, 256
    frequencies, _, spectrum = signal.stft(samples, rate, nperseg=size,
                                           noverlap=size-hop, boundary='zeros', padded=True)
    power = np.abs(spectrum) ** 2
    total = power.sum(axis=0)
    high = power[frequencies >= config['detector_hz']].sum(axis=0)
    fraction = high / np.maximum(total, 1e-20)
    # Energy fraction determines activation, not an inferred phoneme or speaker label.
    excess_db = np.maximum(10*np.log10(np.maximum(fraction, 1e-20) / config['fraction_threshold']), 0)
    requested = np.minimum(excess_db * (1 - 1/config['ratio']), config['max_cut_db'])
    requested[total < 1e-7] = 0
    reduction = np.empty_like(requested)
    previous = 0.
    for i, target in enumerate(requested):
        tau = config['attack_ms'] if target > previous else config['release_ms']
        coefficient = np.exp(-hop / (rate * tau / 1000))
        previous = coefficient*previous + (1-coefficient)*target
        reduction[i] = previous
    # Smooth frequency transition avoids a discontinuous mask/ringing at the split.
    transition = np.clip((frequencies-config['shelf_start_hz']) /
                         (config['shelf_full_hz']-config['shelf_start_hz']), 0, 1)
    shelf = .5 - .5*np.cos(np.pi*transition)
    gain = 10**(-shelf[:, None]*reduction[None, :]/20)
    _, result = signal.istft(spectrum*gain, rate, nperseg=size, noverlap=size-hop,
                             input_onesided=True, boundary=True)
    result = result[:len(samples)]
    if len(result) != len(samples) or not np.isfinite(result).all():
        raise ValueError('Postprocessing must preserve sample count and finite audio')
    active = requested > .05
    return result, {
        'max_reduction_db': float(reduction.max()),
        'active_frame_fraction': float(np.mean(active)),
        'active_reduction_median_db': float(np.median(reduction[active])) if active.any() else 0.,
        'fft_size': size, 'hop_samples': hop,
    }


def validate_preset(preset):
    c = preset['deesser']
    if not 0 < c['fraction_threshold'] < 1 or not 1 <= c['ratio'] <= 10:
        raise ValueError('Invalid de-esser detector or ratio')
    if not 0 <= c['max_cut_db'] <= 6 or not 0 < c['attack_ms'] <= c['release_ms'] <= 500:
        raise ValueError('Invalid bounded reduction or smoothing times')
    if not 1000 <= c['shelf_start_hz'] < c['shelf_full_hz'] < 12000:
        raise ValueError('Invalid shelf transition')
    if not c['shelf_start_hz'] <= c['detector_hz'] <= c['shelf_full_hz']:
        raise ValueError('Detector must be inside the shelf transition')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--before', type=Path, help='Previously delivered WAV for a matched before/after control')
    p.add_argument('--recipe', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--music-stem', type=Path,
                   help='Optional existing, already ducked 60-second stereo music stem')
    a = p.parse_args()
    recipe = json.loads(a.recipe.read_text())
    source_hash = hashlib.sha256(a.source.read_bytes()).hexdigest()
    if source_hash != recipe['source_sha256']:
        p.error('Source hash does not match the approved take')
    for name, preset in recipe['presets'].items():
        if not name.isascii() or not name.isalpha():
            p.error('Preset names must contain ASCII letters only')
        validate_preset(preset)
    target = float(recipe['target_lufs'])
    if not -30 <= target <= -14:
        p.error('Audition loudness must be between -30 and -14 LUFS')
    a.output.mkdir(mode=0o700, parents=True, exist_ok=True)
    if any(a.output.iterdir()):
        p.error('Use an empty output directory; previous results are never overwritten')
    rate = 48000
    source = decode(a.source, rate)
    files = {'raw': {'source': a.source, 'processing': 'linear gain only'}}
    if a.before:
        if len(decode(a.before, rate)) != len(source):
            p.error('Before control must have exactly the same sample count')
        files['before'] = {'source': a.before, 'processing': 'linear gain only'}
    for name, preset in recipe['presets'].items():
        # FFmpeg's deterministic IIR equalizer shapes the broad tone first.
        raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(a.source),
            '-af', preset['equalizer'], '-ar', str(rate), '-ac', '1', '-f', 'f32le', '-'])
        equalized = np.frombuffer(raw, dtype=np.float32)
        if len(equalized) != len(source):
            raise ValueError('Equalization changed duration')
        result, meter = deess(equalized, rate, preset['deesser'])
        path = a.output / f'{name}-working.wav'
        sf.write(path, result, rate, subtype='FLOAT')
        files[name] = {'source': path, 'processing': preset, 'deesser_meter': meter}
    # Use a common linear gain target low enough to preserve peaks in every variant.
    for row in files.values():
        row['input_loudness'] = loudness(row['source'])
    target = min(target, *[float(r['input_loudness']['input_i']) -
                          float(r['input_loudness']['input_tp']) - 1.6 for r in files.values()])
    target = float(np.floor(target*10)/10)
    for name, row in files.items():
        gain_db = target-float(row['input_loudness']['input_i'])
        x = decode(row['source'], rate)*10**(gain_db/20)
        path = a.output / f'{name}.wav'
        sf.write(path, x, rate, subtype='PCM_24')
        measured = loudness(path)
        if abs(float(measured['input_i'])-target) > .1 or float(measured['input_tp']) > -1.49:
            raise ValueError('Matched loudness/headroom verification failed')
        row.update(source=str(row['source']), output=path.name, linear_gain_db=gain_db,
                   samples=len(x), duration_s=len(x)/rate, measured=measured,
                   sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    if a.music_stem:
        voice = np.zeros(round(60*rate))
        clean = decode(a.output/'clean.wav', rate)
        offset = round(.15*rate)
        if offset+len(clean) > len(voice):
            raise ValueError('Approved speech does not fit the 60-second timeline')
        voice[offset:offset+len(clean)] = clean
        music = decode(a.music_stem, rate, channels=2)
        if len(music) != len(voice):
            raise ValueError('Music stem must be exactly 60 seconds')
        sf.write(a.output/'voice-timeline.wav', voice, rate, subtype='PCM_24')
        working = a.output/'mix-working.wav'
        sf.write(working, voice[:, None]+music, rate, subtype='FLOAT')
        measured = loudness(working)
        # Keep peaks intact in the music mix too; never silently insert limiting.
        mix_target = np.floor(min(-16., float(measured['input_i'])-
                                  float(measured['input_tp'])-1.6)*10)/10
        gain_db = float(mix_target)-float(measured['input_i'])
        sf.write(a.output/'mix.wav', decode(working, rate, channels=2)*10**(gain_db/20),
                 rate, subtype='PCM_24')
        for name in ['mix', 'voice-timeline']:
            path = a.output/f'{name}.wav'
            files[name] = dict(output=path.name, duration_s=60,
                measured=loudness(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        files['mix']['music_sha256'] = hashlib.sha256(a.music_stem.read_bytes()).hexdigest()
        files['mix']['linear_gain_db'] = gain_db
        files['mix']['speech_offset_s'] = .15
    for name, row in files.items():
        path = a.output/row['output']; mp3 = a.output/f'{name}.mp3'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(path),
                        '-c:a', 'libmp3lame', '-b:a', '320k', str(mp3)], check=True)
        row['mp3'] = dict(path=mp3.name, measured=loudness(mp3),
                          sha256=hashlib.sha256(mp3.read_bytes()).hexdigest())
    manifest = {'schema': 'instadna.postprocess/v1', 'source_sha256': source_hash,
                'recipe': recipe, 'sample_rate': rate, 'common_target_lufs': target,
                'ffmpeg_version': subprocess.check_output(['ffmpeg','-version']).decode().splitlines()[0],
                'files': files, 'limits': 'Timbre softening only; no claim of restoring missing voice detail.'}
    (a.output/'receipt.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps({'target_lufs':target,'files':{k:dict(seconds=v['duration_s'],LUFS=v['measured']['input_i'],dBTP=v['measured']['input_tp']) for k,v in files.items()}},indent=2))


if __name__ == '__main__':
    main()
