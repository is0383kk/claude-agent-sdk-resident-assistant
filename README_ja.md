> [!WARNING]
> This repository is under development. The source code and documentation are incomplete.

<table>
	<thead>
    	<tr>
      		<th style="text-align:center"><a href="./README.md">English</a></th>
          <th style="text-align:center"><a href="./README_cn.md">Chinese</a></th>
      		<th style="text-align:center">日本語</th>
    	</tr>
  	</thead>
</table>

# 🦀OpenClaude — Claude Code-native personal AI assistant

`claude-agent-sdk` を使った常駐型 AI エージェントシステム。Claude Codeの`settings.json`をベースに動作します。  
このプロジェクトは [OpenClaw](https://github.com/openclaw/openclaw) に触発されたプロジェクトです。  
Unix ソケットサーバーとして常駐し、CLI・REST API からメッセージを受け付けて Claude にプロキシします。

---

## 機能一覧

| 機能                                 | コマンド / エンドポイント                                   |
| ------------------------------------ | ----------------------------------------------------------- |
| デーモン起動・停止・再起動・状態確認 | `openclaude start/stop/restart/status`                      |
| メッセージ送信（ストリーミング）     | `openclaude -m "メッセージ"`                                |
| stdin / パイプ入力                   | `echo "質問" \| openclaude`                                 |
| ログ表示                             | `openclaude logs [--tail N]`                                |
| セッション管理                       | `openclaude sessions`                                       |
| Cron ジョブ管理                      | `openclaude cron add/list/delete/run/edit`                  |
| HTTP REST API                        | `POST /message`, `POST /message/stream`, `GET /status` など |
| Cron REST API                        | `GET /cron`, `POST /cron`, `PATCH /cron/{id}`, `DELETE /cron/{id}` など |
| Discord 連携                         | デーモン起動時に自動接続（`openclaude config set` で設定）  |
| Slack 連携                           | デーモン起動時に自動接続（`openclaude config set` で設定）  |

---

## セットアップ

### 前提

- Linux／Windows（WSL2）
- Python >= 3.14
- [claude-agent-sdkが利用できる環境](https://platform.claude.com/docs/ja/agent-sdk/overview)

### 依存ライブラリ

| パッケージ                 | 用途                            |
| -------------------------- | ------------------------------- |
| `claude-agent-sdk>=0.1.48` | Claude AI エージェント SDK      |
| `fastapi>=0.115.0`         | REST API フレームワーク         |
| `uvicorn>=0.30.0`          | ASGI サーバー                   |
| `apscheduler>=3.10,<4`     | Cron ジョブスケジューラ（v3.x） |
| `discord.py>=2.3`          | Discord Bot（オプション）       |
| `slack-bolt>=1.18`         | Slack Bot（オプション）         |

### インストール

```bash
git clone <repository-url> ~/.openclaude
cd ~/.openclaude
pip install -r requirements.txt

# PATH に追加（~/.bashrc に追記）
echo '[ -d "$HOME/.openclaude" ] && export PATH="$HOME/.openclaude:$PATH"' >> ~/.bashrc

# タブ補完を有効化（~/.bashrc に追記）
echo 'eval "$(register-python-argcomplete openclaude)"' >> ~/.bashrc

source ~/.bashrc
```

> **注意:** プロジェクトは必ず `~/.openclaude/` に配置してください。
> `src/config.py` が `Path.home() / ".openclaude"` をベースパスとして使用するため、別ディレクトリでは動作しません。

---

## 使い方

### デーモン管理

```bash
# 起動（デフォルトポート: 28789）
openclaude start

# ポートを指定して起動
openclaude start --port 18789

# 停止
openclaude stop

# 再起動
openclaude restart

# 状態確認
openclaude status

# ログ表示
openclaude logs           # 全内容
openclaude logs --tail 50 # 末尾50行
```

### メッセージ送信

```bash
# シンプルな送信
openclaude -m "プロンプト"

# セッションを指定
openclaude --session-id work -m "プロンプト"

# stdin / パイプ
echo "質問" | openclaude
cat report.txt | openclaude -m "これを要約して"
git diff | openclaude -m "このdiffをレビューして"
```

### セッション管理

```bash
# 一覧表示
openclaude sessions

# 全セッション削除
openclaude sessions cleanup

# 特定セッション削除
openclaude sessions delete <session-id>
```

### Cron ジョブ

```bash
# ジョブ追加（毎朝9時に実行）
openclaude cron add "0 9 * * *" --name "morning" --session main -m "今日のタスクを整理して"

# 一覧表示
openclaude cron list

# 手動実行
openclaude cron run <job-id>

# ジョブを編集（フィールドを個別に変更可能）
openclaude cron edit <job-id> --name "新しい名前"
openclaude cron edit <job-id> --schedule "0 10 * * *" --message "更新したプロンプト"
openclaude cron edit <job-id> --session work
openclaude cron edit <job-id> --disable
openclaude cron edit <job-id> --enable

# 削除
openclaude cron delete <job-id>
```

### Discord 連携

Discord Bot を接続して、指定チャンネルのメッセージを受信・返信できます。

**前提:**

1. [Discord Developer Portal](https://discord.com/developers/applications) でアプリを作成し、Bot Token を取得
2. Bot 設定で **Message Content Intent** を有効化
3. OAuth2 URL でサーバーに Bot を招待

**セットアップ:**

```bash
# Bot Token を設定（必須）
openclaude config set discord.bot_token <YOUR_BOT_TOKEN>

# 対象チャンネル ID を設定（必須 — チャンネルを右クリック → チャンネル ID をコピー）
openclaude config set discord.channel_id <YOUR_CHANNEL_ID>

# 使用するセッションを変更する場合（デフォルト: "discord"）
openclaude config set discord.session_id discord2

# デーモンを再起動して反映
openclaude restart
```

> **注意:** `discord.channel_id` が未設定の場合、Bot は起動しません（WARNING ログが出ます）。
> Token は環境変数 `DISCORD_BOT_TOKEN` でも設定できます。

**動作確認:**

以下のログが出ていれば正常に起動しています。

```
Discord bot starting (channel_id=..., session=...)
Discord bot ready (logged in as <BotName>)
```

起動後は、設定したチャンネルに送信されたメッセージが Claude に転送され、Bot が返信します。

### Slack 連携

Slack Bot を接続して、DM・チャンネルメンションを Socket Mode で受信・返信できます。

**前提:**

1. [Slack API Portal](https://api.slack.com/apps) でアプリを作成しワークスペースにインストール
2. **Socket Mode** を有効化し、`connections:write` スコープを持つ App-Level Token（`xapp-` 始まり）を取得
3. Bot Token Scopes に `chat:write`, `reactions:write`, `channels:history`, `im:history`, `app_mentions:read` を追加
4. **Event Subscriptions** を有効化し、`message.im` と `app_mention` のボットイベントを購読
5. **Install App**画面からBot Token（xoxb始まり）を取得

**セットアップ:**

```bash
# Bot Token を設定（必須、xoxb- 始まり）
openclaude config set slack.bot_token <YOUR_BOT_TOKEN>

# App Token を設定（必須、xapp- 始まり）
openclaude config set slack.app_token <YOUR_APP_TOKEN>

# 使用するセッションを変更する場合（デフォルト: "slack"）
openclaude config set slack.session_id slack2

# デーモンを再起動して反映
openclaude restart
```

> **注意:** `slack.bot_token` と `slack.app_token` の両方が設定されている場合のみ Bot が起動します。
> Token は環境変数 `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` でも設定できます。

**詳細オプション:**

```bash
# DM を特定ユーザーに限定する（デフォルト: "open" — 全員許可）
openclaude config set slack.dm_policy allowlist
openclaude config set slack.allow_from '["U01234567", "U09876543"]'

# チャンネルメンションを特定チャンネルに限定する（デフォルト: "open" — 全チャンネル許可）
openclaude config set slack.channel_policy allowlist
openclaude config set slack.channels '["C01234567"]'
```

**動作確認:**

以下のログが出ていれば正常に起動しています。

```
Slack bot starting (session=...)
Slack bot ready (logged in as <BotName>, team=<TeamName>)
```

起動後は、Bot への DM および チャンネルでの `@メンション` が Claude に転送され、Bot が返信します。

### systemd 連携（セットアップ済みの場合）

```bash
systemctl --user start openclaude
systemctl --user stop openclaude
systemctl --user status openclaude
```

---

## REST API

デーモン起動後、デフォルトで `http://localhost:28789` でアクセスできます。

| メソッド | パス              | 説明                                 |
| -------- | ----------------- | ------------------------------------ |
| `POST`   | `/message`        | メッセージ送信（完全レスポンス）     |
| `POST`   | `/message/stream` | メッセージ送信（SSE ストリーミング） |
| `GET`    | `/status`         | デーモンステータスと PID             |
| `GET`    | `/sessions`       | セッション一覧                       |
| `DELETE` | `/sessions`       | 全セッション削除                     |
| `DELETE` | `/sessions/{id}`  | 指定セッション削除                   |
| `GET`    | `/cron`           | Cron ジョブ一覧                      |
| `POST`   | `/cron`           | Cron ジョブ追加                      |
| `PATCH`  | `/cron/{id}`      | Cron ジョブ編集                      |
| `DELETE` | `/cron/{id}`      | Cron ジョブ削除                      |
| `POST`   | `/cron/{id}/run`  | Cron ジョブ手動実行                  |
