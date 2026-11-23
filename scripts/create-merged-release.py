#!/usr/bin/env python3
"""Publish categorized release notes for one merged pull request."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
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


def release_notes(pull_request: dict[str, object], commits: list[dict[str, object]]) -> str:
    title = str(pull_request.get("title", "Merged pull request")).strip()
    body = str(pull_request.get("body") or "")
    url = str(pull_request.get("html_url") or "")
    subjects = [title]
    subjects.extend(commit_subject(commit) for commit in commits)
    subjects = [subject for subject in subjects if subject]

    sections = {
        "Breaking changes": [],
        "New features": [],
        "Bug fixes": [],
        "Upgrades": [],
        "Other changes": [],
    }
    for subject in dict.fromkeys(subjects):
        sections[category(subject, subject == title and bool(BREAKING.search(body)))].append(subject)

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


def existing_release(api_url: str, repository: str, tag: str, token: str) -> dict[str, object] | None:
    endpoint = f"{api_url}/repos/{repository}/releases/tags/{urllib.parse.quote(tag, safe='')}"
    try:
        release = request(endpoint, token)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise
    if not isinstance(release, dict):
        raise RuntimeError("Gitea returned an invalid release")
    return release


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

    tag = f"release-pr-{number}-{merge_sha[:12].lower()}"
    release = existing_release(api_url, repository, tag, token)
    if release:
        print(f"Release already exists: {release.get('html_url', tag)}")
        return 0

    pull_request_url = f"{api_url}/repos/{repository}/pulls/{number}"
    pull_request = request(pull_request_url, token)
    if not isinstance(pull_request, dict):
        raise RuntimeError("Gitea returned an invalid pull request")
    commits = pull_request_commits(api_url, repository, number, token)
    payload = {
        "tag_name": tag,
        "target_commitish": merge_sha,
        "name": f"Release for pull request #{number}",
        "body": release_notes(pull_request, commits),
    }
    try:
        created = request(f"{api_url}/repos/{repository}/releases", token, "POST", payload)
    except urllib.error.HTTPError as error:
        if error.code == 409:
            release = existing_release(api_url, repository, tag, token)
            if release:
                print(f"Release already exists: {release.get('html_url', tag)}")
                return 0
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
