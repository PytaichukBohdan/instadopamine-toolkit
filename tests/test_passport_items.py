import json
from pathlib import Path
import tempfile
import unittest

from instadna.passport_items import load_passport_items, render_passport_items
from instadna.references import load_references, render_gallery
import test_reference_publication as reference_fixtures


class PassportItemsTests(unittest.TestCase):
    def fixture(self, root):
        wiki, ref = reference_fixtures.ReferencePublicationTests().fixture(root)
        row = dict(id='example', title='An item', category='objects', image=ref['image'], kind='source_reference',
                   description='Observed detail', context='An insert', usage_brief='Show the object',
                   limit='Ownership unknown', reference_ids=['R01'])
        (wiki/'passport-items.json').write_text(json.dumps({'items': [row]}))
        return wiki, ref, row

    def test_source_image_must_match_evidence_and_synthetic_image_must_be_allowlisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki, ref, row = self.fixture(Path(tmp))
            self.assertEqual(len(load_passport_items(wiki, [ref], [])), 1)
            for kind, image in [('source_reference', 'references/unselected.png'), ('ai_visual_synthesis', 'generated/private.png')]:
                row.update(kind=kind, image=image)
                (wiki/'passport-items.json').write_text(json.dumps({'items': [row]}))
                with self.assertRaises(ValueError):load_passport_items(wiki, [ref], [])

    def test_dangling_evidence_missing_context_and_duplicate_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki, ref, row = self.fixture(Path(tmp))
            for rows in [[row | {'reference_ids': ['R999']}], [row | {'context': ''}], [row, row]]:
                (wiki/'passport-items.json').write_text(json.dumps({'items': rows}))
                with self.assertRaises(ValueError):load_passport_items(wiki, [ref], [])

    def test_source_text_is_escaped_and_download_keeps_exact_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki, ref, row = self.fixture(Path(tmp))
            row['description'] = '<script>alert(1)</script>'
            result = render_passport_items([row])
            self.assertNotIn('<script>', result)
            self.assertIn('&lt;script&gt;', result)
            self.assertIn('href="references/ref.png" download', result)
            self.assertIn('visual-atlas.html#R01', result)

    def test_highlight_poster_keeps_unknown_time_and_exact_story_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki, ref, row = self.fixture(Path(tmp))
            ref.update(source_kind='highlight', highlight_id='123', story_id='456', shortcode='H123',
                       source_url='https://www.instagram.com/stories/highlights/123/?story_media_id=456',
                       kind='video_poster', time_seconds=None, title='Poster', description='Detail', use='Insert', limit='Unknown time', category='objects')
            (wiki/'visual-atlas.json').write_text(json.dumps({'references': [ref]}))
            checked = load_references(wiki)
            self.assertIn('video poster · timestamp unknown', render_gallery(checked))
            self.assertIn('story 1 · 456', render_gallery(checked))
            ref['source_url'] = 'https://www.instagram.com/stories/highlights/123/?story_media_id=789'
            (wiki/'visual-atlas.json').write_text(json.dumps({'references': [ref]}))
            with self.assertRaisesRegex(ValueError, 'does not match'):load_references(wiki)

    def test_timing_cannot_invent_a_date_or_video_offset_for_a_still(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki, ref, row = self.fixture(Path(tmp))
            ref.update(published_at='2024-05-17T08:40:22+00:00', time_seconds=None)
            appearance = dict(reference_id='R01', published_at=ref['published_at'], time_seconds=None,
                              locator='asset 0 · still image', date_basis='Publication timestamp')
            row.update(recurrence='single', recurrence_note='One publication.', appearances=[appearance])
            def save():
                (wiki/'passport-items.json').write_text(json.dumps({'version': 2, 'items': [row]}))
            save()
            self.assertEqual(len(load_passport_items(wiki, [ref], [])), 1)
            for key, value in [('published_at', '2025-01-01T00:00:00+00:00'), ('time_seconds', 1)]:
                original = appearance[key]; appearance[key] = value; save()
                with self.assertRaisesRegex(ValueError, 'does not match'):
                    load_passport_items(wiki, [ref], [])
                appearance[key] = original
            row['appearances'] = []; save()
            with self.assertRaisesRegex(ValueError, 'every source'):
                load_passport_items(wiki, [ref], [])

    def test_undated_evidence_is_visible_and_cannot_imply_a_current_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki, ref, row = self.fixture(Path(tmp))
            row.update(recurrence='single', recurrence_note='One source.', appearances=[
                dict(reference_id='R01', published_at=None, time_seconds=None,
                     locator='asset 0 · still image', date_basis='Date not recovered')])
            rendered = render_passport_items([row])
            self.assertIn('Publication date unknown', rendered)
            self.assertIn('Date not recovered', rendered)
            self.assertIn('One observation', rendered)
