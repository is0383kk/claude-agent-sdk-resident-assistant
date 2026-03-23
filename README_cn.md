> [!WARNING]
> This repository is under development. The source code and documentation are incomplete.

<table>
  <thead>
      <tr>
          <th style="text-align:center"><a href="./README.md">English</a></th>
          <th style="text-align:center">Chinese</th>
          <th style="text-align:center"><a href="./README_ja.md">日本語</a></th>
      </tr>
    </thead>
</table>

# 🦀OpenClaude — Claude Code-native personal AI assistant

基于 `claude-agent-sdk` 构建的持久化 AI 智能体系统。以 Claude Code 的 `settings.json` 为基础运行  
本项目受 [OpenClaw](https://github.com/openclaw/openclaw) 启发而创建  
以 Unix 套接字服务器形式常驻运行，接收来自 CLI 和 REST API 的消息并将其代理至 Claude

---

## 功能列表

| 功能                        | 命令 / 端点                                                 |
| --------------------------- | ----------------------------------------------------------- |
| 守护进程启动/停止/重启/状态 | `openclaude start/stop/restart/status`                      |
| 发送消息（流式传输）        | `openclaude -m "消息"`                                      |
| stdin / 管道输入            | `echo "问题" \| openclaude`                                 |
| 查看日志                    | `openclaude logs [--tail N]`                                |
| 会话管理                    | `openclaude sessions`                                       |
| Cron 任务管理               | `openclaude cron add/list/delete/run/edit`                  |
| HTTP REST API               | `POST /message`, `POST /message/stream`, `GET /status` 等   |
| Cron REST API               | `GET /cron`, `POST /cron`, `PATCH /cron/{id}`, `DELETE /cron/{id}` 等 |
| Discord 集成                | 守护进程启动时自动连接（通过 `openclaude config set` 配置） |
| Slack 集成                  | 守护进程启动时自动连接（通过 `openclaude config set` 配置） |
| Heartbeat                   | 通过 `openclaude config set heartbeat.every 30m` 定期轮询   |

---

## 安装配置

### 前提条件

- Linux / Windows（WSL2）
- Python >= 3.14
- [可使用 claude-agent-sdk 的环境](https://platform.claude.com/docs/zh-CN/agent-sdk/overview)

### 依赖包

| 包名                       | 用途                    |
| -------------------------- | ----------------------- |
| `claude-agent-sdk>=0.1.48` | Claude AI 智能体 SDK    |
| `fastapi>=0.115.0`         | REST API 框架           |
| `uvicorn>=0.30.0`          | ASGI 服务器             |
| `apscheduler>=3.10,<4`     | Cron 任务调度器（v3.x） |
| `discord.py>=2.3`          | Discord Bot（可选）     |
| `slack-bolt>=1.18`         | Slack Bot（可选）       |

### 安装步骤

```bash
git clone <repository-url> ~/.openclaude
cd ~/.openclaude
pip install -r requirements.txt

# 添加至 PATH（追加至 ~/.bashrc）
echo '[ -d "$HOME/.openclaude" ] && export PATH="$HOME/.openclaude:$PATH"' >> ~/.bashrc

# 启用 Tab 补全（追加至 ~/.bashrc）
echo 'eval "$(register-python-argcomplete openclaude)"' >> ~/.bashrc

source ~/.bashrc
```

> **注意：** 项目必须放置在 `~/.openclaude/` 目录下。
> 由于 `src/config.py` 使用 `Path.home() / ".openclaude"` 作为基础路径，放在其他目录将无法正常运行。

---

## 使用方法

### 守护进程管理

```bash
# 启动（默认端口：28789）
openclaude start

# 指定端口启动
openclaude start --port 18789

# 停止
openclaude stop

# 重启
openclaude restart

# 查看状态
openclaude status

# 查看日志
openclaude logs           # 全部内容
openclaude logs --tail 50 # 最后50行
```

### 发送消息

```bash
# 简单发送
openclaude -m "提示词"

# 指定会话
openclaude --session-id work -m "提示词"

# stdin / 管道
echo "问题" | openclaude
cat report.txt | openclaude -m "请总结这份内容"
git diff | openclaude -m "请审查这个diff"
```

### 会话管理

```bash
# 列出会话
openclaude sessions

# 删除所有会话
openclaude sessions cleanup

# 删除指定会话
openclaude sessions delete <session-id>
```

### Cron 任务

```bash
# 添加任务（每天早上9点执行）
openclaude cron add "0 9 * * *" --name "morning" --session main -m "整理今天的任务"

# 列出任务
openclaude cron list

# 手动执行
openclaude cron run <job-id>

# 编辑任务（可单独修改各字段）
openclaude cron edit <job-id> --name "新名称"
openclaude cron edit <job-id> --schedule "0 10 * * *" --message "更新后的提示词"
openclaude cron edit <job-id> --session work
openclaude cron edit <job-id> --disable
openclaude cron edit <job-id> --enable

# 删除任务
openclaude cron delete <job-id>
```

### Heartbeat

在主会话中定期执行智能体轮次，处理 `~/.openclaude/HEARTBEAT.md` 中的检查清单。
与 Cron 不同，Heartbeat 在执行时保留主会话的对话上下文。
若智能体仅回复 `HEARTBEAT_OK`，则抑制通知（仅记录日志）。

**配置步骤：**

```bash
# 启用 Heartbeat（每30分钟执行一次）
openclaude config set heartbeat.every 30m

# 禁用 Heartbeat
openclaude config set heartbeat.every 0m

# 保留间隔设置的同时临时暂停
openclaude config set heartbeat.disabled true

# 设置活跃时间段（仅在 09:00〜22:00 之间执行）
openclaude config set heartbeat.active_hours.start "09:00"
openclaude config set heartbeat.active_hours.end "22:00"

# 重启守护进程以应用配置
openclaude restart
```

**HEARTBEAT.md：**

在 `~/.openclaude/HEARTBEAT.md` 中编写供智能体处理的检查清单：

```markdown
# Heartbeat 检查清单

- 检查是否有紧急的待处理任务
- 如果没有需要关注的事项，请仅回复 HEARTBEAT_OK
```

> **注意：** 若 `HEARTBEAT.md` 不存在，守护进程将仅使用默认提示词执行。
> 若文件仅包含标题行或空行，则视为"实质上为空"并跳过执行，以减少 API 调用。

**验证运行：**

日志中出现以下信息则表示正常启动：

```
Heartbeat scheduler started (interval=1800s)
HEARTBEAT_OK (suppressed)
```

若智能体有需要报告的内容，日志中将显示 `Heartbeat alert (len=N)`。

### Discord 集成

连接 Discord Bot，接收指定频道的消息并自动回复。

**前提条件：**

1. 在 [Discord Developer Portal](https://discord.com/developers/applications) 创建应用并获取 Bot Token
2. 在 Bot 设置中启用 **Message Content Intent**
3. 通过 OAuth2 URL 将 Bot 邀请到服务器

**配置步骤：**

```bash
# 设置 Bot Token（必填）
openclaude config set discord.bot_token <YOUR_BOT_TOKEN>

# 设置目标频道 ID（必填 — 右键点击频道 → 复制频道 ID）
openclaude config set discord.channel_id <YOUR_CHANNEL_ID>

# 更改使用的会话（可选，默认值："discord"）
openclaude config set discord.session_id discord2

# 重启守护进程以应用配置
openclaude restart
```

> **注意：** 若未设置 `discord.channel_id`，Bot 将不会启动（日志中会输出 WARNING）。
> Token 也可通过环境变量 `DISCORD_BOT_TOKEN` 设置。

**验证运行：**

日志中出现以下信息则表示正常启动：

```
Discord bot starting (channel_id=..., session=...)
Discord bot ready (logged in as <BotName>)
```

启动后，发送到指定频道的消息将被转发至 Claude，并由 Bot 自动回复。

### Slack 集成

通过 Socket Mode 连接 Slack Bot，接收私信和频道 @提及 并自动回复。

**前提条件：**

1. 在 [Slack API Portal](https://api.slack.com/apps) 创建应用并安装至工作区
2. 启用 **Socket Mode**，获取具有 `connections:write` 权限范围的 App-Level Token（`xapp-` 前缀）
3. 为 Bot Token 添加以下权限范围：`chat:write`, `reactions:write`, `channels:history`, `im:history`, `app_mentions:read`
4. 启用 **Event Subscriptions** 并订阅 `message.im` 和 `app_mention` Bot 事件
5. 从 **Install App** 页面获取 Bot Token（`xoxb-` 前缀）

**配置步骤：**

```bash
# 设置 Bot Token（必填，xoxb- 前缀）
openclaude config set slack.bot_token <YOUR_BOT_TOKEN>

# 设置 App Token（必填，xapp- 前缀）
openclaude config set slack.app_token <YOUR_APP_TOKEN>

# 更改使用的会话（可选，默认值："slack"）
openclaude config set slack.session_id slack2

# 重启守护进程以应用配置
openclaude restart
```

> **注意：** 必须同时设置 `slack.bot_token` 和 `slack.app_token`，Bot 才会启动。
> Token 也可通过环境变量 `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` 设置。

**高级选项：**

```bash
# 限制私信仅接受特定用户（默认："open" — 允许所有人）
openclaude config set slack.dm_policy allowlist
openclaude config set slack.allow_from '["U01234567", "U09876543"]'

# 限制频道提及仅响应特定频道（默认："open" — 允许所有频道）
openclaude config set slack.channel_policy allowlist
openclaude config set slack.channels '["C01234567"]'
```

**验证运行：**

日志中出现以下信息则表示正常启动：

```
Slack bot starting (session=...)
Slack bot ready (logged in as <BotName>, team=<TeamName>)
```

启动后，发送给 Bot 的私信和频道中的 `@提及` 将被转发至 Claude 并由 Bot 自动回复。

### systemd 集成（已配置的情况下）

```bash
systemctl --user start openclaude
systemctl --user stop openclaude
systemctl --user status openclaude
```

---

## REST API

启动守护进程后，默认可通过 `http://localhost:28789` 访问。

| 方法     | 路径              | 说明                     |
| -------- | ----------------- | ------------------------ |
| `POST`   | `/message`        | 发送消息（完整响应）     |
| `POST`   | `/message/stream` | 发送消息（SSE 流式传输） |
| `GET`    | `/status`         | 守护进程状态与 PID       |
| `GET`    | `/sessions`       | 会话列表                 |
| `DELETE` | `/sessions`       | 删除所有会话             |
| `DELETE` | `/sessions/{id}`  | 删除指定会话             |
| `GET`    | `/cron`           | Cron 任务列表            |
| `POST`   | `/cron`           | 添加 Cron 任务           |
| `PATCH`  | `/cron/{id}`      | 编辑 Cron 任务           |
| `DELETE` | `/cron/{id}`      | 删除 Cron 任务           |
| `POST`   | `/cron/{id}/run`  | 手动执行 Cron 任务       |
