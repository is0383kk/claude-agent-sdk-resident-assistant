> [!WARNING]
> This repository is under development. The source code and documentation are incomplete.

<table>
  <thead>
      <tr>
          <th style="text-align:center">English</th>
          <th style="text-align:center"><a href="./README_cn.md">Chinese</a></th>
          <th style="text-align:center"><a href="./README_ja.md">日本語</a></th>
      </tr>
    </thead>
</table>

# 🦀OpenClaude — Claude Code-native personal AI assistant

A persistent AI agent system built with `claude-agent-sdk`. Operates based on Claude Code's `settings.json`.  
This project is inspired by [OpenClaw](https://github.com/openclaw/openclaw).  
Runs as a Unix socket server, accepting messages from the CLI and REST API and proxying them to Claude.

---

## Features

| Feature                                | Command / Endpoint                                                   |
| -------------------------------------- | -------------------------------------------------------------------- |
| Daemon start / stop / restart / status | `openclaude start/stop/restart/status`                               |
| Send message (streaming)               | `openclaude -m "message"`                                            |
| stdin / pipe input                     | `echo "question" \| openclaude`                                      |
| View logs                              | `openclaude logs [--tail N]`                                         |
| Session management                     | `openclaude sessions`                                                |
| Cron job management                    | `openclaude cron add/list/delete/run`                                |
| HTTP REST API                          | `POST /message`, `POST /message/stream`, `GET /status`, etc.         |
| Cron REST API                          | `GET /cron`, `POST /cron`, `DELETE /cron/{id}`, etc.                 |
| Discord integration                    | Auto-connect on daemon start (configure via `openclaude config set`) |
| Slack integration                      | Auto-connect on daemon start (configure via `openclaude config set`) |

---

## Setup

### Prerequisites

- Linux / Windows (WSL2)
- Python >= 3.14
- [An environment where claude-agent-sdk is available](https://platform.claude.com/docs/en/agent-sdk/overview)

### Dependencies

| Package                    | Purpose                   |
| -------------------------- | ------------------------- |
| `claude-agent-sdk>=0.1.48` | Claude AI Agent SDK       |
| `fastapi>=0.115.0`         | REST API framework        |
| `uvicorn>=0.30.0`          | ASGI server               |
| `apscheduler>=3.10,<4`     | Cron job scheduler (v3.x) |
| `discord.py>=2.3`          | Discord Bot (optional)    |
| `slack-bolt>=1.18`         | Slack Bot (optional)      |

### Installation

```bash
git clone <repository-url> ~/.openclaude
cd ~/.openclaude
pip install -r requirements.txt

# Add to PATH (~/.bashrc)
echo '[ -d "$HOME/.openclaude" ] && export PATH="$HOME/.openclaude:$PATH"' >> ~/.bashrc

# Enable tab completion (~/.bashrc)
echo 'eval "$(register-python-argcomplete openclaude)"' >> ~/.bashrc

source ~/.bashrc
```

> **Note:** The project must be placed in `~/.openclaude/`.
> Since `src/config.py` uses `Path.home() / ".openclaude"` as the base path, it will not work in a different directory.

---

## Usage

### Daemon Management

```bash
# Start (default port: 28789)
openclaude start

# Start with a specific port
openclaude start --port 18789

# Stop
openclaude stop

# Restart
openclaude restart

# Check status
openclaude status

# View logs
openclaude logs           # full output
openclaude logs --tail 50 # last 50 lines
```

### Sending Messages

```bash
# Simple send
openclaude -m "prompt"

# Specify a session
openclaude --session-id work -m "prompt"

# stdin / pipe
echo "question" | openclaude
cat report.txt | openclaude -m "Summarize this"
git diff | openclaude -m "Review this diff"
```

### Session Management

```bash
# List sessions
openclaude sessions

# Delete all sessions
openclaude sessions cleanup

# Delete a specific session
openclaude sessions delete <session-id>
```

### Cron Jobs

```bash
# Add a job (runs every morning at 9:00)
openclaude cron add "0 9 * * *" --name "morning" --session main -m "Organize today's tasks"

# List jobs
openclaude cron list

# Run manually
openclaude cron run <job-id>

# Delete a job
openclaude cron delete <job-id>
```

### Discord Integration

Connect a Discord Bot to receive and reply to messages in a specified channel.

**Prerequisites:**

1. Create an application in the [Discord Developer Portal](https://discord.com/developers/applications) and obtain a Bot Token
2. Enable **Message Content Intent** in the Bot settings
3. Invite the Bot to your server via the OAuth2 URL

**Setup:**

```bash
# Set Bot Token (required)
openclaude config set discord.bot_token <YOUR_BOT_TOKEN>

# Set target channel ID (required — right-click channel → Copy Channel ID)
openclaude config set discord.channel_id <YOUR_CHANNEL_ID>

# Set session to use (optional, default: "discord")
openclaude config set discord.session_id discord2

# Restart daemon to apply
openclaude restart
```

> **Note:** If `discord.channel_id` is not set, the Bot will not start (a warning is logged).
> Alternatively, set the token via the environment variable `DISCORD_BOT_TOKEN`.

**Verify:**

Check that the following messages appear in the logs:

```
Discord bot starting (channel_id=..., session=...)
Discord bot ready (logged in as <BotName>)
```

Once running, any message sent to the configured channel will be forwarded to Claude and replied to by the Bot.

### Slack Integration

Connect a Slack Bot to receive and reply to DMs and channel mentions via Socket Mode.

**Prerequisites:**

1. Create an application in the [Slack API Portal](https://api.slack.com/apps) and install it to your workspace
2. Enable **Socket Mode** and obtain an App-Level Token (`xapp-` prefix) with the `connections:write` scope
3. Add the following Bot Token Scopes: `chat:write`, `reactions:write`, `channels:history`, `im:history`, `app_mentions:read`
4. Enable the **Event Subscriptions** and subscribe to `message.im` and `app_mention` bot events
5. Obtain the Bot Token (`xoxb-` prefix) from the **Install App** page

**Setup:**

```bash
# Set Bot Token (required, xoxb- prefix)
openclaude config set slack.bot_token <YOUR_BOT_TOKEN>

# Set App Token (required, xapp- prefix)
openclaude config set slack.app_token <YOUR_APP_TOKEN>

# Set session to use (optional, default: "slack")
openclaude config set slack.session_id slack2

# Restart daemon to apply
openclaude restart
```

> **Note:** Both `slack.bot_token` and `slack.app_token` must be set for the Bot to start.
> Tokens can also be set via environment variables `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN`.

**Advanced options:**

```bash
# Restrict DMs to specific users (default: "open" — allow all)
openclaude config set slack.dm_policy allowlist
openclaude config set slack.allow_from '["U01234567", "U09876543"]'

# Restrict channel mentions to specific channels (default: "open" — allow all)
openclaude config set slack.channel_policy allowlist
openclaude config set slack.channels '["C01234567"]'
```

**Verify:**

Check that the following messages appear in the logs:

```
Slack bot starting (session=...)
Slack bot ready (logged in as <BotName>, team=<TeamName>)
```

Once running, DMs to the Bot and `@mentions` in channels will be forwarded to Claude and replied to by the Bot.

### systemd Integration (if configured)

```bash
systemctl --user start openclaude
systemctl --user stop openclaude
systemctl --user status openclaude
```

---

## REST API

After starting the daemon, it is accessible at `http://localhost:28789` by default.

| Method   | Path              | Description                  |
| -------- | ----------------- | ---------------------------- |
| `POST`   | `/message`        | Send message (full response) |
| `POST`   | `/message/stream` | Send message (SSE streaming) |
| `GET`    | `/status`         | Daemon status and PID        |
| `GET`    | `/sessions`       | List sessions                |
| `DELETE` | `/sessions`       | Delete all sessions          |
| `DELETE` | `/sessions/{id}`  | Delete a specific session    |
| `GET`    | `/cron`           | List cron jobs               |
| `POST`   | `/cron`           | Add a cron job               |
| `DELETE` | `/cron/{id}`      | Delete a cron job            |
| `POST`   | `/cron/{id}/run`  | Run a cron job manually      |

---

## Architecture

```
CLI (openclaude)
  └── src/cli.py
        └── Communicates with daemon via Unix socket (~/.openclaude/openclaude.sock)

Daemon + API server + Discord Bot + Slack Bot (same process)
  ├── src/daemon.py      ── Unix socket server
  ├── src/api.py         ── FastAPI + uvicorn (REST API)
  ├── src/cron.py        ── apscheduler-based scheduler
  ├── src/discord_bot.py ── Discord Bot (optional)
  └── src/slack_bot.py   ── Slack Bot (optional)
```

### File Structure

```
~/.openclaude/
  ├── src/
  │   ├── config.py        # File path constants and logging configuration
  │   ├── daemon.py        # Unix socket server and message handlers
  │   ├── api.py           # FastAPI REST API server
  │   ├── cron.py          # Cron job management (CronJob / CronScheduler)
  │   ├── discord_bot.py   # Discord Bot (optional)
  │   ├── slack_bot.py     # Slack Bot (optional)
  │   ├── utils.py         # Shared utilities (config loading, etc.)
  │   └── cli.py           # CLI entry point
  ├── sessions/
  │   └── sessions.json         # Session alias -> SDK session ID mapping
  ├── cron/
  │   ├── jobs.json             # Cron job definitions (persisted)
  │   └── runs/<job_id>.jsonl   # Execution history
  ├── openclaude.sock           # Unix socket (only while running)
  ├── openclaude.pid            # PID file (only while running)
  └── daemon.log                # Daemon log
```
