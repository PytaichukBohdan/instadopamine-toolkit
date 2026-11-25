#!/usr/bin/env python3
"""Install/check the owner's person-passport workflow and a scoped global instruction block."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil

NAME = 'person-passport'
START = '<!-- owner-person-passport:start -->'
END = '<!-- owner-person-passport:end -->'
ROOT = Path(__file__).resolve().parents[1]


def files(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}


def install(codex_root, agents_root, check=False):
    source = ROOT/'harness'/NAME
    expected = files(source)
    manifest = json.loads((source/'bundle.json').read_text())
    if manifest['files'] != {k:v for k,v in expected.items() if k != 'bundle.json'}:
        raise ValueError('Source bundle hashes do not match')
    target = codex_root/'skills'/NAME
    alias = agents_root/'skills'/NAME
    override = codex_root/'AGENTS.override.md'
    instructions = override if override.exists() and override.read_text().strip() else codex_root/'AGENTS.md'
    existing = instructions.read_text() if instructions.exists() else ''
    block = START+'\n'+(ROOT/'harness/owner-passport-preference.md').read_text().strip()+'\n'+END
    if existing.count(START) != existing.count(END) or existing.count(START) > 1:
        raise ValueError('Malformed managed instruction block; preserve file for review')
    if target.exists() and (target.is_symlink() or files(target) != expected):
        raise ValueError('Installed skill differs; inspect it before replacing existing work')
    if (alias.exists() or alias.is_symlink()) and (not alias.is_symlink() or alias.resolve() != target.resolve()):
        raise ValueError('Discovery path belongs to another installation')
    if check:
        if not target.is_dir() or not alias.is_symlink() or block not in existing:
            raise ValueError('Skill, discovery link or global trigger is missing')
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copytree(source, target)
        alias.parent.mkdir(parents=True, exist_ok=True)
        if not alias.is_symlink():
            alias.symlink_to(target, target_is_directory=True)
        if START in existing:
            prefix, tail = existing.split(START, 1)
            _, suffix = tail.split(END, 1)
            updated = prefix+block+suffix
        else:
            updated = existing + ('\n\n' if existing else '') + block + '\n'
        instructions.parent.mkdir(parents=True, exist_ok=True)
        if updated != existing:
            instructions.write_text(updated)
    return dict(skill=str(target/'SKILL.md'), discovery=str(alias/'SKILL.md'),
                global_instructions=str(instructions), verified_files=len(expected),
                mode='check' if check else 'install', schema=manifest['schema'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-root', type=Path, default=Path(os.environ.get('CODEX_HOME', Path.home()/'.codex')))
    parser.add_argument('--agents-root', type=Path, default=Path.home()/'.agents')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        result = install(args.codex_root.resolve(), args.agents_root.resolve(), args.check)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
