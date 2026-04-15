"""Outlook Graph token refresh regression tests."""
from __future__ import annotations

import asyncio
import json
import io
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


if "loguru" not in sys.modules:
    fake_loguru = types.ModuleType("loguru")

    class _FakeLogger:
        def __getattr__(self, _name):
            return lambda *_args, **_kwargs: None

    fake_loguru.logger = _FakeLogger()
    sys.modules["loguru"] = fake_loguru

if "httpx" not in sys.modules:
    fake_httpx = types.ModuleType("httpx")

    class _FakeAsyncClient:
        def __init__(self, *_args, **_kwargs):
            pass

    fake_httpx.AsyncClient = _FakeAsyncClient
    sys.modules["httpx"] = fake_httpx

from src.mail.outlook import (
    OutlookMailClient,
    _is_message_recent_enough,
    _parse_received_timestamp,
)


class _FakeSuccessResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeSuccessOpener:
    def __init__(self, payload: dict):
        self._payload = payload

    def open(self, req, timeout=25):  # noqa: ARG002
        return _FakeSuccessResponse(self._payload)


class _FakeFailingOpener:
    def open(self, req, timeout=25):  # noqa: ARG002
        raise OSError("direct token fetch boom")


class _FakeHTTPErrorOpener:
    def open(self, req, timeout=25):  # noqa: ARG002
        import urllib.error

        body = json.dumps({
            "error": "invalid_grant",
            "error_description": "AADSTS70000 scope unauthorized",
        }).encode("utf-8")
        raise urllib.error.HTTPError(
            url="https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=io.BytesIO(body),
        )


class OutlookGraphRefreshTests(unittest.TestCase):
    def test_session_time_filter_uses_received_timestamp_with_small_grace_window(self):
        session_started_at = _parse_received_timestamp("2026-03-01T11:53:20Z")
        self.assertIsNotNone(session_started_at)

        too_old = _parse_received_timestamp("2026-03-01T11:53:14Z")
        within_grace = _parse_received_timestamp("2026-03-01T11:53:17Z")
        after_session = _parse_received_timestamp("Sat, 01 Mar 2026 11:53:21 +0000")

        self.assertEqual(too_old, session_started_at - 6.0)
        self.assertEqual(within_grace, session_started_at - 3.0)
        self.assertEqual(after_session, session_started_at + 1.0)

        self.assertFalse(_is_message_recent_enough(too_old, session_started_at))
        self.assertTrue(_is_message_recent_enough(within_grace, session_started_at))
        self.assertTrue(_is_message_recent_enough(after_session, session_started_at))

    def test_generate_email_marks_new_mailbox_session_and_clears_seen_state(self):
        client = OutlookMailClient(
            email="user@hotmail.com",
            client_id="cid-123",
            refresh_token="rt-123",
            fetch_method="imap",
        )
        client._seen_imap_uids = {"INBOX/1"}
        client._seen_graph_ids = {"msg-1"}

        async def _run():
            return await client.generate_email()

        email = asyncio.run(_run())

        self.assertEqual(email, "user@hotmail.com")
        self.assertEqual(client._seen_imap_uids, set())
        self.assertEqual(client._seen_graph_ids, set())
        self.assertGreater(getattr(client, "_mailbox_session_started_at", 0.0), 0.0)

    def test_refresh_token_sync_returns_access_token_on_direct_success(self):
        client = OutlookMailClient(
            email="user@hotmail.com",
            client_id="cid-123",
            refresh_token="rt-123",
            fetch_method="graph",
        )

        with patch("urllib.request.build_opener", return_value=_FakeSuccessOpener({
            "access_token": "at-123",
            "expires_in": 3600,
        })):
            data = client._refresh_token_sync()

        self.assertEqual(data["access_token"], "at-123")

    def test_refresh_token_sync_surfaces_direct_error_when_no_proxy(self):
        client = OutlookMailClient(
            email="user@hotmail.com",
            client_id="cid-123",
            refresh_token="rt-123",
            fetch_method="graph",
        )

        with patch("urllib.request.build_opener", return_value=_FakeFailingOpener()):
            with self.assertRaises(RuntimeError) as cm:
                client._refresh_token_sync()

        self.assertIn("direct token fetch boom", str(cm.exception))
        self.assertNotIn("UnboundLocalError", str(cm.exception))

    def test_refresh_token_sync_includes_http_error_body_when_token_endpoint_rejects_scope(self):
        client = OutlookMailClient(
            email="user@hotmail.com",
            client_id="cid-123",
            refresh_token="rt-123",
            fetch_method="graph",
        )

        with patch("urllib.request.build_opener", return_value=_FakeHTTPErrorOpener()):
            with self.assertRaises(RuntimeError) as cm:
                client._refresh_token_sync()

        self.assertIn("invalid_grant", str(cm.exception))
        self.assertIn("AADSTS70000", str(cm.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
