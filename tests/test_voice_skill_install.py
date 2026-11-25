"""Global preference preservation and cross-project bundle installation."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('install_voice_skill', Path(__file__).resolve().parents[1]/'scripts/install_voice_skill.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


class VoiceSkillInstallTests(unittest.TestCase):
    def test_install_is_idempotent_and_preserves_unrelated_global_preferences(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); codex=root/'codex'; agents=root/'agents'; codex.mkdir()
            p=codex/'AGENTS.md'; original='# Keep this owner preference\nUnicode: їєґ\n';p.write_text(original)
            module.install(codex,agents)
            after=p.read_bytes()
            self.assertTrue(p.read_text().startswith(original))
            module.install(codex,agents)
            self.assertEqual(after,p.read_bytes())
            self.assertEqual(module.install(codex,agents,True)['mode'],'check')
            self.assertEqual((agents/'skills/voice-clone-dna').resolve(),codex/'skills/voice-clone-dna')

    def test_preexisting_override_receives_rule_without_editing_global_base(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); codex=root/'codex'; codex.mkdir()
            base=codex/'AGENTS.md'; base.write_text('Original base')
            override=codex/'AGENTS.override.md';override.write_text('Existing override')
            result=module.install(codex,root/'agents')
            self.assertEqual(base.read_text(),'Original base')
            self.assertEqual(result['global_instructions'],str(override))
            self.assertTrue(override.read_text().startswith('Existing override'))

    def test_modified_installed_helper_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);codex=root/'codex';agents=root/'agents'
            module.install(codex,agents)
            p=codex/'skills/voice-clone-dna/scripts/postprocess_voice.py';p.write_text('Owner local changes')
            with self.assertRaisesRegex(ValueError,'differs'):
                module.install(codex,agents)
            self.assertEqual(p.read_text(),'Owner local changes')
