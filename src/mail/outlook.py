"""
mail/outlook.py — Outlook/Hotmail mail client with Microsoft OAuth2.

Supports two fetch methods:
  graph : Microsoft Graph API  (recommended, no IMAP permission needed)
  imap  : IMAP with XOAUTH2   (requires IMAP.AccessAsUser.All scope)

Account config (stored in DB section 'mail.outlook'):
  email          : user@outlook.com / user@hotmail.com / user@live.com
  client_id      : Azure AD application (client) ID
  tenant_id      : 'consumers' (personal accounts, default) or specific tenant GUID
  refresh_token  : OAuth2 refresh token (long-lived)
  access_token   : (auto-managed, can be left empty)
  fetch_method   : 'graph' (default) or 'imap'

Minimal Azure AD app registration requirements:
  - Redirect URI: https://login.microsoftonline.com/common/oauth2/nativeclient
  - Delegated permissions (Graph):   Mail.Read, offline_access
  - Delegated permissions (IMAP):    IMAP.AccessAsUser.All, offline_access
  - "Allow public client flows": enabled

Obtaining a refresh_token (one-time, per account):
  Use the device code flow or any OAuth2 tool with the scopes above.
"""
from __future__ import annotations

import asyncio
import base64
import email as email_lib
import random
import re
import time
from email.header import decode_header, make_header
from typing import Optional

import aioimaplib
import httpx
from loguru import logger

from src.mail.base import MailClient

# ── Constants ─────────────────────────────────────────────────────────────

_CODE_RE          = re.compile(r"\b(\d{6})\b")
_CODE_FALLBACK_RE = re.compile(r"\b(\d{4,8})\b")

_GRAPH_MESSAGES_URL = "https://graph.microsoft.com/v1.0/me/messages"
_IMAP_HOST          = "imap-mail.outlook.com"
_IMAP_PORT          = 993

_SCOPE_GRAPH = "https://graph.microsoft.com/Mail.Read offline_access"
_SCOPE_IMAP  = "https://outlook.office.com/IMAP.AccessAsUser.All offline_access"


# ── Helpers ───────────────────────────────────────────────────────────────

def _extract_code(text: str) -> Optional[str]:
    m = _CODE_RE.search(text)
    if m:
        return m.group(1)
    m = _CODE_FALLBACK_RE.search(text)
    return m.group(1) if m else None


def _decode_str(raw) -> str:
    try:
        return str(make_header(decode_header(raw or "")))
    except Exception:
        return str(raw or "")


def _extract_text(msg: email_lib.message.Message) -> str:
    parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct in ("text/plain", "text/html"):
                try:
                    charset = part.get_content_charset() or "utf-8"
                    payload = part.get_payload(decode=True)
                    if payload:
                        parts.append(payload.decode(charset, errors="replace"))
                except Exception:
                    pass
    else:
        try:
            charset = msg.get_content_charset() or "utf-8"
            payload = msg.get_payload(decode=True)
            if payload:
                parts.append(payload.decode(charset, errors="replace"))
        except Exception:
            pass
    return " ".join(parts)


def _make_xoauth2_token(email: str, access_token: str) -> str:
    raw = f"user={email}\x01auth=Bearer {access_token}\x01\x01"
    return base64.b64encode(raw.encode()).decode()


# ── Single Outlook account client ─────────────────────────────────────────

