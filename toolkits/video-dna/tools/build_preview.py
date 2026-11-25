#!/usr/bin/env python3
"""Render a production file into a static "preview passport" review page.

Usage:
    python3 build_preview.py ../productions/<slug>/production.yaml [out_dir]

The page shows what the owner reviews before any paid video generation:
story and trick, cast and asset sheets, the music map, a shot-by-shot storyboard with
preview frames, the exact prompts and model settings, and the feedback / change log.
Optional production keys add sections when present: `narratives` (alternative stories, one
recommended), `process` (the style's production ladder), `dramaturgy` (beats), `ledger` (a motif's appearances), `previous` (links to earlier versions), bible `who`, assets of kind `moodboard`, `bible` (the character bible), `palette`, shot `act`
headers with a filmstrip, `cutdowns`, and higgsfield_estimate.json (tools/higgsfield.py estimate).

Images referenced in the production (relative to the production dir) are copied into
out_dir/img as compressed JPEGs. Prompts are read from <production dir>/prompts/<id>.txt,
written by assemble_prompts.py. The page is noindex and has no login (owner rule, 2026-10-07).
"""
import html
import json
import os
import re
import shutil
import subprocess
import sys

import yaml

CSS = """
:root{--bg:#f6f4ef;--ink:#1d1b18;--mute:#6b665d;--line:#e2ddd2;--card:#fff;--acc:#b4441f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif}
main{max-width:1100px;margin:0 auto;padding:28px 18px 80px}
h1{font-size:30px;line-height:1.15;margin:0 0 6px}h2{font-size:21px;margin:42px 0 12px;padding-top:10px;border-top:1px solid var(--line)}
h3{font-size:17px;margin:0 0 6px}.mute{color:var(--mute)}.tag{display:inline-block;font-size:12px;padding:2px 8px;border:1px solid var(--line);border-radius:99px;margin:0 4px 4px 0;background:#fff}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(300px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;overflow:hidden}
.card img{width:100%;border-radius:8px;display:block;margin-bottom:10px;background:#eee}
.shot{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:16px;background:#fff;border:1px solid var(--line);border-radius:12px;padding:14px;margin:12px 0}
@media(max-width:760px){.shot{grid-template-columns:1fr}}
.shot img{width:100%;border-radius:8px;background:#eee}.noframe{aspect-ratio:4/3;border-radius:8px;background:repeating-linear-gradient(45deg,#eee,#eee 10px,#f6f6f6 10px,#f6f6f6 20px);display:flex;align-items:center;justify-content:center;color:var(--mute);font-size:14px}
.tc{font:600 13px ui-monospace,Menlo,monospace;color:var(--acc)}
ol.beats{padding-left:18px;margin:6px 0}ol.beats li{margin:2px 0}
details{margin-top:8px}summary{cursor:pointer;color:var(--acc);font-weight:600}
pre{white-space:pre-wrap;font:12.5px/1.5 ui-monospace,Menlo,monospace;background:#faf8f3;border:1px solid var(--line);border-radius:8px;padding:10px;max-height:520px;overflow:auto}
.timeline{position:relative;height:54px;background:#fff;border:1px solid var(--line);border-radius:10px;margin:8px 0 4px}
.seg{position:absolute;top:6px;bottom:6px;border-radius:6px;background:#e9dfcf;border:1px solid #d8c9b0;font-size:11px;padding:2px 5px;overflow:hidden;white-space:nowrap}
.cut{position:absolute;top:0;bottom:0;width:2px;background:var(--acc)}
table{border-collapse:collapse;width:100%;background:#fff;font-size:14px}td,th{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
.fb{border-left:3px solid var(--acc);padding:4px 10px;margin:8px 0;background:#fff}
.strip{display:flex;gap:6px;overflow-x:auto;padding:4px 0 10px}.strip a{flex:0 0 150px;text-decoration:none;color:var(--ink);font-size:12px}
.strip img{width:150px;border-radius:6px;display:block}.act{font:600 13px ui-monospace,Menlo,monospace;letter-spacing:.08em;margin:26px 0 4px;color:var(--mute)}
.nar{border:1px solid var(--line);border-radius:12px;background:#fff;padding:14px;margin:12px 0}.nar.rec{border:2px solid var(--acc)}
.nar img{width:100%;max-width:520px;border-radius:8px;display:block;margin:8px 0}
.sw{display:inline-flex;align-items:center;gap:6px;margin:0 12px 6px 0;font-size:13px}.sw i{width:26px;height:26px;border-radius:6px;border:1px solid var(--line);display:inline-block}
.wide img{width:100%;border-radius:10px;display:block}
.toc{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 0}.toc a{font-size:13px;padding:3px 9px;border:1px solid var(--line);border-radius:99px;background:#fff;color:var(--ink);text-decoration:none}
"""


