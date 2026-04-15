"""
post_register.py — 注册完成后的本地持久化与可选自动上传。
"""
from __future__ import annotations

from typing import Any, Callable

from loguru import logger

import src.accounts as accounts
from src.integrations.cli_proxy import upload_account_to_cli_proxy
from src.integrations.sub2api import upload_account_to_sub2api

LogFn = Callable[[str], None]


def _build_upload_meta(*, provider: str, attempted: bool, ok: bool, message: str, target: str = "") -> dict[str, Any]:
    """统一封装上传结果，便于 CLI / WebUI 共用。"""
    return {
        "provider": provider,
        "attempted": attempted,
        "ok": ok,
        "message": message,
        "target": target,
    }


def _resolve_upload_provider(cfg: dict[str, Any]) -> str:
    provider = str(cfg.get("upload_provider", "") or "").strip().lower()
    if provider in {"none", "cpa", "sub2api"}:
        return provider

    cli_cfg = cfg.get("cli_proxy")
    if isinstance(cli_cfg, dict) and bool(cli_cfg.get("enabled", False)):
        return "cpa"
    return "none"


async def persist_account_and_maybe_upload(
    account: dict[str, Any],
    cfg: dict[str, Any],
    log_fn: LogFn | None = None,
) -> dict[str, Any]:
    """先落库，再按配置执行非致命自动上传。"""
    await accounts.upsert(account)

    result = dict(account)

    provider = _resolve_upload_provider(cfg)
    if provider == "none":
        result["_upload"] = _build_upload_meta(
            provider="none",
            attempted=False,
            ok=False,
            message="自动上传未启用",
        )
        return result

    email = str(account.get("email", "") or "").strip()
    if not email:
        result["_upload"] = _build_upload_meta(
            provider=provider,
            attempted=False,
            ok=False,
            message="账号缺少 email，已跳过自动上传",
        )
        return result

    target = ""
    if provider == "cpa":
        cli_cfg = cfg.get("cli_proxy")
        if not isinstance(cli_cfg, dict):
            result["_upload"] = _build_upload_meta(
                provider="cpa",
                attempted=False,
                ok=False,
                message="cli_proxy 配置缺失，已跳过自动上传",
            )
            return result
        target = str(cli_cfg.get("target", "") or "")
        access_token = str(account.get("access_token", "") or "")
        if not access_token:
            result["_upload"] = _build_upload_meta(
                provider="cpa",
                attempted=False,
                ok=False,
                message="账号缺少 access_token，已跳过自动上传",
                target=target,
            )
            result["_cli_proxy_upload"] = result["_upload"]
            return result
        ok, message = await upload_account_to_cli_proxy(account, cfg)
        result["_upload"] = _build_upload_meta(
            provider="cpa",
            attempted=True,
            ok=ok,
            message=message,
            target=target,
        )
        result["_cli_proxy_upload"] = result["_upload"]
        if log_fn:
            log_fn(f"[CLI Proxy] {'成功' if ok else '失败'}：{message}")
        if not ok:
            logger.warning(f"[post_register] CLI Proxy 自动上传失败 email={account.get('email', '')}: {message}")
        return result

    refresh_token = str(account.get("refresh_token", "") or "")
    if not refresh_token:
        result["_upload"] = _build_upload_meta(
            provider="sub2api",
            attempted=False,
            ok=False,
            message="账号缺少 refresh_token，已跳过自动上传",
        )
        return result

    sub2api_cfg = cfg.get("sub2api_upload")
    if isinstance(sub2api_cfg, dict):
        target = str(sub2api_cfg.get("base_url", "") or "")
    ok, message = await upload_account_to_sub2api(account, cfg)
    result["_upload"] = _build_upload_meta(
        provider="sub2api",
        attempted=True,
        ok=ok,
        message=message,
        target=target,
    )
    if log_fn:
        log_fn(f"[Sub2API] {'成功' if ok else '失败'}：{message}")
    if not ok:
        logger.warning(f"[post_register] Sub2API 自动上传失败 email={account.get('email', '')}: {message}")
    return result
