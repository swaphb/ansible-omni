#!/usr/bin/env python3
"""Render and validate supported Omni Compose configurations."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined


ROOT = Path(__file__).resolve().parent.parent


def render(values: dict[str, object]) -> dict[str, object]:
    defaults = yaml.safe_load((ROOT / "roles/omni/defaults/main.yml").read_text())
    defaults.update(values)
    defaults.update({
        "omni_oidc_client_secret": "validation-client-secret-at-least-24-characters",
        "omni_admin_email": "admin@example.test",
        "omni_newt_secret": "validation-newt-secret",
        "omni_pangolin_machine_secret": "validation-machine-secret",
    })
    environment = Environment(
        loader=FileSystemLoader(str(ROOT / "roles/omni/templates")),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    environment.filters["to_json"] = json.dumps
    environment.filters["regex_replace"] = lambda value, pattern, replacement: re.sub(pattern, replacement, value)
    text = environment.get_template("compose.yml.j2").render(**defaults)
    return yaml.safe_load(text)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def validate_variant(name: str, values: dict[str, object]) -> None:
    compose = render(values)
    services = compose.get("services", {})
    is_newt = bool(values.get("omni_newt_enabled"))
    is_pocketid = values.get("omni_oidc_provider") == "pocketid"
    require("omni" in services, f"{name}: Omni service is missing")
    require(("dex" in services) != is_pocketid, f"{name}: incorrect Dex service presence")
    if is_newt:
        require("ports" not in services["omni"], f"{name}: Newt Omni must not publish ports")
        if "dex" in services:
            require("ports" not in services["dex"], f"{name}: Newt Dex must not publish ports")
        require("newt" in services, f"{name}: Newt service is missing")
    else:
        require(services["omni"].get("network_mode") == "host", f"{name}: direct Omni must use host networking")
    if values.get("omni_pangolin_subnet_router_enabled"):
        require("pangolin-subnet-router" in services, f"{name}: subnet router is missing")


def main() -> int:
    for path_text in subprocess.check_output(
        ["git", "ls-files", "*.yml", "*.yaml"], cwd=ROOT, text=True
    ).splitlines():
        yaml.safe_load((ROOT / path_text).read_text())

    ansible = Path(sys.executable).with_name("ansible-playbook")
    if not ansible.exists():
        discovered = shutil.which("ansible-playbook")
        ansible = Path(discovered) if discovered else ansible
    if not ansible.exists():
        raise RuntimeError("ansible-playbook is required for syntax validation")
    environment = os.environ.copy()
    environment.setdefault("ANSIBLE_LOCAL_TEMP", "/tmp/ansible-local")
    Path(environment["ANSIBLE_LOCAL_TEMP"]).mkdir(parents=True, exist_ok=True)
    subprocess.run([str(ansible), "--syntax-check", "site.yml"], cwd=ROOT, check=True, env=environment)

    common_newt = {
        "omni_newt_enabled": True,
        "omni_newt_pangolin_endpoint": "https://pangolin.example.test",
        "omni_newt_id": "validation-site",
    }
    variants = {
        "dex-direct": {"omni_oidc_provider": "dex"},
        "dex-newt": {"omni_oidc_provider": "dex", **common_newt},
        "pocketid-direct": {"omni_oidc_provider": "pocketid", "omni_pocketid_url": "https://id.example.test"},
        "pocketid-newt": {"omni_oidc_provider": "pocketid", "omni_pocketid_url": "https://id.example.test", **common_newt},
        "pocketid-newt-router": {
            "omni_oidc_provider": "pocketid", "omni_pocketid_url": "https://id.example.test",
            "omni_pangolin_subnet_router_enabled": True,
            "omni_pangolin_machine_endpoint": "https://pangolin.example.test",
            "omni_pangolin_machine_id": "validation-machine", **common_newt,
        },
        "dex-external-etcd": {
            "omni_oidc_provider": "dex", "omni_embedded_etcd": False,
            "omni_etcd_endpoints": ["https://etcd.example.test:2379"],
        },
    }
    for name, values in variants.items():
        validate_variant(name, values)
    print(f"validated {len(variants)} Compose variants")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError, yaml.YAMLError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
