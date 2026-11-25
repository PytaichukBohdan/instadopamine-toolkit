#!/usr/bin/env python3
"""Assemble generation prompts from a production file, in the production's chosen creator style.

Usage:
    python3 assemble_prompts.py ../productions/<slug>/production.yaml

Writes <production dir>/prompts/<asset-or-shot id>.txt and prints a summary.

The video prompt follows a tested 21-step block order:
 1 scene context · 2 format · 3 people-law · 4 most important rules + FAIL · 5 active references
 + contamination · 6 body / scale · 7 face · 8 spatial layout · 9 action timing · 10 acting ·
 11 camera · 12 optics · 13 world · 14 physics + anatomy · 15 lighting · 16 integration ·
 17 materials · 18 grade + lock · 19 no-freezing + count + wardrobe · 20 sound ·
 21 stop-inversion + stop-base

`style:` in production.yaml picks the creator DNA (see ../STYLES.md). It is required: if no style
was named, ask which one to use instead of guessing.
Block texts live in ../<style>/blocks/<CODE>.md and cast identity blocks in ../cast/<name>.md
(sections "## FACE", "## BODY", "## MARKS"); an invented character for one film can live in
<production>/cast/<name>.md instead, which wins; likewise <production>/blocks/<CODE>.md adds or
overrides blocks for one film. A shot's wardrobe line is `wardrobe:`, else
`looks[<look>]`, else the production's `wardrobe`. A block can be listed as a plain code or as
{CODE: {PLACEHOLDER: value}} to fill its [PLACEHOLDER] slots.
"""
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOCK_DIR = None   # set from production.yaml `style:` in main()
CAST_DIR = os.path.join(ROOT, "cast")
PROD_CAST_DIR = None   # <production>/cast, set in main()


def cast_path(name, ext):
    """A production-local cast file (an invented character for one film) wins over ../cast/."""
    for folder in (PROD_CAST_DIR, CAST_DIR):
        if folder and os.path.exists(os.path.join(folder, name + ext)):
            return os.path.join(folder, name + ext)
    return None

# Which section of the 21-step order each block belongs to (the tested order).
SECTION_OF = {
    # 2 format / take type
    "MULTI-SHOT": 2, "START-END": 2,
    # 3 people-law
    "PEOPLE-LAW": 3,
    # 4 most important rules + FAIL
    "FAIL": 4, "CARRIED-FEATURE": 4, "HIDDEN-CHANGE": 4, "MATCH-CUT": 4,
    # 5 active references + contamination
    "REF-ROLES": 5, "CONTAMINATION": 5, "CAMERA-REFS": 5, "EMPTY-PLATE-FILL": 5,
    # 6 body / scale, 7 face
    "SCALE": 6, "ANCHORS": 7,
    # 8 spatial layout / first frame
    "FIRST-FRAME": 8, "GEOGRAPHY-LOCK": 8, "ORDINARY-IMPOSSIBLE": 8,
    # 10 acting
    "ACTING": 10, "RESTRAINED": 10, "GAZE": 10, "UNBOTHERED": 10, "UNSEEN-CAUSE": 10, "TASK": 10,
    # 13 world
    "WIND": 13, "WATER": 13, "RAIN": 13, "LIVING-BACKGROUND": 13,
    # 14 physics + anatomy
    "ANATOMY": 14, "CAUSE-EFFECT": 14, "DELAYED-CAUSALITY": 14, "PHYSICS-WEIGHT": 14,
    # 15 lighting, 16 integration, 17 materials / text / props
    "LIGHT-MOTIVATED": 15, "RELIGHT": 15, "INTEGRATION": 16, "TEXT-ON": 17, "PROP-CUSTODY": 17,
    # 18 grade
    "HOUSE-LOOK": 18, "ONE-SATURATED-NOTE": 18,
    # 19 no-freezing + count
    "NO-FREEZING": 19, "NON-STOP": 19, "COUNT": 19, "BLACK-ENDING": 19,
    # 20 sound
    "SOUND": 20, "SOUND-SWITCH": 20, "SOUND-DRAMATURGY": 20, "DIALOGUE": 20, "NO-READ-ALOUD": 20, "LAUGH-TRACK": 20,
    # 21 negatives
    "STOP-BASE": 21, "STOP-INVERSION": 21,
}
PREFIX_SECTION = {"CAM": 11, "OPT": 12, "GRADE": 18, "MC": 5}


