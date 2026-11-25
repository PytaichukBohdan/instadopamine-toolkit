#!/usr/bin/env python3
"""Scrape every public blog post of a Higgsfield creator into Markdown + JSON.

Usage:
    cd video-dna/tools && npm install          # once, for the Yjs decoder
    python3 scrape_higgsfield_blog.py <username> /private/<style> [--media]

Output in <out>:
    posts_index.json      post list (title, slug, dates, views, likes, cover, content_url)
    bins/<slug>.bin       raw post content (Yjs update of a Lexical editor document)
    md/<slug>.md          readable post: headings, notes, media and every prompt block
                          with its model / aspect / resolution / duration
    prompts.json          every prompt block as a row
    media.json            every embedded image / video / audio / file
    comments/<slug>.json  public comments
    media/                videos, audio, files and covers (only with --media)

The public endpoints were found on 2026-10-10 by watching the site's own requests:
    GET fnf-api-gw.higgsfield.ai/fnf/blog/<user>/posts?size=50[&cursor=]
    GET <content_url>  (cdn.higgsfield.ai/blog/<id>.bin)
    GET fnf-api-gw.higgsfield.ai/fnf-community/entities/blog_post/<id>/comments?limit=50
No login is needed. They are undocumented and may change.
"""
import concurrent.futures as cf
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

API = "https://fnf-api-gw.higgsfield.ai"
HEADERS = {"User-Agent": "Mozilla/5.0", "Origin": "https://higgsfield.ai", "Referer": "https://higgsfield.ai/"}
HERE = os.path.dirname(os.path.abspath(__file__))


def get(url, raw=False):
    data = urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60).read()
    return data if raw else json.loads(data)


def fetch_index(user):
    items, cursor = [], None
    while True:
        page = get(f"{API}/fnf/blog/{user}/posts?size=50" + (f"&cursor={cursor}" if cursor else ""))
        items += page["items"]
        cursor = page.get("next_cursor")
        if not cursor or not page["items"]:
            return items


def decode(bin_path):
    out = subprocess.run(["node", os.path.join(HERE, "decode.mjs"), bin_path], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)["tree"]


def text_of(n):
    if "text" in n:
        return n["text"]
    if (n.get("attrs") or {}).get("__type") == "linebreak":
        return "\n"
    return "".join(text_of(k) for k in n.get("kids", []) if isinstance(k, dict) and k.get("kind") != "map")


def gen_params(href):
    return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(href or "").query))


