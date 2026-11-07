#!/usr/bin/env sh
# Render a local group_vars/omni.yml from the single 1Password item.
# The result contains secrets and is intentionally ignored by Git.

set -eu

item_title="ansible-omni"
vault_name=""
output_path="group_vars/omni.yml"

usage() {
  echo "Usage: $0 --vault VAULT [--item ITEM_TITLE] [--out PATH]" >&2
  exit 2
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --vault) [ "$#" -ge 2 ] || usage; vault_name=$2; shift 2 ;;
    --item) [ "$#" -ge 2 ] || usage; item_title=$2; shift 2 ;;
    --out) [ "$#" -ge 2 ] || usage; output_path=$2; shift 2 ;;
    -h|--help) usage ;;
    *) usage ;;
  esac
done

[ -n "$vault_name" ] || usage
command -v op >/dev/null 2>&1 || { echo "1Password CLI (op) is required." >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "python3 is required." >&2; exit 1; }

output_dir=$(dirname "$output_path")
[ -d "$output_dir" ] || { echo "Output directory does not exist: $output_dir" >&2; exit 1; }
temp_path=$(mktemp "$output_dir/.omni.1password.XXXXXX")
trap 'rm -f "$temp_path"' EXIT HUP INT TERM
chmod 600 "$temp_path"

# JSON is valid YAML. Serializing the item this way preserves booleans, lists,
# and multiline PEM fields without exposing them in command arguments or logs.
# The program arrives on file descriptor 3 so Python can read the 1Password
# item JSON from stdin without writing that JSON (which includes secrets) out.
op item get "$item_title" --vault "$vault_name" --format json | python3 /dev/fd/3 >"$temp_path" 3<<'PY'
import json
import sys

item = json.load(sys.stdin)
values = {field.get("label"): field.get("value", "") for field in item["fields"]}
names = (
    "omni_install_docker omni_version omni_dex_version omni_base_dir omni_endpoint "
    "omni_auth_endpoint omni_advertised_ip omni_private_ip omni_admin_email "
    "omni_admin_password omni_oidc_client_id omni_oidc_client_secret "
    "omni_oidc_provider omni_pocketid_url omni_pocketid_bootstrap "
    "omni_pocketid_api_key omni_pocketid_client_name omni_pocketid_skip_consent "
    "omni_extra_ca_certificates omni_eula_name omni_eula_email omni_ca_common_name "
    "omni_cert_country omni_cert_organization omni_cert_valid_days omni_add_host_entries "
    "omni_newt_enabled omni_newt_version omni_newt_pangolin_endpoint omni_newt_id "
    "omni_newt_secret omni_newt_network_name omni_embedded_etcd omni_etcd_endpoints "
    "omni_external_etcd_ca omni_external_etcd_client_cert omni_external_etcd_client_key"
).split()
missing = [name for name in names if name not in values]
if missing:
    raise SystemExit("1Password item is missing fields: " + ", ".join(missing))

bools = {
    "omni_install_docker", "omni_pocketid_bootstrap", "omni_pocketid_skip_consent",
    "omni_add_host_entries", "omni_newt_enabled", "omni_embedded_etcd",
}
result = {name: values[name] for name in names}
for name in bools:
    value = str(result[name]).lower()
    if value not in {"true", "false"}:
        raise SystemExit(f"{name} must be true or false in 1Password")
    result[name] = value == "true"
try:
    result["omni_cert_valid_days"] = int(result["omni_cert_valid_days"])
    result["omni_etcd_endpoints"] = json.loads(result["omni_etcd_endpoints"])
except (TypeError, ValueError, json.JSONDecodeError) as exc:
    raise SystemExit("omni_cert_valid_days must be an integer and omni_etcd_endpoints must be JSON, for example []") from exc
if not isinstance(result["omni_etcd_endpoints"], list):
    raise SystemExit("omni_etcd_endpoints must be a JSON list")

json.dump(result, sys.stdout, indent=2)
sys.stdout.write("\n")
PY

mv "$temp_path" "$output_path"
trap - EXIT HUP INT TERM
echo "Rendered $output_path with mode 0600. It contains secrets; do not commit it."
