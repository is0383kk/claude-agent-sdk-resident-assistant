"""OpenClaude プロセス管理 - デーモンの起動・停止・状態確認とエントリーポイント。

cli.py から使用される関数群と、`python -m src.process` で起動するエントリーポイントを提供する。
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

try:
    from .config import BASE_DIR, DAEMON_LOG, DEFAULT_PORT, PID_FILE, SOCKET_PATH, setup_logging
except ImportError:
    _pkg_root = str(Path(__file__).parent.parent)
    if _pkg_root not in sys.path:
        sys.path.insert(0, _pkg_root)
    from src.config import BASE_DIR, DAEMON_LOG, DEFAULT_PORT, PID_FILE, SOCKET_PATH, setup_logging


# ---------------------------------------------------------------------------
# プロセス管理
# ---------------------------------------------------------------------------


def start_daemon_process(port: int = DEFAULT_PORT) -> None:
    """デーモンをデタッチされたバックグラウンドプロセスとして起動する。

    Args:
        port: API サーバーがリッスンするポート番号。
    """
    python = sys.executable
    with open(str(DAEMON_LOG), "a") as log:
        subprocess.Popen(  # noqa: S603
            [python, "-m", "src.process", "--port", str(port)],
            cwd=str(BASE_DIR),
            stdout=log,
            stderr=log,
            start_new_session=True,
        )


def stop_daemon_process() -> bool:
    """ソケット経由で停止リクエストを送信するか、PID ファイルで SIGTERM を送信する。

    Returns:
        停止リクエストの送信に成功した場合は True。
    """
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(str(SOCKET_PATH))
        sock.sendall((json.dumps({"type": "stop"}) + "\n").encode("utf-8"))
        resp_raw = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            resp_raw += chunk
            if b"\n" in resp_raw:
                break
        sock.close()
        return True
    except Exception as e:
        _logger.debug("stop_daemon_process: socket stop failed, falling back to PID: %s", e)

    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        os.kill(pid, signal.SIGTERM)
        return True
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError, OSError) as e:
        _logger.debug("stop_daemon_process: PID fallback failed: %s", e)

    return False


def get_daemon_status() -> tuple[str, int | None]:
    """デーモンのステータスと PID を返す。

    Returns:
        tuple: (status_string, pid_or_None)
            status_string は 'running', 'stopped', 'stale' のいずれか。
    """
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError, OSError):
        return "stopped", None

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "stale", pid
    except PermissionError as e:
        _logger.debug("get_daemon_status: cannot signal PID %d (no permission): %s", pid, e)

    if SOCKET_PATH.exists():
        return "running", pid

    return "stale", pid


# ---------------------------------------------------------------------------
# エントリーポイント
# ---------------------------------------------------------------------------


async def _main(port: int) -> None:
    """デーモンと API サーバーを起動してシャットダウンまで待機する。

    Args:
        port: API サーバーがリッスンするポート番号。
    """
    os.chdir(str(BASE_DIR))
    setup_logging()

    try:
        import uvicorn  # noqa: PLC0415

        from .api import app as api_app  # noqa: PLC0415
    except ImportError as e:
        _logger.warning("API server disabled (fastapi/uvicorn not installed): %s", e)
        from .daemon import OpenClaudeDaemon  # noqa: PLC0415

        daemon = OpenClaudeDaemon()
        await daemon.start()
        return

    class _NoSignalServer(uvicorn.Server):
        def install_signal_handlers(self) -> None:
            pass  # daemon 側のシグナルハンドラーを維持するため何もしない

    from .daemon import OpenClaudeDaemon  # noqa: PLC0415
    from .discord_bot import create_discord_bot  # noqa: PLC0415
    from .slack_bot import create_slack_bot  # noqa: PLC0415

    daemon = OpenClaudeDaemon()
    api_config = uvicorn.Config(api_app, host="0.0.0.0", port=port, log_level="info")  # noqa: S104
    api_server = _NoSignalServer(api_config)
    discord_bot = create_discord_bot()
    slack_bot = create_slack_bot()

    async def _run_daemon() -> None:
        await daemon.start()
        if discord_bot is not None:
            await discord_bot.stop()
        if slack_bot is not None:
            await slack_bot.stop()
        api_server.should_exit = True

    _logger.info("OpenClaude API server will start on port %d", port)
    coros: list[Any] = [_run_daemon(), api_server.serve()]
    if discord_bot is not None:
        coros.append(discord_bot.start())
    if slack_bot is not None:
        coros.append(slack_bot.start())
    await asyncio.gather(*coros)


if __name__ == "__main__":
    _parser = argparse.ArgumentParser(description="OpenClaude Daemon")
    _parser.add_argument("--port", type=int, default=DEFAULT_PORT, metavar="PORT")
    _args = _parser.parse_args()
    asyncio.run(_main(_args.port))
