# Deploying herdr-mcp

herdr-mcp must run on the machine where the herdr server runs. It reaches herdr through herdr's Unix
socket. The herdr CLI in the image must have the same version as the herdr server on the host.

Every setting comes from an environment variable. `HERDR_MCP_TOKEN` is required in every setup.
Generate one with Python 3 and keep it in the shell.

```sh
export HERDR_MCP_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

## Before you start

Get read access to the repository from its owner and clone it. Every path below starts from that
checkout. Choose a hostname in your Cloudflare zone for the public path. `mcp.example.com` stands for
that hostname everywhere below. Each path needs its own tools.

- On a Mac, you need `uv` and a herdr CLI of the same version as the running herdr server.
- On Coolify, you need a Coolify server whose webhook endpoint GitHub can reach, a Cloudflare zone
  and a copy of the repository that you can push to in your own GitHub account. The certificate
  install needs root on the server, so arrange that step with the server's administrator if you
  lack it.
- On any other Linux server, you need a local Docker daemon and permission to run `docker` as the
  user that runs herdr.

The herdr CLI talks to the herdr server through a Unix socket, by default
`~/.config/herdr/herdr.sock`. A Unix socket cannot cross machines.

The socket has mode 0600. herdr-mcp must run as the user that owns the herdr server. Run `id -u` and
`id -g` as that user to print the uid and gid that a container needs.

A native herdr-mcp inherits `HERDR_SOCKET_PATH` from its shell. Every herdr pane sets that variable,
and it takes precedence over `HERDR_SESSION`. A native herdr-mcp started inside a herdr pane
therefore reports that pane's session.

The container reads only `/herdr/herdr.sock`, which is `herdr.sock` in the mounted directory. Check
that `~/.config/herdr/herdr.sock` exists before you start the container.

Agent names are global per herdr server. Two repositories on one server cannot both name an agent
`worktree-1`. Give every agent a name that is unique on the server.

`herdr status` prints the running server's version under `server:`. `herdr --version` prints the
installed binary's version. The installed binary can be newer than the running server until herdr
restarts. The herdr CLI that herdr-mcp runs must match the server version. [Upgrading
herdr](#upgrading-herdr) explains how to match them.

## On a Mac

Docker Desktop on macOS does not pass a Unix socket through reliably. herdr-mcp therefore runs
natively next to herdr on the Mac.

1. Install it from the checkout with `uv tool install .`.
2. If uv warns that its tool directory is not on your path, run `uv tool update-shell`. Then open a
   new shell and export `HERDR_MCP_TOKEN` there again.
3. Start it with `herdr-mcp` in the shell that holds `HERDR_MCP_TOKEN`.

By default the server listens on `127.0.0.1:8765`. It reaches the herdr server through the socket
that the herdr CLI selects in that shell.

The Mac setup serves MCP clients on the same Mac. Grok needs the public path, which this guide covers
for a Linux server only.

## On Coolify

Coolify builds the image from `Dockerfile` on the server and runs it with
`docker-compose.coolify.yaml`. Every push to `main` triggers a new build and deploy through
Coolify's GitHub App source.

The Compose file mounts the herdr socket directory read-only at `/herdr`. The read-only mount is
enough for herdr-mcp. Coolify connects Traefik to the application's Compose network, so the Compose
file publishes no port. On the first deployment, Coolify held port 8000, so herdr-mcp listens on
8765.

Create the resource with these steps.

1. In your copy of the repository, edit `docker-compose.coolify.yaml`. Set the `user` line to the uid
   and gid of the user that runs herdr, such as `"1000:1000"`. Set the mount source to that user's
   `.config/herdr` directory as an absolute path. Push the change to `main`.
2. Set up the HTTPS dashboard hostname in [Coolify webhook over
   HTTPS](#coolify-webhook-over-https) first, because the GitHub App records its webhook URL
   when you create it. Then create a GitHub App source in Coolify with [Coolify's GitHub App
   guide](https://coolify.io/docs/applications/sources/github/app). Give it access to your copy of
   the repository.
3. Add a new resource from the GitHub App source. Pick your copy of the repository and select the
   `main` branch.
4. Select the Docker Compose build pack. The Dockerfile build pack ignores the Compose file's `user`
   line and socket mount.
5. Set **Base Directory** to `/` and **Docker Compose Location** to `/docker-compose.coolify.yaml`.
6. Check that **Advanced > Deployment > Auto deploy** is set to **Deploy on push (webhooks)**. A
   GitHub App resource has this setting by default.
7. Set the service's domain to `https://mcp.example.com:8765`. The port tells Traefik which
   container port receives the request. Coolify can warn "Unrecognized internal port" before the
   first build. The warning is harmless. Coolify can also warn that the domain's DNS does not point
   at the server yet. Recheck the domain after step 10 publishes the DNS record.