def esc(x):
    return html.escape(str(x or ""))


def copy_img(src_dir, rel, out_dir):
    if not rel:
        return None
    src = os.path.join(src_dir, rel)
    if not os.path.exists(src):
        return None
    os.makedirs(os.path.join(out_dir, "img"), exist_ok=True)
    name = os.path.splitext(rel.replace("/", "_"))[0] + ".jpg"
    dst = os.path.join(out_dir, "img", name)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", src, "-vf", "scale='min(1600,iw)':-2", "-q:v", "4", dst], check=True)
    return "img/" + name


def music_map(prod, src_dir):
    m = prod.get("music") or {}
    total = float(prod["delivery"].get("length_s") or 30)
    cuts = [float(s["start"]) for s in prod.get("shots", []) if s.get("start") not in (None, 0, 0.0)]
    segs = "".join(
        f'<div class="seg" style="left:{100 * float(s["start"]) / total:.2f}%;width:{100 * (float(s["end"]) - float(s["start"])) / total:.2f}%" '
        f'title="{esc(s.get("label"))}">{esc(s.get("label"))}</div>' for s in m.get("sections", []))
    marks = "".join(f'<div class="cut" style="left:{100 * c / total:.2f}%" title="cut {c:.2f}s"></div>' for c in cuts)
    info = " · ".join(x for x in [m.get("title"), f"{m['bpm']} BPM" if m.get("bpm") else None, m.get("edit_mode")] if x)
    return (f'<p class="mute">{esc(info)}</p><div class="timeline">{segs}{marks}</div>'
            f'<p class="mute" style="font-size:13px">Sections in beige, cuts in red, 0 – {total:g} s. {esc(m.get("notes"))}</p>')


def shot_card(prod, shot, src_dir, out_dir):
    img = copy_img(src_dir, shot.get("frame"), out_dir)
    frame = f'<img src="{img}" alt="preview frame {esc(shot["id"])}">' if img else '<div class="noframe">frame not generated yet</div>'
    beats = "".join(f"<li><span class='tc'>{b[0]}–{b[1]}s</span> {esc(b[2])}</li>" for b in shot.get("beats", []))
    tags = "".join(f'<span class="tag">{esc(b if isinstance(b, str) else next(iter(b)))}</span>' for b in shot.get("blocks", []))
    prompt_path = os.path.join(src_dir, "prompts", shot["id"] + ".txt")
    prompt = open(prompt_path).read() if os.path.exists(prompt_path) else "(run assemble_prompts.py)"
    settings = f'{shot.get("model", "seedance_2_5")} · {prod["delivery"]["aspect"]} · {shot.get("resolution", "1080p")} · {shot.get("duration", "?")} s'
    acting = "".join(f"<div><b>{esc(k)}:</b> {esc(v)}</div>" for k, v in (shot.get("acting") or {}).items())
    qa = f'<div style="font-size:13px;margin-top:6px"><b>Frame QA:</b> {esc(shot["qa"])}</div>' if shot.get("qa") else ""
    return f"""<div class="shot" id="{esc(shot['id'])}"><div>{frame}</div><div>
<div class="tc">{esc(shot['id'])} · {shot.get('start', '?')}–{shot.get('end', '?')} s in the edit</div>
<h3>{esc(shot.get('title'))}</h3><div>{esc(shot.get('summary'))}</div>
<div style="margin:8px 0">{tags}</div>
<div><b>Camera:</b> {esc(shot.get('camera'))}</div>{acting}
<ol class="beats">{beats}</ol>
<div><b>Sound:</b> {esc(shot.get('sound'))}</div><div><b>Into next shot:</b> {esc(shot.get('transition_out'))}</div>
<div class="mute" style="font-size:13px;margin-top:6px">Generate with: {esc(settings)}</div>{qa}
<details><summary>Full prompt ({len(prompt):,} chars)</summary><pre>{esc(prompt)}</pre></details>
</div></div>"""


