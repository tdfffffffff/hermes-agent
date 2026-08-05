#!/usr/bin/env python3
"""
hermes-auto-provision.py — Pre-provisions Hermes containers for new OpenWebUI users.

For each user in OpenWebUI's DB:
  1. POST /v1/admin/provision/{username} → wrapper creates the container + API key
  2. If the chat hasn't been injected yet, inserts a pinned welcome chat into
     OpenWebUI's SQLite DB (via docker exec -i) showing the user their API key.

Usage:
  python3 hermes-auto-provision.py          # run once
  python3 hermes-auto-provision.py --daemon # loop every CHECK_INTERVAL seconds
"""

import json
import os
import re
import stat
import subprocess
import sys
import time
import uuid
import urllib.error
import urllib.request

WRAPPER_URL       = "http://127.0.0.1:5000"
WRAPPER_ADMIN_KEY = os.environ.get("WRAPPER_ADMIN_KEY", "")
CHECK_INTERVAL    = 60          # seconds between daemon sweeps
WELCOME_TITLE     = "Hermes — Welcome"
STATE_ROOT        = "/data/hermes/state"

# Content of the agent-browser wrapper deployed to each user's node_modules/.bin/
_AGENT_BROWSER_WRAPPER = """\
#!/bin/bash
export HOME=/opt/data
export TMPDIR=/tmp
export AGENT_BROWSER_EXECUTABLE_PATH="/opt/datasets/agent-browser/chrome-150.0.7871.115/chrome"
export AGENT_BROWSER_ARGS="--no-sandbox --disable-gpu --disable-dev-shm-usage --remote-allow-origins=*"
export AGENT_BROWSER_PROFILE="/opt/data/browser-profile"
exec /opt/hermes/node_modules/agent-browser/bin/agent-browser-linux-x64 "$@"
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def sanitize_username(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "", name)[:64].replace("_", "-")


def get_openwebui_users() -> list:
    """Read all user rows from OpenWebUI's SQLite DB via docker exec."""
    script = (
        "import sqlite3, json; "
        "conn = sqlite3.connect('/app/backend/data/webui.db'); "
        "rows = conn.execute('SELECT id, name, email FROM user').fetchall(); "
        "print(json.dumps([{'id': r[0], 'name': r[1], 'email': r[2]} for r in rows])); "
        "conn.close()"
    )
    result = subprocess.run(
        ["docker", "exec", "openwebui", "python3", "-c", script],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "non-zero exit")
    return json.loads(result.stdout.strip())


