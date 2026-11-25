"""Public discovery is deliberately distinguished from a complete account export."""
from __future__ import annotations

import hashlib
import html
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

UA = "Mozilla/5.0"
RESERVED = {"p", "reel", "reels", "stories", "explore", "accounts", "direct"}


def now():
    return datetime.now(timezone.utc).isoformat()


def profile_name(value: str) -> str:
    if "://" in value:
        p = urlparse(value)
        if p.scheme != "https" or p.hostname not in {"instagram.com", "www.instagram.com"}:
            raise ValueError("Use an HTTPS instagram.com profile URL")
        parts = p.path.strip("/").split("/")
        if len(parts) != 1:
            raise ValueError("Provide a profile URL, not a post or story URL")
        value = parts[0]
    value = value.removeprefix("@")
    if not re.fullmatch(r"[A-Za-z0-9_.]{1,30}", value) or value.lower() in RESERVED or not value.strip('.') or '..' in value:
        raise ValueError("Invalid Instagram username")
    return value.lower()


def shortcode(url: str) -> str:
    p = urlparse(url)
    if p.hostname not in {"instagram.com", "www.instagram.com"}:
        raise ValueError("Not an Instagram post URL")
    match = re.fullmatch(r"/(?:p|reel|reels)/([A-Za-z0-9_-]+)/?", p.path)
    if not match:
        raise ValueError("Invalid Instagram post URL")
    return match[1]


def embedded_context(text: str) -> dict:
    match = re.search(r'"contextJSON":("(?:\\.|[^"\\])*")', text)
    if not match:
        raise ValueError("Public embed has no media payload (login, unavailable, or format changed)")
    return json.loads(json.loads(match[1]))


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def fetch(url: str, *, binary=False):
    response = requests.get(url, headers={"User-Agent": UA}, timeout=(15, 90))
    response.raise_for_status()
    return response.content if binary else response.text


def caption(media):
    return "\n".join(x["node"].get("text", "") for x in media.get("edge_media_to_caption", {}).get("edges", []))


def discover(username: str, root: Path, max_pages=100, extra_urls=None):
    root.mkdir(parents=True, exist_ok=True)
    records = {}
    manifest = {"username": username, "profile_url": f"https://www.instagram.com/{username}/",
                "retrieved_at": now(), "profile_posts_reported": None,
                "archive_exhausted": False, "account_complete": False, "attempts": [], "posts": []}

    def add(url, source, **metadata):
        code = shortcode(url)
        item = records.setdefault(code, {"shortcode": code, "url": f"https://www.instagram.com/p/{code}/", "discovered_via": []})
        if source not in item["discovered_via"]:
            item["discovered_via"].append(source)
        item.update(metadata)

    try:
        url = manifest["profile_url"] + "embed/"
        text = fetch(url)
        (root / "profile-embed.html").write_text(text)
        context = embedded_context(text)["context"]
        save_json(root / "profile.json", context)
        manifest["profile_posts_reported"] = context.get("posts_count")
        manifest["followers_reported"] = context.get("followers_count")
        manifest["display_name"] = context.get("full_name")
        for entry in context.get("graphql_media", []):
            m = entry["shortcode_media"]
            add(f"https://www.instagram.com/p/{m['shortcode']}/", "instagram_profile_embed",
                caption=caption(m), profile_metadata=m)
        manifest["attempts"].append({"source": url, "status": "ok"})
    except (requests.RequestException, ValueError, KeyError) as e:
        manifest["attempts"].append({"source": "instagram_profile_embed", "status": "failed", "reason": str(e)[:250]})

    for page in range(1, max_pages + 1):
        url = f"https://rist.media/api/profile/posts?username={username}&platform=instagram&tab=all&page={page}&limit=50"
        try:
            data = json.loads(fetch(url))
            save_json(root / "discovery" / f"rist-{page:04d}.json", data)
            before = len(records)
            for m in data.get("data", []):
                add(m["url"], "rist_public_archive", archive=m)
            manifest["archive_total_reported"] = data.get("total")
            manifest["attempts"].append({"source": url, "status": "ok", "records": len(data.get("data", []))})
            if not data.get("hasMore"):
                manifest["archive_exhausted"] = True
                break
            if not data.get("data") or (page > 1 and len(records) == before):
                manifest["attempts"].append({"source": "rist", "status": "stopped", "reason": "pagination made no progress"})
                break
            time.sleep(0.5)
        except (requests.RequestException, ValueError, KeyError) as e:
            manifest["attempts"].append({"source": url, "status": "failed", "reason": str(e)[:250]})
            break
    try:
        url = f"https://22flr.com/account/{username}/"
        text = fetch(url)
        (root / "floor.html").write_text(text)
        text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
        for code in re.findall(r'https?://(?:www\.)?instagram\.com/p/([A-Za-z0-9_-]+)/', text):
            # This page contains a site-wide advertisement; ownership is checked below.
            add(f"https://www.instagram.com/p/{code}/", "22flr_public_page")
        manifest["attempts"].append({"source": url, "status": "ok"})
    except requests.RequestException as e:
        manifest["attempts"].append({"source": "22flr", "status": "failed", "reason": str(e)[:250]})
    for url in extra_urls or []:
        add(url, "supplied_post_url")
    manifest["posts"] = list(records.values())
    save_json(root / "manifest.json", manifest)
    return manifest


