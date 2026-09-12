"""safe_text: returns a cleaned plain-text rendering of a document.

Strips detected payload text so downstream LLMs cannot read it.
"""
from __future__ import annotations

import re

from purifydocs.scanner.base import ScanResult

from purifydocs.scanner.txt import ZERO_WIDTH_CHARS, BASE64_RE


def safe_text(result: ScanResult) -> str:
    """Return document text with detected payloads removed.

    Removes:
      * all zero-width characters
      * base64 instruction tokens
      * prompt-like instruction lines
    """
    text = result.extracted_text

    # 1. strip zero-width chars (always) — this can expose hidden
    #    prompt-like text that was previously invisible to humans.
    text = result.extracted_text
    for c in ZERO_WIDTH_CHARS:
        text = text.replace(c, "")

    # 2. remove base64 tokens
    text = BASE64_RE.sub("", text)

    # 3. remove prompt-like lines. Re-detect on the stripped text because
    #    zero-width removal can reveal previously hidden instructions whose
    #    stored evidence (with zero-widths) won't match the clean line.
    from purifydocs.scanner.txt import PROMPT_LIKE_PATTERNS

    kept = []
    for line in text.splitlines():
        if any(p.search(line) for p in PROMPT_LIKE_PATTERNS):
            continue
        kept.append(line)
    text = "\n".join(kept)

    # collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    return text
