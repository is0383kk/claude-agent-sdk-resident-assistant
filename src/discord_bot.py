"""Discord Bot。指定チャンネルのメッセージを claude-agent-sdk に転送して返信する。"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

import discord

from .config import CONFIG_FILE, DISCORD_BOT_TOKEN_ENV, SOCKET_PATH

_logger = logging.getLogger(__name__)

MAX_DISCORD_LENGTH = 2000
DEFAULT_DISCORD_SESSION = "discord"


async def _send_long_message(channel: discord.abc.Messageable, text: str) -> None:
    """Discord のメッセージ文字数上限（2000文字）を超える場合は分割送信する。"""
    for i in range(0, len(text), MAX_DISCORD_LENGTH):
        await channel.send(text[i : i + MAX_DISCORD_LENGTH])


class _DiscordClient(discord.Client):
    """discord.Client のサブクラス。on_ready / on_message をオーバーライドして処理する。"""

    def __init__(self, channel_id: int, session_id: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._channel_id = channel_id
        self._session_id = session_id
        # GC によるタスク破棄を防ぐための参照保持セット
        self._tasks: set[asyncio.Task[None]] = set()

    async def on_ready(self) -> None:
        """接続完了イベント。"""
        channel = self.get_channel(self._channel_id)
        if channel is None:
            _logger.warning("Discord bot: channel %d not found", self._channel_id)
        _logger.info("Discord bot ready (logged in as %s)", self.user)

    async def on_message(self, message: discord.Message) -> None:
        """メッセージ受信イベント。ソケット通信を独立タスクに委譲する。"""
        if message.channel.id != self._channel_id:
            return
        if message.author == self.user:
            return
        # discord.py がこのタスクをキャンセルしても通信が途切れないよう独立タスクで処理する
        # タスク参照を _tasks に保持することで GC による破棄を防ぐ
        task = asyncio.create_task(self._handle_message(message))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _handle_message(self, message: discord.Message) -> None:
        """デーモンへのクエリ送信と Discord への返信を行う。"""
        try:
            reader, writer = await asyncio.open_unix_connection(str(SOCKET_PATH))
        except OSError:
            await _send_long_message(
                message.channel,  # type: ignore[arg-type]
                "ERROR: Cannot connect to daemon",
            )
            return

        chunks: list[str] = []
        error_msg: str | None = None
        try:
            payload = {"type": "query", "session_id": self._session_id, "message": message.content}
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

        if error_msg is not None:
            await _send_long_message(
                message.channel,  # type: ignore[arg-type]
                f"ERROR: {error_msg}",
            )
            return

        full_response = "".join(chunks)
        if full_response:
            try:
                await _send_long_message(
                    message.channel,  # type: ignore[arg-type]
                    full_response,
                )
            except discord.HTTPException as e:
                _logger.error("Discord send error: %s", e)


class DiscordBot:
    """Discord Bot。指定チャンネルのメッセージを claude-agent-sdk に転送する。"""

    def __init__(self, token: str, channel_id: int, session_id: str) -> None:
        """初期化。

        Args:
            token: Discord Bot Token。
            channel_id: 対象チャンネルID。
            session_id: 使用するセッションエイリアス。
        """
        intents = discord.Intents.default()
        intents.message_content = True
        self._client = _DiscordClient(channel_id=channel_id, session_id=session_id, intents=intents)
        self._token = token

    async def start(self) -> None:
        """Bot を起動する。デーモンの asyncio.gather から呼ぶ。"""
        async with self._client:
            await self._client.start(self._token)

    async def stop(self) -> None:
        """Bot を停止する。デーモンのシャットダウン時に呼ぶ。"""
        for task in list(self._client._tasks):
            task.cancel()
        if not self._client.is_closed():
            await self._client.close()


def _load_discord_config() -> dict[str, Any]:
    """config.json から discord セクションを読み込む。失敗時は空 dict を返す。"""
    try:
        data = json.loads(Path(CONFIG_FILE).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            section = data.get("discord", {})
            return section if isinstance(section, dict) else {}
        return {}
    except Exception:  # noqa: BLE001
        return {}


def create_discord_bot() -> "DiscordBot | None":
    """config.json または環境変数から設定を読み込み DiscordBot を返す。

    Token または channel_id が未設定の場合は None を返す（Bot なしでデーモン起動継続）。
    """
    cfg = _load_discord_config()

    # Token: config.json → 環境変数の順にフォールバック
    token: str | None = cfg.get("bot_token") or os.environ.get(DISCORD_BOT_TOKEN_ENV)  # noqa: S105
    if not token:
        _logger.warning(
            "Discord bot disabled: %s not set and discord.bot_token not in config",
            DISCORD_BOT_TOKEN_ENV,
        )
        return None

    # チャンネル ID: config.json からのみ取得（ハードコードなし）
    raw_channel_id = cfg.get("channel_id")
    if raw_channel_id is None:
        _logger.warning("Discord bot disabled: discord.channel_id not set in config")
        return None
    try:
        channel_id = int(raw_channel_id)
    except (ValueError, TypeError):
        _logger.warning("Discord bot disabled: discord.channel_id is invalid: %r", raw_channel_id)
        return None

    session_id: str = cfg.get("session_id", DEFAULT_DISCORD_SESSION)
    _logger.info("Discord bot starting (channel_id=%d, session=%s)", channel_id, session_id)
    return DiscordBot(token=token, channel_id=channel_id, session_id=session_id)
