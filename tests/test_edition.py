import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from instadna.edition import build_edition, check_source, load_phrases, summarize_time

AS_OF = '2026-10-02'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class TemporalTests(unittest.TestCase):
    def test_recency_and_recurrence_are_separate(self):
        recent_once = summarize_time([{'source_id': 'ig:a', 'published_at': '2026-09-30T10:00:00+00:00'}], AS_OF)
        self.assertEqual((recent_once['recency'], recent_once['recurrence']), ('recent', 'not_established'))
        old_repeat = summarize_time([
            {'source_id': 'tg:1', 'published_at': '2022-01-01T00:00:00+00:00', 'occasion_id': 'a', 'occasion_basis': 'different months'},
            {'source_id': 'tg:2', 'published_at': '2022-06-01T00:00:00+00:00', 'occasion_id': 'b', 'occasion_basis': 'different months'}], AS_OF)
        self.assertEqual((old_repeat['recency'], old_repeat['recurrence'], old_repeat['known_occasions']), ('historical', 'across_occasions', 2))
        self.assertEqual(summarize_time([{'source_id': 'yt:x', 'published_at': None}], AS_OF)['recency'], 'unknown')

    def test_future_dates_and_unexplained_occasions_fail(self):
        with self.assertRaisesRegex(ValueError, 'postdate'):
            summarize_time([{'source_id': 'ig:a', 'published_at': '2026-12-01'}], AS_OF)
        with self.assertRaisesRegex(ValueError, 'basis'):
            summarize_time([{'source_id': 'ig:a', 'published_at': '2026-01-01', 'occasion_id': 'trip'}], AS_OF)
        with self.assertRaisesRegex(ValueError, 'timezone'):
            summarize_time([{'source_id': 'ig:a', 'published_at': '2026-01-01T10:00:00'}], AS_OF)

    def test_source_urls_must_match_platform_and_id(self):
        check_source({'platform': 'telegram', 'source_id': 'tg:5', 'source_url': 'https://t.me/example_channel/5'})
        check_source({'platform': 'youtube', 'source_id': 'yt:abc', 'source_url': 'https://www.youtube.com/watch?v=abc123XYZ00'})
        for row in [{'platform': 'telegram', 'source_id': 'ig:5', 'source_url': 'https://t.me/example_channel/5'},
                    {'platform': 'instagram', 'source_id': 'ig:x', 'source_url': 'https://evil.example/p/x/'},
                    {'platform': 'telegram', 'source_id': 'tg:5', 'source_url': 'https://t.me/example_channel/5', 'published_at': '2026-01-01'}]:
            with self.assertRaises(ValueError):
                check_source(row)