class OutlookMailClient(MailClient):
    """
    Single Outlook/Hotmail account using Microsoft OAuth2.

    Token lifecycle is managed internally: the access_token is refreshed
    automatically before it expires using the stored refresh_token.
    """

    def __init__(
        self,
        email: str,
        client_id: str,
        tenant_id: str = "consumers",
        refresh_token: str = "",
        access_token: str = "",
        fetch_method: str = "graph",   # "graph" | "imap"
    ) -> None:
        self._email         = email
        self._client_id     = client_id
        self._tenant_id     = tenant_id or "consumers"
        self._refresh_token = refresh_token
        self._access_token  = access_token
        self._fetch_method  = fetch_method
        self._token_expiry  = 0.0   # Unix timestamp; 0 = always refresh

    # ── Token management ──────────────────────────────────────────────────

    async def _get_token(self) -> str:
        """Return a valid access_token, refreshing if needed."""
        if self._access_token and time.time() < self._token_expiry - 60:
            return self._access_token

        if not self._refresh_token:
            raise ValueError(
                f"[Outlook] No refresh_token configured for {self._email}. "
                "Complete the OAuth2 device-code flow first."
            )

        scope = _SCOPE_GRAPH if self._fetch_method == "graph" else _SCOPE_IMAP
        token_url = (
            f"https://login.microsoftonline.com/{self._tenant_id}/oauth2/v2.0/token"
        )

        # trust_env=False: 不读取 Windows 系统代理（避免代理拦截导致的 SSL 错误）
        async with httpx.AsyncClient(timeout=30, trust_env=False) as c:
            r = await c.post(token_url, data={
                "client_id":     self._client_id,
                "grant_type":    "refresh_token",
                "refresh_token": self._refresh_token,
                "scope":         scope,
            })
            r.raise_for_status()
            data = r.json()

        self._access_token = data["access_token"]
        self._token_expiry = time.time() + data.get("expires_in", 3600)
        if "refresh_token" in data:
            self._refresh_token = data["refresh_token"]

        logger.debug(f"[Outlook] Token refreshed for {self._email}")
        return self._access_token

    # ── generate ─────────────────────────────────────────────────────────

    async def generate_email(
        self,
        prefix: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> str:
        """Return the Outlook address directly (no alias support needed)."""
        logger.info(f"[Outlook] Using account: {self._email}")
        return self._email

    # ── poll ─────────────────────────────────────────────────────────────

    async def poll_code(self, email: str, timeout: int = 120) -> Optional[str]:
        if self._fetch_method == "imap":
            return await self._poll_imap(timeout)
        return await self._poll_graph(timeout)

    # ── Graph API fetch ───────────────────────────────────────────────────

    async def _poll_graph(self, timeout: int) -> Optional[str]:
        deadline  = time.monotonic() + timeout
        seen_ids: set[str] = set()

        logger.info(f"[Outlook/Graph] Polling inbox for {self._email} (timeout={timeout}s)")

        while time.monotonic() < deadline:
            try:
                token = await self._get_token()
                async with httpx.AsyncClient(timeout=30, trust_env=False) as c:
                    r = await c.get(
                        _GRAPH_MESSAGES_URL,
                        headers={"Authorization": f"Bearer {token}"},
                        params={
                            "$select": "id,subject,body,receivedDateTime",
                            "$filter": "isRead eq false",
                            "$orderby": "receivedDateTime desc",
                            "$top": "25",
                        },
                    )
                    r.raise_for_status()
                    messages = r.json().get("value", [])

                for msg in messages:
                    mid = msg.get("id", "")
                    if mid in seen_ids:
                        continue
                    seen_ids.add(mid)
                    subject = msg.get("subject", "")
                    body    = (msg.get("body") or {}).get("content", "")
                    code = _extract_code(f"{subject} {body}")
                    if code:
                        logger.info(f"[Outlook/Graph] Code {code} for {self._email}")
                        return code

            except Exception as exc:
                logger.warning(f"[Outlook/Graph] error: {exc}")

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(4, remaining))

        logger.warning(f"[Outlook/Graph] Timed out ({self._email})")
        return None

    # ── IMAP+XOAUTH2 fetch ────────────────────────────────────────────────

    async def _poll_imap(self, timeout: int) -> Optional[str]:
        deadline      = time.monotonic() + timeout
        seen_uids: set[str] = set()

        logger.info(f"[Outlook/IMAP] Polling {self._email} (timeout={timeout}s)")

        while time.monotonic() < deadline:
            imap = None
            try:
                token   = await self._get_token()
                xoauth2 = _make_xoauth2_token(self._email, token)

                imap = aioimaplib.IMAP4_SSL(host=_IMAP_HOST, port=_IMAP_PORT, timeout=15)
                await imap.wait_hello_from_server()
                # aioimaplib.xoauth2(user, raw_access_token) 内部自建 XOAUTH2 SASL 字符串
                resp = await imap.xoauth2(self._email, token)
                if resp.result != "OK":
                    logger.warning(f"[Outlook/IMAP] Auth failed: {resp.result} {resp.lines}")
                    await asyncio.sleep(5)
                    continue

                ok, _ = await imap.select("INBOX")
                if ok != "OK":
                    await asyncio.sleep(5)
                    continue

                ok, data = await imap.search("UNSEEN", charset=None)
                if ok != "OK":
                    await asyncio.sleep(4)
                    continue

                uid_list: list[str] = []
                if data and data[0]:
                    raw = data[0]
                    if isinstance(raw, bytes):
                        raw = raw.decode()
                    uid_list = [u for u in raw.split() if u]

                for uid in uid_list:
                    if uid in seen_uids:
                        continue
                    seen_uids.add(uid)

                    ok, msg_data = await imap.fetch(uid, "(RFC822)")
                    if ok != "OK":
                        continue

                    raw_bytes: Optional[bytes] = None
                    for part in msg_data:
                        if isinstance(part, bytes) and len(part) > 100:
                            raw_bytes = part
                            break
                    if not raw_bytes:
                        continue

                    msg     = email_lib.message_from_bytes(raw_bytes)
                    subject = _decode_str(msg.get("Subject", ""))
                    body    = _extract_text(msg)
                    code    = _extract_code(f"{subject} {body}")
                    if code:
                        logger.info(f"[Outlook/IMAP] Code {code} for {self._email}")
                        await imap.logout()
                        return code

            except asyncio.TimeoutError:
                logger.warning("[Outlook/IMAP] Timeout — retrying")
            except OSError as exc:
                logger.warning(f"[Outlook/IMAP] Network error [{type(exc).__name__}]: {exc!r}")
            except Exception as exc:
                logger.warning(
                    f"[Outlook/IMAP] Error [{type(exc).__name__}]: {exc!r} | "
                    f"args={exc.args!r}"
                )
            finally:
                if imap is not None:
                    try:
                        await imap.logout()
                    except Exception:
                        pass

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(4, remaining))

        logger.warning(f"[Outlook/IMAP] Timed out ({self._email})")
        return None


# ── Multi-account wrapper ─────────────────────────────────────────────────

class MultiOutlookMailClient(MailClient):
    """
    Wraps multiple OutlookMailClient instances and round-robins across them.
    Each generate_email() call picks the next unused account; poll_code()
    routes to the owning account.
    """

    def __init__(self, clients: list[OutlookMailClient]) -> None:
        if not clients:
            raise ValueError("MultiOutlookMailClient requires at least one account")
        self._clients  = clients
        self._index    = 0
        self._routing: dict[str, OutlookMailClient] = {}

    async def generate_email(
        self,
        prefix: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> str:
        client = self._clients[self._index % len(self._clients)]
        self._index += 1
        addr = await client.generate_email()
        self._routing[addr.lower()] = client
        return addr

    async def poll_code(self, email: str, timeout: int = 120) -> Optional[str]:
        client = self._routing.get(email.lower())
        if client is None:
            logger.warning(f"[Outlook] No routing for {email!r} — using first account")
            client = self._clients[0]
        return await client.poll_code(email, timeout)

