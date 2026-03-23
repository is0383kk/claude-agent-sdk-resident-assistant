"""OpenClaude Heartbeat スケジューラ - 定期ポーリング。

config.json の heartbeat.every 設定に従い、定期的にメインセッションで
エージェントターンを実行して HEARTBEAT.md のチェックリストを処理する。
HEARTBEAT_OK のみのレスポンスはログのみで完了し、配信を行わない。
"""

import asyncio
import json
import logging
import re
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime, time
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

try:
    from .config import CONFIG_FILE, HEARTBEAT_MD
except ImportError:
    _pkg_root = str(Path(__file__).parent.parent)
    if _pkg_root not in sys.path:
        sys.path.insert(0, _pkg_root)
    from src.config import CONFIG_FILE, HEARTBEAT_MD

DEFAULT_HEARTBEAT_PROMPT: str = (
    "Read HEARTBEAT.md if it exists (workspace context). "
    "Follow it strictly. Do not infer or repeat old tasks from prior chats. "
    "If nothing needs attention, reply HEARTBEAT_OK."
)
HEARTBEAT_OK_TOKEN: str = "HEARTBEAT_OK"  # noqa: S105
DEFAULT_ACK_MAX_CHARS: int = 300


def parse_duration_to_seconds(every: str) -> int | None:
    """期間文字列（"30m", "1h" など）を秒数に変換する。

    "0m" / "0h" / 空文字 → None（無効化）

    Args:
        every: 期間文字列。"30m"（分）または "1h"（時間）形式。

    Returns:
        秒数（int）。無効化の場合は None。
    """
    if not every:
        return None
    every = every.strip()
    match = re.fullmatch(r"(\d+)([mh])", every)
    if not match:
        _logger.warning("heartbeat: invalid every format: %r", every)
        return None
    value, unit = int(match.group(1)), match.group(2)
    if value == 0:
        return None
    if unit == "m":
        return value * 60
    return value * 3600


def is_heartbeat_ok(text: str, ack_max_chars: int = DEFAULT_ACK_MAX_CHARS) -> bool:
    """HEARTBEAT_OK 判定ロジック。

    判定ルール:
    1. strip() 後が HEARTBEAT_OK のみ → True
    2. 先頭に HEARTBEAT_OK があり、残り文字数が ack_max_chars 以下 → True
    3. 末尾に HEARTBEAT_OK があり、先行文字数が ack_max_chars 以下 → True
    4. 中間にある場合 → False

    Args:
        text: エージェントのレスポンステキスト。
        ack_max_chars: 許容する追加文字数の上限。

    Returns:
        ACK（抑制）すべき場合 True。
    """
    stripped = text.strip()

    # ルール1: HEARTBEAT_OK のみ
    if stripped == HEARTBEAT_OK_TOKEN:
        return True

    # ルール2: 先頭に HEARTBEAT_OK
    if stripped.startswith(HEARTBEAT_OK_TOKEN):
        remainder = stripped[len(HEARTBEAT_OK_TOKEN) :]
        if len(remainder.strip()) <= ack_max_chars:
            return True

    # ルール3: 末尾に HEARTBEAT_OK
    if stripped.endswith(HEARTBEAT_OK_TOKEN):
        preceding = stripped[: -len(HEARTBEAT_OK_TOKEN)]
        if len(preceding.strip()) <= ack_max_chars:
            return True

    # ルール4: 中間にある（またはない）場合
    return False


