#!/usr/bin/env python3
"""Patch ccr-router app_config: set claudeCode profile models to openrouter/free."""
import json
import os
import sqlite3

DB = os.environ.get("CCR_CONFIG_DB", os.path.expanduser("~/.claude-code-router/config.sqlite"))

db = sqlite3.connect(DB)
row = db.execute("SELECT value_json FROM app_config WHERE key='default'").fetchone()
if not row:
    raise SystemExit("app_config 'default' row not found")
data = json.loads(row[0])

prof = data.setdefault("profile", {})
cc = prof.setdefault("claudeCode", {})

MODELS = {
    "model": "openrouter/free",
    "opusModel": "openrouter/free",
    "sonnetModel": "openrouter/free",
    "smallFastModel": "openrouter/free",
    "haikuModel": "openrouter/free",
}
cc.update(MODELS)
print("claudeCode profile before profiles-loop:", {k: cc.get(k) for k in MODELS})

for p in prof.get("profiles", []):
    if p.get("id") == "default-claude-code":
        p.update(MODELS)
        print("default-claude-code profile patched")

db.execute("UPDATE app_config SET value_json=?, updated_at=datetime('now') WHERE key='default'", (json.dumps(data),))
db.commit()

# verify
row2 = db.execute("SELECT value_json FROM app_config WHERE key='default'").fetchone()
d2 = json.loads(row2[0])["profile"].get("claudeCode", {})
print("VERIFY claudeCode:", {k: d2.get(k) for k in MODELS})
db.close()
