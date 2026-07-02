import sqlite3

conn = sqlite3.connect("/Users/johnny/projects/integration-test/.coverage")
cur = conn.cursor()

# Print table names
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cur.fetchall()
print("TABLES:", tables)

# Try to get file list
if any(t[0] == 'file' for t in tables):
    cur.execute("SELECT id, path FROM file")
    for row in cur.fetchall():
        print("FILE:", row)

# Try to get line info
if any(t[0] == 'line_bits' for t in tables):
    cur.execute("SELECT * FROM line_bits LIMIT 5")
    for row in cur.fetchall():
        print("LINE_BITS:", row)

conn.close()