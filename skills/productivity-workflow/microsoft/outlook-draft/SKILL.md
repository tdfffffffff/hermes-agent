---
name: outlook-draft
version: 4.0.0
description: Finds an email by sender name and saves a reply draft via Microsoft Graph. Never sends — always shows draft to user first. Signs in automatically if not yet authenticated.
tools:
  - execute_code
---

## Overview

Searches the inbox for an email from a given sender, generates a reply draft, shows it for approval, then saves it to Drafts via `hermes-graph-mcp`. Never sends without explicit user confirmation. Handles Microsoft sign-in inline — no need to run a separate auth skill first.

**Critical: use `execute_code` for every MCP call. Never construct curl or shell commands.**

---

## Two-phase workflow

### Phase 1 — Find the email (MODE = "find")

```python
import urllib.request, urllib.parse, json

MCP = "http://hermes-graph-mcp:8083"

def mcp_get(path, params=None):
    url = MCP + path
    if params:
        url += "?" + urllib.parse.urlencode({k: str(v) for k, v in params.items()})
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return {"error": f"HTTP {e.code}", "detail": body[:500]}
    except Exception as e:
        return {"error": str(e)}

try:
    username = open("/opt/data/hermes-username").read().strip()
except Exception:
    username = "unknown"

# ── SET THESE BEFORE RUNNING ────────────────────────────────────────────────
MODE        = "find"          # find | draft_reply
SENDER_NAME = ""              # partial name to search for (e.g. "John" or "Kwang Hwee")
EMAIL_ID    = ""              # set this in Phase 2 from Phase 1 output
DRAFT_BODY  = ""              # set this in Phase 2 after composing the draft
# ───────────────────────────────────────────────────────────────────────────

# Auth check — start sign-in flow inline if not authenticated
auth = mcp_get("/auth/status", {"username": username})
if auth.get("status") != "complete":
    r = mcp_get("/auth/start", {"username": username})
    if r.get("status") == "already_authenticated":
        pass
    elif "user_code" in r:
        print("Sign-in required to access your Outlook.")
        print()
        print(f"1. Open: {r['verification_uri']}")
        print(f"2. Enter code: {r['user_code']}")
        print("3. Sign in with your Microsoft account and complete MFA")
        print()
        mins = r.get("expires_in", 900) // 60
        print(f"Code valid for {mins} minutes.")
        print("Once signed in, tell me and I'll continue.")
        raise SystemExit(0)
    else:
        print(f"Auth error: {r}")
        raise SystemExit(0)

auth = mcp_get("/auth/status", {"username": username})
if auth.get("status") != "complete":
    print("Authentication not yet confirmed. Please try again in a moment.")
    raise SystemExit(0)

if MODE == "find":
    r = mcp_get("/api/emails", {"username": username, "days": 14, "top": 50})
    if "error" in r:
        detail = r.get("detail", "")
        if "MailboxNotEnabledForRESTAPI" in detail:
            print("Mailbox access issue — your mailbox is hosted on-premises and is not reachable via Microsoft Graph.")
            print("This affects all Outlook-related features. Contact your IT team to migrate to Exchange Online.")
        elif "401" in r["error"]:
            print("Authentication expired. Ask me to sign in again.")
        else:
            print(f"Error: {r['error']}")
            if detail:
                print(f"Detail: {detail[:300]}")
        raise SystemExit(0)

    msgs = r.get("value", [])
    if not msgs:
        print("No emails found in the last 14 days.")
        raise SystemExit(0)

    hint = SENDER_NAME.lower()
    if hint:
        matched = [m for m in msgs
                   if hint in m.get("from", {}).get("emailAddress", {}).get("name", "").lower()
                   or hint in m.get("from", {}).get("emailAddress", {}).get("address", "").lower()]
    else:
        matched = msgs

    if not matched:
        print(f"No emails found from '{SENDER_NAME}' in the last 14 days.")
        print("Emails found from:")
        senders = list(dict.fromkeys(
            m.get("from", {}).get("emailAddress", {}).get("name", "") for m in msgs[:10]
        ))
        for s in senders:
            print(f"  • {s}")
        raise SystemExit(0)

    print(f"Found {len(matched)} email(s) matching '{SENDER_NAME}':\n")
    for m in matched[:5]:
        date   = str(m.get("receivedDateTime", ""))[:10]
        sender = m.get("from", {}).get("emailAddress", {}).get("name", "Unknown")
        subj   = m.get("subject", "(no subject)")
        prev   = m.get("bodyPreview", "")[:100]
        print(f"ID: {m['id']}")
        print(f"  [{date}] From: {sender}")
        print(f"  Subject: {subj}")
        if prev:
            print(f"  {prev}")
        print()
    print("Copy the ID of the email you want to reply to, set it as EMAIL_ID in Phase 2.")

elif MODE == "draft_reply":
    if not EMAIL_ID:
        print("ERROR: EMAIL_ID is empty. Run MODE='find' first and paste the ID here.")
        raise SystemExit(0)
    if not DRAFT_BODY:
        print("ERROR: DRAFT_BODY is empty. Compose the reply text and set DRAFT_BODY.")
        raise SystemExit(0)

    url = MCP + f"/api/emails/{EMAIL_ID}/draft-reply"
    url += "?" + urllib.parse.urlencode({"username": username})
    data = json.dumps({"body": DRAFT_BODY}).encode()
    req  = urllib.request.Request(url, data=data,
           headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        result = {"error": f"HTTP {e.code}", "detail": body[:300]}
    except Exception as e:
        result = {"error": str(e)}

    if "error" in result:
        detail = result.get("detail", "")
        if "MailboxNotEnabledForRESTAPI" in detail:
            print("Draft save failed — mailbox is on-premises and not reachable via Graph API.")
        else:
            print(f"Error saving draft: {result['error']}")
    else:
        print("Draft saved to your Drafts folder.")
        print()
        print("Not sent.")
        print("Open Outlook to review and send when ready.")

else:
    print(f"Unknown MODE: {MODE}. Valid: find | draft_reply")
```

---

## Workflow

**Phase 1 — find the email:**
1. If not authenticated: show the sign-in code verbatim, end your turn, wait for user to confirm sign-in, then re-run.
2. Set `SENDER_NAME` to the person's name (partial is fine). Run with `MODE = "find"`.
3. Show the matching emails to the user. Ask which one to reply to.

**Phase 2 — draft and save:**
1. Compose the draft reply based on the user's instructions.
2. Show the draft to the user: "Here's the draft — shall I save this to your Drafts folder?"
3. After user confirms: set `EMAIL_ID`, `DRAFT_BODY`, `MODE = "draft_reply"`. Run the block.
4. Confirm: "Draft saved to your Drafts folder. Not sent."

## Rules
- Use `execute_code` for all MCP calls. No curl or shell.
- If the block shows a sign-in code: show it verbatim, end your turn, wait for confirmation.
- ALWAYS show the draft to the user and get confirmation before running `draft_reply`.
- The `draft_reply` endpoint saves to Drafts — it does NOT send. Make this clear.
- If MailboxNotEnabledForRESTAPI: explain the on-prem Exchange limitation.
- Never construct a send call. The send endpoint exists but must never be called from this skill.
