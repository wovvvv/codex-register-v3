"""
端到端验证：用实际的 OutlookMailClient 做 token refresh + IMAP 拉取。
用法: uv run python test/diag_e2e.py
"""
import asyncio
import sys
sys.path.insert(0, ".")

async def main():
    import src.settings_db as sdb
    from src.mail.outlook import OutlookMailClient

    accs = await sdb.get_section("mail.outlook")
    if not accs:
        print("No outlook accounts configured"); return

    acc = accs[0]
    print(f"Testing account: {acc['email']}")
    print(f"fetch_method: {acc.get('fetch_method', 'graph')}")
    print(f"account proxy: {acc.get('proxy', '(none)')}")
    print(f"job proxy (simulated): http://127.0.0.1:10810")

    client = OutlookMailClient(
        email         = acc["email"],
        client_id     = acc["client_id"],
        tenant_id     = acc.get("tenant_id", "consumers"),
        refresh_token = acc["refresh_token"],
        fetch_method  = acc.get("fetch_method", "imap"),
        # Simulate: job proxy is set (as it would be with proxy_strategy=static)
        proxy         = acc.get("proxy") or "http://127.0.0.1:10810",
    )

    print("\n--- Step 1: _get_token() ---")
    try:
        token = await client._get_token()
        print(f"  OK token={token[:30]}...")
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"  FAIL [{type(e).__name__}]: {e!r}"); return

    print("\n--- Step 2: poll_code (timeout=20s) ---")
    try:
        code = await client.poll_code(acc["email"], timeout=20)
        print(f"  Result: code={code!r}")
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"  FAIL [{type(e).__name__}]: {e!r}")

asyncio.run(main())

