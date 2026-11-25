#!/usr/bin/env python3
"""Analyze every collected media item with a video/audio-native Gemini model.

Builds one item per Instagram post, Highlight story, Telegram media message or
YouTube video, sends the original media (YouTube by public URL) plus collector
metadata, and stores validated JSON in a private, resumable analysis directory.
GEMINI_API_KEY is read from the environment; usage accrues API charges.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from instadna import gemini  # noqa: E402
from instadna.media_analysis import SYSTEM, context_text, signature, validate  # noqa: E402

MIME = {'.mp4': 'video/mp4', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp',
        '.ogg': 'audio/ogg', '.mp3': 'audio/mpeg', '.m4a': 'audio/mp4', '.pdf': 'application/pdf', '.mov': 'video/mov'}


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.chmod(0o600)
    tmp.replace(path)


def duration(path):
    try:
        out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', str(path)],
                             capture_output=True, text=True, check=True).stdout
        return round(float(json.loads(out)['format']['duration']), 3)
    except (subprocess.CalledProcessError, KeyError, ValueError):
        return None


def instagram_items(root, creator):
    manifest = json.loads((root / 'manifest.json').read_text())
    for post in manifest['posts']:
        if post.get('status') not in {'downloaded', 'partial'}:
            continue
        media = []
        for a in post['assets']:
            if a.get('status') != 'downloaded':
                continue
            path = root / a['path']
            media.append({'index': a['index'], 'kind': a['kind'], 'path': str(path), 'sha256': a['sha256'],
                          'duration_s': duration(path) if a['kind'] == 'video' else None, 'mime': MIME[path.suffix]})
        if not media:
            continue
        videos = [m['duration_s'] or 0 for m in media if m['kind'] == 'video']
        kind = 'reel' if post.get('product_type') == 'clips' else post.get('type') or 'post'
        yield {'item_id': 'ig:' + post['shortcode'], 'platform': 'instagram', 'kind': kind, 'source_url': post['url'],
               'published_at': post.get('published_at'), 'duration_s': max(videos) if len(media) == 1 and videos else None,
               'media': media,
               'context': {'creator': creator, 'publishing_account': post.get('owner'), 'coauthors': post.get('coauthors'),
                           'caption': post.get('caption'), 'music_metadata': post.get('music'),
                           'tagged_accounts': post.get('usertags'), 'location_tag': (post.get('location') or {}).get('name'),
                           'paid_partnership_label': post.get('paid_partnership'), 'product_type': post.get('product_type')}}


def telegram_items(root, creator):
    """Public-preview downloads first; files fetched by message ID (sibling `mtproto/`) fill the gaps."""
    rows = [json.loads(line) for line in (root / 'messages.jsonl').read_text().split('\n') if line.strip()]
    downloads = json.loads((root / 'downloads.json').read_text())
    extra_root = root.parent / 'mtproto'
    extra = json.loads((extra_root / 'manifest.json').read_text())['files'] if (extra_root / 'manifest.json').exists() else {}
    for row in rows:
        media, documents = [], 0
        for i, m in enumerate(row['media']):
            d = downloads.get(f"{row['id']}-{i}")
            if d and d.get('status') == 'downloaded':
                path, digest, tg_kind = root / d['path'], d['sha256'], m['kind']
            else:
                # Album documents are separate consecutive messages listed under the first one.
                target = row['id'] + documents if m['kind'] == 'document' else m['message_id']
                f = extra.get(str(target))
                if not f or f.get('status') != 'downloaded':
                    documents += m['kind'] == 'document'
                    continue
                path, digest = extra_root / f['path'], f['sha256']
                tg_kind = {'video': 'video', 'round_video': 'round_video', 'audio': 'music_file'}.get(f['kind'], 'document')
            documents += m['kind'] == 'document'
            suffix = path.suffix.lower()
            if tg_kind == 'document' and suffix in {'.png', '.jpg', '.jpeg'}:
                tg_kind = 'image_file'
            kind = {'voice': 'audio', 'music_file': 'audio', 'round_video': 'video', 'video': 'video', 'photo': 'image', 'image_file': 'image'}.get(tg_kind, 'document')
            if kind == 'document' and suffix != '.pdf':
                continue
            mime = MIME.get(suffix)
            if not mime:
                raise ValueError(f'No supported MIME type for {path.name}')
            media.append({'index': i, 'kind': kind, 'telegram_kind': tg_kind, 'path': str(path), 'sha256': digest,
                          'duration_s': duration(path) if kind in {'video', 'audio'} else None, 'mime': mime})
        if not media:
            continue
        kinds = {m['telegram_kind'] for m in media}
        kind = ('voice' if kinds == {'voice'} else 'round_video' if 'round_video' in kinds else 'video' if 'video' in kinds
                else 'music_files' if kinds == {'music_file'} else 'document' if 'document' in kinds else 'photos')
        timed = [m['duration_s'] or 0 for m in media if m['kind'] in {'video', 'audio'}]
        yield {'item_id': f"tg:{row['id']}", 'platform': 'telegram', 'kind': kind, 'source_url': row['source_url'],
               'published_at': row['published_at'], 'duration_s': max(timed) if len(media) == 1 and timed else None,
               'media': media,
               'context': {'creator': creator, 'channel': row['source_url'].split('/')[3],
                           'post_text': row['text'], 'forwarded_from': row.get('forward'), 'author_signature': row.get('author_signature'),
                           'links': row.get('links'), 'reply_to_message': row.get('reply_to'),
                           # Only present for document posts, so earlier analyses keep their cache key.
                           **({'document_titles': titles} if (titles := [m.get('title') for m in row['media'] if m['kind'] == 'document']) else {})}}


def youtube_items(root, creator):
    for line in (root / 'videos.jsonl').read_text().split('\n'):
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get('status') != 'ok':
            continue
        kind = 'youtube_short' if row['tab'] == 'shorts' else 'youtube_video'
        yield {'item_id': 'yt:' + row['id'], 'platform': 'youtube', 'kind': kind, 'source_url': row['url'],
               'published_at': row.get('published_date'), 'duration_s': row.get('duration_s'),
               'media': [{'index': 0, 'kind': 'video', 'youtube_url': row['url'], 'duration_s': row.get('duration_s')}],
               'context': {'creator': creator, 'title': row.get('title'), 'description': row.get('description'),
                           'date_basis': row.get('date_basis'), 'tab': row['tab']}}


def highlight_items(root, creator):
    manifest = json.loads((root / 'manifest.json').read_text())
    for collection in manifest['collections']:
        for item in collection['items']:
            assets = [a for a in item.get('assets', []) if a.get('status') == 'downloaded']
            chosen = next((a for a in assets if a['kind'] == 'video'), assets[0] if assets else None)
            if not chosen:
                continue
            path = root / chosen['path']
            kind = 'video' if chosen['kind'] == 'video' else 'image'
            yield {'item_id': f"igh:{item['story_id']}", 'platform': 'instagram_highlight', 'kind': 'story_' + kind,
                   'source_url': item['source_url'],
                   'published_at': datetime.fromtimestamp(item['taken_at'], timezone.utc).isoformat() if item.get('taken_at') else None,
                   'duration_s': duration(path) if kind == 'video' else None,
                   'media': [{'index': 0, 'kind': kind, 'path': str(path), 'sha256': chosen['sha256'],
                              'duration_s': duration(path) if kind == 'video' else None, 'mime': MIME[path.suffix]}],
                   'context': {'creator': creator, 'highlight_title': collection.get('title'), 'highlight_id': collection['highlight_id'],
                               'position_in_highlight': item['index'] + 1}}


def story_items(root, creator):
    """Stories live on the retrieval day, captured in the Highlight manifest layout."""
    for item in highlight_items(root, creator):
        story = item['item_id'].split(':', 1)[1]
        yield {**item, 'item_id': 'igs:' + story, 'platform': 'instagram_story', 'kind': item['kind'],
               'context': {**item['context'], 'highlight_title': None, 'note': 'Live story at retrieval, not saved to a Highlight'}}


BUILDERS = {'instagram': instagram_items, 'telegram': telegram_items, 'youtube': youtube_items, 'highlights': highlight_items,
            'stories': story_items}


CHUNK_OVER = 480
CHUNK = 300
MERGE = """You receive, in order, chunk-level JSON analyses of ONE long media item (each chunk covers a stated time window).
Using ONLY their content, return JSON with keys: item_id, summary (80-160 words), content_format, languages, speakers (merge equivalent labels;
keep attribution_basis), narrative {hook, structure, payoff, cta, persuasion_devices}, phrases (best 12 verbatim creator phrases with times),
topics, offers_products, claims, people_named, reference_moments (best 8 with times), uncertainties. Never invent content or times."""


PDF_LIMIT = 45 * 1024 * 1024
PDF_PAGES = 40


def pdf_pages(path):
    """Render the first pages of an oversized PDF to JPEG (poppler) in a private temporary directory."""
    import base64
    import tempfile
    with tempfile.TemporaryDirectory(dir=path.parent) as tmp:
        subprocess.run(['pdftoppm', '-jpeg', '-r', '80', '-l', str(PDF_PAGES), str(path), str(Path(tmp) / 'page')], check=True,
                       capture_output=True)
        return [base64.b64encode(p.read_bytes()).decode() for p in sorted(Path(tmp).glob('page-*.jpg'))]


def _record_usage(meta, totals, lock):
    usage = meta.get('usage') or {}
    with lock:
        totals['input'] += usage.get('promptTokenCount', 0)
        totals['output'] += usage.get('candidatesTokenCount', 0) + usage.get('thoughtsTokenCount', 0)


def _media_parts(item, uploaded, window=None):
    parts = []
    for m in item['media']:
        clip = {'video_metadata': {'start_offset': f'{window[0]}s', 'end_offset': f'{window[1]}s'}} if window and m['kind'] == 'video' else {}
        if 'youtube_url' in m:
            parts.append({'file_data': {'file_uri': m['youtube_url']}, **clip})
            continue
        if m['mime'] == 'application/pdf' and Path(m['path']).stat().st_size > PDF_LIMIT:
            parts.append({'text': f"MEDIA index {m['index']} (PDF too large to send whole; first {PDF_PAGES} pages as images):"})
            parts.extend({'inline_data': {'mime_type': 'image/jpeg', 'data': page}} for page in pdf_pages(Path(m['path'])))
            continue
        cached = next((f for f in uploaded if f['_path'] == m['path']), None)
        if cached:
            part = {'file_data': {'mime_type': m['mime'], 'file_uri': cached['uri']}}
        else:
            part, file = gemini.media_part(Path(m['path']), m['mime'])
            if file:
                file['_path'] = m['path']
                uploaded.append(file)
        parts.append({'text': f"MEDIA index {m['index']} ({m['kind']}):"})
        parts.append({**part, **clip})
    return parts


def _chunked(item, model, uploaded, totals, lock):
    total = item['duration_s']
    windows = [(s, min(total, s + CHUNK)) for s in range(0, int(total), CHUNK) if min(total, s + CHUNK) - s > 3]
    chunks, metas = [], []
    for start, end in windows:
        note = (f'\nTHIS REQUEST COVERS ONLY seconds {start}-{end:.1f} of the full media (chunk {len(chunks) + 1} of {len(windows)}). '
                'Report every time in seconds from the START OF THE FULL MEDIA, within this window.')
        result, meta = gemini.generate(model, [{'text': context_text(item) + note}] + _media_parts(item, uploaded, (start, end)),
                                       system=SYSTEM, max_output_tokens=32768, timeout=900)
        _record_usage(meta, totals, lock)
        issues = validate(result, item)
        for row in result.get('transcript') or []:
            if isinstance(row.get('start'), (int, float)) and not start - 3 <= row['start'] <= end + 3:
                issues.append(f"chunk time outside window: {row['start']} not in {start}-{end}")
        chunks.append({'window': [start, end], 'analysis': result, 'validation_issues': issues, 'provenance': meta})
        metas.append(meta)
    digest = [{'window': c['window'], **{k: c['analysis'].get(k) for k in ['summary', 'content_format', 'languages', 'speakers', 'narrative',
              'phrases', 'topics', 'offers_products', 'claims', 'people_named', 'reference_moments', 'uncertainties']}} for c in chunks]
    merged, meta = gemini.generate(model, [{'text': f"item_id: {item['item_id']}\n" + json.dumps(digest, ensure_ascii=False)}],
                                   system=MERGE, max_output_tokens=16384)
    _record_usage(meta, totals, lock)
    if merged.get('item_id') != item['item_id']:
        raise ValueError('Merged analysis item ID mismatch')
    combine = lambda key: [row for c in chunks for row in (c['analysis'].get(key) or [])]
    visual = {k: [row for c in chunks for row in ((c['analysis'].get('visual') or {}).get(k) or [])]
              for k in ['setting', 'wardrobe', 'accessories', 'objects_props', 'gestures_expressions']}
    first = chunks[0]['analysis']
    visual.update({k: (first.get('visual') or {}).get(k) for k in ['appearance', 'camera_framing', 'lighting_palette', 'edit']})
    merged.update(transcript=combine('transcript'), on_screen_text=combine('on_screen_text'), visual=visual,
                  audio={**(first.get('audio') or {}), 'by_chunk': [{'window': c['window'], **(c['analysis'].get('audio') or {})} for c in chunks]})
    return merged, {'model': meta.get('model'), 'mode': f'{len(chunks)} clipped windows of {CHUNK}s + text merge',
                    'chunk_provenance': metas, 'merge_provenance': meta}, chunks


LONGFORM_OVER = 1200
AUDIO_WINDOW = 600
LONG_TRANSCRIBE = """This audio is seconds {start}-{end} of a longer recording published by the creator in the CONTEXT.
Transcribe ALL speech verbatim in the original language(s) (keep surzhyk, slang, fillers). Times are seconds from the START OF THE FULL
RECORDING, inside this window. Label speakers by role from context only (never by voice identity): "creator" for the account owner when
she is the host/first-person narrator, otherwise "guest 1", "participant", "interviewer", "unknown".
Return JSON {{"segments": [{{"start", "end", "speaker", "text"}}], "delivery": one English sentence on the creator's pace, energy and tone here,
"music": null or a short description}}."""
LONG_FRAMES = """These still frames were sampled evenly across one long recording (times are in the labels). Describe only what is visible.
Return JSON {"visual": {"setting": [{"time", "description"}], "appearance": {"hair", "makeup", "nails", "other_visible"},
"wardrobe": [{"time", "item", "colors", "details"}], "accessories": [{"time", "item", "details"}], "objects_props": [{"time", "item", "details"}],
"camera_framing", "lighting_palette", "gestures_expressions": [{"time", "description"}], "edit": {"approx_shot_changes", "pace", "transitions",
"captions_style", "graphics", "b_roll"}}, "on_screen_text": [{"time", "text", "kind"}], "reference_moments": [{"time", "shows", "use"}]}"""
LONG_MERGE = """You receive the full machine transcript (with times) and frame notes of ONE long recording by the creator in the CONTEXT.
Using ONLY them return JSON with: item_id, summary (100-180 words), content_format, languages {spoken, written, notes},
speakers [{label, role: account_owner|guest|client|interviewer|voiceover|song_vocals|unknown, attribution_basis, approx_share_pct}],
narrative {hook:{time, text, technique}, structure, payoff, cta:{time, text, mechanism}, persuasion_devices},
phrases (up to 12 verbatim creator phrases with times and function), topics, offers_products, claims (dated self-reports with times),
people_named, uncertainties. Never invent content or times."""


def _longform(item, model, totals, lock):
    """Long recordings: chunked audio transcription + evenly sampled frames + text merge (no continuous video tokens)."""
    import base64
    import tempfile
    media = item['media'][0]
    total = item['duration_s']
    with tempfile.TemporaryDirectory(dir=Path(media['path']).parent) as tmp:
        tmp = Path(tmp)
        audio = tmp / 'audio.mp3'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', media['path'], '-vn', '-ac', '1', '-ar', '16000', '-b:a', '40k', str(audio)], check=True)
        windows = [(s, min(total, s + AUDIO_WINDOW)) for s in range(0, int(total), AUDIO_WINDOW) if min(total, s + AUDIO_WINDOW) - s > 3]

        def transcribe(window):
            start, end = window
            clip = tmp / f'w{start}.mp3'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(start), '-t', str(end - start), '-i', str(audio), '-c', 'copy', str(clip)], check=True)
            part, _ = gemini.media_part(clip, 'audio/mpeg')
            result, meta = gemini.generate(model, [{'text': context_text(item)}, {'text': LONG_TRANSCRIBE.format(start=start, end=f'{end:.0f}')}, part],
                                           max_output_tokens=65536, timeout=900)
            _record_usage(meta, totals, lock)
            rows = [r for r in result.get('segments') or [] if isinstance(r.get('start'), (int, float))]
            return {'window': [start, end], 'analysis': {'transcript': rows, 'audio': {'voice_delivery': {'notable_habits': result.get('delivery')},
                                                                                       'music': {'present': bool(result.get('music')), 'description': result.get('music')}}},
                    'provenance': meta}

        with ThreadPoolExecutor(max_workers=4) as pool:
            chunks = list(pool.map(transcribe, windows))
        times = [round(total * (k + .5) / 6, 1) for k in range(6)]
        parts = [{'text': LONG_FRAMES}]
        for t in times:
            frame = tmp / f'f{t}.jpg'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(t), '-i', media['path'], '-frames:v', '1', '-vf', 'scale=720:-2', str(frame)], check=True)
            parts += [{'text': f'Frame at {t} s:'}, {'inline_data': {'mime_type': 'image/jpeg', 'data': base64.b64encode(frame.read_bytes()).decode()}}]
        frames, meta_f = gemini.generate(model, parts, max_output_tokens=16384)
        _record_usage(meta_f, totals, lock)
    transcript = [r for c in chunks for r in c['analysis']['transcript']]
    lines = '\n'.join(f"[{r['start']:.0f}s] {r.get('speaker') or ''}: {r.get('text') or ''}" for r in transcript)
    merged, meta_m = gemini.generate(model, [{'text': context_text(item) + '\nFRAME NOTES:\n' + json.dumps(frames, ensure_ascii=False) + '\nTRANSCRIPT:\n' + lines}],
                                     system=LONG_MERGE, max_output_tokens=32768, timeout=900)
    _record_usage(meta_m, totals, lock)
    if merged.get('item_id') != item['item_id']:
        raise ValueError('Merged analysis item ID mismatch')
    merged.update(transcript=transcript, on_screen_text=frames.get('on_screen_text') or [], visual=frames.get('visual') or {},
                  reference_moments=frames.get('reference_moments') or [],
                  audio={**chunks[0]['analysis']['audio'], 'by_chunk': [{'window': c['window'], **c['analysis']['audio']} for c in chunks]})
    issues = [f"chunk time outside window: {r['start']}" for c in chunks for r in c['analysis']['transcript']
              if not c['window'][0] - 3 <= r['start'] <= c['window'][1] + 3]
    provenance = {'model': meta_m.get('model'), 'mode': f'long-form: {len(chunks)} audio windows of {AUDIO_WINDOW}s + 6 frames + text merge',
                  'chunk_provenance': [c['provenance'] for c in chunks], 'frames_provenance': meta_f, 'merge_provenance': meta_m}
    return merged, provenance, chunks, issues


def run_item(item, out, model, totals, lock):
    path = out / (item['item_id'].replace(':', '/') + '.json')
    sig = signature(item, model)
    if path.exists():
        old = json.loads(path.read_text())
        if old.get('signature') == sig and old.get('status') == 'ok':
            return 'cached', item['item_id']
    uploaded = []
    try:
        timed = [m for m in item['media'] if m['kind'] == 'video']
        chunks = None
        if len(item['media']) == 1 and timed and 'path' in timed[0] and (item.get('duration_s') or 0) > LONGFORM_OVER:
            result, meta, chunks, issues = _longform(item, model, totals, lock)
        elif len(item['media']) == 1 and timed and (item.get('duration_s') or 0) > CHUNK_OVER:
            result, meta, chunks = _chunked(item, model, uploaded, totals, lock)
            issues = [i for c in chunks for i in c['validation_issues']]
        else:
            result, meta = gemini.generate(model, [{'text': context_text(item)}] + _media_parts(item, uploaded),
                                           system=SYSTEM, max_output_tokens=32768, timeout=900)
            _record_usage(meta, totals, lock)
            issues = validate(result, item)
        record = {'status': 'ok', 'item_id': item['item_id'], 'platform': item['platform'], 'kind': item['kind'],
                  'source_url': item['source_url'], 'published_at': item['published_at'], 'duration_s': item.get('duration_s'),
                  'media': [{k: v for k, v in m.items() if k != 'path'} for m in item['media']],
                  'signature': sig, 'analysed_at': now(), 'provenance': meta, 'validation_issues': issues,
                  'review_status': 'machine_observations_pending_editorial_review', 'analysis': result}
        if chunks:
            record['chunks'] = chunks
        save(path, record)
        return 'analysed', item['item_id']
    except Exception as error:  # recorded and retried on the next run
        save(path.with_suffix('.error.json'), {'item_id': item['item_id'], 'error': str(error)[:600], 'at': now()})
        return 'failed', item['item_id']
    finally:
        for file in uploaded:
            gemini.delete(file['name'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--platform', choices=sorted(BUILDERS), required=True)
    parser.add_argument('--root', type=Path, required=True, help='Private corpus for this platform')
    parser.add_argument('--out', type=Path, required=True, help='Private analysis directory')
    parser.add_argument('--creator', required=True, help='Owner-supplied identity context, e.g. "Name (@handle)"')
    parser.add_argument('--model', default='gemini-3.8-flash')
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--ids', help='Comma-separated item IDs to (re)run')
    parser.add_argument('--kinds', help='Comma-separated item kinds to include')
    args = parser.parse_args()
    os.umask(0o077)
    items = list(BUILDERS[args.platform](args.root.resolve(), args.creator))
    if args.ids:
        wanted = set(args.ids.split(','))
        items = [i for i in items if i['item_id'] in wanted]
    if args.kinds:
        kinds = set(args.kinds.split(','))
        items = [i for i in items if i['kind'] in kinds]
    items = items[:args.limit] if args.limit else items
    totals, lock, counts = {'input': 0, 'output': 0}, threading.Lock(), {}
    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_item, item, args.out.resolve(), args.model, totals, lock) for item in items]
        for i, future in enumerate(as_completed(futures), 1):
            status, item_id = future.result()
            counts[status] = counts.get(status, 0) + 1
            if status == 'failed' or i % 10 == 0 or i == len(items):
                print(json.dumps({'done': i, 'of': len(items), 'last': item_id, 'status': status, **counts, 'tokens': totals,
                                  'minutes': round((time.time() - started) / 60, 1)}), flush=True)
    save(args.out.resolve() / f'run-{args.platform}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json',
         {'platform': args.platform, 'model': args.model, 'items': len(items), 'counts': counts, 'tokens': totals, 'finished_at': now()})


if __name__ == '__main__':
    main()
