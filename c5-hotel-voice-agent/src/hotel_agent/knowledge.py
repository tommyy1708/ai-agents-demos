"""Retrieval over the hotel's knowledge file: the agent answers policy questions from these sections, not from
memory. Facts that change (hours, prices, rules) belong in a file or a tool, never in the prompt.

Keyword scoring is enough for a dozen sections. Swap in embeddings when the file grows.
"""

import math
import re
from dataclasses import dataclass
from pathlib import Path

KNOWLEDGE_FILE = Path(__file__).resolve().parents[2] / "knowledge" / "hotel.md"

_STOP = set("a an and are at be can do does for from i in is it me my of on or the to we what when where which who will with you your".split())


@dataclass
class Section:
    title: str
    text: str


def load(path: Path = KNOWLEDGE_FILE) -> list[Section]:
    sections = []
    for block in re.split(r"^## ", path.read_text(), flags=re.MULTILINE)[1:]:
        title, _, body = block.partition("\n")
        sections.append(Section(title.strip(), " ".join(body.split())))
    return sections


def _words(text: str) -> list[str]:
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP]
    # Fold plurals so "dog" finds "Dogs": crude, but enough for a short file.
    return [w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in words]


def search(question: str, sections: list[Section], k: int = 2) -> list[Section]:
    """The k sections that best match the question, best first. Title words count double."""
    words = set(_words(question))
    if not words:
        return []
    doc_freq = {w: sum(w in _words(s.title + " " + s.text) for s in sections) for w in words}
    scored = []
    for s in sections:
        body, title = _words(s.text), set(_words(s.title))
        score = sum(
            (body.count(w) + 2 * (w in title)) * math.log(1 + len(sections) / doc_freq[w])
            for w in words
            if doc_freq[w]
        )
        if score > 0:
            scored.append((score, s))
    return [s for _, s in sorted(scored, key=lambda x: -x[0])[:k]]
