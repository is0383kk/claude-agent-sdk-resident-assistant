"""セッション管理 - alias → sdk_session_id マッピングの永続化と JSONL 操作。"""

import json
import logging
import sys
from pathlib import Path
from typing import Any, Iterator

_logger = logging.getLogger(__name__)

try:
    from .config import CLAUDE_PROJECTS_DIR, SESSIONS_DIR, SESSIONS_JSON
    from .utils import atomic_write_json
except ImportError:
    _pkg_root = str(Path(__file__).parent.parent)
    if _pkg_root not in sys.path:
        sys.path.insert(0, _pkg_root)
    from src.config import CLAUDE_PROJECTS_DIR, SESSIONS_DIR, SESSIONS_JSON
    from src.utils import atomic_write_json


class SessionStore:
    """セッション alias → sdk_session_id マッピングを管理する。"""

    def __init__(self) -> None:
        """sessions.json から読み込んで初期化する。"""
        self._sessions: dict[str, str] = self._load()

    # ------------------------------------------------------------------
    # dict-like インターフェース
    # ------------------------------------------------------------------

    def get(self, alias: str) -> str | None:
        """Alias に対応する sdk_session_id を返す。なければ None。"""
        return self._sessions.get(alias)

    def items(self) -> Iterator[tuple[str, str]]:
        """(alias, sdk_session_id) のイテレータを返す。"""
        return iter(self._sessions.items())

    def values(self) -> Iterator[str]:
        """sdk_session_id のイテレータを返す。"""
        return iter(self._sessions.values())

    def __setitem__(self, alias: str, sdk_id: str) -> None:
        """Alias と sdk_session_id をセットする。"""
        self._sessions[alias] = sdk_id

    def __delitem__(self, alias: str) -> None:
        """Alias を削除する。"""
        del self._sessions[alias]

    def __len__(self) -> int:
        """セッション数を返す。"""
        return len(self._sessions)

    def __contains__(self, alias: object) -> bool:
        """Alias が存在するか。"""
        return alias in self._sessions

    def clear(self) -> None:
        """全セッションをメモリから削除する。"""
        self._sessions = {}

    # ------------------------------------------------------------------
    # 永続化
    # ------------------------------------------------------------------

    def save(self) -> None:
        """sessions.json にアトミック書き込みする。"""
        try:
            atomic_write_json(SESSIONS_JSON, self._sessions, dir_path=SESSIONS_DIR)
        except Exception as e:
            _logger.warning("Failed to save sessions: %s", e)

    def _load(self) -> dict[str, str]:
        """sessions.json から alias → sdk_session_id を読み込む。"""
        try:
            data = json.loads(SESSIONS_JSON.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        except FileNotFoundError:
            _logger.debug("sessions.json not found, starting with empty sessions")
        except Exception as e:
            _logger.warning("Failed to load sessions: %s", e)
        return {}

    # ------------------------------------------------------------------
    # JSONL 操作
    # ------------------------------------------------------------------

    def delete_jsonl(self, sdk_session_id: str) -> tuple[str | None, str | None]:
        """sdk_session_id に対応する JSONL ファイルを削除して (deleted_name, error_message) を返す。"""
        jsonl_path = CLAUDE_PROJECTS_DIR / f"{sdk_session_id}.jsonl"
        try:
            jsonl_path.unlink()
            return jsonl_path.name, None
        except FileNotFoundError:
            _logger.debug("JSONL already absent: %s", jsonl_path.name)
            return None, None
        except Exception as e:
            return None, f"{jsonl_path.name}: {e}"

    def read_stats(self, sdk_session_id: str) -> dict[str, Any]:
        """sdk_session_id に対応する JSONL から last_active と total_tokens を返す。"""
        jsonl_path = CLAUDE_PROJECTS_DIR / f"{sdk_session_id}.jsonl"
        last_active: str | None = None
        total_tokens = 0

        try:
            lines = jsonl_path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return {"last_active": None, "total_tokens": 0}

        for raw in lines:
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError as e:
                _logger.warning("Skipping malformed JSONL line in %s: %s", jsonl_path.name, e)
                continue
            if "timestamp" in entry:
                last_active = entry["timestamp"]
            msg = entry.get("message")
            if isinstance(msg, dict) and msg.get("stop_reason"):
                usage = msg.get("usage") or {}
                total_tokens += usage.get("input_tokens", 0)
                total_tokens += usage.get("cache_creation_input_tokens", 0)
                total_tokens += usage.get("cache_read_input_tokens", 0)
                total_tokens += usage.get("output_tokens", 0)

        return {"last_active": last_active, "total_tokens": total_tokens}
