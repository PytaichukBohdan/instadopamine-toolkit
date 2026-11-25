import importlib.util
import hashlib
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


asr = script('transcribe_telegram')
analysis = script('analyze_telegram')


class TelegramEvidenceTest(unittest.TestCase):
    def test_audio_must_match_hash_and_stay_in_private_corpus(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / 'voice.ogg'
            audio.write_bytes(b'OggS test')
            record = {'path': 'voice.ogg', 'sha256': hashlib.sha256(audio.read_bytes()).hexdigest()}
            self.assertEqual(asr.validated_audio(root, record), audio)
            link = root / 'linked.ogg'
            link.symlink_to(audio)
            with self.assertRaises(ValueError):
                asr.validated_audio(root, {**record, 'path': 'linked.ogg'})
            with self.assertRaises(ValueError):
                asr.validated_audio(root, {**record, 'path': '../outside.ogg'})
            audio.write_bytes(b'tampered')
            with self.assertRaises(ValueError):
                asr.validated_audio(root, record)

    def test_model_must_account_for_all_sources_and_use_known_ids(self):
        rows = [{'message_id': 1, 'text': 'Друзі, всім привіт!'}, {'message_id': 2, 'text': 'Поїхали!'}]
        with self.assertRaises(ValueError):
            analysis.validate({'reviewed_ids': [1]}, rows)
        with self.assertRaises(ValueError):
            analysis.validate({'reviewed_ids': [1, 2], 'patterns': [{'evidence': [{'message_id': 3}]}]}, rows)
        result = {'reviewed_ids': [1, 2], 'patterns': [{'evidence': [
            {'message_id': 1, 'quote': 'Друзі, всім привіт!', 'start': None, 'end': None},
            {'message_id': 2, 'quote': 'Invented quote', 'start': None, 'end': None}]}]}
        checks = analysis.validate(result, rows)
        self.assertTrue(checks[0]['exact_substring'])
        self.assertFalse(checks[1]['exact_substring'])

    def test_audio_offsets_cannot_extend_beyond_original(self):
        rows = [{'message_id': 1, 'duration': 3, 'segments': [{'start': 0, 'end': 3, 'text': 'Привіт'}]}]
        result = {'reviewed_ids': [1], 'patterns': [{'evidence': [{'message_id': 1, 'quote': 'Привіт', 'start': 2, 'end': 30}]}]}
        self.assertFalse(analysis.validate(result, rows)[0]['offsets_valid'])


if __name__ == '__main__':
    unittest.main()
