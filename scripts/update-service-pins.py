#!/usr/bin/env python3
"""Discover stable service releases and synchronize this repository's pins.

The script deliberately updates files only with --apply.  Newt is special: the
private-HTTPS HTTP/2 patch must apply cleanly to its release source before the
Newt pin and compatibility map are changed.
"""

from __future__ import annotations

import argparse
import http.client
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "automation/service-pins.json"
DEFAULTS = ROOT / "roles/omni/defaults/main.yml"
EXAMPLE = ROOT / "group_vars/omni.yml.example"
BOOTSTRAP = ROOT / "scripts/bootstrap-1password.sh"
README = ROOT / "README.md"
ROUTER_EXAMPLE = ROOT / "examples/pangolin-subnet-router/compose.yml"
NEWT_COMPATIBILITY = ROOT / "roles/omni/vars/main.yml"


def run(*args: str, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        args, cwd=cwd, text=True, check=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


def release_key(tag: str) -> tuple[int, ...] | None:
    """Return a numeric key for stable SemVer-like release tags."""
    match = re.fullmatch(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", tag)
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())


def latest_release(repository: str, prefix: str, discovery: str = "releases") -> str:
    endpoint = "tags" if discovery == "tags" else "releases"
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/{endpoint}?per_page=100",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "ansible-omni-updater"},
    )
    releases = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                releases = json.load(response)
            break
        except (http.client.HTTPException, urllib.error.URLError) as error:
            if attempt == 2:
                raise RuntimeError(f"could not query {endpoint} for {repository}: {error}") from error
            time.sleep(attempt + 1)
    assert releases is not None

    candidates: list[tuple[tuple[int, ...], str]] = []
    for release in releases:
        tag = release.get("name", "") if discovery == "tags" else release.get("tag_name", "")
        if discovery == "releases" and (release.get("draft") or release.get("prerelease")):
            continue
        if prefix and not tag.startswith(prefix):
            continue
        if release_key(tag) is not None:
            candidates.append((release_key(tag), tag))
    if not candidates:
        raise RuntimeError(f"no stable SemVer release was found for {repository}")
    return max(candidates)[1]


def current_value(variable: str) -> str:
    match = re.search(rf"^{re.escape(variable)}:\s*[\"']?([^\"'\s#]+)", DEFAULTS.read_text(), re.MULTILINE)
    if not match:
        raise RuntimeError(f"could not find {variable} in {DEFAULTS.relative_to(ROOT)}")
    return match.group(1)


def replace_exact(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count == 0:
        raise RuntimeError(f"expected {old!r} in {path.relative_to(ROOT)}")
    path.write_text(text.replace(old, new))


def resolve_newt_commit(tag: str) -> str:
    refs = run("git", "ls-remote", "https://github.com/fosrl/newt.git", f"refs/tags/{tag}^{{}}", f"refs/tags/{tag}")
    lines = [line.split("\t", 1) for line in refs.splitlines() if "\t" in line]
    peeled = [sha for sha, ref in lines if ref.endswith("^{}")]
    commit = peeled[0] if peeled else (lines[0][0] if lines else "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError(f"could not resolve immutable source commit for Newt tag {tag}")
    return commit


def newt_patch_applies(commit: str, patch: Path) -> bool:
    tempdir = Path(tempfile.mkdtemp(prefix="ansible-omni-newt-"))
    try:
        repository = tempdir / "newt"
        run("git", "init", str(repository))
        run("git", "remote", "add", "origin", "https://github.com/fosrl/newt.git", cwd=repository)
        run("git", "fetch", "--depth", "1", "origin", commit, cwd=repository)
        run("git", "checkout", "--detach", "FETCH_HEAD", cwd=repository)
        try:
            run("git", "apply", "--check", str(patch), cwd=repository)
        except subprocess.CalledProcessError:
            return False
        return True
    finally:
        shutil.rmtree(tempdir)


def newt_derivative_builds(tag: str, commit: str, patch: Path) -> bool:
    """Build the same derivative the role will build, including its Go test."""
    if not shutil.which("docker"):
        return False
    tempdir = Path(tempfile.mkdtemp(prefix="ansible-omni-newt-build-"))
    try:
        dockerfile = (ROOT / "roles/omni/templates/newt-http2.Dockerfile.j2").read_text()
        dockerfile = dockerfile.replace("{{ omni_newt_source_commit }}", commit)
        dockerfile = dockerfile.replace("{{ omni_newt_version }}", tag)
        (tempdir / "Dockerfile").write_text(dockerfile)
        shutil.copy2(patch, tempdir / "newt-http2.patch")
        try:
            run("docker", "build", "--pull", "--tag", "ansible-omni/newt-http2:update-candidate", str(tempdir))
        except subprocess.CalledProcessError:
            return False
        return True
    finally:
        shutil.rmtree(tempdir)


def update_regular_pin(variable: str, old: str, new: str) -> None:
    for path in (DEFAULTS, EXAMPLE, BOOTSTRAP, README):
        replace_exact(path, old, new)
    if variable == "omni_pangolin_cli_version":
        replace_exact(ROUTER_EXAMPLE, old, new)


def update_newt_pin(old_tag: str, new_tag: str, old_commit: str, new_commit: str) -> None:
    update_regular_pin("omni_newt_version", old_tag, new_tag)
    for path in (DEFAULTS, EXAMPLE, BOOTSTRAP, README):
        replace_exact(path, old_commit, new_commit)
    old_short = f"{old_commit[:7]}…{old_commit[-6:]}"
    new_short = f"{new_commit[:7]}…{new_commit[-6:]}"
    replace_exact(README, old_short, new_short)
    compatibility = NEWT_COMPATIBILITY.read_text()
    compatibility = re.sub(
        rf'^(\s*)"{re.escape(old_tag)}": "{re.escape(old_commit)}"$',
        rf'\1"{new_tag}": "{new_commit}"',
        compatibility,
        flags=re.MULTILINE,
    )
    NEWT_COMPATIBILITY.write_text(compatibility)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write discovered pins into tracked files")
    parser.add_argument("--report", type=Path, help="write a JSON update report")
    args = parser.parse_args()

    catalog = json.loads(CATALOG.read_text())["services"]
    report: dict[str, object] = {"updated": {}, "unchanged": {}, "skipped": {}}

    for name, service in catalog.items():
        variable = service["variable"]
        old = current_value(variable)
        latest_release_tag = latest_release(
            service["github_repository"], service["tag_prefix"], service.get("discovery", "releases")
        )
        latest = latest_release_tag.removeprefix("v") if service.get("strip_leading_v") else latest_release_tag
        if latest == old:
            report["unchanged"][name] = old
            continue

        if name == "newt":
            old_commit = current_value("omni_newt_source_commit")
            new_commit = resolve_newt_commit(latest_release_tag)
            patch = ROOT / service["http2_patch"]
            if not newt_patch_applies(new_commit, patch):
                report["skipped"][name] = (
                    f"{old} -> {latest}: HTTP/2 patch does not apply cleanly to {new_commit}"
                )
                continue
            if not newt_derivative_builds(latest, new_commit, patch):
                report["skipped"][name] = (
                    f"{old} -> {latest}: HTTP/2 derivative did not build and pass its focused test"
                )
                continue
            if args.apply:
                update_newt_pin(old, latest, old_commit, new_commit)
            report["updated"][name] = {"from": old, "to": latest, "source_commit": new_commit}
            continue

        if args.apply:
            update_regular_pin(variable, old, latest)
        report["updated"][name] = {"from": old, "to": latest}

    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.write_text(payload)
    print(payload, end="")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
