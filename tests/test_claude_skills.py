import importlib.util
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("install_claude_skills", REPO / "scripts" / "install_claude_skills.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def run(*args):
    with redirect_stdout(io.StringIO()):
        return installer.main(list(args))


class ClaudeSkillsTest(unittest.TestCase):
    def test_every_skill_resolves_with_matching_frontmatter(self):
        found = sorted(p.name for p in (REPO / ".claude" / "skills").iterdir())
        self.assertEqual(found, sorted(installer.SKILLS))
        for name in installer.SKILLS:
            text = (installer.source(name) / "SKILL.md").read_text()
            self.assertTrue(text.startswith(f"---\nname: {name}\ndescription: "), name)

    def test_skill_links_stay_inside_the_repo(self):
        for name in installer.SKILLS:
            self.assertTrue(installer.source(name).is_relative_to(REPO), name)

    def test_install_check_and_refuse_to_overwrite_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            self.assertEqual(run("--dest", tmp, "--check"), 1)
            self.assertEqual(run("--dest", tmp), 0)
            self.assertEqual(run("--dest", tmp, "--check"), 0)
            changed = dest / "voice-clone-dna" / "SKILL.md"
            changed.write_text(changed.read_text() + "\nlocal note\n")
            unrelated = dest / "someone-else"
            unrelated.mkdir()
            self.assertEqual(run("--dest", tmp), 1)
            self.assertIn("local note", changed.read_text())
            self.assertEqual(run("--dest", tmp, "--force"), 0)
            self.assertNotIn("local note", changed.read_text())
            self.assertTrue(unrelated.is_dir())


if __name__ == "__main__":
    unittest.main()
