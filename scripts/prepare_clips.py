#!/usr/bin/env python3
"""Cut each shot's image-to-video clip into the frames the engine plays as a video plate.

For every shot in the compiled storyboard whose clip is listed in the clips manifest, ffmpeg takes the clip from its
in-point (`offset_s`), plays it at `speed` (1 = real time, 2 = twice as fast), resamples it to the edit's frame rate,
scales it to cover 1080x1920 (lanczos) and writes exactly the frames the shot's window needs as numbered JPEGs, with an
index.json (fps, frame count, source hash, in-point, speed). The engine (video/app/src/scenes/face.ts) loads frame k at
song time start + k / fps. A shot whose clip is too short for its window at that speed is refused. The frames stay in
private storage; only the final edit is published.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path


def probe_duration(path):
    return float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)]))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--storyboard', type=Path, required=True, help='Compiled storyboard JSON (shot windows)')
    p.add_argument('--clips', type=Path, required=True, help='Clips manifest: {"clips": [{"shot", "path", "offset_s", "speed"}]}')
    p.add_argument('--out', type=Path, required=True, help='Private frames directory (one folder per shot)')
    p.add_argument('--fps', type=int, default=25)
    p.add_argument('--width', type=int, default=1080)
    p.add_argument('--height', type=int, default=1920)
    p.add_argument('--only', help='Comma-separated shot IDs')
    a = p.parse_args()
    board = json.loads(a.storyboard.read_text())
    manifest = json.loads(a.clips.read_text())
    base = a.clips.parent
    windows = {s['id']: (s['start'], s['end']) for s in board['shots']}
    wanted = set(a.only.split(',')) if a.only else None
    done = []
    for row in manifest['clips']:
        shot = row['shot']
        if wanted and shot not in wanted:
            continue
        if shot not in windows:
            raise SystemExit(f'{shot}: not in the storyboard')
        start, end = windows[shot]
        src = (base / row['path']).resolve() if not Path(row['path']).is_absolute() else Path(row['path'])
        offset, speed = float(row.get('offset_s', 0.0)), float(row.get('speed', 1.0))
        frames = math.ceil((end - start) * a.fps - 1e-6) + 1
        need = offset + frames / a.fps * speed
        length = probe_duration(src)
        if need > length + 1e-3:
            raise SystemExit(f'{shot}: needs {need:.2f} s of clip at speed {speed} from {offset} s, the clip has {length:.2f} s')
        folder = a.out / shot
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        vf = (f'trim=start={offset},setpts=(PTS-STARTPTS)/{speed},fps={a.fps},'
              f'scale={a.width}:{a.height}:force_original_aspect_ratio=increase:flags=lanczos,crop={a.width}:{a.height}')
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(src), '-vf', vf, '-frames:v', str(frames), '-q:v', '3',
                        '-start_number', '0', str(folder / '%04d.jpg')], check=True)
        written = len(list(folder.glob('*.jpg')))
        if written < frames:
            raise SystemExit(f'{shot}: wrote {written} of {frames} frames')
        info = {'shot': shot, 'fps': a.fps, 'frames': frames, 'width': a.width, 'height': a.height, 'window': [start, end],
                'source': row['path'], 'source_sha256': hashlib.sha256(src.read_bytes()).hexdigest(),
                'source_duration_s': round(length, 3), 'offset_s': offset, 'speed': speed}
        (folder / 'index.json').write_text(json.dumps(info, ensure_ascii=False, indent=1) + '\n')
        done.append({'shot': shot, 'frames': frames, 'speed': speed, 'offset_s': offset})
    print(json.dumps({'prepared': len(done), 'shots': done}, ensure_ascii=False))


if __name__ == '__main__':
    main()
