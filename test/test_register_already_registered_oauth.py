"""Regression tests for OAuth acquisition on already-registered emails."""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

if "loguru" not in sys.modules:
    _logger = types.SimpleNamespace(
        info=lambda *a, **k: None,
        debug=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        success=lambda *a, **k: None,
        error=lambda *a, **k: None,
    )
    sys.modules["loguru"] = types.SimpleNamespace(logger=_logger)

if "playwright.async_api" not in sys.modules:
    sys.modules["playwright.async_api"] = types.SimpleNamespace(
        Page=object,
        Locator=object,
        TimeoutError=Exception,
    )

if "src.browser.engine" not in sys.modules:
    sys.modules["src.browser.engine"] = types.SimpleNamespace(create_page=None)

if "src.browser.helpers" not in sys.modules:
    async def _noop_async(*_args, **_kwargs):
        return None

    sys.modules["src.browser.helpers"] = types.SimpleNamespace(
        click_submit_or_text=_noop_async,
        dismiss_google_one_tap=_noop_async,
        find_signup_button=_noop_async,
        human_move_and_click=_noop_async,
        is_error_page=_noop_async,
        is_visible=_noop_async,
        jitter_sleep=_noop_async,
        set_react_input=_noop_async,
        set_spinbutton=_noop_async,
        wait_any_element=_noop_async,
    )

from src.browser.register import EmailAlreadyRegisteredError, register_one
from src.mail.base import MailClient


class _FakeMailClient(MailClient):
    def __init__(self, email: str):
        self._email = email

    async def generate_email(self, prefix=None, domain=None):
        return self._email

    async def poll_code(self, email: str, timeout: int = 120):
        return None


class _FakePage:
    url = "https://auth.openai.com/log-in/password"


class _FakePageContext:
    def __init__(self, page: _FakePage):
        self._page = page

    async def __aenter__(self):
        return self._page

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeToken:
    account_id = "acc-123"
    expires_at = "2099-01-01T00:00:00Z"

    def to_dict(self):
        return {
            "access_token": "access-123",
            "refresh_token": "refresh-123",
            "account_id": self.account_id,
        }


class RegisterAlreadyRegisteredOAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_already_registered_email_still_attempts_oauth_and_returns_tokens(self):
        page = _FakePage()
        mail_client = _FakeMailClient("known@example.com")
        fake_oauth = types.SimpleNamespace(
            acquire_tokens_via_browser=AsyncMock(return_value=_FakeToken())
        )
        fake_accounts = types.SimpleNamespace(
            get_by_email=AsyncMock(return_value={"email": "known@example.com", "password": "stored-pass"})
        )

        with (
            patch("src.browser.register.create_page", return_value=_FakePageContext(page)),
            patch("src.browser.register._state_machine", side_effect=EmailAlreadyRegisteredError("exists")),
            patch.dict(sys.modules, {"src.browser.oauth": fake_oauth, "src.accounts": fake_accounts}, clear=False),
        ):
            result = await register_one(
                task_id="task-x",
                cfg={"enable_oauth": True, "engine": "playwright", "headless": True},
                mail_client=mail_client,
            )

        fake_oauth.acquire_tokens_via_browser.assert_awaited_once()
        self.assertEqual(
            fake_oauth.acquire_tokens_via_browser.await_args.kwargs["password"],
            "stored-pass",
        )
        self.assertEqual(result["status"], "注册完成")
        self.assertEqual(result["password"], "stored-pass")
        self.assertEqual(result["access_token"], "access-123")
        self.assertEqual(result["refresh_token"], "refresh-123")
        self.assertEqual(result["account_id"], "acc-123")


if __name__ == "__main__":
    unittest.main(verbosity=2)
