"""OAuth 登录密码页推进回退逻辑测试。"""
from __future__ import annotations

import asyncio
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

if "loguru" not in sys.modules:
    _logger = types.SimpleNamespace(info=lambda *a, **k: None, debug=lambda *a, **k: None, warning=lambda *a, **k: None)
    sys.modules["loguru"] = types.SimpleNamespace(logger=_logger)
if "playwright.async_api" not in sys.modules:
    sys.modules["playwright.async_api"] = types.SimpleNamespace(
        Page=object,
        Locator=object,
        TimeoutError=Exception,
    )
if "httpx" not in sys.modules:
    sys.modules["httpx"] = types.SimpleNamespace(AsyncClient=object)
if "aiosqlite" not in sys.modules:
    sys.modules["aiosqlite"] = types.SimpleNamespace(connect=None)

from src.browser.oauth import _submit_password_and_advance, _switch_to_passwordless_otp


class _FakePage:
    def __init__(self, url: str):
        self.url = url
        self.eval_calls: list[str] = []
        self.passwordless_visible = False

    async def evaluate(self, script: str):
        self.eval_calls.append(script)

    def get_by_text(self, text: str, exact: bool = True):
        return _FakeTextLocator(self, text, exact)


class _FakeTextLocator:
    def __init__(self, page: _FakePage, text: str, exact: bool):
        self.page = page
        self.text = text
        self.exact = exact
        self.first = self

    async def is_visible(self):
        return self.page.passwordless_visible and self.text == "Log in with a one-time code" and self.exact

    async def click(self):
        if await self.is_visible():
            self.page.url = "https://auth.openai.com/email-verification"


class OAuthPasswordGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_falls_back_to_dom_click_when_password_submit_does_not_progress(self):
        page = _FakePage("https://auth.openai.com/log-in/password")

        async def _fake_click_submit_or_text(*_args, **_kwargs):
            return True

        with (
            patch("src.browser.oauth.click_submit_or_text", side_effect=_fake_click_submit_or_text) as submit_click,
            patch("src.browser.oauth.asyncio.sleep", new=AsyncMock()),
        ):
            await _submit_password_and_advance(page)

        submit_click.assert_awaited_once()
        self.assertEqual(page.eval_calls, ["document.querySelector(\"button[type='submit']\")?.click()"])

    async def test_skips_dom_click_when_password_submit_changes_url(self):
        page = _FakePage("https://auth.openai.com/log-in/password")

        async def _fake_click_submit_or_text(*_args, **_kwargs):
            page.url = "https://auth.openai.com/add-phone"
            return True

        with (
            patch("src.browser.oauth.click_submit_or_text", side_effect=_fake_click_submit_or_text) as submit_click,
            patch("src.browser.oauth.asyncio.sleep", new=AsyncMock()),
        ):
            await _submit_password_and_advance(page)

        submit_click.assert_awaited_once()
        self.assertEqual(page.eval_calls, [])

    async def test_switches_to_passwordless_otp_when_link_visible(self):
        page = _FakePage("https://auth.openai.com/log-in/password")
        page.passwordless_visible = True

        switched = await _switch_to_passwordless_otp(page)

        self.assertTrue(switched)
        self.assertEqual(page.url, "https://auth.openai.com/email-verification")

    async def test_passwordless_switch_is_noop_when_link_hidden(self):
        page = _FakePage("https://auth.openai.com/log-in/password")

        switched = await _switch_to_passwordless_otp(page)

        self.assertFalse(switched)
        self.assertEqual(page.url, "https://auth.openai.com/log-in/password")


if __name__ == "__main__":
    unittest.main(verbosity=2)
