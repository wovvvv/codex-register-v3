"""Sub2API 上传链路测试。"""
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
        fake_register = types.ModuleType("src.browser.register")

        async def _fake_register_one(*_args, **_kwargs):
            return {}

        fake_register.register_one = _fake_register_one
        sys.modules["src.browser.register"] = fake_register


_install_test_stubs()


class Sub2APIUploadConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_config_contains_upload_provider_and_sub2api_defaults(self):
        import src.settings_db as settings_db

        fake_db = copy.deepcopy(settings_db._DEFAULTS)
        with patch("src.settings_db.get_all", new=AsyncMock(return_value=fake_db)):
            cfg = await settings_db.build_config()

        self.assertEqual(cfg["upload_provider"], "none")
        self.assertIn("sub2api_upload", cfg)
        self.assertEqual(cfg["sub2api_upload"]["base_url"], "")
        self.assertEqual(cfg["sub2api_upload"]["api_key"], "")
        self.assertEqual(cfg["sub2api_upload"]["import_models"], False)
        self.assertEqual(cfg["sub2api_upload"]["model_whitelist"], [])
        self.assertEqual(cfg["sub2api_upload"]["group_ids"], [])


class Sub2APIUploadDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_post_register_routes_to_selected_upload_provider(self):
        post_register = importlib.import_module("src.post_register")

        account = {
            "email": "worker@example.com",
            "access_token": "at-123",
            "refresh_token": "rt-123",
            "account_id": "acct-123",
        }
        cfg = {
            "upload_provider": "sub2api",
            "sub2api_upload": {
                "base_url": "http://sub2api:8080",
                "api_key": "worker-secret",
                "group_ids": [9, 10],
            },
        }

        with (
            patch("src.post_register.accounts.upsert", new=AsyncMock(return_value=None)) as upsert_mock,
            patch("src.post_register.upload_account_to_cli_proxy", new=AsyncMock(return_value=(True, "cpa ok"))) as cpa_mock,
            patch("src.post_register.upload_account_to_sub2api", new=AsyncMock(return_value=(True, "sub2api ok"))) as sub2api_mock,
        ):
            result = await post_register.persist_account_and_maybe_upload(account, cfg)

        upsert_mock.assert_awaited_once()
        cpa_mock.assert_not_awaited()
        sub2api_mock.assert_awaited_once()
        self.assertTrue(result["_upload"]["attempted"])
        self.assertTrue(result["_upload"]["ok"])
        self.assertEqual(result["_upload"]["provider"], "sub2api")


class _FakeRequest:
    def __init__(self, body: dict):
        self._body = body

    async def json(self):
        return self._body


class _FakeTask:
    def done(self):
        return False


