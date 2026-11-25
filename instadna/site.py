"""Only allowlisted wiki content enters the static, fail-closed Pages output."""
from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path

import bleach
import markdown

from .wiki import SECTIONS
from .references import load_references, render_gallery
from .audio_assets import load_audio, render_audio, render_audio_ab, audio_document
from .generated_images import load_generated_images
from .passport_items import load_passport_items, render_passport_items
from .phrases import load_phrases, render_phrases


def safe_markdown(text, allowed_images=frozenset()):
    rendered = markdown.markdown(text, extensions=["tables", "fenced_code", "toc"])
    def image_attribute(tag, name, value):
        return name == "alt" or (name == "src" and value in allowed_images | {"shots/before.png", "shots/after.png", "shots/mobile.png", "shots/audio-before.png", "shots/audio-after.png", "shots/audio-mobile.png", "shots/market-before.png", "shots/market-after.png", "shots/market-mobile.png", "shots/eleven-before.png", "shots/eleven-after.png", "shots/eleven-mobile.png", "shots/post-before.png", "shots/post-after.png", "shots/post-mobile.png", "shots/harness-before.png", "shots/harness-after.png", "shots/harness-mobile.png"})
    return bleach.clean(rendered, tags={"p","a","h1","h2","h3","h4","h5","h6","ul","ol","li","strong","em","code","pre","blockquote","table","thead","tbody","tr","th","td","hr","br","span","div","img"},
                        attributes={"a":["href","title"],"img":image_attribute,"*": ["id","class"]}, protocols={"http","https","mailto"},strip=True)


def ukrainian_script_document(title, content, prefix):
    """A Ukrainian reading surface for the requested Ukrainian-only script."""
    return f'''<!doctype html><html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>{html.escape(title)}</title><link rel="stylesheet" href="{prefix}style.css"></head>
<body><aside><a class="brand" href="{prefix}reel-intro-uk.html"><span class="mark">60</span>ДНК автора</a><div class="eyebrow">АВТОР · САМОПРЕЗЕНТАЦІЯ</div>
<nav><a href="#script">Сценарій і розкадрування</a><a href="#objects">Предмети в історії</a><a href="#editing">Темп і монтаж</a><a href="#basis">На чому побудовано сценарій</a><a href="{prefix}index.html">До дослідження</a></nav><div class="aside-note">УКРАЇНСЬКА ВЕРСІЯ<br>Новий авторський сценарій<br>Жовтень 2026</div></aside>
<main><header><span class="eyebrow">СЦЕНАРІЙ · ОПИСИ КАДРІВ · ОПОРНІ ЗОБРАЖЕННЯ</span><span class="status">60 секунд · 8 епізодів</span></header><article>{content}</article><footer>Текст і розкадрування підготовлено для зйомки. Фактичний хронометраж перевіряється під час пробного читання.</footer></main></body></html>'''


