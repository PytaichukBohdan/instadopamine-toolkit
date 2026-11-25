#!/usr/bin/env python3
"""Stage 2: generate the costume sheet and one preview frame per shot with the Codex CLI's
built-in image tool, on the ChatGPT subscription.

Usage:
    python3 preview_frames.py ../productions/<slug>/production.yaml [ID ...] [--jobs 3] [--render-only]

- No IDs: every asset, then every shot (assets first, because shots reference the sheet).
- Each asset or shot needs `preview_refs` (keys from the cast's <name>.refs.json, or the id of any asset
  in this production, e.g. "sheet", a plate or a second character's sheet; an empty list is fine for
  plates and moodboards) and a still description (`still:` for shots; assets use their assembled
  image prompt from prompts/<id>.txt).
- Cast files are looked up in <production>/cast/ first (invented characters for one film), then in
  ../cast/. A shot's `cast:` picks whose FACE blocks are prepended (default: the first cast member);
  its wardrobe line is `wardrobe:`, else `looks[<look>]`, else the production's `wardrobe`.
- Output: frames/<id>-v<N>.jpg (shots centre-cropped to the delivery aspect), a symlink
  frames/<id>.jpg pointing at the newest version, and frames/manifest.jsonl with hashes, refs,
  the Codex session id and the tool's revised prompt. Full-size PNGs are kept in
  /mnt/data/video-dna-cache/<slug>/.

No API path exists here: /usr/local/bin/codex strips OPENAI_API_KEY and runs on the ChatGPT login.
A missing or expired login is a hard failure. The image tool takes at most 5 reference images.
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]          # video-dna/
REPO = ROOT.parent
CACHE = Path("/mnt/data/video-dna-cache")
CODEX_HOME = Path.home() / ".codex"
MAX_REFS = 5
ASPECTS = {"4:3": 4 / 3, "16:9": 16 / 9, "9:16": 9 / 16, "3:2": 3 / 2, "1:1": 1.0}

PREAMBLE = """Use your built-in image generation tool exactly once, then reply DONE. Do not write files or run commands.
Pass the brief below to the image tool as completely and literally as you can: keep every rule, ban and count; do not summarise it away; do not add new creative ideas.
The attached images are references of this film's cast (the lead is a real person; any other character is defined by her or his own sheet), their costume sheets and empty location plates. They are identity, wardrobe, body and geometry references only: never copy their backgrounds, studio light, panel layout or cropping.
Attached references, in order:
"""


def sha(b):
    return hashlib.sha256(b).hexdigest()


def resolve_repo_file(rel):
    """Return a local path for a repo file, extracting it from git history if this branch lacks it."""
    p = REPO / rel
    if p.exists():
        return p
    out = CACHE / "repo" / rel
    if out.exists():
        return out
    commit = subprocess.run(["git", "-C", str(REPO), "log", "--all", "-1", "--format=%H", "--", rel],
                            capture_output=True, text=True).stdout.strip()
    if not commit:
        sys.exit(f"reference not found in any branch: {rel}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(subprocess.run(["git", "-C", str(REPO), "show", f"{commit}:{rel}"], capture_output=True, check=True).stdout)
    return out


def upload_copy(src, slug):
    """Downscale a reference to a 1536 px JPEG for upload (as the passport toolkit does)."""
    dst = CACHE / slug / "refs" / (Path(src).stem + ".jpg")
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-vf", "scale='min(1536,iw)':-2", "-q:v", "3", str(dst)], check=True)
    return dst


def cast_file(base, name, ext):
    """A production-local cast file (an invented character for one film) wins over ../cast/."""
    for folder in (base / "cast", ROOT / "cast"):
        if (folder / f"{name}{ext}").exists():
            return folder / f"{name}{ext}"
    return None


def cast_text(base, name, section):
    path = cast_file(base, name, ".md")
    if not path:
        return ""
    text = path.read_text()
    m = re.search(rf"^## {section}\b.*?\n(.*?)(?=^## |\Z)", text, flags=re.S | re.M)
    return re.sub(r"<!--.*?-->", "", m.group(1), flags=re.S).replace("**", "").strip() if m else ""


def build_job(prod, base, item, is_shot):
    cast_all = prod.get("cast", ["lead"])
    cast_here = item.get("cast", cast_all[:1])
    refmap = {}
    for c in cast_all:
        path = cast_file(base, c, ".refs.json")
        for key, value in (json.loads(path.read_text()) if path else {}).items():
            if not key.startswith("_"):
                refmap.setdefault(key, value)
    assets = {a["id"]: a for a in prod.get("assets", [])}
    refs = []
    for key in item.get("preview_refs", []):
        if key in assets or key == "sheet":
            img = base / "frames" / f"{key}.jpg"
            if not img.exists():
                raise RuntimeError(f"{item['id']}: needs {key} first (frames/{key}.jpg)")
            label = assets.get(key, {}).get("ref_label") or (
                "The lead's costume sheet for THIS film: wardrobe and hair as they must appear" if key == "sheet" else assets[key].get("title", key))
            refs.append((img.resolve(), label))
        else:
            refs.append((upload_copy(resolve_repo_file(refmap[key]["path"]), prod["slug"]), refmap[key]["label"]))
    if len(refs) > MAX_REFS:
        raise RuntimeError(f"{item['id']}: {len(refs)} refs > {MAX_REFS}")
    if is_shot:
        wardrobe = (item.get("wardrobe") or (prod.get("looks") or {}).get(item.get("look")) or prod.get("wardrobe", "")) if cast_here else ""
        brief = "\n\n".join(x for x in [
            *(cast_text(base, c, "FACE") for c in cast_here),
            cast_text(base, cast_here[0], "MARKS") if item.get("marks") and cast_here else "",
            item["still"].strip(),
            "WARDROBE (identical to the costume sheet): " + wardrobe if wardrobe else "",
            "LIGHT: take the light from this scene only; do not copy the flat studio light of the reference sheets.",
            f"FRAME: a landscape photograph; keep every important element inside the central {prod['delivery']['aspect']} area "
            "because the image will be centre-cropped to that aspect. Photoreal film still, not an illustration. "
            + ("No added text, logos or watermark; the only lettering is his own small forearm tattoo." if item.get("marks") else "No text, no logos, no watermark.")
        ] if x)
    else:
        prompt_file = base / "prompts" / f"{item['id']}.txt"
        if not prompt_file.exists():
            raise RuntimeError(f"{item['id']}: run assemble_prompts.py first")
        brief = prompt_file.read_text().strip() + "\n\nA landscape image. No text, no labels, no logos."
    listing = "".join(f"Image {i + 1}: {label}\n" for i, (_, label) in enumerate(refs))
    return PREAMBLE + listing + "\nBRIEF\n" + brief, refs


def next_version(frames, item_id):
    vs = [int(m.group(1)) for f in frames.glob(f"{item_id}-v*.jpg") if (m := re.search(r"-v(\d+)\.jpg$", f.name))]
    return max(vs, default=0) + 1


def run_job(prod, base, item, is_shot, render_only=False):
    text, refs = build_job(prod, base, item, is_shot)
    if render_only:
        return {"id": item["id"], "prompt": text, "refs": [str(r) for r, _ in refs]}
    args = ["codex", "exec", "--skip-git-repo-check", "-s", "read-only", "-c", 'model_reasoning_effort="low"']
    for r, _ in refs:
        args += ["-i", str(r)]
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run(args, input=text, capture_output=True, text=True, timeout=1800, cwd=tmp)
    log = proc.stdout + proc.stderr
    m = re.search(r"session id: ([0-9a-f-]{36})", log)
    folder = CODEX_HOME / "generated_images" / m[1] if m else None
    pngs = sorted(folder.glob("*.png")) if folder and folder.exists() else []
    if not pngs:  # the agent can reply DONE after a tool error, so trust only the file
        raise RuntimeError(f"{item['id']}: Codex returned no image. Tail: {log[-500:]}")
    frames = base / "frames"
    frames.mkdir(exist_ok=True)
    version = next_version(frames, item["id"])
    full = CACHE / prod["slug"] / f"{item['id']}-v{version}.png"
    full.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pngs[-1], full)
    out = frames / f"{item['id']}-v{version}.jpg"
    vf = "scale='min(1600,iw)':-2"
    if is_shot:
        ar = ASPECTS[prod["delivery"]["aspect"]]
        vf = f"crop='min(iw,ih*{ar:.6f})':'min(ih,iw/{ar:.6f})',scale='min(1600,iw)':-2"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(full), "-vf", vf, "-q:v", "3", str(out)], check=True)
    link = frames / f"{item['id']}.jpg"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(out.name)
    revised = None
    for f in (CODEX_HOME / "sessions").rglob(f"*{m[1]}.jsonl"):
        for line in f.read_text().splitlines():
            if "image_gen" in line and "revisedPrompt" in line:
                revised = json.loads(line).get("payload", {}).get("item", {}).get("revisedPrompt") or revised
    row = {"id": item["id"], "version": version, "file": out.name, "png_cache": str(full), "sha256": sha(full.read_bytes()),
           "prompt_sha256": sha(text.encode()), "refs": [{"file": str(r), "sha256": sha(Path(r).read_bytes())} for r, _ in refs],
           "engine": "Codex CLI built-in image_gen (ChatGPT subscription)", "codex_session": m[1], "revised_prompt": revised,
           "started_at": started, "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "label": "AI-generated preview frame; not a photograph"}
    with open(frames / "manifest.jsonl", "a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"id": item["id"], "file": out.name}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("production")
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--render-only", action="store_true")
    a = ap.parse_args()
    path = Path(a.production).resolve()
    base, prod = path.parent, yaml.safe_load(path.read_text())
    assets = [x for x in prod.get("assets", []) if "preview_refs" in x and (not a.ids or x["id"] in a.ids)]
    shots = [x for x in prod.get("shots", []) if "preview_refs" in x and x.get("still") and (not a.ids or x["id"] in a.ids)]
    ids = {x["id"] for x in prod.get("assets", [])} | {"sheet"}
    # assets first, because shots reference them; assets that reference no other asset run in parallel
    waves = [[x for x in assets if not ids & set(x["preview_refs"])], [x for x in assets if ids & set(x["preview_refs"])],
             [(s, True) for s in shots]]
    for wave in waves:
        with cf.ThreadPoolExecutor(a.jobs) as ex:
            futs = {}
            for entry in wave:
                item, is_shot = entry if isinstance(entry, tuple) else (entry, False)
                futs[ex.submit(run_job, prod, base, item, is_shot, a.render_only)] = item["id"]
            for f in cf.as_completed(futs):
                try:
                    print(json.dumps(f.result(), ensure_ascii=False), flush=True)
                except Exception as e:
                    print(json.dumps({"id": futs[f], "error": str(e)[:600]}), flush=True)


if __name__ == "__main__":
    main()
