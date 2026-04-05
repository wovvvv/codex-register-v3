"""
settings_db.py — All WebUI configuration stored in SQLite.
config.yaml is no longer the source of truth; it is used only as a one-time
migration source and as a code-level fallback for missing keys.
"""
from __future__ import annotations

import json
from typing import Any

import aiosqlite

from src.db import DB_PATH

# ── Sections managed in DB ────────────────────────────────────────────────

_SECTIONS = [
    "general",       # engine, headless, mobile, concurrency, proxy, mail_provider
    "mail.gptmail",
    "mail.npcmail",
    "mail.yydsmail",
    "mail.imap",
    "mail.outlook",
    "registration",
    "team",
    "sync",
    "oauth",
    "mouse",
    "timeouts",
    "timing",
]

_DEFAULTS: dict[str, Any] = {
    "general": {
        "engine":         "playwright",
        "headless":       True,
        "slow_mo":        0,
        "mobile":         False,
        "max_concurrent": 2,
        "mail_provider":  "gptmail",
        "proxy_strategy": "none",
        "proxy_static":   "",
    },
    "mail.gptmail":  {"api_key": "", "base_url": "https://mail.chatgpt.org.uk"},
    "mail.npcmail":  {"api_key": "", "base_url": "https://dash.xphdfs.me"},
    "mail.yydsmail": {"api_key": "", "base_url": "https://maliapi.215.im/v1"},
    "mail.imap":     [],
    "mail.outlook":  [],
    "registration": {"prefix": "", "domain": ""},
    "team": {"url": "", "key": ""},
    "sync": {"url": "", "key": ""},
    "oauth": {"enabled": True, "timeout": 45},
    "mouse": {
        "human_simulation": True,
        "steps_min":        4,
        "steps_max":        8,
        "step_delay_min":   0.003,
        "step_delay_max":   0.010,
        "hover_min":        0.02,
        "hover_max":        0.08,
    },
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
    "timing": {
        "post_nav":      1.0,
        "pre_fill":      0.5,
        "post_click":    1.5,
        "post_complete": 1.0,
    },
}


# ── Internal helpers ──────────────────────────────────────────────────────

