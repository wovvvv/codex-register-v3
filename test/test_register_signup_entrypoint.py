"""注册入口点击回退逻辑测试。"""
from __future__ import annotations

import asyncio
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

# 测试环境可不安装 aioimaplib；这里提供最小桩避免导入失败。
if "aioimaplib" not in sys.modules:
    sys.modules["aioimaplib"] = types.SimpleNamespace(IMAP4_SSL=object, IMAP4=object)
if "loguru" not in sys.modules:
    _logger = types.SimpleNamespace(info=lambda *a, **k: None, debug=lambda *a, **k: None, warning=lambda *a, **k: None)
    sys.modules["loguru"] = types.SimpleNamespace(logger=_logger)
if "playwright.async_api" not in sys.modules:
    sys.modules["playwright.async_api"] = types.SimpleNamespace(
        Page=object,
        Locator=object,
        TimeoutError=Exception,
    )
if "aiosqlite" not in sys.modules:
    sys.modules["aiosqlite"] = types.SimpleNamespace(connect=None)

from src.browser.register import _click_signup_entrypoint


class _FakePage:
    def __init__(self, url: str):
        self.url = url


class _FakeLocator:
    def __init__(self):
        self.evaluate_calls: list[str] = []

    async def evaluate(self, script: str):
        self.evaluate_calls.append(script)


class SignupEntrypointTests(unittest.IsolatedAsyncioTestCase):
    async def test_falls_back_to_dom_click_when_mouse_click_does_not_progress(self):
        page = _FakePage("https://chatgpt.com/auth/login")
        locator = _FakeLocator()
        wait_results = [
            None,
            ("input[type='email']", object()),
        ]

        async def _fake_wait_any(*_args, **_kwargs):
            return wait_results.pop(0)

        with (
            patch("src.browser.register.human_move_and_click", new=AsyncMock()) as human_click,
            patch("src.browser.register.jitter_sleep", new=AsyncMock()),
            patch("src.browser.register._assert_not_error", new=AsyncMock()),
            patch("src.browser.register.wait_any_element", side_effect=_fake_wait_any),
        ):
            await _click_signup_entrypoint("task-x", page, locator)

        human_click.assert_awaited_once()
        self.assertEqual(locator.evaluate_calls, ["el => el.click()"])

    async def test_skips_dom_click_when_email_input_already_appears(self):
        page = _FakePage("https://chatgpt.com/auth/login")
        locator = _FakeLocator()

        async def _fake_wait_any(*_args, **_kwargs):
            return ("input[type='email']", object())

        with (
            patch("src.browser.register.human_move_and_click", new=AsyncMock()) as human_click,
            patch("src.browser.register.jitter_sleep", new=AsyncMock()),
            patch("src.browser.register._assert_not_error", new=AsyncMock()),
            patch("src.browser.register.wait_any_element", side_effect=_fake_wait_any),
        ):
            await _click_signup_entrypoint("task-x", page, locator)

        human_click.assert_awaited_once()
        self.assertEqual(locator.evaluate_calls, [])

    async def test_skips_dom_click_when_url_already_changes_after_mouse_click(self):
        page = _FakePage("https://chatgpt.com/auth/login")
        locator = _FakeLocator()

        async def _fake_human_click(*_args, **_kwargs):
            page.url = "https://auth.openai.com/log-in-or-create-account"

        with (
            patch("src.browser.register.human_move_and_click", side_effect=_fake_human_click),
            patch("src.browser.register.jitter_sleep", new=AsyncMock()),
            patch("src.browser.register._assert_not_error", new=AsyncMock()),
            patch("src.browser.register.wait_any_element", new=AsyncMock(return_value=None)),
        ):
            await _click_signup_entrypoint("task-x", page, locator)

        self.assertEqual(locator.evaluate_calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