def build_site(wiki: Path, output: Path, public: bool = False):
    wiki, output = wiki.resolve(), output.resolve()
    if output == wiki or output.is_relative_to(wiki) or wiki.is_relative_to(output):
        raise ValueError("Site output and wiki must be separate directories")
    policy_path = wiki / "publication-policy.json"
    restricted = False
    if policy_path.exists():
        policy = json.loads(policy_path.read_text())
        if policy.get("version") != 1 or not isinstance(policy.get("requires_authentication"), bool):
            raise ValueError("Invalid publication policy; refusing to build")
        restricted = policy["requires_authentication"]
        if public and restricted:
            raise ValueError("This wiki includes restricted source-derived analysis; build with authentication, without --public")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Use an empty prepared output directory; never deploy a repository root")
    stats = json.loads((wiki / "coverage.json").read_text())
    references = load_references(wiki)
    audio_assets = load_audio(wiki)
    generated_images = load_generated_images(wiki)
    passport_items = load_passport_items(wiki, references, generated_images)
    phrase_bank = load_phrases(wiki, public=public)
    image_paths = frozenset(r[k] for r in references for k in ["image", "thumbnail"]) | frozenset(r[k] for r in generated_images for k in ["path", "thumbnail"] if k in r)
    nav = [("index", "Overview"), ("reel-intro-uk", "Самопрезентація · 60 секунд"), ("visual-atlas", f"{len(references)} visual references"), ("authenticity", "The concrete DNA"), ("vocabulary","Phrases & recurring фішки"), ("entities","Names, objects & associations"), ("language-ledger","Word-level evidence"), ("highlights","Highlights & informal content"), *[(k,t[0]) for k,t in SECTIONS.items()], ("coverage","Coverage & limits"), ("sources","Evidence library"), ("methodology","Method & maintenance"), ("log","Research log"), ("completion","Delivery report")]
    pages = list(wiki.rglob("*.md"))
    if audio_assets:
        nav.insert(1, ("audio-lab", "Слухати голос · 60 секунд"))
    if generated_images:
        nav.insert(0, ("visual-passport", "Passport · separate items" if passport_items else "Visual person passport · new"))
        if (wiki / 'highlight-inventory.json').exists():
            nav = [(name, label) for name, label in nav if name != 'highlights']
            nav.insert(1, ("highlights", "Highlights · recovered"))
        else:
            nav.insert(1, ("person-dna-round2", "Round two · precise details"))
    if (wiki / 'identity-core.md').exists():
        nav.insert(1, ('identity-core', 'Identity · what stays recognizable'))
    if (wiki / 'telegram-dna.md').exists():
        nav.insert(1, ('telegram-dna', 'Telegram · writing & voice DNA'))
        nav.insert(2, ('telegram-phrases', 'Telegram · dated phrase bank'))
    telegram_stats = json.loads((wiki / 'telegram-coverage.json').read_text()) if (wiki / 'telegram-coverage.json').exists() else None
    if phrase_bank:
        nav.insert(1, ('phrase-bank', 'Original phrases · listen & date'))
    if (wiki / 'time-evidence.md').exists():
        nav.insert(2, ('time-evidence', 'Time · recent, repeated, historical'))
    search = []
    for source in pages:
        if source.name == "AGENTS.md":
            continue
        rel = source.relative_to(wiki)
        text = source.read_text()
        title = re.search(r"^# (.+)$", text, re.M)
        title = title[1] if title else source.stem
        text = re.sub(r'\]\(([^)\s]+)\.md(#[^)]*)?\)', lambda m: "]("+m[1]+".html"+(m[2] or "")+")", text)
        content = safe_markdown(text, image_paths)
        content = re.sub(r'href="(?!https?://)([^"#]+)\.md(#[^"]*)?"',
                         lambda m: f'href="{m[1]}.html{m[2] or ""}"', content)
        if '<div id="reference-gallery"></div>' in content:
            content = content.replace('<div id="reference-gallery"></div>', render_gallery(references))
        if '<div id="audio-gallery"></div>' in content:
            content = content.replace('<div id="audio-gallery"></div>', render_audio(audio_assets))
        if '<div id="passport-items"></div>' in content:
            content = content.replace('<div id="passport-items"></div>', render_passport_items(passport_items))

        if '<div id="audio-ab"></div>' in content:
            content = content.replace('<div id="audio-ab"></div>', render_audio_ab(audio_assets))
        if '<div id="phrase-bank"></div>' in content:
            content = content.replace('<div id="phrase-bank"></div>', render_phrases(phrase_bank))
        depth = len(rel.parts)-1
        prefix = "../" * depth
        menu = "".join(f'<a class="{"active" if source.stem==name else ""}" href="{prefix}{name}.html">{html.escape(label)}</a>' for name,label in nav if (wiki/(name+".md")).exists())
        document = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>{html.escape(title)} · InstaDopamine</title><link rel="stylesheet" href="{prefix}style.css"><script src="{prefix}search.js" defer></script></head>
