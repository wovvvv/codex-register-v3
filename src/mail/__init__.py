"""
mail/__init__.py — Factory for all mail service clients.
"""
from __future__ import annotations

from importlib import import_module
from typing import Optional

from src.mail.base import MailClient

__all__ = [
    "MailClient", "GPTMailClient", "NPCMailClient",
    "YYDSMailClient", "IMAPMailClient", "MultiIMAPMailClient",
    "OutlookMailClient", "MultiOutlookMailClient", "CFWorkerMailClient",
    "get_mail_client",
]


_LAZY_EXPORTS = {
    "GPTMailClient": ("src.mail.gptmail", "GPTMailClient"),
    "NPCMailClient": ("src.mail.npcmail", "NPCMailClient"),
    "YYDSMailClient": ("src.mail.yydsmail", "YYDSMailClient"),
    "IMAPMailClient": ("src.mail.imap", "IMAPMailClient"),
    "MultiIMAPMailClient": ("src.mail.imap", "MultiIMAPMailClient"),
    "OutlookMailClient": ("src.mail.outlook", "OutlookMailClient"),
    "MultiOutlookMailClient": ("src.mail.outlook", "MultiOutlookMailClient"),
    "CFWorkerMailClient": ("src.mail.cfworker", "CFWorkerMailClient"),
}


def __getattr__(name: str):
    """模块级懒加载导出，避免可选依赖在导入期强制失败。"""
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals().keys()) | set(_LAZY_EXPORTS.keys()))


