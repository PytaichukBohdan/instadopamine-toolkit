"""Publish reviewed synthetic images separately from original source evidence."""
import hashlib
import json
import re
from pathlib import Path

from PIL import Image


def load_generated_images(wiki: Path):
    manifest = wiki / "generated-images.json"
    if not manifest.exists():
        return []
    rows = json.loads(manifest.read_text())["images"]
    seen = set()
    for row in rows:
        name = row["path"]
        if not re.fullmatch(r"generated/[A-Za-z0-9_.-]+\.png", name) or name in seen:
            raise ValueError("Generated image must have a unique allowlisted PNG path")
        seen.add(name)
        path = wiki / name
        if path.is_symlink() or not path.resolve().is_relative_to(wiki.resolve()):
            raise ValueError("Generated image escapes wiki or is a symlink")
        if row.get("kind") != "ai_visual_synthesis" or not row.get("model"):
            raise ValueError("Generated image must be labeled with its model and synthetic kind")
        if any(type(row.get(k)) is not int or row[k] <= 0 for k in ("width", "height")):
            raise ValueError("Invalid generated image dimensions")
        if path.stat().st_size >= 25 * 1024 * 1024:
            raise ValueError("Generated image exceeds Pages asset limit")
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("Generated image hash mismatch")
        with Image.open(path) as img:
            if img.format != "PNG" or img.size != (row["width"], row["height"]):
                raise ValueError("Generated image format or dimensions mismatch")
            img.verify()
        if 'thumbnail' in row:
            name = row['thumbnail']
            if not re.fullmatch(r'generated/[A-Za-z0-9_.-]+\.webp', name) or name in seen:
                raise ValueError('Generated thumbnail must have a unique allowlisted WebP path')
            seen.add(name)
            thumbnail = wiki / name
            if thumbnail.is_symlink() or not thumbnail.resolve().is_relative_to(wiki.resolve()):
                raise ValueError('Generated thumbnail escapes wiki or is a symlink')
            if hashlib.sha256(thumbnail.read_bytes()).hexdigest() != row.get('thumbnail_sha256'):
                raise ValueError('Generated thumbnail hash mismatch')
            with Image.open(thumbnail) as img:
                if img.format != 'WEBP' or max(img.size) > 640:
                    raise ValueError('Invalid generated thumbnail format or size')
                img.verify()
    return rows
