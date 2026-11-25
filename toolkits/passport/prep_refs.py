#!/usr/bin/env python3
"""Turn a person's raw inputs (HEIC/JPG photos, MOV/MP4 videos) into a reference pack for gen.py.

usage:
  prep_refs.py --person people/<slug> convert                 # photos -> work/<slug>/refs/*.jpg + contact sheet; list videos
  prep_refs.py --person people/<slug> frames VIDEO [--fps 2] [--start S] [--end E] [--box x0,y0,x1,y1] [--tag NAME]
                                                               # video frames + contact sheet labelled with timestamps
  prep_refs.py --person people/<slug> transcribe VIDEO         # local faster-whisper, word timestamps (no API)
  prep_refs.py --person people/<slug> picks [--force]          # people/<slug>/picks.json -> refpack crops + boards

Boxes are fractions of the (auto-rotated) frame: x0,y0,x1,y1. Everything is written under work/<slug>/
(gitignored, private); nothing here is published.
"""
import argparse, json, os, subprocess, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen import REPO, Person  # noqa: E402

PHOTO = {'.heic', '.heif', '.jpg', '.jpeg', '.png', '.webp'}
VIDEO = {'.mov', '.mp4', '.m4v'}


def open_photo(path):
    if path.suffix.lower() in {'.heic', '.heif'}:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    return ImageOps.exif_transpose(Image.open(path)).convert('RGB')


def video_frame(path, t):
    out = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(t), '-i', str(path), '-frames:v', '1', '-f', 'image2pipe',
                          '-vcodec', 'png', '-'], capture_output=True, check=True).stdout
    from io import BytesIO
    return Image.open(BytesIO(out)).convert('RGB')


def crop(img, box):
    if not box:
        return img
    w, h = img.size
    return img.crop((int(box[0] * w), int(box[1] * h), int(box[2] * w), int(box[3] * h)))


def contact(paths, out, cols=8, cell=220, labels=None):
    tiles = [Image.open(p).convert('RGB') for p in paths]
    if not tiles:
        return
    th = int(cell * tiles[0].height / tiles[0].width)
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * (cell + 4), rows * (th + 18)), 'white')
    draw = ImageDraw.Draw(sheet)
    for i, t in enumerate(tiles):
        t.thumbnail((cell, th))
        x, y = (i % cols) * (cell + 4), (i // cols) * (th + 18)
        sheet.paste(t, (x, y))
        draw.text((x + 2, y + th + 2), labels[i] if labels else Path(paths[i]).stem, fill='black')
    sheet.save(out, quality=88)
    print('contact sheet:', out)


def cmd_convert(person, work):
    src = REPO / person.cfg['inputs']
    dst = work / 'refs'
    dst.mkdir(parents=True, exist_ok=True)
    done = []
    for f in sorted(src.iterdir()):
        if f.suffix.lower() in PHOTO:
            img = open_photo(f)
            img.thumbnail((1600, 1600), Image.LANCZOS)
            out = dst / f'{f.stem}.jpg'
            img.save(out, quality=92)
            done.append(out)
            print(f'photo {f.name} -> {out.name} {img.size}')
        elif f.suffix.lower() in VIDEO:
            dur = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(f)],
                                 capture_output=True, text=True).stdout.strip()
            print(f'video {f.name} {float(dur):.1f}s -> run: frames {f.name} / transcribe {f.name}')
    contact(done, work / 'contact_photos.jpg', cols=7)


def cmd_frames(person, work, a):
    src = REPO / person.cfg['inputs'] / a.video
    tag = a.tag or Path(a.video).stem
    out = work / 'frames' / tag
    out.mkdir(parents=True, exist_ok=True)
    vf = [f'fps={a.fps}']
    if a.box:
        x0, y0, x1, y1 = map(float, a.box.split(','))
        vf.append(f'crop=iw*{x1 - x0}:ih*{y1 - y0}:iw*{x0}:ih*{y0}')
    vf.append('scale=480:-2')
    cmd = ['ffmpeg', '-v', 'error', '-y'] + (['-ss', str(a.start)] if a.start else []) + (['-to', str(a.end)] if a.end else [])
    subprocess.run(cmd + ['-i', str(src), '-vf', ','.join(vf), '-q:v', '3', str(out / 'f_%04d.jpg')], check=True)
    files = sorted(out.glob('f_*.jpg'))
    start = a.start or 0
    labels = [f't={start + i / a.fps:.2f}s' for i in range(len(files))]
    contact(files, work / f'contact_{tag}.jpg', cols=10, cell=150, labels=labels)
    print(f'{len(files)} frames in {out}; the label under each tile is its timestamp for picks.json')


