# herdr-mcp

`herdr-mcp` is an MCP server for [herdr](https://herdr.dev) agents. A voice client such as Grok can
list your herdr agents, read one agent's visible screen and send an instruction to your orchestrator
agent. This project is the repository `dexpetkovic/herdr-mcp`. Its MCP server name is `herdr`,
which a client shows as `serverInfo.name`.

## Tools

| Tool | What it does | Changes anything |
|---|---|---|
| `list_agents` | It lists every herdr agent with its target, kind, status and workspace. | No |
| `get_agent_activity` | It reads what one agent's screen shows now. | No |
| `send_message` | It sends one instruction to your named orchestrator agent. | Yes |

## Requirements

herdr-mcp needs herdr on the same machine, Python 3.11 or newer, and `uv`. This release targets
herdr 0.9.5, the version that the image installs by default. The herdr CLI must match the version of
the running herdr server, as [Upgrading herdr](docs/deploy.md#upgrading-herdr) explains.

## Install

Install herdr-mcp from a checkout of the repository.

```sh
uv tool install .
```

The repository is private. A checkout needs access from its owner. When your Git has a credential
helper that supplies a GitHub credential with access to the repository, you can also install
without a checkout.

```sh
uv tool install git+https://github.com/dexpetkovic/herdr-mcp
```

[docs/deploy.md](docs/deploy.md) explains how to run herdr-mcp on a Mac, on Coolify or in a
container, how to expose it through one public path and how to connect Grok.

## Run as a systemd user service

`contrib/herdr-mcp.service` keeps herdr-mcp running on a Linux host without Docker. Run these steps
as the user that runs herdr.

1. Install herdr-mcp from a checkout, as [Install](#install) shows. Run the later steps in that
   checkout.
2. Create the environment file with mode 0600. The commands keep an existing file and fix its mode.

   ```sh
   mkdir -p ~/.config/herdr-mcp
   [ -e ~/.config/herdr-mcp/env ] || install -m 600 /dev/null ~/.config/herdr-mcp/env
   chmod 600 ~/.config/herdr-mcp/env
   ```

   Edit the file. It holds one `KEY=value` line per setting. Replace `<token>` with a token from
   the command at the top of [docs/deploy.md](docs/deploy.md).

   ```text
   HERDR_MCP_TOKEN=<token>
   HERDR_MCP_HOST=127.0.0.1
   HERDR_MCP_PORT=8765
   ```

   The host line keeps the listener on the loopback interface, whatever the user manager's
   environment holds. The port line fixes the port. Add `HERDR_BIN=<path to herdr>` when herdr is not in `~/.local/bin` or `/usr/local/bin`.
   Add `HERDR_SESSION=<name>` to report a herdr session other than the default. The unit clears
   `HERDR_SOCKET_PATH`, so `HERDR_SESSION` takes effect.
3. Copy the unit.

   ```sh
   mkdir -p ~/.config/systemd/user
   cp contrib/herdr-mcp.service ~/.config/systemd/user/
   ```

   The unit starts `~/.local/bin/herdr-mcp`. When `uv tool dir --bin` prints another directory,
   change `ExecStart` in `~/.config/systemd/user/herdr-mcp.service` to match. Then start the unit.

   ```sh
   systemctl --user daemon-reload
   systemctl --user enable --now herdr-mcp
   ```

4. Run `loginctl enable-linger` once. The service then starts at boot without a login.
5. Read `journalctl --user -u herdr-mcp` when the service is not active or a request fails. systemd
   logs a missing environment file or executable there. herdr-mcp logs a line there that names an
   invalid setting.
6. Connect a client on the same host to `http://127.0.0.1:8765/mcp` with the header
   `Authorization: Bearer <token>`. The guide documents the public path for the container, in [Expose it through one public
   path](docs/deploy.md#expose-it-through-one-public-path).

## Privacy

The connected client receives the terminal output of every agent it reads. Connect only a client
that you trust with what your agents show.

## Limits of send_message

`send_message` sends only to a named orchestrator. The orchestrator must be the only agent in tab 1
of the main checkout's workspace. Name it with `herdr agent rename`. `list_agents` marks the
orchestrator with `orchestrator: true`. The server tells the client to send your words unchanged.
The tool sends only when the orchestrator is idle or done at its check just before sending.

- The orchestrator can start working between that check and the delivery.
- The agent can move to another tab or workspace, or lose its name to a new agent, before herdr
  delivers the message.

## License

herdr-mcp is licensed under the MIT license. The container image bundles herdr, which is licensed
under Apache-2.0.