def narratives(prod, src_dir, out_dir):
    out = []
    for n in prod.get("narratives", []):
        img = copy_img(src_dir, n.get("frame"), out_dir)
        beats = "".join(f"<li>{esc(b)}</li>" for b in n.get("beats", []))
        out.append(f'<div class="nar{" rec" if n.get("recommended") else ""}"><h3>{esc(n.get("title"))}</h3>'
                   f'<div><span class="tag">{esc(n.get("format"))}</span><span class="tag">{esc(n.get("length"))}</span></div>'
                   f'<p>{esc(n.get("logline"))}</p>' + (f'<img src="{img}" alt="key frame, narrative {esc(n.get("id"))}">' if img else "")
                   + f'<ol class="beats">{beats}</ol><div><b>Why:</b> {esc(n.get("why"))}</div><div><b>Risk:</b> {esc(n.get("risk"))}</div></div>')
    return "".join(out)


def moodboards(prod, src_dir, out_dir):
    out = []
    for a in prod.get("assets", []):
        if a.get("kind") != "moodboard":
            continue
        img = copy_img(src_dir, a.get("image"), out_dir)
        out.append(f'<div class="card wide">' + (f'<img src="{img}" alt="{esc(a["title"])}">' if img else '<div class="noframe">not generated yet</div>')
                   + f'<h3>{esc(a["title"])}</h3><div><b>Take:</b> {esc(a.get("take"))}</div><div><b>Don\'t take:</b> {esc(a.get("do_not_take"))}</div>'
                   f'<div class="mute">{esc(a.get("use"))}</div></div>')
    return "".join(out)


def bible(prod, src_dir, out_dir):
    out = []
    assets = {a["id"]: a for a in prod.get("assets", [])}
    for c in prod.get("bible", []):
        pics = "".join(f'<img src="{img}" alt="{esc(sid)}">' for sid in c.get("sheets", [])
                       if (img := copy_img(src_dir, assets.get(sid, {}).get("image"), out_dir)))
        out.append(f'<div class="card">{pics}<h3>{esc(c.get("name"))}</h3>' + (f'<p>{esc(c["who"])}</p>' if c.get("who") else "") + f'<div><b>Trait:</b> {esc(c.get("trait"))}</div>'
                   f'<div><b>Signature prop:</b> {esc(c.get("prop"))}</div><div><b>World:</b> {esc(c.get("world"))}</div>'
                   f'<div class="mute">{esc(c.get("note"))}</div></div>')
    return '<div class="grid">' + "".join(out) + "</div>"


def palette(prod):
    return "".join(f'<div class="card" style="margin:8px 0"><h3>{esc(p.get("act"))}</h3><div>'
                   + "".join(f'<span class="sw"><i style="background:{esc(h)}"></i>{esc(n)} <span class="mute">{esc(h)}</span></span>' for h, n in p.get("swatches", []))
                   + f'</div><div class="mute">{esc(p.get("grade"))}</div></div>' for p in prod.get("palette", []))


def filmstrip(prod, src_dir, out_dir):
    cells = []
    for sh in prod.get("shots", []):
        img = copy_img(src_dir, sh.get("frame"), out_dir)
        if img:
            cells.append(f'<a href="#{esc(sh["id"])}"><img src="{img}" alt="{esc(sh["id"])}"><span class="tc">{esc(sh["id"])}</span> {sh.get("start")}–{sh.get("end")}s</a>')
    return f'<div class="strip">{"".join(cells)}</div>' if cells else ""


def cutdowns(prod):
    out = []
    for c in prod.get("cutdowns", []):
        rows = "".join(f"<tr><td>{esc(s)}</td><td>{a}–{b} s</td><td>{(float(b) - float(a)):.1f} s</td></tr>" for s, a, b in c.get("shots", []))
        out.append(f'<h3>{esc(c.get("title"))}</h3><table><tr><th>Shot</th><th>In the cut</th><th>Length</th></tr>{rows}</table>'
                   f'<p class="mute">{esc(c.get("notes"))}</p>')
    return "".join(out)


def higgsfield_estimate(src_dir):
    path = os.path.join(src_dir, "higgsfield_estimate.json")
    if not os.path.exists(path):
        return ""
    e = json.load(open(path))
    res = list(e.get("totals_usd", {}))
    head = "".join(f"<th>{esc(r)} (USD)</th>" for r in res)
    rows = "".join(f"<tr><td>{esc(r['id'])}</td><td>{r['duration']} s</td>"
                   + "".join(f"<td>{(r.get(x) or {}).get('usd')}</td>" for x in res) + "</tr>" for r in e.get("per_shot", []))
    total = "".join(f"<td><b>{v}</b></td>" for v in e["totals_usd"].values())
    return (f'<h3>Higgsfield cost estimate (nothing generated)</h3><p class="mute">{esc(e.get("endpoint"))} · from Higgsfield\'s /estimate on '
            f'{esc(e.get("estimated_at"))}. {esc(e.get("note"))}</p><table><tr><th>Shot</th><th>Clip</th>{head}</tr>{rows}'
            f'<tr><td><b>Total, one take each</b></td><td></td>{total}</tr></table>'
            f'<details><summary>Higgsfield pricing text</summary><pre>{esc(e.get("pricing_description"))}</pre></details>')