def provision_user_api(username: str) -> dict:
    """POST /v1/admin/provision/{username}. Blocks until container is running (≤30s)."""
    req = urllib.request.Request(
        f"{WRAPPER_URL}/v1/admin/provision/{username}",
        method="POST",
        headers={"Authorization": f"Bearer {WRAPPER_ADMIN_KEY}"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


GMAIL_MAILPIT_SHORTCUTS = [
    {
        "command": "gmail-inbox",
        "name": "Gmail Inbox — Read, triage, draft and send Gmail emails",
        "content": "Use the gmail-inbox skill.",
    },
    {
        "command": "gmail-meeting-prep",
        "name": "Gmail Meeting Prep — Pre-meeting brief from Google Calendar and Gmail",
        "content": "Use the gmail-meeting-prep skill.",
    },
    {
        "command": "gmail-req-harvester",
        "name": "Gmail Requirements Harvester — Extract requirements from Gmail threads and generate PPTX / DOCX",
        "content": "Use the gmail-req-harvester skill.",
    },
    {
        "command": "mailpit-inbox",
        "name": "Mailpit Inbox (On-Prem) — Triage, read, draft and send emails. No internet required.",
        "content": "Use the mailpit-inbox skill.",
    },
    {
        "command": "mailpit-meeting-prep",
        "name": "Mailpit Meeting Prep (On-Prem) — Pre-meeting brief from on-prem calendar. No internet required.",
        "content": "Use the mailpit-meeting-prep skill.",
    },
    {
        "command": "mailpit-req-harvester",
        "name": "Mailpit Req Harvester (On-Prem) — Extract requirements, generate PPTX/DOCX. No internet required.",
        "content": "Use the mailpit-req-harvester skill.",
    },
]


def build_welcome(username: str, api_key: str) -> str:
    return (
        f"**Welcome to Hermes, {username}!** Your container is ready.\n\n"
        "Your personal API key:\n\n"
        f"`{api_key}`\n\n"
        "**One-time setup:**\n"
        "1. Copy the key above\n"
        "2. Open **Settings → Connections → OpenAI API**\n"
        "3. Set **API Key** to your key, then save\n\n"
        "**Gmail skills** — connect your Google account first:\n"
        "- *\"Use gmail-inbox\"* — read, triage, draft and send emails\n"
        "- *\"Use gmail-meeting-prep\"* — pre-meeting brief from Google Calendar + Gmail\n"
        "- *\"Use gmail-req-harvester\"* — extract requirements from Gmail threads\n\n"
        "**Mailpit skills** — on-prem email, no internet required:\n"
        "- *\"Use mailpit-inbox\"* — read, triage, draft and send emails\n"
        "- *\"Use mailpit-meeting-prep\"* — pre-meeting brief from on-prem calendar\n"
        "- *\"Use mailpit-req-harvester\"* — extract requirements and generate PPTX/DOCX"
    )


def inject_shortcuts(user_id: str) -> int:
    """
    Insert Gmail and Mailpit prompt shortcuts for a user if they don't already have them.
    Returns the count of shortcuts newly inserted.
    """
    payload = json.dumps({"user_id": user_id, "shortcuts": GMAIL_MAILPIT_SHORTCUTS})
    db_script = """\
import sqlite3, json, sys, uuid, time
d = json.loads(sys.stdin.read())
conn = sqlite3.connect('/app/backend/data/webui.db')
now = int(time.time())
inserted = 0
for s in d['shortcuts']:
    row = conn.execute("SELECT id FROM prompt WHERE command=?", (s['command'],)).fetchone()
    if not row:
        pid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO prompt (id, command, user_id, name, content, data, meta, is_active, tags, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, '{}', '{}', 1, '[]', ?, ?)",
            (pid, s['command'], d['user_id'], s['name'], s['content'], now, now)
        )
        inserted += 1
    else:
        pid = row[0]
    # Ensure wildcard read grant exists so all users can see this shortcut
    grant_exists = conn.execute(
        'SELECT 1 FROM access_grant WHERE resource_type="prompt" AND resource_id=? AND principal_id="*"',
        (pid,)
    ).fetchone()
    if not grant_exists:
        conn.execute(
            'INSERT INTO access_grant (id, resource_type, resource_id, principal_type, principal_id, permission, created_at)'
            ' VALUES (?, "prompt", ?, "user", "*", "read", ?)',
            (str(uuid.uuid4()), pid, now)
        )
conn.commit()
print(inserted)
conn.close()
"""
    result = subprocess.run(
        ["docker", "exec", "-i", "openwebui", "python3", "-c", db_script],
        input=payload,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "non-zero exit from shortcut script")
    return int(result.stdout.strip() or "0")


def inject_welcome_chat(user_id: str, username: str, api_key: str) -> str:
    """
    Insert a pinned welcome chat into OpenWebUI's SQLite DB.
    Returns 'injected' if new, 'exists' if already present.
    Passes all data via JSON on stdin to avoid quoting issues.
    """
    user_msg_id  = str(uuid.uuid4())
    asst_msg_id  = str(uuid.uuid4())
    chat_id      = str(uuid.uuid4())
    now          = int(time.time())
    content      = build_welcome(username, api_key)

    # OpenWebUI history tree: root must be a user message; assistant is its child.
    # Each node needs a `models` field or the renderer skips it.
    chat_blob = json.dumps({
        "id":     chat_id,
        "title":  WELCOME_TITLE,
        "models": ["hermes-agent"],
        "messages": [
            {"role": "user",      "content": ""},
            {"role": "assistant", "content": content},
        ],
        "history": {
            "currentId": asst_msg_id,
            "messages": {
                user_msg_id: {
                    "id":          user_msg_id,
                    "parentId":    None,
                    "childrenIds": [asst_msg_id],
                    "role":        "user",
                    "content":     "",
                    "timestamp":   now,
                    "models":      ["hermes-agent"],
                },
                asst_msg_id: {
                    "id":          asst_msg_id,
                    "parentId":    user_msg_id,
                    "childrenIds": [],
                    "role":        "assistant",
                    "content":     content,
                    "timestamp":   now,
                    "models":      ["hermes-agent"],
                },
            },
        },
        "files":     [],
        "tags":      [],
        "timestamp": now,
    })

    payload = json.dumps({
        "user_id":      user_id,
        "chat_id":      chat_id,
        "user_msg_id":  user_msg_id,
        "asst_msg_id":  asst_msg_id,
        "title":        WELCOME_TITLE,
        "chat_blob":    chat_blob,
        "content":      json.dumps(content),   # JSON-encoded for chat_message.content
        "now":          now,
    })

    # Script runs inside the openwebui container; data arrives on stdin.
    # Inserts into both `chat` (sidebar entry) and `chat_message` (rendered messages).
    db_script = """\
import sqlite3, json, sys
d = json.loads(sys.stdin.read())
conn = sqlite3.connect('/app/backend/data/webui.db')
exists = conn.execute(
    "SELECT 1 FROM chat WHERE user_id=? AND title=?",
    (d['user_id'], d['title'])
).fetchone()
if not exists:
    conn.execute(
        "INSERT INTO chat (id, user_id, title, chat, archived, pinned, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, 0, 1, ?, ?)",
        (d['chat_id'], d['user_id'], d['title'], d['chat_blob'], d['now'], d['now'])
    )
    # User message row (empty prompt root)
    conn.execute(
        "INSERT INTO chat_message"
        " (id, chat_id, user_id, role, parent_id, content, output, model_id, files, sources, embeds, done, status_history, error, usage, created_at, updated_at)"
        " VALUES (?, ?, ?, 'user', NULL, '\"\"', 'null', NULL, 'null', 'null', 'null', 1, 'null', 'null', 'null', ?, ?)",
        (
            d['chat_id'] + '-' + d['user_msg_id'],
            d['chat_id'], d['user_id'],
            d['now'], d['now'],
        )
    )
    # Assistant welcome message row
    conn.execute(
        "INSERT INTO chat_message"
        " (id, chat_id, user_id, role, parent_id, content, output, model_id, files, sources, embeds, done, status_history, error, usage, created_at, updated_at)"
        " VALUES (?, ?, ?, 'assistant', ?, ?, 'null', 'hermes-agent', 'null', 'null', 'null', 1, 'null', 'null', 'null', ?, ?)",
        (
            d['chat_id'] + '-' + d['asst_msg_id'],
            d['chat_id'], d['user_id'],
            d['user_msg_id'],
            d['content'],
            d['now'], d['now'],
        )
    )
    conn.commit()
    print('injected')
else:
    print('exists')
conn.close()
"""
    result = subprocess.run(
        ["docker", "exec", "-i", "openwebui", "python3", "-c", db_script],
        input=payload,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "non-zero exit from db_script")
    return result.stdout.strip()


# ── Index.html patch ──────────────────────────────────────────────────────────

INDEX_HOST = "/data/openwebui-custom/index.html"
INDEX_CTR  = "/app/build/index.html"
MARKER     = "hw3_"   # unique string only present after injection

def ensure_index_patch() -> None:
    """Re-inject the welcome-redirect script if the container lost it (e.g. after recreation)."""
    check = subprocess.run(
        ["docker", "exec", "openwebui", "grep", "-q", MARKER, INDEX_CTR],
        capture_output=True,
    )
    if check.returncode == 0:
        return  # already patched

    # Read host copy and push back into container
    try:
        result = subprocess.run(
            ["docker", "exec", "-i", "openwebui", "sh", "-c", f"cat > {INDEX_CTR}"],
            input=open(INDEX_HOST, "rb").read(),
            capture_output=True,
            timeout=15,
        )
        if result.returncode == 0:
            print("[provisioner] Re-applied index.html patch", flush=True)
        else:
            print(f"[provisioner] index.html patch failed: {result.stderr.decode()}", flush=True)
    except Exception as exc:
        print(f"[provisioner] index.html patch error: {exc}", flush=True)


# ── Browser wrapper ───────────────────────────────────────────────────────────

def ensure_browser_wrapper(username: str) -> None:
    """Deploy the agent-browser wrapper to the user's HERMES_HOME node_modules."""
    bin_dir = os.path.join(STATE_ROOT, username, "node_modules", ".bin")
    wrapper  = os.path.join(bin_dir, "agent-browser")
    try:
        os.makedirs(bin_dir, exist_ok=True)
        with open(wrapper, "w") as f:
            f.write(_AGENT_BROWSER_WRAPPER)
        os.chmod(wrapper, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
    except Exception as exc:
        print(f"[provisioner] browser wrapper error ({username}): {exc}", flush=True)


# ── Main loop ─────────────────────────────────────────────────────────────────

def run_once() -> None:
    ensure_index_patch()

    try:
        users = get_openwebui_users()
    except Exception as exc:
        print(f"[provisioner] Cannot read OpenWebUI users: {exc}", flush=True)
        return

    for user in users:
        safe = sanitize_username(user.get("name", ""))
        if not safe:
            continue

        try:
            result  = provision_user_api(safe)
            status  = result.get("status", "")
            api_key = result.get("api_key") or ""

            if status == "provisioned":
                print(f"[provisioner] New container: {safe}", flush=True)

            ensure_browser_wrapper(safe)

            if api_key:
                out = inject_welcome_chat(user["id"], safe, api_key)
                if out == "injected":
                    print(f"[provisioner] Welcome chat injected: {safe}", flush=True)

            added = inject_shortcuts(user["id"])
            if added:
                print(f"[provisioner] Shortcuts injected ({added}): {safe}", flush=True)

        except urllib.error.URLError as exc:
            print(f"[provisioner] Wrapper unreachable ({safe}): {exc}", flush=True)
        except Exception as exc:
            print(f"[provisioner] Error ({safe}): {exc}", flush=True)


if __name__ == "__main__":
    if "--daemon" in sys.argv:
        print(f"[provisioner] Daemon started (interval={CHECK_INTERVAL}s)", flush=True)
        while True:
            run_once()
            time.sleep(CHECK_INTERVAL)
    else:
        run_once()
