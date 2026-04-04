import sqlite3, json
conn = sqlite3.connect('accounts.db')
row = conn.execute(
    "SELECT email, password, extra FROM accounts WHERE email='g675gzkn5s0f@bhauesh.shop'"
).fetchone()
if row:
    extra = json.loads(row[2]) if row[2] else {}
    print('EMAIL:', row[0])
    print('PASS:', row[1])
    print('EXTRA keys:', list(extra.keys()) if extra else 'empty')
conn.close()

