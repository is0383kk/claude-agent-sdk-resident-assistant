"""Slack Bot。DM・チャンネルメンションを claude-agent-sdk に転送して返信する。"""

import asyncio
import json
import logging
import os
import re
from typing import Any

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

from .config import SLACK_APP_TOKEN_ENV, SLACK_BOT_TOKEN_ENV, SOCKET_PATH
from .utils import load_config

_logger = logging.getLogger(__name__)

MAX_SLACK_LENGTH = 4000
DEFAULT_SLACK_SESSION = "slack"


async def _send_long_message(
    client: Any,
    channel: str,
    thread_ts: str | None,
    text: str,
    placeholder_ts: str | None = None,
    placeholder_channel: str | None = None,
) -> None:
    """4000文字超の場合は分割して送信する。

    placeholder_ts が指定された場合、最初のチャンクはプレースホルダーを chat.update で
    上書きし、残りのチャンクは新規メッセージとして投稿する。
    """
    for i in range(0, len(text), MAX_SLACK_LENGTH):
        chunk = text[i : i + MAX_SLACK_LENGTH]
        if i == 0 and placeholder_ts is not None:
            await client.chat_update(
                channel=placeholder_channel or channel,
                ts=placeholder_ts,
                text=chunk,
            )
        else:
            kwargs: dict[str, Any] = {"channel": channel, "text": chunk}
            if thread_ts is not None:
                kwargs["thread_ts"] = thread_ts
            await client.chat_postMessage(**kwargs)


