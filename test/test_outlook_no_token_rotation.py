"""Outlook no-token 轮换选择测试。"""
from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch


def _install_test_stubs() -> None:
    if "loguru" not in sys.modules:
        fake_loguru = types.ModuleType("loguru")

        class _FakeLogger:
            def __getattr__(self, _name):
                return lambda *_args, **_kwargs: None

        fake_loguru.logger = _FakeLogger()
        sys.modules["loguru"] = fake_loguru

    if "aiosqlite" not in sys.modules:
        fake_aiosqlite = types.ModuleType("aiosqlite")

        class _FakeRow(dict):
            pass

        async def _unused_connect(*_args, **_kwargs):
            raise AssertionError("测试不应触发真实 aiosqlite.connect")

        fake_aiosqlite.Row = _FakeRow
        fake_aiosqlite.connect = _unused_connect
        sys.modules["aiosqlite"] = fake_aiosqlite

    if "uvicorn" not in sys.modules:
        fake_uvicorn = types.ModuleType("uvicorn")
        fake_uvicorn.run = lambda *_args, **_kwargs: None
        sys.modules["uvicorn"] = fake_uvicorn

    if "httpx" not in sys.modules:
        fake_httpx = types.ModuleType("httpx")

        class _FakeHTTPError(Exception):
            pass

        class _FakeRequestError(_FakeHTTPError):
            pass

        class _AsyncClientPlaceholder:
            def __init__(self, *_args, **_kwargs):
                raise AssertionError("测试不应触发真实 httpx.AsyncClient")

        fake_httpx.HTTPError = _FakeHTTPError
        fake_httpx.RequestError = _FakeRequestError
        fake_httpx.AsyncClient = _AsyncClientPlaceholder
        sys.modules["httpx"] = fake_httpx

    if "fastapi" not in sys.modules:
        fake_fastapi = types.ModuleType("fastapi")

        class HTTPException(Exception):
            def __init__(self, status_code: int, detail):
                super().__init__(detail)
                self.status_code = status_code
                self.detail = detail

        class Request:
            pass

        class FastAPI:
            def __init__(self, *_args, **_kwargs):
                self.routes = []

            def _route(self, *_args, **_kwargs):
                def decorator(func):
                    self.routes.append(func)
                    return func

                return decorator

            get = post = delete = _route

            def mount(self, *_args, **_kwargs):
                return None

        fake_fastapi.FastAPI = FastAPI
        fake_fastapi.HTTPException = HTTPException
        fake_fastapi.Request = Request
        sys.modules["fastapi"] = fake_fastapi

        fake_responses = types.ModuleType("fastapi.responses")

        class Response:
            def __init__(self, content=None, media_type=None, headers=None, status_code: int = 200):
                self.content = content
                self.media_type = media_type
                self.headers = headers or {}
                self.status_code = status_code

        class HTMLResponse(Response):
            pass

        fake_responses.Response = Response
        fake_responses.HTMLResponse = HTMLResponse
        sys.modules["fastapi.responses"] = fake_responses

        fake_staticfiles = types.ModuleType("fastapi.staticfiles")

        class StaticFiles:
            def __init__(self, *_args, **_kwargs):
                pass

        fake_staticfiles.StaticFiles = StaticFiles
        sys.modules["fastapi.staticfiles"] = fake_staticfiles

    if "src.mail" not in sys.modules:
        fake_mail = types.ModuleType("src.mail")
        fake_mail.get_mail_client = lambda *_args, **_kwargs: object()
        sys.modules["src.mail"] = fake_mail

    if "src.mail.imap" not in sys.modules:
        fake_mail_imap = types.ModuleType("src.mail.imap")
        fake_mail_imap.build_imap_client_from_provider = lambda *_args, **_kwargs: object()
        fake_mail_imap.is_provider_based_imap_config = lambda *_args, **_kwargs: False
        fake_mail_imap.parse_imap_selector = lambda *_args, **_kwargs: (None, None)
        sys.modules["src.mail.imap"] = fake_mail_imap

    if "src.mail.outlook" not in sys.modules:
        fake_mail_outlook = types.ModuleType("src.mail.outlook")

        class OutlookMailClient:
            def __init__(self, *_args, **_kwargs):
                pass

        fake_mail_outlook.OutlookMailClient = OutlookMailClient
        sys.modules["src.mail.outlook"] = fake_mail_outlook

    if "src.proxy_pool" not in sys.modules:
        fake_proxy_pool = types.ModuleType("src.proxy_pool")
        fake_proxy_pool.acquire = AsyncMock(return_value=None)
        fake_proxy_pool.report_result = AsyncMock(return_value=None)
        fake_proxy_pool.list_all = AsyncMock(return_value=[])
        fake_proxy_pool.add = AsyncMock(return_value=None)
        fake_proxy_pool.remove = AsyncMock(return_value=None)
        sys.modules["src.proxy_pool"] = fake_proxy_pool

    if "src.browser.register" not in sys.modules:
        fake_mod = types.ModuleType("src.browser.register")

        async def _fake_register_one(*_args, **_kwargs):
            return {}

        fake_mod.register_one = _fake_register_one
        sys.modules["src.browser.register"] = fake_mod

    if "src.post_register" not in sys.modules:
        fake_post_register = types.ModuleType("src.post_register")

        async def _fake_persist(account, *_args, **_kwargs):
            return account

        fake_post_register.persist_account_and_maybe_upload = _fake_persist
        sys.modules["src.post_register"] = fake_post_register


