import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from instadna.generated_images import load_generated_images
from instadna.site import build_site


class GeneratedImagePublicationTests(unittest.TestCase):
    def fixture(self, root):
        wiki = root / 'wiki'
        (wiki / 'generated').mkdir(parents=True)
        (wiki / 'index.md').write_text('# Example\n\n![Board](generated/board.png)\n![Secret](generated/unselected.png)')
        (wiki / 'coverage.json').write_text(json.dumps(dict(posts_analyzed=1, videos_downloaded=0, video_minutes_prepared=0, profile_posts_reported=1)))
        (wiki / 'source-inventory.json').write_text('[]')
        for name in ('board.png', 'unselected.png'):
            Image.new('RGB', (40, 30)).save(wiki / 'generated' / name)
        row = dict(path='generated/board.png', kind='ai_visual_synthesis', model='gpt-image-2', width=40, height=30)
        row['sha256'] = hashlib.sha256((wiki / row['path']).read_bytes()).hexdigest()
        self.write_manifest(wiki, row)
        return wiki, row

    def write_manifest(self, wiki, row):
        (wiki / 'generated-images.json').write_text(json.dumps({'images': [row]}))

    def test_only_selected_synthetic_image_enters_site(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); wiki, row = self.fixture(root)
            build_site(wiki, root / 'site')
            self.assertTrue((root / 'site' / row['path']).exists())
            self.assertFalse((root / 'site/generated/unselected.png').exists())
            text = (root / 'site/index.html').read_text()
            self.assertIn('src="generated/board.png"', text)
            self.assertNotIn('src="generated/unselected.png"', text)
            self.assertTrue((root / 'site/generated-images.json').exists())

    def test_modified_image_or_dimensions_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            wiki, row = self.fixture(Path(temp))
            row['width'] = 41; self.write_manifest(wiki, row)
            with self.assertRaisesRegex(ValueError, 'dimensions'):
                load_generated_images(wiki)
            row['width'] = 40; self.write_manifest(wiki, row)
            Image.new('RGB', (40, 30), 'red').save(wiki / row['path'])
            with self.assertRaisesRegex(ValueError, 'hash'):
                load_generated_images(wiki)

    def test_path_traversal_symlinks_and_missing_label_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); wiki, row = self.fixture(root)
            row['kind'] = 'source_photo'; self.write_manifest(wiki, row)
            with self.assertRaisesRegex(ValueError, 'labeled'):
                load_generated_images(wiki)
            row['kind'] = 'ai_visual_synthesis'; row['path'] = '../private.png'
            self.write_manifest(wiki, row)
            with self.assertRaisesRegex(ValueError, 'allowlisted'):
                load_generated_images(wiki)
            row['path'] = 'generated/board.png'; self.write_manifest(wiki, row)
            image = wiki / row['path']; outside = root / 'private.png'
            outside.write_bytes(image.read_bytes()); image.unlink(); image.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                load_generated_images(wiki)

    def test_generated_directory_symlink_cannot_expose_private_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); wiki, row = self.fixture(root)
            (wiki / 'generated').rename(root / 'private')
            (wiki / 'generated').symlink_to(root / 'private', target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'escapes'):
                load_generated_images(wiki)

    def test_only_hash_validated_thumbnail_is_published(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); wiki, row = self.fixture(root)
            row['thumbnail'] = 'generated/board-thumb.webp'
            Image.new('RGB', (40, 30), 'green').save(wiki / row['thumbnail'])
            row['thumbnail_sha256'] = hashlib.sha256((wiki / row['thumbnail']).read_bytes()).hexdigest()
            self.write_manifest(wiki, row)
            build_site(wiki, root / 'site')
            self.assertEqual((wiki / row['thumbnail']).read_bytes(), (root / 'site' / row['thumbnail']).read_bytes())
            Image.new('RGB', (40, 30), 'red').save(wiki / row['thumbnail'])
            with self.assertRaisesRegex(ValueError, 'thumbnail hash'):
                load_generated_images(wiki)


if __name__ == '__main__':
    unittest.main()