class SlackBot:
    """Slack Bot。DM・チャンネルメンションを claude-agent-sdk に転送する。"""

    def __init__(self, bot_token: str, app_token: str, session_id: str, config: dict[str, Any]) -> None:
        """初期化。

        Args:
            bot_token: Slack Bot Token（xoxb- 始まり）。
            app_token: Slack App Token（xapp- 始まり）。Socket Mode 接続に使用。
            session_id: 使用するセッションエイリアス。
            config: config.json の slack セクション。
        """
        self._app = AsyncApp(token=bot_token)
        self._handler = AsyncSocketModeHandler(self._app, app_token)
        self._session_id = session_id

        dm_policy = config.get("dm_policy", "open")
        self._dm_policy: str = dm_policy if isinstance(dm_policy, str) else "open"
        allow_from = config.get("allow_from", [])
        self._allow_from: list[str] = allow_from if isinstance(allow_from, list) else []

        channel_policy = config.get("channel_policy", "open")
        self._channel_policy: str = channel_policy if isinstance(channel_policy, str) else "open"
        channels = config.get("channels", [])
        self._channels: list[str] = channels if isinstance(channels, list) else []

        ack_reaction = config.get("ack_reaction", "eyes")
        self._ack_reaction: str = ack_reaction if isinstance(ack_reaction, str) else "eyes"

        typing_message = config.get("typing_message", ":hourglass_flowing_sand: 考え中...")
        self._typing_message: str = typing_message if isinstance(typing_message, str) else ""

        # GC によるタスク破棄を防ぐための参照保持セット
        self._tasks: set[asyncio.Task[None]] = set()

        self._register_handlers()

    def _register_handlers(self) -> None:
        """@app.event ハンドラーを登録する。"""

        @self._app.event("message")
        async def on_dm(event: dict[str, Any], ack: Any, client: Any) -> None:
            await ack()
            if event.get("bot_id"):
                return
            if event.get("channel_type") != "im":
                return
            if self._dm_policy == "allowlist" and event.get("user") not in self._allow_from:
                return
            task = asyncio.create_task(self._handle_message(event, client, is_mention=False))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

        @self._app.event("app_mention")
        async def on_mention(event: dict[str, Any], ack: Any, client: Any) -> None:
            await ack()
            if event.get("bot_id"):
                return
            if self._channel_policy == "allowlist" and event.get("channel") not in self._channels:
                return
            task = asyncio.create_task(self._handle_message(event, client, is_mention=True))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _handle_message(self, event: dict[str, Any], client: Any, is_mention: bool) -> None:
        """デーモンへのクエリ送信と Slack への返信を行う。"""
        channel: str = event.get("channel", "")
        event_ts: str = event.get("ts", "")

        if is_mention:
            raw_text: str = event.get("text", "")
            text = re.sub(r"<@[A-Z0-9]+>\s*", "", raw_text).strip()
            thread_ts: str | None = event_ts
        else:
            text = event.get("text", "")
            thread_ts = None

        # 処理中リアクションを追加
        if self._ack_reaction and event_ts:
            try:
                await client.reactions_add(
                    name=self._ack_reaction,
                    channel=channel,
                    timestamp=event_ts,
                )
            except Exception as e:  # noqa: BLE001
                _logger.warning("Failed to add ack reaction: %s", e)

        # タイピングプレースホルダーを投稿
        placeholder_ts: str | None = None
        placeholder_channel: str = channel
        if self._typing_message:
            try:
                ph_kwargs: dict[str, Any] = {"channel": channel, "text": self._typing_message}
                if thread_ts is not None:
                    ph_kwargs["thread_ts"] = thread_ts
                ph_resp = await client.chat_postMessage(**ph_kwargs)
                placeholder_ts = ph_resp["ts"]
                placeholder_channel = ph_resp["channel"]
            except Exception as e:  # noqa: BLE001
                _logger.warning("Failed to post typing placeholder: %s", e)

        chunks: list[str] = []
        error_msg: str | None = None

        try:
            try:
                reader, writer = await asyncio.open_unix_connection(str(SOCKET_PATH))
            except OSError as e:
                error_msg = f"Cannot connect to daemon: {e}"
                return

            try:
                payload = {"type": "query", "session_id": self._session_id, "message": text}
                writer.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
                await writer.drain()

                async for line in reader:
                    resp = json.loads(line)
                    if resp["type"] == "chunk":
                        chunks.append(resp["text"])
                    elif resp["type"] == "done":
                        break
                    elif resp["type"] == "error":
                        error_msg = resp.get("message", "unknown error")
                        break
            finally:
                writer.close()
                await writer.wait_closed()

            reply_text = f"ERROR: {error_msg}" if error_msg is not None else "".join(chunks)
            if reply_text:
                try:
                    await _send_long_message(
                        client, channel, thread_ts, reply_text, placeholder_ts, placeholder_channel
                    )
                except Exception as e:  # noqa: BLE001
                    _logger.error("Slack send error: %s", e)
            elif placeholder_ts is not None:
                # 応答が空の場合はプレースホルダーを削除
                try:
                    await client.chat_delete(channel=placeholder_channel, ts=placeholder_ts)
                except Exception as e:  # noqa: BLE001
                    _logger.warning("Failed to delete empty placeholder: %s", e)
        finally:
            # 処理中リアクションを除去
            if self._ack_reaction and event_ts:
                try:
                    await client.reactions_remove(
                        name=self._ack_reaction,
                        channel=channel,
                        timestamp=event_ts,
                    )
                except Exception as e:  # noqa: BLE001
                    _logger.warning("Failed to remove ack reaction: %s", e)

    async def start(self) -> None:
        """Bot を起動する。デーモンの asyncio.gather から呼ぶ。"""
        try:
            auth = await self._app.client.auth_test()
            _logger.info("Slack bot ready (logged in as %s, team=%s)", auth["user"], auth["team"])
        except Exception as e:  # noqa: BLE001
            _logger.warning("Slack bot auth_test failed: %s", e)
        await self._handler.start_async()

    async def stop(self) -> None:
        """Bot を停止する。デーモンのシャットダウン時に呼ぶ。"""
        for task in list(self._tasks):
            task.cancel()
        if hasattr(self._handler, "close_async"):
            await self._handler.close_async()
        elif hasattr(self._handler, "close"):
            await self._handler.close()


def _load_slack_config() -> dict[str, Any]:
    """config.json から slack セクションを読み込む。失敗時は空 dict を返す。"""
    section = load_config().get("slack", {})
    return section if isinstance(section, dict) else {}


def create_slack_bot() -> "SlackBot | None":
    """config.json または環境変数から設定を読み込み SlackBot を返す。

    bot_token または app_token が未設定の場合は None を返す（Bot なしでデーモン起動継続）。
    """
    cfg = _load_slack_config()

    # Bot Token: config.json → 環境変数の順にフォールバック
    bot_token: str | None = cfg.get("bot_token") or os.environ.get(SLACK_BOT_TOKEN_ENV)  # noqa: S105
    if not bot_token:
        _logger.warning("Slack bot disabled: bot_token not set")
        return None

    # App Token: config.json → 環境変数の順にフォールバック
    app_token: str | None = cfg.get("app_token") or os.environ.get(SLACK_APP_TOKEN_ENV)  # noqa: S105
    if not app_token:
        _logger.warning("Slack bot disabled: app_token not set")
        return None

    session_id: str = cfg.get("session_id", DEFAULT_SLACK_SESSION)
    _logger.info("Slack bot starting (session=%s)", session_id)
    return SlackBot(bot_token=bot_token, app_token=app_token, session_id=session_id, config=cfg)
