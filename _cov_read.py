import sqlite3

conn = sqlite3.connect('.coverage')
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
print("TABLES:", cur.fetchall())
conn.close()