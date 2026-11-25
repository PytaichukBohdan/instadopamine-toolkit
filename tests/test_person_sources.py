import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import analyze_media_gemini  # noqa: E402
import build_instagram_corpus  # noqa: E402
import compile_person  # noqa: E402
from instadna import gemini  # noqa: E402
from instadna.media_analysis import validate  # noqa: E402

try:
    from bs4 import BeautifulSoup
    import collect_telegram_public
except ImportError:  # optional collector dependency
    BeautifulSoup = None

PAGE = '''<div class="tgme_widget_message_wrap"><div class="tgme_widget_message" data-post="chan_name/12">
<div class="tgme_widget_message_forwarded_from">Forwarded from <a class="tgme_widget_message_forwarded_from_name" href="https://t.me/other">Other</a></div>
<a class="tgme_widget_message_reply" href="https://t.me/chan_name/9"></a>
<div class="tgme_widget_message_text">Слушайте<br>пиши <a href="https://forms.gle/x">СЕКРЕТ</a></div>
<a class="tgme_widget_message_photo_wrap" href="https://t.me/chan_name/12?single" style="background-image:url('https://cdn4.telesco.pe/file/a.jpg')"></a>
<a class="tgme_widget_message_photo_wrap" href="https://t.me/chan_name/13?single" style="background-image:url('https://cdn4.telesco.pe/file/b.jpg')"></a>
<audio class="tgme_widget_message_voice" src="https://cdn4.telesco.pe/file/v.ogg"></audio><time class="tgme_widget_message_voice_duration">1:05</time>
<a class="tgme_widget_message_video_player not_supported" href="https://t.me/chan_name/14"><time class="message_video_duration">2:01</time></a>
<span class="tgme_widget_message_views">1.2K</span><a class="tgme_widget_message_date"><time datetime="2026-09-30T14:21:46+00:00"></time></a>
</div></div>'''


@unittest.skipIf(BeautifulSoup is None, 'beautifulsoup4/lxml not installed')
class TelegramPreviewTests(unittest.TestCase):
    def test_message_media_text_and_attribution_are_parsed(self):
        soup = BeautifulSoup(PAGE, 'lxml')
        row = collect_telegram_public.parse_message(soup.select_one('.tgme_widget_message_wrap'), 'chan_name')
        self.assertEqual((row['id'], row['published_at'], row['views_text'], row['reply_to']), (12, '2026-09-30T14:21:46+00:00', '1.2K', 9))
        self.assertEqual(row['text'], 'Слушайте\nпиши СЕКРЕТ')
        self.assertEqual(row['links'], ['https://forms.gle/x'])
        self.assertEqual(row['forward']['from'], 'Other')
        kinds = [(m['kind'], m['message_id'], m.get('duration_s'), bool(m.get('url'))) for m in row['media']]
        self.assertEqual(kinds, [('photo', 12, None, True), ('photo', 13, None, True), ('voice', 12, 65, True), ('video', 14, 121, False)])

    def test_posts_from_other_channels_are_ignored(self):
        soup = BeautifulSoup(PAGE.replace('chan_name/12', 'someone/12'), 'lxml')
        self.assertIsNone(collect_telegram_public.parse_message(soup.select_one('.tgme_widget_message_wrap'), 'chan_name'))


class InstagramNormalizeTests(unittest.TestCase):
    def test_owner_coauthor_music_and_media_are_kept(self):
        node = {'code': 'ABC', 'pk': 1, 'taken_at': 1790000000, 'media_type': 8, 'product_type': 'carousel_container',
                'user': {'username': 'other_acc'}, 'coauthor_producers': [{'username': 'example_creator'}],
                'caption': {'text': 'пиши СЕКРЕТ'}, 'clips_metadata': {'audio_type': 'licensed_music', 'music_info': {'music_asset_info': {
                    'title': 'Song', 'display_artist': 'Artist', 'audio_cluster_id': '9'}}},
                'carousel_media': [{'media_type': 1, 'image_versions2': {'candidates': [{'url': 'u1', 'width': 10, 'height': 10}, {'url': 'u2', 'width': 20, 'height': 20}]},
                                    'usertags': {'in': [{'user': {'username': 'friend', 'full_name': 'F'}}]}},
                                   {'media_type': 2, 'video_versions': [{'url': 'v', 'width': 720, 'height': 1280}], 'image_versions2': {'candidates': []}}]}
        post = build_instagram_corpus.normalize(node, 'example_creator')
        self.assertTrue(post['associated'])
        self.assertEqual(post['published_at'][:10], '2026-09-21')
        self.assertEqual(post['music'], {'type': 'licensed_music', 'title': 'Song', 'artist': 'Artist', 'audio_id': '9', 'explicit': None})
        self.assertEqual([(a['kind'], a['_url']) for a in post['assets']], [('image', 'u2'), ('video', 'v')])
        self.assertEqual(post['usertags'], [{'asset_index': 0, 'username': 'friend', 'full_name': 'F'}])

    def test_cta_keywords_need_an_upper_case_code_word(self):
        self.assertEqual(compile_person.cta_keywords('План на месяц — пиши СЕКРЕТ📲 и забирай'), ['СЕКРЕТ'])
        self.assertEqual(compile_person.cta_keywords('пиши мне в директ'), [])

    def test_cta_keywords_cover_ukrainian_and_direct_forms(self):
        found = lambda text: set(compile_person.cta_keywords(text))
        self.assertEqual(found('Написати мені СЕКРЕТ і забрати план'), {'СЕКРЕТ'})
        self.assertEqual(found('Пишіть ШАНС і забирайте доступ'), {'ШАНС'})
        self.assertEqual(found('Пиши в директ МАСШТАБ, если готов'), {'МАСШТАБ'})
        self.assertEqual(found('пиши мне МАСШТАБ ✨'), {'МАСШТАБ'})
        self.assertEqual(found('Пиши в директ @target.example_creator слово ШАНС'), {'ШАНС'})
        self.assertEqual(found('МАСШТАБ у дірект, щоб взяти максимум'), {'МАСШТАБ'})
        self.assertEqual(found('можна забрати за словом МАСШТАБ, щоб'), {'МАСШТАБ'})
        self.assertEqual(found('Это ШАНС💜'), set())


