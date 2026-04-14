"""Outlook provider split helper tests."""
from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest.mock import AsyncMock


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


class OutlookProviderSplitTests(unittest.TestCase):
    def _import_server(self):
        return importlib.import_module("src.webui.server")

    def test_select_outlook_accounts_keeps_mixed_rotation_for_plain_outlook(self):
        web_server = self._import_server()
        configured = [
            {"email": "imap@example.com", "fetch_method": "imap"},
            {"email": "graph@example.com", "fetch_method": "graph"},
            {"email": "default@example.com"},
        ]

        selected = web_server._select_outlook_accounts("outlook", configured)

        self.assertEqual(
            [item["email"] for item in selected],
            ["imap@example.com", "graph@example.com", "default@example.com"],
        )

    def test_select_outlook_accounts_filters_to_imap_accounts(self):
        web_server = self._import_server()
        configured = [
            {"email": "imap@example.com", "fetch_method": "imap"},
            {"email": "graph@example.com", "fetch_method": "graph"},
            {"email": "default@example.com"},
        ]

        selected = web_server._select_outlook_accounts("outlook-imap", configured)

        self.assertEqual([item["email"] for item in selected], ["imap@example.com"])

    def test_select_outlook_accounts_filters_to_graph_accounts(self):
        web_server = self._import_server()
        configured = [
            {"email": "imap@example.com", "fetch_method": "imap"},
            {"email": "graph@example.com", "fetch_method": "graph"},
            {"email": "default@example.com"},
        ]

        selected = web_server._select_outlook_accounts("outlook-graph", configured)

        self.assertEqual(
            [item["email"] for item in selected],
            ["graph@example.com", "default@example.com"],
        )

    def test_parse_outlook_provider_selector_extracts_filtered_index(self):
        web_server = self._import_server()

        family, fixed_index = web_server._parse_outlook_provider_selector("outlook-imap:1")

        self.assertEqual(family, "outlook-imap")
        self.assertEqual(fixed_index, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