def is_heartbeat_md_empty(path: Path) -> bool:
    """HEARTBEAT.md が実質的に空かどうか確認する。

    空行・Markdown ヘッダー（# 始まり）・HTML コメント行のみなら True。
    ファイルが存在しない・読み込めない場合は False（スキップしない）。

    Args:
        path: HEARTBEAT.md のパス。

    Returns:
        実質的に空の場合 True。
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return False

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("<!--") and stripped.endswith("-->"):
            continue
        return False
    return True


class HeartbeatScheduler:
    """定期ポーリングスケジューラ。

    config.json の heartbeat 設定に従い、一定間隔でメインセッションの
    エージェントターンを実行する。
    """

    def __init__(
        self,
        execute_fn: Callable[[str, str], Awaitable[str | None]],
    ) -> None:
        """初期化。

        Args:
            execute_fn: 実行コールバック。
                        シグネチャ: execute_fn(session_id, prompt) -> response_text | None
        """
        self._execute_fn = execute_fn
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """config.json を読み込み、有効な場合は定期実行タスクを起動する。"""
        config = self._load_config()
        heartbeat_cfg: dict[str, Any] = config.get("heartbeat", {})

        # disabled フラグの確認
        disabled = heartbeat_cfg.get("disabled", False)
        if disabled is True or str(disabled).lower() == "true":
            _logger.info("Heartbeat disabled (disabled flag)")
            return

        # every 設定の確認
        interval = parse_duration_to_seconds(str(heartbeat_cfg.get("every", "")))
        if interval is None:
            _logger.info("Heartbeat disabled (every not set)")
            return

        _logger.info("Heartbeat scheduler started (interval=%ds)", interval)
        self._task = asyncio.create_task(self._run_loop(interval))

    async def stop(self) -> None:
        """定期実行タスクをキャンセルして停止する。"""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                _logger.debug("heartbeat: task cancelled")
        self._task = None

    def _load_config(self) -> dict[str, Any]:
        """config.json を読み込んで返す。"""
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
        except (OSError, json.JSONDecodeError):
            return {}

    def _is_in_active_hours(self, active_hours: dict[str, Any]) -> bool:
        """現在時刻が active_hours 範囲内かチェックする。設定なし → True（常にアクティブ）。"""
        start_str = active_hours.get("start", "")
        end_str = active_hours.get("end", "")
        if not start_str or not end_str:
            return True

        try:
            now = datetime.now().time()
            start_h, start_m = map(int, start_str.split(":"))
            end_h, end_m = map(int, end_str.split(":"))
            return time(start_h, start_m) <= now <= time(end_h, end_m)
        except (ValueError, AttributeError):
            _logger.warning("heartbeat: invalid active_hours format, ignoring")
            return True

    async def _run_loop(self, interval_seconds: int) -> None:
        """指定間隔で _execute_heartbeat() を繰り返す asyncio 無限ループ。

        最初の実行は interval_seconds 待機後（デーモン起動直後は実行しない）。
        """
        while True:
            await asyncio.sleep(interval_seconds)
            await self._execute_heartbeat()

    async def _execute_heartbeat(self) -> None:
        """1回の Heartbeat ターンを実行する。"""
        config = self._load_config()
        heartbeat_cfg: dict[str, Any] = config.get("heartbeat", {})

        # アクティブ時間帯チェック
        if not self._is_in_active_hours(heartbeat_cfg.get("active_hours", {})):
            _logger.debug("heartbeat: skipped (outside active_hours)")
            return

        # HEARTBEAT.md が実質的に空ならスキップ
        if is_heartbeat_md_empty(HEARTBEAT_MD):
            _logger.debug("heartbeat: skipped (HEARTBEAT.md is empty)")
            return

        prompt: str = str(heartbeat_cfg.get("prompt", DEFAULT_HEARTBEAT_PROMPT))
        ack_max_chars: int = int(heartbeat_cfg.get("ack_max_chars", DEFAULT_ACK_MAX_CHARS))

        try:
            response = await self._execute_fn("main", prompt)
        except Exception as e:
            _logger.error("heartbeat: execute error: %s", e)
            return

        if response is None:
            _logger.warning("heartbeat: no response received")
            return

        if is_heartbeat_ok(response, ack_max_chars):
            _logger.info("HEARTBEAT_OK (suppressed)")
        else:
            _logger.info("Heartbeat alert (len=%d)", len(response))
