"""デーモン管理コマンド - start / stop / restart / status / logs。"""

import collections
import sys
import time

try:
    from ..config import DAEMON_LOG, DEFAULT_PORT, PID_FILE, SOCKET_PATH
    from ..process import get_daemon_status, start_daemon_process, stop_daemon_process
except ImportError:
    import sys as _sys
    from pathlib import Path as _Path

    _pkg_root = str(_Path(__file__).parent.parent.parent)
    if _pkg_root not in _sys.path:
        _sys.path.insert(0, _pkg_root)
    from src.config import DAEMON_LOG, DEFAULT_PORT, PID_FILE, SOCKET_PATH
    from src.process import get_daemon_status, start_daemon_process, stop_daemon_process


def cmd_start(port: int = DEFAULT_PORT) -> None:
    """デーモンと API サーバーを起動する。既に起動済みの場合はメッセージを表示して終了する。"""
    status, pid = get_daemon_status()
    if status == "running":
        print(f"OpenClaude is already running (PID: {pid})")
        return

    if status == "stale":
        print(f"Removing stale PID file (PID: {pid} is dead)...")
        PID_FILE.unlink(missing_ok=True)

    print("Starting OpenClaude daemon...")
    start_daemon_process(port)

    for _ in range(150):
        time.sleep(0.1)
        if SOCKET_PATH.exists():
            status, pid = get_daemon_status()
            if status == "running":
                print(f"OpenClaude started (PID: {pid})")
                return

    print(
        "ERROR: Daemon did not start in time. Check daemon.log for details.",
        file=sys.stderr,
    )
    sys.exit(1)


def cmd_stop() -> None:
    """デーモンを停止する。起動していない場合はメッセージを表示して終了する。"""
    status, _ = get_daemon_status()
    if status == "stopped":
        print("OpenClaude is not running.")
        return
    if status == "stale":
        PID_FILE.unlink(missing_ok=True)
        SOCKET_PATH.unlink(missing_ok=True)
        print("OpenClaude stopped (cleaned up stale state).")
        return

    print("Stopping OpenClaude daemon...")
    ok = stop_daemon_process()
    if ok:
        for _ in range(50):
            time.sleep(0.1)
            if not SOCKET_PATH.exists():
                break
        print("OpenClaude stopped.")
    else:
        print("ERROR: Failed to stop OpenClaude.", file=sys.stderr)
        sys.exit(1)


def cmd_restart(port: int = DEFAULT_PORT) -> None:
    """デーモンと API サーバーを再起動する。"""
    cmd_stop()
    time.sleep(0.5)
    cmd_start(port)


def cmd_status() -> None:
    """デーモンの稼働状態を表示する。"""
    status, pid = get_daemon_status()
    if status == "running":
        print(f"OpenClaude is running (PID: {pid})")
    elif status == "stale":
        print(f"OpenClaude has a stale PID file (PID: {pid}, process not found).")
    else:
        print("OpenClaude is stopped.")


def cmd_logs(tail: int | None = None) -> None:
    """デーモンログを表示する。"""
    if not DAEMON_LOG.exists():
        print("No log file found.", file=sys.stderr)
        return

    if tail is not None:
        with DAEMON_LOG.open(encoding="utf-8") as f:
            lines = list(collections.deque(f, maxlen=tail))
        print("".join(lines), end="")
    else:
        print(DAEMON_LOG.read_text(encoding="utf-8"), end="")
