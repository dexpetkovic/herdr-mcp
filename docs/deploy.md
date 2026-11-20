# Deploying herdr-mcp

herdr-mcp must run on the machine where the herdr server runs. It reaches herdr through herdr's Unix
socket. The herdr CLI that herdr-mcp calls must have the same version as the herdr server.
`herdr status` prints both versions and reports `endpoint_compatible: yes` when they match.

Every setting comes from an environment variable. `HERDR_MCP_TOKEN` is required in every setup.
Generate one with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.

## On a Mac

herdr-mcp runs natively next to herdr on the Mac.

1. Install it from a checkout with `uv tool install .`.
2. Start it with `HERDR_MCP_TOKEN=<token> herdr-mcp`.

The server listens on `127.0.0.1:8000` and finds herdr's socket in `~/.config/herdr/`.

## On Coolify

The workflow `.github/workflows/image.yml` builds the image on every push to `main`. It pushes
`ghcr.io/dexpetkovic/herdr-mcp` with the tags `latest` and `sha-<short commit>`. It then calls
Coolify's deploy webhook. Coolify pulls `latest` and runs it with `docker-compose.coolify.yaml`.

The container runs as uid 2001, which owns herdr's socket on the server. It mounts
`/home/agent/.config/herdr` read-only at `/herdr`. Coolify's Traefik reaches the container on the
`coolify` network, so the compose file publishes no port.

Set it up once.

1. Create a classic GitHub personal access token with `read:packages`. In Coolify, open
   **Registries**, choose the GHCR preset and log the server in with that token. Coolify runs
   `docker login ghcr.io` for the server.
2. Add a new resource from the GitHub App source and pick this repository.
3. Select the Docker Compose build pack.
4. Set **Base Directory** to `/` and **Docker Compose Location** to `/docker-compose.coolify.yaml`.
5. Set **Advanced > Deployment > Auto deploy** to **Manual deployments only**. The workflow then
   starts every deploy after the image exists.
6. Set the service's domain to `https://herdr-mcp.elands.studio:8765`. The port tells Traefik which
   container port receives the request.
7. Set `HERDR_MCP_TOKEN` and `HERDR_MCP_PUBLIC_HOST=herdr-mcp.elands.studio` under **Environment
   Variables**. Coolify refuses to deploy while either is empty.
8. Point a proxied Cloudflare DNS record for `herdr-mcp.elands.studio` at the server.
9. Enable **Settings > Advanced > API access**. Create an API token with only the **Deploy**
   permission under **Keys & Tokens > API Tokens**.
10. Copy the resource's deploy webhook URL from its **Webhooks** page.
11. Add the repository secrets `COOLIFY_WEBHOOK` with that URL and `COOLIFY_TOKEN` with the token
    under **Settings > Secrets and variables > Actions** on GitHub.

Change the uid, gid and mount source in the compose file when herdr runs as another user.

## On any other Linux server

Build the image from `Dockerfile` and run it next to herdr.

```sh
docker build -t herdr-mcp .
docker run -d --restart unless-stopped \
  --user "$(id -u):$(id -g)" \
  -v "$HOME/.config/herdr:/herdr:ro" \
  -e HERDR_MCP_TOKEN=<token> \
  -e HERDR_MCP_PUBLIC_HOST=<public hostname> \
  -p 127.0.0.1:8765:8765 \
  herdr-mcp
```

Run the commands as the user that runs herdr. Put an HTTPS reverse proxy in front of
`127.0.0.1:8765` for the public hostname.

## Upgrading herdr

The image pins the herdr CLI with the build argument `HERDR_VERSION`. After every herdr upgrade on
the host, change its default in `Dockerfile` to the new version. On Coolify, merging that change
rebuilds and redeploys the image. Elsewhere, rebuild the image. Check the result with
`docker exec <container> herdr status`.