def load_block(code, fill=None, pronouns="she"):
    # a production may define its own blocks (e.g. a recurring magical element) in <production>/blocks/
    local = os.path.join(os.path.dirname(PROD_CAST_DIR), "blocks", code + ".md") if PROD_CAST_DIR else None
    path = local if local and os.path.exists(local) else os.path.join(BLOCK_DIR, code + ".md")
    if not os.path.exists(path):
        sys.exit(f"unknown block {code}: no {path}")
    text = open(path).read()
    text = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S).strip()
    text = re.sub(r"^\*\(.*?\)\*\s*$", "", text, flags=re.M).strip()   # her italic notes to the writer
    # re-gender HER template first, then fill: our fill values name people explicitly and must stay as written
    text = adapt_pronouns(text, pronouns)
    for key, value in (fill or {}).items():
        # placeholders are "[KEY]" or "[KEY — hint for the writer]"; keys match case-insensitively.
        # A list fills repeated slots of the same name in order ("X[..]/Y[..]" → [50, 58]).
        pattern = rf"\[{re.escape(key)}(?: — [^\]]*)?\]"
        for v in (value if isinstance(value, list) else [value]):
            text = re.sub(pattern, lambda _m, v=v: str(v), text, count=1 if isinstance(value, list) else 0, flags=re.I)
    return text


LITERAL_BRACKETS = {"[LAUGH TRACK]", "[APPLAUSE]"}   # cue syntax that belongs in the prompt


def unfilled(text):
    """Any [bracketed slot] left in a finished prompt is a bug: the model invents its content."""
    return sorted({m for m in re.findall(r"\[[^\[\]\n]{1,160}\]", text) if m not in LITERAL_BRACKETS})


PRONOUNS_HE = [
    (r"\bherself\b", "himself"), (r"\bHerself\b", "Himself"), (r"\bHERSELF\b", "HIMSELF"),
    (r"\bhers\b", "his"),
    # "her" before a preposition, conjunction or punctuation is an object → him; otherwise possessive → his
    (r"\bher(?=\s+(?:to|in|on|up|from|with|at|into|onto|over|around|back|down|out|off|through|and|as|than|or|forward|again|away)\b|\s*[.,;:!?)\]—-]|\s*$)", "him"),
    (r"\bHer(?=\s*[.,;:!?)\]—-])", "Him"), (r"\bHER(?=\s*[.,;:!?)\]—-]|\s+(?:TO|IN|ON|FROM|WITH|AND)\b)", "HIM"),
    (r"\bher\b", "his"), (r"\bHer\b", "His"), (r"\bHER\b", "HIS"),
    (r"\bshe\b", "he"), (r"\bShe\b", "He"), (r"\bSHE\b", "HE"),
    (r"\bwoman\b", "man"), (r"\bWOMAN\b", "MAN"), (r"\bgirl\b", "man"),
]


def adapt_pronouns(text, pronouns):
    """A style's verbatim blocks may be written for one character (she/her). Re-gender them for the cast."""
    if pronouns != "he":
        return text
    for pat, rep in PRONOUNS_HE:
        text = re.sub(pat, rep, text, flags=re.M)
    return text


def section_for(code):
    if code in SECTION_OF:
        return SECTION_OF[code]
    return PREFIX_SECTION.get(code.split("-")[0], 17)


def cast_pronouns(cast):
    import json
    for c in cast or []:
        cfg = cast_path(c, ".refs.json")
        if cfg:
            return json.load(open(cfg)).get("_pronouns", "she")
    return "she"


def cast_section(name, section):
    path = cast_path(name, ".md")
    if not path:
        return ""
    text = open(path).read()
    m = re.search(rf"^## {section}\b.*?\n(.*?)(?=^## |\Z)", text, flags=re.S | re.M)
    if not m:
        return ""
    body = re.sub(r"<!--.*?-->", "", m.group(1), flags=re.S)   # notes for us, not for the generator
    return body.replace("**", "").strip()


