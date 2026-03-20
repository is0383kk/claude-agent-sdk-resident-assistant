"""OpenClaude API - Pydantic リクエスト/レスポンスモデル定義。"""

from pathlib import Path
import sys

try:
    from ..config import DEFAULT_SESSION_ID
except ImportError:
    _pkg_root = str(Path(__file__).parent.parent.parent)
    if _pkg_root not in sys.path:
        sys.path.insert(0, _pkg_root)
    from src.config import DEFAULT_SESSION_ID

from pydantic import BaseModel, ConfigDict, Field


class MessageRequest(BaseModel):
    """POST /message のリクエストボディ。"""

    session_id: str = DEFAULT_SESSION_ID
    message: str = Field(min_length=1)


class MessageResponse(BaseModel):
    """POST /message のレスポンスボディ。"""

    session_id: str
    response: str
    stop_reason: str | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_cost_usd: float | None = None
    num_turns: int | None = None


class SessionInfo(BaseModel):
    """セッション情報。"""

    session_id: str
    sdk_session_id: str | None = None
    last_active: str | None = None
    total_tokens: int = 0


class SessionsResponse(BaseModel):
    """GET /sessions のレスポンスボディ。"""

    sessions: list[SessionInfo]
    total: int


class CleanupResponse(BaseModel):
    """DELETE /sessions のレスポンスボディ。"""

    deleted_count: int
    failed: list[str] = []


class DeleteSessionResponse(BaseModel):
    """DELETE /sessions/{session_id} のレスポンスボディ。"""

    session_id: str
    deleted_file: str | None = None
    failed: str | None = None


class StatusResponse(BaseModel):
    """GET /status のレスポンスボディ。"""

    status: str
    pid: int


class CronAddRequest(BaseModel):
    """POST /cron のリクエストボディ。"""

    name: str | None = None
    schedule: str
    session_id: str = DEFAULT_SESSION_ID
    message: str = Field(min_length=1)


class CronJobResponse(BaseModel):
    """Cron ジョブ情報。"""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    schedule: str
    session_id: str
    message: str
    enabled: bool
    created_at: str
    last_run_at: str | None = None
    last_run_status: str | None = None


class CronListResponse(BaseModel):
    """GET /cron のレスポンスボディ。"""

    jobs: list[CronJobResponse]
    total: int
