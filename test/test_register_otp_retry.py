"""Minimal offline checks for OTP retry helpers in src.browser.register.

Run:
    uv run python test/test_register_otp_retry.py
"""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

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
    sys.modules["playwright.async_api"] = types.SimpleNamespace(Page=object)

if "src.browser.engine" not in sys.modules:
    async def _unused_create_page(*_args, **_kwargs):
        raise RuntimeError("create_page should not be used in this test")

    sys.modules["src.browser.engine"] = types.SimpleNamespace(create_page=_unused_create_page)

if "src.browser.helpers" not in sys.modules:
    async def _noop_async(*_args, **_kwargs):
        return None

    async def _fake_is_visible(page, selector):
        return await page.locator(selector).is_visible()

    sys.modules["src.browser.helpers"] = types.SimpleNamespace(
        click_submit_or_text=_noop_async,
        dismiss_google_one_tap=_noop_async,
        find_signup_button=_noop_async,
        human_move_and_click=_noop_async,
        is_error_page=_noop_async,
        is_visible=_fake_is_visible,
        jitter_sleep=_noop_async,
        set_react_input=_noop_async,
        set_spinbutton=_noop_async,
        wait_any_element=_noop_async,
    )

from src.browser.register import (
    _classify_otp_submit_result,
    _poll_fresh_code,
    _wait_for_password_or_otp,
)
from src.mail.base import MailClient


class _FakeLocator:
    def __init__(self, *, visible: bool = False, count: int = 0):
        self._visible = visible
        self._count = count
        self.first = self

    async def is_visible(self):
        return self._visible

    async def count(self):
        return self._count


class _FakePage:
    def __init__(self, *, url: str, text: str = "", otp_boxes: int = 0, visible_selectors: set[str] | None = None):
        self.url = url
        self._text = text
        self._otp_boxes = otp_boxes
        self._visible_selectors = visible_selectors or set()

    async def evaluate(self, script: str):
        return self._text.lower()

    def locator(self, selector: str):
        if "maxlength='1'" in selector or 'maxlength="1"' in selector:
            return _FakeLocator(count=self._otp_boxes, visible=self._otp_boxes > 0)
        return _FakeLocator(visible=selector in self._visible_selectors)


class _FakeMailClient(MailClient):
    def __init__(self, codes: list[str | None], *, supports_fresh_tracking: bool = False):
        self._codes = list(codes)
        self._supports_fresh_tracking = supports_fresh_tracking

    async def generate_email(self, prefix=None, domain=None):
        return "x@example.com"

    async def poll_code(self, email: str, timeout: int = 120):
        await asyncio.sleep(0)
        if self._codes:
            return self._codes.pop(0)
        return None

    def supports_fresh_message_tracking(self) -> bool:
        return self._supports_fresh_tracking


async def _test_incorrect():
    page = _FakePage(
        url="https://auth.openai.com/u/signup/email-verification",
        text="Incorrect code. Please try again.",
        otp_boxes=6,
    )
    result = await _classify_otp_submit_result("task-x", page, timeout_ms=50)
    assert result == "incorrect", result


async def _test_accepted_by_profile_url():
    page = _FakePage(
        url="https://auth.openai.com/u/signup/about-you",
        text="",
        otp_boxes=0,
    )
    result = await _classify_otp_submit_result("task-x", page, timeout_ms=50)
    assert result == "accepted", result


async def _test_poll_fresh_code():
    mail = _FakeMailClient(["111111", "111111", "222222"])
    code = await _poll_fresh_code(
        "task-x",
        mail,
        "x@example.com",
        previous_code="111111",
        seen_codes=None,
        timeout=5,
    )
    assert code == "222222", code


async def _test_poll_fresh_code_skips_any_seen_codes():
    mail = _FakeMailClient(["111111", "222222", "111111", "333333"])
    code = await _poll_fresh_code(
        "task-x",
        mail,
        "x@example.com",
        previous_code="222222",
        seen_codes={"111111", "222222"},
        timeout=5,
    )
    assert code == "333333", code


async def _test_poll_fresh_code_accepts_same_code_for_fresh_tracking_clients():
    mail = _FakeMailClient(
        ["222222"],
        supports_fresh_tracking=True,
    )
    code = await _poll_fresh_code(
        "task-x",
        mail,
        "x@example.com",
        previous_code="222222",
        seen_codes={"222222"},
        timeout=5,
    )
    assert code == "222222", code


async def _test_wait_for_password_or_otp_treats_login_email_verification_as_existing_account():
    page = _FakePage(
        url="https://auth.openai.com/email-verification",
        text="",
        otp_boxes=6,
    )
    result = await _wait_for_password_or_otp(page, timeout_ms=50)
    assert result == "already_registered", result


async def _main():
    await _test_incorrect()
    await _test_accepted_by_profile_url()
    await _test_poll_fresh_code()
    await _test_poll_fresh_code_skips_any_seen_codes()
    await _test_poll_fresh_code_accepts_same_code_for_fresh_tracking_clients()
    await _test_wait_for_password_or_otp_treats_login_email_verification_as_existing_account()
    print("OTP retry helper tests passed")


if __name__ == "__main__":
    asyncio.run(_main())
