import sqlite3
import json
from pathlib import Path

config_dir = Path.home() / ".research_copilot"
db_path = config_dir / "app.db"

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

data = {
    "workspaces": [dict(r) for r in conn.execute("SELECT * FROM workspace").fetchall()],
    "chats": [dict(r) for r in conn.execute("SELECT id, workspace_id, title, is_archived, is_incognito FROM chat").fetchall()],
}

with open("D:/Research_Copilot/db_dump.json", "w") as f:
    json.dump(data, f, indent=2)

conn.close()
