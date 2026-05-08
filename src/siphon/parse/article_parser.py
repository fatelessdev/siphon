"""Twitter Article (draft.js) content parser for Siphon.

Converts Twitter Article draft.js content blocks into Markdown text.
Ported from twitter-cli parser.py::_parse_article().
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _deep_get(data: Any, *keys: Any) -> Any:
    """Safely get nested dict/list values.  Supports int keys for list access."""
    current = data
    for key in keys:
        if current is None:
            return None
        if isinstance(key, int):
            if not isinstance(current, list) or key >= len(current):
                return None
            current = current[key]
        else:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
    return current


def _blocks_to_markdown(blocks: list[dict]) -> str:
    """Convert draft.js content blocks to markdown string.

    Supported block types:
    - header-one → # text
    - header-two → ## text
    - header-three → ### text
    - blockquote → > text
    - unordered-list-item → - text
    - ordered-list-item → 1. text (auto-increment)
    - code-block → ```text```
    - atomic → skipped (images/embeds)
    - Everything else → plain text
    """
    parts: list[str] = []
    ordered_counter = 0

    for block in blocks:
        block_type = block.get("type", "unstyled")

        # Skip atomic blocks (images, embeds)
        if block_type == "atomic":
            continue

        text = block.get("text", "")
        if not text:
            continue

        # Reset ordered counter on non-ordered blocks
        if block_type != "ordered-list-item":
            ordered_counter = 0

        if block_type == "header-one":
            parts.append(f"# {text}")
        elif block_type == "header-two":
            parts.append(f"## {text}")
        elif block_type == "header-three":
            parts.append(f"### {text}")
        elif block_type == "blockquote":
            parts.append(f"> {text}")
        elif block_type == "unordered-list-item":
            parts.append(f"- {text}")
        elif block_type == "ordered-list-item":
            ordered_counter += 1
            parts.append(f"{ordered_counter}. {text}")
        elif block_type == "code-block":
            parts.append(f"```\n{text}\n```")
        else:
            parts.append(text)

    return "\n\n".join(parts)


def parse_article_content(tweet_data: dict) -> dict[str, str]:
    """Parse Twitter Article draft.js content to markdown.

    Extracts article data from the tweet's nested `article.article_results.result`
    path and converts draft.js content blocks to Markdown.

    Args:
        tweet_data: The full tweet data dict (containing the `article` key).

    Returns:
        {"title": str, "text": str} — both empty strings if not an article.
    """
    article_result = _deep_get(tweet_data, "article", "article_results", "result")
    if not article_result:
        return {"title": "", "text": ""}

    title = article_result.get("title", "")
    content_state = article_result.get("content_state", {})
    blocks = content_state.get("blocks", [])

    if not blocks:
        return {"title": title or "", "text": ""}

    try:
        markdown = _blocks_to_markdown(blocks)
    except Exception:
        logger.debug("Failed to convert article blocks to markdown", exc_info=True)
        return {"title": title or "", "text": ""}

    return {"title": title or "", "text": markdown}
