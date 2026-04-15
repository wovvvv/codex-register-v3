"""CLI Proxy 上传链路后端测试。"""
from __future__ import annotations

import base64
import copy
import importlib
import io
import json
import sys
import tempfile
import types
import unittest
import zipfile
from unittest.mock import AsyncMock, patch


def _install_test_stubs() -> None:
    """为缺失依赖注入最小桩，保证测试只验证目标行为。"""
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


_install_test_stubs()


def _b64url(data: dict) -> str:
    raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _make_jwt(payload: dict) -> str:
    return f"{_b64url({'alg': 'none', 'typ': 'JWT'})}.{_b64url(payload)}.sig"


class _FakeResponse:
    def __init__(self, status_code: int, *, text: str = "", json_body=None, json_error: bool = False):
        self.status_code = status_code
        self.text = text
        self._json_body = json_body
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("not json")
        if self._json_body is None:
            return {}
        return self._json_body


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse):
        self.response = response
        self.calls: list[tuple[tuple, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


class _FakeRequest:
    def __init__(self, body: dict):
        self._body = body

    async def json(self):
        return self._body


def _import_web_server():
    # 避免测试时拉起真实浏览器依赖。
    if "src.browser.register" not in sys.modules:
        fake_mod = types.ModuleType("src.browser.register")

        async def _fake_register_one(*_args, **_kwargs):
            return {}

        fake_mod.register_one = _fake_register_one
        sys.modules["src.browser.register"] = fake_mod
    return importlib.import_module("src.webui.server")


class CliProxyConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_config_contains_cli_proxy_defaults(self):
        import src.settings_db as settings_db

        fake_db = copy.deepcopy(settings_db._DEFAULTS)
        with patch("src.settings_db.get_all", new=AsyncMock(return_value=fake_db)):
            cfg = await settings_db.build_config()

        self.assertIn("cli_proxy", cfg)
        self.assertEqual(cfg["cli_proxy"]["cpa_url"], "")
        self.assertEqual(cfg["cli_proxy"]["api_key"], "")


class CliProxyIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_cli_proxy_token_json_prefers_existing_fields(self):
        from src.integrations.cli_proxy import build_cli_proxy_token_json

        account = {
            "email": "user@example.com",
            "access_token": _make_jwt({"exp": 9999999999}),
            "refresh_token": "rt_123",
            "account_id": "acc_1",
            "_raw": {
                "id_token": "id_123",
                "expired": "2026-04-16T23:36:56+08:00",
                "last_refresh": "2026-04-07T12:00:00+08:00",
            },
        }
        result = build_cli_proxy_token_json(account)
        self.assertEqual(result["type"], "codex")
        self.assertEqual(result["email"], "user@example.com")
        self.assertEqual(result["id_token"], "id_123")
        self.assertEqual(result["expired"], "2026-04-16T23:36:56+08:00")
        self.assertEqual(result["last_refresh"], "2026-04-07T12:00:00+08:00")
        self.assertEqual(result["refresh_token"], "rt_123")
        self.assertEqual(result["account_id"], "acc_1")

    async def test_resolve_cli_proxy_base_url_accepts_management_url(self):
        from src.integrations.cli_proxy import resolve_cli_proxy_base_url

        cfg = {
            "cli_proxy": {
                "cpa_url": " http://127.0.0.1:8317/management.html#/ ",
                "api_key": "k",
            }
        }
        self.assertEqual(resolve_cli_proxy_base_url(cfg, None), "http://127.0.0.1:8317")

    async def test_upload_account_to_cli_proxy_request_shape(self):
        from src.integrations import cli_proxy

        account = {
            "email": "shape@example.com",
            "access_token": _make_jwt({"exp": 1893456000}),
            "refresh_token": "rt_shape",
            "account_id": "acc_shape",
        }
        cfg = {
            "cli_proxy": {
                "cpa_url": "http://127.0.0.1:8317/management.html#/",
                "api_key": "sk-test",
            }
        }
        fake_client = _FakeAsyncClient(_FakeResponse(201, json_body={"ok": True}))
        with patch("src.integrations.cli_proxy.httpx.AsyncClient", return_value=fake_client):
            ok, _msg = await cli_proxy.upload_account_to_cli_proxy(account, cfg)

        self.assertTrue(ok)
        self.assertEqual(len(fake_client.calls), 1)
        args, kwargs = fake_client.calls[0]
        self.assertEqual(args[0], "http://127.0.0.1:8317/v0/management/auth-files")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer sk-test")
        uploaded = kwargs["files"]["file"]
        self.assertEqual(uploaded[0], "shape@example.com.json")
        self.assertEqual(uploaded[2], "application/json")
        payload = json.loads(uploaded[1].decode("utf-8"))
        self.assertEqual(payload["email"], "shape@example.com")
        self.assertEqual(payload["type"], "codex")

    async def test_upload_account_to_cli_proxy_returns_false_on_http_error(self):
        from src.integrations import cli_proxy

        account = {"email": "bad@example.com", "access_token": _make_jwt({"exp": 1893456000})}
        cfg = {
            "cli_proxy": {
                "cpa_url": "http://127.0.0.1:8317/management.html#/",
                "api_key": "sk-test",
            }
        }
        fake_client = _FakeAsyncClient(_FakeResponse(500, text="server error", json_error=True))
        with patch("src.integrations.cli_proxy.httpx.AsyncClient", return_value=fake_client):
            ok, msg = await cli_proxy.upload_account_to_cli_proxy(account, cfg)
        self.assertFalse(ok)
        self.assertIn("HTTP 500", msg)

    async def test_build_cpa_export_zip_bytes_filters_missing_token_accounts(self):
        import src.accounts as accounts

        rows = [
            {
                "email": "with@example.com",
                "password": "pw1",
                "access_token": _make_jwt({"exp": 1893456000}),
                "refresh_token": "rt1",
                "account_id": "acc1",
            },
            {
                "email": "skip@example.com",
                "password": "pw2",
                "access_token": "",
            },
        ]

        content, count = accounts.build_cpa_export_zip_bytes(rows)

        self.assertEqual(count, 1)
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            self.assertEqual(
                sorted(zf.namelist()),
                ["accounts/with@example.com.json", "passwords.txt"],
            )
            payload = json.loads(zf.read("accounts/with@example.com.json").decode("utf-8"))
            self.assertEqual(payload["email"], "with@example.com")
            self.assertEqual(payload["type"], "codex")
            passwords_txt = zf.read("passwords.txt").decode("utf-8")
            self.assertIn("with@example.com----pw1", passwords_txt)
            self.assertNotIn("skip@example.com", passwords_txt)

    async def test_export_json_writes_zip_payload_for_cli(self):
        import src.accounts as accounts

        rows = [
            {
                "email": "cli@example.com",
                "password": "pw-cli",
                "access_token": _make_jwt({"exp": 1893456000}),
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            target = accounts.Path(tmpdir) / "accounts_export.zip"
            with patch("src.accounts.list_all", new=AsyncMock(return_value=rows)):
                count = await accounts.export_json(target)

            self.assertEqual(count, 1)
            with zipfile.ZipFile(target) as zf:
                self.assertIn("accounts/cli@example.com.json", zf.namelist())
                self.assertIn("passwords.txt", zf.namelist())


class PostRegisterTests(unittest.IsolatedAsyncioTestCase):
    async def test_persist_account_and_maybe_upload_keeps_success_when_upload_fails(self):
        from src.post_register import persist_account_and_maybe_upload

        events: list[str] = []

        async def _fake_upsert(_account: dict):
            events.append("upsert")

        async def _fake_upload(*_args, **_kwargs):
            events.append("upload")
            return False, "mock failed"

        account = {
            "email": "persist@example.com",
            "status": "注册完成",
            "access_token": _make_jwt({"exp": 1893456000}),
        }
        cfg = {"cli_proxy": {"enabled": True, "cpa_url": "http://127.0.0.1:8317/management.html#/", "api_key": "k"}}
        with (
            patch("src.post_register.accounts.upsert", side_effect=_fake_upsert),
            patch("src.post_register.upload_account_to_cli_proxy", side_effect=_fake_upload),
        ):
            result = await persist_account_and_maybe_upload(account, cfg)

        self.assertEqual(events, ["upsert", "upload"])
        self.assertEqual(result["status"], "注册完成")
        self.assertFalse(result["_cli_proxy_upload"]["ok"])
        self.assertTrue(result["_cli_proxy_upload"]["attempted"])

    async def test_persist_account_and_maybe_upload_skips_when_missing_token(self):
        from src.post_register import persist_account_and_maybe_upload

        account = {"email": "skip@example.com", "status": "注册完成"}
        cfg = {"cli_proxy": {"enabled": True}}
        with (
            patch("src.post_register.accounts.upsert", new=AsyncMock()) as upsert_mock,
            patch("src.post_register.upload_account_to_cli_proxy", new=AsyncMock()) as upload_mock,
        ):
            result = await persist_account_and_maybe_upload(account, cfg)

        upsert_mock.assert_awaited_once()
        upload_mock.assert_not_awaited()
        self.assertFalse(result["_cli_proxy_upload"]["attempted"])
        self.assertIn("access_token", result["_cli_proxy_upload"]["message"])


class CliProxyApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_cli_proxy_upload_single_success(self):
        web_server = _import_web_server()

        request = _FakeRequest({"email": "single@example.com"})
        cfg = {"cli_proxy": {"cpa_url": "https://cpa.opentan.xyz/management.html#/", "api_key": "k"}}
        account = {"email": "single@example.com", "access_token": _make_jwt({"exp": 1893456000})}

        with (
            patch("src.webui.server.settings_db.build_config", new=AsyncMock(return_value=cfg)),
            patch("src.webui.server.accounts_mod.get_by_email", new=AsyncMock(return_value=account)),
            patch("src.webui.server.upload_account_to_cli_proxy", new=AsyncMock(return_value=(True, "上传成功"))),
        ):
            result = await web_server.api_cli_proxy_upload(request)

        self.assertTrue(result["ok"])
        self.assertEqual(result["email"], "single@example.com")

    async def test_api_cli_proxy_upload_batch_partial_success(self):
        web_server = _import_web_server()

        request = _FakeRequest({"emails": ["a@example.com", "missing@example.com", "b@example.com"]})
        cfg = {"cli_proxy": {"cpa_url": "https://cpa.opentan.xyz/management.html#/", "api_key": "k"}}
        accounts_side_effect = [
            {"email": "a@example.com", "access_token": _make_jwt({"exp": 1893456000})},
            None,
            {"email": "b@example.com", "access_token": _make_jwt({"exp": 1893456000})},
        ]
        upload_side_effect = [(True, "ok"), (False, "fail")]

        with (
            patch("src.webui.server.settings_db.build_config", new=AsyncMock(return_value=cfg)),
            patch("src.webui.server.accounts_mod.get_by_email", new=AsyncMock(side_effect=accounts_side_effect)),
            patch("src.webui.server.upload_account_to_cli_proxy", new=AsyncMock(side_effect=upload_side_effect)),
        ):
            result = await web_server.api_cli_proxy_upload_batch(request)

        self.assertEqual(result["total"], 3)
        self.assertEqual(result["success"], 1)
        self.assertEqual(result["failed"], 2)
        self.assertEqual(result["results"][0]["email"], "a@example.com")
        self.assertTrue(result["results"][0]["ok"])
        self.assertEqual(result["results"][1]["email"], "missing@example.com")
        self.assertFalse(result["results"][1]["ok"])
        self.assertIn("未找到", result["results"][1]["message"])

    async def test_api_export_json_returns_cpa_zip(self):
        web_server = _import_web_server()
        rows = [
            {
                "email": "zip@example.com",
                "password": "pw-zip",
                "access_token": _make_jwt({"exp": 1893456000}),
            },
            {
                "email": "skip@example.com",
                "password": "pw-skip",
                "access_token": "",
            },
        ]

        with patch("src.webui.server.accounts_mod.list_all", new=AsyncMock(return_value=rows)):
            response = await web_server.api_export("json")

        self.assertEqual(response.media_type, "application/zip")
        self.assertIn("accounts.zip", response.headers["Content-Disposition"])
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            self.assertIn("accounts/zip@example.com.json", zf.namelist())
            self.assertIn("passwords.txt", zf.namelist())
            self.assertNotIn("accounts/skip@example.com.json", zf.namelist())

    async def test_api_export_token_zip_honors_selected_emails(self):
        web_server = _import_web_server()
        request = _FakeRequest({"emails": ["only@example.com"]})
        rows = [
            {
                "email": "only@example.com",
                "password": "pw-only",
                "access_token": _make_jwt({"exp": 1893456000}),
            },
            {
                "email": "other@example.com",
                "password": "pw-other",
                "access_token": _make_jwt({"exp": 1893456000}),
            },
        ]

        with patch("src.webui.server.accounts_mod.list_all", new=AsyncMock(return_value=rows)):
            response = await web_server.api_export_token_zip(request)

        self.assertEqual(response.media_type, "application/zip")
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            self.assertEqual(
                sorted(zf.namelist()),
                ["accounts/only@example.com.json", "passwords.txt"],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
