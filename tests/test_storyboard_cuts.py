"""Storyboard cut resolution: word anchors, montage cuts and cuts moved onto the music (absolute times)."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_storyboard', ROOT / 'scripts/build_storyboard.py')
build_storyboard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_storyboard)

LYRICS = {'lines': [
    {'i': 0, 'text': 'Меня зовут Мария.', 'start': 0.2, 'end': 1.6, 'words': [
        {'w': 'Меня', 'start': 0.2, 'end': 0.5}, {'w': 'зовут', 'start': 0.6, 'end': 0.9}, {'w': 'Мария.', 'start': 1.0, 'end': 1.6}]},
    {'i': 1, 'text': 'Только вперёд.', 'start': 2.4, 'end': 3.0, 'words': [
        {'w': 'Только', 'start': 2.4, 'end': 2.7}, {'w': 'вперёд.', 'start': 2.7, 'end': 3.0}]}]}


def spec_with(cut):
    return {'format': {'end_card': {'start_after_line': 1, 'gap_s': 0.2}}, 'shots': [
        {'id': 'S01', 'type': 'world', 'cut': None, 'lead': 0.06, 'captions': []},
        {'id': 'S02', 'type': 'world', 'cut': cut, 'lead': 0.06, 'captions': [{'at': [0, 2], 'style': 'fp'}]},
        {'id': 'S03', 'type': 'world', 'cut': [1, 0], 'lead': 0.06, 'captions': [{'at': [1, 0], 'to': [1, 1], 'style': 'fp'}]},
        {'id': 'S04', 'type': 'card', 'cut': None, 'lead': 0.0, 'captions': []}]}


class StoryboardCutTests(unittest.TestCase):
    def test_word_anchor_and_absolute_cut_resolve_to_the_same_windows(self):
        anchored = build_storyboard.resolve(spec_with([0, 2]), LYRICS, 4.0)
        at = build_storyboard.resolve(spec_with({'at': 0.94, 'from': [0, 2], 'snap': 'beat'}), LYRICS, 4.0)
        self.assertEqual([(s['start'], s['end']) for s in anchored], [(s['start'], s['end']) for s in at])
        self.assertEqual(at[1]['captions'][0]['text'], 'МАРИЯ')
        self.assertEqual(at[-1]['start'], 3.2)

    def test_a_cut_on_the_music_may_trail_its_caption_by_at_most_015_s(self):
        late = build_storyboard.resolve(spec_with({'at': 1.12, 'snap': 'hit'}), LYRICS, 4.0)
        self.assertEqual(late[1]['start'], 1.12)
        self.assertEqual(late[1]['captions'][0]['start'], 1.0)
        with self.assertRaisesRegex(ValueError, 'starts outside its shot'):
            build_storyboard.resolve(spec_with({'at': 1.2, 'snap': 'hit'}), LYRICS, 4.0)

    def test_word_anchored_cuts_keep_captions_inside_their_shot(self):
        bad = spec_with([0, 2])
        bad['shots'][1]['lead'] = -0.1  # the cut would land after its caption word
        with self.assertRaisesRegex(ValueError, 'starts outside its shot'):
            build_storyboard.resolve(bad, LYRICS, 4.0)


if __name__ == '__main__':
    unittest.main()
