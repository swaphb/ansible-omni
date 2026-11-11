# Newt site with public resources

```mermaid
flowchart LR
  admin[Administrator browser]
  talos[Talos machines]

  subgraph pangolin[Pangolin server]
    ui[HTTPS resource\nomni.example.com]
    oidc[OIDC resource\nauth.example.com\nDex mode only]
    raw[Raw resources\nTCP 8090 / 8091 / 8100\nUDP 50180]
  end

  subgraph host[Omni host: no published backend ports]
    subgraph bridge[Private Docker bridge: omni-newt]
      newt[Newt site connector]
      omni[Omni\nomni:443, 8090, 8091, 8100, 50180]
      dex[Dex\ndex:5556\nDex mode only]
    end
  end

  admin -->|HTTPS 443| ui
  ui ==>|outbound Newt tunnel| newt
  newt -->|HTTPS| omni
  admin -->|OIDC HTTPS, if Dex| oidc
  oidc ==>|outbound Newt tunnel| newt
  newt -->|HTTPS| dex
  talos -->|TCP / UDP published on Pangolin| raw
  raw ==>|outbound Newt tunnel| newt
  newt -->|matching TCP / UDP target| omni
```

Newt makes an outbound connection; Omni and Dex have no published Docker ports
on the backend host. The HTTPS UI resource may use Pangolin authentication.
Raw TCP/UDP resources do not enforce Pangolin authentication and must not have
an interactive login policy in front of machine traffic.
