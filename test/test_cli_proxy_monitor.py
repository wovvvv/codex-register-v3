"""CLI Proxy 认证文件监控测试。"""
from __future__ import annotations

import copy
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

    if "httpx" not in sys.modules:
        fake_httpx = types.ModuleType("httpx")

        class _FakeHTTPError(Exception):
            pass

        class _FakeRequestError(_FakeHTTPError):
            pass

        class _AsyncClientPlaceholder:
            def __init__(self, *_args, **_kwargs):
                raise AssertionError("测试应显式 patch httpx.AsyncClient")

        fake_httpx.HTTPError = _FakeHTTPError
        fake_httpx.RequestError = _FakeRequestError
        fake_httpx.AsyncClient = _AsyncClientPlaceholder
        sys.modules["httpx"] = fake_httpx

    if "uvicorn" not in sys.modules:
        fake_uvicorn = types.ModuleType("uvicorn")
        fake_uvicorn.run = lambda *_args, **_kwargs: None
        sys.modules["uvicorn"] = fake_uvicorn

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


def _import_web_server():
    return importlib.import_module("src.webui.server")


class CliProxyMonitorConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_config_contains_cli_proxy_monitor_defaults(self):
        import src.settings_db as settings_db

        fake_db = copy.deepcopy(settings_db._DEFAULTS)
        with patch("src.settings_db.get_all", new=AsyncMock(return_value=fake_db)):
            cfg = await settings_db.build_config()

        self.assertEqual(cfg["cli_proxy"]["monitor_interval_minutes"], 180)
        self.assertEqual(cfg["cli_proxy"]["monitor_active_probe"], False)
        self.assertEqual(cfg["cli_proxy"]["monitor_probe_timeout"], 8)


class CliProxyMonitorLogicTests(unittest.IsolatedAsyncioTestCase):
    async def test_match_status_401_reason_detects_status_and_message(self):
        monitor = importlib.import_module("src.integrations.cli_proxy_monitor")

        self.assertEqual(monitor.match_status_401_reason({"status": 401}), "status_401")
        self.assertEqual(
            monitor.match_status_401_reason({"status_message": "额度获取失败：401"}),
            "status_message_401",
        )
        self.assertEqual(
            monitor.match_status_401_reason({"status_message": "Unauthorized token"}),
            "status_message_401",
        )
        self.assertEqual(monitor.match_status_401_reason({"status": "active"}), "")

    async def test_scan_and_delete_invalid_auth_files_deletes_only_401_hits(self):
        monitor = importlib.import_module("src.integrations.cli_proxy_monitor")
        cfg = {"cli_proxy": {"cpa_url": "https://cpa.example.com/management.html#/", "api_key": "k"}}
        files = [
            {"name": "bad.json", "provider": "codex", "status": 401, "status_message": "", "email": "bad@example.com"},
            {"name": "good.json", "provider": "codex", "status": "active", "status_message": "", "email": "good@example.com"},
        ]
        history = AsyncMock()

        with (
            patch("src.integrations.cli_proxy_monitor.list_auth_files", new=AsyncMock(return_value=files)),
            patch("src.integrations.cli_proxy_monitor.delete_auth_file", new=AsyncMock(return_value={"ok": True})),
        ):
            result = await monitor.scan_and_delete_invalid_auth_files(
                cfg,
                active_probe=False,
                probe_timeout=8,
                record_history=history,
            )

        self.assertEqual(result["checked"], 2)
        self.assertEqual(result["deleted"], 1)
        self.assertEqual(result["records"][0]["file_name"], "bad.json")
        self.assertEqual(result["records"][0]["source"], "status_scan")
        self.assertEqual(result["records"][0]["reason"], "status_401")
        history.assert_awaited_once()


class CliProxyMonitorApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_monitor_status_and_history_apis_proxy_manager_state(self):
        web_server = _import_web_server()

        class _FakeManager:
            async def get_status(self):
                return {"running": True, "next_run_at": 123}

            async def get_history(self, limit=100):
                return [{"file_name": "bad.json"}]

        with patch("src.webui.server.cli_proxy_monitor_mod.monitor_manager", new=_FakeManager()):
            status = await web_server.api_cli_proxy_monitor_status()
            history = await web_server.api_cli_proxy_monitor_history()

        self.assertTrue(status["running"])
        self.assertEqual(history["items"][0]["file_name"], "bad.json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
