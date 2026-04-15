"""CFWorker 邮箱 provider 行为测试。"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

# 测试环境可不安装 httpx；这里提供最小桩避免导入失败。
if "httpx" not in sys.modules:
    class _RequestError(Exception):
        pass

    sys.modules["httpx"] = types.SimpleNamespace(AsyncClient=object, RequestError=_RequestError)

from src.mail import get_mail_client
from src.mail.cfworker import CFWorkerMailClient


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, data=None, text: str = "", json_error: Exception | None = None):
        self.status_code = status_code
        self._data = data
        self.text = text
        self._json_error = json_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._data


class _FakeAsyncClient:
    def __init__(self, responses, calls):
        self._responses = responses
        self._calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, *, headers=None, json=None, params=None):
        self._calls.append(
            {"method": "POST", "url": url, "headers": headers or {}, "json": json, "params": params}
        )
        return self._responses.pop(0)

    async def get(self, url, *, headers=None, params=None):
        self._calls.append(
            {"method": "GET", "url": url, "headers": headers or {}, "params": params, "json": None}
        )
        return self._responses.pop(0)


class _ErrorAsyncClient:
    def __init__(self, error):
        self._error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, *, headers=None, json=None, params=None):
        raise self._error

    async def get(self, url, *, headers=None, params=None):
        raise self._error


def _patch_async_client(responses, calls):
    return patch(
        "src.mail.cfworker.httpx.AsyncClient",
        side_effect=lambda *args, **kwargs: _FakeAsyncClient(responses, calls),
    )


def _patch_async_client_error(error):
    return patch(
        "src.mail.cfworker.httpx.AsyncClient",
        side_effect=lambda *args, **kwargs: _ErrorAsyncClient(error),
    )


class TestCFWorkerMail(unittest.IsolatedAsyncioTestCase):
    def test_domain_and_subdomain_normalize(self) -> None:
        self.assertEqual(CFWorkerMailClient._normalize_domain(" @ExAmple.COM "), "example.com")
        self.assertEqual(CFWorkerMailClient._normalize_subdomain(" .A.B..C. "), "a.b.c")

    def test_domains_and_enabled_domains_dedup_and_intersection(self) -> None:
        client = CFWorkerMailClient(
            api_url="https://cf.example",
            admin_token="adm",
            domains="A.com, b.com, a.com",
            enabled_domains=["b.com", "c.com", "B.com"],
            domain="",
        )
        self.assertEqual(client._domains, ["a.com", "b.com"])
        self.assertEqual(client._enabled_domains, ["b.com"])

    def test_pick_domain_priority(self) -> None:
        client = CFWorkerMailClient(
            api_url="https://cf.example",
            admin_token="adm",
            domain="d0.com",
            domains=["d1.com", "d2.com"],
            enabled_domains=["d2.com"],
        )
        self.assertEqual(client._pick_domain(), "d2.com")

        client2 = CFWorkerMailClient(
            api_url="https://cf.example",
            admin_token="adm",
            domain="d0.com",
            domains=["d1.com", "d2.com"],
            enabled_domains=[],
        )
        self.assertIn(client2._pick_domain(), {"d1.com", "d2.com"})

        client3 = CFWorkerMailClient(
            api_url="https://cf.example",
            admin_token="adm",
            domain="d0.com",
            domains=[],
            enabled_domains=[],
        )
        self.assertEqual(client3._pick_domain(), "d0.com")

    def test_compose_domain_order_random_then_subdomain(self) -> None:
        client = CFWorkerMailClient(
            api_url="https://cf.example",
            admin_token="adm",
            domain="base.com",
            subdomain="fixed",
            random_subdomain=True,
        )
        with patch.object(client, "_generate_subdomain_label", return_value="rnd123"):
            self.assertEqual(client._compose_domain("base.com"), "rnd123.fixed.base.com")

    async def test_generate_email_post_admin_new_address(self) -> None:
        calls = []
        responses = [_FakeResponse(data={"email": "abc@a.b.com", "token": "t123"})]
        client = CFWorkerMailClient(
            api_url="https://cf.example/",
            admin_token="adm",
            custom_auth="site-pass",
            fingerprint="fp-1",
            domain="base.com",
            subdomain="fixed",
            random_subdomain=True,
        )
        with patch.object(client, "_generate_local_part", return_value="name001"), patch.object(
            client, "_generate_subdomain_label", return_value="rnd123"
        ), _patch_async_client(responses, calls):
            got = await client.generate_email()

        self.assertEqual(got, "abc@a.b.com")
        self.assertEqual(len(calls), 1)
        req = calls[0]
        self.assertEqual(req["method"], "POST")
        self.assertEqual(req["url"], "https://cf.example/admin/new_address")
        self.assertEqual(req["headers"]["x-admin-auth"], "adm")
        self.assertEqual(req["headers"]["x-custom-auth"], "site-pass")
        self.assertEqual(req["headers"]["x-fingerprint"], "fp-1")
        self.assertEqual(
            req["json"],
            {"enablePrefix": True, "name": "name001", "domain": "rnd123.fixed.base.com"},
        )

    async def test_poll_code_extracts_6_and_fallback_4_8(self) -> None:
        client = CFWorkerMailClient(
            api_url="https://cf.example",
            admin_token="adm",
            domain="base.com",
        )

        calls1 = []
        responses1 = [_FakeResponse(data={"results": [{"subject": "your code is 123456"}]})]
        with _patch_async_client(responses1, calls1):
            code = await client.poll_code("a@b.com", timeout=1)
        self.assertEqual(code, "123456")
        self.assertEqual(calls1[0]["url"], "https://cf.example/admin/mails")
        self.assertEqual(calls1[0]["params"]["address"], "a@b.com")
        self.assertEqual(calls1[0]["params"]["limit"], 20)
        self.assertEqual(calls1[0]["params"]["offset"], 0)

        calls2 = []
        responses2 = [_FakeResponse(data={"results": [{"text": "pin: 1234"}]})]
        with _patch_async_client(responses2, calls2):
            code2 = await client.poll_code("a@b.com", timeout=1)
        self.assertEqual(code2, "1234")

    async def test_poll_code_extracts_code_from_raw_message(self) -> None:
        client = CFWorkerMailClient(
            api_url="https://cf.example",
            admin_token="adm",
            domain="base.com",
        )
        raw_mail = (
            "Subject: Your ChatGPT code is 551965\r\n"
            "Content-Type: text/plain; charset=UTF-8\r\n"
            "\r\n"
            "OpenAI\\n\\nEnter this temporary verification code to continue:\\n\\n551965"
        )
        calls = []
        responses = [_FakeResponse(data={"results": [{"id": 852, "subject": "Your ChatGPT code is 551965", "raw": raw_mail}]})]
        with _patch_async_client(responses, calls):
            code = await client.poll_code("a@b.com", timeout=1)
        self.assertEqual(code, "551965")

    async def test_poll_code_prefers_newer_mail_by_id(self) -> None:
        client = CFWorkerMailClient(
            api_url="https://cf.example",
            admin_token="adm",
            domain="base.com",
        )
        calls = []
        responses = [_FakeResponse(data={"results": [
            {"id": 847, "subject": "Your ChatGPT code is 111111"},
            {"id": 852, "subject": "Your ChatGPT code is 222222"},
        ]})]
        with _patch_async_client(responses, calls):
            code = await client.poll_code("a@b.com", timeout=1)
        self.assertEqual(code, "222222")

    async def test_poll_code_timeout_returns_none(self) -> None:
        client = CFWorkerMailClient(
            api_url="https://cf.example",
            admin_token="adm",
            domain="base.com",
        )
        self.assertIsNone(await client.poll_code("a@b.com", timeout=0))

    async def test_missing_api_url(self) -> None:
        client = CFWorkerMailClient(
            api_url="",
            admin_token="adm",
            domain="base.com",
        )
        with self.assertRaisesRegex(RuntimeError, "api_url"):
            await client.generate_email()

    def test_missing_domain_sources(self) -> None:
        with self.assertRaisesRegex(ValueError, "domain"):
            CFWorkerMailClient(
                api_url="https://cf.example",
                admin_token="adm",
                domain="",
                domains=[],
                enabled_domains=[],
            )

    def test_enabled_domains_intersection_empty(self) -> None:
        with self.assertRaisesRegex(ValueError, "enabled_domains"):
            CFWorkerMailClient(
                api_url="https://cf.example",
                admin_token="adm",
                domain="",
                domains=["a.com"],
                enabled_domains=["b.com"],
            )

    def test_enabled_domains_fold_to_empty_when_domains_empty(self) -> None:
        client = CFWorkerMailClient(
            api_url="https://cf.example",
            admin_token="adm",
            domain="base.com",
            domains=[],
            enabled_domains=["a.com"],
        )
        self.assertEqual(client._enabled_domains, [])

    def test_enabled_domains_only_cannot_bypass_missing_domain_sources(self) -> None:
        with self.assertRaisesRegex(ValueError, "enabled_domains.*domains"):
            CFWorkerMailClient(
                api_url="https://cf.example",
                admin_token="adm",
                domain="",
                domains=[],
                enabled_domains=["a.com"],
            )

    async def test_missing_admin_token(self) -> None:
        client = CFWorkerMailClient(
            api_url="https://cf.example",
            admin_token="",
            domain="base.com",
        )
        with self.assertRaisesRegex(RuntimeError, "admin_token"):
            await client.generate_email()

    async def test_httpx_request_error_contains_path_and_url(self) -> None:
        request_error_cls = getattr(sys.modules["httpx"], "RequestError")
        client = CFWorkerMailClient(
            api_url="https://cf.example",
            admin_token="adm",
            domain="base.com",
        )
        with _patch_async_client_error(request_error_cls("dial tcp timeout")):
            with self.assertRaises(RuntimeError) as ctx:
                await client.generate_email()
        msg = str(ctx.exception)
        self.assertIn("/admin/new_address", msg)
        self.assertIn("https://cf.example/admin/new_address", msg)

    async def test_request_json_unknown_method_raises(self) -> None:
        client = CFWorkerMailClient(
            api_url="https://cf.example",
            admin_token="adm",
            domain="base.com",
        )
        with self.assertRaisesRegex(ValueError, "unsupported HTTP method"):
            await client._request_json("PUT", "/admin/new_address")

    async def test_non_json_response(self) -> None:
        calls = []
        responses = [_FakeResponse(text="<html>oops</html>", json_error=ValueError("bad json"))]
        client = CFWorkerMailClient(
            api_url="https://cf.example",
            admin_token="adm",
            domain="base.com",
        )
        with patch.object(client, "_generate_local_part", return_value="name001"), _patch_async_client(
            responses, calls
        ):
            with self.assertRaisesRegex(RuntimeError, "non-JSON|非 JSON"):
                await client.generate_email()

    async def test_http_error_contains_path_and_status(self) -> None:
        calls = []
        responses = [_FakeResponse(status_code=503, text="unavailable", data={"message": "down"})]
        client = CFWorkerMailClient(
            api_url="https://cf.example",
            admin_token="adm",
            domain="base.com",
        )
        with patch.object(client, "_generate_local_part", return_value="name001"), _patch_async_client(
            responses, calls
        ):
            with self.assertRaises(RuntimeError) as ctx:
                await client.generate_email()
        msg = str(ctx.exception)
        self.assertIn("/admin/new_address", msg)
        self.assertIn("503", msg)

    async def test_response_missing_email(self) -> None:
        calls = []
        responses = [_FakeResponse(data={"token": "jwt-token"})]
        client = CFWorkerMailClient(
            api_url="https://cf.example",
            admin_token="adm",
            domain="base.com",
        )
        with patch.object(client, "_generate_local_part", return_value="name001"), _patch_async_client(
            responses, calls
        ):
            with self.assertRaisesRegex(RuntimeError, "email"):
                await client.generate_email()

    async def test_new_address_missing_token_has_compat_hint(self) -> None:
        calls = []
        responses = [_FakeResponse(data={"email": "x@base.com"})]
        client = CFWorkerMailClient(
            api_url="https://cf.example",
            admin_token="adm",
            domain="base.com",
        )
        with patch.object(client, "_generate_local_part", return_value="name001"), _patch_async_client(
            responses, calls
        ):
            with self.assertRaisesRegex(RuntimeError, "token|jwt|兼容"):
                await client.generate_email()

    async def test_private_site_password_requires_custom_auth_hint(self) -> None:
        calls = []
        responses = [_FakeResponse(status_code=401, text="This site has private site password")]
        client = CFWorkerMailClient(
            api_url="https://cf.example",
            admin_token="adm",
            domain="base.com",
        )
        with patch.object(client, "_generate_local_part", return_value="name001"), _patch_async_client(
            responses, calls
        ):
            with self.assertRaisesRegex(RuntimeError, "custom_auth"):
                await client.generate_email()

    def test_get_mail_client_cfworker(self) -> None:
        cfg = {
            "mail": {
                "cfworker": {
                    "api_url": "https://cf.example",
                    "admin_token": "adm",
                    "domain": "base.com",
                }
            }
        }
        client = get_mail_client("cfworker", cfg=cfg)
        self.assertIsInstance(client, CFWorkerMailClient)


if __name__ == "__main__":
    unittest.main(verbosity=2)
