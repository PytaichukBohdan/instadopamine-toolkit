"""Ukrainian stress coverage and request-bound evidence, not a linguistic oracle.

Adapted from an earlier stress-handling tool and its pronunciation contract. No other
project's content, voice, music, narrative or provider policy is imported.
"""
from __future__ import annotations

import hashlib
import re

ACUTE = "\u0301"
VOWELS = frozenset("аеєиіїоуюяАЕЄИІЇОУЮЯ")
WORD = re.compile(r"[A-Za-zА-Яа-яЄєІіЇїҐґ́]+(?:[’ʼ'][A-Za-zА-Яа-яЄєІіЇїҐґ́]+)*")


def plain(text: str) -> str:
    """Remove only stress marks; preserve й, ї, punctuation and spelling."""
    return text.replace(ACUTE, "")


def words(text: str):
    """Hyphenated compounds are checked component by component."""
    return list(WORD.finditer(text))


def stress_vowel(word: str) -> int | None:
    index, found = -1, []
    for ch in word:
        if ch in VOWELS:
            index += 1
        elif ch == ACUTE:
            found.append(index)
    return found[0] if len(found) == 1 else None


def check_text(marked: str, original: str | None = None) -> list[str]:
    errors = []
    if original is not None and plain(marked) != original:
        errors.append("Stress annotation changes the original spelling or punctuation")
    if re.search(r"\d", marked):
        errors.append("Spell out numbers in spoken text")
    if any(ch in marked for ch in "\u0306\u0308"):
        errors.append("Keep й and ї precomposed; only the acute is combining")
    for match in words(marked):
        word = match.group()
        if re.search(r"[эыъёЭЫЪЁ]", word):
            errors.append(f"Non-Ukrainian spelling at {match.start()}: {word}")
        if re.search(r"[A-Za-z]", word):
            errors.append(f"Write the intended Ukrainian pronunciation at {match.start()}: {word}")
        syllables = sum(ch in VOWELS for ch in word)
        marks = word.count(ACUTE)
        if marks != (1 if syllables > 1 else 0):
            errors.append(f"Invalid stress count at {match.start()}: {word}")
    for i, ch in enumerate(marked):
        if ch == ACUTE and (i == 0 or marked[i - 1] not in VOWELS):
            errors.append(f"Acute must immediately follow a vowel at {i}")
    return errors


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_ledger(request: bytes, texts: list[str], bases: list[list[str]], reviewer: str) -> dict:
    """Record a review basis for every occurrence, including repetitions."""
    if not reviewer.strip() or len(bases) != len(texts):
        raise ValueError("Reviewer and per-section review bases are required")
    sections = []
    for i, (text, reasons) in enumerate(zip(texts, bases)):
        errors = check_text(text)
        tokens = words(text)
        if errors:
            raise ValueError("; ".join(errors))
        if len(tokens) != len(reasons) or any(not reason.strip() for reason in reasons):
            raise ValueError(f"Every occurrence in section {i} needs a review basis")
        sections.append({"index": i, "text_sha256": sha256(text.encode()), "words": [
            {"text": m.group(), "offset": m.start(), "stress_vowel": stress_vowel(m.group()), "basis": reason}
            for m, reason in zip(tokens, reasons)]})
    return {"schema": "instadna.pronunciation/v1", "request_sha256": sha256(request),
            "reviewed_by": reviewer, "sections": sections,
            "acceptance": "Coverage only. Every word in generated audio still requires listening."}


def validate_ledger(request: bytes, texts: list[str], ledger: dict) -> None:
    if ledger.get("schema") != "instadna.pronunciation/v1":
        raise ValueError("Unsupported pronunciation ledger")
    if ledger.get("request_sha256") != sha256(request):
        raise ValueError("Request changed since pronunciation review")
    sections = ledger.get("sections", [])
    if len(sections) != len(texts):
        raise ValueError("Section coverage changed")
    bases = [[word.get("basis", "") for word in section.get("words", [])] for section in sections]
    expected = make_ledger(request, texts, bases, ledger.get("reviewed_by", ""))
    if expected["sections"] != sections:
        raise ValueError("Text or word occurrence coverage changed")