class AnalysisInputTests(unittest.TestCase):
    def test_gap_filled_telegram_files_use_supported_mime_types(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'public'
            extra = Path(temp) / 'mtproto'
            (root / 'media/photo').mkdir(parents=True)
            (extra / 'files').mkdir(parents=True)
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=64x64:rate=5:duration=1', '-f', 'lavfi', '-i',
                            'sine=duration=1', '-shortest', '-f', 'mov', str(extra / 'files/14-1.mov')], check=True)
            (extra / 'files/20-2.pdf').write_bytes(b'%PDF-1.4\n%%EOF\n')
            (extra / 'files/21-3.epub').write_bytes(b'zip')
            rows = [{'id': 14, 'source_url': 'https://t.me/chan_name/14', 'published_at': '2026-01-01T00:00:00+00:00', 'text': '', 'media': [{'kind': 'video', 'message_id': 14}]},
                    {'id': 20, 'source_url': 'https://t.me/chan_name/20', 'published_at': '2026-01-01T00:00:00+00:00', 'text': 'Программа',
                     'media': [{'kind': 'document', 'message_id': 20, 'title': 'p.pdf'}, {'kind': 'document', 'message_id': 20, 'title': 'b.epub'}]}]
            (root / 'messages.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
            (root / 'downloads.json').write_text('{}')
            files = {'14': {'status': 'downloaded', 'path': 'files/14-1.mov', 'sha256': 'a', 'kind': 'video'},
                     '20': {'status': 'downloaded', 'path': 'files/20-2.pdf', 'sha256': 'b', 'kind': 'document'},
                     '21': {'status': 'downloaded', 'path': 'files/21-3.epub', 'sha256': 'c', 'kind': 'document'}}
            (extra / 'manifest.json').write_text(json.dumps({'files': files}))
            items = {i['item_id']: i for i in analyze_media_gemini.telegram_items(root, 'creator')}
            self.assertEqual(items['tg:14']['media'][0]['mime'], 'video/mov')
            self.assertEqual(items['tg:14']['kind'], 'video')
            self.assertEqual([(m['kind'], m['mime']) for m in items['tg:20']['media']], [('document', 'application/pdf')])
            self.assertEqual(items['tg:20']['context']['document_titles'], ['p.pdf', 'b.epub'])
            self.assertNotIn('document_titles', items['tg:14']['context'])

    def test_validation_rejects_wrong_ids_and_flags_impossible_times(self):
        item = {'item_id': 'ig:A', 'duration_s': 10.0, 'media': [{'index': 0}]}
        with self.assertRaisesRegex(ValueError, 'ID mismatch'):
            validate({'item_id': 'ig:B', 'speakers': [], 'transcript': []}, item)
        issues = validate({'item_id': 'ig:A', 'speakers': [], 'transcript': [{'start': 2, 'end': 30}],
                           'reference_moments': [{'time': 3, 'asset_index': 4}]}, item)
        self.assertEqual(len(issues), 2)

    def test_malformed_json_reply_is_retried_once(self):
        calls = []

        def flaky(*args):
            calls.append(1)
            if len(calls) == 1:
                raise json.JSONDecodeError('bad', '{', 0)
            return {'ok': True}, {}
        with mock.patch.object(gemini, '_generate', side_effect=flaky):
            self.assertEqual(gemini.generate('m', [])[0], {'ok': True})
        self.assertEqual(len(calls), 2)


if __name__ == '__main__':
    unittest.main()
