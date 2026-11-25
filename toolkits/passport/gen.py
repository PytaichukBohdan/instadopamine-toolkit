#!/usr/bin/env python3
"""Generate passport images for one person through the logged-in Codex CLI's built-in image tool.

Runs on the ChatGPT/Codex subscription only (the /usr/local/bin/codex wrapper strips OPENAI_API_KEY);
there is no API fallback. Each run saves <output>/<job>-v<N>.png plus a WebP preview and appends a
manifest row with prompt/reference/output hashes, the Codex session id and the tool's revised prompt.

usage: gen.py --person people/<slug> JOB [JOB ...]

The person folder holds person.json (name, pronouns, refpack, output), refs.json (reference labels),
jobs.json (job -> prompt + up to 5 refs) and prompts/ (job prompts plus shared _block.md files).
"""
import argparse, fcntl, hashlib, json, re, shutil, subprocess, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
CODEX_HOME = Path.home() / '.codex'
MAX_REFS = 5  # the built-in image tool rejects more than 5 reference images

PREAMBLE = """Use your built-in image generation tool exactly once, then reply DONE. Do not write files or run commands.
Pass the brief below to the image tool as completely and literally as you can - keep every rule, ban and count; do not summarise it away, do not add new creative ideas.
The attached photos are real reference photos of one person, {name}. They are identity/body references only - never copy their rooms, light or cropping.
Attached references, in order:
"""


def sha(b):
    return hashlib.sha256(b).hexdigest()


class Person:
    def __init__(self, folder):
        self.dir = (REPO / folder).resolve()
        self.cfg = json.loads((self.dir / 'person.json').read_text())
        self.labels = json.loads((self.dir / 'refs.json').read_text())
        self.jobs = {j['id']: j for j in json.loads((self.dir / 'jobs.json').read_text())}
        self.refpack = REPO / self.cfg['refpack']
        self.out = REPO / self.cfg['output']
        self.prompts = self.dir / 'prompts'

    def render(self, prompt_name):
        """Expand {{block}} files (prompts/_block.md) and {{NAME}}/{{Name}}/pronoun placeholders."""
        text = (self.prompts / f'{prompt_name}.md').read_text().strip()
        text = re.sub(r'\{\{([a-z_]+)\}\}', lambda m: self._block(m[1]), text)
        words = {'NAME': self.cfg['name'].upper(), 'Name': self.cfg['name'], **self.cfg.get('pronouns', {})}
        return re.sub(r'\{\{(\w+)\}\}', lambda m: words.get(m[1], m[0]), text)

    def _block(self, name):
        f = self.prompts / f'_{name}.md'
        return f.read_text().strip() if f.exists() else '{{' + name + '}}'


def session_details(session):
    files = list((CODEX_HOME / 'sessions').rglob(f'*{session}.jsonl'))
    revised, model = None, None
    for line in files[0].read_text().splitlines() if files else []:
        if 'image_gen.generation' in line:
            item = json.loads(line).get('payload', {}).get('item', {})
            revised = item.get('revisedPrompt') or revised
        m = re.search(r'"model":\s*"([^"]+)"', line)
        if m and not model:
            model = m[1]
    return revised, model


def next_version(person, job_id):
    # number from the manifest, not the folder: retired versions are deleted from disk but stay in the log
    manifest = person.out / 'manifest.jsonl'
    logged = [json.loads(l)['version'] for l in manifest.read_text().splitlines()
              if l.strip() and json.loads(l)['job'] == job_id] if manifest.exists() else []
    return 1 + max(logged + [len(list(person.out.glob(f'{job_id}-v*.png')))])


def run(person, job_id):
    job = person.jobs[job_id]
    refs = job['refs']
    if len(refs) > MAX_REFS:
        raise ValueError(f'{job_id}: {len(refs)} refs > {MAX_REFS}; combine angles into a board (prep_refs.py board)')
    prompt = person.render(job['prompt'])
    ref_hashes = [{'id': r, 'sha256': sha((person.refpack / f'{r}.jpg').read_bytes())} for r in refs]
    listing = ''.join(f"Image {i + 1}: {person.labels[r]}\n" for i, r in enumerate(refs))
    text = PREAMBLE.format(name=person.cfg['name']) + listing + '\nBRIEF\n' + prompt
    with tempfile.TemporaryDirectory() as tmp:
        args = ['codex', 'exec', '--skip-git-repo-check', '-s', 'read-only', '-c', 'model_reasoning_effort="low"']
        for r in refs:
            args += ['-i', str(person.refpack / f'{r}.jpg')]
        started = datetime.now(timezone.utc).isoformat()
        proc = subprocess.run(args, input=text, capture_output=True, text=True, timeout=1800, cwd=tmp)
    log = proc.stdout + proc.stderr
    m = re.search(r'session id: ([0-9a-f-]{36})', log)
    folder = CODEX_HOME / 'generated_images' / m[1] if m else None
    pngs = sorted(folder.glob('*.png')) if folder and folder.exists() else []
    if not pngs:  # the agent may still reply DONE after a tool error, so trust only the file
        raise RuntimeError(f'{job_id}: Codex returned no image. Tail: {log[-600:]}')
    person.out.mkdir(parents=True, exist_ok=True)
    version = next_version(person, job_id)
    dest = person.out / f'{job_id}-v{version}.png'
    shutil.copy2(pngs[-1], dest)
    with Image.open(dest) as img:
        width, height = img.size
        thumb = img.convert('RGB')
        thumb.thumbnail((1200, 1200), Image.LANCZOS)
        thumb.save(dest.with_suffix('.webp'), 'WEBP', quality=84, method=6)
    revised, agent = session_details(m[1])
    row = {
        'job': job_id, 'version': version, 'file': dest.name, 'thumbnail': dest.with_suffix('.webp').name,
        'width': width, 'height': height, 'sha256': sha(dest.read_bytes()),
        'engine': 'Codex CLI built-in image_gen (ChatGPT subscription auth; C2PA: ChatGPT gpt-image)',
        'codex_agent_model': agent, 'codex_session': m[1],
        'prompt_file': str((person.prompts / f"{job['prompt']}.md").relative_to(REPO)), 'prompt_sha256': sha(prompt.encode()),
        'references': ref_hashes, 'revised_prompt': revised,
        'started_at': started, 'finished_at': datetime.now(timezone.utc).isoformat(),
        'label': 'AI-generated likeness from owner-supplied reference photos/video; not a photograph',
    }
    with open(person.out / 'manifest.jsonl', 'a') as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(json.dumps(row, ensure_ascii=False) + '\n')
    print(json.dumps({'generated': dest.name, 'size': [width, height], 'session': m[1]}), flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--person', required=True, help='person folder, e.g. people/<slug>')
    ap.add_argument('--render-only', action='store_true', help='print the expanded prompt(s) instead of generating')
    ap.add_argument('jobs', nargs='+')
    a = ap.parse_args()
    person = Person(a.person)
    for j in a.jobs:
        if a.render_only:
            print(f'===== {j}\n' + person.render(person.jobs[j]['prompt']))
            continue
        try:
            run(person, j)
        except Exception as e:  # report and continue with the next job
            print(json.dumps({'job': j, 'error': str(e)[:800]}), flush=True)


if __name__ == '__main__':
    sys.exit(main())
