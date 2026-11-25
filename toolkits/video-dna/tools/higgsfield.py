#!/usr/bin/env python3
"""Stage 3 bridge to the Higgsfield API (Seedance 2.5), with the official Python SDK `higgsfield-client`.

Set up on 2026-10-12. The `check` and `estimate` commands never generate anything: they call Higgsfield's
free /estimate endpoint. `generate` is the only command that spends credits; it refuses to run
without --confirm-spend, which needs the owner's explicit "go" (workflow/03-generation.md).

Credentials
    HF_KEY="<key-id>:<key-secret>" lives in .env.local at the repo root (git-ignored, chmod 600).
    It is loaded at runtime with python-dotenv and only ever sent in the Authorization header.
    This tool never prints, logs or writes it. Override the file with HF_ENV_FILE=/path/to/.env.local.
    Server-side only: never ship the key to a browser page.

Install (the project's uv venv)
    uv pip install --python /mnt/data/video-dna-venv/bin/python -r video-dna/tools/requirements.txt

Usage
    PY=/mnt/data/video-dna-venv/bin/python
    $PY tools/higgsfield.py check                                    # key loads + one free estimate
    $PY tools/higgsfield.py estimate productions/<slug>/production.yaml   # draft and final cost per shot
    $PY tools/higgsfield.py generate productions/<slug>/production.yaml s03 --resolution 480p --confirm-spend

Seedance 2.5 endpoints (docs.higgsfield.ai/docs/models/seedance-2-5, read 2026-10-12)
    bytedance/seedance-2.5/text-to-video       prompt; duration 4–30 (default 5); resolution 480p|720p|1080p
                                               (default 720p); aspect_ratio 16:9|4:3|1:1|3:4|9:16|21:9;
                                               bitrate_mode; output_format mp4|mov; generate_audio (default true)
    bytedance/seedance-2.5/image-to-video      image_url (required, public URL), end_image_url, prompt, duration,
                                               resolution, bitrate_mode, generate_audio. Framing follows the image.
    bytedance/seedance-2.5/reference-to-video  image_urls (≤30) / video_urls (≤10) / audio_urls (≤10), prompt,
                                               duration, resolution, aspect_ratio, generate_audio
    Requests are asynchronous: queued → in_progress → completed | failed | nsfw | canceled. Failed and nsfw
    requests are not charged. Outputs are kept for at least 7 days, so `generate` downloads them at once.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]          # video-dna/
REPO = ROOT.parent
API = "https://api.higgsfield.ai"
SEEDANCE = "bytedance/seedance-2.5"


def env_file():
    """The first .env.local found: $HF_ENV_FILE, this checkout's root, then the main checkout's root."""
    if os.getenv("HF_ENV_FILE"):
        return Path(os.environ["HF_ENV_FILE"])
    candidates = [REPO / ".env.local"]
    common = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True).stdout.strip()
    if common:
        candidates.append(Path(common).parent / ".env.local")
    return next((p for p in candidates if p.exists()), None)


def load_credentials():
    """Load HF_KEY into this process only. Returns where it came from, never the value."""
    path = env_file()
    if path:
        load_dotenv(path, override=False)
    if not (os.getenv("HF_KEY") or (os.getenv("HF_API_KEY") and os.getenv("HF_API_SECRET"))):
        sys.exit("Higgsfield credentials missing: put HF_KEY=<key-id>:<key-secret> in .env.local at the repo root "
                 "(the owner enters it locally; never paste it into chat).")
    return str(path) if path else "environment"


def auth_header():
    from higgsfield_client.auth import get_credential_key
    return {"Authorization": f"Key {get_credential_key()}"}


def estimate(endpoint, body):
    """POST /estimate/<endpoint>: the cost of a request with these parameters. Generates nothing."""
    r = httpx.post(f"{API}/estimate/{endpoint}", json=body, headers=auth_header(), timeout=60)
    if r.status_code != 200:
        detail = r.text[:300]
        try:
            detail = r.json().get("detail", detail)
        except ValueError:
            pass
        raise RuntimeError(f"estimate {endpoint}: HTTP {r.status_code}: {detail}")
    return r.json()


def shot_body(prod, shot, resolution, image_url):
    return {"image_url": image_url, "prompt": prompt_text(prod, shot), "duration": int(shot.get("duration", 5)),
            "resolution": resolution, "generate_audio": True}


def prompt_text(prod, shot):
    path = PROD_DIR / "prompts" / f"{shot['id']}.txt"
    if not path.exists():
        sys.exit(f"{shot['id']}: run assemble_prompts.py first")
    return path.read_text().strip()


def cmd_check(_args):
    source = load_credentials()
    body = {"prompt": "credentials check", "duration": 4, "resolution": "480p", "aspect_ratio": "4:3"}
    est = estimate(f"{SEEDANCE}/text-to-video", body)
    print(json.dumps({"credentials": "loaded", "from": source, "endpoint": f"{SEEDANCE}/text-to-video",
                      "estimate_4s_480p": est, "generated": False}, ensure_ascii=False))


def usd_per_second(est, resolution):
    """Seedance 2.5 estimates come back as a pricing description with per-second USD rates per tier
    (checked 2026-10-12), not as a credit number. Returns the rate for one tier, or None."""
    if est.get("usd") is not None:
        return None
    m = re.search(r"\$([\d.]+) per second of generated video at 480p, \$([\d.]+) at 720p, and \$([\d.]+) at 1080p",
                  est.get("pricing_description", ""))
    return float(m.group(("480p", "720p", "1080p").index(resolution) + 1)) if m else None


def cmd_estimate(args):
    load_credentials()
    rows, totals, description = [], {r: 0.0 for r in args.resolutions}, None
    for shot in PROD.get("shots", []):
        if shot.get("model", "seedance_2_5") != "seedance_2_5":
            continue
        row = {"id": shot["id"], "duration": int(shot.get("duration", 5))}
        for res in args.resolutions:
            # the start frame is uploaded only at generation time; any public URL prices the same request
            est = estimate(f"{SEEDANCE}/image-to-video", shot_body(PROD, shot, res, "https://higgsfield.ai/favicon.ico"))
            rate = usd_per_second(est, res)
            usd = float(est["usd"]) if est.get("usd") is not None else (round(rate * row["duration"], 3) if rate else None)
            row[res] = {"usd": usd, "credits": est.get("credits")}
            description = est.get("pricing_description", description)
            totals[res] += usd or 0.0
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    out = {"production": PROD["slug"], "endpoint": f"{SEEDANCE}/image-to-video", "per_shot": rows,
           "totals_usd": {r: round(v, 2) for r, v in totals.items()}, "pricing_description": description,
           "note": "USD before any account discount, from Higgsfield's /estimate. One take per shot; rerolls multiply it.",
           "estimated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "generated": False}
    (PROD_DIR / "higgsfield_estimate.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({"totals_usd": out["totals_usd"]}, ensure_ascii=False))


def cmd_generate(args):
    """UNTESTED against the live API on purpose: no generation has been authorised yet."""
    if not args.confirm_spend:
        sys.exit("generate spends Higgsfield credits. Re-run with --confirm-spend only after the owner's explicit go.")
    load_credentials()
    import higgsfield_client
    shot = next((s for s in PROD["shots"] if s["id"] == args.shot), None)
    if not shot:
        sys.exit(f"no shot {args.shot}")
    frame = PROD_DIR / shot.get("frame", f"frames/{shot['id']}.jpg")
    image_url = higgsfield_client.upload_file(str(frame.resolve()))
    body = shot_body(PROD, shot, args.resolution, image_url)
    est = estimate(f"{SEEDANCE}/image-to-video", body)
    ctl = higgsfield_client.submit(f"{SEEDANCE}/image-to-video", arguments=body)
    take = {"shot": shot["id"], "request_id": ctl.request_id, "resolution": args.resolution, "duration": body["duration"],
            "estimate": est, "start_frame": str(frame), "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    result = ctl.get()   # polls until a terminal status
    take["status"] = result.get("status")
    if result.get("status") == "completed":
        clips = PROD_DIR / "clips"
        clips.mkdir(exist_ok=True)
        dst = clips / f"{shot['id']}-{args.resolution}-{ctl.request_id[:8]}.mp4"
        dst.write_bytes(httpx.get(result["video"]["url"], timeout=300).content)
        take["file"] = str(dst.relative_to(PROD_DIR))
    with open(PROD_DIR / "takes.jsonl", "a") as fh:
        fh.write(json.dumps(take, ensure_ascii=False) + "\n")
    print(json.dumps(take, ensure_ascii=False))


def main():
    global PROD, PROD_DIR
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    e = sub.add_parser("estimate")
    e.add_argument("production")
    e.add_argument("--resolutions", nargs="+", default=["480p", "1080p"])
    g = sub.add_parser("generate")
    g.add_argument("production")
    g.add_argument("shot")
    g.add_argument("--resolution", default="480p", choices=["480p", "720p", "1080p"])
    g.add_argument("--confirm-spend", action="store_true")
    a = ap.parse_args()
    if a.cmd != "check":
        PROD_DIR = Path(a.production).resolve().parent
        PROD = yaml.safe_load(Path(a.production).read_text())
    {"check": cmd_check, "estimate": cmd_estimate, "generate": cmd_generate}[a.cmd](a)


PROD, PROD_DIR = None, None

if __name__ == "__main__":
    main()