def get_mail_client(
    provider: str,
    api_key: str = "",
    base_url: str = "",
    cfg: Optional[dict] = None,
) -> MailClient:
    """
    Return the appropriate MailClient for *provider*.

    Parameters
    ----------
    provider : Provider name, e.g. 'gptmail', 'imap', 'imap:0', 'outlook', 'outlook:1'.
    api_key  : API key for HTTP-based providers (gptmail / npcmail / yydsmail).
    base_url : Base URL for HTTP-based providers.
    cfg      : Full merged config dict (from settings_db.build_config()).
               Required for IMAP/Outlook/CFWorker providers because all runtime config
               is now stored in SQLite.
    """
    def _get_cfg() -> dict:
        if cfg is not None:
            return cfg
        raise ValueError(
            "DB-backed config is required for this provider. "
            "Load it with settings_db.build_config() first."
        )

    match provider.lower():
        case "gptmail":
            from src.mail.gptmail import GPTMailClient
            return GPTMailClient(
                api_key=api_key or "gpt-test",
                **({"base_url": base_url} if base_url else {}),
            )
        case "npcmail":
            from src.mail.npcmail import NPCMailClient
            return NPCMailClient(
                api_key=api_key,
                **({"base_url": base_url} if base_url else {}),
            )
        case "yydsmail":
            from src.mail.yydsmail import YYDSMailClient
            return YYDSMailClient(
                api_key=api_key,
                **({"base_url": base_url} if base_url else {}),
            )
        case "cfworker":
            from src.mail.cfworker import CFWorkerMailClient
            _cf_cfg = (_get_cfg().get("mail") or {}).get("cfworker", {})
            if not isinstance(_cf_cfg, dict):
                _cf_cfg = {}
            return CFWorkerMailClient(
                api_url=_cf_cfg.get("api_url", ""),
                admin_token=_cf_cfg.get("admin_token", ""),
                custom_auth=_cf_cfg.get("custom_auth", ""),
                domain=_cf_cfg.get("domain", ""),
                domains=_cf_cfg.get("domains", []),
                enabled_domains=_cf_cfg.get("enabled_domains", []),
                subdomain=_cf_cfg.get("subdomain", ""),
                random_subdomain=_cf_cfg.get("random_subdomain", False),
                fingerprint=_cf_cfg.get("fingerprint", ""),
            )

        # ── IMAP ──────────────────────────────────────────────────────────
        case _ if provider.lower() == "imap" or provider.lower().startswith("imap:"):
            from src.mail.imap import (
                IMAPMailClient,
                MultiIMAPMailClient,
                build_imap_client_from_provider,
                is_provider_based_imap_config,
                parse_imap_selector,
            )
            _provider_idx, _account_idx = parse_imap_selector(provider)

            _imap_raw = (_get_cfg().get("mail") or {}).get("imap", [])
            if isinstance(_imap_raw, dict):
                _imap_raw = [_imap_raw]
            _is_provider_based = is_provider_based_imap_config(_imap_raw)

            def _build_client_flat(c: dict) -> IMAPMailClient:
                return IMAPMailClient(
                    email        = c.get("email", ""),
                    password     = c.get("password", ""),
                    host         = c.get("host", ""),
                    port         = int(c.get("port", 993)),
                    ssl          = bool(c.get("ssl", True)),
                    folder       = c.get("folder", "INBOX"),
                    use_alias    = c.get("use_alias"),
                    address_mode = c.get("address_mode"),
                    registration_domain = c.get("registration_domain", ""),
                    provider_name = c.get("provider_name", "imap"),
                    auth_type    = c.get("auth_type", "password"),
                    access_token = c.get("access_token", ""),
                )

            if _is_provider_based:
                if _provider_idx is not None:
                    if _provider_idx >= len(_imap_raw):
                        raise ValueError(
                            f"imap:{_provider_idx} out of range — "
                            f"{len(_imap_raw)} provider(s) configured (index 0–{len(_imap_raw) - 1})"
                        )
                    _prov = _imap_raw[_provider_idx]
                    _accounts = [a for a in (_prov.get("accounts", []) or []) if a.get("email")]
                    if not _accounts:
                        raise ValueError(
                            f"IMAP provider {_provider_idx} has no valid account configured"
                        )
                    if _account_idx is not None:
                        if _account_idx >= len(_accounts):
                            raise ValueError(
                                f"imap:{_provider_idx}:{_account_idx} out of range — "
                                f"{len(_accounts)} account(s) configured (index 0–{len(_accounts) - 1})"
                            )
                        return build_imap_client_from_provider(_prov, _accounts[_account_idx], _provider_idx)
                    _clients = [
                        build_imap_client_from_provider(_prov, acc, _provider_idx)
                        for acc in _accounts
                    ]
                    return _clients[0] if len(_clients) == 1 else MultiIMAPMailClient(_clients)

                _clients = []
                for _idx, _prov in enumerate(_imap_raw):
                    for _acc in (_prov.get("accounts", []) or []):
                        if _acc.get("email"):
                            _clients.append(build_imap_client_from_provider(_prov, _acc, _idx))
            else:
                if _account_idx is not None:
                    raise ValueError("imap:N:M selector is only supported for provider-based IMAP config")
                _clients = [
                    _build_client_flat(c)
                    for c in _imap_raw
                    if c.get("email")
                ]

            if not _clients:
                raise ValueError(
                    "No valid IMAP accounts configured. "
                    "Add at least one entry under Settings → IMAP 账户."
                )

            if _provider_idx is not None:
                if _provider_idx >= len(_clients):
                    raise ValueError(
                        f"imap:{_provider_idx} out of range — "
                        f"{len(_clients)} account(s) configured (index 0–{len(_clients) - 1})"
                    )
                return _clients[_provider_idx]

            return _clients[0] if len(_clients) == 1 else MultiIMAPMailClient(_clients)

        # ── Outlook / Hotmail ─────────────────────────────────────────────
        case _ if provider.lower() in ("outlook", "hotmail") or provider.lower().startswith("outlook:"):
            from src.mail.outlook import OutlookMailClient, MultiOutlookMailClient
            _parts = provider.split(":", 1)
            _index = None
            if len(_parts) == 2 and _parts[1].isdigit():
                _index = int(_parts[1])

            _out_raw = (_get_cfg().get("mail") or {}).get("outlook", [])
            if isinstance(_out_raw, dict):
                _out_raw = [_out_raw]

            _clients_out = [
                OutlookMailClient(
                    email         = c.get("email", ""),
                    client_id     = c.get("client_id", ""),
                    tenant_id     = c.get("tenant_id", "consumers"),
                    refresh_token = c.get("refresh_token", ""),
                    access_token  = c.get("access_token", ""),
                    fetch_method  = c.get("fetch_method", "graph"),
                )
                for c in _out_raw
                if c.get("email") and c.get("client_id")
            ]

            if not _clients_out:
                raise ValueError(
                    "No valid Outlook accounts configured. "
                    "Add at least one entry under Settings → Outlook/Hotmail."
                )

            if _index is not None:
                if _index >= len(_clients_out):
                    raise ValueError(
                        f"outlook:{_index} out of range — "
                        f"{len(_clients_out)} account(s) configured"
                    )
                return _clients_out[_index]

            return _clients_out[0] if len(_clients_out) == 1 else MultiOutlookMailClient(_clients_out)

        case _:
            raise ValueError(f"Unknown mail provider: {provider!r}")
