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
checkout. Each path needs its own tools.

- On a Mac, you need `uv` and a herdr CLI of the same version as the running herdr server.
- On Coolify, you need a Coolify server, a Cloudflare zone and a copy of the repository that you can
  push to in your own GitHub account.
- On any other Linux server, you need Docker and permission to run `docker` as the user that runs
  herdr.

The herdr CLI talks to the herdr server through the Unix socket `~/.config/herdr/herdr.sock`. A Unix
socket cannot cross machines, so herdr-mcp runs on the machine that runs the herdr server.

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
herdr](#upgrading-herdr) explains how to keep them equal.

## On a Mac

Docker Desktop on macOS does not pass a Unix socket through reliably. herdr-mcp therefore runs
natively next to herdr on the Mac.

1. Install it from the checkout with `uv tool install .`.
2. Start it with `herdr-mcp` in the shell that holds `HERDR_MCP_TOKEN`.

The server listens on `127.0.0.1:8765` and finds herdr's socket in `~/.config/herdr/`.

## On Coolify

Coolify builds the image from `Dockerfile` on the server and runs it with
`docker-compose.coolify.yaml`. Every push to `main` triggers a new build and deploy through
Coolify's GitHub App source.

The compose file mounts the herdr socket directory read-only at `/herdr`. The read-only mount is
enough for herdr-mcp. Coolify connects Traefik to the application's Compose network, so the compose
file publishes no port. Coolify's dashboard uses port 8000 by default, so herdr-mcp listens on 8765.

Set it up once.

1. In your copy of the repository, edit `docker-compose.coolify.yaml`. Set the `user` line to the uid
   and gid of the user that runs herdr, such as `"1000:1000"`. Set the mount source to that user's
   `.config/herdr` directory as an absolute path. Push the change to `main`.
2. Give Coolify's GitHub App access to your copy of the repository.
3. Add a new resource from the GitHub App source. Pick your copy of the repository and select the
   `main` branch.
4. Select the Docker Compose build pack. The Dockerfile build pack ignores the compose file's `user`
   line and socket mount.
5. Set **Base Directory** to `/` and **Docker Compose Location** to `/docker-compose.coolify.yaml`.
6. Check that **Advanced > Deployment > Auto deploy** is set to **Deploy on push (webhooks)**. A
   GitHub App resource has this setting by default.
7. Set the service's domain to `https://mcp.example.com:8765`. The port tells Traefik which
   container port receives the request. Coolify can warn "Unrecognized internal port" before the
   first build. The warning is harmless.
8. Remove the `www.` copy of the domain that Coolify adds under **Public access**.
9. Set `HERDR_MCP_TOKEN` and `HERDR_MCP_PUBLIC_HOST=mcp.example.com` under **Environment
   Variables**. Coolify refuses to deploy while either is empty.
10. Set the server's firewall as [Expose it through one public
    path](#expose-it-through-one-public-path) describes.
11. Point a proxied Cloudflare DNS record for `mcp.example.com` at the server. Set the zone's
    SSL/TLS encryption mode to **Full (strict)**.
12. Deploy.

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

A reverse proxy inside a container cannot reach the host's `127.0.0.1`. Put both containers on one
user-defined Docker network, because Docker resolves container names only on such a network. Set
`PROXY_NETWORK` to the network that the proxy container joins. Replace the `-p` line with this line.

```sh
  --network "$PROXY_NETWORK" \
```

Point the proxy at the upstream `http://herdr-mcp:8765`.

In both setups the proxy forwards the public Host header unchanged.

## Expose it through one public path

Grok's custom connectors call herdr-mcp from xAI's servers. herdr-mcp therefore needs a public HTTPS
URL that ends in `/mcp`, such as `https://mcp.example.com/mcp`.

The recommended path has three hops. A proxied Cloudflare DNS record receives the request. A reverse
proxy on the server, such as Coolify's Traefik, forwards it. The herdr-mcp container answers it.

Keep this path the only public way in. Set the server's firewall to accept ports 80 and 443 only
from [Cloudflare's IP ranges](https://www.cloudflare.com/ips/). Do this before you publish the DNS
record. Open no second public path to the server.

Set the zone's encryption mode to **Full (strict)** on the **SSL/TLS Overview** page in Cloudflare.
Full (strict) needs a valid certificate for the hostname on the origin. The Let's Encrypt
certificate that Traefik obtains qualifies. The **Flexible** mode loops on Coolify's HTTPS redirect.

Run herdr-mcp as a container on the proxy's network. On the first deployment, a host process behind
Coolify's Traefik timed out. UFW dropped the traffic from Coolify's bridge networks to the host.
Traefik answered 504 after 30 seconds.

Set `HERDR_MCP_PUBLIC_HOST` to the public hostname. The MCP SDK answers 421 to a Host header it does
not know.

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

1. Open grok.com/connectors and choose **New Connector**, then **Custom**.
2. Enter `https://mcp.example.com/mcp` as the server URL.
3. Add the header `Authorization` with the value `Bearer <token>`. `<token>` is the value of
   `HERDR_MCP_TOKEN`.
4. Ask Grok what your herdr agents are doing. Compare the answer with an agent that you see in herdr.

The two probes never touch the herdr socket. Only Grok's answer in step 4 proves the whole path. On
the first deployment, Grok showed the tool as `herdr_mcp___list_agents`.

A connector added at grok.com also works in the Grok mobile app. On 2026-11-20, Grok listed live
agents from the mobile app. Grok in a car has no recorded test yet.

At least 15 public repositories share the name herdr-mcp. This project is the repository
`dexpetkovic/herdr-mcp`. Its MCP server name is `herdr`. Its tools are `list_agents`,
`get_agent_activity` and `send_message`. The server sends instructions on `initialize` that tell
the client to answer from this live server. Whether Grok follows them is not yet verified.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| A request with the token returns `401`. | The `Authorization` header is missing or carries another token. | Send `Authorization: Bearer <token>` with the exact value of `HERDR_MCP_TOKEN`. |
| A request returns `421`. | The Host header differs from `HERDR_MCP_PUBLIC_HOST`. | Set `HERDR_MCP_PUBLIC_HOST` to the public hostname. Make the proxy forward the Host header unchanged. |
| Traefik returns `504` after 30 seconds. | The host firewall drops traffic from the proxy's network to a host process. | Run herdr-mcp as a container on the proxy's network. |
| The browser reports too many redirects. | The Cloudflare zone uses the **Flexible** encryption mode. | Set the mode to **Full (strict)**. |
| Cloudflare returns `526`. | The origin has no valid certificate for the hostname. | Wait for Traefik's Let's Encrypt certificate, and check the domain in Coolify. |
| herdr reports a permission error on `herdr.sock`. | herdr-mcp runs as a user that does not own the socket. | Run it with the uid and gid that `id -u` and `id -g` print for the herdr user. |
| `herdr status` inside the container prints `endpoint_compatible: no`. | The image's herdr CLI differs from the running server's version. | Follow [Upgrading herdr](#upgrading-herdr). |
| `list_agents` reports agents from another herdr session. | A native herdr-mcp inherited `HERDR_SOCKET_PATH` from a herdr pane. | Run `echo "$HERDR_SOCKET_PATH"` in the shell that starts herdr-mcp. Start it in a shell where that path names the session you want. |
| Naming an agent fails because the name is taken. | Agent names are global per herdr server. | Give the agent a name that no other agent on the server uses. |
| The domain also answers on `www.`. | Coolify added a `www.` copy of the domain. | Remove it under **Public access**. |
| Grok answers about a different herdr-mcp project. | Grok searched the web instead of calling the connector. | Check that the connector is enabled, and ask Grok to call `list_agents`. |

On the first deployment, one Grok question produced five requests in the container log. All came
from the proxy's address. `initialize` returned 200, and the initialized notification returned 202.
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
