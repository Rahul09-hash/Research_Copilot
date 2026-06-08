import sqlite3

conn = sqlite3.connect(r"D:\Research_Copilot\data\copilot.db")
c = conn.cursor()
c.execute("SELECT content FROM message ORDER BY id DESC LIMIT 2")
for row in c.fetchall():
    print(row[0])
    print("=" * 80)
conn.close()
