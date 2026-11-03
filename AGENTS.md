# AGENTS.md

## Repository purpose

This repository deploys a self-hosted Sidero Omni instance with Ansible and
Docker Compose. The default deployment uses bundled Dex authentication,
embedded etcd, SQLite, host networking, and role-generated TLS. Optional modes
support:

- an external Pocket ID OIDC provider;
- one-time Pocket ID client bootstrap through its REST API;
- a Pangolin Newt connector with an unpublished private Docker network; and
- external etcd with client-certificate authentication.

Read `README.md` before changing behavior. Keep implementation and operating
documentation synchronized.

## Repository layout

- `site.yml`: top-level playbook.
- `inventory/hosts.yml`: example inventory.
- `group_vars/omni.yml.example`: user-facing configuration example.
- `roles/omni/defaults/main.yml`: complete role defaults and public variables.
- `roles/omni/tasks/main.yml`: validation, PKI, identity bootstrap, deployment,
  and health checks.
- `roles/omni/templates/compose.yml.j2`: Docker Compose topology for all modes.
- `roles/omni/templates/dex.yaml.j2`: bundled Dex configuration.
- `roles/omni/templates/newt-config.json.j2`: Newt credential secret.
- `roles/omni/templates/openssl.cnf.j2`: server certificate SAN configuration.
- `roles/omni/handlers/main.yml`: stack restart handler.

## Supported deployment combinations

Changes must preserve all four primary combinations:

| OIDC provider | Exposure mode | Expected topology |
|---|---|---|
| Dex | Direct | Dex publishes 5556; Omni uses host networking |
| Dex | Newt | Dex, Omni, and Newt share `omni-newt`; no backend ports are published |
| Pocket ID | Direct | Dex is absent; Omni uses host networking |
| Pocket ID | Newt | Omni and Newt share `omni-newt`; Dex is absent and no backend ports are published |

Embedded etcd is the default in every combination. External etcd must continue
to mount its CA, client certificate, and client key without exposing them in
logs.

## Networking invariants

- Docker does not allow `network_mode: host` together with custom networks.
  Direct mode uses host networking; Newt mode uses the private bridge.
- Newt mode must not publish Omni or Dex ports on the backend host.
- In Newt mode, container DNS aliases must let Omni resolve the configured Dex
  endpoint locally.
- Omni requires `/dev/net/tun` and `NET_ADMIN` for SideroLink/WireGuard.
- Omni-managed machines need the SideroLink API, event sink, and WireGuard
  paths. Do not document the browser UI as the only required Pangolin resource.
- Pangolin raw TCP/UDP resources do not provide Pangolin authentication. Keep
  this warning in the README whenever raw-resource guidance is present.
- `omni_advertised_ip` must represent the address Talos machines can reach for
  UDP 50180. In Newt mode this is normally the Pangolin server's public IP.

## Authentication invariants

- `omni_oidc_provider` accepts only `dex` or `pocketid`.
- Dex is the default and must remain usable without Pocket ID variables.
- Pocket ID mode must not render or start Dex.
- The Omni callback URL is exactly:
  `https://<omni_endpoint>/oidc/consume`.
- Pocket ID bootstrap is create-only. It must not overwrite an existing
  client's callbacks, access rules, or credentials.
- When bootstrap creates a Pocket ID client, remove Pocket ID's initial
  generated secret after installing the configured secret.
- Pocket ID API keys and all client secrets must use `no_log: true` in tasks.
- `omni_admin_email` is passed as Omni's initial user and must match the OIDC
  provider's email claim.

## Secrets and persisted state

Never commit real credentials. `group_vars/omni.yml` is intentionally ignored;
users should encrypt it with Ansible Vault.

Treat these as sensitive:

- `omni_oidc_client_secret`;
- `omni_admin_password` and its persisted bcrypt hash;
- `omni_newt_secret`;
- `omni_pocketid_api_key`;
- external etcd client keys;
- `/opt/omni/secrets/omni.asc`;
- all private keys under `/opt/omni/pki`; and
- rendered Compose and identity-provider configuration.

Tasks that accept, render, register, or copy secret material must use
`no_log: true`. Keep sensitive files at mode `0600` and secret directories at
mode `0700`. Do not print rendered Compose, Dex, Newt, or API response content
in validation output.

The GPG key, CA, server keys, etcd data, and SQLite data are persistent state.
Do not regenerate or delete them during routine convergent runs. Destructive
migration or rotation behavior requires explicit user opt-in and documented
backup/recovery steps.

## Ansible conventions

- Use fully qualified collection names such as `ansible.builtin.copy`.
- Prefer built-in modules over shell commands. Use `command` instead of `shell`
  unless pipes, redirection, or shell expansion are required.
- Make tasks idempotent with module state, `creates`, explicit checks, or
  accurate `changed_when` conditions.
- Quote file modes as strings, for example `"0600"`.
- Validate required variables early with `ansible.builtin.assert`.
- Pin container versions in defaults. Do not silently switch to `latest`.
- Add new public variables to defaults, the example group variables when
  appropriate, and the README variable or feature documentation.
- Preserve compatibility with Ansible Core 2.15 or newer.
- Automatic Docker installation supports Debian/Ubuntu. RHEL-family targets
  require a preinstalled Docker Engine and Compose v2.

## Editing guidelines

- Use `apply_patch` for repository edits.
- Preserve unrelated user changes and do not rewrite vaulted or generated
  deployment files.
- Do not add generated certificates, keys, API responses, inventory secrets, or
  runtime data to the repository.
- Keep Jinja conditionals aligned so the rendered YAML remains readable.
- Escape literal dollar signs only where Docker Compose performs interpolation.
  Files mounted into containers, such as `dex.yaml`, are not interpolated by
  Compose.
- When changing endpoint names or TLS behavior, verify certificate SANs,
  advertised URLs, OIDC issuer URLs, and callback URLs together.

## Required validation

For every change:

1. Parse every static YAML file.
2. Run `ansible-playbook --syntax-check site.yml` when Ansible is installed.
3. Render and parse `compose.yml.j2` for all four Dex/Pocket ID and
   direct/Newt combinations.
4. If etcd behavior changes, render both embedded and external etcd variants.
5. Confirm Newt variants contain no `ports` entry for Omni or Dex.
6. Confirm Pocket ID variants contain no Dex service.
7. Check that no secret value appears in command output or committed files.

A lightweight Compose-render validation can use Python, Jinja2, and PyYAML.
When manually constructing the Jinja environment, provide equivalents for
Ansible filters used by the template, including `to_json` and `regex_replace`.
Prefer actual `ansible-playbook --syntax-check` and `docker compose config`
when those tools are available.

Do not claim live deployment, Pocket ID bootstrap, Pangolin connectivity, or
container health was tested unless it was exercised against real services.
Clearly distinguish static rendering/syntax validation from integration tests.

## Documentation and upstream references

This project follows upstream behavior rather than inventing incompatible
configuration. For changes involving current flags, endpoints, licensing,
ports, or API schemas, verify the latest official documentation:

- Sidero Omni on-prem documentation:
  `https://docs.siderolabs.com/omni/self-hosted/run-omni-on-prem`
- Pocket ID API and OIDC documentation:
  `https://pocket-id.org/docs/api`
- Pangolin Newt installation documentation:
  `https://docs.pangolin.net/manage/sites/install-newt`
- Pangolin raw-resource documentation:
  `https://docs.pangolin.net/manage/resources/public/raw-resources`

Keep the licensing language accurate: this repository does not bypass Sidero's
license. Non-production self-hosting and production licensing requirements must
continue to be described according to Sidero's current terms.
