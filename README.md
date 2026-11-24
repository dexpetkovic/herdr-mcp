# Grok-ready Herdr-MCP for your Tesla

Herdr-MCP is an opinionated MCP server for [herdr](https://herdr.dev) agents. It contains out-of-the-box configuration that enables you to connect your Tesla Grok AI assistant to your agentic setup in herdr. Grok can list your orchestrator agents and read one agent's visible screen. It can also send your words to an orchestrator. This enables you to steer the development while driving, so you are always up to date with what your agents are doing.

## Tools

| Tool | What it does | Changes anything |
|---|---|---|
| `list_agents` | It lists your orchestrator agents with their target, kind, status and workspace. | No |
| `get_agent_activity` | It reads what one agent's screen shows now. | No |
| `send_message` | It sends your words to a named orchestrator and returns the visible screen when herdr can read it. | Yes |

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

## Connect Grok

This project is the repository `dexpetkovic/herdr-mcp`. The server reports `herdr` as its
`serverInfo.name`. Follow these steps to connect Grok to it.

1. Deploy herdr-mcp and expose it through one public path, as [docs/deploy.md](docs/deploy.md)
   explains.
2. Open [grok.com/connectors](https://grok.com/connectors) and add a custom connector. Enter the
   public server URL, such as `https://mcp.example.com/mcp`.
3. Add the header `Authorization: Bearer <token>` to the connector. `<token>` is the value of
   `HERDR_MCP_TOKEN`.
4. Paste the text from [docs/grok-instructions.md](docs/grok-instructions.md) into Grok under
   **Settings**, then **Customize**.

[Connect Grok](docs/deploy.md#connect-grok) in the deployment guide shows how to check the endpoint.
It also shows how to recreate the connector with a new `?v=N` value when Grok keeps a stale tool list.
[Troubleshooting](docs/deploy.md#troubleshooting) covers failed requests.

## Use it in your Tesla

Grok in the car uses the connectors of the Grok account it is signed in to. The engineer's Tesla
Model Y reached this connector that way. In the car, sign in to the Grok account where you added the
connector.

Tesla's [Grok support page](https://www.tesla.com/support/grok) lists the vehicle requirements for
Grok. They cover the software version, the processor and the connectivity.

Talk to Grok in the car by voice. For example, say "ask my orchestrator in herdr-mcp what it is
working on".

The Model Y run listed the orchestrators. The full voice round trip from the car has not been
recorded yet.

## Test without a car

The Grok mobile app and grok.com use the same connector. You can test every tool there first.
Voice mode in the Grok mobile app comes closest to the car.

## Privacy

The connected client receives the terminal output of every agent it reads. Connect only a client
that you trust with what your agents show.

## Limits of send_message

herdr-mcp supports one layout. Each project has one workspace on its main checkout, and workspace
labels tell the projects apart. Tab 1 of that workspace holds only the orchestrator. A reviewer's
name starts with `rev-` or contains `-rev-`, such as `rev-main` or `hm-rev-main`.

`list_agents` lists only the agents in the orchestrator position. `send_message` sends only to a
named orchestrator. Name it with `herdr agent rename`. The server tells the client to send your
words unchanged. The tool sends only when the orchestrator is idle or done at its check just before
sending.

The server wraps your words in one line before it sends them. The orchestrator receives this text.

```
Voice message from the engineer, relayed by Grok: "<your words>". Reply in plain text and do not open a question dialog. If you need me to choose, list numbered options and end your turn.
```

You answer the options with another message, such as "option 2". Grok sends that answer to the
same orchestrator name. Claude Code's own permission prompts still need the computer.

`send_message` waits up to 30 seconds for the orchestrator's turn to settle. It then returns the
orchestrator's visible screen when herdr can read it. The screen can still show an earlier answer, or only the end of a
long one. When the turn takes longer, the tool says that the message may have been sent. Read the
screen later with `get_agent_activity`.

- The orchestrator can start working between that check and the delivery.
- The agent can move to another tab or workspace, or lose its name to a new agent, before herdr
  delivers the message.

## License

herdr-mcp is licensed under the MIT license. The container image bundles herdr, which is licensed
under Apache-2.0.
