"""Preservation and bounded de-essing checks on controlled acoustic signals."""
import copy
import json
from pathlib import Path
import sys
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from postprocess_voice import deess, validate_preset


class VoicePostprocessTests(unittest.TestCase):
    def setUp(self):
        self.preset = json.loads((ROOT/'harness/voice-clone-dna/references/postprocess-template.json').read_text())['presets']['clean']
        self.rate = 48000

    def test_neutral_mask_reconstructs_arbitrary_length_and_silence(self):
        rng = np.random.default_rng(42)
        x = rng.normal(0, .05, 98765)
        config = {**self.preset['deesser'], 'max_cut_db': 0}
        y, _ = deess(x, self.rate, config)
        self.assertEqual(len(x), len(y))
        self.assertLess(np.max(np.abs(x-y)), 1e-10)
        zero, _ = deess(np.zeros(48007), self.rate, self.preset['deesser'])
        self.assertTrue(np.array_equal(zero, np.zeros(48007)))

    def test_sibilant_burst_is_reduced_without_removing_low_voice(self):
        t = np.arange(3*self.rate)/self.rate
        voice = .12*np.sin(2*np.pi*180*t) + .035*np.sin(2*np.pi*540*t)
        x = voice.copy()
        mask = (t >= 1) & (t < 1.6)
        x[mask] += .16*np.sin(2*np.pi*6500*t[mask])
        y, meter = deess(x, self.rate, self.preset['deesser'])
        self.assertEqual(len(x), len(y))
        self.assertLessEqual(meter['max_reduction_db'], 3.5)
        self.assertGreater(meter['max_reduction_db'], 2)
        calm = (t > .2) & (t < .8)
        self.assertLess(np.sqrt(np.mean((y[calm]-voice[calm])**2)), 1e-4)
        burst = (t > 1.15) & (t < 1.45)
        before = np.sqrt(np.mean((x[burst]-voice[burst])**2))
        after = np.sqrt(np.mean((y[burst]-voice[burst])**2))
        self.assertLess(after/before, .8)
        tail = (t > 2.4) & (t < 2.8)
        self.assertLess(np.sqrt(np.mean((y[tail]-voice[tail])**2)), 1e-4)

    def test_extreme_and_inverted_presets_are_rejected(self):
        validate_preset(self.preset)
        for name, value in [('max_cut_db', 20), ('ratio', .5), ('fraction_threshold', 0), ('shelf_full_hz', 2000)]:
            bad = copy.deepcopy(self.preset)
            bad['deesser'][name] = value
            with self.assertRaises(ValueError):
                validate_preset(bad)
