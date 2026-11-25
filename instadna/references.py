"""Validate and render the explicit, reviewed reference-image publication manifest."""
import hashlib
import html
import json
import math
import re
from pathlib import Path

from PIL import Image
from .passport_items import evidence_date


def load_references(wiki: Path):
    manifest = wiki / "visual-atlas.json"
    if not manifest.exists():
        return []
    references = json.loads(manifest.read_text())["references"]
    seen = set()
    for row in references:
        if 'published_at' in row:
            evidence_date(row['published_at'])
        for field in ["width", "height"]:
            if type(row[field]) is not int or row[field] <= 0:
                raise ValueError("Invalid reference dimensions")
        if type(row["asset_index"]) is not int or row["asset_index"] < 0:
            raise ValueError("Invalid reference asset index")
        time = row["time_seconds"]
        if row["kind"] == "video":
            if type(time) not in (int, float) or not math.isfinite(time) or time < 0:
                raise ValueError("Invalid reference video timestamp")
        elif row["kind"] not in {"image", "video_poster"} or time is not None:
            raise ValueError("Still reference must not have a timestamp")
        if not re.fullmatch(r"R[0-9]+", row["id"]) or row["id"] in seen:
            raise ValueError("Invalid or duplicate reference ID")
        seen.add(row["id"])
        if not re.fullmatch(r"[A-Za-z0-9_-]+", row["shortcode"]):
            raise ValueError("Invalid reference source")
        source_kind = row.get("source_kind", "feed")
        if source_kind == "highlight":
            if not all(re.fullmatch(r"[0-9]+", str(row.get(k, ""))) for k in ("highlight_id", "story_id")):
                raise ValueError("Highlight reference requires collection and story IDs")
            expected_url = f"https://www.instagram.com/stories/highlights/{row['highlight_id']}/?story_media_id={row['story_id']}"
            if row["shortcode"] != "H" + row["highlight_id"]:
                raise ValueError("Highlight source note must match collection")
        elif source_kind == "feed":
            expected_url = f"https://www.instagram.com/p/{row['shortcode']}/"
        else:
            raise ValueError("Unknown reference source kind")
        if row["source_url"] != expected_url:
            raise ValueError("Reference URL does not match source")
        for field, digest_field in [("image", "sha256"), ("thumbnail", "thumbnail_sha256")]:
            name = row[field]
            if not re.fullmatch(r"references/[A-Za-z0-9_.-]+\.(png|webp)", name):
                raise ValueError("Reference must be an allowlisted local PNG or WebP")
            path = wiki / name
            if path.is_symlink() or not path.resolve().is_relative_to(wiki.resolve()):
                raise ValueError("Reference escapes wiki or is a symlink")
            if hashlib.sha256(path.read_bytes()).hexdigest() != row[digest_field]:
                raise ValueError(f"Reference hash mismatch: {name}")
            with Image.open(path) as img:
                if field == "image" and img.size != (row["width"], row["height"]):
                    raise ValueError("Reference dimensions do not match image")
                img.verify()
            if path.stat().st_size >= 25 * 1024 * 1024:
                raise ValueError("Reference exceeds Pages asset limit")
    return references


def render_gallery(references):
    esc = html.escape
    categories = list(dict.fromkeys(r["category"] for r in references))
    buttons = '<button type="button" data-filter="all" aria-pressed="true">All</button>'
    buttons += ''.join(f'<button type="button" data-filter="{esc(c)}" aria-pressed="false">{esc(c.title())}</button>' for c in categories)
    cards = []
    for r in references:
        publication = evidence_date(r.get('published_at')) or 'date unknown'
        locator = (f"story {r['asset_index'] + 1} · {r['story_id']} · " if r.get('source_kind') == 'highlight' else f"asset {r['asset_index']} · ") + (f"{r['time_seconds']:g}s" if r['time_seconds'] is not None else "video poster · timestamp unknown" if r['kind'] == 'video_poster' else "still image")
        cards.append(f'''<figure id="{r['id']}" class="reference-card" data-category="{esc(r['category'])}">
<a href="{esc(r['image'])}" class="reference-image" aria-label="Open full-resolution {r['id']}"><img src="{esc(r['thumbnail'])}" alt="{esc(r['title'])}" loading="lazy" width="540" height="720"></a>
<figcaption><span class="eyebrow">{r['id']} · {esc(r['category'])}</span><h3>{esc(r['title'])}</h3>
<p>{esc(r['description'])}</p><p><strong>Use:</strong> {esc(r['use'])}</p><p class="reference-limit">{esc(r['limit'])}</p>
<p class="reference-meta">Published · {esc(publication)}<br>{esc(locator)} · {r['width']} × {r['height']} px<br><a href="sources/{r['shortcode']}.html">Evidence note</a> · <a href="{esc(r['source_url'])}">Instagram source</a><br><a href="{esc(r['image'])}" download>Download full-resolution PNG</a></p></figcaption></figure>''')
    return f'<div class="atlas-controls" aria-label="Filter reference images">{buttons}</div><p id="atlas-count" aria-live="polite">{len(references)} references</p><div class="reference-grid">'+''.join(cards)+'</div>'
