#!/usr/bin/env python3
"""Publish a sequentially versioned release for one merged pull request."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request


BREAKING = re.compile(r"\bbreaking(?:[ -]change)?\b|^[a-z]+(?:\([^)]*\))?!:", re.IGNORECASE)
FEATURE = re.compile(r"^(?:feat|feature)(?:\([^)]*\))?!?:", re.IGNORECASE)
FIX = re.compile(r"^(?:fix|bugfix|hotfix)(?:\([^)]*\))?!?:|\b(?:bug fix|bugfix)\b", re.IGNORECASE)
# Words that mark a subject as being about dependencies rather than prose.
DEPENDENCY_CONTEXT = (
    r"dependenc(?:y|ies)|packages?|images?|modules?|charts?|librar(?:y|ies)"
    r"|versions?|digests?|releases?|requirements?|lock(?:file)?s?"
)
UPGRADE_VERB = r"upgrade[sd]?|upgrading|pin(?:s|ned|ning)?"
# An upgrade is either a build/ci/chore/deps commit, or a subject that names a
# dependency outright, or an upgrade verb paired with dependency context. Bare
# "update" / "version" are deliberately excluded: they appear in unrelated
# subjects such as "docs: update README formatting".
UPGRADE = re.compile(
    r"^(?:build|ci|chore|deps)(?:\([^)]*\))?!?:"
    r"|\bdependenc(?:y|ies)\b"
    r"|\bbump(?:s|ed|ing)?\b"
    rf"|\b(?:{UPGRADE_VERB})\b[^\n]*\b(?:{DEPENDENCY_CONTEXT})\b"
    rf"|\b(?:{DEPENDENCY_CONTEXT})\b[^\n]*\b(?:{UPGRADE_VERB})\b",
    re.IGNORECASE,
)

VERSION_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def request(url: str, token: str, method: str = "GET", body: dict[str, object] | None = None) -> object:
    data = json.dumps(body).encode() if body is not None else None
    call = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Authorization": f"token {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(call, timeout=30) as response:
        return json.load(response)


def pull_request_commits(api_url: str, repository: str, number: str, token: str) -> list[dict[str, object]]:
    commits: list[dict[str, object]] = []
    page = 1
    while True:
        endpoint = f"{api_url}/repos/{repository}/pulls/{number}/commits?limit=100&page={page}"
        result = request(endpoint, token)
        if not isinstance(result, list):
            raise RuntimeError("Gitea returned an invalid pull-request commit list")
        commits.extend(commit for commit in result if isinstance(commit, dict))
        if len(result) < 100:
            return commits
        page += 1


def commit_subject(commit: dict[str, object]) -> str:
    message = commit.get("commit", {})
    if not isinstance(message, dict):
        return ""
    text = message.get("message", "")
    return str(text).splitlines()[0].strip()


def category(subject: str, is_breaking_pull_request: bool = False) -> str:
    if is_breaking_pull_request or BREAKING.search(subject):
        return "Breaking changes"
    if FEATURE.search(subject):
        return "New features"
    if FIX.search(subject):
        return "Bug fixes"
    if UPGRADE.search(subject):
        return "Upgrades"
    return "Other changes"


def link_label(text: str) -> str:
    """Escape text so it stays inside the label of a Markdown link."""
    return re.sub(r"([\\\[\]])", r"\\\1", text)


def categorize(pull_request: dict[str, object], commits: list[dict[str, object]]) -> dict[str, list[str]]:
    title = str(pull_request.get("title", "Merged pull request")).strip()
    body = str(pull_request.get("body") or "")
    subjects = [title]
    subjects.extend(commit_subject(commit) for commit in commits)
    subjects = [subject for subject in subjects if subject]

    sections: dict[str, list[str]] = {
        "Breaking changes": [],
        "New features": [],
        "Bug fixes": [],
        "Upgrades": [],
        "Other changes": [],
    }
    for subject in dict.fromkeys(subjects):
        sections[category(subject, subject == title and bool(BREAKING.search(body)))].append(subject)
    return sections


def bump_kind(sections: dict[str, list[str]]) -> str:
    """The semver component a release should bump, from its categorized changes."""
    if sections["Breaking changes"]:
        return "major"
    if sections["New features"]:
        return "minor"
    return "patch"


def release_notes(pull_request: dict[str, object], sections: dict[str, list[str]]) -> str:
    title = str(pull_request.get("title", "Merged pull request")).strip()
    url = str(pull_request.get("html_url") or "")

    lines = ["## Included pull request", ""]
    if url:
        lines.append(f"- [{link_label(title)}]({url})")
    else:
        lines.append(f"- {title}")
    for heading, changes in sections.items():
        if changes:
            lines.extend(["", f"## {heading}", ""])
            lines.extend(f"- {change}" for change in changes)
    return "\n".join(lines) + "\n"


def list_releases(api_url: str, repository: str, token: str) -> list[dict[str, object]]:
    releases: list[dict[str, object]] = []
    page = 1
    while True:
        endpoint = f"{api_url}/repos/{repository}/releases?limit=50&page={page}"
        result = request(endpoint, token)
        if not isinstance(result, list):
            raise RuntimeError("Gitea returned an invalid release list")
        releases.extend(release for release in result if isinstance(release, dict))
        if len(result) < 50:
            return releases
        page += 1


def parse_version(tag: str) -> tuple[int, int, int] | None:
    match = VERSION_TAG.fullmatch(tag)
    if not match:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return (major, minor, patch)


def latest_version(releases: list[dict[str, object]]) -> tuple[int, int, int] | None:
    versions = [
        version
        for version in (parse_version(str(release.get("tag_name", ""))) for release in releases)
        if version
    ]
    return max(versions) if versions else None


def next_version(latest: tuple[int, int, int] | None, kind: str) -> tuple[int, int, int]:
    if latest is None:
        return (1, 0, 0)
    major, minor, patch = latest
    if kind == "major":
        return (major + 1, 0, 0)
    if kind == "minor":
        return (major, minor + 1, 0)
    return (major, minor, patch + 1)


def format_version(version: tuple[int, int, int]) -> str:
    return f"v{version[0]}.{version[1]}.{version[2]}"


def release_for_commit(releases: list[dict[str, object]], merge_sha: str) -> dict[str, object] | None:
    return next(
        (release for release in releases if str(release.get("target_commitish", "")) == merge_sha),
        None,
    )


def main() -> int:
    api_url = os.environ["GITEA_API_URL"].rstrip("/")
    repository = os.environ["GITEA_REPOSITORY"]
    token = os.environ["GITEA_TOKEN"]
    merge_sha = os.environ["MERGE_COMMIT_SHA"]
    number = os.environ["PULL_REQUEST_NUMBER"]
    if not re.fullmatch(r"[0-9a-fA-F]{7,64}", merge_sha):
        raise RuntimeError("MERGE_COMMIT_SHA must be a Git commit SHA")
    if not number.isdecimal():
        raise RuntimeError("PULL_REQUEST_NUMBER must be numeric")

    releases = list_releases(api_url, repository, token)
    existing = release_for_commit(releases, merge_sha)
    if existing:
        print(f"Release already exists for this merge commit: {existing.get('html_url', merge_sha)}")
        return 0

    pull_request_url = f"{api_url}/repos/{repository}/pulls/{number}"
    pull_request = request(pull_request_url, token)
    if not isinstance(pull_request, dict):
        raise RuntimeError("Gitea returned an invalid pull request")
    commits = pull_request_commits(api_url, repository, number, token)
    sections = categorize(pull_request, commits)
    kind = bump_kind(sections)
    tag = format_version(next_version(latest_version(releases), kind))

    payload = {
        "tag_name": tag,
        "target_commitish": merge_sha,
        "name": tag,
        "body": release_notes(pull_request, sections),
    }
    try:
        created = request(f"{api_url}/repos/{repository}/releases", token, "POST", payload)
    except urllib.error.HTTPError as error:
        if error.code == 409:
            # Another run took this tag or this merge commit first. Re-read
            # releases: if this commit is now covered, we're done; otherwise
            # recompute the next version from current state and retry once.
            releases = list_releases(api_url, repository, token)
            existing = release_for_commit(releases, merge_sha)
            if existing:
                print(f"Release already exists for this merge commit: {existing.get('html_url', merge_sha)}")
                return 0
            payload["tag_name"] = payload["name"] = format_version(next_version(latest_version(releases), kind))
            created = request(f"{api_url}/repos/{repository}/releases", token, "POST", payload)
        else:
            raise
    if not isinstance(created, dict):
        raise RuntimeError("Gitea returned an invalid created release")
    print(f"Created release: {created.get('html_url', tag)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, RuntimeError, urllib.error.URLError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
