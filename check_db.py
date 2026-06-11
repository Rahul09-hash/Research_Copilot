import sqlite3
import json
from pathlib import Path

config_dir = Path.home() / ".research_copilot"
db_path = config_dir / "app.db"

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

print("--- WORKSPACES ---")
for row in conn.execute("SELECT * FROM workspace").fetchall():
    print(dict(row))

print("\n--- CHATS ---")
for row in conn.execute("SELECT id, workspace_id, title, is_archived, is_incognito FROM chat").fetchall():
    print(dict(row))

print("\n--- MESSAGES ---")
for row in conn.execute("SELECT id, chat_id, role, content, group_id, is_active FROM message").fetchall():
    print(dict(row))

conn.close()
