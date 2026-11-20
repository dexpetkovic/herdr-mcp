# Deploying herdr-mcp

herdr-mcp must run on the machine where the herdr server runs. It reaches herdr through herdr's Unix
socket. The herdr CLI that herdr-mcp calls must have the same version as the herdr server. Run
`herdr status` and compare the client and server versions it prints.

Every setting comes from an environment variable. `HERDR_MCP_TOKEN` is required in every setup.
Generate one and keep it in the shell.

```sh
export HERDR_MCP_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

## On a Mac

herdr-mcp runs natively next to herdr on the Mac.

1. Install it from a checkout with `uv tool install .`.
2. Start it with `herdr-mcp` in the shell that holds `HERDR_MCP_TOKEN`.

The server listens on `127.0.0.1:8000` and finds herdr's socket in `~/.config/herdr/`.

## On Coolify

Coolify builds the image from `Dockerfile` on the server and runs it with
`docker-compose.coolify.yaml`. Every push to `main` triggers a new build and deploy through the
GitHub App source.

The container runs as uid 2001, which owns herdr's socket on the server. It mounts
`/home/agent/.config/herdr` read-only at `/herdr`. Coolify connects Traefik to the application's
Compose network, so the compose file publishes no port.

The server's firewall must accept ports 80 and 443 only from Cloudflare's IP ranges. Cloudflare is
then the only public way in. Check this before you publish the domain.

Set it up once.

1. Add a new resource from the GitHub App source, pick this repository and select the `main` branch.
2. Select the Docker Compose build pack.
3. Set **Base Directory** to `/` and **Docker Compose Location** to `/docker-compose.coolify.yaml`.
4. Check that **Advanced > Deployment > Auto deploy** is set to **Deploy on push (webhooks)**.
5. Set the service's domain to `https://herdr-mcp.elands.studio:8765`. The port tells Traefik which
   container port receives the request.
6. Set `HERDR_MCP_TOKEN` and `HERDR_MCP_PUBLIC_HOST=herdr-mcp.elands.studio` under **Environment
   Variables**. Coolify refuses to deploy while either is empty.
7. Point a proxied Cloudflare DNS record for `herdr-mcp.elands.studio` at the server.
8. Deploy.

Change the uid, gid and mount source in the compose file when herdr runs as another user.

## On any other Linux server

Build the image from `Dockerfile` and run it next to herdr. Run the commands as the user that runs
herdr, in a shell that holds `HERDR_MCP_TOKEN` and `HERDR_MCP_PUBLIC_HOST`.

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

Put an HTTPS reverse proxy in front of `127.0.0.1:8765` for the public hostname.

## Upgrading herdr

The image pins the herdr CLI with the build argument `HERDR_VERSION`. After every herdr upgrade on
the host, change its default in `Dockerfile` to the new version. On Coolify, pushing that change to
`main` rebuilds and redeploys the image.

On any other Linux server, run `docker rm -f herdr-mcp` after the rebuild. Then start the container
again with the `docker run` command above.

Find the container's name with `docker ps --filter name=herdr-mcp`. Check the versions with
`docker exec <container name> herdr status`.
