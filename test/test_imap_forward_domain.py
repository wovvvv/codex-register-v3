"""IMAP forwarded-domain 行为测试。"""
from __future__ import annotations

import sys
import types
import unittest
from email.message import EmailMessage
from importlib import import_module
from unittest.mock import patch

# 测试环境可不安装 aioimaplib；这里提供最小桩避免导入失败。
if "aioimaplib" not in sys.modules:
    sys.modules["aioimaplib"] = types.SimpleNamespace(IMAP4_SSL=object, IMAP4=object)
if "loguru" not in sys.modules:
    _logger = types.SimpleNamespace(info=lambda *a, **k: None, debug=lambda *a, **k: None, warning=lambda *a, **k: None)
    sys.modules["loguru"] = types.SimpleNamespace(logger=_logger)

from src.mail import get_mail_client
from src.mail.imap import IMAPMailClient
from src.mail.imap import MultiIMAPMailClient
from src.mail.imap import is_provider_based_imap_config


class TestIMAPForwardDomain(unittest.IsolatedAsyncioTestCase):
    async def test_generate_email_inbox_mode_returns_real_inbox(self) -> None:
        client = IMAPMailClient(
            email="sanviewyouzi@gmail.com",
            password="x",
            address_mode="inbox",
            provider_name="imap-gmail",
        )
        got = await client.generate_email(prefix="any")
        self.assertEqual(got, "sanviewyouzi@gmail.com")
        self.assertEqual(client._provider_name, "imap-gmail")

    async def test_generate_email_plus_alias_mode(self) -> None:
        client = IMAPMailClient(
            email="sanviewyouzi@gmail.com",
            password="x",
            address_mode="plus_alias",
        )
        with patch("src.mail.imap._random_alias", return_value="aliasxyz1"):
            got = await client.generate_email()
        self.assertEqual(got, "sanviewyouzi+aliasxyz1@gmail.com")

    async def test_generate_email_random_local_part_mode(self) -> None:
        client = IMAPMailClient(
            email="sanviewyouzi@gmail.com",
            password="x",
            address_mode="random_local_part",
            registration_domain="dfghdfghd.xyz",
        )
        got = await client.generate_email(prefix="random-a")
        self.assertEqual(got, "random-a@dfghdfghd.xyz")

    async def test_generate_email_random_local_part_mode_falls_back_when_prefix_empty(self) -> None:
        client = IMAPMailClient(
            email="sanviewyouzi@gmail.com",
            password="x",
            address_mode="random_local_part",
            registration_domain="dfghdfghd.xyz",
        )
        with patch("src.mail.imap._random_alias", return_value="fallbackxx"):
            got = await client.generate_email(prefix="")
        self.assertEqual(got, "fallbackxx@dfghdfghd.xyz")

    async def test_generate_email_random_local_part_sanitizes_prefix(self) -> None:
        client = IMAPMailClient(
            email="sanviewyouzi@gmail.com",
            password="x",
            address_mode="random_local_part",
            registration_domain="dfghdfghd.xyz",
        )
        got = await client.generate_email(prefix=" R@nd+om/ A? ")
        self.assertEqual(got, "RndomA@dfghdfghd.xyz")

    async def test_address_mode_normalization_accepts_mixed_case(self) -> None:
        client = IMAPMailClient(
            email="sanviewyouzi@gmail.com",
            password="x",
            address_mode=" Inbox ",
        )
        got = await client.generate_email()
        self.assertEqual(got, "sanviewyouzi@gmail.com")

    async def test_random_local_part_without_registration_domain_raises(self) -> None:
        client = IMAPMailClient(
            email="sanviewyouzi@gmail.com",
            password="x",
            address_mode="random_local_part",
        )
        with self.assertRaises(ValueError):
            await client.generate_email(prefix="random-a")

    async def test_legacy_use_alias_true_keeps_plus_alias_behavior(self) -> None:
        client = IMAPMailClient(
            email="sanviewyouzi@gmail.com",
            password="x",
            use_alias=True,
        )
        with patch("src.mail.imap._random_alias", return_value="legacy123"):
            got = await client.generate_email()
        self.assertEqual(got, "sanviewyouzi+legacy123@gmail.com")

    def test_message_matches_filter_checks_to_and_delivered_to(self) -> None:
        client = IMAPMailClient(
            email="sanviewyouzi@gmail.com",
            password="x",
            address_mode="random_local_part",
            registration_domain="dfghdfghd.xyz",
        )
        msg = EmailMessage()
        msg["To"] = "random-a@dfghdfghd.xyz"
        msg["Delivered-To"] = "sanviewyouzi@gmail.com"

        self.assertTrue(client._message_matches_filter(msg, "random-a@dfghdfghd.xyz"))
        self.assertFalse(client._message_matches_filter(msg, "random-b@dfghdfghd.xyz"))

    def test_message_matches_filter_delivered_to_only_match(self) -> None:
        client = IMAPMailClient(
            email="sanviewyouzi@gmail.com",
            password="x",
            address_mode="random_local_part",
            registration_domain="dfghdfghd.xyz",
        )
        msg = EmailMessage()
        msg["Delivered-To"] = "random-a@dfghdfghd.xyz"
        self.assertTrue(client._message_matches_filter(msg, "random-a@dfghdfghd.xyz"))

    def test_message_matches_filter_to_miss_but_delivered_to_hit(self) -> None:
        client = IMAPMailClient(
            email="sanviewyouzi@gmail.com",
            password="x",
            address_mode="random_local_part",
            registration_domain="dfghdfghd.xyz",
        )
        msg = EmailMessage()
        msg["To"] = "random-b@dfghdfghd.xyz"
        msg["Delivered-To"] = "random-a@dfghdfghd.xyz"
        self.assertTrue(client._message_matches_filter(msg, "random-a@dfghdfghd.xyz"))

    def test_get_mail_client_provider_based_imap_0_rotates_within_provider(self) -> None:
        cfg = {
            "mail": {
                "imap": [
                    {
                        "name": "prov-0",
                        "host": "imap.example.com",
                        "port": 993,
                        "ssl": True,
                        "accounts": [
                            {"email": "a0@example.com", "credential": "c0"},
                            {"email": "a1@example.com", "credential": "c1"},
                        ],
                    },
                    {
                        "name": "prov-1",
                        "host": "imap.example.org",
                        "port": 993,
                        "ssl": True,
                        "accounts": [{"email": "b0@example.org", "credential": "d0"}],
                    },
                ]
            }
        }
        client = get_mail_client("imap:0", cfg=cfg)
        self.assertIsInstance(client, MultiIMAPMailClient)
        self.assertEqual(len(client._clients), 2)
        self.assertEqual(client._clients[0]._email, "a0@example.com")
        self.assertEqual(client._clients[1]._email, "a1@example.com")

    def test_provider_based_detector_legacy_dict_is_false(self) -> None:
        self.assertFalse(is_provider_based_imap_config({"email": "legacy@example.com"}))

    def test_get_mail_client_provider_based_imap_0_1_selects_fixed_account(self) -> None:
        cfg = {
            "mail": {
                "imap": [
                    {
                        "name": "prov-0",
                        "host": "imap.example.com",
                        "port": 993,
                        "ssl": True,
                        "accounts": [
                            {"email": "a0@example.com", "credential": "c0"},
                            {"email": "a1@example.com", "credential": "c1"},
                        ],
                    }
                ]
            }
        }
        client = get_mail_client("imap:0:1", cfg=cfg)
        self.assertIsInstance(client, IMAPMailClient)
        self.assertEqual(client._email, "a1@example.com")

    def test_get_mail_client_flat_structure_still_supports_imap_index(self) -> None:
        cfg = {
            "mail": {
                "imap": [
                    {"email": "x0@gmail.com", "password": "p0"},
                    {"email": "x1@gmail.com", "password": "p1"},
                ]
            }
        }
        client = get_mail_client("imap:1", cfg=cfg)
        self.assertIsInstance(client, IMAPMailClient)
        self.assertEqual(client._email, "x1@gmail.com")

    def test_src_mail_lazy_exports_are_resolvable(self) -> None:
        mail_mod = import_module("src.mail")
        cls = getattr(mail_mod, "IMAPMailClient")
        self.assertTrue(isinstance(cls, type))

    def test_message_matches_filter_accepts_display_name_format(self) -> None:
        client = IMAPMailClient(
            email="sanviewyouzi@gmail.com",
            password="x",
            address_mode="random_local_part",
            registration_domain="dfghdfghd.xyz",
        )
        msg = EmailMessage()
        msg["To"] = "Name <random-a@dfghdfghd.xyz>"
        self.assertTrue(client._message_matches_filter(msg, "random-a@dfghdfghd.xyz"))

    def test_message_matches_filter_multiple_to_addresses_exact_match_only(self) -> None:
        client = IMAPMailClient(
            email="sanviewyouzi@gmail.com",
            password="x",
            address_mode="random_local_part",
            registration_domain="dfghdfghd.xyz",
        )
        msg = EmailMessage()
        msg["To"] = "first@a.com, random-a@dfghdfghd.xyz, third@b.com"
        self.assertTrue(client._message_matches_filter(msg, "random-a@dfghdfghd.xyz"))
        self.assertFalse(client._message_matches_filter(msg, "random-a@dfghdfghd.xyz.evil.com"))

    def test_message_matches_filter_does_not_match_evil_suffix_domain(self) -> None:
        client = IMAPMailClient(
            email="sanviewyouzi@gmail.com",
            password="x",
            address_mode="random_local_part",
            registration_domain="dfghdfghd.xyz",
        )
        msg = EmailMessage()
        msg["To"] = "random-a@dfghdfghd.xyz.evil.com"
        self.assertFalse(client._message_matches_filter(msg, "random-a@dfghdfghd.xyz"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
