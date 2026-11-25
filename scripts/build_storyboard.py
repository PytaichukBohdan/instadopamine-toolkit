#!/usr/bin/env python3
"""Compile the published storyboard (wiki/<person>/storyboard.json) from the spec, word timings and frames.

Shot windows and caption times are resolved from anchors in the engine's lyrics file exactly as
video/app/src/timeline.ts resolves them: a shot starts `lead` seconds before its anchor word ([line, word]),
or `plus` seconds after the end of a word ({"after": [line, word], "plus": s}, for montage beats in the
pauses), or at an absolute time ({"at": s}, written by align_cuts_to_music.py when cuts sit on the music's beats);
the first shot at 0, the end card `gap_s` after the last line and runs to the end of the audio. The voice-over of a
shot is every word whose start falls inside its window. Start frames come from the hash-checked frames
manifest; styled frames (engine renders with the captions, `render.ts board`) are converted to WebP and
hashed. Nothing here calls a model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

PUNCT = re.compile(r'[«»"“”„.,:;!?…—–]')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def display(word, style):
    bare = PUNCT.sub('', word).strip()
    return bare.lower() if style == 'script' else bare.upper()


def resolve(spec, lyrics, duration):
    lines = lyrics['lines']
    flat = [dict(w, line=li, index=wi) for li, line in enumerate(lines) for wi, w in enumerate(line['words'])]

    def word(anchor):
        try:
            return lines[anchor[0]]['words'][anchor[1]]
        except (IndexError, TypeError):
            raise ValueError(f'Storyboard anchor not in lyrics: {anchor}')

    card = spec['format']['end_card']
    card_start = lines[card['start_after_line']]['end'] + card['gap_s']
    shots = [s for s in spec['shots'] if s['type'] != 'anchor']
    starts = []
    for i, s in enumerate(shots):
        cut = s['cut']
        if isinstance(cut, dict) and 'at' in cut:
            starts.append(float(cut['at']))
        elif s['type'] == 'card':
            starts.append(card_start)
        elif i == 0 or not cut:
            starts.append(0.0)
        elif isinstance(cut, dict):
            starts.append(word(cut['after'])['end'] + cut.get('plus', 0.0))
        else:
            starts.append(word(cut)['start'] - s['lead'])
    if any(b <= a for a, b in zip(starts, starts[1:])):
        raise ValueError('Shot anchors are not in time order')
    out = []
    for i, s in enumerate(shots):
        start = starts[i]
        end = duration if s['type'] == 'card' or i + 1 == len(shots) else starts[i + 1]
        caps = []
        for c in s['captions']:
            first, last = word(c['at']), word(c.get('to') or c['at'])
            gi0 = next(k for k, w in enumerate(flat) if w['line'] == c['at'][0] and w['index'] == c['at'][1])
            gi1 = next(k for k, w in enumerate(flat) if w['line'] == (c.get('to') or c['at'])[0] and w['index'] == (c.get('to') or c['at'])[1])
            words = [{'w': display(w['w'], c['style']), 'start': w['start']} for w in flat[gi0:gi1 + 1]]
            caps.append({'at': c['at'], **({'to': c['to']} if c.get('to') else {}), 'text': c.get('text') or ' '.join(w['w'] for w in words),
                         'style': c['style'], 'start': first['start'],
                         'end': None, 'words': words, 'last_word_end': last['end']})
        # a cut moved onto the music (align_cuts_to_music.py) may land up to 0.15 s after its first caption word:
        # the engine then shows that caption from the cut
        lag = 0.15 if isinstance(s['cut'], dict) and 'at' in s['cut'] else 0.0
        for k, c in enumerate(caps):
            c['end'] = round(caps[k + 1]['start'] if k + 1 < len(caps) else end, 3)
            if not (start - lag - 1e-6 <= c['start'] < end):
                raise ValueError(f"{s['id']}: caption «{c['text']}» starts outside its shot")
        spoken = [w for w in flat if start <= w['start'] < end]
        out.append({**s, 'start': round(start, 3), 'end': round(end, 3), 'duration': round(end - start, 3),
                    'vo': ' '.join(w['w'] for w in spoken), 'vo_lines': sorted({w['line'] for w in spoken}),
                    'words': [{'w': w['w'], 'start': w['start'], 'end': w['end']} for w in spoken], 'captions': caps})
    return out


def webp(src, dest, max_side=None, quality=85):
    with Image.open(src) as img:
        img = img.convert('RGB')
        if max_side:
            img.thumbnail((max_side, max_side), Image.LANCZOS)
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, 'WEBP', quality=quality, method=6)
        return img.size


def disclosure(wiki, spec):
    """The likeness/voice disclosure, naming the person from the wiki's edition.json (or the spec)."""
    edition = wiki / 'edition.json'
    name = json.loads(edition.read_text())['person']['display_name'] if edition.exists() else spec.get('person_name', 'the person')
    return (f'Planning material. Every frame is an AI-generated illustration of {name} made from her published '
            'photos (a synthetic likeness), and the voice is the consented synthetic self-presentation. Nothing here '
            'is a photograph or a recording of her. Show it only with her approval, and label it as AI-generated.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--lyrics', type=Path, required=True)
    parser.add_argument('--envelope', type=Path, required=True, help='Engine audio.json (duration)')
    parser.add_argument('--frames', type=Path, required=True, help='Frames manifest written by generate_storyboard_frames.py')
    parser.add_argument('--wiki', type=Path, required=True)
    parser.add_argument('--styled', type=Path, action='append', default=[], help='render.ts board output dir (index.json + PNGs)')
    parser.add_argument('--frames-dir', default='storyboard', help='Wiki folder of this storyboard\'s frames (styled frames go to <dir>/styled)')
    parser.add_argument('--styled-dir', help='Wiki folder for the styled frames (default <frames-dir>/styled)')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text())
    lyrics = json.loads(args.lyrics.read_text())
    duration = json.loads(args.envelope.read_text())['duration']
    frames = {r['shot']: r for r in json.loads(args.frames.read_text())['frames']}
    passport = {i['id']: i['title'] for i in json.loads((args.wiki / 'passport.json').read_text())['items']}
    shots = resolve(spec, lyrics, duration)

    styled = {}
    for directory in args.styled:
        index = json.loads((directory / 'index.json').read_text())
        mode = index['captions']
        for row in index['frames']:
            dest = args.wiki / (args.styled_dir or f'{args.frames_dir}/styled') / f"{row['id']}-{mode}.webp"
            thumb = dest.with_name(f"{row['id']}-{mode}-thumb.webp")
            size = webp(directory / row['file'], dest, quality=84)
            webp(directory / row['file'], thumb, max_side=960, quality=80)
            styled.setdefault(row['id'], {})[mode] = {'path': str(dest.relative_to(args.wiki)), 'sha256': sha(dest), 'width': size[0],
                                                      'height': size[1], 'thumbnail': str(thumb.relative_to(args.wiki)),
                                                      'thumbnail_sha256': sha(thumb), 't': row['t'], 'caption': row['caption'],
                                                      'renderer': 'video/app (pdoom-video engine, vertical edit) · render.ts board'}

    def frame_row(shot_id):
        row = frames.get(shot_id)
        if not row:
            return None
        for key in ('path', 'thumbnail'):
            if sha(args.wiki / row[key]) != row['sha256' if key == 'path' else 'thumbnail_sha256']:
                raise ValueError(f'{shot_id}: {key} hash mismatch')
        return {k: row[k] for k in ('path', 'thumbnail', 'sha256', 'thumbnail_sha256', 'width', 'height', 'kind', 'model', 'label',
                                    'prompt_sha256', 'generated_at')} | {'references': [r['ref'] for r in row['references']]}

    short = set(spec.get('short_cut_lines', []))
    published = []
    for n, s in enumerate(shots, 1):
        published.append({
            'id': s['id'], 'n': n, 'type': s['type'], 'title': s['title'], 'start': s['start'], 'end': s['end'], 'duration': s['duration'],
            'cut': s['cut'], 'lead': s['lead'], 'camera': s['camera'], 'caption_zone': s['caption_zone'],
            'caption_at': s.get('caption_at') or s['caption_zone'], 'vo': s['vo'], 'words': s['words'],
            'captions': s['captions'], 'scene': s['scene'], 'motion': s['motion'], 'basis': s['basis'],
            'passport': [{'id': p, 'title': passport.get(p, p)} for p in s['passport']],
            'references': s['refs'], 'person': s['person'],
            **{k: s[k] for k in ('subject', 'view', 'framing', 'angle', 'round') if k in s},
            'frame': frame_row(s['id']), 'styled': styled.get(s['id'], {}),
            'short_cut': bool(short) and (s['type'] == 'card' or (bool(s['vo_lines']) and set(s['vo_lines']) <= short)),
        })
    image_shots = [s for s in published if s['type'] != 'card']
    lengths = [s['duration'] for s in image_shots]
    short_shots = [s for s in published if s['short_cut']]
    anchor = next(s for s in spec['shots'] if s['type'] == 'anchor')
    board = {
        'schema': 'instadna.storyboard/v1', 'entity': spec['entity'], 'title': spec['title'], 'round': spec.get('round', 1),
        'compiled_at': datetime.now(timezone.utc).isoformat(), 'format': spec['format'], 'references': spec['references'],
        'audio': {**spec['audio'], 'duration_s': duration, 'lyrics_sha256': sha(args.lyrics), 'alignment': lyrics.get('notes', '')},
        'disclosure': disclosure(args.wiki, spec),
        'identity_anchor': {'id': anchor['id'], 'title': anchor['title'], 'scene': anchor['scene'], 'references': anchor['refs'],
                            'frame': frame_row(anchor['id'])},
        'prompt_blocks': {'style': spec['style'], 'identity': spec['identity'], 'rules': spec['rules']},
        'stats': {'shots': len(published), 'image_shots': len(image_shots), 'frames': sum(1 for s in published if s['frame']),
                  'captions': sum(len(s['captions']) for s in published), 'mean_shot_s': round(statistics.mean(lengths), 2),
                  'median_shot_s': round(statistics.median(lengths), 2), 'shortest_s': min(lengths), 'longest_s': max(lengths),
                  'short_cut': {'lines': sorted(short), 'shots': len(short_shots), 'duration_s': round(sum(s['duration'] for s in short_shots), 2)} if short else None},
        'shots': published,
    }
    args.out.write_text(json.dumps(board, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps(board['stats'], ensure_ascii=False))


if __name__ == '__main__':
    main()
