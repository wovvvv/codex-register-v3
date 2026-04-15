"""
mail/cfworker.py — CFWorker mail client.
"""
from __future__ import annotations

import asyncio
import json
import html as html_lib
import random
import re
import string
import time
import quopri
from typing import Any, Optional

import httpx

from src.mail.base import MailClient


def _extract_code(text: str) -> Optional[str]:
    text = str(text or "")
    m = re.search(r"\b(\d{6})\b", text)
    if m:
        return m.group(1)
    m = re.search(r"\b(\d{4,8})\b", text)
    return m.group(1) if m else None


def _decode_raw_content(raw: str) -> str:
    """解析 Worker 返回的原始邮件内容，尽量还原正文文本。"""
    text = str(raw or "")
    if not text:
        return ""
    if "\r\n\r\n" in text:
        text = text.split("\r\n\r\n", 1)[1]
    elif "\n\n" in text:
        text = text.split("\n\n", 1)[1]
    try:
        text = quopri.decodestring(text).decode("utf-8", errors="ignore")
    except Exception:
        pass
    text = html_lib.unescape(text)
    text = re.sub(r"(?im)^content-(?:type|transfer-encoding):.*$", " ", text)
    text = re.sub(r"(?im)^--+[_=\w.-]+$", " ", text)
    text = re.sub(r"(?i)----=_part_[\w.]+", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


class CFWorkerMailClient(MailClient):
    def __init__(
        self,
        *,
        api_url: str = "",
        admin_token: str = "",
        custom_auth: str = "",
        domain: str = "",
        domains: Any = None,
        enabled_domains: Any = None,
        subdomain: str = "",
        random_subdomain: Any = False,
        fingerprint: str = "",
    ) -> None:
        self._api_url = str(api_url or "").strip().rstrip("/")
        self._admin_token = str(admin_token or "").strip()
        self._custom_auth = str(custom_auth or "").strip()
        self._domain = self._normalize_domain(domain)
        self._domains = self._parse_domains(domains)
        self._enabled_domains = self._normalize_enabled_domains(
            enabled_domains=enabled_domains,
            domains=self._domains,
        )
        self._subdomain = self._normalize_subdomain(subdomain)
        self._random_subdomain = self._to_bool(random_subdomain)
        self._fingerprint = str(fingerprint or "").strip()
        if not (self._enabled_domains or self._domains or self._domain):
            raise ValueError(
                "CFWorker requires at least one domain source: domains/domain. "
                "Note: enabled_domains only works together with domains."
            )

    @staticmethod
    def _normalize_domain(domain: Any) -> str:
        value = str(domain or "").strip().lower()
        if value.startswith("@"):
            value = value[1:]
        return value

    @staticmethod
    def _normalize_subdomain(value: Any) -> str:
        sub = str(value or "").strip().lower().strip(".")
        if sub.startswith("@"):
            sub = sub[1:]
        parts = [part for part in sub.split(".") if part]
        return ".".join(parts)

    @classmethod
    def _parse_domains(cls, value: Any) -> list[str]:
        if not value:
            return []
        if isinstance(value, (list, tuple, set)):
            items = list(value)
        elif isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = None
            if isinstance(parsed, list):
                items = parsed
            else:
                items = [part for chunk in text.splitlines() for part in chunk.split(",")]
        else:
            items = [value]

        result: list[str] = []
        seen: set[str] = set()
        for item in items:
            domain = cls._normalize_domain(item)
            if not domain or domain in seen:
                continue
            seen.add(domain)
            result.append(domain)
        return result

    @staticmethod
    def _to_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() in {"1", "true", "yes", "on"}

    @classmethod
    def _normalize_enabled_domains(cls, *, enabled_domains: Any, domains: list[str]) -> list[str]:
        parsed_enabled = cls._parse_domains(enabled_domains)
        if not parsed_enabled:
            return []
        # 语义约束：enabled_domains 只是 domains 的“启用子集”，不能单独作为域名来源。
        if not domains:
            return []
        allow = set(domains)
        filtered = [d for d in parsed_enabled if d in allow]
        if parsed_enabled and domains and not filtered:
            raise ValueError("CFWorker enabled_domains has empty intersection with domains")
        return filtered

    def _pick_domain(self) -> str:
        if self._enabled_domains:
            return random.choice(self._enabled_domains)
        if self._domains:
            return random.choice(self._domains)
        return self._domain

    def _generate_subdomain_label(self, length: int = 6) -> str:
        alphabet = string.ascii_lowercase + string.digits
        return "".join(random.choices(alphabet, k=length))

    def _compose_domain(self, base_domain: str) -> str:
        domain = self._normalize_domain(base_domain)
        if not domain:
            return ""
        parts: list[str] = []
        if self._random_subdomain:
            parts.append(self._generate_subdomain_label())
        if self._subdomain:
            parts.append(self._subdomain)
        if not parts:
            return domain
        return f"{'.'.join(parts)}.{domain}"

    def _generate_local_part(self) -> str:
        letters = "".join(random.choices(string.ascii_lowercase, k=6))
        digits = "".join(random.choices(string.digits, k=4))
        return f"{letters}{digits}"

    def _headers(self) -> dict[str, str]:
        h = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "x-admin-auth": self._admin_token,
        }
        if self._custom_auth:
            h["x-custom-auth"] = self._custom_auth
        if self._fingerprint:
            h["x-fingerprint"] = self._fingerprint
        return h

    def _ensure_api_configured(self) -> None:
        if not self._api_url:
            raise RuntimeError("CFWorker api_url is required")
        if not self._admin_token:
            raise RuntimeError("CFWorker admin_token is required")

    @staticmethod
    def _json_or_error(response: Any, *, path: str) -> Any:
        try:
            return response.json()
        except Exception as exc:
            preview = (getattr(response, "text", "") or "").strip()[:200] or "<empty>"
            raise RuntimeError(
                f"CFWorker API {path} returned non-JSON response: HTTP {response.status_code} {preview}"
            ) from exc

    @staticmethod
    def _raise_http_error_if_needed(response: Any, *, path: str) -> None:
        status = int(getattr(response, "status_code", 0) or 0)
        if status < 400:
            return
        body = (getattr(response, "text", "") or "").strip()
        preview = body[:200] or "<empty>"
        if "private site password" in body.lower():
            raise RuntimeError(
                f"CFWorker API {path} failed: HTTP {status}. Please configure custom_auth for private site password."
            )
        raise RuntimeError(f"CFWorker API {path} failed: HTTP {status} {preview}")

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
        timeout: int = 15,
    ) -> Any:
        self._ensure_api_configured()
        url = f"{self._api_url}{path}"
        verb = method.upper()
        if verb not in {"GET", "POST"}:
            raise ValueError(f"CFWorker unsupported HTTP method: {method!r}")
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                if verb == "POST":
                    response = await client.post(url, headers=self._headers(), json=payload or {}, params=params)
                else:
                    response = await client.get(url, headers=self._headers(), params=params)
        except Exception as exc:
            request_error_type = getattr(httpx, "RequestError", None)
            if request_error_type is not None and isinstance(exc, request_error_type):
                raise RuntimeError(f"CFWorker API request failed: {path} ({url}): {exc}") from exc
            raise
        self._raise_http_error_if_needed(response, path=path)
        return self._json_or_error(response, path=path)

    async def generate_email(
        self,
        prefix: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> str:
        selected = self._compose_domain(domain or self._pick_domain())
        name = str(prefix or "").strip() or self._generate_local_part()
        payload: dict[str, Any] = {
            "enablePrefix": True,
            "name": name,
        }
        if selected:
            payload["domain"] = selected
        data = await self._request_json(
            "POST",
            "/admin/new_address",
            payload=payload,
            timeout=15,
        )
        if not isinstance(data, dict):
            raise RuntimeError(f"CFWorker API /admin/new_address returned invalid payload: {data!r}")
        email = data.get("email") or data.get("address")
        if not email:
            raise RuntimeError(f"CFWorker API /admin/new_address response missing email: {data}")
        token = data.get("token") or data.get("jwt")
        if not token:
            raise RuntimeError(
                "CFWorker API /admin/new_address response missing token/jwt. "
                "Please check worker API compatibility."
            )
        return str(email)

    async def poll_code(self, email: str, timeout: int = 120) -> Optional[str]:
        deadline = time.monotonic() + max(int(timeout or 0), 0)
        while time.monotonic() < deadline:
            data = await self._request_json(
                "GET",
                "/admin/mails",
                params={"limit": 20, "offset": 0, "address": email},
                timeout=10,
            )
            mails: list[Any]
            if isinstance(data, dict):
                mails = data.get("results") or data.get("mails") or data.get("data") or []
            elif isinstance(data, list):
                mails = data
            else:
                mails = []

            sortable_mails = [mail for mail in mails if isinstance(mail, dict)]
            sortable_mails.sort(key=lambda m: int(m.get("id", 0) or 0), reverse=True)

            for mail in sortable_mails:
                if not isinstance(mail, dict):
                    continue
                decoded_raw = _decode_raw_content(mail.get("raw", ""))
                merged = " ".join(
                    filter(
                        None,
                        [
                            str(mail.get("subject", "")),
                            str(mail.get("text", "")),
                            str(mail.get("content", "")),
                            str(mail.get("html", "")),
                            str(mail.get("body", "")),
                            decoded_raw,
                        ],
                    )
                )
                code = _extract_code(merged)
                if code:
                    return code

            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(3)
        return None
