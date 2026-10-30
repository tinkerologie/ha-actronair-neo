"""Find developer-blog changes that name identifiers in the integration."""  # noqa: INP001 - Standalone CLI.

from __future__ import annotations

import argparse
import builtins
import json
import keyword
import re
import sys
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup, Tag
from defusedxml import ElementTree
from links import canonical_link

FEED = "https://developers.home-assistant.io/blog/rss.xml"
CHANGE = re.compile(
    r"deprecated|removed|will be removed|no longer|breaking|stops working|must now",
    re.IGNORECASE,
)
# These are ubiquitous context names rather than useful migration signals.
IGNORE = {"hass", "self", "cls", "homeassistant", "async_setup_entry", "async_setup"}


def fetch(url: str) -> bytes:
    """Fetch official HA content over verified HTTPS, following redirects."""
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "developers.home-assistant.io",
        "contributors.home-assistant.io",
    }:
        message = "Only HTTPS Home Assistant developer-blog URLs are supported"
        raise ValueError(message)
    request = Request(  # noqa: S310 - URL scheme and host are validated above.
        url, headers={"User-Agent": "ha-actronair-neo compatibility monitor"}
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310 - Validated official HTTPS host.
        return response.read()


def positive_days(value: str) -> int:
    """Accept only positive integer lookback windows."""
    days = int(value)
    if days < 1:
        message = "days must be a positive integer"
        raise argparse.ArgumentTypeError(message)
    return days


def identifiers(html: bytes) -> set[str] | None:
    """Extract change-announcing inline code and tables in the same section."""
    body = BeautifulSoup(html, "html.parser").select_one(
        "article[data-pagefind-body] .prose"
    )
    if body is None:
        return None
    section = 0
    announcing: set[int] = set()
    candidates: list[tuple[int, Tag]] = []
    codes: list[Tag] = []
    for element in body.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th"]
    ):
        if re.fullmatch(r"h[1-6]", element.name):
            section += 1
        elif element.name in {"td", "th"}:
            candidates.append((section, element))
        elif CHANGE.search(element.get_text(" ", strip=True)):
            announcing.add(section)
            codes.extend(element.find_all("code"))
    for section_id, element in candidates:
        if section_id in announcing:
            codes.extend(element.find_all("code"))
    result: set[str] = set()
    for code in codes:
        if code.find_parent("pre") is not None:
            continue
        name = code.get_text().strip().removesuffix("()")
        parts = name.split(".")
        if not all(
            part.isidentifier() and not keyword.iskeyword(part) for part in parts
        ):
            continue
        for candidate in {name, parts[-1]}:
            if candidate not in IGNORE and candidate not in vars(builtins):
                result.add(candidate)
    return result


def source_hits(names: set[str], root: Path) -> dict[str, list[str]]:
    """Find exact identifiers and their _attr_ backing attributes in Python."""
    hits: dict[str, list[str]] = {}
    for name in sorted(names):
        pattern = re.compile(
            r"(?<!\w)(?:" + re.escape(name) + r"|_attr_" + re.escape(name) + r")(?!\w)"
        )
        locations = []
        for path in sorted((root / "custom_components/actronair_neo").rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if pattern.search(line):
                    locations.append(f"{path.relative_to(root).as_posix()}:{number}")
        if locations:
            hits[name] = locations
    return hits


def scan(days: int, root: Path) -> dict[str, Any]:
    """Inspect every in-window post without assuming feed ordering."""
    feed = ElementTree.fromstring(fetch(FEED))
    cutoff = datetime.now(UTC).date() - timedelta(days=days)
    posts = []
    outside = 0
    seen: set[str] = set()
    for item in feed.findall(".//item"):
        raw_link = item.findtext("link", "")
        link = canonical_link(raw_link)
        if link in seen:
            continue
        seen.add(link)
        try:
            published = parsedate_to_datetime(item.findtext("pubDate", ""))
            if published.tzinfo is None:
                published = published.replace(tzinfo=UTC)
            date = published.astimezone(UTC).date()
        except (TypeError, ValueError, IndexError):
            posts.append(
                {
                    "title": item.findtext("title", "Untitled"),
                    "link": link,
                    "date": "unknown",
                    "identifiers": [],
                    "hits": {},
                    "reason": "Invalid publication date",
                }
            )
            continue
        if date < cutoff:
            outside += 1
            continue
        post: dict[str, Any] = {
            "title": item.findtext("title", "Untitled"),
            "link": link,
            "date": date.isoformat(),
            "identifiers": [],
            "hits": {},
            "reason": "",
        }
        try:
            names = identifiers(fetch(raw_link))
            if names is None:
                post["reason"] = "Article body missing"
            else:
                post["identifiers"] = sorted(names)
                post["hits"] = source_hits(names, root)
                if not names:
                    post["reason"] = "No change-announcing code"
                elif not post["hits"]:
                    post["reason"] = "No integration identifier hit"
        except (OSError, ValueError, HTTPException) as error:
            post["reason"] = f"Article fetch failure: {error}"
        posts.append(post)
    return {"posts": posts, "outside_window": outside}


def main() -> int:
    """Save scan evidence; only an unreadable or invalid feed fails the scan."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=positive_days, default=7)
    parser.add_argument("--output", type=Path, default=Path("blog-results.json"))
    parser.add_argument(
        "--source-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    args = parser.parse_args()
    try:
        result = scan(args.days, args.source_root.resolve())
    except Exception as error:  # noqa: BLE001 - A feed failure must produce a failed workflow.
        sys.stderr.write(f"Developer blog feed failed: {error}\n")
        return 1
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(
        f"Scanned {len(result['posts'])} posts; "
        f"{result['outside_window']} outside the window\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
