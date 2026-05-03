"""Casra 共通ユーティリティ関数。"""

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

try:
    from .config import CONFIG_FILE, SOCKET_PATH
except ImportError:
    import sys

    _pkg_root = str(Path(__file__).parent.parent)
    if _pkg_root not in sys.path:
        sys.path.insert(0, _pkg_root)
    from src.config import CONFIG_FILE, SOCKET_PATH


def atomic_write_json(path: Path, data: Any, dir_path: Path | None = None, indent: int | None = None) -> None:
    """JSON データをアトミックに書き込む。

    Args:
        path: 書き込み先ファイルパス。
        data: JSON シリアライズ可能なデータ。
        dir_path: 一時ファイルを作成するディレクトリ。None の場合は path の親ディレクトリを使用。
        indent: JSON インデント幅。None の場合は最小化出力。
    """
    target_dir = dir_path or path.parent
    fd, tmp = tempfile.mkstemp(dir=str(target_dir), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError as cleanup_err:
            _logger.debug("Failed to remove temp file %s: %s", tmp, cleanup_err)
        raise


def load_config() -> dict[str, Any]:
    """config.json を読み込む。ファイルが存在しない場合は空 dict を返す。"""
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except FileNotFoundError:
        _logger.debug("config.json not found, returning empty config")
    except Exception as e:
        _logger.warning("Failed to load config: %s", e)
    return {}


def save_config(data: dict[str, Any]) -> None:
    """config.json にアトミックに書き込む。"""
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(CONFIG_FILE, data, indent=2)
    except Exception as e:
        _logger.warning("Failed to save config: %s", e)


async def daemon_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Unix ソケット経由でデーモンに JSON リクエストを送信し、単一レスポンスを返す。

    Args:
        payload: デーモンに送信する JSON ペイロード。

    Returns:
        デーモンからの JSON レスポンス。空レスポンスの場合は空 dict。

    Raises:
        FileNotFoundError: ソケットファイルが存在しない場合。
        ConnectionRefusedError: 接続が拒否された場合。
    """
    reader, writer = await asyncio.open_unix_connection(str(SOCKET_PATH))
    try:
        writer.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        await writer.drain()
        line = await reader.readline()
        if not line:
            return {}
        return json.loads(line.decode("utf-8").strip())  # type: ignore[no-any-return]
    finally:
        writer.close()
        await writer.wait_closed()
