# Direct exposure

```mermaid
flowchart LR
  admin[Administrator browser / Omni CLI]
  talos[Talos machines]
  pocket[Pocket ID issuer\noptional]

  subgraph host[Omni host]
    omni[Omni\nhost network]
    dex[Dex\nport 5556\nDex mode only]
  end

  admin -->|HTTPS 443| omni
  admin -->|OIDC HTTPS 5556| dex
  omni -->|OIDC HTTPS 5556| dex
  admin -->|OIDC HTTPS| pocket
  omni -->|OIDC HTTPS| pocket
  talos -->|TCP 8090 API\nTCP 8091 event sink\nTCP 8100 Kubernetes proxy\nUDP 50180 WireGuard| omni
```

The Dex paths apply only when `omni_oidc_provider: dex`; the Pocket ID paths
apply only when `omni_oidc_provider: pocketid`. In this mode Omni uses host
networking, so the host firewall and any upstream NAT expose the required
ports directly.
