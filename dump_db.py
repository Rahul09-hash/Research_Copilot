import sqlite3

with open(r"D:\Research_Copilot\db_out.txt", "w", encoding="utf-8") as f:
    conn = sqlite3.connect(r"D:\Research_Copilot\data\copilot.db")
    c = conn.cursor()
    c.execute("SELECT content FROM message ORDER BY id DESC LIMIT 2")
    for row in c.fetchall():
        f.write(row[0] + "\n")
        f.write("=" * 80 + "\n")
    conn.close()
