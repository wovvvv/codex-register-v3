"""
cli_proxy.py — CLI Proxy CPA 文件上传集成。
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from loguru import logger

_UTC8 = timezone(timedelta(hours=8))
_UPLOAD_PATH = "/v0/management/auth-files"


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    """解码 JWT payload；输入异常时返回空字典。"""
    try:
        parts = (token or "").split(".")
        if len(parts) < 2 or not parts[1]:
            return {}
        payload = parts[1]
        padding = (-len(payload)) % 4
        if padding:
            payload += "=" * padding
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        data = json.loads(decoded.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _get_raw_dict(account: dict[str, Any]) -> dict[str, Any]:
    raw = account.get("_raw")
    return raw if isinstance(raw, dict) else {}


def _get_raw_field(account: dict[str, Any], key: str, default: str = "") -> str:
    raw = _get_raw_dict(account)
    value = raw.get(key, default)
    return value if isinstance(value, str) else default


def _now_iso_utc8() -> str:
    return datetime.now(_UTC8).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def _jwt_auth_info(payload: dict[str, Any]) -> dict[str, Any]:
    nested = payload.get("https://api.openai.com/auth")
    if isinstance(nested, dict):
        return nested
    return {}


def _jwt_expired_iso(access_token: str) -> str:
    payload = _decode_jwt_payload(access_token)
    exp_value = payload.get("exp")
    if not isinstance(exp_value, (int, float)) or exp_value <= 0:
        return ""
    return datetime.fromtimestamp(exp_value, tz=_UTC8).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def _account_id_from_token(access_token: str) -> str:
    payload = _decode_jwt_payload(access_token)
    auth = _jwt_auth_info(payload)
    for key in ("chatgpt_account_id", "account_id"):
        value = auth.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _payload_preview(response) -> str:
    """优先取 JSON 错误体，失败时回退到 text 预览。"""
    try:
        data = response.json()
        if isinstance(data, dict):
            for key in ("message", "error", "detail"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    return value
            return json.dumps(data, ensure_ascii=False)[:200]
        if isinstance(data, list):
            return json.dumps(data, ensure_ascii=False)[:200]
    except Exception:
        pass
    text = getattr(response, "text", "") or ""
    return text[:200]


def build_cli_proxy_token_json(account: dict[str, Any]) -> dict[str, str]:
    """生成 CPA 兼容 token json。"""
    email = str(account.get("email", "") or "").strip()
    access_token = str(account.get("access_token", "") or "")
    refresh_token = str(account.get("refresh_token", "") or "")
    id_token = _get_raw_field(account, "id_token") or str(account.get("id_token", "") or "")
    expired = _get_raw_field(account, "expired") or _jwt_expired_iso(access_token)
    last_refresh = _get_raw_field(account, "last_refresh") or _now_iso_utc8()
    account_id = str(account.get("account_id", "") or "") or _account_id_from_token(access_token)

    return {
        "type": "codex",
        "email": email,
        "expired": expired,
        "id_token": id_token,
        "account_id": account_id,
        "access_token": access_token,
        "last_refresh": last_refresh,
        "refresh_token": refresh_token,
    }


def _legacy_cli_proxy_url(cli_cfg: dict[str, Any], target_override: str | None = None) -> str:
    """兼容旧版 local/remote 配置结构。"""
    target = str(target_override or cli_cfg.get("target") or "").strip().lower()
    if target not in {"local", "remote"}:
        target = "local"
    key = "remote_url" if target == "remote" else "local_url"
    return str(cli_cfg.get(key, "") or "").strip()


def _normalize_cpa_base_url(raw_url: str) -> str:
    """
    允许用户填写：
    - API 根地址： http://127.0.0.1:8317
    - 管理页地址： http://127.0.0.1:8317/management.html#/
    统一归一化为 API 根地址。
    """
    raw = str(raw_url or "").strip()
    if not raw:
        return ""

    try:
        parsed = urlsplit(raw)
    except Exception:
        return raw.rstrip("/")

    path = parsed.path or ""
    if path.endswith("/management.html"):
        path = path[: -len("/management.html")]
    path = path.rstrip("/")
    if path == "/":
        path = ""
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def resolve_cli_proxy_base_url(cfg: dict[str, Any], target_override: str | None = None) -> str:
    """解析单一 cpa_url，并兼容旧版 local/remote 配置。"""
    cli_cfg = cfg.get("cli_proxy")
    if not isinstance(cli_cfg, dict):
        raise ValueError("cli_proxy 配置缺失")

    raw_url = str(cli_cfg.get("cpa_url", "") or "").strip()
    if not raw_url:
        raw_url = _legacy_cli_proxy_url(cli_cfg, target_override)
    base_url = _normalize_cpa_base_url(raw_url)
    if not base_url:
        raise ValueError("cli_proxy.cpa_url 未配置")
    return base_url


def get_cli_proxy_runtime_config(cfg: dict[str, Any], target_override: str | None = None) -> dict[str, str]:
    """解析运行时上传配置，并校验必填字段。"""
    cli_cfg = cfg.get("cli_proxy")
    if not isinstance(cli_cfg, dict):
        raise ValueError("cli_proxy 配置缺失")

    base_url = resolve_cli_proxy_base_url(cfg, target_override)
    api_key = str(cli_cfg.get("api_key", "") or "").strip()
    if not api_key:
        raise ValueError("cli_proxy.api_key 未配置")

    return {
        "base_url": base_url,
        "api_key": api_key,
    }


async def upload_account_to_cli_proxy(
    account: dict[str, Any],
    cfg: dict[str, Any],
    target_override: str | None = None,
) -> tuple[bool, str]:
    """上传单个账号到 CLI Proxy CPA 文件接口。"""
    email = str(account.get("email", "") or "").strip()
    if not email:
        return False, "账号缺少 email，无法上传"

    access_token = str(account.get("access_token", "") or "")
    if not access_token:
        return False, "账号缺少 access_token，无法上传"

    try:
        runtime = get_cli_proxy_runtime_config(cfg, target_override)
    except ValueError as exc:
        return False, str(exc)

    token_json = build_cli_proxy_token_json(account)
    file_bytes = json.dumps(token_json, ensure_ascii=False, indent=2).encode("utf-8")
    upload_url = f"{runtime['base_url']}{_UPLOAD_PATH}"
    headers = {"Authorization": f"Bearer {runtime['api_key']}"}
    files = {"file": (f"{email}.json", file_bytes, "application/json")}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(upload_url, headers=headers, files=files)
    except Exception as exc:
        logger.warning(f"[cli_proxy] 上传异常 email={email}: {exc}")
        return False, f"网络异常：{exc}"

    if response.status_code in (200, 201):
        return True, "上传成功"

    detail = _payload_preview(response)
    if detail:
        return False, f"HTTP {response.status_code}: {detail}"
    return False, f"HTTP {response.status_code}"