_install_test_stubs()


class OutlookNoTokenRotationTests(unittest.TestCase):
    def _import_server(self):
        return importlib.import_module("src.webui.server")

    def test_build_outlook_rotation_stats_counts_remaining_no_token_accounts(self):
        web_server = self._import_server()
        stats = web_server._build_outlook_rotation_stats(
            [
                {"email": "done@example.com"},
                {"email": "todo@example.com"},
                {"email": "todo2@example.com"},
                {"email": " "},
            ],
            {"done@example.com", "other@example.com"},
        )

        self.assertEqual(stats["configured"], 3)
        self.assertEqual(stats["with_token"], 1)
        self.assertEqual(stats["without_token"], 2)

    def test_select_outlook_accounts_keeps_full_rotation_for_plain_outlook(self):
        web_server = self._import_server()
        configured = [
            {"email": "done@example.com"},
            {"email": "todo@example.com"},
        ]

        selected = web_server._select_outlook_accounts(
            "outlook",
            configured,
            {"done@example.com"},
        )

        self.assertEqual(
            [item["email"] for item in selected],
            ["done@example.com", "todo@example.com"],
        )

    def test_select_outlook_accounts_filters_existing_token_emails(self):
        web_server = self._import_server()
        configured = [
            {"email": " Done@Example.com "},
            {"email": "todo@example.com"},
            {"email": "  "},
        ]

        selected = web_server._select_outlook_accounts(
            "outlook:no-token",
            configured,
            {"done@example.com"},
        )

        self.assertEqual([item["email"] for item in selected], ["todo@example.com"])

    def test_select_outlook_accounts_excludes_phone_required_emails(self):
        web_server = self._import_server()
        configured = [
            {"email": "todo@example.com"},
            {"email": "blocked@example.com"},
        ]

        selected = web_server._select_outlook_accounts(
            "outlook:no-token",
            configured,
            token_emails=set(),
            blocked_emails={"blocked@example.com"},
        )

        self.assertEqual([item["email"] for item in selected], ["todo@example.com"])

    def test_build_outlook_rotation_stats_excludes_phone_required_emails_from_remaining_pool(self):
        web_server = self._import_server()
        stats = web_server._build_outlook_rotation_stats(
            [
                {"email": "done@example.com"},
                {"email": "todo@example.com"},
                {"email": "blocked@example.com"},
            ],
            {"done@example.com"},
            {"blocked@example.com"},
        )

        self.assertEqual(stats["configured"], 3)
        self.assertEqual(stats["with_token"], 1)
        self.assertEqual(stats["without_token"], 1)

    def test_job_records_finished_timestamp_when_marked_done(self):
        web_server = self._import_server()
        with patch("src.webui.server.time.time", side_effect=[100.0, 160.0]):
            job = web_server._Job("job-1", 1, "outlook:no-token", "camoufox", "none")
            job.set_status("done")
            payload = job.to_dict()

        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["started"], 100.0)
        self.assertEqual(payload["finished"], 160.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
