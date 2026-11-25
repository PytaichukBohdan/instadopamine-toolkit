"""Publish only explicitly selected, hash-checked generated video exports (AI edits), with a mandatory disclosure."""
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path

LIMIT = 25 * 1024 * 1024  # Cloudflare Pages asset limit


def _checked(wiki: Path, name: str, pattern: str, sha: str, what: str):
    if not re.fullmatch(pattern, name):
        raise ValueError(f'{what} must be an allowlisted file under video/: {name}')
    path = wiki / name
    if path.is_symlink() or not path.resolve().is_relative_to(wiki.resolve()):
        raise ValueError(f'{what} escapes the wiki or is a symlink')
    if path.stat().st_size >= LIMIT:
        raise ValueError(f'{what} exceeds the Pages asset limit')
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
        raise ValueError(f'{what} hash mismatch: {name}')
    return path


def load_video(wiki: Path):
    """Rows of `video-manifest.json` and its disclosure; ([], '') when there is none."""
    manifest = wiki / 'video-manifest.json'
    if not manifest.exists():
        return [], ''
    data = json.loads(manifest.read_text())
    if data.get('schema') != 'instadna.video/v1':
        raise ValueError('Unsupported video manifest')
    disclosure = (data.get('disclosure') or '').strip()
    if 'ai-generated' not in disclosure.lower():
        raise ValueError('Generated video needs a disclosure that names it as AI-generated')
    rows, seen = data['assets'], set()
    for row in rows:
        if not re.fullmatch(r'[a-z][a-z0-9-]+', row['id']) or row['id'] in seen:
            raise ValueError('Invalid or duplicate video ID')
        seen.add(row['id'])
        if row.get('origin') != 'generated' or row.get('publish') is not True:
            raise ValueError('Only selected generated exports may be published')
        path = _checked(wiki, row['path'], r'video/[a-z0-9-]+\.mp4', row['sha256'], 'Video')
        if row.get('poster'):
            _checked(wiki, row['poster'], r'video/[a-z0-9-]+\.jpg', row['poster_sha256'], 'Poster')
        duration = row['duration_s']
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
            raise ValueError('Invalid video duration')
        probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)]))
        kinds = sorted(s['codec_type'] for s in probe['streams'])
        if kinds != ['audio', 'video']:
            raise ValueError('A video export must hold exactly one video and one audio stream')
        video = next(s for s in probe['streams'] if s['codec_type'] == 'video')
        if video['codec_name'] != 'h264' or (video['width'], video['height']) != (row['width'], row['height']):
            raise ValueError('Video must be H.264 at the size the manifest states')
        if abs(float(probe['format']['duration']) - duration) > .1:
            raise ValueError('Video duration does not match the manifest')
    return rows, disclosure


def files(rows):
    return [r['path'] for r in rows] + [r['poster'] for r in rows if r.get('poster')]
