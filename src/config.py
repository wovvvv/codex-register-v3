"""
config.py — Code-level default fallback.
All settings are now stored in SQLite (settings_db).
config.yaml is read ONCE at startup for one-time migration and then ignored.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

_DEFAULTS: dict[str, Any] = {
    # ── Operational (primary store: DB "general" section) ──────────────────
    "engine": "playwright",
    "headless": True,
    "slow_mo": 0,
    "mobile": False,
    "max_concurrent": 2,
    "mail_provider": "gptmail",
    "mail": {
        "gptmail":  {"api_key": "", "base_url": "https://mail.chatgpt.org.uk"},
        "npcmail":  {"api_key": "", "base_url": "https://dash.xphdfs.me"},
        "yydsmail": {"api_key": "", "base_url": "https://maliapi.215.im/v1"},
        "imap": [],
    },
    "registration": {"prefix": "", "domain": ""},
    "proxy_strategy": "pool",
    "proxy_static": "",
    "team": {"url": "", "key": ""},
    "sync":  {"url": "", "key": ""},
    "enable_oauth": True,
    # ── Mouse (primary store: DB "mouse" section) ──────────────────────────
    "mouse": {
        "human_simulation": True,
        "steps_min":       4,
        "steps_max":       8,
        "step_delay_min":  0.003,
        "step_delay_max":  0.010,
        "hover_min":       0.02,
        "hover_max":       0.08,
    },
    # ── Timeouts (primary store: DB "timeouts" section) ────────────────────
    "timeouts": {
        "page_load":            30,
        "auth0_redirect":       8,
        "email_input":          15,
        "password_input":       60,
        "otp_input":            60,
        "otp_code":             180,
        "profile_detect":       15,
        "profile_field":        5,
        "complete_redirect":    20,
        "oauth_navigate":       20,
        "oauth_flow_element":   8,
        "oauth_login_email":    8,
        "oauth_login_password": 10,
        "oauth_token_exchange": 30,
        "oauth_total":          45,
    },
}


def load() -> dict[str, Any]:
    """Load config.yaml merged with code defaults. Used only as migration source."""
    if not CONFIG_PATH.exists():
        return dict(_DEFAULTS)
    with CONFIG_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return _deep_merge(_DEFAULTS, data)


def get(key: str, default: Any = None) -> Any:
    """Dot-notation getter (code-level fallback only)."""
    cfg = load()
    parts = key.split(".")
    val: Any = cfg
    for part in parts:
        if isinstance(val, dict) and part in val:
            val = val[part]
        else:
            return default
    return val


def set_key(key: str, value: Any) -> None:
    """Write a key to config.yaml (legacy; prefer settings_db for new code)."""
    if isinstance(value, str):
        if value.lower() in ("true", "false"):
            value = value.lower() == "true"
        else:
            try:
                value = int(value)
            except ValueError:
                try:
                    value = float(value)
                except ValueError:
                    pass
    cfg = load()
    parts = key.split(".")
    d = cfg
    for part in parts[:-1]:
        d = d.setdefault(part, {})
    d[parts[-1]] = value
    _save(cfg)


def _save(cfg: dict) -> None:
    CONFIG_PATH.write_text(
        yaml.dump(cfg, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result



