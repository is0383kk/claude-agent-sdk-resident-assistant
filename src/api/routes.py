"""OpenClaude API - FastAPI エンドポイント定義とヘルパー関数。"""

import asyncio
import json
import logging
import os
import sys
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

_logger = logging.getLogger(__name__)

try:
    from ..config import SOCKET_PATH
    from ..utils import daemon_request
    from .models import (
        CleanupResponse,
        CronAddRequest,
        CronJobResponse,
        CronListResponse,
        CronUpdateRequest,
        DeleteSessionResponse,
        MessageRequest,
        MessageResponse,
        SessionInfo,
        SessionsResponse,
        StatusResponse,
    )
except ImportError:
    _pkg_root = str(Path(__file__).parent.parent.parent)
    if _pkg_root not in sys.path:
        sys.path.insert(0, _pkg_root)
    from src.config import SOCKET_PATH
    from src.utils import daemon_request
    from src.api.models import (
        CleanupResponse,
        CronAddRequest,
        CronJobResponse,
        CronListResponse,
        CronUpdateRequest,
        DeleteSessionResponse,
        MessageRequest,
        MessageResponse,
        SessionInfo,
        SessionsResponse,
        StatusResponse,
    )

# ---------------------------------------------------------------------------
# FastAPI アプリ
# ---------------------------------------------------------------------------

app = FastAPI(title="OpenClaude API", version="0.1.0")

# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


async def _request_daemon(payload: dict[str, Any]) -> dict[str, Any]:
    """Unix ソケット経由でデーモンに JSON リクエストを送信し、単一レスポンスを返す。

    Raises:
        HTTPException: デーモンが起動していない場合（503）。
    """
    try:
        resp = await daemon_request(payload)
    except (FileNotFoundError, ConnectionRefusedError) as e:
        raise HTTPException(status_code=503, detail=f"Daemon is not running: {e}") from e
    if not resp:
        raise HTTPException(status_code=503, detail="Empty response from daemon")
    return resp


def _sse_event(data: dict[str, Any]) -> str:
    r"""Dict を SSE イベント文字列に変換する。

    Returns:
        `data: {...}\\n\\n` 形式の SSE イベント文字列。
    """
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _build_query_payload(request: MessageRequest) -> dict[str, Any]:
    """MessageRequest からデーモンに送信するクエリペイロードを構築する。"""
    return {"type": "query", "session_id": request.session_id, "message": request.message}


async def _stream_message_generator(request: MessageRequest) -> AsyncGenerator[str, None]:
    r"""Unix ソケット経由でデーモンと通信し、SSE イベントを yield する。

    Yields:
        SSE フォーマットの文字列（`data: {...}\n\n`）。
    """
    try:
        reader, writer = await asyncio.open_unix_connection(str(SOCKET_PATH))
    except (FileNotFoundError, ConnectionRefusedError) as e:
        yield _sse_event({"type": "error", "message": f"Daemon is not running: {e}"})
        return

    try:
        writer.write((json.dumps(_build_query_payload(request), ensure_ascii=False) + "\n").encode("utf-8"))
        await writer.drain()

        while True:
            line = await reader.readline()
            if not line:
                break
            resp = json.loads(line.decode("utf-8").strip())
            resp_type = resp.get("type")

            if resp_type == "chunk":
                yield _sse_event({"type": "chunk", "text": resp.get("text", "")})
            elif resp_type == "done":
                yield _sse_event(resp)
                break
            elif resp_type == "error":
                yield _sse_event({"type": "error", "message": resp.get("message", "Unknown error")})
                break
    finally:
        writer.close()
        await writer.wait_closed()


# ---------------------------------------------------------------------------
# エンドポイント
# ---------------------------------------------------------------------------


