"""Publish only explicitly selected, hash-checked generated audio exports."""
import hashlib
import html
import json
import math
import re
import subprocess
from pathlib import Path


def load_audio(wiki: Path):
    manifest = wiki / "audio-manifest.json"
    if not manifest.exists():
        return []
    data = json.loads(manifest.read_text())
    if data.get("schema") != "instadna.audio/v1":
        raise ValueError("Unsupported audio manifest")
    rows = data["assets"]
    seen = set()
    for row in rows:
        if not re.fullmatch(r"[a-z][a-z0-9-]+", row["id"]) or row["id"] in seen:
            raise ValueError("Invalid or duplicate audio ID")
        seen.add(row["id"])
        if row.get("origin") != "generated" or row.get("publish") is not True:
            raise ValueError("Only selected generated exports may be published")
        name = row["path"]
        if not re.fullmatch(r"audio/[a-z0-9-]+\.(wav|mp3)", name):
            raise ValueError("Audio must be an allowlisted WAV or MP3")
        path = wiki / name
        if path.is_symlink() or not path.resolve().is_relative_to(wiki.resolve()):
            raise ValueError("Audio escapes wiki or is a symlink")
        if path.stat().st_size >= 25 * 1024 * 1024:
            raise ValueError("Audio exceeds Pages asset limit")
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError(f"Audio hash mismatch: {name}")
        duration = row["duration_s"]
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
            raise ValueError("Invalid audio duration")
        probe = json.loads(subprocess.check_output([
            "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)
        ]))
        streams = probe["streams"]
        if len(streams) != 1 or streams[0]["codec_type"] != "audio":
            raise ValueError("Export must contain one audio stream and no video")
        if abs(float(probe["format"]["duration"]) - duration) > .1:
            raise ValueError("Audio duration does not match manifest")
    return rows


def render_audio(rows):
    esc = html.escape
    groups = {"main": [], "comparison": [], "archive": []}
    for row in rows:
        if row.get("download_only"):
            continue
        downloads = [r for r in rows if r.get("download_for") == row["id"]]
        links = f'<a href="{esc(row["path"])}" download>Завантажити {Path(row["path"]).suffix[1:].upper()}</a>'
        links += "".join(f' · <a href="{esc(r["path"])}" download>{esc(r.get("download_label", Path(r["path"]).suffix[1:].upper()))}</a>' for r in downloads)
        groups.get(row.get('group'), groups['main']).append(f'''<section class="audio-card {"audio-master" if row.get("role") == "master" else ""}" id="{esc(row["id"])}">
<span class="eyebrow">{esc(row["label"])} · {row["duration_s"]:.1f} с</span>
<h3>{esc(row["title"])}</h3><p>{esc(row["description"])}</p>
<audio id="player-{esc(row["id"])}" controls preload="metadata" src="{esc(row["path"])}" aria-label="{esc(row["title"])}"></audio>
<p class="audio-downloads">{links}</p></section>''')
    def grid(cards):
        return '<div class="audio-grid">' + "".join(cards) + '</div>'
    result = grid(groups['main'])
    for group, title in [('comparison', 'Порівняти нові дублі та попередній голос'),
                         ('archive', 'Архів попередніх моделей і дослідів')]:
        if groups[group]:
            result += f'<details class="audio-collection"><summary>{title}</summary>{grid(groups[group])}</details>'
    return result


def render_audio_ab(rows):
    """An aligned, loudness-matched comparison using only validated manifest assets."""
    choices = [r for r in rows if r.get('comparison_set') == 'post' and not r.get('download_only')]
    if not choices:
        return ''
    choices.sort(key=lambda r: {'До': 0, 'Обробка': 1, 'М’якше': 2}.get(r['comparison_label'], 3))
    selected = next((r for r in choices if r.get('comparison_default')), choices[0])
    esc = html.escape
    buttons = []
    for row in choices:
        wav = next((r['path'] for r in rows if r.get('download_for') == row['id'] and r['path'].endswith('.wav')), '')
        buttons.append(f'<button type="button" data-audio-src="{esc(row["path"])}" data-audio-wav="{esc(wav)}" data-audio-label="{esc(row["comparison_label"])}" aria-pressed="{str(row is selected).lower()}">{esc(row["comparison_label"])}</button>')
    wav = next((r['path'] for r in rows if r.get('download_for') == selected['id'] and r['path'].endswith('.wav')), '')
    wav_link = f'<a class="ab-wav" href="{esc(wav)}" download>WAV</a>' if wav else '<a class="ab-wav" hidden download>WAV</a>'
    return f'''<section class="audio-ab audio-card" data-audio-ab>
<div class="eyebrow">ТОЙ САМИЙ ДУБЛЬ · ОДНАКОВА ГУЧНІСТЬ</div>
<p>Перемикайте версії під час прослуховування — позиція збережеться.</p>
<div class="ab-buttons" role="group" aria-label="Варіант обробки">{"".join(buttons)}</div>
<p class="ab-status" aria-live="polite">{esc(selected['comparison_label'])}</p>
<audio controls preload="metadata" src="{esc(selected['path'])}" aria-label="Порівняння постобробки голосу"></audio>
<p class="audio-downloads"><a class="ab-mp3" href="{esc(selected['path'])}" download>Завантажити MP3</a> · {wav_link}</p>
</section>'''


def audio_document(title, content, prefix, source_evidence=False):
    evidence_nav = f'<a href="{prefix}phrase-bank.html">Оригінальні фрази · джерела і час</a><a href="{prefix}time-evidence.html">Давність і повторюваність</a>' if source_evidence else ""
    return f'''<!doctype html><html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>{html.escape(title)}</title><link rel="stylesheet" href="{prefix}style.css"><script src="{prefix}audio.js" defer></script></head>
<body class="audio-edition"><aside><a class="brand" href="{prefix}audio-lab.html"><span class="mark">▶</span>Голос автора</a><div class="eyebrow">АУДІОЛАБОРАТОРІЯ · ЖОВТЕНЬ 2026</div><nav>{evidence_nav}<a href="{prefix}audio-lab.html">Слухати та порівняти</a><a href="{prefix}audio-post.html">Обробка: до / після</a><a href="{prefix}voice-dna.html">Голос і мікрофрази</a><a href="{prefix}audio-script.html">Сценарій та наголоси</a><a href="{prefix}format-dna.html">Як працюють референси</a><a href="{prefix}audio-method.html">Моделі й перевірка</a><a href="{prefix}index.html">Уся ДНК автора</a><a href="{prefix}completion.html">Звіт про виконання</a></nav><div class="aside-note">СИНТЕТИЧНИЙ ГОЛОС<br>Авторський сценарій для творчої проби.<br>Це не справжня заява автора.</div></aside><main><header><span class="eyebrow">АВТОР · АУДІО ДЛЯ РІЛСА</span><span class="status">Синтетична творча проба</span></header><article>{content}</article><footer>Згенероване аудіо за новим сценарієм. Подібність голосу та вимови потребує оцінки слухача. Першоджерела й обмеження відкриті в дослідженні.</footer></main></body></html>'''