def media_children(media):
    edges = media.get("edge_sidecar_to_children", {}).get("edges", [])
    return [x["node"] for x in edges] if edges else [media]


def download_posts(root: Path, delay=0.6):
    manifest = json.loads((root / "manifest.json").read_text())
    for i, post in enumerate(manifest["posts"]):
        folder = root / "posts" / post["shortcode"]
        folder.mkdir(parents=True, exist_ok=True)
        try:
            cache = folder / "media.json"
            if cache.exists():
                media = json.loads(cache.read_text())
            else:
                text = fetch(post["url"] + "embed/captioned/")
                try:
                    context = embedded_context(text)
                except ValueError:
                    # A second public embed representation sometimes remains available.
                    text = fetch(post["url"] + "embed/")
                    context = embedded_context(text)
                (folder / "embed.html").write_text(text)
                media = context["gql_data"]["shortcode_media"]
                save_json(cache, media)
            owner = media.get("owner", {}).get("username", "").lower()
            post["owner"] = owner
            # Explicit coauthor metadata can establish a collaboration; a tag alone cannot.
            coauthors = post.get("profile_metadata", {}).get("coauthor_producers", [])
            embed_path = folder / "embed.html"
            embed_text = embed_path.read_text() if embed_path.exists() else ""
            header_handles = [h.lower() for h in re.findall(r'<a class="[^"]*CollabAvatar[^\"]*" href="https://www\.instagram\.com/([A-Za-z0-9_.]+)/', embed_text)]
            post["coauthors_from_embed_header"] = sorted(set(header_handles))
            associated = manifest["username"] in [x.get("username", "").lower() for x in coauthors] + header_handles
            if owner != manifest["username"] and not associated:
                post["status"] = "excluded_owner_mismatch"
                continue
            post.update(status="metadata_only", caption=caption(media) or post.get("caption", ""),
                        type=media.get("__typename"), assets=[])
            for j, child in enumerate(media_children(media)):
                video = child.get("is_video", False)
                url = child.get("video_url") if video else child.get("display_url")
                asset = {"index": j, "kind": "video" if video else "image", "duration": child.get("video_duration"),
                         "status": "missing_url"}
                post["assets"].append(asset)
                if not url:
                    continue
                path = folder / f"asset-{j:02d}.{'mp4' if video else 'jpg'}"
                try:
                    if not path.exists():
                        data = fetch(url, binary=True)
                        if len(data) < 500:
                            raise ValueError("Media response too small")
                        path.write_bytes(data)
                    asset.update(status="downloaded", path=str(path.relative_to(root)), bytes=path.stat().st_size,
                                 sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                except (requests.RequestException, ValueError) as e:
                    asset.update(status="failed", error=type(e).__name__)
            ok = sum(a["status"] == "downloaded" for a in post["assets"])
            post["status"] = "downloaded" if ok == len(post["assets"]) else ("partial" if ok else "metadata_only")
        except (requests.RequestException, ValueError, KeyError) as e:
            post.update(status="failed", error=str(e)[:250])
        finally:
            save_json(root / "manifest.json", manifest)
            print(f"[{i+1}/{len(manifest['posts'])}] {post['shortcode']}: {post.get('status')}", flush=True)
            time.sleep(delay)
    return manifest
