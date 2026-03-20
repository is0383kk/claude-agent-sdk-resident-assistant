"""OpenClaude API パッケージ。

`from src.api import app` で FastAPI アプリインスタンスを取得できる。

スタンドアロン起動:
    python3 -m src.api          (~/.openclaude/ から)
    python3 -m src.api --port 8080
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

_logger = logging.getLogger(__name__)

try:
    from .routes import app
    from ..config import DEFAULT_PORT, WEBHOOK_PID_FILE, setup_logging
except ImportError:
    _pkg_root = str(Path(__file__).parent.parent.parent)
    if _pkg_root not in sys.path:
        sys.path.insert(0, _pkg_root)
    from src.api.routes import app
    from src.config import DEFAULT_PORT, WEBHOOK_PID_FILE, setup_logging

__all__ = ["app"]


async def _main(port: int) -> None:
    """API サーバーを起動してシャットダウンまで待機する。"""
    import uvicorn  # noqa: PLC0415

    setup_logging()
    WEBHOOK_PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    _logger.info("OpenClaude API server starting on port %d (PID: %d)", port, os.getpid())

    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")  # noqa: S104
    server = uvicorn.Server(config)
    try:
        await server.serve()
    finally:
        WEBHOOK_PID_FILE.unlink(missing_ok=True)
        _logger.info("OpenClaude API server stopped.")


if __name__ == "__main__":
    _parser = argparse.ArgumentParser(description="OpenClaude API Server")
    _parser.add_argument("--port", type=int, default=DEFAULT_PORT, metavar="PORT")
    _args = _parser.parse_args()
    asyncio.run(_main(_args.port))
