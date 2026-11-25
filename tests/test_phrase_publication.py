import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from instadna.phrases import load_phrases, render_phrases
from instadna.temporal import summarize_time


class PhraseTests(unittest.TestCase):
    def fixture(self, root):
        (root/'audio').mkdir();(root/'sources').mkdir();(root/'sources/A.md').write_text('# Source')
        path=root/'audio/phrase-example.mp3'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=200:duration=1','-y',str(path)],check=True)
        source=dict(id='A',source_id='A',page='sources/A.md',url='https://www.instagram.com/p/A/',label='Example',duration_s=5,
                    audio_sha256='a'*64,published_at='2026-01-01T00:00:00Z',date_basis='Publication',occasion_id=None)
        phrase=dict(id='example',family='address',source_id='A',origin='source_excerpt',publish=True,
                    text='Example',language='en',attribution='Text-attributed',delivery='Short fall',context='Greeting',
                    review_method='Model listening',limitations='Automatic',path='audio/phrase-example.mp3',
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(),start_s=1,end_s=2,duration_s=1)
        data=dict(schema='instadna.phrases/v1',audience='private',as_of='2026-10-02',sources=[source],phrases=[phrase],
                  families=[dict(id='address',title='Address',context='Greeting',temporal=summarize_time([source],'2026-10-02'))])
        (root/'phrase-bank.json').write_text(json.dumps(data));return data

    def test_private_source_clips_are_not_accepted_in_public_builds(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.fixture(root)
            self.assertEqual(len(load_phrases(root)['phrases']),1)
            with self.assertRaisesRegex(ValueError,'private'):load_phrases(root,public=True)

    def test_corruption_source_escape_and_invalid_windows_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);original=self.fixture(root)
            for patch in [dict(sha256='b'*64),dict(path='../private.mp3'),dict(end_s=6),dict(end_s=2,start_s=2),dict(duration_s=float('nan')),dict(origin='generated')]:
                data=copy.deepcopy(original);data['phrases'][0].update(patch);(root/'phrase-bank.json').write_text(json.dumps(data))
                with self.assertRaises(ValueError):load_phrases(root)

    def test_repeated_crops_do_not_inflate_family_or_exact_phrase_source_counts(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);data=self.fixture(root)
            data['phrases'].append(data['phrases'][0] | {'id':'another-crop'})
            rendered=render_phrases(data)
            self.assertIn('Exact wording: 1 distinct source(s)',rendered)
            self.assertNotIn('Exact wording: 2',rendered)
            data['families'][0]['temporal']['distinct_sources']=2
            data['phrases'].pop();(root/'phrase-bank.json').write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'summary mismatch'):load_phrases(root)
