"""Cron 管理コマンド - cron add / list / delete / run。"""

import sys

_CRAB = "🦀"

try:
    from ..process import get_daemon_status
    from ..utils import daemon_request
except ImportError:
    import sys as _sys
    from pathlib import Path as _Path

    _pkg_root = str(_Path(__file__).parent.parent.parent)
    if _pkg_root not in _sys.path:
        _sys.path.insert(0, _pkg_root)
    from src.process import get_daemon_status
    from src.utils import daemon_request


def _is_daemon_up() -> bool:
    status, _ = get_daemon_status()
    return status == "running"


async def cmd_cron_add(schedule: str, name: str | None, session: str, message: str) -> None:
    """Cron ジョブを追加する。"""
    if not _is_daemon_up():
        print("OpenClaude daemon is not running.")
        return

    try:
        response = await daemon_request(
            {"type": "cron_add", "name": name, "schedule": schedule, "session_id": session, "message": message}
        )
        if response.get("type") == "cron_added":
            print(f"Cron job added: {response['id']} ({response['name']})")
            print(f"  schedule: {response['schedule']}")
            print(f"  session:  {response['session_id']}")
            print(f"  message:  {response['message']}")
        elif response.get("type") == "error":
            print(f"ERROR: {response.get('message')}", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


async def cmd_cron_list() -> None:
    """Cron ジョブ一覧を表示する。"""
    if not _is_daemon_up():
        print("OpenClaude daemon is not running.")
        return

    try:
        response = await daemon_request({"type": "cron_list"})
        if response.get("type") == "error":
            print(f"ERROR: {response.get('message')}", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    jobs = response.get("jobs", [])
    print(f"{_CRAB} OpenClaude Cron Jobs\n")
    if not jobs:
        print("No cron jobs registered.")
        return

    print(f"Jobs: {len(jobs)}\n")
    col_id = max(max(len(j["id"]) for j in jobs), 8)
    col_name = max(max(len(j["name"]) for j in jobs), 12)
    col_sched = max(max(len(j["schedule"]) for j in jobs), 10)
    col_session = max(max(len(j["session_id"]) for j in jobs), 7)
    col_status = max(max(len(j.get("last_run_status") or "-") for j in jobs), 6)
    header = (
        f"{'id':<{col_id}}  {'name':<{col_name}}  {'schedule':<{col_sched}}  "
        f"{'session':<{col_session}}  {'status':<{col_status}}  message"
    )
    print(header)
    for j in jobs:
        msg_preview = j["message"][:40] + ("..." if len(j["message"]) > 40 else "")
        print(
            f"{j['id']:<{col_id}}  {j['name']:<{col_name}}  {j['schedule']:<{col_sched}}  "
            f"{j['session_id']:<{col_session}}  {(j.get('last_run_status') or '-'):<{col_status}}  {msg_preview}"
        )


async def cmd_cron_delete(job_id: str) -> None:
    """Cron ジョブを削除する。"""
    if not _is_daemon_up():
        print("OpenClaude daemon is not running.")
        return

    try:
        response = await daemon_request({"type": "cron_delete", "job_id": job_id})
        if response.get("type") == "cron_deleted":
            print(f"Deleted cron job: {job_id}")
        elif response.get("type") == "error":
            print(f"ERROR: {response.get('message')}", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


async def cmd_cron_run(job_id: str) -> None:
    """Cron ジョブを手動で即時実行する。"""
    if not _is_daemon_up():
        print("OpenClaude daemon is not running.")
        return

    try:
        response = await daemon_request({"type": "cron_run", "job_id": job_id})
        if response.get("type") == "cron_run_started":
            print(f"Cron job started: {job_id}")
        elif response.get("type") == "error":
            print(f"ERROR: {response.get('message')}", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
