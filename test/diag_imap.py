"""
诊断脚本：分步测试 Outlook IMAP proxy 连接。
用法: uv run python test/diag_imap.py
"""
import asyncio
import json as _json
import socket
import ssl
import imaplib
import urllib.request as _urlreq
import urllib.parse as _urlparse
from urllib.parse import urlparse

PROXY     = "http://127.0.0.1:10810"
IMAP_HOST = "outlook.live.com"
IMAP_PORT = 993


async def test():
    p          = urlparse(PROXY)
    proxy_host = p.hostname
    proxy_port = p.port

    connect_req = (
        f"CONNECT {IMAP_HOST}:{IMAP_PORT} HTTP/1.1\r\n"
        f"Host: {IMAP_HOST}:{IMAP_PORT}\r\n\r\n"
    )

    def _make_tunnel():
        raw = socket.create_connection((proxy_host, proxy_port), timeout=10)
        raw.sendall(connect_req.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = raw.recv(4096)
            if not chunk:
                break
            resp += chunk
        if b"200" not in resp.split(b"\r\n")[0]:
            raise ConnectionError(f"CONNECT rejected: {resp[:100]}")
        ctx      = ssl.create_default_context()
        ssl_sock = ctx.wrap_socket(raw, server_hostname=IMAP_HOST)
        return ssl_sock

    # Step 1: TCP
    print(f"\n=== Step 1: TCP connect to proxy {proxy_host}:{proxy_port}")
    try:
        s = socket.create_connection((proxy_host, proxy_port), timeout=5)
        s.close()
        print("  OK")
    except Exception as e:
        print(f"  FAIL [{type(e).__name__}]: {e!r}"); return

    # Step 2+3: CONNECT + SSL
    print(f"=== Step 2+3: HTTP CONNECT → SSL")
    try:
        ssl_sock = await asyncio.to_thread(_make_tunnel)
        greeting = ssl_sock.recv(2048)
        print(f"  OK  IMAP greeting: {greeting[:80]}")
        ssl_sock.close()
    except Exception as e:
        print(f"  FAIL [{type(e).__name__}]: {e!r}"); return

    # Step 4: Token refresh via urllib (stdlib — avoids httpx+anyio TLS bug)
    print("=== Step 4: Token refresh via urllib.request")
    try:
        import src.settings_db as sdb
        accs = await sdb.get_section("mail.outlook")
        if not accs:
            print("  No outlook accounts"); return
        acc        = accs[0]
        email_addr = acc["email"]
        client_id  = acc["client_id"]
        tenant_id  = acc.get("tenant_id", "consumers")
        refresh_tk = acc["refresh_token"]

        scope     = "https://outlook.office.com/IMAP.AccessAsUser.All offline_access"
        token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        payload   = _urlparse.urlencode({
            "client_id": client_id, "grant_type": "refresh_token",
            "refresh_token": refresh_tk, "scope": scope,
        }).encode()

        proxy_handler = _urlreq.ProxyHandler({"http": PROXY, "https": PROXY})
        https_handler = _urlreq.HTTPSHandler(context=ssl.create_default_context())
        opener        = _urlreq.build_opener(proxy_handler, https_handler)
        req_obj       = _urlreq.Request(
            token_url, data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        def _do_token():
            with opener.open(req_obj, timeout=25) as r:
                return _json.loads(r.read())

        print(f"  Getting token for {email_addr} ...")
        data         = await asyncio.to_thread(_do_token)
        access_token = data.get("access_token", "")
        print(f"  Token OK  expires_in={data.get('expires_in')}s")

    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"  FAIL [{type(e).__name__}]: {e!r}"); return

    # Step 5: Full IMAP auth
    print("=== Step 5: IMAP XOAUTH2 auth")
    try:
        ssl_sock2 = await asyncio.to_thread(_make_tunnel)
        _the_sock = ssl_sock2

        class _PatchedIMAP4(imaplib.IMAP4):
            def open(self, host, port=None):
                self.sock = _the_sock
                self.file = self.sock.makefile("rb")

        M          = _PatchedIMAP4(IMAP_HOST)
        auth_bytes = f"user={email_addr}\x01auth=Bearer {access_token}\x01\x01".encode()
        typ, _     = M.authenticate("XOAUTH2", lambda _: auth_bytes)
        print(f"  Auth: {typ}")
        if typ == "OK":
            _, msgs = M.search(None, "ALL")
            count   = len(msgs[0].split()) if msgs and msgs[0] else 0
            print(f"  INBOX ALL: {count} messages")
        M.logout()
        print("  Done!")
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"  FAIL [{type(e).__name__}]: {e!r}")


asyncio.run(test())