class Sub2APIJobOverrideTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_start_job_keeps_upload_provider_but_ignores_sub2api_overrides(self):
        web_server = importlib.import_module("src.webui.server")
        web_server._jobs.clear()

        async def _dummy_coro():
            return None

        def _fake_create_task(coro):
            try:
                coro.close()
            except Exception:
                pass
            return _FakeTask()

        with (
            patch("src.webui.server.settings_db.build_config", new=AsyncMock(return_value={
                "mail_provider": "gptmail",
                "engine": "camoufox",
                "proxy_strategy": "none",
                "upload_provider": "cpa",
                "sub2api_upload": {
                    "group_id": 9,
                    "priority": 2,
                    "model_whitelist": ["gpt-5.1-codex"],
                },
            })),
            patch("src.webui.server.asyncio.create_task", new=_fake_create_task),
        ):
            resp = await web_server.api_start_job(_FakeRequest({
                "count": 1,
                "provider": "imap:0",
                "engine": "camoufox",
                "upload_provider": "sub2api",
                "sub2api_upload": {
                    "group_ids": [10, 11],
                    "priority": 3,
                    "import_models": True,
                    "model_whitelist": ["gpt-5.4"],
                },
            }))

        job = web_server._jobs[resp["job_id"]]
        self.assertEqual(job.upload_provider, "sub2api")
        self.assertFalse(hasattr(job, "sub2api_upload"))
        self.assertNotIn("sub2api_upload", job.to_dict(full=True))

    async def test_run_job_uses_global_sub2api_config_without_task_override_merge(self):
        web_server = importlib.import_module("src.webui.server")

        job = web_server._Job(
            "job12345",
            1,
            "gptmail",
            "camoufox",
            "none",
            upload_provider="sub2api",
        )
        job.sub2api_upload = {
            "group_ids": [99],
            "priority": 9,
            "model_whitelist": ["gpt-5.4"],
        }

        captured_cfg: dict = {}
        fake_mail_client = object()

        async def _fake_register_one(**_kwargs):
            return {
                "email": "worker@example.com",
                "status": "注册完成",
            }

        async def _fake_persist(result, cfg, log_fn=None):
            captured_cfg.clear()
            captured_cfg.update(copy.deepcopy(cfg))
            if log_fn is not None:
                log_fn("upload ok")
            return result

        with (
            patch("src.webui.server.settings_db.build_config", new=AsyncMock(return_value={
                "engine": "camoufox",
                "proxy_strategy": "none",
                "upload_provider": "sub2api",
                "sub2api_upload": {
                    "group_ids": [9, 10],
                    "priority": 2,
                    "model_whitelist": ["gpt-5.1-codex"],
                },
                "mail": {"gptmail": {}},
            })),
            patch("src.webui.server.get_mail_client", return_value=fake_mail_client),
            patch("src.webui.server.register_one", new=AsyncMock(side_effect=_fake_register_one)),
            patch("src.webui.server.persist_account_and_maybe_upload", new=AsyncMock(side_effect=_fake_persist)),
        ):
            await web_server._run_job(job)

        self.assertEqual(captured_cfg["sub2api_upload"]["group_ids"], [9, 10])
        self.assertEqual(captured_cfg["sub2api_upload"]["priority"], 2)
        self.assertEqual(captured_cfg["sub2api_upload"]["model_whitelist"], ["gpt-5.1-codex"])

    async def test_run_job_logs_current_mail_fetch_method_for_outlook_account(self):
        web_server = importlib.import_module("src.webui.server")

        async def _fake_register_one(**_kwargs):
            return {
                "email": "worker@example.com",
                "status": "注册完成",
            }

        async def _fake_persist(result, _cfg, log_fn=None):
            if log_fn is not None:
                log_fn("upload ok")
            return result

        class _FakeOutlookMailClient:
            def __init__(self, **kwargs):
                self._email = kwargs.get("email", "")
                self._fetch_method = kwargs.get("fetch_method", "graph")

        for fetch_method in ("graph", "imap"):
            job = web_server._Job(
                f"job-{fetch_method}",
                1,
                "outlook:0",
                "camoufox",
                "none",
            )
            with self.subTest(fetch_method=fetch_method):
                with (
                    patch("src.webui.server.settings_db.build_config", new=AsyncMock(return_value={
                        "engine": "camoufox",
                        "proxy_strategy": "none",
                        "upload_provider": "none",
                        "mail": {
                            "imap": [],
                            "outlook": [{
                                "email": "route@example.com",
                                "client_id": "cid-123",
                                "tenant_id": "consumers",
                                "refresh_token": "rt-123",
                                "access_token": "at-123",
                                "fetch_method": fetch_method,
                            }],
                        },
                    })),
                    patch("src.webui.server.OutlookMailClient", new=_FakeOutlookMailClient),
                    patch("src.webui.server.register_one", new=AsyncMock(side_effect=_fake_register_one)),
                    patch("src.webui.server.persist_account_and_maybe_upload", new=AsyncMock(side_effect=_fake_persist)),
                ):
                    await web_server._run_job(job)

                self.assertTrue(
                    any(f"邮箱 route@example.com 使用 {fetch_method} 获取验证码" in log for log in job.logs),
                    msg=f"未在日志中看到 fetch_method={fetch_method}: {job.logs}",
                )


class Sub2APIManualUploadApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_sub2api_upload_api_uses_account_and_runtime_config(self):
        web_server = importlib.import_module("src.webui.server")

        with (
            patch("src.webui.server.settings_db.build_config", new=AsyncMock(return_value={
                "sub2api_upload": {"base_url": "http://sub2api:8080", "api_key": "worker-secret", "group_ids": [9, 10]},
            })),
            patch("src.webui.server.accounts_mod.get_by_email", new=AsyncMock(return_value={
                "email": "worker@example.com",
                "refresh_token": "rt-123",
            })),
            patch("src.webui.server.upload_account_to_sub2api", new=AsyncMock(return_value=(True, "sub2api ok"))) as upload_mock,
        ):
            resp = await web_server.api_sub2api_upload(_FakeRequest({"email": "worker@example.com"}))

        upload_mock.assert_awaited_once()
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["email"], "worker@example.com")


if __name__ == "__main__":
    unittest.main(verbosity=2)
