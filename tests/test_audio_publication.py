import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import wave

from instadna.audio_assets import load_audio, render_audio, render_audio_ab
from instadna.site import build_site


class AudioPublicationTests(unittest.TestCase):
    def fixture(self, root):
        wiki = root / "wiki"
        (wiki / "audio").mkdir(parents=True)
        (wiki / "audio-lab.md").write_text('# Голос\n\n<div id="audio-gallery"></div>')
        (wiki / "coverage.json").write_text(json.dumps(dict(posts_analyzed=1, videos_downloaded=1, video_minutes_prepared=1, profile_posts_reported=1)))
        (wiki / "source-inventory.json").write_text('[]')
        path = wiki / "audio/test.wav"
        with wave.open(str(path), 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
            wav.writeframes(b'\0\0' * 24000)
        row = dict(id="test-voice", path="audio/test.wav", origin="generated", publish=True,
                   sha256=hashlib.sha256(path.read_bytes()).hexdigest(), duration_s=1,
                   label="Проба", title="Голос", description="Синтетична проба", role="master")
        self.save(wiki, row)
        return wiki, row

    def save(self, wiki, row):
        (wiki / 'audio-manifest.json').write_text(json.dumps(dict(schema='instadna.audio/v1', assets=[row])))

    def test_allowlist_copies_audio_but_not_private_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); wiki, row = self.fixture(root)
            (wiki / 'audio/private.pt').write_bytes(b'private voice embedding')
            build_site(wiki, root / 'site', public=True)
            self.assertTrue((root / 'site/audio/test.wav').exists())
            self.assertFalse((root / 'site/audio/private.pt').exists())
            page = (root / 'site/audio-lab.html').read_text()
            self.assertIn('<html lang="uk">', page)
            self.assertIn('<audio', page)
            self.assertIn('audio.js', page)

    def test_tampered_audio_and_raw_sources_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            wiki, row = self.fixture(Path(temp))
            (wiki / row['path']).write_bytes(b'wrong bytes')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                load_audio(wiki)
            row['origin'] = 'source-recording'; self.save(wiki, row)
            with self.assertRaisesRegex(ValueError, 'generated exports'):
                load_audio(wiki)

    def test_paths_symlinks_and_metadata_are_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); wiki, row = self.fixture(root)
            row['duration_s'] = 60; self.save(wiki, row)
            with self.assertRaisesRegex(ValueError, 'duration does not match'):
                load_audio(wiki)
            row['path'] = '../secret.wav'; self.save(wiki, row)
            with self.assertRaisesRegex(ValueError, 'allowlisted'):
                load_audio(wiki)
            row['path'] = 'audio/test.wav'; self.save(wiki, row)
            path = wiki / row['path']; outside = root / 'private.wav'
            outside.write_bytes(path.read_bytes()); path.unlink(); path.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                load_audio(wiki)

    def test_manifest_text_is_escaped(self):
        html = render_audio([dict(id='test-voice', path='audio/test.wav', label='Test', duration_s=1,
                                title='<script>alert(1)</script>', description='" onload="bad')])
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)

    def test_comparison_uses_selected_assets_and_escapes_labels(self):
        rows = [dict(id='chosen', path='audio/chosen.mp3', comparison_set='post',
                     comparison_default=True, comparison_label='<img src=x onerror=bad>'),
                dict(id='wav', path='audio/chosen.wav', download_only=True,
                     download_for='chosen'),
                dict(id='archive', path='audio/archive.mp3')]
        page = render_audio_ab(rows)
        self.assertIn('data-audio-wav="audio/chosen.wav"', page)
        self.assertIn('aria-pressed="true"', page)
        self.assertIn('<audio controls preload="metadata" src="audio/chosen.mp3"', page)
        self.assertNotIn('audio/archive.mp3', page)
        self.assertNotIn('<img', page)
        self.assertIn('&lt;img', page)
        self.assertEqual(render_audio_ab([rows[2]]), '')
