# Grok-ready Herdr-MCP for your Tesla

Herdr-MCP is an opinionated MCP server for [herdr](https://herdr.dev) agents. It contains out-of-the-box configuration that enables you to connect your Tesla Grok AI assistant to your agentic setup in herdr. Grok can list your orchestrator agents and read one agent's visible screen. It can also send your words to an orchestrator. This enables you to steer the development while driving, so you are always up to date with what your agents are doing.

## Tools

| Tool | What it does | Changes anything |
|---|---|---|
| `list_agents` | This tool lists each orchestrator's target, kind, status and workspace. | No |
| `get_agent_activity` | This tool reads one agent's visible screen. | No |
| `send_message` | This tool sends your words to a named orchestrator. The result includes the orchestrator's visible screen when herdr can read it. | Yes |

## Requirements

herdr-mcp needs herdr on the same machine, Python 3.11 or newer, and `uv`. This release targets
herdr 0.9.5. The container image installs that version by default. The herdr CLI must match the
version of the running herdr server, as [Upgrading herdr](docs/deploy.md#upgrading-herdr) explains.

## Install

Install herdr-mcp from a checkout of the repository.

```sh
uv tool install .
```

You can also install it straight from GitHub without a checkout.

```sh
uv tool install git+https://github.com/dexpetkovic/herdr-mcp
```

The [deployment guide](docs/deploy.md) covers local setup on a Mac. It shows how to expose
herdr-mcp over HTTPS on Coolify or another Linux server. It also shows how to connect Grok.

## Run as a systemd user service

`contrib/herdr-mcp.service` keeps herdr-mcp running on a Linux host without Docker. Run these steps
as the user that runs herdr.

1. Install herdr-mcp from a checkout, as [Install](#install) shows. Run these steps from the
   repository checkout.
2. Create the environment file. These commands set its permissions to 0600. An existing file keeps
   its contents.

   ```sh
   mkdir -p ~/.config/herdr-mcp
   [ -e ~/.config/herdr-mcp/env ] || install -m 600 /dev/null ~/.config/herdr-mcp/env
   chmod 600 ~/.config/herdr-mcp/env
   ```

   Edit `~/.config/herdr-mcp/env`. Put one `KEY=value` line in the file for each setting. Replace
   `<token>` with a token from the command at the top of [docs/deploy.md](docs/deploy.md).

   ```text
   HERDR_MCP_TOKEN=<token>
   HERDR_MCP_HOST=127.0.0.1
   HERDR_MCP_PORT=8765
   ```

   `HERDR_MCP_HOST` keeps the server on loopback regardless of the systemd user manager's
   environment. `HERDR_MCP_PORT` sets the listening port to 8765. Add `HERDR_BIN=<path to herdr>`
   when herdr is not in `~/.local/bin` or `/usr/local/bin`. Set `HERDR_SESSION=<name>` to read
   agents from a herdr session other than the default. The unit clears `HERDR_SOCKET_PATH` so that
   `HERDR_SESSION` takes effect.
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
5. Run `journalctl --user -u herdr-mcp` if the service is inactive or a request fails. systemd logs a
   missing environment file or executable in that journal. herdr-mcp logs a line that names an
   invalid setting in the same journal.
6. Connect a client on the same host to `http://127.0.0.1:8765/mcp` with the header
   `Authorization: Bearer <token>`. For public HTTPS access to the container, see [Expose it through
   one public path](docs/deploy.md#expose-it-through-one-public-path).

## Connect Grok

The project lives in the `dexpetkovic/herdr-mcp` repository. The server reports `herdr` as its
`serverInfo.name`.

1. Deploy herdr-mcp using the [deployment guide](docs/deploy.md). Give the server a public HTTPS
   URL.
2. Open [grok.com/connectors](https://grok.com/connectors) and add a custom connector. Enter the
   public HTTPS endpoint ending in `/mcp`, such as `https://mcp.example.com/mcp`.
3. Add the header `Authorization: Bearer <token>` to the connector. `<token>` is the value of
   `HERDR_MCP_TOKEN`.
4. Open the herdr-mcp connector at [grok.com/connectors](https://grok.com/connectors). Paste the
   text from [docs/grok-instructions.md](docs/grok-instructions.md) into its **Customize** field.

[Connect Grok](docs/deploy.md#connect-grok) in the deployment guide shows how to check the endpoint.
Grok can keep an old tool list. The same section shows how to recreate the connector with a new
`?v=N` value.
[Troubleshooting](docs/deploy.md#troubleshooting) covers failed requests.

## Use it in your Tesla

Tesla's [Grok support page](https://www.tesla.com/support/grok) says Grok in the car uses the
connectors from your signed-in Grok account. In the car, sign in to the Grok account where you
added the connector. Grok picks up the connector automatically after you sign in.

Tesla Support lists the vehicle requirements for Grok and Connectors. It covers the software
version, processor and connectivity.

Speak to Grok in the car. For example, say "ask my orchestrator in herdr-mcp what it is
working on".

Grok in a Tesla Model Y reaches this connector and calls its tools.

## Test without a car

The Grok mobile app and grok.com use the same connector. You can test every tool in the Grok mobile
app or on grok.com. The mobile app's voice mode is the closest match for talking to Grok in the car.

## Security and privacy

The token lets whoever holds it send instructions to your orchestrator. What the orchestrator does
with them depends on its own permissions. An orchestrator with a shell can run commands as the user
that runs herdr. Treat the token like that user's password.

Keep the token out of chat logs and screenshots.

To rotate the token, choose a new one and apply it with the steps for your setup. The server reads
the token only when it starts.

- The systemd user service reads the token from `~/.config/herdr-mcp/env`. Edit that file, then run
  `systemctl --user restart herdr-mcp`.
- On a Mac, herdr-mcp reads the token from the shell that starts it. Stop the server, export the new
  token in that shell and start it again, as [On a Mac](docs/deploy.md#on-a-mac) shows.
- On Coolify, change the value under **Environment Variables** and redeploy.
- With plain Docker, a restart keeps the old token. Export the new token in your shell first. Remove
  the container with `docker rm -f herdr-mcp`. Start it again with the `docker run` command in [On
  any other Linux server](docs/deploy.md#on-any-other-linux-server), with the same `-p` or
  `--network` option as before.

Then put the new token in the connector's `Authorization` header. Check the change with the
`initialize` probe in [Connect Grok](docs/deploy.md#connect-grok). Point it at your MCP URL, such as
`http://127.0.0.1:8765/mcp` for a local setup. In the shell where you run curl, set
`HERDR_MCP_TOKEN` to the new token. The probe should return `200`. Repeat with the old token and
look for `401`.

A connected client can read your agents' visible terminal output. Connect only clients you trust
with that output.

## Limits of send_message

herdr-mcp supports one layout. Give each project one workspace on its main checkout. Use workspace
labels to distinguish projects. Tab 1 of that workspace holds only the orchestrator. A reviewer's
name starts with `rev-` or contains `-rev-`, such as `rev-main` or `hm-rev-main`.

`list_agents` lists the orchestrators in that layout. `send_message` sends only to a named
orchestrator in that layout. Set the orchestrator's name with `herdr agent rename`. The server tells
the client to send your words unchanged. `send_message` checks the orchestrator's status once before
the send. It sends only if that check shows the orchestrator idle or done, or shows a busy Claude Code
orchestrator. A message to a busy Claude Code orchestrator is sent without waiting for the turn. It
asks the orchestrator to finish its current task first unless the message asks it to stop.
`send_message` refuses to send to a busy Codex orchestrator.

For an idle or done orchestrator, the server sends your words and these instructions together in a
single line.

```
Voice message from the engineer, relayed by Grok: "<your words>". Reply in plain text and do not open a question dialog. If you need me to choose, list numbered options and end your turn.
```

Reply with the option number in another message, such as "option 2". Grok sends that reply to the
same orchestrator name. Answer Claude Code's permission prompts at the computer.

When that check shows the orchestrator idle or done, `send_message` waits up to 30 seconds for the
turn to settle. `send_message` then returns the orchestrator's visible screen when herdr can read
it. The screen may show an earlier answer or just the end of a long answer. If the wait times out,
`send_message` can report that the message may have been sent. Check the same orchestrator with
`get_agent_activity` before you send again.

- The orchestrator can start working between the status check and delivery.
- The agent can move to another tab or workspace before delivery.
- Another agent can take the target name before delivery.

## Development

Install the package and its development dependencies with `uv sync`. Run the tests with
`uv run pytest`. Run the linter with `uv run ruff check`. Check the formatting with
`uv run ruff format --check`. GitHub runs these three checks on each pull request that has no
merge conflict.

## License

herdr-mcp is licensed under the MIT license. The container image bundles herdr. Herdr uses the
Apache-2.0 license.
