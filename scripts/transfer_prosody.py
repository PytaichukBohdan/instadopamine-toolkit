#!/usr/bin/env python3
"""Transfer a measured phrase pitch contour to synthetic speech; no source waveform is inserted.

The selected windows must contain the same spoken phrase. ASR timing is only a starting
point; inspect boundaries and listen to the result. This is not phoneme alignment.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np
import parselmouth
from parselmouth.praat import call
from scipy.ndimage import median_filter
import soundfile as sf


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--source-start', type=float, required=True)
    p.add_argument('--source-end', type=float, required=True)
    p.add_argument('--target', type=Path, required=True)
    p.add_argument('--target-start', type=float, required=True)
    p.add_argument('--target-end', type=float, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--match-duration', action='store_true')
    a = p.parse_args()
    if a.output.exists() or a.output.with_suffix('.json').exists():
        p.error('Output already exists')
    source = parselmouth.Sound(str(a.source)).extract_part(from_time=a.source_start, to_time=a.source_end, preserve_times=False)
    target, rate = sf.read(a.target)
    if target.ndim != 1:
        p.error('Use a mono target')
    begin, end = round(a.target_start*rate), round(a.target_end*rate)
    if begin < 0 or end > len(target) or begin >= end:
        p.error('Invalid target window')
    clip = parselmouth.Sound(target[begin:end], sampling_frequency=rate)
    pitch = source.to_pitch_ac(time_step=.01, pitch_floor=65, pitch_ceiling=400)
    f0 = pitch.selected_array['frequency']; voiced = f0 > 0
    if voiced.sum() < 5:
        p.error('Insufficient voiced source frames')
    frequency = median_filter(f0[voiced], size=3)
    times = pitch.xs()[voiced]
    manipulation = call(clip, 'To Manipulation', .01, 65, 400)
    tier = call(manipulation, 'Extract pitch tier')
    call(tier, 'Remove points between', 0, clip.duration)
    for t, value in zip(times/source.duration*clip.duration, frequency):
        call(tier, 'Add point', float(t), float(value))
    call([tier, manipulation], 'Replace pitch tier')
    result = call(manipulation, 'Get resynthesis (overlap-add)').values[0]
    if a.match_duration:
        with tempfile.TemporaryDirectory() as directory:
            before = Path(directory)/'before.wav'; after = Path(directory)/'after.wav'
            sf.write(before, result, rate)
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(before), '-af',
                            f'atempo={clip.duration/source.duration}', '-ar', str(rate), str(after)], check=True)
            result, _ = sf.read(after)
    fade = min(round(.004*rate), len(result)//4)
    result[:fade] *= np.linspace(0, 1, fade); result[-fade:] *= np.linspace(1, 0, fade)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(a.output, np.concatenate([target[:begin], result, target[end:]]), rate)
    metadata = dict(source_sha256=hashlib.sha256(a.source.read_bytes()).hexdigest(),
                    target_sha256=hashlib.sha256(a.target.read_bytes()).hexdigest(),
                    result_sha256=hashlib.sha256(a.output.read_bytes()).hexdigest(),
                    source_window=[a.source_start, a.source_end], target_window=[a.target_start, a.target_end],
                    result_phrase_duration_s=len(result)/rate, match_duration=a.match_duration,
                    method='Praat pitch-tier overlap-add; optional FFmpeg atempo; synthetic waveform only',
                    source_pitch_points=[[float(t), float(f)] for t,f in zip(times,frequency)],
                    limit='Global phrase timing and F0 transfer, not a guarantee of exact articulation or perceived identity.')
    a.output.with_suffix('.json').write_text(json.dumps(metadata, indent=2))


if __name__ == '__main__':
    main()
