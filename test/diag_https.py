"""Test HTTPS connectivity to login.microsoftonline.com via various methods."""
import socket, ssl, http.client, urllib.request, urllib.parse

PROXY = "http://127.0.0.1:10810"
HOST  = "login.microsoftonline.com"

# ── Test 1: Direct (no proxy) ─────────────────────────────────────────────
print("=== Test 1: Direct HTTPS (no proxy)")
try:
    ctx  = ssl.create_default_context()
    conn = http.client.HTTPSConnection(HOST, timeout=10, context=ctx)
    conn.request("HEAD", "/")
    r = conn.getresponse()
    print(f"  OK  HTTP {r.status}")
    conn.close()
except Exception as e:
    print(f"  FAIL [{type(e).__name__}]: {e!r}")

# ── Test 2: urllib + proxy, TLS 1.2 only ─────────────────────────────────
print("=== Test 2: urllib via proxy, TLS 1.2")
try:
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"https": PROXY}),
        urllib.request.HTTPSHandler(context=ctx),
    )
    with opener.open(f"https://{HOST}/", timeout=10) as r:
        print(f"  OK  HTTP {r.status}")
except Exception as e:
    print(f"  FAIL [{type(e).__name__}]: {e!r}")

# ── Test 3: Manual CONNECT to port 443 ───────────────────────────────────
print("=== Test 3: Manual CONNECT to port 443 → SSL → HTTP/1.1 HEAD")
try:
    from urllib.parse import urlparse
    p = urlparse(PROXY)
    raw = socket.create_connection((p.hostname, p.port), timeout=8)
    req = f"CONNECT {HOST}:443 HTTP/1.1\r\nHost: {HOST}:443\r\n\r\n"
    raw.sendall(req.encode())
    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = raw.recv(4096)
        if not chunk:
            break
        resp += chunk
    status_line = resp.split(b"\r\n")[0]
    print(f"  CONNECT response: {status_line}")
    if b"200" in status_line:
        ctx2     = ssl.create_default_context()
        ssl_sock = ctx2.wrap_socket(raw, server_hostname=HOST)
        print(f"  SSL OK  cipher={ssl_sock.cipher()[0]}")
        ssl_sock.sendall(
            f"HEAD / HTTP/1.1\r\nHost: {HOST}\r\nConnection: close\r\n\r\n".encode()
        )
        head = ssl_sock.recv(512)
        print(f"  HTTP: {head[:80]}")
    else:
        print(f"  CONNECT rejected")
except Exception as e:
    import traceback; traceback.print_exc()
    print(f"  FAIL [{type(e).__name__}]: {e!r}")