class EditionBuildTests(unittest.TestCase):
    def fixture(self, root):
        wiki = root / 'wiki'
        for folder in ['references', 'generated', 'audio']:
            (wiki / folder).mkdir(parents=True)
        (wiki / 'publication-policy.json').write_text(json.dumps({'version': 1, 'requires_authentication': True}))
        (wiki / 'edition.json').write_text(json.dumps({
            'schema': 'instadna.edition/v1', 'person': {'display_name': 'Test Person', 'subtitle': 'DNA', 'monogram': 'TP'},
            'nav': [['index', 'Overview'], ['#g', 'Group'], ['phrases', 'Phrases']], 'stats': [[3, 'platforms']],
            'eyebrow': 'E', 'status': 'S', 'footer': 'F', 'footer_note': 'N', 'wide_pages': ['index']}))
        (wiki / 'index.md').write_text('# Overview\n\n<div id="evidence-atlas"></div>\n\n<div id="passport-items"></div>\n\n<div id="chart-cadence"></div>\n\n[Phrases](phrases.md)\n')
        (wiki / 'phrases.md').write_text('# Phrases\n\n<div id="phrase-bank"></div>\n\n<div id="data-room"></div>\n')
        Image.new('RGB', (60, 80), 'white').save(wiki / 'references/A001.webp', 'WEBP')
        Image.new('RGB', (30, 40), 'white').save(wiki / 'references/A001-thumb.webp', 'WEBP')
        (wiki / 'atlas.json').write_text(json.dumps({'schema': 'instadna.atlas/v1', 'as_of': AS_OF, 'references': [{
            'id': 'A001', 'platform': 'telegram', 'source_id': 'tg:7', 'source_url': 'https://t.me/chan_name/7',
            'published_at': '2026-09-01T10:00:00+00:00', 'date_basis': 'Telegram message date', 'asset_index': 0, 'time_seconds': 2.0,
            'kind': 'video_frame', 'title': 'Necklaces', 'category': 'accessories', 'description': 'd', 'use': 'u', 'limit': 'l',
            'image': 'references/A001.webp', 'thumbnail': 'references/A001-thumb.webp', 'width': 60, 'height': 80,
            'sha256': sha(wiki / 'references/A001.webp'), 'thumbnail_sha256': sha(wiki / 'references/A001-thumb.webp'),
            'source_media_sha256': 'a' * 64}]}))
        Image.new('RGB', (64, 64), 'beige').save(wiki / 'generated/item-necklace.png')
        Image.new('RGB', (32, 32), 'beige').save(wiki / 'generated/item-necklace.webp', 'WEBP')
        (wiki / 'generated-images.json').write_text(json.dumps({'images': [{
            'path': 'generated/item-necklace.png', 'thumbnail': 'generated/item-necklace.webp', 'kind': 'ai_visual_synthesis',
            'model': 'gemini-3-pro-image', 'width': 64, 'height': 64, 'sha256': sha(wiki / 'generated/item-necklace.png'),
            'thumbnail_sha256': sha(wiki / 'generated/item-necklace.webp')}]}))
        (wiki / 'passport.json').write_text(json.dumps({'schema': 'instadna.passport/v1', 'as_of': AS_OF, 'items': [{
            'id': 'necklace', 'title': 'Layered silver necklaces', 'category': 'accessories', 'image': 'generated/item-necklace.png',
            'thumbnail': 'generated/item-necklace.webp', 'image_kind': 'ai_reconstruction', 'description': 'd', 'context': 'c',
            'usage_brief': 'b', 'limit': 'l', 'recurrence_note': 'r',
            'evidence': [{'platform': 'telegram', 'source_id': 'tg:7', 'source_url': 'https://t.me/chan_name/7', 'atlas_id': 'A001',
                          'published_at': '2026-09-01T10:00:00+00:00', 'date_basis': 'Telegram message date', 'locator': 'asset 0 · 2s'}]}]}))
        clip = wiki / 'audio/phrase-p001.mp3'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=220:duration=1.5', '-ac', '1', '-b:a', '64k', str(clip)], check=True)
        length = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(clip)]))
        (wiki / 'phrases.json').write_text(json.dumps({'schema': 'instadna.phrases/v2', 'audience': 'private', 'as_of': AS_OF,
            'sources': [{'id': 'tg:7', 'platform': 'telegram', 'url': 'https://t.me/chan_name/7', 'published_at': '2026-09-01T10:00:00+00:00',
                         'date_basis': 'Telegram message date', 'audio_sha256': 'b' * 64, 'duration_s': 60.0}],
            'families': [{'id': 'address', 'title': 'Audience address', 'context': 'c'}],
            'spoken': [{'id': 'p001', 'source_id': 'tg:7', 'family': 'address', 'text': 'Слушайте', 'gloss': 'Listen', 'language': 'ru',
                        'start_s': 1.0, 'end_s': 1.0 + length, 'duration_s': length, 'path': 'audio/phrase-p001.mp3', 'sha256': sha(clip),
                        'delivery': 'd', 'context': 'c', 'attribution': 'a', 'review_method': 'r', 'limitations': 'l'}],
            'written': [{'id': 'w001', 'source_id': 'tg:7', 'family': 'address', 'text': 'Слушайте', 'gloss': 'Listen', 'language': 'ru', 'context': 'c'}]}))
        (wiki / 'charts.json').write_text(json.dumps({'schema': 'instadna.charts/v1', 'charts': [{
            'id': 'cadence', 'type': 'stacked', 'title': 'Items', 'categories': ['2025', '2026'],
            'series': [{'name': 'Instagram', 'values': [3, 4]}, {'name': 'Telegram', 'values': [1, 0]}]}]}))
        room = root / 'room'
        (room / 'items').mkdir(parents=True)
        (room / 'index.json').write_text(json.dumps({'schema': 'instadna.dataroom/v1', 'items': [{
            'id': 'tg:7', 'platform': 'telegram', 'url': 'https://t.me/chan_name/7', 'published_at': '2026-09-01T10:00:00+00:00'}]}))
        (room / 'items/telegram-000.json').write_text('{}')
        return wiki, room

    def test_protected_edition_builds_all_widgets_without_inline_styles(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wiki, room = self.fixture(root)
            result = build_edition(wiki, root / 'site', room)
            self.assertEqual(result['phrases'], 1)
            page = (root / 'site/index.html').read_text()
            self.assertIn('id="A001"', page)
            self.assertIn('Layered silver necklaces', page)
            self.assertIn('class="bar s1"', page)
            self.assertNotIn('style=', page)
            self.assertIn('href="phrases.html"', page)
            self.assertIn('audio/phrase-p001.mp3', (root / 'site/phrases.html').read_text())
            for name in ['_worker.js', '_routes.json', 'edition.css', 'edition.js', 'data/index.json', 'references/A001.webp',
                         'generated/item-necklace.png', 'audio/phrase-p001.mp3']:
                self.assertTrue((root / 'site' / name).exists(), name)

    def test_public_policy_tampering_and_bad_room_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wiki, room = self.fixture(root)
            (wiki / 'publication-policy.json').write_text(json.dumps({'version': 1, 'requires_authentication': False}))
            with self.assertRaisesRegex(ValueError, 'always protected'):
                build_edition(wiki, root / 'a', room)
            (wiki / 'publication-policy.json').write_text(json.dumps({'version': 1, 'requires_authentication': True}))
            Image.new('RGB', (60, 80), 'red').save(wiki / 'references/A001.webp', 'WEBP')
            with self.assertRaisesRegex(ValueError, 'Hash mismatch'):
                build_edition(wiki, root / 'b', room)
            wiki, room = self.fixture(root / 'second')
            (room / 'items/raw.mp4').write_bytes(b'x')
            with self.assertRaisesRegex(ValueError, 'only JSON and WebP'):
                build_edition(wiki, root / 'c', room)

    def test_generated_speech_is_hash_checked_and_disclosed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wiki, room = self.fixture(root)
            take = wiki / 'audio/self-presentation.mp3'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=200:duration=2', '-ac', '1', '-b:a', '64k', str(take)], check=True)
            length = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(take)]))
            manifest = {'schema': 'instadna.audio/v1', 'disclosure': 'Authored synthetic speech in a consented voice clone.',
                        'assets': [{'id': 'self-presentation', 'origin': 'generated', 'publish': True, 'path': 'audio/self-presentation.mp3',
                                    'sha256': sha(take), 'duration_s': length, 'title': 'Self-presentation', 'label': 'Synthetic voice',
                                    'description': 'd'}]}
            (wiki / 'audio-manifest.json').write_text(json.dumps(manifest))
            (wiki / 'voice.md').write_text('# Voice\n\n<div id="generated-audio"></div>\n')
            result = build_edition(wiki, root / 'site', room)
            self.assertEqual(result['generated_audio'], 1)
            page = (root / 'site/voice.html').read_text()
            self.assertIn('Synthetic speech.', page)
            self.assertIn('src="audio/self-presentation.mp3"', page)
            self.assertTrue((root / 'site/audio/self-presentation.mp3').exists())
            manifest['disclosure'] = 'A voice.'
            (wiki / 'audio-manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'synthetic'):
                build_edition(wiki, root / 'site2', room)

    def storyboard_fixture(self, root):
        wiki, room = self.fixture(root)
        take = wiki / 'audio/self-presentation.mp3'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=200:duration=2', '-ac', '1', '-b:a', '64k', str(take)], check=True)
        length = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(take)]))
        (wiki / 'audio-manifest.json').write_text(json.dumps({'schema': 'instadna.audio/v1', 'disclosure': 'Authored synthetic speech.',
            'assets': [{'id': 'self-presentation', 'origin': 'generated', 'publish': True, 'path': 'audio/self-presentation.mp3',
                        'sha256': sha(take), 'duration_s': length, 'title': 'T', 'label': 'Synthetic voice', 'description': 'd'}]}))
        (wiki / 'storyboard/styled').mkdir(parents=True)
        Image.new('RGB', (90, 160), 'gray').save(wiki / 'storyboard/S01.webp', 'WEBP')
        Image.new('RGB', (45, 80), 'gray').save(wiki / 'storyboard/S01-thumb.webp', 'WEBP')
        Image.new('RGB', (90, 160), 'black').save(wiki / 'storyboard/styled/S02-fp.webp', 'WEBP')
        frame = {'path': 'storyboard/S01.webp', 'thumbnail': 'storyboard/S01-thumb.webp', 'sha256': sha(wiki / 'storyboard/S01.webp'),
                 'thumbnail_sha256': sha(wiki / 'storyboard/S01-thumb.webp'), 'width': 90, 'height': 160, 'kind': 'ai_storyboard_frame',
                 'model': 'Codex CLI built-in image tool', 'label': 'AI-generated storyboard frame', 'prompt_sha256': 'c' * 64,
                 'generated_at': '2026-10-02T11:00:00+00:00', 'references': ['atlas:A001']}
        shot = {'id': 'S01', 'n': 1, 'type': 'world', 'title': 'Pool', 'start': 0.0, 'end': 1.0, 'duration': 1.0, 'camera': 'push',
                'vo': 'Слушайте,', 'words': [{'w': 'Слушайте,', 'start': 0.2, 'end': 0.7}], 'scene': 's', 'motion': 'm', 'basis': 'b',
                'captions': [{'text': 'СЛУШАЙТЕ', 'style': 'fp', 'start': 0.2, 'end': 1.0}], 'passport': [{'id': 'necklace', 'title': 'N'}],
                'references': ['atlas:A001', 'private:pouch'], 'frame': frame, 'styled': {}, 'short_cut': True}
        card = {'id': 'S02', 'n': 2, 'type': 'card', 'title': 'End card', 'start': 1.0, 'end': round(length, 3), 'duration': round(length - 1, 3),
                'camera': 'push', 'vo': '', 'words': [], 'scene': 's', 'motion': 'm', 'basis': 'b', 'captions': [], 'passport': [],
                'references': [], 'frame': None, 'short_cut': True,
                'styled': {'fp': {'path': 'storyboard/styled/S02-fp.webp', 'sha256': sha(wiki / 'storyboard/styled/S02-fp.webp'), 'width': 90, 'height': 160}}}
        board = {'schema': 'instadna.storyboard/v1', 'disclosure': 'Every frame is AI-generated.', 'format': {'end_card': {'text': 'ИМЯ'}},
                 'audio': {'path': 'audio/self-presentation.mp3', 'duration_s': round(length, 3)}, 'identity_anchor': {},
                 'stats': {'short_cut': {'shots': 2, 'duration_s': 2.0}}, 'shots': [shot, card]}
        (wiki / 'storyboard.json').write_text(json.dumps(board, ensure_ascii=False))
        (wiki / 'video.md').write_text('# Video\n\n<div id="storyboard"></div>\n\n<div id="storyboard-types"></div>\n')
        return wiki, room, board

    def test_storyboard_is_hash_checked_disclosed_and_contiguous(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wiki, room, board = self.storyboard_fixture(root)
            result = build_edition(wiki, root / 'site', room)
            self.assertEqual(result['storyboard_shots'], 2)
            page = (root / 'site/video.html').read_text()
            self.assertIn('class="board"', page)
            self.assertIn('src="storyboard/S01-thumb.webp"', page)
            self.assertIn('href="visual-passport.html#necklace"', page)
            self.assertIn('pouch (private reference)', page)
            self.assertNotIn('style=', page)
            for name in ['storyboard.json', 'storyboard/S01.webp', 'storyboard/S01-thumb.webp', 'storyboard/styled/S02-fp.webp']:
                self.assertTrue((root / 'site' / name).exists(), name)
            broken = [('disclosure', 'A storyboard.', 'AI-generated disclosure'),
                      ('gap', None, 'contiguous'),
                      ('label', None, 'labelled as an AI-generated'),
                      ('hash', None, 'Hash mismatch'),
                      ('audio', None, 'published, disclosed generated audio')]
            for n, (case, value, message) in enumerate(broken):
                bad = json.loads(json.dumps(board))
                if case == 'disclosure':
                    bad['disclosure'] = value
                elif case == 'gap':
                    bad['shots'][1]['start'] = 1.2
                elif case == 'label':
                    bad['shots'][0]['frame']['label'] = 'A frame'
                elif case == 'hash':
                    bad['shots'][0]['frame']['sha256'] = 'd' * 64
                else:
                    bad['audio']['path'] = 'audio/other.mp3'
                (wiki / 'storyboard.json').write_text(json.dumps(bad, ensure_ascii=False))
                with self.assertRaisesRegex(ValueError, message):
                    build_edition(wiki, root / f'bad{n}', room)

    def test_each_storyboard_page_uses_its_own_manifest_and_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wiki, room, board = self.storyboard_fixture(root)
            (wiki / 'storyboard/round2').mkdir()
            for name in ['S01.webp', 'S01-thumb.webp']:
                shutil.copyfile(wiki / 'storyboard' / name, wiki / 'storyboard/round2' / name)
            second = json.loads(json.dumps(board))
            second['round'] = 2
            for key in ('path', 'thumbnail'):
                second['shots'][0]['frame'][key] = second['shots'][0]['frame'][key].replace('storyboard/', 'storyboard/round2/')
            second['shots'][0]['captions'][0]['text'] = 'РАУНД'
            (wiki / 'storyboard-round2.json').write_text(json.dumps(second, ensure_ascii=False))
            manifest = json.loads((wiki / 'audio-manifest.json').read_text())
            manifest['assets'][0]['page'] = 'video'
            manifest['assets'][0]['latest'] = True
            (wiki / 'audio-manifest.json').write_text(json.dumps(manifest))
            (wiki / 'video.md').write_text('# Video\n\n<div id="generated-audio-latest"></div>\n\n<div id="storyboard"></div>\n\n<div id="generated-audio"></div>\n')
            (wiki / 'video-round1.md').write_text('# Round 1\n\n<div id="storyboard"></div>\n\n<div id="storyboard-history"></div>\n\n<div id="generated-audio"></div>\n')
            edition = json.loads((wiki / 'edition.json').read_text())
            edition['storyboards'] = {'video': 'storyboard-round2.json', 'video-round1': 'storyboard.json'}
            (wiki / 'edition.json').write_text(json.dumps(edition))
            result = build_edition(wiki, root / 'site', room)
            self.assertEqual(result['storyboard_shots'], 4)
            page2, page1 = (root / 'site/video.html').read_text(), (root / 'site/video-round1.html').read_text()
            self.assertIn('data-src="storyboard-round2.json"', page2)
            self.assertIn('РАУНД', page2)
            self.assertIn('data-src="storyboard.json"', page1)
            self.assertNotIn('РАУНД', page1)
            self.assertIn('audio/self-presentation.mp3', page2.split('class="board"')[1].split('</ol>')[1])
            self.assertNotIn('class="audio-card"', page1)
            history = page1.split('class="storyboard-history"')[1]
            self.assertIn('href="video.html#S01"', history)
            self.assertIn('src="storyboard/round2/S01-thumb.webp"', history)
            self.assertNotIn('href="video-round1.html#', history)
            self.assertIn('<audio controls preload="none" src="audio/self-presentation.mp3"', history)
            self.assertLess(page2.index('audio-latest'), page2.index('class="board"'))
            pinned = json.loads((wiki / 'audio-manifest.json').read_text())
            extra = dict(pinned['assets'][0], id='first-take', page='other', latest=False, pinned=['video'], pin_label='First')
            pinned['assets'].append(extra)
            (wiki / 'audio-manifest.json').write_text(json.dumps(pinned))
            (wiki / 'other.md').write_text('# Other\n\n<div id="generated-audio"></div>\n')
            build_edition(wiki, root / 'site-pinned', room)
            pinned_page = (root / 'site-pinned/video.html').read_text()
            self.assertLess(pinned_page.index('id="pinned-' + manifest['assets'][0]['id']), pinned_page.index('id="pinned-first-take"'))
            self.assertIn('href="other.html#first-take"', pinned_page)
            self.assertIn('AI-generated: a synthetic voice', page2)
            for name in ['storyboard.json', 'storyboard-round2.json', 'storyboard/round2/S01.webp']:
                self.assertTrue((root / 'site' / name).exists(), name)
            edition['storyboards'] = {'video': '../secrets.json'}
            (wiki / 'edition.json').write_text(json.dumps(edition))
            with self.assertRaisesRegex(ValueError, 'allowlist'):
                build_edition(wiki, root / 'bad', room)

    def test_generated_video_is_hash_checked_disclosed_and_rendered(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wiki, room = self.fixture(root)
            (wiki / 'video').mkdir()
            clip = wiki / 'video/edit-test.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=72x128:d=1:r=25', '-f', 'lavfi', '-i',
                            'sine=frequency=440:duration=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest',
                            str(clip)], check=True)
            Image.new('RGB', (72, 128), 'black').save(wiki / 'video/edit-test.jpg', 'JPEG')
            duration = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(clip)]))
            row = {'id': 'edit-test', 'origin': 'generated', 'publish': True, 'page': 'film', 'path': 'video/edit-test.mp4',
                   'sha256': sha(clip), 'duration_s': round(duration, 3), 'width': 72, 'height': 128, 'poster': 'video/edit-test.jpg',
                   'poster_sha256': sha(wiki / 'video/edit-test.jpg'), 'title': 'Edit', 'label': 'AI video', 'description': 'd'}
            manifest = {'schema': 'instadna.video/v1', 'disclosure': 'AI-generated likeness and scenes.', 'assets': [row]}
            (wiki / 'video-manifest.json').write_text(json.dumps(manifest))
            (wiki / 'film.md').write_text('# Film\n\n<div id="generated-video"></div>\n')
            (wiki / 'other.md').write_text('# Other\n\n<div id="generated-video"></div>\n')
            result = build_edition(wiki, root / 'site', room)
            self.assertEqual(result['generated_video'], 1)
            page = (root / 'site/film.html').read_text()
            self.assertIn('<source src="video/edit-test.mp4" type="video/mp4">', page)
            self.assertIn('poster="video/edit-test.jpg"', page)
            self.assertIn('AI-generated video.', page)
            self.assertNotIn('<video', (root / 'site/other.html').read_text())
            for name in ['video/edit-test.mp4', 'video/edit-test.jpg', 'video-manifest.json']:
                self.assertTrue((root / 'site' / name).exists(), name)
            for change, message in [({'sha256': '0' * 64}, 'hash mismatch'), ({'path': 'video/../edit.mp4'}, 'allowlisted'),
                                    ({'width': 1080}, 'H.264 at the size')]:
                bad = json.loads(json.dumps(manifest))
                bad['assets'][0].update(change)
                (wiki / 'video-manifest.json').write_text(json.dumps(bad))
                with self.assertRaisesRegex(ValueError, message):
                    build_edition(wiki, root / f'bad-{message[:4]}', room)
            bad = dict(manifest, disclosure='A video.')
            (wiki / 'video-manifest.json').write_text(json.dumps(bad))
            with self.assertRaisesRegex(ValueError, 'AI-generated'):
                build_edition(wiki, root / 'bad-disclosure', room)

    def test_phrase_windows_and_public_builds_are_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            wiki, _ = self.fixture(Path(temp))
            with self.assertRaisesRegex(ValueError, 'private'):
                load_phrases(wiki, public=True)
            data = json.loads((wiki / 'phrases.json').read_text())
            data['spoken'][0]['end_s'] = 70.0
            (wiki / 'phrases.json').write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'window'):
                load_phrases(wiki)


class EditionScriptTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js is not installed')
    def test_edition_script_parses(self):
        script = Path(__file__).resolve().parents[1] / 'instadna' / 'web' / 'edition.js'
        result = subprocess.run(['node', '--check', str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
