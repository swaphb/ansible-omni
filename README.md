# Self-hosted Sidero Omni with Ansible

This project deploys one self-hosted Sidero Omni instance on a Linux host, with
Dex OIDC, TLS, embedded etcd, and SQLite. It follows Sidero's
[on-prem guide](https://docs.siderolabs.com/omni/self-hosted/run-omni-on-prem)
and automates that setup with Ansible and Docker Compose.

> Omni uses the Business Source License. Sidero's documentation says
> self-hosting is available for non-production use, and production use requires
> a support contract. This repository does not bypass licensing. Read the
> [production vs non-production guidance](https://docs.siderolabs.com/omni/self-hosted/production-vs-non-production-use-under-the-business-source-license)
> and accept the applicable EULA before using Omni.

## What the role configures

- Docker Engine and Docker Compose v2 on Debian and Ubuntu when
  `omni_install_docker` is true
- A private root CA and a server certificate for Omni and Dex
- A persistent GPG key that encrypts data stored in etcd
- Dex with one local administrator account
- Omni with host networking, `/dev/net/tun`, and `NET_ADMIN`
- Persistent directories under `/opt/omni/data`
- Embedded etcd by default, or external etcd through variables
- A startup health check against the Omni UI

The role keeps existing PKI and the GPG encryption key on later runs. Back
them up. Losing `omni.asc` can make the datastore unrecoverable.

## Requirements

Control machine:

- Ansible Core 2.15 or newer
- SSH access to the target, and privilege escalation with `become` or sudo

Target host:

- A dedicated, internet-connected 64-bit Linux host
- Debian 12, or Ubuntu 22.04 or 24.04, when the role installs Docker.
  RHEL-family hosts work when Docker Engine and the Compose v2 plugin are
  already installed and `omni_install_docker` is false. Other distributions
  need that same manual Docker setup and package mappings in the role.
- At least 2 vCPUs and 4 GiB RAM. Add CPU and RAM when you run multiple clusters.
- Persistent disk for `/opt/omni`. The amount depends on how many machines and
  clusters you run.
- Working DNS and NTP, and outbound HTTPS and DNS to GHCR, GitHub, Sidero's
  Image Factory, and the Talos image and release endpoints.
- `/dev/net/tun` on the host. Containers and LXC guests get that device only if
  you pass it through.
- An IP address that administrators and every Talos machine Omni manages can
  reach. Do not advertise `127.0.0.1`, a Docker address, or a NAT address those
  machines cannot reach.

### Proxmox LXC (advanced)

Omni can run in an unprivileged Proxmox LXC when Docker nesting, `keyctl`, and
`/dev/net/tun` access are enabled. This is more operationally complex than a
small VM and is not the recommended production topology. The helper below must
run as root on a Proxmox VE host; it creates the LXC but does not install
Docker, because the role does that on Debian/Ubuntu by default.

```bash
scripts/create-proxmox-omni-lxc.sh \
  --ctid 120 \
  --template local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --ip 192.168.1.120/24 --gateway 192.168.1.1 \
  --ssh-keys /root/.ssh/authorized_keys
```

The LXC needs its own reachable network address. In direct mode, open the
required Omni ports to the LXC; in Newt mode it needs outbound reachability to
the Pangolin endpoint. The helper requires a current Proxmox release supporting
`pct set <CTID> --dev0 /dev/net/tun`.

Required inbound ports when Omni is published on the host. With Newt enabled,
publish these ports on the Pangolin server. The role does not publish them
on the Omni host.

| Port | Protocol | Purpose |
|---:|:---:|---|
| 443 | TCP | Omni UI and API |
| 5556 | TCP | Dex OIDC login |
| 8090 | TCP | SideroLink machine API |
| 8091 | TCP | machine event sink |
| 8100 | TCP | Kubernetes API proxy |
| 50180 | UDP | SideroLink WireGuard |

The role does not change the host firewall. Firewall tools and allowed source
networks differ by site. Restrict ports 443 and 5556 to administrator networks
where you can. Machines Omni manages must reach 8090, 8091, and 50180. Users
of the Kubernetes proxy must reach 8100. If the server is behind NAT, forward
these ports and set `omni_advertised_ip` to the externally reachable address.

You also need two names that resolve, such as `omni.home.example` and
`auth.home.example`. Point them at the target IP in direct mode, and at the
Pangolin server in Newt mode. Prefer split DNS. The role adds those names to
the server's `/etc/hosts`. Browsers and other clients still need DNS, or those
names in their hosts files.

## Quick start

1. Edit the inventory address, copy the example group variables, and edit them:

   ```bash
   cd ansible-omni
   $EDITOR inventory/hosts.yml
   cp group_vars/omni.yml.example group_vars/omni.yml
   $EDITOR group_vars/omni.yml
   ```

2. Set `omni_advertised_ip`, both endpoint names, and the administrator email.
   Set `omni_admin_password` to at least 12 characters and
   `omni_oidc_client_secret` to at least 24 characters. Generate the client
   secret with `openssl rand -hex 32`.

3. Encrypt the secrets file. Store the vault password where you can recover it:

   ```bash
   ansible-vault encrypt group_vars/omni.yml
   ```

4. Check connectivity, preview the changes, then deploy:

   ```bash
   ansible omni -m ping --ask-vault-pass
   ansible-playbook site.yml --ask-vault-pass --check --diff
   ansible-playbook site.yml --ask-vault-pass
   ```

The first run downloads large images and generates 4096-bit keys, so it can
take several minutes. Open `https://<omni_endpoint>` and log in with the
administrator email and password. If you left the EULA variables blank, the
UI asks the first user to accept the EULA.

## Store group variables in 1Password

The repository includes a bootstrap script that creates one Secure Note with
a field for every public `omni_*` role variable. Secret fields, including the
administrator password, OAuth secret, Newt secret, Pocket ID API key, and the
external etcd client key, are concealed fields. The bootstrap generates a
fresh administrator password and Omni OIDC client secret directly into the
item. Provider-issued values (Pocket ID API key, Pangolin/Newt secret, and
external etcd key) start empty for you to paste from those systems.

```bash
scripts/bootstrap-1password.sh --vault "Infrastructure" --item "ansible-omni"
cp group_vars/omni.1password.yml.example group_vars/omni.1password.yml
```

Dex is the default OIDC mode. For Pocket ID, initialize the item with the
matching mode; the generated `omni_oidc_client_secret` is suitable for the
Omni client that the optional Pocket ID bootstrap creates. Enter the existing
Pocket ID URL and API key before running the playbook.

```bash
scripts/bootstrap-1password.sh --vault "Infrastructure" --oidc-provider pocketid
```

Replace `<vault>` and `<item>` in `group_vars/omni.1password.yml`. The template
uses standard `op://vault/item/field` secret references, so the 1Password VS
Code extension can insert and manage each reference. This reference file is
safe to commit. Keep field names unchanged when rotating a value: the variable
name is the reference's field name.

Ansible does not resolve `op://` references itself. Immediately before a run,
render the one item locally. This writes the separate, mode-`0600`, Git-ignored
`group_vars/omni.yml` and preserves booleans, lists, and multiline PEM content:

```bash
scripts/render-1password-group-vars.sh --vault "Infrastructure" --item "ansible-omni"
ansible-playbook site.yml
```

For external etcd, enter `omni_etcd_endpoints` in 1Password as JSON, for
example `["https://etcd-1.internal:2379"]`. Do not run `op inject` directly
against the template for PEM fields: direct text substitution cannot safely
indent multiline certificates and keys. Use the render script instead.

## Trusting the generated CA

The role creates `/opt/omni/pki/ca.pem`. Copy that public certificate to each
administrator workstation. Do not copy `ca-key.pem`.

```bash
scp ubuntu@192.0.2.10:/opt/omni/pki/ca.pem ./omni-ca.pem
```

- On Debian or Ubuntu, copy it to
  `/usr/local/share/ca-certificates/omni-ca.crt` and run
  `sudo update-ca-certificates`.
- On RHEL or Fedora, copy it to
  `/etc/pki/ca-trust/source/anchors/omni-ca.crt` and run `sudo update-ca-trust`.
- On macOS, import it into the System keychain and mark it trusted.
- On Windows, import it into the local machine Trusted Root Certification
  Authorities store.

For a real internal domain, use a certificate from your internal or public CA
when clients already trust it. This role creates its own private CA. Add a
certificate-input mode to the role before you replace its files with
certificates you manage elsewhere. The server certificate must include both
endpoint DNS SANs and the relevant IP SANs.

## Important variables

| Variable | Default | Meaning |
|---|---|---|
| `omni_version` | `v1.13.3` | Pinned Omni image tag. Review the release notes before changing it. |
| `omni_dex_version` | `v2.46.1` | Pinned Dex image tag |
| `omni_endpoint` | `omni.internal` | Omni API and UI DNS name |
| `omni_auth_endpoint` | `auth.internal` | Dex issuer DNS name |
| `omni_advertised_ip` | host default IP | Address Talos machines use for WireGuard |
| `omni_private_ip` | host default IP | Extra IP SAN on the certificate |
| `omni_admin_password` | required | Initial Dex static-user password, at least 12 characters |
| `omni_oidc_client_secret` | required | Dex OAuth client secret, at least 24 characters |
| `omni_eula_name` and `omni_eula_email` | empty | Set both to accept the EULA during the playbook run |
| `omni_embedded_etcd` | `true` | Use the single-host embedded datastore |
| `omni_base_dir` | `/opt/omni` | Root for configuration and persistent data |
| `omni_newt_enabled` | `false` | Isolate services behind a Pangolin Newt connector |
| `omni_newt_version` | `1.20.1` | Pinned Newt container tag |
| `omni_newt_http2_enabled` | `false` | Build a pinned Newt derivative that proxies HTTPS resources with HTTP/2 support |
| `omni_newt_source_commit` | `745110e…c8e33d` | Exact Newt 1.20.1 source revision used by the HTTP/2 derivative |
| `omni_pangolin_subnet_router_enabled` | `false` | Run a Pangolin machine client as a subnet router on the Omni host |
| `omni_pangolin_machine_*` | empty | Pangolin machine-client endpoint, ID, and secret for the subnet router |
| `omni_oidc_provider` | `dex` | Bundled Dex, or an external Pocket ID server |

### Automated service updates

`.gitea/workflows/service-updates.yml` runs every Monday at 03:23 UTC and can
also be started manually from Gitea Actions. It discovers the newest stable
Omni, Dex, Newt, and Pangolin CLI releases, updates their pinned values and all
documented/default-value mirrors, validates the supported Compose variants,
pulls every image, and opens or refreshes the workflow-owned
`automation/service-updates` pull request. Review and merge that PR normally;
the workflow never commits directly to `main`.

Enable Gitea Actions for the repository and ensure its built-in
`GITEA_TOKEN` is allowed `contents: write` and `pull-requests: write`. The
runner needs Docker, Git, Python 3, and outbound access to GitHub, PyPI, Docker
Hub, GHCR, and public ECR. The workflow installs its pinned Ansible/Jinja/YAML
validation dependencies in a temporary virtual environment.

Newt is patch-gated because the optional Omni HTTP/2 derivative modifies
upstream source. Its version advances only when the release source can be
resolved to an immutable commit and `newt-http2.patch` applies cleanly. The
full Docker validation then runs the focused Newt test and build. If that gate
fails, the report records Newt as skipped while compatible updates for the
other services can still be proposed.

The role hashes the admin password with bcrypt, stores that hash in
`/opt/omni/secrets/admin-password.hash`, and writes the hash into the Dex
configuration. Ansible still receives the plaintext password. Changing the
inventory password does not rotate an existing hash. Delete that hash file and
rerun the playbook to rotate the password. Use Ansible Vault,
and keep playbook output private. Tasks that render secrets set `no_log`.

## Using an existing Pocket ID server

Set `omni_oidc_provider` to `pocketid` to skip the bundled Dex container and
use an existing Pocket ID server. Omni uses Pocket ID's discovery document and
the standard `openid`, `profile`, and `email` scopes.

### Automated client bootstrap

Pocket ID has an administrator REST API, so the role can create the OIDC
client on the first run. In Pocket ID, open Administration, then API Keys.
Create a narrowly scoped bootstrap key, copy it once, and vault it with the
other deployment secrets:

```yaml
omni_oidc_provider: pocketid
omni_pocketid_url: https://id.example.com
omni_pocketid_bootstrap: true
omni_pocketid_api_key: "{{ vault_pocketid_api_key }}"

# Stable values used by both Omni and Pocket ID.
omni_oidc_client_id: sidero-omni
omni_oidc_client_secret: "{{ vault_omni_oidc_client_secret }}"
omni_pocketid_client_name: Sidero Omni
omni_pocketid_skip_consent: false
```

The bootstrap registers this callback URL:

```text
https://<omni_endpoint>/oidc/consume
```

The role creates a confidential client and sets Omni's launch URL. The client
allows every Pocket ID user. The role installs the configured client secret
and deletes the secret Pocket ID created with the client. Only the secret
you set stays active. The role marks the API key `no_log` and does
not write the key into the Omni Compose project.

Bootstrap only creates a client:

- If the configured client ID does not exist, the role creates the client and
  adds the supplied secret.
- If that ID already exists, the role leaves its callback, access policy, and
  credentials as they are.
- Changing `omni_oidc_client_secret` later does not update the secret in Pocket
  ID.

After the first
successful run, set `omni_pocketid_bootstrap` to false. Remove the API key
from the deployment variables when you no longer need it, and revoke that key
in Pocket ID. Make later changes to the callback, group policy, and client
secret in Pocket ID.

A Pocket ID API key has the permissions of the administrator who created it.
See the [Pocket ID REST API documentation](https://pocket-id.org/docs/api)
and the [OIDC client setup guide](https://pocket-id.org/docs/setup/connect-an-app).

### Manual Pocket ID setup

To keep the Pocket ID API key out of Ansible, leave bootstrap disabled and
create the client in Administration, then OIDC Clients:

1. Create a confidential client and set the callback to
   `https://<omni_endpoint>/oidc/consume`.
2. Select the groups allowed to sign in, or allow all users.
3. Copy the client ID and the one-time client secret into
   `omni_oidc_client_id` and `omni_oidc_client_secret`.
4. Set `omni_pocketid_url` to Pocket ID's public issuer URL.

If Pocket ID uses a private CA, put that CA's public PEM chain in the vaulted
`omni_extra_ca_certificates` variable. The role appends it to Omni's trust
bundle. Do not put a private key in that variable.

`omni_admin_email` must match a Pocket ID user's `email` claim. Omni uses that
value as the initial user. Allow that user, or a Pocket ID group the user
belongs to, to use the client before you switch providers. Otherwise you can
lock yourself out.

## Optional Newt-only exposure

### Network diagrams

The supported network paths are documented as standalone Mermaid diagrams:

| Scenario | Diagram |
|---|---|
| Direct host exposure (Dex or Pocket ID) | [Direct exposure](docs/networking/direct-exposure.md) |
| Newt site with public HTTPS and raw machine resources | [Newt site and public resources](docs/networking/newt-site-and-public-resources.md) |
| Newt site with private resources consumed through the Pangolin CLI subnet router | [Newt site and private resources](docs/networking/newt-private-resources.md) |

Set `omni_newt_enabled` to true to run a Newt connector alongside Omni. The
role then makes these changes:

- Creates a Docker bridge named `omni-newt`.
- Attaches Omni, Dex, and Newt to that bridge.
- Removes host networking from Omni and the published port from Dex.
- Publishes no ports for Omni, Dex, or Newt on the backend host.
- Runs the playbook health check against Omni's address on that bridge.

Newt keeps an outbound tunnel open, so the backend host needs no inbound
firewall openings for Omni. Root and local Docker users can still reach
container addresses, as they can on any Docker bridge.

Create a Newt site in your Pangolin dashboard before you run the playbook, and
keep the generated ID and secret. Put these values in the vaulted group
variables:

```yaml
omni_newt_enabled: true
omni_newt_version: "1.20.1"
omni_newt_pangolin_endpoint: https://pangolin.example.com
omni_newt_id: site-id-from-pangolin
omni_newt_secret: "{{ vault_omni_newt_secret }}"
# Required for the Omni UI/API resource; see the HTTP/2 note below.
omni_newt_http2_enabled: true
omni_newt_source_commit: "745110e75fefd6139ada2895818d9a3529c8e33d"
```

The role writes a root-only Compose secret and starts `omni-newt`. Pangolin's
[Newt installation documentation](https://docs.pangolin.net/manage/sites/install-newt)
requires the endpoint, the site ID, and the site secret.

### Omni UI HTTP/2 support

Omni uses long-lived HTTP/2 API streams. Newt 1.20.1's private HTTPS handler
does not advertise HTTP/2 or enable it on its HTTPS upstream transport, which
can make the sign-in page load while the application itself times out or fails
to load assets. Set `omni_newt_http2_enabled: true` for the Omni site.

The role then builds a local, pinned derivative from the exact Newt 1.20.1
source commit with only three changes: it advertises `h2` and `http/1.1` over
TLS, enables Go's HTTP/2 server handler, and enables HTTP/2 on the HTTPS
upstream transport. The build runs on the Omni host and needs outbound access
to GitHub and Docker Hub/ECR for its source and builder images. It does not
change the Pangolin resource: keep the UI target at `https` and `omni:443`.
Review and update the pin and patch together when changing `omni_newt_version`.
The role intentionally permits a custom HTTP/2 build only for a version and
source revision listed in its tested compatibility map. The update workflow
maintains that map only after the patch gate succeeds.

### Optional Pangolin subnet router

Talos cannot run the Pangolin access client. If you want Talos machines to
reach Pangolin private resources, the role can run the official Pangolin CLI as
a machine client and subnet router. This is separate from Newt: Newt exposes
the Omni site to Pangolin, while the machine client consumes private resources
on behalf of devices routed through the Omni host.

Create a Machine Client in Pangolin, grant it access to the required private
host or CIDR resource, then vault its values:

```yaml
omni_pangolin_subnet_router_enabled: true
omni_pangolin_cli_version: "0.23.0"
omni_pangolin_machine_endpoint: https://pangolin.example.com
omni_pangolin_machine_id: machine-client-id-from-pangolin
omni_pangolin_machine_secret: "{{ vault_omni_pangolin_machine_secret }}"
```

The sidecar uses Pangolin CLI 0.23.0 or newer because subnet-router support
was introduced in CLI 0.18.0. It uses host networking, `NET_ADMIN`, and
`/dev/net/tun`; enabling it
changes routing and firewall behavior on the Omni host. It is only useful when
the Talos subnet routes Pangolin private-resource traffic through that host. If
the Omni host is not the Talos subnet's default gateway, add a static route on
that gateway for the private-resource CIDR, with the Omni host as next hop.
Pangolin warns that Docker forwarding rules can interfere with subnet routers;
configure Docker's `ip-forward-no-drop` setting on the host before enabling
this mode. The role intentionally does not modify `/etc/docker/daemon.json` or
the Talos network gateway.

For a Talos LAN at a different physical location, deploy the separate
[remote subnet-router Compose bundle](examples/pangolin-subnet-router/README.md)
on a Linux router at that location. The Omni-host sidecar cannot route traffic
from a remote LAN that does not use the Omni host as its next hop.

### Pangolin resources and targets

Starting Newt does not publish any Omni port. In Pangolin, create resources
for the Newt site and point them at these container DNS targets:

| Omni function | Protocol | Target | Notes |
|---|---|---|---|
| UI and API | HTTPS | `omni:443` | Use `omni_endpoint` as the public resource FQDN |
| Dex login | HTTPS or raw TCP | `dex:5556` | Required only with bundled Dex. Clients must reach `omni_auth_endpoint:5556`. |
| SideroLink API | Raw TCP | `omni:8090` | Map Pangolin server TCP 8090 |
| Event sink | Raw TCP | `omni:8091` | Map Pangolin server TCP 8091 |
| Kubernetes proxy | Raw TCP | `omni:8100` | Map Pangolin server TCP 8100 |
| SideroLink WireGuard | Raw UDP | `omni:50180` | Map Pangolin server UDP 50180 |

Set `omni_endpoint` and `omni_auth_endpoint` to names that resolve to the
Pangolin server. Set `omni_advertised_ip` to the Pangolin server's external
IP. Talos machines use that IP for UDP 50180. The certificate includes those
names, the advertised IP, and the private IP.

With Pocket ID, skip the Dex resource. Browsers and the Omni container both
need to reach Pocket ID at the issuer URL in `omni_pocketid_url`. Expose
Pocket ID with a separate Pangolin resource or another trusted route.

The UI resource can use Pangolin authentication and policy. Do not put an
interactive Pangolin login in front of the machine API, the event sink, the
Kubernetes proxy, or WireGuard. Talos and other native clients cannot complete
a browser login. Pangolin's documentation says public raw TCP and UDP
resources do not interpret the application protocol, and they do not enforce
Pangolin authentication. If those ports must stay off the public internet, use
Pangolin private host or CIDR access only when every client can use it, or
restrict source addresses on the Pangolin server. See Pangolin's
[raw TCP/UDP resource guidance](https://docs.pangolin.net/manage/resources/public/raw-resources).

On self-hosted Pangolin, raw resources also need `allow_raw_resources`,
matching Traefik entry points, Docker port mappings, and firewall openings on
the Pangolin server. Make those changes on the Pangolin server. This role does
not configure that server.

Confirm that the backend has no published ports and that Newt is healthy:

```bash
sudo docker compose -f /opt/omni/compose.yml ps
sudo docker network inspect omni-newt
sudo docker port omni       # expected: no output
sudo docker port dex        # expected: no output
sudo docker logs omni-newt
```

## External etcd

Use embedded etcd with one Omni process. For high availability, run external
etcd. A second Omni container does not provide high availability. Follow
Sidero's [external etcd guide](https://docs.siderolabs.com/omni/self-hosted/run-etcd-cluster-on-prem),
then set:

```yaml
omni_embedded_etcd: false
omni_etcd_endpoints:
  - https://10.0.0.11:2379
  - https://10.0.0.12:2379
  - https://10.0.0.13:2379
omni_external_etcd_ca: "{{ vault_etcd_ca }}"
omni_external_etcd_client_cert: "{{ vault_etcd_client_cert }}"
omni_external_etcd_client_key: "{{ vault_etcd_client_key }}"
```

Keep these values in Ansible Vault. The role writes them with mode `0600` and
disables embedded etcd.

## Operations

On the target:

```bash
cd /opt/omni
sudo docker compose ps
sudo docker compose logs -f omni
sudo docker compose logs -f dex
sudo docker compose pull
```

To upgrade, read the Omni release notes. Some releases require a matching
`omnictl` version. Change `omni_version` and rerun the playbook. Leave the
image tag pinned. Tracking `latest` makes rollback and compatibility harder.

Back up at least these paths:

- `/opt/omni/data/etcd`
- `/opt/omni/data/sqlite`
- `/opt/omni/secrets/omni.asc`
- `/opt/omni/pki`, in particular `ca-key.pem` and `server-key.pem`
- the vaulted inventory variables and the vault password

Stop the stack, or use Sidero's documented snapshot procedure, so the
datastore backup is consistent. Encrypt the backups and test a restore.

To inspect the deployment without printing secrets:

```bash
curl -kI https://127.0.0.1/
sudo docker compose -f /opt/omni/compose.yml ps
sudo ss -lntup | grep -E ':(443|5556|8090|8091|8100|50180)\\b'
```

Common failures:

- **Omni cannot start WireGuard.** `/dev/net/tun` is missing, or the hypervisor
  or container security policy blocks it.
- **Login redirect or certificate error.** The DNS names do not match
  `omni_endpoint` and `omni_auth_endpoint`, the workstation does not trust the
  CA, or the certificate was issued before a hostname change. Changing the
  endpoint variables regenerates the server certificate. Distribute the CA
  again only when the CA itself changes.
- **Machines do not connect.** Check NAT and firewall rules, TCP 8090 and 8091,
  UDP 50180, and whether machines can reach `omni_advertised_ip`.
- **Image pulls fail.** Check DNS, the system clock, outbound HTTPS, and
  registry proxy credentials or rate limits.

## Scope and security

This project deploys one host for non-production use. It does not provide high
availability. Dex keeps its static account in memory. On restart, Dex reloads
that account from disk. For a shared environment, connect Omni to your OIDC or
SAML identity provider, set an access policy, centralize backups and
monitoring, and use certificates from your existing PKI.

Keep the Compose file root-only. It contains the OIDC client secret. The role
sets sensitive files to mode `0600` and sensitive directories to mode `0700`.
Root and Docker administrators can still read those files. Treat Docker access
as root access.