<body><aside><a class="brand" href="{prefix}index.html"><span class="mark">ID</span>InstaDopamine</a><div class="eyebrow">CREATOR DNA / RESEARCH WIKI</div><label for="search">Search this wiki</label><input id="search" type="search" placeholder="Wardrobe, gestures, hooks…" data-root="{prefix}"><div id="search-results" aria-live="polite"></div><nav>{menu}</nav><div class="aside-note">PRIVATE RESEARCH<br>Source-linked · Text-only edition<br>October 2026</div></aside>
<main><header><span class="eyebrow">PUBLIC CONTENT • PRIVATE ANALYSIS</span><span class="status">Partial archive · explicit evidence</span></header><div class="stats"><div><b>{stats['posts_analyzed']}</b><span>posts analyzed</span></div><div><b>{stats['videos_downloaded']}</b><span>video files</span></div><div><b>{stats['video_minutes_prepared']:.1f}</b><span>minutes recovered</span></div><div><b>{stats['profile_posts_reported'] or '?'}</b><span>profile post count</span></div></div><article>{content}</article><footer>Observations describe published creative content. A sampled archive cannot establish a person's complete life or beliefs.</footer></main></body></html>'''
        if public:
            document = document.replace("PRIVATE RESEARCH", "CREATOR RESEARCH").replace("PUBLIC CONTENT • PRIVATE ANALYSIS", "PUBLIC CONTENT • EVIDENCE REVIEW")
        elif restricted:
            document = document.replace("PUBLIC CONTENT • PRIVATE ANALYSIS", "PUBLISHED CONTENT • PRIVATE ANALYSIS")
        if telegram_stats and (source.stem.startswith('telegram-') or rel.parts[0] == 'telegram-sources'):
            metrics = '<div class="stats">' + ''.join(
                f'<div><b>{html.escape(str(value))}</b><span>{label}</span></div>' for value, label in [
                    (telegram_stats['messages_retrieved'], 'Telegram messages'),
                    (telegram_stats['text_messages_analyzed'], 'written posts reviewed'),
                    (telegram_stats['audio_transcribed'], 'voice transcripts'),
                    (f"{telegram_stats['audio_minutes_transcribed'] / 60:.1f}", 'hours transcribed')]) + '</div>'
            document = re.sub(r'<div class="stats">.*?</div></div><article>', metrics + '<article>', document, count=1)
        if references:
            document = document.replace("Text-only edition", "Visual & verbal edition")
        if source.stem == "visual-atlas":
            document = document.replace('</head>', f'<script src="{prefix}atlas.js" defer></script></head>')
        if source.stem == "visual-passport":
            document = document.replace('<body>', '<body class="passport-page">')
            document = document.replace('</head>', f'<script src="{prefix}passport.js" defer></script></head>')
        if source.stem == 'phrase-bank':
            document = document.replace('</head>', f'<script src="{prefix}audio.js" defer></script><script src="{prefix}phrases.js" defer></script></head>')
        if source.stem == "reel-intro-uk":
            document = ukrainian_script_document(title, content, prefix)
        if source.stem in {"audio-lab", "audio-post", "voice-workflow", "voice-dna", "audio-script", "format-dna", "audio-method", "paid-tts-market"}:
            document = audio_document(title, content, prefix, source_evidence=bool(phrase_bank))
        dest = output / rel.with_suffix(".html")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(document)
        search.append({"title":title,"url":str(rel.with_suffix(".html")),"text":re.sub(r'[#*|\[\]()]',' ',source.read_text())[:35000]})
    (output / "search-index.json").write_text(json.dumps(search,ensure_ascii=False))
    for name in ["style.css", "search.js", "atlas.js", "audio.js", "passport.js", "phrases.js", "_worker.js", "_routes.json"]:
        source_name = "public-worker.js" if public and name == "_worker.js" else name
        shutil.copyfile(Path(__file__).parent / "web" / source_name, output / name)
    # Explicit small text exports only; no raw transcripts, media, credentials or repository files.
    for name in ["coverage.json", "source-inventory.json"]:
        shutil.copyfile(wiki / name, output / name)
    # Only explicitly selected, hash-validated creator references enter publication.
    for name in image_paths:
        (output / name).parent.mkdir(exist_ok=True)
        shutil.copyfile(wiki / name, output / name)
    for name in ["visual-atlas.json", "lexicon.json"]:
        if (wiki / name).exists():
            shutil.copyfile(wiki / name, output / name)
    if generated_images:
        shutil.copyfile(wiki / "generated-images.json", output / "generated-images.json")
    for name in ["passport-items.json", "highlight-inventory.json"]:
        if (wiki / name).exists():
            shutil.copyfile(wiki / name, output / name)
    for name in ["telegram-coverage.json", "telegram-inventory.json", "telegram-phrases.json"]:
        if (wiki / name).exists():
            shutil.copyfile(wiki / name, output / name)
    for row in audio_assets:
        (output / "audio").mkdir(exist_ok=True)
        shutil.copyfile(wiki / row["path"], output / row["path"])
    if audio_assets:
        shutil.copyfile(wiki / "audio-manifest.json", output / "audio-manifest.json")
    if phrase_bank:
        (output / 'audio').mkdir(exist_ok=True)
        for row in phrase_bank['phrases']:
            shutil.copyfile(wiki/row['path'], output/row['path'])
        shutil.copyfile(wiki/'phrase-bank.json', output/'phrase-bank.json')
    # Delivery UI screenshots are separate from creator media.
    for name in ["before.png", "after.png", "mobile.png", "audio-before.png", "audio-after.png", "audio-mobile.png", "market-before.png", "market-after.png", "market-mobile.png", "eleven-before.png", "eleven-after.png", "eleven-mobile.png", "post-before.png", "post-after.png", "post-mobile.png", "harness-before.png", "harness-after.png", "harness-mobile.png"]:
        source = wiki / "shots" / name
        if source.exists():
            (output / "shots").mkdir(exist_ok=True)
            shutil.copyfile(source, output / "shots" / name)
