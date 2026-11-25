from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .collect import discover, download_posts, now, profile_name
from .wiki import SECTIONS, export_sources, lint_wiki, lint_references, synthesize_page


def initialize_wiki(wiki, username, stats):
    index = [f"# @{username} · Creator DNA wiki", "A source-linked analysis of public creative content. Read the coverage page before generalizing from this selective archive.",
             f"**Recovered:** {stats['posts_downloaded']} posts; {stats['videos_downloaded']} videos; {stats['images_downloaded']} still images. **Analyzed:** {stats['posts_analyzed']} posts. **Profile snapshot:** {stats['profile_posts_reported']} posts.",
             "**Workflow stage:** compiled source research. A full passport also needs clean individual visual assets, descriptions/use contexts, a dated phrase/audio bank and reviewed recency/recurrence. Follow the project's person-passport workflow; text compilation alone does not complete those stages."]
    index += [f"- [{title}]({slug}.md) — {SECTIONS[slug][1].split('.')[0]}." for slug,(title,_) in SECTIONS.items() if (wiki/(slug+".md")).exists()]
    index += ["- [Coverage and limits](coverage.md)", "- [Evidence library](sources.md)", "- [Methodology and maintenance](methodology.md)", "- [Research log](log.md)"]
    (wiki / "index.md").write_text("\n\n".join(index) + "\n")
    method = """# Methodology and maintenance

[Wiki home](index.md) · [Coverage](coverage.md)

The wiki uses separate raw evidence, machine observations, and editorial synthesis. Its organization follows the persistent-wiki pattern in [Karpathy's LLM Wiki note](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

## Evidence layers

1. Each acquisition run has its own private corpus directory. It stores original public embed payloads, downloaded media, timestamps and SHA-256 hashes. Raw files and full transcripts are not published.
2. FFmpeg samples a regular time grid, dense opening moments and the final frame. Every frame retains its time and asset index. Carousel photographs have image indices, not timestamps. Audio is transcribed in full where available.
3. A vision model receives contact sheets and the transcript for each post and writes structured observations. These are machine notes, with model and sampling provenance, uncertainty and candidate source locators.
4. Topic pages synthesize the per-post notes. They must distinguish visible detail, creator statement, guest statement and interpretation. Editorial review corrects source/attribution mistakes before strong claims are promoted.

## Working with the wiki

Start at index.md, follow the relevant topic, then inspect its source pages. A citation supports only what that source shows. Do not infer off-camera habits, ownership or friendship from a single appearance. Publishing-account names and coauthor handles are textual metadata, not facial identification.

On new ingestion, preserve the previous raw corpus, collect into a new run, compare source IDs and asset hashes, update the touched topic pages, record contradictions, and append to log.md. Run the link checker after every compilation. Do not quietly replace uncertainty with a confident biography.

## Interpretation limits

Visual sampling can miss fast cuts, gestures and transient objects. ASR can mishear names, slang and mixed Ukrainian/Russian speech. Automatic transcription does not diarize the host and guest reliably. It does not constitute analysis of musical structure, timbre or emotional prosody. The public discovery archive is selective and may omit most historical posts. These limits remain visible in the [coverage ledger](coverage.md).

The compiler prepares research and production briefs. Complete the person-passport workflow with separately generated clean assets, an original evidence atlas, descriptions and use contexts, and a source-linked phrase/audio bank. Track publication dates, first/last observations and independent occasions across all layers. The compiler does not itself generate the images or verify pronunciation.
"""
    if not (wiki / "methodology.md").exists():
        (wiki / "methodology.md").write_text(method)
    with (wiki / "log.md").open("a") as f:
        if f.tell() == 0:
            f.write("# Research log\n\n[Wiki home](index.md)\n")
        f.write(f"\n## [{now()}] compile | @{username}\n\nCompiled {stats['posts_analyzed']} source analyses. Full account coverage remains unproven. See [coverage](coverage.md).\n")


