# Newt site with Pangolin private resources

```mermaid
flowchart LR
  admin[Administrator browser\nwith Pangolin access client]
  talos[Talos machines]
  gateway[Talos LAN gateway]

  subgraph pangolin[Pangolin]
    resource[Private Host or CIDR resource\nprivate-resource CIDR]
    control[Dashboard / control endpoint]
  end

  subgraph host[Omni host]
    router[Pangolin CLI machine client\nsubnet router\nhost network + TUN]
    subgraph bridge[Private Docker bridge: omni-newt]
      newt[Newt site connector]
      omni[Omni]
    end
  end

  admin -->|authenticated private-resource traffic| resource
  gateway -->|static route: private-resource CIDR\nnext hop = Omni host LAN IP| router
  talos --> gateway
  router ==>|Pangolin client tunnel| resource
  control -.->|machine ID + secret\ninstalls authorized routes| router
  resource ==>|Newt tunnel, when target is Omni site| newt
  newt --> omni
```

The Pangolin CLI sidecar is a **consumer** of private resources, not another
Newt connector. Pangolin supplies routes for resources the machine client may
access. The LAN gateway must route the private-resource CIDR to the Omni host's
normal LAN address; it is not configured through `omni_advertised_ip`.
