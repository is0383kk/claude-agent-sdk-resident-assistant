"""メッセージ送信コマンド - cmd_message とストリーミングヘルパー。"""

import asyncio
import json
import logging
import sys
from typing import Any, cast

_CRAB = "🦀"
_logger = logging.getLogger(__name__)

try:
    from ..config import DEFAULT_PORT, SOCKET_PATH
    from ..process import get_daemon_status, start_daemon_process
    from ..utils import load_config
    from .config_cmds import config_get_nested
except ImportError:
    import sys as _sys
    from pathlib import Path as _Path

    _pkg_root = str(_Path(__file__).parent.parent.parent)
    if _pkg_root not in _sys.path:
        _sys.path.insert(0, _pkg_root)
    from src.config import DEFAULT_PORT, SOCKET_PATH
    from src.process import get_daemon_status, start_daemon_process
    from src.utils import load_config
    from src.commands.config_cmds import config_get_nested


def _is_daemon_up() -> bool:
    status, _ = get_daemon_status()
    return status == "running"


def resolve_message(message_arg: str | None) -> str | None:
    """コマンドライン引数と stdin からメッセージを解決する。

    stdin がパイプ/リダイレクトの場合は stdin の内容を読み込む。
    - message_arg が None の場合: stdin の内容をそのままメッセージにする。
    - message_arg がある場合: stdin の内容を前置きし、message_arg を後ろに結合する。
    """
    if sys.stdin.isatty():
        return message_arg

    stdin_text = sys.stdin.read().strip()
    if not stdin_text:
        return message_arg

    return stdin_text if message_arg is None else stdin_text + "\n\n" + message_arg


async def _read_json(reader: asyncio.StreamReader) -> dict[str, Any]:
    line = await reader.readline()
    if not line:
        return {}
    return cast(dict[str, Any], json.loads(line.decode("utf-8").strip()))


async def cmd_message(session_id: str, message: str) -> None:
    """エージェントにメッセージを送信してレスポンスをストリーミング表示する。"""
    if not _is_daemon_up():
        print("Starting OpenClaude daemon...")
        _cfg_port = config_get_nested(load_config(), "default.port") or DEFAULT_PORT
        start_daemon_process(_cfg_port)
        for _ in range(150):
            await asyncio.sleep(0.1)
            if SOCKET_PATH.exists():
                break
        else:
            print(
                "ERROR: Daemon did not start. Check daemon.log for details.",
                file=sys.stderr,
            )
            sys.exit(1)

    try:
        reader, writer = await asyncio.open_unix_connection(str(SOCKET_PATH))
    except (FileNotFoundError, ConnectionRefusedError) as e:
        print(f"ERROR: Cannot connect to daemon: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        print(f"{_CRAB} OpenClaude（{session_id}）")
        print("│")
        print("◇")

        request = {"type": "query", "session_id": session_id, "message": message}
        writer.write((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
        await writer.drain()

        while True:
            response = await _read_json(reader)
            resp_type = response.get("type")

            if resp_type == "chunk":
                text = response.get("text", "")
                print(text, end="", flush=True)

            elif resp_type == "done":
                print()
                break

            elif resp_type == "error":
                print()
                print(f"ERROR: {response.get('message')}", file=sys.stderr)
                sys.exit(1)

            else:
                _logger.debug("cmd_message: unknown response type: %s", resp_type)

    finally:
        writer.close()
        await writer.wait_closed()