def dramaturgy(prod):
    rows = "".join(f"<tr><td class='tc'>{esc(b.get('t'))}</td><td><b>{esc(b.get('beat'))}</b></td><td>{esc(b.get('text'))}</td></tr>"
                   for b in prod.get("dramaturgy", []))
    return f"<table><tr><th>When</th><th>Beat</th><th>What the viewer feels and learns</th></tr>{rows}</table>"


def ledger(prod):
    led = prod.get("ledger") or {}
    rows = "".join(f"<tr><td class='tc'>{esc(r.get('shot'))}</td><td>{esc(r.get('where'))}</td><td>{esc(r.get('state'))}</td>"
                   f"<td>{esc(r.get('who'))}</td><td>{esc(r.get('meaning'))}</td></tr>" for r in led.get("rows", []))
    return (f"<p>{esc(led.get('intro'))}</p><table><tr><th>Shot</th><th>Where</th><th>What it looks like</th>"
            f"<th>Who sees it</th><th>What it means (revealed at the end)</th></tr>{rows}</table>")


def process(prod):
    rows = "".join(f"<tr><td>{i + 1}</td><td><b>{esc(st.get('step'))}</b><br><span class='mute'>{esc(st.get('creator') or st.get('style'))}</span></td>"
                   f"<td>{esc(st.get('here'))}</td><td>{esc(st.get('status'))}</td></tr>" for i, st in enumerate(prod.get("process", [])))
    return f"<table><tr><th>#</th><th>Style step</th><th>In this film</th><th>Status</th></tr>{rows}</table>"


def asset_card(prod, a, src_dir, out_dir):
    img = copy_img(src_dir, a.get("image"), out_dir)
    pic = f'<img src="{img}" alt="{esc(a["id"])}">' if img else '<div class="noframe">not generated yet</div>'
    prompt_path = os.path.join(src_dir, "prompts", a["id"] + ".txt")
    prompt = open(prompt_path).read() if os.path.exists(prompt_path) else ""
    return (f'<div class="card">{pic}<h3>{esc(a.get("title", a["id"]))}</h3><div class="mute">{esc(a.get("kind"))} · '
            f'{esc(a.get("model", "seedream_v5_pro"))}</div><div>{esc(a.get("use"))}</div>'
            + (f'<details><summary>Prompt</summary><pre>{esc(prompt)}</pre></details>' if prompt else "") + "</div>")


