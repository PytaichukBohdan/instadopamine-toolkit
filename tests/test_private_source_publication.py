import json
import tempfile
import unittest
from pathlib import Path

from instadna.site import build_site


class PrivateSourcePublicationTest(unittest.TestCase):
    def test_restricted_analysis_cannot_enter_public_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wiki = root / 'wiki'
            wiki.mkdir()
            (wiki / 'publication-policy.json').write_text(json.dumps({'version': 1, 'requires_authentication': True}))
            with self.assertRaisesRegex(ValueError, 'restricted source-derived'):
                build_site(wiki, root / 'site', public=True)
            self.assertFalse((root / 'site').exists())

    def test_invalid_policy_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wiki = root / 'wiki'
            wiki.mkdir()
            (wiki / 'publication-policy.json').write_text(json.dumps({'version': 1, 'requires_authentication': 'false'}))
            with self.assertRaisesRegex(ValueError, 'Invalid publication policy'):
                build_site(wiki, root / 'site', public=True)


if __name__ == '__main__':
    unittest.main()
