---
name: outlook-triage
version: 4.0.0
description: Fetches the user's Outlook inbox via Microsoft Graph and classifies each email as Needs Reply / Action Required / FYI / Low Priority. Signs in automatically if not yet authenticated.
tools:
  - execute_code
---

## Overview

Fetches recent emails from the user's Outlook inbox via `hermes-graph-mcp` and produces a triage digest. Handles Microsoft sign-in inline — no need to run a separate auth skill first.

**Critical: use `execute_code` for every MCP call. Never construct curl or shell commands.**

---

## The single execute_code block — set variables then run

```python
import urllib.request, urllib.parse, json, time
from datetime import datetime, timezone, timedelta

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
DAYS        = 7      # how many days back to fetch
TOP         = 30     # max emails to fetch
UNREAD_ONLY = False  # set True to show only unread
# ───────────────────────────────────────────────────────────────────────────

# 1. Auth check — start sign-in flow inline if not authenticated
auth = mcp_get("/auth/status", {"username": username})
if auth.get("status") != "complete":
    r = mcp_get("/auth/start", {"username": username})
    if r.get("status") == "already_authenticated":
        pass  # re-check below
    elif "user_code" in r:
        print("Sign-in required to access your Outlook.")
        print()
        print(f"1. Open: {r['verification_uri']}")
        print(f"2. Enter code: {r['user_code']}")
        print("3. Sign in with your Microsoft account and complete MFA")
        print()
        mins = r.get("expires_in", 900) // 60
        print(f"Code valid for {mins} minutes.")
        print("Once signed in, tell me and I'll fetch your inbox.")
        raise SystemExit(0)
    else:
        print(f"Auth error: {r}")
        raise SystemExit(0)

# Confirm auth is complete
auth = mcp_get("/auth/status", {"username": username})
if auth.get("status") != "complete":
    print("Authentication not yet confirmed. Please try again in a moment.")
    raise SystemExit(0)

# 2. Fetch emails
r = mcp_get("/api/emails", {
    "username":    username,
    "days":        DAYS,
    "top":         TOP,
    "unread_only": UNREAD_ONLY,
})

if "error" in r:
    detail = r.get("detail", "")
    if "MailboxNotEnabledForRESTAPI" in detail:
        print("Mailbox access issue. The Microsoft Graph API is returning:")
        print()
        print('  MailboxNotEnabledForRESTAPI — "The mailbox is either inactive, soft-deleted, or is hosted on-premise."')
        print()
        print("This typically means your Outlook mailbox is hosted on an on-premises Exchange server")
        print("rather than Exchange Online / Microsoft 365, which Microsoft Graph doesn't support for mailbox access.")
        print()
        print("To unblock, your IT team would need to either:")
        print("  • Migrate your mailbox to Exchange Online (cloud), or")
        print("  • Set up Exchange Web Services (EWS) access for on-prem Exchange.")
    elif "401" in r["error"]:
        print("Authentication expired. Ask me to sign in again.")
    else:
        print(f"Error fetching emails: {r['error']}")
        if detail:
            print(f"Detail: {detail[:300]}")
    raise SystemExit(0)

msgs = r.get("value", [])
if not msgs:
    print(f"No emails found in the last {DAYS} days.")
    raise SystemExit(0)

# 3. Print triage digest
print(f"INBOX DIGEST — last {DAYS} days ({len(msgs)} emails)")
print("=" * 60)
print()

for m in msgs:
    date    = str(m.get("receivedDateTime", ""))[:10]
    sender  = m.get("from", {}).get("emailAddress", {}).get("name", "Unknown")
    subj    = m.get("subject", "(no subject)")
    preview = m.get("bodyPreview", "")[:120]
    is_read = m.get("isRead", True)
    unread  = " [UNREAD]" if not is_read else ""

    print(f"{date}{unread}  {sender}")
    print(f"  {subj}")
    if preview:
        print(f"  {preview}")
    print()

print("-" * 60)
print(f"Total: {len(msgs)} emails shown.")
print()
print("Classification guide (apply to each email above):")
print("  Needs Reply      — sender is waiting for your response")
print("  Action Required  — you need to do something (review, approve, attend)")
print("  FYI              — informational, no action needed")
print("  Low Priority     — newsletters, notifications, auto-generated")
```

---

## Workflow

1. Run the block as-is.
   - If not authenticated: it shows a sign-in code. End your turn and wait for the user to sign in.
   - When the user confirms they've signed in: re-run the block — auth will pass and the inbox loads.

2. After printing the digest, classify each email using the guide at the bottom. Group by category in your response.

3. End with: "Want to draft a reply to any of these? Just tell me which one."

## Rules
- Use `execute_code` for the MCP call. Do not use curl or shell.
- If the block shows a sign-in code: show the code and URL verbatim, end your turn, and wait for the user to confirm sign-in before re-running.
- If MailboxNotEnabledForRESTAPI: print the full error message exactly, including the bullet points. This is a known infrastructure limitation.
- Adjust DAYS and TOP based on user request (e.g. "last 3 days", "top 10 unread").
