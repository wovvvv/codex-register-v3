"""
mail/imap.py — Generic IMAP mailbox client (supports multiple accounts, alias mode, OAuth2).

Unlike the API-based providers (gptmail / yydsmail), this client connects
directly to any standard IMAP server using the account's own credentials.

**Alias mode** (auto-enabled for qq.com and gmail.com mailboxes):
    generate_email() returns ``local+{random8}@domain`` instead of the bare
    address.  All aliases land in the same inbox; poll_code() filters by the
    ``To:`` / ``Delivered-To:`` headers so concurrent registrations sharing one
    mailbox receive the right code.

Configuration in SQLite settings:
    mail_provider: imap
    mail:
      imap:
        - email:    user@gmail.com
          password: app-password        # Gmail: use app-specific password
          host:     imap.gmail.com
          port:     993                 # 993 = IMAPS (SSL), 143 = STARTTLS
          ssl:      true
          folder:   INBOX
          # use_alias: true            # override auto-detect (omit → auto)
        - email:    user2@qq.com
          password: qq-app-password
          host:     imap.qq.com
          port:     993
          ssl:      true
          folder:   INBOX

CLI smoke-test:
    python -m src.mail.imap
"""
from __future__ import annotations

import asyncio
import base64
import email as email_lib
import random
import re
import string
import time
from email.header import decode_header, make_header
from email.utils import getaddresses
from typing import Optional

import aioimaplib
from loguru import logger

from src.mail.base import MailClient

# ── Constants ─────────────────────────────────────────────────────────────

_ALIAS_DOMAINS: frozenset[str] = frozenset({"qq.com", "gmail.com"})
_ADDRESS_MODES: frozenset[str] = frozenset({"inbox", "plus_alias", "random_local_part"})

# Well-known IMAP hosts auto-detected from email domain.
_AUTO_HOSTS: dict[str, str] = {
    "gmail.com":    "imap.gmail.com",
    "qq.com":       "imap.qq.com",
    "foxmail.com":  "imap.qq.com",
    "163.com":      "imap.163.com",
    "126.com":      "imap.126.com",
    "yeah.net":     "imap.yeah.net",
    "hotmail.com":  "imap-mail.outlook.com",
    "outlook.com":  "imap-mail.outlook.com",
    "live.com":     "imap-mail.outlook.com",
    "msn.com":      "imap-mail.outlook.com",
}

_CODE_RE          = re.compile(r"\b(\d{6})\b")
_CODE_FALLBACK_RE = re.compile(r"\b(\d{4,8})\b")


# ── Helpers ───────────────────────────────────────────────────────────────

def _extract_code(text: str) -> Optional[str]:
    """Return the first 6-digit (or 4–8 digit fallback) numeric code in *text*."""
    m = _CODE_RE.search(text)
    if m:
        return m.group(1)
    m = _CODE_FALLBACK_RE.search(text)
    return m.group(1) if m else None


def _decode_str(raw) -> str:
    """Decode an RFC-2047 encoded email header value to a plain string."""
    try:
        return str(make_header(decode_header(raw or "")))
    except Exception:
        return str(raw or "")


def _extract_text(msg: email_lib.message.Message) -> str:
    """Walk a parsed email message and concatenate all text parts."""
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


def _random_alias(length: int = 8) -> str:
    """Return a random alphanumeric string for use as a '+alias' suffix."""
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def _sanitize_local_part(value: str) -> str:
    """保留邮箱 local-part 常见安全字符，其余字符移除。"""
    return re.sub(r"[^A-Za-z0-9._-]+", "", value or "")


def _validate_registration_domain(domain: str) -> str:
    """校验注册域名是否为普通 DNS hostname，返回小写规范值。"""
    d = (domain or "").strip().lower()
    if not d:
        raise ValueError("registration_domain is required")
    if "*" in d:
        raise ValueError("registration_domain must not contain wildcard")
    if "." not in d:
        raise ValueError("registration_domain must contain at least one dot")
    if not re.fullmatch(
        r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+",
        d,
    ):
        raise ValueError("registration_domain must be a plain DNS hostname")
    return d


def _make_xoauth2_token(email: str, access_token: str) -> str:
    """Build the base64-encoded XOAUTH2 SASL token for IMAP authentication."""
    raw = f"user={email}\x01auth=Bearer {access_token}\x01\x01"
    return base64.b64encode(raw.encode()).decode()