class Renderer:
    """Walks the Lexical tree in document order and emits Markdown, prompt rows and media rows."""

    def __init__(self, slug):
        self.slug, self.ctx, self.prompts, self.media = slug, {}, [], []

    def section(self):
        return " / ".join(self.ctx[k] for k in sorted(self.ctx) if self.ctx.get(k))

    def render(self, n, out, depth=0):
        a = n.get("attrs") or {}
        t = a.get("__type")
        if n.get("kind") == "map" or "text" in n:
            return
        if t is None:
            for k in n.get("kids", []):
                self.render(k, out, depth)
        elif t == "heading":
            txt, lvl = text_of(n).strip(), int(a.get("__tag", "h2")[1])
            self.ctx["h%d" % lvl] = txt
            for d in range(lvl + 1, 7):
                self.ctx.pop("h%d" % d, None)
            out.append("\n" + "#" * (lvl + 1) + " " + txt + "\n")
        elif t in ("paragraph", "quote", "blog-quote"):
            txt = text_of(n).strip()
            if txt:
                out.append(("> " if "quote" in t else "") + txt + "\n")
        elif t == "callout":
            inner = []
            for k in n.get("kids", []):
                self.render(k, inner, depth + 1)
            out.append("\n> " + a.get("__emoji", "") + " **Note:** " + "".join(inner).strip().replace("\n", "\n> ") + "\n")
        elif t == "list":
            for i, li in enumerate(n.get("kids", [])):
                if not isinstance(li, dict) or li.get("kind") == "map":
                    continue
                kids = [k for k in li.get("kids", []) if isinstance(k, dict) and k.get("kind") != "map"]
                nested = [k for k in kids if (k.get("attrs") or {}).get("__type") == "list"]
                txt = "".join(text_of(k) for k in kids if k not in nested).strip()
                bullet = {"check": "- [ ] ", "number": "%d. " % (i + 1)}.get(a.get("__listType"), "- ")
                if txt:
                    out.append("  " * depth + bullet + txt + "\n")
                for nl in nested:
                    self.render(nl, out, depth + 1)
        elif t == "listitem":
            out.append("- " + text_of(n).strip() + "\n")
        elif t == "horizontalrule":
            out.append("\n---\n")
        elif t == "blog-prompt":
            p = gen_params(a.get("__href"))
            kind = "video" if "videoModel" in p else ("image" if "imageModel" in p else "?")
            row = dict(slug=self.slug, order=len(self.prompts) + 1, kind=kind,
                       model=p.get("videoModel") or p.get("imageModel") or "?",
                       aspect=p.get("aspectRatio"), resolution=p.get("resolution"), duration=p.get("duration"),
                       section=self.section(), prompt=a.get("__prompt") or "",
                       references=json.loads(a["__referencesJson"]) if a.get("__referencesJson") else [],
                       href=a.get("__href"))
            self.prompts.append(row)
            meta = f"{kind} · {row['model']} · {row['aspect'] or '?'} · {row['resolution'] or '?'}" + (f" · {row['duration']}s" if row["duration"] else "")
            out.append(f"\n**PROMPT #{row['order']}** — `{meta}`\n\n```text\n{row['prompt'].strip()}\n```\n")
        elif t == "asset-embed":
            m = dict(slug=self.slug, section=self.section(), kind=a.get("__fileKind") or a.get("__mediaKind"),
                     url=a.get("__url"), filename=a.get("__filename"), prompt=a.get("__prompt"), description=a.get("__description"))
            self.media.append(m)
            out.append(f"\n[{m['kind']}] {m['url']}" + (f"  (file: {m['filename']})" if m["filename"] else "")
                       + (f"\n  prompt: {m['prompt']}" if m["prompt"] else "") + "\n")
        elif t == "asset-carousel":
            items = json.loads(a.get("__itemsJson") or "[]")
            out.append(f"\n**Carousel** {a.get('__label') or ''} ({len(items)} items)\n")
            for it in items:
                m = dict(slug=self.slug, section=self.section(), kind=it.get("mediaKind"), url=it.get("url"),
                         filename=it.get("filename"), prompt=it.get("prompt"), description=it.get("caption"), carousel=True)
                self.media.append(m)
                out.append(f"- [{m['kind']}] {m['url']}" + (f"  caption: {m['description']}" if m["description"] else "")
                           + (f"\n  prompt: {m['prompt']}" if m["prompt"] else "") + "\n")
        elif t == "blog-cta":
            out.append(f"\n[CTA] {a.get('__text')} — {a.get('__label')} {a.get('__href')}\n")
        else:
            out.append(f"\n[{t}] {text_of(n)}\n")


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    user, out_dir, with_media = sys.argv[1], sys.argv[2], "--media" in sys.argv
    for d in ("bins", "md", "comments"):
        os.makedirs(os.path.join(out_dir, d), exist_ok=True)

    index = fetch_index(user)
    json.dump(index, open(os.path.join(out_dir, "posts_index.json"), "w"), indent=1, ensure_ascii=False)
    print(f"{len(index)} posts")

    all_prompts, all_media = [], []
    for it in index:
        slug = it["slug"]
        bin_path = os.path.join(out_dir, "bins", slug + ".bin")
        open(bin_path, "wb").write(get(it["content_url"], raw=True))
        r = Renderer(slug)
        body = []
        r.render(decode(bin_path), body)
        head = (f"# {it['title']}\n\nSource: https://higgsfield.ai/@{user}/blogs/{slug}  \n"
                f"Published: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(it['published_at']))} · views {it['views_count']} · "
                f"likes {it['likes_count']} · reading {it['reading_time_minutes']} min  \n"
                f"Cover: {it['cover']['url'] if it.get('cover') else '-'}\n")
        open(os.path.join(out_dir, "md", slug + ".md"), "w").write(head + "\n" + "".join(body))
        all_prompts += r.prompts
        all_media += r.media
        try:
            comments = get(f"{API}/fnf-community/entities/blog_post/{it['id']}/comments?limit=50").get("items", [])
        except Exception as e:  # comments are optional evidence
            comments = [{"error": str(e)}]
        json.dump(comments, open(os.path.join(out_dir, "comments", slug + ".json"), "w"), indent=1, ensure_ascii=False)

    json.dump(all_prompts, open(os.path.join(out_dir, "prompts.json"), "w"), indent=1, ensure_ascii=False)
    json.dump(all_media, open(os.path.join(out_dir, "media.json"), "w"), indent=1, ensure_ascii=False)
    print(f"{len(all_prompts)} prompts, {len(all_media)} media items")

    if with_media:
        jobs = [(m["url"], os.path.join(out_dir, "media", m["kind"] or "other", f"{m['slug']}__{os.path.basename(m['url'])}"))
                for m in all_media if m.get("url") and m["kind"] in ("video", "audio", "file")]
        jobs += [(it["cover"]["url"], os.path.join(out_dir, "media", "covers", it["slug"] + os.path.splitext(it["cover"]["url"])[1]))
                 for it in index if it.get("cover")]

        def dl(job):
            url, path = job
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if not os.path.exists(path):
                open(path, "wb").write(get(url, raw=True))

        with cf.ThreadPoolExecutor(8) as ex:
            list(ex.map(dl, jobs))
        print(f"{len(jobs)} media files")


if __name__ == "__main__":
    main()