@app.post("/message/stream")
async def post_message_stream(request: MessageRequest) -> StreamingResponse:
    r"""デーモンにメッセージを転送し、SSE ストリーミングでレスポンスを返す。

    Returns:
        SSE ストリーミングレスポンス（`text/event-stream`）。
        各イベントは `data: {...}\n\n` 形式で、type は `chunk` / `done` / `error`。
    """
    return StreamingResponse(
        _stream_message_generator(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/message")
async def post_message(request: MessageRequest) -> MessageResponse:
    """デーモンにメッセージを転送し、完全なレスポンスを返す。

    Raises:
        HTTPException: デーモンが起動していない場合（503）またはデーモンがエラーを返した場合（500）。
    """
    chunks: list[str] = []
    done_resp: dict[str, Any] = {}

    try:
        reader, writer = await asyncio.open_unix_connection(str(SOCKET_PATH))
    except (FileNotFoundError, ConnectionRefusedError) as e:
        raise HTTPException(status_code=503, detail=f"Daemon is not running: {e}") from e

    try:
        writer.write((json.dumps(_build_query_payload(request), ensure_ascii=False) + "\n").encode("utf-8"))
        await writer.drain()

        while True:
            line = await reader.readline()
            if not line:
                break
            resp = json.loads(line.decode("utf-8").strip())
            resp_type = resp.get("type")

            if resp_type == "chunk":
                chunks.append(resp.get("text", ""))
            elif resp_type == "done":
                done_resp = resp
                break
            elif resp_type == "error":
                raise HTTPException(status_code=500, detail=resp.get("message", "Unknown error"))
    finally:
        writer.close()
        await writer.wait_closed()

    return MessageResponse(
        session_id=request.session_id,
        response="".join(chunks),
        stop_reason=done_resp.get("stop_reason"),
        model=done_resp.get("model"),
        input_tokens=done_resp.get("input_tokens"),
        output_tokens=done_resp.get("output_tokens"),
        total_cost_usd=done_resp.get("total_cost_usd"),
        num_turns=done_resp.get("num_turns"),
    )


@app.get("/cron")
async def get_cron() -> CronListResponse:
    """Cron ジョブ一覧を取得する。

    Raises:
        HTTPException: デーモンが起動していない場合（503）またはエラーが発生した場合（500）。
    """
    resp = await _request_daemon({"type": "cron_list"})
    if resp.get("type") == "error":
        raise HTTPException(status_code=500, detail=resp.get("message", "Unknown error"))
    jobs = [CronJobResponse(**j) for j in resp.get("jobs", [])]
    return CronListResponse(jobs=jobs, total=len(jobs))


@app.post("/cron", status_code=201)
async def post_cron(request: CronAddRequest) -> CronJobResponse:
    """Cron ジョブを追加する。

    Raises:
        HTTPException: 不正な cron 式（422）、デーモン未起動（503）、エラー（500）。
    """
    resp = await _request_daemon(
        {
            "type": "cron_add",
            "name": request.name,
            "schedule": request.schedule,
            "session_id": request.session_id,
            "message": request.message,
        }
    )
    if resp.get("type") == "error":
        msg = resp.get("message", "Unknown error")
        status_code = 422 if "invalid cron" in msg.lower() else 500
        raise HTTPException(status_code=status_code, detail=msg)
    return CronJobResponse.model_validate(resp)


@app.patch("/cron/{job_id}")
async def update_cron(job_id: str, request: CronUpdateRequest) -> CronJobResponse:
    """Cron ジョブを部分更新する。

    Raises:
        HTTPException: ジョブが見つからない場合（404）、不正な cron 式 / patch が空（422）、
                       デーモン未起動（503）、エラー（500）。
    """
    patch: dict[str, Any] = {
        k: v
        for k, v in {
            "name": request.name,
            "schedule": request.schedule,
            "session_id": request.session_id,
            "message": request.message,
            "enabled": request.enabled,
        }.items()
        if v is not None
    }
    if not patch:
        raise HTTPException(status_code=422, detail="patch is empty")

    resp = await _request_daemon({"type": "cron_update", "job_id": job_id, "patch": patch})
    if resp.get("type") == "error":
        msg = resp.get("message", "Unknown error")
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        if "invalid cron" in msg.lower() or "patch is empty" in msg.lower():
            raise HTTPException(status_code=422, detail=msg)
        raise HTTPException(status_code=500, detail=msg)
    return CronJobResponse.model_validate(resp)


@app.delete("/cron/{job_id}")
async def delete_cron(job_id: str) -> dict[str, str]:
    """Cron ジョブを削除する。

    Raises:
        HTTPException: ジョブが見つからない場合（404）、デーモン未起動（503）、エラー（500）。
    """
    resp = await _request_daemon({"type": "cron_delete", "job_id": job_id})
    if resp.get("type") == "error":
        msg = resp.get("message", "Unknown error")
        status_code = 404 if "not found" in msg.lower() else 500
        raise HTTPException(status_code=status_code, detail=msg)
    return {"job_id": resp.get("job_id", job_id)}


@app.post("/cron/{job_id}/run")
async def run_cron(job_id: str) -> dict[str, str]:
    """Cron ジョブを手動で即時実行する。

    Raises:
        HTTPException: ジョブが見つからない場合（404）、デーモン未起動（503）、エラー（500）。
    """
    resp = await _request_daemon({"type": "cron_run", "job_id": job_id})
    if resp.get("type") == "error":
        msg = resp.get("message", "Unknown error")
        status_code = 404 if "not found" in msg.lower() else 500
        raise HTTPException(status_code=status_code, detail=msg)
    return {"job_id": resp.get("job_id", job_id), "status": "started"}


@app.get("/status")
async def get_status() -> StatusResponse:
    """デーモンのステータスと PID を返す。

    Returns:
        デーモンのステータス（常に running）と PID。
    """
    return StatusResponse(status="running", pid=os.getpid())


@app.get("/sessions")
async def get_sessions() -> SessionsResponse:
    """デーモンからセッション一覧を取得して返す。

    Raises:
        HTTPException: デーモンが起動していない場合（503）またはエラーが発生した場合（500）。
    """
    resp = await _request_daemon({"type": "sessions"})
    if resp.get("type") == "error":
        raise HTTPException(status_code=500, detail=resp.get("message", "Unknown error"))
    sessions = [SessionInfo(**s) for s in resp.get("sessions", [])]
    return SessionsResponse(sessions=sessions, total=len(sessions))


@app.delete("/sessions")
async def cleanup_sessions() -> CleanupResponse:
    """全セッションを削除する。

    Raises:
        HTTPException: デーモンが起動していない場合（503）またはエラーが発生した場合（500）。
    """
    resp = await _request_daemon({"type": "cleanup_sessions"})
    if resp.get("type") == "error":
        raise HTTPException(status_code=500, detail=resp.get("message", "Unknown error"))
    return CleanupResponse(
        deleted_count=resp.get("deleted_count", 0),
        failed=resp.get("failed", []),
    )


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> DeleteSessionResponse:
    """指定したセッションを削除する。

    Raises:
        HTTPException: セッションが見つからない場合（404）、デーモン未起動（503）、エラー（500）。
    """
    resp = await _request_daemon({"type": "delete_session", "session_id": session_id})
    if resp.get("type") == "error":
        msg = resp.get("message", "Unknown error")
        status_code = 404 if "not found" in msg.lower() else 500
        raise HTTPException(status_code=status_code, detail=msg)
    return DeleteSessionResponse(
        session_id=resp.get("session_id", session_id),
        deleted_file=resp.get("deleted_file"),
        failed=resp.get("failed"),
    )