def cmd_transcribe(person, work, a):
    src = REPO / person.cfg['inputs'] / a.video
    wav = work / f'{Path(a.video).stem}.wav'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(src), '-vn', '-ac', '1', '-ar', '16000', str(wav)], check=True)
    os.environ.setdefault('HF_HOME', '/mnt/data/root/cache-huggingface')
    os.environ.setdefault('HF_HUB_OFFLINE', '1')
    from faster_whisper import WhisperModel  # local model; no API, no credits
    model = WhisperModel(a.model, device='cpu', compute_type='int8')
    segs, info = model.transcribe(str(wav), word_timestamps=True)
    rows = []
    for s in segs:
        print(f'[{s.start:6.2f}-{s.end:6.2f}] {s.text}')
        rows.append({'start': s.start, 'end': s.end, 'text': s.text,
                     'words': [{'w': w.word, 's': w.start, 'e': w.end} for w in (s.words or [])]})
    out = work / f'{Path(a.video).stem}.transcript.json'
    out.write_text(json.dumps({'language': info.language, 'segments': rows}, ensure_ascii=False, indent=1))
    print('transcript:', out)


def cmd_picks(person, a):
    picks = json.loads((person.dir / 'picks.json').read_text())
    inputs = REPO / person.cfg['inputs']
    person.refpack.mkdir(parents=True, exist_ok=True)
    for c in picks.get('crops', []):
        out = person.refpack / f"{c['id']}.jpg"
        if out.exists() and not a.force:
            continue
        src = c['src']
        if src.startswith('generated:'):
            img = Image.open(person.out / src.split(':', 1)[1]).convert('RGB')
        elif 't' in c:
            img = video_frame(inputs / src, c['t'])
        else:
            img = open_photo(inputs / src)
        if c.get('rotate'):
            img = img.rotate(c['rotate'], expand=True)
        img = crop(img, c.get('box'))
        img.thumbnail((c.get('max', 1024),) * 2, Image.LANCZOS)
        img.save(out, quality=93)
        print('crop', out.name, img.size)
    for b in picks.get('boards', []):
        out = person.refpack / f"{b['id']}.jpg"
        if out.exists() and not a.force:
            continue
        tiles = [Image.open(person.refpack / f'{t}.jpg').convert('RGB') for t in b['tiles']]
        cols, cell = b.get('cols', 3), b.get('cell', 512)
        ch = b.get('cell_h', cell)
        rows = (len(tiles) + cols - 1) // cols
        board = Image.new('RGB', (cols * (cell + 12), rows * (ch + 12)), 'white')
        for i, t in enumerate(tiles):
            t = ImageOps.contain(t, (cell, ch))
            x = (i % cols) * (cell + 12) + 6 + (cell - t.width) // 2
            y = (i // cols) * (ch + 12) + 6 + (ch - t.height) // 2
            board.paste(t, (x, y))
        board.save(out, quality=93)
        print('board', out.name, board.size)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--person', required=True)
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('convert')
    f = sub.add_parser('frames')
    f.add_argument('video'); f.add_argument('--fps', type=float, default=2); f.add_argument('--start', type=float)
    f.add_argument('--end', type=float); f.add_argument('--box'); f.add_argument('--tag')
    t = sub.add_parser('transcribe')
    t.add_argument('video'); t.add_argument('--model', default='mobiuslabsgmbh/faster-whisper-large-v3-turbo')
    p = sub.add_parser('picks')
    p.add_argument('--force', action='store_true')
    a = ap.parse_args()
    person = Person(a.person)
    work = REPO / 'work' / person.cfg['slug']
    work.mkdir(parents=True, exist_ok=True)
    {'convert': lambda: cmd_convert(person, work), 'frames': lambda: cmd_frames(person, work, a),
     'transcribe': lambda: cmd_transcribe(person, work, a), 'picks': lambda: cmd_picks(person, a)}[a.cmd]()


if __name__ == '__main__':
    main()
