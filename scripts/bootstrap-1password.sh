#!/usr/bin/env sh
# Create one 1Password item containing every public ansible-omni role variable.
#
# Usage:
#   scripts/bootstrap-1password.sh --vault "Infrastructure"
#   scripts/bootstrap-1password.sh --vault "Infrastructure" --item "Production Omni"
#   scripts/bootstrap-1password.sh --vault "Infrastructure" --oidc-provider pocketid

set -eu

item_title="ansible-omni"
vault_name=""
oidc_provider="dex"

usage() {
  echo "Usage: $0 --vault VAULT [--item ITEM_TITLE] [--oidc-provider dex|pocketid]" >&2
  exit 2
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --vault)
      [ "$#" -ge 2 ] || usage
      vault_name=$2
      shift 2
      ;;
    --item)
      [ "$#" -ge 2 ] || usage
      item_title=$2
      shift 2
      ;;
    --oidc-provider)
      [ "$#" -ge 2 ] || usage
      oidc_provider=$2
      shift 2
      ;;
    -h|--help)
      usage
      ;;
    *)
      usage
      ;;
  esac
done

[ -n "$vault_name" ] || usage
case "$oidc_provider" in
  dex|pocketid) ;;
  *)
    echo "--oidc-provider must be dex or pocketid." >&2
    exit 2
    ;;
esac

command -v op >/dev/null 2>&1 || {
  echo "1Password CLI (op) is required; install it and sign in first." >&2
  exit 1
}
command -v python3 >/dev/null 2>&1 || {
  echo "python3 is required to build the item template." >&2
  exit 1
}

# Do not replace an existing item: it may contain rotated credentials.
if op item get "$item_title" --vault "$vault_name" --format json >/dev/null 2>&1; then
  echo "1Password item '$item_title' already exists in vault '$vault_name'; refusing to overwrite it." >&2
  exit 1
fi

# Python's secrets module generates the two fresh credentials in memory. They
# enter 1Password only through the JSON template and never appear in arguments
# or command output. Existing provider-issued credentials remain empty.
OP_ITEM_TITLE=$item_title OP_OIDC_PROVIDER=$oidc_provider python3 - <<'PY' | op item create --vault "$vault_name" - >/dev/null
import json
import os
import secrets

admin_password = secrets.token_urlsafe(32)
oidc_client_secret = secrets.token_hex(32)

values = {
    "omni_install_docker": True,
    "omni_version": "v1.12.4",
    "omni_dex_version": "v2.41.1",
    "omni_base_dir": "/opt/omni",
    "omni_endpoint": "omni.internal",
    "omni_auth_endpoint": "auth.internal",
    "omni_advertised_ip": "{{ ansible_default_ipv4.address }}",
    "omni_private_ip": "{{ ansible_default_ipv4.address }}",
    "omni_admin_email": "admin@omni.internal",
    "omni_admin_password": admin_password,
    "omni_oidc_client_id": "omni",
    "omni_oidc_client_secret": oidc_client_secret,
    "omni_oidc_provider": os.environ["OP_OIDC_PROVIDER"],
    "omni_pocketid_url": "",
    "omni_pocketid_bootstrap": False,
    "omni_pocketid_api_key": "",
    "omni_pocketid_client_name": "Sidero Omni",
    "omni_pocketid_skip_consent": False,
    "omni_extra_ca_certificates": "",
    "omni_eula_name": "",
    "omni_eula_email": "",
    "omni_ca_common_name": "Omni Internal Root CA",
    "omni_cert_country": "US",
    "omni_cert_organization": "Internal Infrastructure",
    "omni_cert_valid_days": 3650,
    "omni_add_host_entries": True,
    "omni_newt_enabled": False,
    "omni_newt_version": "1.19.0",
    "omni_newt_pangolin_endpoint": "",
    "omni_newt_id": "",
    "omni_newt_secret": "",
    "omni_newt_network_name": "omni-newt",
    "omni_newt_http2_enabled": False,
    "omni_newt_source_commit": "329d6a1c6509aa0769fa5bf3b8437518fc4e83df",
    "omni_pangolin_subnet_router_enabled": False,
    "omni_pangolin_cli_version": "0.18.1",
    "omni_pangolin_machine_endpoint": "",
    "omni_pangolin_machine_id": "",
    "omni_pangolin_machine_secret": "",
    "omni_embedded_etcd": True,
    "omni_etcd_endpoints": "[]",
    "omni_external_etcd_ca": "",
    "omni_external_etcd_client_cert": "",
    "omni_external_etcd_client_key": "",
}
concealed = {
    "omni_admin_password",
    "omni_oidc_client_secret",
    "omni_pocketid_api_key",
    "omni_newt_secret",
    "omni_pangolin_machine_secret",
    "omni_external_etcd_client_key",
}

item = {
    "title": os.environ["OP_ITEM_TITLE"],
    # A Secure Note has no required built-in password field. Credentials below
    # remain custom concealed fields with the exact variable-name labels used
    # by the Ansible reference template.
    "category": "SECURE_NOTE",
    "fields": [
        {"label": name, "type": "CONCEALED" if name in concealed else "STRING", "value": str(value).lower() if isinstance(value, bool) else str(value)}
        for name, value in values.items()
    ],
}
print(json.dumps(item))
PY

echo "Created '$item_title' in '$vault_name'."
echo "Generated omni_admin_password and omni_oidc_client_secret in the item."
echo "Paste existing Pocket ID, Pangolin/Newt, or external-etcd credentials into their empty fields as needed."
echo "Next: copy group_vars/omni.1password.yml.example to group_vars/omni.yml and replace <vault> and <item>."