def fmt_time(t):
    return f"{float(t):.2f}".rstrip("0").rstrip(".")


def references_text(refs):
    lines = []
    for r in refs:
        take = r.get("take", "")
        skip = r.get("do_not_take", "")
        lines.append(f"{r['tag']} = {r['what']}." + (f" TAKE: {take}." if take else "")
                     + (f" DO NOT TAKE: {skip}." if skip else " Take nothing else from it."))
    return "\n".join(lines)


def motion_control_prompt(prod, shot):
    """hf-mult-motion-control: the source video carries camera, timing and look, so the prompt
    spends its words on what may change and what must not (her Genjutsu doctrine)."""
    parts = [shot.get("context", "")]
    if shot.get("references"):
        parts.append("INPUTS:\n" + references_text(shot["references"]))
    for b in shot.get("blocks", []):
        code, fill = (next(iter(b.items())) if isinstance(b, dict) else (b, None))
        parts.append(load_block(code, fill, cast_pronouns(shot.get("cast", prod.get("cast", [])))))
    if shot.get("source_timeline"):
        parts.append("EXACT SOURCE TIMELINE — seconds from the start of the input; descriptions identify EXISTING footage:\n"
                     + "\n".join(f"{fmt_time(t[0])}–{fmt_time(t[1])} — {t[2]}" for t in shot["source_timeline"]))
    if shot.get("inversions"):
        parts.append("DO NOT: " + "; ".join(shot["inversions"]) + ".")
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def video_prompt(prod, shot):
    if str(shot.get("model", "")).startswith("hf-mult-motion-control"):
        return motion_control_prompt(prod, shot)
    cast = shot.get("cast", prod.get("cast", []))
    blocks = shot.get("blocks", []) + prod.get("global_blocks", [])
    by_section = {}
    for b in blocks:
        code, fill = (next(iter(b.items())) if isinstance(b, dict) else (b, None))
        by_section.setdefault(section_for(code), []).append(load_block(code, fill, cast_pronouns(cast)))

    s = {}
    s[1] = shot.get("context") or prod.get("trick", "")
    dur = shot.get("duration")
    fmt = [f"FORMAT: {dur} s" if dur else "FORMAT:",
           f"{prod['delivery']['aspect']}", f"{prod['delivery'].get('fps', 24)} fps"]
    if shot.get("cuts"):
        fmt.append(f"{len(shot['cuts']) + 1} shots, cuts at " + ", ".join(fmt_time(c) for c in shot["cuts"]) + " s")
    else:
        fmt.append("one continuous shot, no cuts")
    fmt.append(shot.get("music", prod.get("music_line", "no music")))
    s[2] = ", ".join(fmt) + "."
    if shot.get("main"):
        s[4] = "THE MOST IMPORTANT RULES IN THIS SHOT:\n" + "\n".join(f"- {m}" for m in shot["main"])
    if shot.get("fail"):
        s[4] = s.get(4, "") + "\n" + "\n".join(f"FAIL CONDITION: IF {f.upper()} — THE SHOT IS WRONG." for f in shot["fail"])
    if shot.get("references"):
        s[5] = "ACTIVE REFERENCES:\n" + references_text(shot["references"])
    if cast:
        s[6] = "\n\n".join(cast_section(c, "BODY") for c in cast if cast_section(c, "BODY"))
        s[7] = "\n\n".join(cast_section(c, "FACE") + ("\n\n" + cast_section(c, "MARKS") if shot.get("marks") else "") for c in cast)
    if shot.get("layout"):
        s[8] = "SPATIAL LAYOUT (near to far): " + shot["layout"]
    if shot.get("beats"):
        s[9] = "ACTION TIMING — preserve exactly:\n" + "\n".join(
            f"{fmt_time(b[0])}–{fmt_time(b[1])} s: {b[2]}" for b in shot["beats"])
    if shot.get("acting"):
        a = shot["acting"]
        s[10] = ("ACTING TASK — the whole performance is in the eyes; the task produces the emotion:\n"
                 + "\n".join(f"{k.replace('_', ' ').upper()}: {v}" for k, v in a.items()))
    if shot.get("camera"):
        s[11] = "CAMERA: " + shot["camera"]
    if shot.get("lens"):
        s[12] = "LENS: " + shot["lens"]
    if shot.get("lighting"):
        s[15] = "LIGHTING: " + shot["lighting"]
    if shot.get("materials"):
        s[17] = "MATERIALS: " + shot["materials"]
    wardrobe = shot.get("wardrobe") or (prod.get("looks") or {}).get(shot.get("look")) or prod.get("wardrobe")
    if wardrobe and cast:
        s[19] = "WARDROBE — identical in every frame: " + wardrobe
    if shot.get("count"):
        s[19] = s.get(19, "") + "\nCONTINUITY / COUNT LOCK: " + shot["count"] + " These counts hold in every frame. If more are visible, the shot is wrong."
    if shot.get("sound"):
        s[20] = "AUDIO: " + shot["sound"]
    if shot.get("inversions"):
        s[21] = "BANS SPECIFIC TO THIS SHOT: " + "; ".join(shot["inversions"]) + "."

    for sec, texts in by_section.items():
        s[sec] = (s.get(sec, "") + "\n\n" + "\n\n".join(texts)).strip()
    return "\n\n".join(s[k].strip() for k in sorted(s) if s.get(k, "").strip())


