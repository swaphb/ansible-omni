#!/usr/bin/env python3
"""Create or update the single workflow-owned dependency update pull request."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def request(url: str, token: str, method: str = "GET", body: dict | None = None) -> object:
    data = json.dumps(body).encode() if body is not None else None
    call = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"token {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(call, timeout=30) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--branch", default="automation/service-updates")
    args = parser.parse_args()
    api_url = os.environ["GITEA_API_URL"].rstrip("/")
    repository = os.environ["GITEA_REPOSITORY"]
    token = os.environ["GITEA_TOKEN"]
    owner, _ = repository.split("/", 1)
    report = json.load(open(args.report))
    updates = report.get("updated", {})
    if not updates:
        print("No pull request created: no compatible stable releases found.")
        return 0
    lines = ["## Automated dependency update", "", "Validated pinned service images and Compose variants.", "", "### Changes", ""]
    for service, change in updates.items():
        if isinstance(change, dict):
            lines.append(f"- `{service}`: `{change['from']}` → `{change['to']}`")
    for service, reason in report.get("skipped", {}).items():
        lines.append(f"- `{service}`: skipped — {reason}")
    body = "\n".join(lines) + "\n"
    pulls = request(f"{api_url}/repos/{repository}/pulls?state=open&limit=100", token)
    existing = next((pull for pull in pulls if pull.get("head", {}).get("ref") == args.branch), None)
    if existing:
        updated = request(f"{api_url}/repos/{repository}/pulls/{existing['number']}", token, "PATCH", {"title": "chore: update pinned service versions", "body": body})
        print(updated["html_url"])
        return 0
    created = request(f"{api_url}/repos/{repository}/pulls", token, "POST", {
        "title": "chore: update pinned service versions",
        "head": args.branch,
        "base": "main",
        "body": body,
    })
    print(created["html_url"])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, OSError, urllib.error.URLError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