8. Remove the `www.` copy of the domain that Coolify adds under **Public access**.
9. Set `HERDR_MCP_TOKEN` and `HERDR_MCP_PUBLIC_HOST=mcp.example.com` under **Environment
   Variables**. Coolify refuses to deploy while either is empty.
10. Follow [Expose it through one public path](#expose-it-through-one-public-path) for the
    firewall, the certificate and the DNS record.
11. Deploy. Then run the origin certificate check at the end of [Expose it through one public
    path](#expose-it-through-one-public-path).
12. Push any commit to `main`. Check that GitHub shows a successful webhook delivery and that
    Coolify starts a new deployment.

Coolify's proxy files under `/data/coolify/proxy/` belong to root. Run herdr-mcp as a Coolify
resource, and Coolify writes its Traefik route.

## On any other Linux server

Build the image from `Dockerfile` and run it next to herdr. herdr publishes Linux binaries for
`x86_64` and `aarch64`, so the image builds on those two architectures. Run the commands in the
checkout, as the user that runs herdr. Set `HERDR_MCP_PUBLIC_HOST` to the public hostname, such as
`mcp.example.com`, in the shell that holds `HERDR_MCP_TOKEN`.

```sh
docker build -t herdr-mcp .
docker run -d --name herdr-mcp --restart unless-stopped \
  --user "$(id -u):$(id -g)" \
  -v "$HOME/.config/herdr:/herdr:ro" \
  -e HERDR_MCP_TOKEN="$HERDR_MCP_TOKEN" \
  -e HERDR_MCP_PUBLIC_HOST="$HERDR_MCP_PUBLIC_HOST" \
  -p 127.0.0.1:8765:8765 \
  herdr-mcp
```

Run the HTTPS reverse proxy on the host, and forward the public hostname to `127.0.0.1:8765`.

A reverse proxy in its own container network cannot reach the host's `127.0.0.1`. Put both
containers on one user-defined Docker network. Docker resolves container names only on such a
network. Set `PROXY_NETWORK` to the network that the proxy container joins. Replace the `-p` line
with this line.

```sh
  --network "$PROXY_NETWORK" \
```

Point the proxy at the upstream `http://herdr-mcp:8765`.

In both setups the proxy forwards the public Host header unchanged. Then follow [Expose it through
one public path](#expose-it-through-one-public-path).

## Expose it through one public path

Grok's custom connectors call herdr-mcp from xAI's servers. herdr-mcp therefore needs a public HTTPS
URL that ends in `/mcp`, such as `https://mcp.example.com/mcp`.

The recommended path has three hops. The proxied DNS record resolves to Cloudflare. Cloudflare
forwards each request to the origin. A reverse proxy on the server, such as Coolify's Traefik,
forwards it to the herdr-mcp container. The container answers it.

The public path must meet three requirements. Each vendor's own guide gives the steps.

1. Cloudflare is the only public way in to the MCP endpoint. A firewall at the hosting provider accepts ports 80 and 443
   only from [Cloudflare's IP ranges](https://www.cloudflare.com/ips/). UFW on the server does not
   filter ports that Docker publishes, as [Docker's firewall
   documentation](https://docs.docker.com/engine/network/packet-filtering-firewalls/) explains. The
   first deployment used a [Hetzner Cloud
   Firewall](https://docs.hetzner.com/cloud/firewalls/getting-started/creating-a-firewall/).
2. The reverse proxy presents a certificate for the hostname that [Full
   (strict)](https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/full-strict/)
   accepts. The first deployment used a Cloudflare Origin CA certificate. Create one with
   [Cloudflare's Origin CA guide](https://developers.cloudflare.com/ssl/origin-configuration/origin-ca/),
   and skip that guide's step for the SSL/TLS mode. On Coolify, install it on Traefik with
   [Coolify's custom certificate
   guide](https://coolify.io/docs/core/networking/proxy/traefik/custom-ssl-certs). Do that guide's
   file and Dynamic Configuration steps before you publish the DNS record. Its verification step
   needs the public hostname, so run the origin check below after the deploy instead. With any
   other reverse proxy, load the certificate for the hostname as that proxy's documentation
   describes.
3. Cloudflare's encryption mode for the hostname is **Full (strict)**. When other hostnames share
   the zone, set it for this hostname alone with a [Configuration
   Rule](https://developers.cloudflare.com/rules/configuration-rules/settings/#ssl). The
   **Flexible** mode loops on Coolify's HTTPS redirect.

Keep an administrator path open. Add a rule that allows SSH from your own address or a private
network such as Tailscale. On Coolify, add the same rule for the dashboard port, 8000 by default.
Narrow or remove every other allow rule for the dashboard port, in every firewall attached to the
server. Apply the firewall. Then open a fresh SSH session to confirm that SSH still works. On Coolify,
reload the dashboard through the administrator path to confirm that it still works.

Check requirement 1 before you publish the DNS record. Open every firewall that applies to the
server in the provider's console. Hetzner combines the allow rules of all attached firewalls, as its
[firewall FAQ](https://docs.hetzner.com/cloud/firewalls/faq/) states. Confirm that ports 80 and 443
accept only Cloudflare's ranges, for every public IPv4 and IPv6 address of the server. On Coolify,
confirm that the dashboard port accepts only your administrator sources.

### Coolify webhook over HTTPS

On Coolify, the firewall also blocks GitHub's webhook deliveries to the dashboard port. GitHub
reaches Coolify through Cloudflare over HTTPS instead. This route makes the dashboard's login page
publicly reachable through Cloudflare. Set this up before you create the GitHub App,
because the app records its webhook URL when you create it.

1. Choose a dashboard hostname, such as `coolify.example.com`. Point a proxied Cloudflare DNS record
   for it at the server.
2. Open **Servers > localhost > Proxy** in Coolify. A fresh install has no running proxy. Select
   Traefik and click **Start Proxy** if the proxy is stopped.
3. Install a certificate for the dashboard hostname on Traefik, as requirement 2 describes for the
   MCP hostname. Set **Full (strict)** for the dashboard hostname, as requirement 3 describes.
   [Coolify's Cloudflare guide](https://coolify.io/docs/integrations/security/cloudflare/ddos-protection)
   covers the dashboard setup.
4. Set `https://coolify.example.com` as **URL** in Coolify's [instance
   settings](https://coolify.io/docs/core/instance-management/instance-settings).
5. Open `https://coolify.example.com` in a browser. The dashboard must load over HTTPS.
6. When you create the GitHub App, choose **Use a custom endpoint**. Enter
   `https://coolify.example.com` as the base URL. Cloudflare's proxy does not forward port 8000.

The first deployment allowed GitHub's webhook IP ranges on port 8000 instead. That path sends
payloads over plain HTTP, so this guide does not use it. Coolify step 12 confirms a delivery
afterwards. A Cloudflare Access policy on the dashboard hostname must let the GitHub App's webhook
through.

Then create a proxied DNS record for `mcp.example.com` that points at the server, as [Cloudflare's
DNS guide](https://developers.cloudflare.com/dns/manage-dns-records/how-to/create-dns-records/)
describes.

After the deploy, check the origin certificate on the server itself. A check through the public
hostname shows Cloudflare's edge certificate instead. Replace `127.0.0.1` with the proxy's listen
address when the proxy binds one interface only.

```sh
openssl s_client -connect 127.0.0.1:443 -servername mcp.example.com </dev/null 2>/dev/null \
  | openssl x509 -noout -issuer -ext subjectAltName -dates -checkhost mcp.example.com
```

The output must meet three conditions. The issuer names Cloudflare's Origin CA when you use an
Origin CA certificate. The current UTC time falls between the `notBefore` and `notAfter` dates.
The last line reads as follows.

```text
Hostname mcp.example.com does match certificate
```

When the reverse proxy runs in a container, run herdr-mcp as a container on the proxy's network. On
the first deployment, a host process behind Coolify's Traefik timed out. UFW dropped the traffic
from Coolify's bridge networks to the host. Traefik answered 504 after 30 seconds.

Set `HERDR_MCP_PUBLIC_HOST` to the public hostname. The MCP SDK answers 421 to a Host header outside
its allowed list. The list holds the loopback hosts and `HERDR_MCP_PUBLIC_HOST`.

Private access over Tailscale needs no public path. A DNS-only hostname that points at a Tailscale
address cannot pass Let's Encrypt's HTTP challenge. Its certificate needs the [DNS-01
challenge](https://letsencrypt.org/docs/challenge-types/), such as Traefik with a Cloudflare API
token.

## Connect Grok

Check the public endpoint before you add the connector. A request without the token returns `401`.

```sh
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://mcp.example.com/mcp
```

An `initialize` request with the token prints a JSON result whose `serverInfo.name` is `herdr`. The
status code `200` follows it.

```sh
curl -s -w '\n%{http_code}\n' -X POST https://mcp.example.com/mcp \
  -H "Authorization: Bearer $HERDR_MCP_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
```

Add the connector.

1. Open [grok.com/connectors](https://grok.com/connectors) and choose **New Connector**, then
   **Custom**.
2. Enter `https://mcp.example.com/mcp` as the server URL.
3. Add the header `Authorization` with the value `Bearer <token>`. `<token>` is the value of
   `HERDR_MCP_TOKEN`.
4. Ask Grok what your herdr agents are doing. Compare the answer with an agent that you see in herdr.

The two probes never touch the herdr socket. On the first deployment, Grok showed the tool as
`herdr_mcp___list_agents`.

On the first deployment, a connector added at grok.com also worked in the Grok mobile app. Grok in a
car has no recorded test yet.

On 2026-11-20, at least 15 public repositories shared the name herdr-mcp. This project is the
repository `dexpetkovic/herdr-mcp`. Its MCP server name is `herdr`. Its tools are `list_agents`,
`get_agent_activity` and `send_message`. The server sends instructions on `initialize` that tell
the client to answer from this live server. I have yet to verify whether Grok follows those instructions.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| A request that sends the token gets `401`. | The `Authorization` header is missing or carries another token. | Send `Authorization: Bearer <token>` with the exact value of `HERDR_MCP_TOKEN`. |
| A request gets `421`. | The Host header is neither a loopback host nor `HERDR_MCP_PUBLIC_HOST`. | Set `HERDR_MCP_PUBLIC_HOST` to the public hostname. Make the proxy forward the Host header unchanged. |
| Traefik returns `504` after 30 seconds. | On the first deployment, UFW dropped traffic from the proxy's network to a host process. | Run herdr-mcp as a container on the proxy's network. |
| The browser reports too many redirects. | Cloudflare uses the **Flexible** encryption mode for the hostname. | Set **Full (strict)** for the hostname. |
| Cloudflare returns `526`. | The origin presents no certificate that Cloudflare trusts for the hostname. | Meet requirement 2 in [Expose it through one public path](#expose-it-through-one-public-path). |
| herdr reports a permission error on `herdr.sock`. | herdr-mcp runs as a user that does not own the socket. | Run it with the uid and gid that `id -u` and `id -g` print for the herdr user. |
| `herdr status` inside the container prints `endpoint_compatible: no`. | The image's herdr CLI differs from the running server's version. | Follow [Upgrading herdr](#upgrading-herdr). |
| A native herdr-mcp reports agents from another herdr session. | It inherited `HERDR_SOCKET_PATH` from a herdr pane. | Run `echo "$HERDR_SOCKET_PATH"` in the shell that starts herdr-mcp. Start it in a shell where that path names the session you want. |
| The container reports agents from another herdr session. | The container reads only `herdr.sock` in the mounted directory. | Check that the mounted directory holds the socket of the session you want to expose. |
| Naming an agent fails because the name is taken. | Agent names are global per herdr server. | Give the agent a name that no other agent on the server uses. |
| The domain also answers on `www.`. | Coolify added a `www.` copy of the domain. | Remove it under **Public access**. |
| Grok answers about a different herdr-mcp project. | On 2026-11-20, Grok searched the web instead of calling the connector. | Check that the connector is enabled, and ask Grok to call `list_agents`. |

On the first deployment, one Grok question produced five requests in the container log. All came
from the proxy's address. `initialize` returned 200. The initialized notification returned 202.
`GET /mcp` opened the server stream and returned 200. The tool request returned 200. `DELETE /mcp`
returned 200.

herdr-mcp logs a separate `tool call` record for each tool call. The record ends in JSON fields like
this illustrative example.

```json
{"tool": "list_agents", "outcome": "ok", "duration_ms": 42}
```

## Upgrading herdr

The image pins the herdr CLI with the build argument `HERDR_VERSION`. Its default in `Dockerfile`
must equal the version of the running herdr server. Run `herdr status` on the host as the user that
runs herdr. Set the default to the `version` it prints under `server:`.

An updated herdr binary leaves a running server on its old version until herdr restarts. Change the
default only after `herdr status` reports the new server version.

On Coolify, pushing that change to `main` rebuilds and redeploys the image. The resource's
**Terminal** page in Coolify can also run `herdr status` inside the container.

On any other Linux server, rebuild the image with `docker build -t herdr-mcp .`. Remove the old
container with `docker rm -f herdr-mcp`. Then start it again with the `docker run` command above.
