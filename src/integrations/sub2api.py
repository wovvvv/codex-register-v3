"""
sub2api.py — Sub2API worker ingest integration.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
from loguru import logger

_UPLOAD_PATH = "/api/v1/account-registration/worker/openai"


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _positive_int(value: Any) -> int | None:
    try:
        num = int(value)
    except (TypeError, ValueError):
        return None
    return num if num > 0 else None


def _positive_int_list(value: Any) -> list[int]:
    source: list[Any]
    if isinstance(value, list):
        source = value
    elif isinstance(value, str):
        source = value.replace("\n", ",").split(",")
    else:
        source = []

    seen: set[int] = set()
    items: list[int] = []
    for raw in source:
        num = _positive_int(raw)
        if num is None or num in seen:
            continue
        seen.add(num)
        items.append(num)
    return items


def _clean_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_model_whitelist(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    items: list[str] = []
    for raw in value:
        model = _clean_text(raw)
        if not model or model in seen:
            continue
        seen.add(model)
        items.append(model)
    return items


def get_sub2api_runtime_config(cfg: dict[str, Any]) -> dict[str, Any]:
    section = cfg.get("sub2api_upload")
    if not isinstance(section, dict):
        raise ValueError("sub2api_upload 配置缺失")

    base_url = _clean_text(section.get("base_url"))
    api_key = _clean_text(section.get("api_key"))
    group_ids = _positive_int_list(section.get("group_ids"))
    legacy_group_id = _positive_int(section.get("group_id"))
    if not group_ids and legacy_group_id is not None:
        group_ids = [legacy_group_id]
    if not base_url:
        raise ValueError("sub2api_upload.base_url 未配置")
    if not api_key:
        raise ValueError("sub2api_upload.api_key 未配置")
    if not group_ids:
        raise ValueError("sub2api_upload.group_ids 未配置")

    return {
        "base_url": base_url.rstrip("/"),
        "api_key": api_key,
        "group_ids": group_ids,
        "proxy_id": _positive_int(section.get("proxy_id")),
        "notes": _clean_text(section.get("notes")),
        "concurrency": _positive_int(section.get("concurrency")),
        "load_factor": _positive_int(section.get("load_factor")),
        "priority": _positive_int(section.get("priority")),
        "rate_multiplier": _clean_float(section.get("rate_multiplier")),
        "import_models": bool(section.get("import_models", False)),
        "model_whitelist": _normalize_model_whitelist(section.get("model_whitelist")),
    }


def build_sub2api_payload(account: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    runtime = get_sub2api_runtime_config(cfg)
    email = _clean_text(account.get("email"))
    refresh_token = _clean_text(account.get("refresh_token"))
    if not email:
        raise ValueError("账号缺少 email，无法上传")
    if not refresh_token:
        raise ValueError("账号缺少 refresh_token，无法上传")

    raw = account.get("_raw")
    raw = raw if isinstance(raw, dict) else {}
    client_id = _clean_text(account.get("client_id")) or _clean_text(raw.get("client_id"))
    account_id = _clean_text(account.get("account_id")) or _clean_text(raw.get("account_id"))
    id_token = _clean_text(account.get("id_token")) or _clean_text(raw.get("id_token"))
    expires_at = _clean_text(account.get("expires_at")) or _clean_text(raw.get("expired"))

    import_options: dict[str, Any] = {
        "group_ids": runtime["group_ids"],
    }
    if runtime["proxy_id"] is not None:
        import_options["proxy_id"] = runtime["proxy_id"]
    if runtime["notes"]:
        import_options["notes"] = runtime["notes"]
    if runtime["concurrency"] is not None:
        import_options["concurrency"] = runtime["concurrency"]
    if runtime["load_factor"] is not None:
        import_options["load_factor"] = runtime["load_factor"]
    if runtime["priority"] is not None:
        import_options["priority"] = runtime["priority"]
    if runtime["rate_multiplier"] is not None:
        import_options["rate_multiplier"] = runtime["rate_multiplier"]
    if runtime["import_models"]:
        import_options["import_models"] = True
    if runtime["model_whitelist"]:
        import_options["model_whitelist"] = runtime["model_whitelist"]

    payload: dict[str, Any] = {
        "email": email,
        "refresh_token": refresh_token,
        "import_options": import_options,
    }
    access_token = _clean_text(account.get("access_token"))
    if access_token:
        payload["access_token"] = access_token
    if id_token:
        payload["id_token"] = id_token
    if account_id:
        payload["account_id"] = account_id
    if client_id:
        payload["client_id"] = client_id
    if expires_at:
        payload["expires_at"] = expires_at
    return payload


async def upload_account_to_sub2api(account: dict[str, Any], cfg: dict[str, Any]) -> tuple[bool, str]:
    try:
        runtime = get_sub2api_runtime_config(cfg)
        payload = build_sub2api_payload(account, cfg)
    except ValueError as exc:
        return False, str(exc)

    upload_url = f"{runtime['base_url']}{_UPLOAD_PATH}"
    headers = {
        "Authorization": f"Bearer {runtime['api_key']}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(upload_url, headers=headers, json=payload)
    except Exception as exc:
        logger.warning(f"[sub2api] 上传异常 email={account.get('email', '')}: {exc}")
        return False, f"网络异常：{exc}"

    if response.status_code in (200, 201):
        return True, "上传成功"

    detail = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            detail = str(body.get("message") or body.get("detail") or body.get("reason") or "").strip()
            if not detail:
                detail = json.dumps(body, ensure_ascii=False)[:200]
    except Exception:
        detail = (getattr(response, "text", "") or "")[:200]
    if detail:
        return False, f"HTTP {response.status_code}: {detail}"
    return False, f"HTTP {response.status_code}"
