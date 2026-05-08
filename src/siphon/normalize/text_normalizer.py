from __future__ import annotations

import html
import re
import unicodedata

_ZERO_WIDTH_CHARS = re.compile(
    "[\u200b\u200c\u200d\u200e\u200f\ufeff\u00ad\u2060\u2061\u2062\u2063\u2064\u180e]"
)
_SMART_QUOTES = str.maketrans({
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2014": "--",
    "\u2013": "-",
    "\u2026": "...",
    "\u00a0": " ",
    "\u00ab": '"',
    "\u00bb": '"',
})
_TCO_TRAILING = re.compile(r"\s*https?://t\.co/\w+\s*$")


def normalize_text(raw: str) -> str:
    if not raw:
        return ""
    text = unicodedata.normalize("NFKC", raw)
    text = html.unescape(text)
    text = text.translate(_SMART_QUOTES)
    text = _ZERO_WIDTH_CHARS.sub("", text)
    text = _TCO_TRAILING.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
