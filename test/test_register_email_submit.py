"""邮箱提交回退逻辑测试。"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

if "aioimaplib" not in sys.modules:
    sys.modules["aioimaplib"] = types.SimpleNamespace(IMAP4_SSL=object, IMAP4=object)
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
if "aiosqlite" not in sys.modules:
    sys.modules["aiosqlite"] = types.SimpleNamespace(connect=None)

from src.browser.register import _submit_email_and_advance


class _FakePage:
    def __init__(self, url: str):
        self.url = url
        self.eval_calls: list[str] = []

    async def evaluate(self, script: str):
        self.eval_calls.append(script)


class _FakeEmailLocator:
    def __init__(self):
        self.press_calls: list[str] = []

    async def press(self, key: str):
        self.press_calls.append(key)


class _FakeSubmitLocator:
    pass


class RegisterEmailSubmitTests(unittest.IsolatedAsyncioTestCase):
    async def test_falls_back_to_dom_submit_when_primary_submit_does_not_progress(self):
        page = _FakePage("https://auth.openai.com/log-in-or-create-account")
        email_el = _FakeEmailLocator()
        submit_loc = _FakeSubmitLocator()

        with (
            patch("src.browser.register.human_move_and_click", new=AsyncMock()) as human_click,
            patch("src.browser.register.jitter_sleep", new=AsyncMock()),
            patch("src.browser.register.dismiss_google_one_tap", new=AsyncMock()),
            patch("src.browser.register._assert_not_error", new=AsyncMock()),
            patch("src.browser.register._email_submit_progressed", side_effect=[False, True]),
        ):
            await _submit_email_and_advance("task-x", page, email_el, submit_loc)

        human_click.assert_awaited_once_with(page, submit_loc)
        self.assertEqual(len(page.eval_calls), 1)
        self.assertEqual(email_el.press_calls, ["Enter"])

    async def test_skips_dom_submit_when_primary_submit_already_progressed(self):
        page = _FakePage("https://auth.openai.com/log-in-or-create-account")
        email_el = _FakeEmailLocator()
        submit_loc = _FakeSubmitLocator()

        with (
            patch("src.browser.register.human_move_and_click", new=AsyncMock()) as human_click,
            patch("src.browser.register.jitter_sleep", new=AsyncMock()),
            patch("src.browser.register._email_submit_progressed", return_value=True),
        ):
            await _submit_email_and_advance("task-x", page, email_el, submit_loc)

        human_click.assert_awaited_once_with(page, submit_loc)
        self.assertEqual(page.eval_calls, [])
        self.assertEqual(email_el.press_calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
