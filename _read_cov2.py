import sqlite3
conn = sqlite3.connect("/Users/johnny/projects/integration-test/.coverage")
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
print("TABLES:", cur.fetchall())
cur.execute("SELECT id, path FROM file")
for row in cur.fetchall():
    print("FILE:", row)
cur.execute("SELECT * FROM line_bits LIMIT 5")
for row in cur.fetchall():
    print("LINE_BITS:", row)
conn.close()