async def _ensure_table() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                section TEXT PRIMARY KEY,
                value   TEXT NOT NULL DEFAULT '{}'
            )
        """)
        await db.commit()


# ── Public API ────────────────────────────────────────────────────────────

async def init_from_yaml() -> None:
    """
    One-time migration: read config.yaml and write any missing sections into DB.
    After first run the DB is the sole source of truth; YAML is ignored.
    """
    await _ensure_table()
    import src.config as cfg_mod
    yaml_cfg = cfg_mod.load()

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT section FROM settings") as cur:
            existing = {row[0] async for row in cur}

        to_insert: list[tuple[str, str]] = []

        for section in _SECTIONS:
            if section in existing:
                continue

            if section == "general":
                # Migrate flat operational keys from YAML top-level
                val = {
                    "engine":         yaml_cfg.get("engine",         "playwright"),
                    "headless":       yaml_cfg.get("headless",       True),
                    "slow_mo":        yaml_cfg.get("slow_mo",        0),
                    "mobile":         yaml_cfg.get("mobile",         False),
                    "max_concurrent": yaml_cfg.get("max_concurrent", 2),
                    "mail_provider":  yaml_cfg.get("mail_provider",  "gptmail"),
                    "proxy_strategy": yaml_cfg.get("proxy_strategy", "none"),
                    "proxy_static":   yaml_cfg.get("proxy_static",   ""),
                }
                to_insert.append((section, json.dumps(val, ensure_ascii=False)))

            elif section.startswith("mail."):
                provider = section[5:]
                raw = yaml_cfg.get("mail", {}).get(provider, _DEFAULTS[section])
                to_insert.append((section, json.dumps(raw, ensure_ascii=False)))

            elif section == "oauth":
                val = {
                    "enabled": yaml_cfg.get("enable_oauth",
                                             yaml_cfg.get("oauth", {}).get("enabled", True)),
                    "timeout": yaml_cfg.get("oauth", {}).get("timeout", 45),
                }
                to_insert.append((section, json.dumps(val, ensure_ascii=False)))

            elif section == "mouse":
                # Migrate mouse from YAML; also pick up human_simulation if present
                yaml_mouse = dict(yaml_cfg.get("mouse", {}))
                merged = {**_DEFAULTS["mouse"], **yaml_mouse}
                # human_simulation was stored as top-level in YAML by previous versions
                if "human_simulation" in yaml_cfg:
                    merged["human_simulation"] = yaml_cfg["human_simulation"]
                to_insert.append((section, json.dumps(merged, ensure_ascii=False)))

            elif section in yaml_cfg and yaml_cfg[section]:
                to_insert.append((section, json.dumps(yaml_cfg[section], ensure_ascii=False)))

            else:
                to_insert.append((section, json.dumps(_DEFAULTS[section], ensure_ascii=False)))

        if to_insert:
            await db.executemany(
                "INSERT OR IGNORE INTO settings (section, value) VALUES (?, ?)",
                to_insert,
            )
            await db.commit()


async def get_section(section: str) -> Any:
    """Return a single settings section (or default if not stored)."""
    await _ensure_table()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT value FROM settings WHERE section = ?", (section,)
        ) as cur:
            row = await cur.fetchone()
    return json.loads(row[0]) if row else _DEFAULTS.get(section, {})


async def set_section(section: str, value: Any) -> None:
    """Persist a settings section to DB."""
    await _ensure_table()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (section, value) VALUES (?, ?)",
            (section, json.dumps(value, ensure_ascii=False)),
        )
        await db.commit()


async def get_all() -> dict[str, Any]:
    """Return all settings sections (DB values override defaults)."""
    await _ensure_table()
    result = {k: v for k, v in _DEFAULTS.items()}
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT section, value FROM settings") as cur:
            rows = await cur.fetchall()
    for section, value_json in rows:
        result[section] = json.loads(value_json)
    return result


async def build_config() -> dict[str, Any]:
    """
    Build the complete runtime config dict entirely from DB.
    YAML (config.py defaults) is used only as a code-level fallback for
    keys that are absent from the DB — not as the primary source.

    Priority (highest → lowest):
      DB general  >  DB per-section  >  YAML / code defaults
    """
    import src.config as cfg_mod
    yaml_cfg = cfg_mod.load()   # code-level fallback only
    db = await get_all()

    # Start from YAML as skeleton (provides structure / fallback defaults)
    cfg = dict(yaml_cfg)

    # ── 1. General operational settings (DB overrides YAML) ───────────────
    general_db = db.get("general", {})
    cfg.update(general_db)   # engine, headless, mobile, concurrency, proxy …

    # ── 2. Mail credentials ───────────────────────────────────────────────
    mail = cfg.setdefault("mail", {})
    for provider in ("gptmail", "npcmail", "yydsmail"):
        key = f"mail.{provider}"
        if db.get(key):
            mail[provider] = db[key]
    if db.get("mail.imap") is not None:
        mail["imap"] = db["mail.imap"]
    if db.get("mail.outlook") is not None:
        mail["outlook"] = db["mail.outlook"]

    # ── 3. Other per-section overrides ────────────────────────────────────
    for section in ("registration", "team", "sync", "mouse", "timeouts", "timing"):
        if db.get(section):
            cfg[section] = db[section]

    # ── 4. OAuth ──────────────────────────────────────────────────────────
    oauth_db = db.get("oauth", {})
    if oauth_db:
        cfg["enable_oauth"] = oauth_db.get("enabled", True)
        cfg.setdefault("oauth", {})["enabled"] = oauth_db.get("enabled", True)
        cfg.setdefault("oauth", {})["timeout"]  = oauth_db.get("timeout",  45)
        cfg.setdefault("timeouts", {})["oauth_total"] = oauth_db.get("timeout", 45)

    return cfg

