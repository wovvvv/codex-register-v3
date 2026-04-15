"""
cli_proxy_monitor.py — CPA auth-file monitor and history helpers.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

import aiosqlite
import httpx
from loguru import logger

import src.settings_db as settings_db
from src.db import DB_PATH
from src.integrations.cli_proxy import get_cli_proxy_runtime_config

_UTC8 = timezone(timedelta(hours=8))
_AUTH_FILES_PATH = "/v0/management/auth-files"
_API_CALL_CANDIDATES = (
    "/v0/management/api-call",
    "/api-call",
    "/v0/api-call",
    "/management/api-call",
)
_INVALID_TOKEN_KEYWORDS = [
    '额度获取失败：401',
    '"status": 401',
    '"status":401',
    'token_invalidated',
    'token_revoked',
    'Your authentication token has been invalidated.',
    'Encountered invalidated oauth token for user',
]


def _now_iso_utc8() -> str:
    return datetime.now(_UTC8).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def _status_message_has_401(status_message: str) -> bool:
    text = str(status_message or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if "401" in lowered or "unauthorized" in lowered:
        return True
    try:
        obj = json.loads(text)
    except Exception:
        return False

    if isinstance(obj, dict):
        try:
            if int(obj.get("status", 0) or 0) == 401:
                return True
        except Exception:
            pass
        err = obj.get("error", {})
        if isinstance(err, dict):
            try:
                if int(err.get("status", 0) or 0) == 401:
                    return True
            except Exception:
                pass
    return False


def match_status_401_reason(file_obj: dict[str, Any]) -> str:
    try:
        if int(file_obj.get("status", 0) or 0) == 401:
            return "status_401"
    except Exception:
        pass

    if _status_message_has_401(str(file_obj.get("status_message", "") or "")):
        return "status_message_401"
    return ""


async def list_auth_files(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    runtime = get_cli_proxy_runtime_config(cfg)
    url = f"{runtime['base_url']}{_AUTH_FILES_PATH}"
    headers = {"Authorization": f"Bearer {runtime['api_key']}"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        payload = response.json()
    if isinstance(payload, dict):
        files = payload.get("files", [])
        return files if isinstance(files, list) else []
    return []


async def delete_auth_file(cfg: dict[str, Any], name: str) -> dict[str, Any]:
    runtime = get_cli_proxy_runtime_config(cfg)
    url = f"{runtime['base_url']}{_AUTH_FILES_PATH}"
    headers = {"Authorization": f"Bearer {runtime['api_key']}"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.delete(url, headers=headers, params={"name": name})
    try:
        payload = response.json()
    except Exception:
        payload = {"raw": response.text}

    ok = 200 <= response.status_code < 300
    if isinstance(payload, dict):
        status = str(payload.get("status", "") or "").lower()
        if status in {"ok", "success"}:
            ok = True
        elif status in {"error", "failed", "fail"} or payload.get("error"):
            ok = False
    return {"ok": ok, "http_status": response.status_code, "payload": payload}


async def _post_probe_payload(cfg: dict[str, Any], payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    runtime = get_cli_proxy_runtime_config(cfg)
    headers = {"Authorization": f"Bearer {runtime['api_key']}"}
    async with httpx.AsyncClient(timeout=float(timeout)) as client:
        for path in _API_CALL_CANDIDATES:
            url = f"{runtime['base_url']}{path}"
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code == 404:
                continue
            response.raise_for_status()
            return response.json()
    raise RuntimeError("未找到可用的 CPA probe 端点")


def _probe_body_reason(body: str) -> str:
    text = str(body or "")
    if _status_message_has_401(text):
        return "probe_body_401"
    for keyword in _INVALID_TOKEN_KEYWORDS:
        if keyword in text:
            return f"probe_{keyword}"
    return ""


async def probe_auth_401(cfg: dict[str, Any], file_obj: dict[str, Any], timeout: int) -> tuple[bool, str]:
    auth_index = str(file_obj.get("auth_index", "") or "").strip()
    provider = str(file_obj.get("provider", "") or "").strip().lower()
    if not auth_index or provider != "codex":
        return False, ""

    probe_payload = {
        "auth_index": auth_index,
        "method": "POST",
        "url": "https://chatgpt.com/backend-api/codex/responses/compact",
        "header": {
            "Authorization": "Bearer $TOKEN$",
            "Content-Type": "application/json",
            "User-Agent": "codex_cli_rs/0.101.0",
        },
        "data": json.dumps(
            {"model": "gpt-5.1-codex", "input": [{"role": "user", "content": "ping"}]},
            ensure_ascii=False,
        ),
    }

    try:
        payload = await _post_probe_payload(cfg, probe_payload, timeout)
    except Exception as exc:
        return False, f"probe_error:{exc}"

    try:
        status_code = int(payload.get("status_code", 0) or 0)
    except Exception:
        status_code = 0
    if status_code == 401:
        return True, "probe_status_401"

    reason = _probe_body_reason(str(payload.get("body", "") or ""))
    if reason:
        return True, reason
    return False, ""


async def insert_monitor_history(record: dict[str, Any]) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO cli_proxy_monitor_history
                (deleted_at, file_name, email, provider, reason, source, status_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(record.get("deleted_at", "") or ""),
                str(record.get("file_name", "") or ""),
                str(record.get("email", "") or ""),
                str(record.get("provider", "") or ""),
                str(record.get("reason", "") or ""),
                str(record.get("source", "") or ""),
                str(record.get("status_message", "") or ""),
            ),
        )
        await db.commit()


async def list_monitor_history(limit: int = 100) -> list[dict[str, Any]]:
    limit_value = max(1, int(limit))
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT id, deleted_at, file_name, email, provider, reason, source, status_message
            FROM cli_proxy_monitor_history
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit_value,),
        )
        rows = await cur.fetchall()
    return [dict(row) for row in rows]


async def scan_and_delete_invalid_auth_files(
    cfg: dict[str, Any],
    *,
    active_probe: bool,
    probe_timeout: int,
    record_history: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    files = await list_auth_files(cfg)
    deleted = 0
    records: list[dict[str, Any]] = []

    for file_obj in files:
        if not isinstance(file_obj, dict):
            continue

        source = ""
        reason = match_status_401_reason(file_obj)
        if reason:
            source = "status_scan"
        elif active_probe:
            hit, probe_reason = await probe_auth_401(cfg, file_obj, probe_timeout)
            if hit:
                source = "active_probe"
                reason = probe_reason

        file_name = str(file_obj.get("name", "") or "").strip()
        if not reason or not file_name:
            continue

        result = await delete_auth_file(cfg, file_name)
        if not result.get("ok"):
            continue

        record = {
            "deleted_at": _now_iso_utc8(),
            "file_name": file_name,
            "email": str(file_obj.get("email", "") or ""),
            "provider": str(file_obj.get("provider", "") or ""),
            "reason": reason,
            "source": source,
            "status_message": str(file_obj.get("status_message", "") or ""),
        }
        if record_history is not None:
            await record_history(record)

        message = (
            f"[cpa-monitor] deleted file={record['file_name']} "
            f"email={record['email'] or '-'} source={record['source']} reason={record['reason']}"
        )
        if log_fn is not None:
            log_fn(message)
        else:
            logger.info(message)

        records.append(record)
        deleted += 1

    return {
        "checked": len([item for item in files if isinstance(item, dict)]),
        "deleted": deleted,
        "records": records,
    }


class CliProxyMonitorManager:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._run_lock = asyncio.Lock()
        self._status: dict[str, Any] = {
            "running": False,
            "busy": False,
            "started_at": None,
            "last_run_at": None,
            "last_completed_at": None,
            "next_run_at": None,
            "last_result": None,
        }

    async def _current_monitor_config(self) -> dict[str, Any]:
        cfg = await settings_db.build_config()
        cli_cfg = cfg.get("cli_proxy", {}) if isinstance(cfg, dict) else {}
        return {
            "cfg": cfg,
            "interval_minutes": max(1, int(cli_cfg.get("monitor_interval_minutes", 180) or 180)),
            "active_probe": bool(cli_cfg.get("monitor_active_probe", False)),
            "probe_timeout": max(1, int(cli_cfg.get("monitor_probe_timeout", 8) or 8)),
        }

    async def _execute_once(self) -> dict[str, Any]:
        if self._run_lock.locked():
            return {"ok": False, "message": "监控正在执行中"}

        async with self._run_lock:
            self._status["busy"] = True
            self._status["last_run_at"] = time.time()
            try:
                monitor_cfg = await self._current_monitor_config()
                result = await scan_and_delete_invalid_auth_files(
                    monitor_cfg["cfg"],
                    active_probe=monitor_cfg["active_probe"],
                    probe_timeout=monitor_cfg["probe_timeout"],
                    record_history=insert_monitor_history,
                )
                result["ok"] = True
                result["active_probe"] = monitor_cfg["active_probe"]
                self._status["last_result"] = result
                return result
            finally:
                self._status["busy"] = False
                self._status["last_completed_at"] = time.time()

    async def _run_loop(self) -> None:
        try:
            while self._stop_event is not None and not self._stop_event.is_set():
                monitor_cfg = await self._current_monitor_config()
                interval_seconds = monitor_cfg["interval_minutes"] * 60
                self._status["next_run_at"] = time.time() + interval_seconds
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=interval_seconds)
                    break
                except asyncio.TimeoutError:
                    await self._execute_once()
        finally:
            self._status["running"] = False
            self._status["next_run_at"] = None
            self._task = None
            self._stop_event = None

    async def start(self) -> dict[str, Any]:
        if self._task is not None and not self._task.done():
            return {"ok": False, "message": "监控已在运行中"}
        self._stop_event = asyncio.Event()
        self._status["running"] = True
        self._status["started_at"] = time.time()
        self._status["last_result"] = None
        monitor_cfg = await self._current_monitor_config()
        self._status["next_run_at"] = time.time() + monitor_cfg["interval_minutes"] * 60
        self._task = asyncio.create_task(self._run_loop())
        return {"ok": True, **await self.get_status()}

    async def stop(self) -> dict[str, Any]:
        if self._stop_event is not None:
            self._stop_event.set()
        self._status["running"] = False
        self._status["next_run_at"] = None
        return {"ok": True, **await self.get_status()}

    async def run_once(self) -> dict[str, Any]:
        return await self._execute_once()

    async def get_status(self) -> dict[str, Any]:
        status = dict(self._status)
        monitor_cfg = await self._current_monitor_config()
        status["interval_minutes"] = monitor_cfg["interval_minutes"]
        status["active_probe"] = monitor_cfg["active_probe"]
        status["probe_timeout"] = monitor_cfg["probe_timeout"]
        return status

    async def get_history(self, limit: int = 100) -> list[dict[str, Any]]:
        return await list_monitor_history(limit)


monitor_manager = CliProxyMonitorManager()