def main():
    path = sys.argv[1]
    src_dir = os.path.dirname(os.path.abspath(path))
    out_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(src_dir, "site")
    prod = yaml.safe_load(open(path))
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)
    d = prod["delivery"]
    head = (f'<p class="mute">Preview passport v{prod.get("version", 1)} · {esc(prod.get("date"))} · in the DNA of '
            f'{esc(prod.get("dna", prod.get("style", "")))}</p><h1>{esc(prod["title"])}</h1>'
            f'<p style="font-size:18px">{esc(prod.get("logline"))}</p>'
            f'<p><span class="tag">format: {esc(prod.get("format"))}</span><span class="tag">{esc(d["aspect"])} · {d.get("fps", 24)} fps · ~{d.get("length_s")} s</span>'
            f'<span class="tag">{esc(d.get("platform"))}</span><span class="tag">edit: {esc((prod.get("music") or {}).get("edit_mode"))}</span></p>'
            f'<p><b>The one trick:</b> {esc(prod.get("trick"))}</p>'
            + "".join(f'<p class="mute">Earlier version: <a href="{esc(v.get("link"))}">v{esc(v.get("version"))} — {esc(v.get("title"))}</a></p>' for v in prod.get("previous", []))
            + '<!--TOC-->')
    inp = prod.get("input", {})
    inputs = (f'<h2>1 · Input</h2><div class="card"><div><b>Idea (owner\'s words):</b> {esc(inp.get("idea"))}</div>'
              + (f'<div><b>In English:</b> {esc(inp.get("idea_en"))}</div>' if inp.get("idea_en") else "")
              + "".join(f'<div><b>Reference:</b> {esc(r.get("what"))} — take: {esc(r.get("take"))}; not: {esc(r.get("do_not_take"))}</div>' for r in inp.get("references", []))
              + f'<div><b>Music:</b> {esc((prod.get("music") or {}).get("title"))}</div></div>')
    story = "<h2>2 · Story</h2>" + "".join(f"<p>{esc(p)}</p>" for p in prod.get("story", []))
    cast = '<h2>3 · Cast, locations and props</h2><div class="grid">' + "".join(
        asset_card(prod, a, src_dir, out_dir) for a in prod.get("assets", []) if a.get("kind") not in ("moodboard", "narrative-frame")) + "</div>"
    music = "<h2>4 · Music map</h2>" + music_map(prod, src_dir)
    shots, act = [], None
    for sh in prod.get("shots", []):
        if sh.get("act") and sh["act"] != act:
            act = sh["act"]
            shots.append(f'<div class="act">{esc(act)}</div>')
        shots.append(shot_card(prod, sh, src_dir, out_dir))
    board = "<h2>5 · Storyboard</h2>" + filmstrip(prod, src_dir, out_dir) + "".join(shots)
    if prod.get("ledger"):
        story = story + f"<h2>{esc((prod['ledger']).get('title', 'Motif ledger'))}</h2>" + ledger(prod)
    if prod.get("dramaturgy"):
        story = "<h2>Dramaturgy: the beats</h2>" + dramaturgy(prod) + story
    if prod.get("process"):
        story += "<h2>How the style's creator would make it</h2>" + process(prod)
    if prod.get("narratives"):
        story = ('<h2>Narratives: three ways to tell it</h2><p class="mute">The recommended one is outlined and boarded '
                 'in full below; B and C have one key frame each.</p>' + narratives(prod, src_dir, out_dir) + story)
    mood = moodboards(prod, src_dir, out_dir)
    if mood:
        story += "<h2>Moodboards</h2>" + mood
    if prod.get("bible"):
        cast = "<h2>Character bible</h2>" + bible(prod, src_dir, out_dir) + cast
    if prod.get("palette"):
        music = "<h2>Palette and grade per act</h2>" + palette(prod) + music
    if prod.get("cutdowns"):
        board += "<h2>Cut-downs</h2>" + cutdowns(prod)
    gen = prod.get("generation", {})
    plan = ("<h2>6 · Generation plan</h2><table><tr><th>Step</th><th>What</th><th>Model</th><th>Notes</th></tr>"
            + "".join(f"<tr><td>{i + 1}</td><td>{esc(s.get('what'))}</td><td>{esc(s.get('model'))}</td><td>{esc(s.get('notes'))}</td></tr>" for i, s in enumerate(gen.get("steps", [])))
            + "</table>" + (f'<p class="mute">{esc(gen.get("budget"))}</p>' if gen.get("budget") else "") + higgsfield_estimate(src_dir))
    fb = "<h2>7 · Feedback and changes</h2>" + ("".join(
        f'<div class="fb"><b>v{esc(f.get("version"))} · {esc(f.get("date"))}</b> — {esc(f.get("owner"))}<br><span class="mute">→ {esc(f.get("change"))}</span></div>'
        for f in prod.get("feedback", [])) or '<p class="mute">No feedback yet. Reply in chat with shot ids (for example "s03: …") and the next version will be listed here.</p>')
    page = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="robots" content="noindex,nofollow"><title>{esc(prod["title"])} · preview passport</title><style>{CSS}</style></head>'
            f'<body><main>{head}{inputs}{story}{cast}{music}{board}{plan}{fb}</main></body></html>')
    counter, toc = iter(range(1, 100)), []

    def number(m):   # number sections in page order and give each an anchor for the index
        n = next(counter)
        toc.append(f'<a href="#sec{n}">{n} · {esc(html.unescape(m.group(1)))}</a>')
        return f'<h2 id="sec{n}">{n} · {m.group(1)}</h2>'
    page = re.sub(r"<h2>(?:\d+ · )?(.*?)</h2>", number, page)
    nav = '<nav class="toc">' + " ".join(toc) + (f' <a href="{esc(prod["report_link"])}">report</a>' if prod.get("report_link") else "") + "</nav>"
    page = page.replace("<!--TOC-->", nav, 1)
    open(os.path.join(out_dir, "index.html"), "w").write(page)
    open(os.path.join(out_dir, "robots.txt"), "w").write("User-agent: *\nDisallow: /\n")
    open(os.path.join(out_dir, "_headers"), "w").write("/*\n  X-Robots-Tag: noindex, nofollow\n")
    print(json.dumps({"out": out_dir, "shots": len(prod.get("shots", [])), "assets": len(prod.get("assets", []))}))


if __name__ == "__main__":
    main()
