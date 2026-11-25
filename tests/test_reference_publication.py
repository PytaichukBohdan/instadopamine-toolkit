import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from instadna.references import load_references
from instadna.site import build_site


class ReferencePublicationTests(unittest.TestCase):
    def fixture(self, root):
        wiki = root / 'wiki'
        (wiki / 'references').mkdir(parents=True)
        (wiki / 'index.md').write_text('# Example')
        (wiki / 'coverage.json').write_text(json.dumps(dict(posts_analyzed=1, videos_downloaded=1, video_minutes_prepared=1, profile_posts_reported=1)))
        (wiki / 'source-inventory.json').write_text('[]')
        for name in ['ref.png', 'thumb.webp', 'unselected.png']:
            Image.new('RGB', (10, 10)).save(wiki / 'references' / name)
        row = dict(id='R01', shortcode='ABC', source_url='https://www.instagram.com/p/ABC/', image='references/ref.png', thumbnail='references/thumb.webp', width=10, height=10, asset_index=0, kind='video', time_seconds=0)
        row['sha256'] = hashlib.sha256((wiki / row['image']).read_bytes()).hexdigest()
        row['thumbnail_sha256'] = hashlib.sha256((wiki / row['thumbnail']).read_bytes()).hexdigest()
        (wiki / 'visual-atlas.json').write_text(json.dumps({'references': [row]}))
        return wiki, row

    def test_only_selected_images_are_published(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); wiki, row = self.fixture(root)
            build_site(wiki, root / 'public', public=True)
            self.assertTrue((root / 'public' / row['image']).exists())
            self.assertFalse((root / 'public/references/unselected.png').exists())

    def test_changed_image_hash_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            wiki, row = self.fixture(Path(temp))
            Image.new('RGB', (11, 10)).save(wiki / row['image'])
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                load_references(wiki)

    def test_external_path_or_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); wiki, row = self.fixture(root)
            path = wiki / row['image']; outside = root / 'private.png'
            outside.write_bytes(path.read_bytes()); path.unlink(); path.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                load_references(wiki)
            row['image'] = '../private.png'
            (wiki / 'visual-atlas.json').write_text(json.dumps({'references': [row]}))
            with self.assertRaisesRegex(ValueError, 'allowlisted'):
                load_references(wiki)

    def test_count_deduplicates_posts_and_excludes_second_asr(self):
        spec = importlib.util.spec_from_file_location('language_index', Path(__file__).parents[1] / 'scripts/index_language.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); post = root / 'posts/ABC'; (post / 'asset-00').mkdir(parents=True)
            (post / 'analysis.json').write_text('{}')
            (root / 'manifest.json').write_text(json.dumps({'username': 'example_creator'}))
            (post / 'media.json').write_text(json.dumps({'owner': {'username': 'example_creator'}, 'edge_media_to_caption': {'edges': [{'node': {'text': 'randoms randoms'}}]}}))
            data = {'segments': [{'start': 0, 'end': 2, 'text': 'ну ну'}, {'start': 2, 'end': 3, 'text': 'ну'}]}
            for name in ['transcript-openai.json', 'transcript-diarized.json']:
                (post / 'asset-00' / name).write_text(json.dumps(data))
            result = module.build_index(root); terms = {t['id']: t for t in result['terms']}
            self.assertEqual(result['audio_transcripts'], 1)
            self.assertEqual(result['owner_posts'], 1)
            self.assertEqual(terms['well']['speech_posts'], 1)
            self.assertEqual(sum(m['occurrences'] for m in terms['well']['matches']), 3)
            self.assertEqual(terms['randoms']['caption_posts'], 1)
