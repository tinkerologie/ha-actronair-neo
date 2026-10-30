"""Canonicalise developer-blog links for open and closed issue deduplication."""  # noqa: INP001 - Shared CLI helper.

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def canonical_link(raw: str) -> str:
    """Map the old blog host to its new host and discard tracking parameters."""
    parsed = urlsplit(raw.strip())
    host = parsed.netloc.lower()
    if host == "developers.home-assistant.io":
        host = "contributors.home-assistant.io"
    return urlunsplit((parsed.scheme, host, parsed.path.rstrip("/") + "/", "", ""))