def is_provider_based_imap_config(imap_raw: object) -> bool:
    """判断 IMAP 配置是否为 provider-based 结构。"""
    if isinstance(imap_raw, dict):
        return "accounts" in imap_raw
    if isinstance(imap_raw, list) and imap_raw and isinstance(imap_raw[0], dict):
        return "accounts" in imap_raw[0]
    return False


def parse_imap_selector(provider: str) -> tuple[Optional[int], Optional[int]]:
    """解析 selector: imap / imap:N / imap:N:M。"""
    parts = provider.split(":")
    provider_idx: Optional[int] = None
    account_idx: Optional[int] = None
    if len(parts) >= 2 and parts[1].isdigit():
        provider_idx = int(parts[1])
    if len(parts) >= 3 and parts[2].isdigit():
        account_idx = int(parts[2])
    return provider_idx, account_idx


# ── Single-account IMAP client ────────────────────────────────────────────

class IMAPMailClient(MailClient):
    """
    Generic IMAP client that wraps a single existing mailbox.

    Parameters
    ----------
    email        : Full e-mail address used for login.
    password     : IMAP password (ignored when auth_type='oauth2').
    host         : IMAP server. Auto-detected from domain when empty.
    port         : 993 = IMAPS (SSL), 143 = STARTTLS.
    ssl          : True → IMAPS; False → plain/STARTTLS.
    folder       : Mailbox folder (default 'INBOX').
    use_alias    : None = auto-detect (qq.com/gmail.com), True/False = override.
    auth_type    : 'password' (default) or 'oauth2' (XOAUTH2).
    access_token : Bearer token required when auth_type='oauth2'.
    """

    def __init__(
        self,
        email: str,
        password: str = "",
        host: str = "",
        port: int = 993,
        ssl: bool = True,
        folder: str = "INBOX",
        use_alias: Optional[bool] = None,
        address_mode: Optional[str] = None,
        registration_domain: str = "",
        provider_name: str = "",
        auth_type: str = "password",
        access_token: str = "",
    ) -> None:
        self._email        = email
        self._password     = password
        self._host         = host or _AUTO_HOSTS.get(email.split("@")[-1].lower() if "@" in email else "", "")
        self._port         = port
        self._ssl          = ssl
        self._folder       = folder
        self._auth_type    = auth_type
        self._access_token = access_token
        self._provider_name = provider_name or "imap"

        # 兼容旧配置：未传 address_mode 时继续沿用 use_alias / 域名自动 alias 逻辑。
        if address_mode:
            mode_normalized = address_mode.strip().lower()
            if mode_normalized not in _ADDRESS_MODES:
                raise ValueError(
                    f"Unknown address_mode: {address_mode!r}, "
                    f"expected one of {sorted(_ADDRESS_MODES)}"
                )
            self._address_mode = mode_normalized
        else:
            if use_alias is None:
                domain = email.split("@")[-1].lower() if "@" in email else ""
                use_alias = domain in _ALIAS_DOMAINS
            self._address_mode = "plus_alias" if use_alias else "inbox"
        self._use_alias = self._address_mode == "plus_alias"

        self._registration_domain = (
            _validate_registration_domain(registration_domain)
            if registration_domain
            else ""
        )

    def _message_matches_filter(
        self,
        msg: email_lib.message.Message,
        filter_to: Optional[str],
    ) -> bool:
        """检查邮件是否匹配 To/Delivered-To 过滤条件。"""
        if not filter_to:
            return True
        needle = filter_to.lower()
        to_values = msg.get_all("To", [])
        delivered_values = msg.get_all("Delivered-To", [])
        parsed_addresses = [
            addr.lower()
            for _, addr in getaddresses([*to_values, *delivered_values])
            if addr
        ]
        matched = needle in parsed_addresses
        if not matched:
            logger.debug(
                f"[IMAP] provider={self._provider_name} skip=filter_mismatch "
                f"inbox={self._email} filter_to={needle!r} "
                f"to={str(to_values)[:120]!r} delivered_to={str(delivered_values)[:120]!r} "
                f"parsed={parsed_addresses[:6]!r}"
            )
        return matched

    # ── generate ─────────────────────────────────────────────────────────

    async def generate_email(
        self,
        prefix: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> str:
        """
        Return a usable registration address.

        * **Alias mode** (qq.com / gmail.com or ``use_alias: true``):
          Returns ``local+{random8}@domain``.  The inbox still receives all
          messages sent to any ``+alias`` variant.
        * **random_local_part mode**:
          Returns ``{safe_prefix_or_random}@registration_domain`` while still
          logging into the real IMAP inbox for polling.
        * **Standard mode**: Returns the configured address as-is.
        """
        if self._address_mode == "plus_alias":
            local, _, dom = self._email.partition("@")
            # Strip any pre-existing alias suffix before adding a new one.
            local = local.split("+")[0]
            alias_email = f"{local}+{_random_alias()}@{dom}"
            logger.info(
                f"[IMAP] provider={self._provider_name} mode=plus_alias "
                f"inbox={self._email} registration={alias_email}"
            )
            return alias_email

        if self._address_mode == "random_local_part":
            if not self._registration_domain:
                raise ValueError("registration_domain is required for random_local_part mode")
            local_part = _sanitize_local_part((prefix or "").strip()) or _random_alias()
            registration_email = f"{local_part}@{self._registration_domain}"
            logger.info(
                f"[IMAP] provider={self._provider_name} mode=random_local_part "
                f"inbox={self._email} registration={registration_email}"
            )
            return registration_email

        logger.info(
            f"[IMAP] provider={self._provider_name} mode=inbox "
            f"inbox={self._email} registration={self._email}"
        )
        return self._email

    # ── poll ─────────────────────────────────────────────────────────────

    async def poll_code(self, email: str, timeout: int = 120) -> Optional[str]:
        """
        Connect to the IMAP server, repeatedly search for unseen messages
        and return the first OTP code found in subject + body text.

        When *email* differs from the configured mailbox address (i.e., an
        alias was used), only messages whose ``To:`` / ``Delivered-To:``
        header contains *email* are considered — this prevents concurrent
        tasks sharing the same inbox from stealing each other's codes.
        """
        deadline      = time.monotonic() + timeout
        seen_uids: set[str] = set()
        poll_interval = 4   # seconds between IMAP searches

        # 统一按完整注册邮箱过滤 To/Delivered-To，避免误命中。
        filter_to: Optional[str] = None
        if email.lower() != self._email.lower():
            filter_to = email.lower()

        logger.info(
            f"[IMAP] provider={self._provider_name} poll_start "
            f"inbox={self._email} registration={email} filter_to={filter_to!r} "
            f"folder={self._folder} host={self._host}:{self._port} timeout={timeout}s"
        )

        while time.monotonic() < deadline:
            imap = None
            try:
                # ── Connect & authenticate ────────────────────────────────
                if self._ssl:
                    imap = aioimaplib.IMAP4_SSL(
                        host=self._host, port=self._port,
                        timeout=15,
                    )
                else:
                    imap = aioimaplib.IMAP4(
                        host=self._host, port=self._port,
                        timeout=15,
                    )

                await imap.wait_hello_from_server()
                if self._auth_type == "oauth2":
                    token = _make_xoauth2_token(self._email, self._access_token)
                    ok, _ = await imap.authenticate("XOAUTH2", lambda x: token.encode())
                else:
                    ok, _ = await imap.login(self._email, self._password)
                if ok != "OK":
                    logger.warning(f"[IMAP] provider={self._provider_name} login_failed={ok}")
                    await asyncio.sleep(poll_interval)
                    continue

                ok, _ = await imap.select(self._folder)
                if ok != "OK":
                    logger.warning(f"[IMAP] SELECT {self._folder} failed: {ok}")
                    await asyncio.sleep(poll_interval)
                    continue

                # ── Search for all UNSEEN messages ────────────────────────
                ok, data = await imap.search("UNSEEN")
                if ok != "OK":
                    await asyncio.sleep(poll_interval)
                    continue

                uid_list: list[str] = []
                if data and data[0]:
                    raw = data[0]
                    if isinstance(raw, bytes):
                        raw = raw.decode()
                    uid_list = [u for u in raw.split() if u]

                # Filter UIDs we've already checked
                new_uids = [u for u in uid_list if u not in seen_uids]
                seen_uids.update(uid_list)

                for uid in new_uids:
                    ok, msg_data = await imap.fetch(uid, "(RFC822)")
                    if ok != "OK":
                        continue

                    # aioimaplib returns a list; find the raw bytes entry
                    raw_bytes: Optional[bytes] = None
                    for part in msg_data:
                        if isinstance(part, bytes) and len(part) > 100:
                            raw_bytes = part
                            break

                    if not raw_bytes:
                        continue

                    msg = email_lib.message_from_bytes(raw_bytes)

                    if not self._message_matches_filter(msg, filter_to):
                        continue

                    subject  = _decode_str(msg.get("Subject", ""))
                    body     = _extract_text(msg)
                    combined = f"{subject} {body}"

                    logger.debug(
                        f"[IMAP] provider={self._provider_name} uid={uid} subject={subject[:60]!r}"
                    )
                    code = _extract_code(combined)
                    if code:
                        logger.info(
                            f"[IMAP] provider={self._provider_name} uid={uid} code_found={code}"
                        )
                        await imap.logout()
                        return code

            except asyncio.TimeoutError:
                logger.warning("[IMAP] Connection timed out — retrying")
            except OSError as exc:
                logger.warning(f"[IMAP] Network error: {exc}")
            except Exception as exc:
                logger.warning(f"[IMAP] Unexpected error: {exc}")
            finally:
                if imap is not None:
                    try:
                        await imap.logout()
                    except Exception:
                        pass

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(poll_interval, remaining))

        logger.warning(
            f"[IMAP] provider={self._provider_name} poll_timeout "
            f"inbox={self._email} registration={email} filter_to={filter_to!r}"
        )
        return None


