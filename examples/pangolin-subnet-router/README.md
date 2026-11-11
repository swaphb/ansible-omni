# Remote Pangolin subnet router

This Compose bundle runs a Pangolin **machine client** as a subnet router for
one remote Talos LAN. It is not a reverse proxy and it is not a Newt site
connector: it forwards traffic from Talos nodes to Pangolin private resources.

Use one dedicated Linux VM, LXC, or small host on each remote Talos network.
It needs outbound access to the Pangolin endpoint, a fixed LAN address, Docker
Compose v2, and `/dev/net/tun`.

The bundle pins Pangolin CLI 0.18.1. Subnet-router support was introduced in
CLI 0.18.0, so do not substitute an earlier image tag.

## Configure and start

1. In Pangolin, create a Machine Client for this remote location. Grant it
   access to the private Omni Host or CIDR resource.

2. Copy the secret template and fill in the endpoint, machine-client ID, and
   secret. Keep the resulting file local:

   ```bash
   cp router.env.example router.env
   chmod 0600 router.env
   $EDITOR router.env
   ```

3. Docker must not install a forwarding rule that drops router traffic. Merge
   this setting into `/etc/docker/daemon.json` on the router host, then restart
   Docker:

   ```json
   {
     "ip-forward-no-drop": true
   }
   ```

4. Start the client:

   ```bash
   docker compose up -d
   docker compose logs -f pangolin-subnet-router
   ```

The Pangolin CLI enables forwarding and creates its temporary NAT/firewall
rules while it runs. Verify them with:

```bash
sudo nft list table ip olm_subnet_router
```

## Route the Talos network

On the remote LAN's default gateway, create a route for the private Omni
resource address (or the complete Pangolin resource CIDR) through this router.
For example, if this router is `192.168.50.10` and the private Omni address is
`100.96.128.24`:

```text
destination: 100.96.128.24/32
next hop:    192.168.50.10
```

If you cannot change the LAN gateway, add the equivalent route to every Talos
machine configuration under `machine.network.interfaces[].routes`.

Talos also needs DNS for `omni.private.swaphb.com` resolving to
`100.96.128.24`. Use internal DNS, or an explicit Talos host entry. Do not
route the entire `100.64.0.0/10` range unless Pangolin assigned and you intend
to use that whole range; it can overlap with other overlay networks.

## Security notes

- `router.env` contains a machine-client secret and is intentionally ignored.
- The router forwards only Pangolin private resources granted to its machine
  client.
- Configure the Omni resource as a private Host or CIDR resource, not as
  private HTTPS only, so TCP 8090/8091/8100 and UDP 50180 can traverse it.
- Keep the router host patched and restrict administrative access to it.
