#!/usr/bin/env bash
# Create the non-root SSH account used to run this repository's Ansible playbook.
# Run inside the Omni target LXC as root after its root authorized_keys exists.

set -Eeuo pipefail

username="ansible"
authorized_keys_source="/root/.ssh/authorized_keys"

usage() {
  cat <<'USAGE'
Usage:
  sudo scripts/create-omni-ansible-user.sh [OPTIONS]

Create a non-root account with passwordless sudo for the ansible-omni
playbook. The account receives a copy of root's SSH authorized_keys file on
first creation, so the same SSH key can authenticate as both users.

Options:
  --user NAME                Account name (default: ansible).
  --authorized-keys PATH     Public-key file to install (default:
                              /root/.ssh/authorized_keys).
  -h, --help                 Show this help text.
USAGE
}

while (($#)); do
  case "$1" in
    --user) username=${2:?}; shift 2 ;;
    --authorized-keys) authorized_keys_source=${2:?}; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ $EUID -eq 0 ]] || { echo "Run this script as root inside the LXC." >&2; exit 1; }
[[ $username =~ ^[a-z_][a-z0-9_-]*\$?$ ]] || {
  echo "--user must be a valid Linux account name." >&2
  exit 2
}
[[ -r $authorized_keys_source ]] || {
  echo "Cannot read authorized-key file: $authorized_keys_source" >&2
  exit 2
}

if ! command -v sudo >/dev/null; then
  command -v apt-get >/dev/null || {
    echo "sudo is not installed and this host has no apt-get; install sudo first." >&2
    exit 1
  }
  apt-get update
  apt-get install -y sudo
fi

getent group sudo >/dev/null || {
  echo "The sudo group does not exist on this host." >&2
  exit 1
}

if id "$username" >/dev/null 2>&1; then
  echo "User '$username' already exists; preserving the existing account."
else
  adduser --disabled-password --gecos "" "$username"
fi
usermod -aG sudo "$username"

user_group=$(id -gn "$username")
user_home=$(getent passwd "$username" | cut -d: -f6)
ssh_dir="$user_home/.ssh"
user_authorized_keys="$ssh_dir/authorized_keys"

install -d -m "0700" -o "$username" -g "$user_group" "$ssh_dir"
if [[ ! -e $user_authorized_keys ]]; then
  install -m "0600" -o "$username" -g "$user_group" \
    "$authorized_keys_source" "$user_authorized_keys"
else
  echo "Preserving existing authorized keys: $user_authorized_keys"
fi

sudoers_file="/etc/sudoers.d/$username"
sudoers_tmp=$(mktemp)
trap 'rm -f "$sudoers_tmp"' EXIT
printf '%s ALL=(ALL) NOPASSWD: ALL\n' "$username" >"$sudoers_tmp"
chmod "0440" "$sudoers_tmp"
visudo -cf "$sudoers_tmp" >/dev/null
install -m "0440" "$sudoers_tmp" "$sudoers_file"

echo "Created or updated '$username'."
echo "Test it with: ssh $username@<lxc-ip> 'sudo -n whoami'"
