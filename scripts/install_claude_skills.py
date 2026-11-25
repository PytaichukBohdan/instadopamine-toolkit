#!/usr/bin/env python3
"""Install or check this repo's five creator skills for Claude Code.

Claude Code already loads them from `.claude/skills/` when a session starts inside
this repository. Run this to use them in every project on a machine:

    python scripts/install_claude_skills.py --check     # report only
    python scripts/install_claude_skills.py             # copy missing skills
    python scripts/install_claude_skills.py --force     # also replace changed copies

It only touches the five listed skill folders under the destination
(default $CLAUDE_CONFIG_DIR/skills, else ~/.claude/skills). A differing installed copy is never replaced without
--force. No credentials, voices or person data are part of any skill.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO / ".claude" / "skills"
SKILLS = ["voice-clone-dna", "person-passport", "person-visual-passport", "video-dna-extract", "video-dna-make"]
IGNORE = {"__pycache__", ".DS_Store"}


def files(root: Path) -> dict[str, str]:
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not (set(path.relative_to(root).parts) & IGNORE):
            out[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def source(name: str) -> Path:
    path = (SKILLS_DIR / name).resolve()
    if not (path / "SKILL.md").is_file():
        raise SystemExit(f"{name}: missing SKILL.md in {path}")
    head = (path / "SKILL.md").read_text().split("\n", 3)
    if head[0] != "---" or head[1] != f"name: {name}":
        raise SystemExit(f"{name}: SKILL.md frontmatter must start with 'name: {name}'")
    return path


def status(name: str, dest: Path) -> str:
    target = dest / name
    if not target.exists():
        return "missing"
    return "same" if files(source(name)) == files(target) else "different"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dest", type=Path, default=Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "skills")
    ap.add_argument("--check", action="store_true", help="report only; exit 1 if any skill is missing or different")
    ap.add_argument("--force", action="store_true", help="replace installed copies that differ from the repo")
    args = ap.parse_args(argv)
    report, exit_code = {}, 0
    for name in SKILLS:
        state = status(name, args.dest)
        if args.check:
            exit_code |= state != "same"
        elif state == "missing" or (state == "different" and args.force):
            target = args.dest / name
            if target.is_symlink() or target.is_file():
                target.unlink()
            elif target.exists():
                shutil.rmtree(target)
            shutil.copytree(source(name), target, ignore=shutil.ignore_patterns(*IGNORE))
            state = "installed" if state == "missing" else "replaced"
        elif state == "different":
            state = "different (kept; use --force to replace)"
            exit_code = 1
        report[name] = state
    print(json.dumps({"dest": str(args.dest), "mode": "check" if args.check else "install", "skills": report}, indent=1))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
