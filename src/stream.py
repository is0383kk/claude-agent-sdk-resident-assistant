"""claude-agent-sdk ストリームイベント処理ユーティリティ。

デーモンと Cron 実行の両方から使用される StreamEvent 処理関数と
Unix ソケット用 JSON 送信ヘルパーを提供する。
"""

import asyncio
import json
import logging
from typing import Any

_logger = logging.getLogger(__name__)


async def send_json(writer: asyncio.StreamWriter, data: dict[str, Any]) -> None:
    """JSON データを改行区切りで writer に送信する。"""
    line = json.dumps(data, ensure_ascii=False) + "\n"
    writer.write(line.encode("utf-8"))
    await writer.drain()


async def handle_stream_event(
    message: Any,
    writer: asyncio.StreamWriter | None,
    full_text: str,
    has_stream_events: bool,
) -> tuple[str, bool]:
    """StreamEvent からテキストチャンクを抽出する。writer が指定された場合はストリーミング送信も行う。"""
    event = message.event
    if event.get("type") == "content_block_delta":
        delta = event.get("delta", {})
        if delta.get("type") == "text_delta":
            has_stream_events = True
            chunk = delta.get("text", "")
            if chunk:
                full_text += chunk
                if writer is not None:
                    await send_json(writer, {"type": "chunk", "text": chunk})
    return full_text, has_stream_events


async def handle_assistant_message(
    message: Any,
    writer: asyncio.StreamWriter | None,
    has_stream_events: bool,
    full_text: str,
) -> tuple[str | None, str]:
    """AssistantMessage からモデル情報を取得する。

    StreamEvent 未着時はフォールバックとしてテキストを蓄積し、writer が指定された場合は送信もする。
    """
    from claude_agent_sdk.types import TextBlock  # noqa: PLC0415

    current_model: str | None = message.model if hasattr(message, "model") else None
    if not has_stream_events:
        for block in message.content:
            if isinstance(block, TextBlock):
                full_text += block.text
                if writer is not None:
                    await send_json(writer, {"type": "chunk", "text": block.text})
    return current_model, full_text


async def handle_result_message(
    message: Any,
    writer: asyncio.StreamWriter | None,
    current_model: str | None,
) -> None:
    """ResultMessage を処理する。writer が指定された場合は完了シグナルを送信する。"""
    usage = getattr(message, "usage", None) or {}
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    _logger.info(
        "query done: stop_reason=%s, model=%s, input_tokens=%d, output_tokens=%d",
        getattr(message, "stop_reason", "end_turn"),
        current_model,
        input_tokens,
        output_tokens,
    )
    if writer is not None:
        await send_json(
            writer,
            {
                "type": "done",
                "stop_reason": getattr(message, "stop_reason", "end_turn"),
                "model": current_model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_cost_usd": getattr(message, "total_cost_usd", None),
                "num_turns": getattr(message, "num_turns", 0),
            },
        )
