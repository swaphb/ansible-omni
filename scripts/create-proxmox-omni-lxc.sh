#!/usr/bin/env bash
# Create a Proxmox VE LXC suitable for this repository's Docker-based Omni role.
# Run on the Proxmox host as root. Requires Proxmox VE with `pct --dev0` support.

set -Eeuo pipefail

ctid="8000"
template="ISOs:vztmpl/ubuntu-26.04-standard_26.04-1_amd64.tar.zst"
storage="pve1_nvme"
bridge="vmbr0"
hostname="omni"
ip="dhcp"
gateway=""
cores="2"
memory="4096"
swap="512"
disk_gib="32"
ssh_keys="./ssh-pub-key.pub"

usage() {
  cat <<'USAGE'
Usage:
  sudo scripts/create-proxmox-omni-lxc.sh \
    --ctid 120 \
    --template local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
    --ip 192.168.1.120/24 --gateway 192.168.1.1

Required:
  --ctid ID                 Unused numeric Proxmox CT ID.
  --template STORAGE:PATH   Downloaded Debian or Ubuntu LXC template.

Optional:
  --storage NAME            Rootfs storage (default: local-lvm).
  --bridge NAME             Proxmox network bridge (default: vmbr0).
  --hostname NAME           Container hostname (default: omni).
  --ip CIDR|dhcp            Container IP configuration (default: dhcp).
  --gateway IP              Required when --ip is static.
  --cores N                 vCPUs (default: 2).
  --memory MIB              RAM in MiB (default: 4096).
  --swap MIB                Swap in MiB (default: 512).
  --disk-gib N              Rootfs size in GiB (default: 32).
  --ssh-keys PATH           Public-key file passed to pct at creation.
USAGE
  exit 2
}

while (($#)); do
  case "$1" in
    --ctid) ctid=${2:?}; shift 2 ;;
    --template) template=${2:?}; shift 2 ;;
    --storage) storage=${2:?}; shift 2 ;;
    --bridge) bridge=${2:?}; shift 2 ;;
    --hostname) hostname=${2:?}; shift 2 ;;
    --ip) ip=${2:?}; shift 2 ;;
    --gateway) gateway=${2:?}; shift 2 ;;
    --cores) cores=${2:?}; shift 2 ;;
    --memory) memory=${2:?}; shift 2 ;;
    --swap) swap=${2:?}; shift 2 ;;
    --disk-gib) disk_gib=${2:?}; shift 2 ;;
    --ssh-keys) ssh_keys=${2:?}; shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown argument: $1" >&2; usage ;;
  esac
done

[[ $EUID -eq 0 ]] || { echo "Run this script as root on the Proxmox host." >&2; exit 1; }
command -v pct >/dev/null || { echo "This must run on a Proxmox VE host with pct installed." >&2; exit 1; }
[[ $ctid =~ ^[0-9]+$ ]] || { echo "--ctid must be numeric." >&2; exit 2; }
[[ -n $template ]] || usage
[[ $ip == dhcp || -n $gateway ]] || { echo "--gateway is required with a static --ip." >&2; exit 2; }
[[ -c /dev/net/tun ]] || { echo "The Proxmox host has no /dev/net/tun device." >&2; exit 1; }
if pct status "$ctid" >/dev/null 2>&1; then
  echo "CT $ctid already exists; refusing to modify it." >&2
  exit 1
fi
if [[ -n $ssh_keys && ! -r $ssh_keys ]]; then
  echo "Cannot read --ssh-keys file: $ssh_keys" >&2
  exit 2
fi

net0="name=eth0,bridge=${bridge},ip=${ip},type=veth"
if [[ $ip != dhcp ]]; then
  net0+=",gw=${gateway}"
fi

pct_args=(
  create "$ctid" "$template"
  --arch amd64
  --hostname "$hostname"
  --cores "$cores"
  --memory "$memory"
  --swap "$swap"
  --rootfs "${storage}:${disk_gib}"
  --net0 "$net0"
  --unprivileged 1
  --features nesting=1,keyctl=1
  --onboot 1
  --start 0
)
if [[ -n $ssh_keys ]]; then
  pct_args+=(--ssh-public-keys "$ssh_keys")
fi

pct "${pct_args[@]}"

# Omni's Docker container needs this device for SideroLink/WireGuard. On
# current Proxmox releases, --dev0 creates the constrained device mount.
if ! pct set "$ctid" --dev0 /dev/net/tun; then
  echo "Failed to pass /dev/net/tun into CT $ctid." >&2
  echo "Delete the incomplete CT or configure TUN manually before starting it." >&2
  exit 1
fi

pct start "$ctid"
pct exec "$ctid" -- test -c /dev/net/tun

cat <<EOF
Created and started unprivileged CT $ctid ($hostname).

Next steps:
  1. Ensure SSH access for Ansible (supply --ssh-keys or configure it through
     the console) and set the CT address in inventory/hosts.yml.
  2. Run this repository's playbook. It installs Docker on Debian/Ubuntu when
     omni_install_docker=true.
  3. In direct mode, allow the Omni machine-facing ports through the CT and
     upstream firewall. In Newt mode, the CT still needs outbound connectivity
     to the Pangolin endpoint.
EOF
