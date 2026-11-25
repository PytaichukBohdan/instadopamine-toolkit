#!/usr/bin/env python3
"""Transcribe hash-verified Telegram audio into a private, resumable corpus.

No model synthesis, speaker identification, video downloads or publication.
OPENAI_API_KEY is read from the process environment. Original source audio and
complete transcripts must remain outside the repository and publication tree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temp.chmod(0o600)
    temp.replace(path)


def validated_audio(root, record):
    candidate = root / record["path"]
    path = candidate.resolve()
    if not path.is_relative_to(root.resolve()) or candidate.is_symlink():
        raise ValueError("Audio path must remain within the private corpus")
    if sha256(path) != record["sha256"]:
        raise ValueError("Source audio hash mismatch")
    if path.stat().st_size > 24_000_000:
        raise ValueError("Audio needs explicit chunking before a request over 24 MB")
    return path


def transcribe(root, record, key):
    if not str(record["document_id"]).isdigit():
        raise ValueError("Invalid Telegram document ID")
    source = validated_audio(root, record)
    output = root / "transcripts" / (record["document_id"] + ".json")
    if output.exists():
        previous = json.loads(output.read_text())
        if previous.get("source_sha256") == record["sha256"] and previous.get("status") == "transcribed":
            return {"document_id": record["document_id"], "status": "cached"}
    mime = {".ogg": "audio/ogg", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav"}.get(source.suffix, "application/octet-stream")
    for attempt in range(3):
        with source.open("rb") as audio:
            response = requests.post("https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": "Bearer " + key},
                files={"file": (source.name, audio, mime)},
                data={"model": "whisper-1", "response_format": "verbose_json", "timestamp_granularities[]": "segment"},
                timeout=(20, 300))
        if response.status_code == 429 and attempt < 2:
            time.sleep(10 * (attempt + 1))
            continue
        if not response.ok:
            raise RuntimeError(f"Transcription HTTP {response.status_code}")
        result = response.json()
        duration = float(result.get("duration", 0))
        for segment in result.get("segments", []):
            if not 0 <= segment["start"] <= segment["end"] <= duration + 1:
                raise ValueError("Transcription returned invalid source offsets")
        result.update(status="transcribed", model="whisper-1", source_sha256=record["sha256"],
            document_id=record["document_id"], message_id=record["message_id"],
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            reliability="Automatic transcript; source language, speaker attribution and quoted words require review.")
        save(output, result)
        return {"document_id": record["document_id"], "message_id": record["message_id"],
            "status": "transcribed", "duration": duration, "language": result.get("language")}
    raise RuntimeError("Transcription rate limit persisted")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if not 1 <= args.workers <= 8:
        parser.error("Use between one and eight workers")
    os.umask(0o077)
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("OPENAI_API_KEY is not configured")
    root = args.root.resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    records = [r for r in manifest["audio_downloads"] if r["status"] == "downloaded"]
    if args.limit is not None:
        records = records[:args.limit]
    (root / "transcripts").mkdir(exist_ok=True, mode=0o700)
    outcomes = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        tasks = {pool.submit(transcribe, root, row, key): row for row in records}
        for task in as_completed(tasks):
            row = tasks[task]
            try:
                result = task.result()
            except Exception as error:
                # Fixed local exceptions only; HTTP bodies and credentials are never logged.
                result = {"document_id": row["document_id"], "message_id": row["message_id"],
                    "status": "failed", "error": str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__}
            outcomes.append(result)
            save(root / "transcription-status.json", outcomes)
            print(json.dumps({**result, "finished": len(outcomes), "total": len(records)}), flush=True)
    if any(r["status"] == "failed" for r in outcomes):
        raise SystemExit("Some transcriptions failed; completed outputs are cached for resume")


if __name__ == "__main__":
    main()