# ── Multi-account IMAP client ─────────────────────────────────────────────

class MultiIMAPMailClient(MailClient):
    """
    Wraps multiple :class:`IMAPMailClient` instances and randomly selects one
    per ``generate_email()`` call.

    The chosen client is stored per-alias-email so that a subsequent
    ``poll_code(alias_email)`` always queries the correct inbox — safe for
    concurrent registrations that share a single ``MultiIMAPMailClient`` instance.
    """

    def __init__(self, clients: list[IMAPMailClient]) -> None:
        if not clients:
            raise ValueError("MultiIMAPMailClient requires at least one account")
        self._clients = clients
        # Maps generated alias email → the IMAPMailClient that owns it.
        self._routing: dict[str, IMAPMailClient] = {}

    async def generate_email(
        self,
        prefix: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> str:
        client = random.choice(self._clients)
        addr   = await client.generate_email(prefix, domain)
        # Store mapping so poll_code() knows which inbox to check.
        self._routing[addr.lower()] = client
        return addr

    async def poll_code(self, email: str, timeout: int = 120) -> Optional[str]:
        client = self._routing.get(email.lower())
        if client is None:
            # Fallback: should not normally happen; pick random client.
            logger.warning(
                f"[IMAP] No routing entry for {email!r} — "
                "falling back to random client"
            )
            client = random.choice(self._clients)
        return await client.poll_code(email, timeout)


def build_imap_client_from_provider(
    prov: dict,
    acc: dict,
    provider_idx: int,
) -> IMAPMailClient:
    """按 provider 配置 + account 配置构造单个 IMAPMailClient。"""
    auth_type = prov.get("auth_type", "password")
    cred = acc.get("credential", "")
    return IMAPMailClient(
        email=acc.get("email", ""),
        password=cred if auth_type == "password" else "",
        host=prov.get("host", ""),
        port=int(prov.get("port", 993)),
        ssl=bool(prov.get("ssl", True)),
        folder=prov.get("folder", "INBOX"),
        use_alias=prov.get("use_alias"),
        address_mode=prov.get("address_mode"),
        registration_domain=prov.get("registration_domain", ""),
        provider_name=prov.get("name", f"imap:{provider_idx}"),
        auth_type=auth_type,
        access_token=cred if auth_type == "oauth2" else "",
    )


# ── CLI smoke-test ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import src.settings_db as settings_db

    async def _main() -> None:
        cfg      = await settings_db.build_config()
        imap_raw = (cfg.get("mail") or {}).get("imap", [])

        # Backward compat: single dict in config
        if isinstance(imap_raw, dict):
            imap_raw = [imap_raw]

        valid = [c for c in imap_raw if c.get("email")]
        if not valid:
            print(
                "No IMAP accounts found in SQLite settings.\n"
                "Open the WebUI and add entries under Settings → IMAP 账户 first.\n"
            )
            sys.exit(1)

        clients = [
            IMAPMailClient(
                email     = c["email"],
                password  = c["password"],
                host      = c["host"],
                port      = int(c.get("port", 993)),
                ssl       = bool(c.get("ssl", True)),
                folder    = c.get("folder", "INBOX"),
                use_alias = c.get("use_alias"),
            )
            for c in valid
        ]

        client = MultiIMAPMailClient(clients) if len(clients) > 1 else clients[0]
        addr   = await client.generate_email()
        print(f"Mailbox / alias: {addr}")
        print("Waiting 30 s for a verification code …")
        code = await client.poll_code(addr, timeout=30)
        print(f"Code: {code or '(none received)'}")

    asyncio.run(_main())
