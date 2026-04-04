import sqlite3
conn = sqlite3.connect('accounts.db')
cols = [r[1] for r in conn.execute('PRAGMA table_info(accounts)').fetchall()]
print('Columns:', cols)
rows = conn.execute('SELECT * FROM accounts LIMIT 3').fetchall()
for r in rows:
    print('Row:', r[:5])  # 前5列
conn.close()

