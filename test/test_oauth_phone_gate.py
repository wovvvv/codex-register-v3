"""OAuth phone-gate detection regression tests."""
from __future__ import annotations

import asyncio
import sys
import types
import unittest

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
if "httpx" not in sys.modules:
    sys.modules["httpx"] = types.SimpleNamespace(AsyncClient=object)
if "aiosqlite" not in sys.modules:
    sys.modules["aiosqlite"] = types.SimpleNamespace(connect=None)

from src.browser.oauth import _oauth_add_phone_required


class _FakePage:
    def __init__(self, *, url: str, text: str):
        self.url = url
        self._text = text

    async def evaluate(self, _script: str):
        return self._text


class OAuthPhoneGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_detects_add_phone_gate_by_url_and_text(self):
        page = _FakePage(
            url="https://auth.openai.com/add-phone",
            text="Phone number required To continue, please add a phone number.",
        )
        self.assertTrue(await _oauth_add_phone_required(page))

    async def test_ignores_non_phone_gate_pages(self):
        page = _FakePage(
            url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
            text="Continue to Codex",
        )
        self.assertFalse(await _oauth_add_phone_required(page))


if __name__ == "__main__":
    unittest.main(verbosity=2)
