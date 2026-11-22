#!/usr/bin/env python3
"""Confirm pinned runtime images resolve and the Newt derivative builds."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULTS = ROOT / "roles/omni/defaults/main.yml"


def value(name: str) -> str:
    match = re.search(rf"^{re.escape(name)}:\s*[\"']?([^\"'\s#]+)", DEFAULTS.read_text(), re.MULTILINE)
    if not match:
        raise RuntimeError(f"could not read {name} from defaults")
    return match.group(1)


def run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    if not shutil.which("docker"):
        raise RuntimeError("docker is required to validate service images")
    images = (
        f"ghcr.io/siderolabs/omni:{value('omni_version')}",
        f"ghcr.io/dexidp/dex:{value('omni_dex_version')}",
        f"docker.io/fosrl/newt:{value('omni_newt_version')}",
        f"docker.io/fosrl/pangolin-cli:{value('omni_pangolin_cli_version')}",
    )
    for image in images:
        run("docker", "pull", image)

    # The deployment's custom Newt image is the protocol-sensitive path. Build
    # it exactly as the role does; the Dockerfile also runs its focused Go test.
    with tempfile.TemporaryDirectory(prefix="ansible-omni-newt-build-") as temp:
        context = Path(temp)
        dockerfile = (ROOT / "roles/omni/templates/newt-http2.Dockerfile.j2").read_text()
        dockerfile = dockerfile.replace("{{ omni_newt_source_commit }}", value("omni_newt_source_commit"))
        dockerfile = dockerfile.replace("{{ omni_newt_version }}", value("omni_newt_version"))
        (context / "Dockerfile").write_text(dockerfile)
        shutil.copy2(ROOT / "roles/omni/files/newt-http2.patch", context / "newt-http2.patch")
        run("docker", "build", "--pull", "--tag", "ansible-omni/newt-http2:update-check", str(context))
    print("validated pinned service images and Newt HTTP/2 derivative")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
