"""File blog findings using all open and closed issues for deduplication."""  # noqa: INP001 - Standalone CLI.

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from links import canonical_link


def gh(*args: str) -> str:
    """Invoke a resolved GitHub CLI with arguments passed as data."""
    executable = shutil.which("gh")
    if executable is None:
        message = "GitHub CLI is required"
        raise RuntimeError(message)
    return subprocess.run(  # noqa: S603 - Resolved CLI, arguments, no shell.
        [executable, *args], check=True, text=True, capture_output=True
    ).stdout


def ensure_labels(repository: str, labels: set[str] | None) -> set[str]:
    """Create missing issue labels while preserving existing label metadata."""
    if labels is None:
        pages = json.loads(
            gh(
                "api",
                "--paginate",
                "--slurp",
                f"repos/{repository}/labels?per_page=100",
            )
        )
        labels = {label["name"] for page in pages for label in page}
    for label, color in [("ha-dev-blog", "0075ca"), ("enhancement", "a2eeef")]:
        if label not in labels:
            gh("label", "create", label, "--color", color, "--repo", repository)
            labels.add(label)
    return labels


def main() -> None:
    """Create one issue per matched post and summarise every scanned post."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    repository = os.environ["GH_REPO"]
    pages = json.loads(
        gh(
            "api",
            "--paginate",
            "--slurp",
            f"repos/{repository}/issues?state=all&per_page=100",
        )
    )
    existing: dict[str, int] = {}
    labels: set[str] | None = None
    for page in pages:
        for issue in page:
            if "pull_request" in issue:
                continue
            for link in re.findall(
                r"https://(?:developers|contributors)\.home-assistant\.io/[^\s<>\])]+",
                issue.get("body") or "",
            ):
                existing[canonical_link(link)] = issue["number"]
    summary = ["## Developer blog watch", "", "| Post | Result |", "| --- | --- |"]
    for post in data["posts"]:
        link = canonical_link(post["link"])
        if link in existing:
            result = f"Existing issue #{existing[link]}"
        elif not post["hits"]:
            result = post["reason"] or "No integration identifier hit"
        else:
            labels = ensure_labels(repository, labels)
            body = (
                f"Developer blog: {link}\n\nPublished: {post['date']}\n\n"
                "The post names identifiers used by this integration:\n\n"
            )
            for name, hits in post["hits"].items():
                body += f"- `{name}`: " + ", ".join(f"`{hit}`" for hit in hits) + "\n"
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "body.md"
                path.write_text(body, encoding="utf-8")
                url = gh(
                    "issue",
                    "create",
                    "--repo",
                    repository,
                    "--title",
                    ("HA dev blog: " + post["title"])[:256],
                    "--label",
                    "ha-dev-blog",
                    "--label",
                    "enhancement",
                    "--body-file",
                    str(path),
                ).strip()
            existing[link] = int(url.rsplit("/", 1)[1])
            result = f"Created [#{existing[link]}]({url})"
        title = post["title"].replace("|", "\\|").replace("\n", " ")
        result = result.replace("|", "\\|").replace("\n", " ")
        summary.append(f"| [{title}]({link}) | {result} |")
    summary.append(f"\nPosts outside the window: {data['outside_window']}\n")
    if output := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write("\n".join(summary))


if __name__ == "__main__":
    main()