def compile_wiki(root, wiki, username, model, workers):
    stats = export_sources(root, wiki)
    initialize_wiki(wiki, username, stats)
    failures = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(synthesize_page, root, wiki, section, model): section for section in SECTIONS}
        for future in as_completed(futures):
            section = futures[future]
            try:
                future.result()
                print(f"Compiled {section}", flush=True)
            except Exception as e:
                failures.append(section)
                print(f"Failed {section}: {e}", file=sys.stderr, flush=True)
    initialize_wiki(wiki, username, stats)
    if failures:
        raise RuntimeError("Incomplete wiki pages: " + ", ".join(failures))


def main():
    parser = argparse.ArgumentParser(description="Turn an Instagram profile link into an evidence-led creator DNA wiki.")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ["collect", "analyze", "compile", "run"]:
        p = sub.add_parser(command)
        if command in {"collect", "run"}:
            p.add_argument("profile", type=profile_name)
            p.add_argument("--urls", type=Path, help="Optional newline-delimited public post URLs to extend discovery")
        p.add_argument("--root", type=Path, required=True, help="Private corpus directory; use a fresh directory for each acquisition run")
        if command in {"analyze", "compile", "run"}:
            p.add_argument("--model", default="gpt-5.4")
            p.add_argument("--workers", type=int, default=2)
        if command in {"analyze", "run"}:
            p.add_argument("--interval", type=float, default=3.0)
            p.add_argument("--asr", choices=["openai", "local"], default="openai")
        if command in {"compile", "run"}:
            p.add_argument("--wiki", type=Path, required=True)
    p = sub.add_parser("build")
    p.add_argument("--wiki", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True, help="Empty directory containing only prepared site output")
    p.add_argument("--public", action="store_true", help="Publish without login only when the owner explicitly authorizes public access")
    p = sub.add_parser("edition", help="Build one person's protected multi-platform edition from its reviewed manifests")
    p.add_argument("--wiki", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True, help="Empty directory containing only prepared site output")
    p.add_argument("--data-room", type=Path, help="Private data-room export (JSON + WebP) attached to the protected build")
    p = sub.add_parser("lint")
    p.add_argument("--wiki", type=Path, required=True)
    p.add_argument("--root", type=Path, help="Also verify reference locators against this private corpus")
    args = parser.parse_args()
    try:
        if args.command in {"collect", "run"}:
            if (args.root / "manifest.json").exists():
                manifest = json.loads((args.root / "manifest.json").read_text())
                if manifest["username"] != args.profile:
                    raise ValueError("Corpus belongs to a different profile")
                if args.urls:
                    raise ValueError("Additional discovery requires a fresh corpus directory")
            else:
                urls = [u.strip() for u in args.urls.read_text().splitlines() if u.strip()] if args.urls else None
                discover(args.profile, args.root, extra_urls=urls)
            download_posts(args.root)
        if args.command in {"analyze", "run"}:
            from .analyze import analyze_all
            if args.interval <= 0 or args.workers < 1:
                raise ValueError("Interval and workers must be positive")
            results = analyze_all(args.root, interval=args.interval, backend=args.asr, model=args.model, workers=args.workers)
            if any(x["status"] == "failed" for x in results):
                raise RuntimeError("Some media analyses failed; see analysis-status.json. Rerun to resume before compiling.")
        if args.command in {"compile", "run"}:
            manifest = json.loads((args.root / "manifest.json").read_text())
            compile_wiki(args.root, args.wiki, manifest["username"], args.model, args.workers)
            errors = lint_wiki(args.wiki)
            if errors:
                raise RuntimeError("Wiki link verification failed: " + "; ".join(errors))
        if args.command == "build":
            from .site import build_site
            build_site(args.wiki, args.output, public=args.public)
        if args.command == "edition":
            from .edition import build_edition
            print(json.dumps(build_edition(args.wiki, args.output, args.data_room)))
        if args.command == "lint":
            errors = lint_wiki(args.wiki)
            if args.root:
                errors.extend(lint_references(args.wiki, args.root))
            print("\n".join(errors) if errors else "Wiki links pass")
            if errors:
                return 1
    except (ValueError, RuntimeError, OSError) as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