def image_prompt(prod, asset):
    """Image prompts follow her still style: identity tag first, then one dense descriptive
    paragraph ending with lens, aspect and 'no text, no logos'."""
    parts = []
    if asset.get("identity_tag"):
        parts.append(f"{asset['identity_tag']} is the single identity source: same face, hair, skin, "
                     "eye colour, age and proportions in every panel. Do not alter facial features.")
    for c in asset.get("cast", []):
        parts.append(cast_section(c, "FACE"))
    for b in asset.get("blocks", []):
        code, fill = (next(iter(b.items())) if isinstance(b, dict) else (b, None))
        parts.append(load_block(code, fill, cast_pronouns(asset.get("cast", prod.get("cast", [])))))
    parts.append(asset.get("description", "").strip())
    tail = [asset.get("lens"), prod["delivery"]["aspect"] if asset.get("aspect_from_delivery", True) else asset.get("aspect"),
            "no text, no logos"]
    parts.append(", ".join(t for t in tail if t))
    return "\n\n".join(p for p in parts if p)


def main():
    global BLOCK_DIR, PROD_CAST_DIR
    path = sys.argv[1]
    PROD_CAST_DIR = os.path.join(os.path.dirname(os.path.abspath(path)), "cast")
    prod = yaml.safe_load(open(path))
    style = prod.get("style")
    if not style:
        sys.exit("production.yaml has no `style:`. Ask which creator style to use "
                 "(one of video-dna/STYLES.md), then set it.")
    BLOCK_DIR = os.path.join(ROOT, style, "blocks")
    if not os.path.isdir(BLOCK_DIR):
        sys.exit(f"unknown style {style!r}: no {BLOCK_DIR} (registered styles: see video-dna/STYLES.md)")
    out_dir = os.path.join(os.path.dirname(os.path.abspath(path)), "prompts")
    os.makedirs(out_dir, exist_ok=True)
    for asset in prod.get("assets", []):
        text = image_prompt(prod, asset)
        open(os.path.join(out_dir, asset["id"] + ".txt"), "w").write(text + "\n")
        print(f"{asset['id']:<18} image  {asset.get('model', 'seedream_v5_pro'):<18} {len(text):>6} chars")
        for ph in unfilled(text):
            print(f"  WARNING {asset['id']}: unfilled placeholder {ph}")
    for shot in prod.get("shots", []):
        text = video_prompt(prod, shot)
        open(os.path.join(out_dir, shot["id"] + ".txt"), "w").write(text + "\n")
        print(f"{shot['id']:<18} video  {shot.get('model', 'seedance_2_5'):<18} {len(text):>6} chars")
        for ph in unfilled(text):
            print(f"  WARNING {shot['id']}: unfilled placeholder {ph}")


if __name__ == "__main__":
    main()
