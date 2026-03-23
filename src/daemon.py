"""OpenClaude デーモン - asyncio Unix ソケットサーバー。

セッション管理を行い、claude-agent-sdk へのリクエストをプロキシする。
プロセス管理・起動エントリーポイントは src/process.py を参照。
"""

import asyncio
import json
import logging
import os
import signal
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

try:
    from .config import BASE_DIR, PID_FILE, SESSIONS_DIR, SOCKET_PATH
    from .cron import CronScheduler
    from .heartbeat import HeartbeatScheduler
    from .session_store import SessionStore
    from .stream import handle_assistant_message, handle_result_message, handle_stream_event, send_json
except ImportError:
    _pkg_root = str(Path(__file__).parent.parent)
    if _pkg_root not in sys.path:
        sys.path.insert(0, _pkg_root)
    from src.config import BASE_DIR, PID_FILE, SESSIONS_DIR, SOCKET_PATH
    from src.cron import CronScheduler
    from src.heartbeat import HeartbeatScheduler
    from src.session_store import SessionStore
    from src.stream import handle_assistant_message, handle_result_message, handle_stream_event, send_json


class OpenClaudeDaemon:
    """Unix ソケットサーバーとして動作する常駐デーモン。"""

    def __init__(self) -> None:
        """セッションストア・サーバー状態・Cron スケジューラを初期化する。"""
        self._store = SessionStore()
        self._server: asyncio.AbstractServer | None = None
        self._shutdown_event = asyncio.Event()
        self._cron: CronScheduler = CronScheduler(self._execute_for_cron)
        self._heartbeat: HeartbeatScheduler = HeartbeatScheduler(self._execute_for_heartbeat)

    async def start(self) -> None:
        """Unix ソケットサーバーを起動し、シャットダウンまで待機する。"""
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        SOCKET_PATH.unlink(missing_ok=True)

        self._server = await asyncio.start_unix_server(self.handle_client, path=str(SOCKET_PATH))
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._shutdown_event.set)

        await self._cron.start()
        await self._heartbeat.start()
        _logger.info("OpenClaude daemon started (PID: %d)", os.getpid())

        async with self._server:
            await self._shutdown_event.wait()

        await self._cron.stop()
        await self._heartbeat.stop()
        SOCKET_PATH.unlink(missing_ok=True)
        PID_FILE.unlink(missing_ok=True)
        _logger.info("OpenClaude daemon stopped.")

    # ------------------------------------------------------------------
    # クライアントハンドラー
    # ------------------------------------------------------------------

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:  # noqa: C901
        """クライアント接続を受け付け、リクエストの種別に応じてハンドラーに振り分ける。"""
        try:
            line = await reader.readline()
            if not line:
                return
            request = json.loads(line.decode("utf-8").strip())
            req_type = request.get("type")

            if req_type == "query":
                await self.handle_query(request, writer)
            elif req_type == "sessions":
                await self.handle_sessions(writer)
            elif req_type == "cleanup_sessions":
                await self.handle_cleanup_sessions(writer)
            elif req_type == "delete_session":
                await self.handle_delete_session(request, writer)
            elif req_type == "stop":
                await self.handle_stop(writer)
            elif req_type == "cron_add":
                await self.handle_cron_add(request, writer)
            elif req_type == "cron_list":
                await self.handle_cron_list(writer)
            elif req_type == "cron_delete":
                await self.handle_cron_delete(request, writer)
            elif req_type == "cron_run":
                await self.handle_cron_run(request, writer)
            elif req_type == "cron_update":
                await self.handle_cron_update(request, writer)
            else:
                await send_json(writer, {"type": "error", "message": f"Unknown type: {req_type}"})
        except json.JSONDecodeError as e:
            _logger.error("Invalid JSON from client: %s", e)
            try:
                await send_json(writer, {"type": "error", "message": f"Invalid JSON: {e}"})
            except Exception as send_err:
                _logger.debug("Failed to send JSON decode error to client: %s", send_err)
        except Exception as e:
            _logger.error("Unhandled error in handle_client: %s", e)
            try:
                await send_json(writer, {"type": "error", "message": str(e)})
            except Exception as send_err:
                _logger.debug("Failed to send error response to client: %s", send_err)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception as close_err:
                _logger.debug("Failed to close writer: %s", close_err)

    # ------------------------------------------------------------------
    # リクエストハンドラー
    # ------------------------------------------------------------------

    async def handle_query(self, request: dict[str, Any], writer: asyncio.StreamWriter) -> None:
        """claude-agent-sdk を呼び出してレスポンスチャンクを CLI にストリーミングする。"""
        try:
            from claude_agent_sdk import (  # noqa: PLC0415
                AssistantMessage,
                ClaudeAgentOptions,
                ResultMessage,
                query,
            )
            from claude_agent_sdk.types import StreamEvent  # noqa: PLC0415
        except ImportError as e:
            await send_json(writer, {"type": "error", "message": f"claude_agent_sdk not installed: {e}"})
            return

        session_alias = request.get("session_id", "main")
        user_message = request.get("message", "")

        if not user_message.strip():
            await send_json(writer, {"type": "error", "message": "Empty message"})
            return

        _logger.info("query: session=%s, message_len=%d", session_alias, len(user_message))
        sdk_session_id = self._store.get(session_alias)

        options = ClaudeAgentOptions(
            setting_sources=["project"],
            permission_mode="acceptEdits",
            cwd=str(BASE_DIR),
            include_partial_messages=True,
            resume=sdk_session_id,
        )

        current_model: str | None = None
        full_text: str = ""
        has_stream_events: bool = False

        try:
            async for message in query(prompt=user_message, options=options):
                if hasattr(message, "subtype") and message.subtype == "init":
                    self._handle_init_event(message, session_alias)
                elif isinstance(message, StreamEvent):
                    full_text, has_stream_events = await handle_stream_event(
                        message, writer, full_text, has_stream_events
                    )
                elif isinstance(message, AssistantMessage):
                    current_model, full_text = await handle_assistant_message(
                        message, writer, has_stream_events, full_text
                    )
                elif isinstance(message, ResultMessage):
                    await handle_result_message(message, writer, current_model)
        except Exception as e:
            _logger.error("query error: session=%s, error=%s", session_alias, e)
            await send_json(writer, {"type": "error", "message": str(e)})

    def _handle_init_event(self, message: Any, session_alias: str) -> None:
        """セッション初期化メッセージから sdk_session_id を取得して保存する。"""
        new_id = (message.data or {}).get("session_id")
        if new_id:
            self._store[session_alias] = new_id
            self._store.save()

    async def handle_sessions(self, writer: asyncio.StreamWriter) -> None:
        """メモリ上のセッション一覧を JSON で返す。"""
        sessions = []
        for alias, sid in self._store.items():
            stats = self._store.read_stats(sid) if sid else {"last_active": None, "total_tokens": 0}
            sessions.append(
                {
                    "session_id": alias,
                    "sdk_session_id": sid,
                    "last_active": stats["last_active"],
                    "total_tokens": stats["total_tokens"],
                }
            )
        await send_json(writer, {"type": "sessions_list", "sessions": sessions})

    async def handle_stop(self, writer: asyncio.StreamWriter) -> None:
        """停止レスポンスを返した後、デーモンをシャットダウンする。"""
        await send_json(writer, {"type": "stopped"})
        asyncio.get_running_loop().call_later(0.2, self._shutdown_event.set)

    async def handle_cleanup_sessions(self, writer: asyncio.StreamWriter) -> None:
        """全セッションのメモリ・sessions.json・JSONL ファイルを削除する。"""
        _logger.info("cleanup_sessions: start, count=%d", len(self._store))
        deleted_files: list[str] = []
        failed_files: list[str] = []

        for sdk_session_id in list(self._store.values()):
            if sdk_session_id:
                deleted, error = self._store.delete_jsonl(sdk_session_id)
                if deleted:
                    deleted_files.append(deleted)
                if error:
                    failed_files.append(error)

        self._store.clear()
        self._store.save()

        _logger.info("cleanup_sessions: done, deleted=%d, failed=%d", len(deleted_files), len(failed_files))
        await send_json(
            writer,
            {
                "type": "cleanup_done",
                "deleted_count": len(deleted_files),
                "failed": failed_files,
            },
        )

    async def handle_delete_session(self, request: dict[str, Any], writer: asyncio.StreamWriter) -> None:
        """指定した alias のセッションのメモリ・sessions.json・JSONL ファイルを削除する。"""
        session_alias = request.get("session_id", "")

        if not session_alias:
            await send_json(writer, {"type": "error", "message": "session_id is required"})
            return

        _logger.info("delete_session: session=%s", session_alias)
        sdk_session_id = self._store.get(session_alias)
        if sdk_session_id is None:
            _logger.warning("delete_session: session not found: %s", session_alias)
            await send_json(writer, {"type": "error", "message": f"Session not found: {session_alias}"})
            return

        deleted_file, failed = self._store.delete_jsonl(sdk_session_id)
        del self._store[session_alias]
        self._store.save()

        _logger.info("delete_session: done, session=%s, deleted_file=%s", session_alias, deleted_file)
        await send_json(
            writer,
            {
                "type": "delete_done",
                "session_id": session_alias,
                "deleted_file": deleted_file,
                "failed": failed,
            },
        )

    # ------------------------------------------------------------------
    # Cron ハンドラー
    # ------------------------------------------------------------------

    async def handle_cron_add(self, request: dict[str, Any], writer: asyncio.StreamWriter) -> None:
        """Cron ジョブを追加する。"""
        name = request.get("name")
        schedule = request.get("schedule", "")
        session_id = request.get("session_id", "main")
        message = request.get("message", "")

        if not schedule:
            await send_json(writer, {"type": "error", "message": "schedule is required"})
            return
        if not message.strip():
            await send_json(writer, {"type": "error", "message": "message is required"})
            return

        try:
            job = self._cron.add_job(name=name, schedule=schedule, session_id=session_id, message=message)
        except ValueError as e:
            await send_json(writer, {"type": "error", "message": f"Invalid cron expression: {e}"})
            return

        await send_json(writer, {"type": "cron_added", **asdict(job)})

    async def handle_cron_list(self, writer: asyncio.StreamWriter) -> None:
        """Cron ジョブ一覧を返す。"""
        jobs = [asdict(job) for job in self._cron.list_jobs()]
        await send_json(writer, {"type": "cron_list", "jobs": jobs})

    async def handle_cron_delete(self, request: dict[str, Any], writer: asyncio.StreamWriter) -> None:
        """Cron ジョブを削除する。"""
        job_id = request.get("job_id", "")
        if not job_id:
            await send_json(writer, {"type": "error", "message": "job_id is required"})
            return

        try:
            self._cron.delete_job(job_id)
        except ValueError as e:
            await send_json(writer, {"type": "error", "message": str(e)})
            return

        await send_json(writer, {"type": "cron_deleted", "job_id": job_id})

    async def handle_cron_run(self, request: dict[str, Any], writer: asyncio.StreamWriter) -> None:
        """Cron ジョブを手動で即時実行する。実行は非同期で開始し、すぐに応答を返す。"""
        job_id = request.get("job_id", "")
        if not job_id:
            await send_json(writer, {"type": "error", "message": "job_id is required"})
            return

        try:
            await self._cron.run_job_now(job_id)
        except ValueError as e:
            await send_json(writer, {"type": "error", "message": str(e)})
            return

        await send_json(writer, {"type": "cron_run_started", "job_id": job_id})

    async def handle_cron_update(self, request: dict[str, Any], writer: asyncio.StreamWriter) -> None:
        """Cron ジョブのフィールドを部分更新する。"""
        job_id = request.get("job_id", "")
        patch = request.get("patch", {})

        if not job_id:
            await send_json(writer, {"type": "error", "message": "job_id is required"})
            return
        if not patch:
            await send_json(writer, {"type": "error", "message": "patch is empty"})
            return

        try:
            job = self._cron.update_job(job_id, patch)
        except ValueError as e:
            await send_json(writer, {"type": "error", "message": str(e)})
            return

        await send_json(writer, {"type": "cron_updated", **asdict(job)})

    async def _run_sdk_query(self, session_id: str, message: str) -> str:
        """claude-agent-sdk を呼び出し、ログのみで実行してレスポンステキストを返す共通ヘルパー。

        Cron ジョブと Heartbeat の両方から利用される。writer=None でストリーミングなし。

        Args:
            session_id: 実行するセッションのエイリアス。
            message: エージェントに送るプロンプト。

        Returns:
            エージェントのレスポンステキスト全文。
        """
        try:
            from claude_agent_sdk import (  # noqa: PLC0415
                AssistantMessage,
                ClaudeAgentOptions,
                ResultMessage,
                query,
            )
            from claude_agent_sdk.types import StreamEvent  # noqa: PLC0415
        except ImportError as e:
            raise RuntimeError(f"claude_agent_sdk not installed: {e}") from e

        sdk_session_id = self._store.get(session_id)

        options = ClaudeAgentOptions(
            setting_sources=["project"],
            permission_mode="acceptEdits",
            cwd=str(BASE_DIR),
            include_partial_messages=True,
            resume=sdk_session_id,
        )

        full_text: str = ""
        has_stream_events: bool = False
        current_model: str | None = None

        async for msg in query(prompt=message, options=options):
            if hasattr(msg, "subtype") and msg.subtype == "init":
                self._handle_init_event(msg, session_id)
            elif isinstance(msg, StreamEvent):
                full_text, has_stream_events = await handle_stream_event(msg, None, full_text, has_stream_events)
            elif isinstance(msg, AssistantMessage):
                current_model, full_text = await handle_assistant_message(msg, None, has_stream_events, full_text)
            elif isinstance(msg, ResultMessage):
                await handle_result_message(msg, None, current_model)

        return full_text

    async def _execute_for_cron(self, job_id: str, session_id: str, message: str) -> None:
        """CronScheduler から呼び出されるジョブ実行コールバック。"""
        _logger.info("cron_execute_query: job=%s, session=%s, message_len=%d", job_id, session_id, len(message))
        full_text = await self._run_sdk_query(session_id, message)
        _logger.info("cron_execute_query result: job=%s, text_len=%d", job_id, len(full_text))

    async def _execute_for_heartbeat(self, session_id: str, prompt: str) -> str | None:
        """HeartbeatScheduler から呼び出されるターン実行コールバック。"""
        _logger.info("heartbeat_execute_query: session=%s, message_len=%d", session_id, len(prompt))
        full_text = await self._run_sdk_query(session_id, prompt)
        _logger.info("heartbeat_execute_query result: text_len=%d", len(full_text))
        return full_text
