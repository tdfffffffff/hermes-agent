---
name: ms-auth-setup
version: 4.0.0
description: One-time Microsoft account sign-in using device code flow. No passwords in chat. Session persists ~90 days.
tools:
  - execute_code
---

## Overview

Links the user's your Microsoft account to Hermes using a device code — they sign in from any browser (phone, personal laptop, anything) and Hermes confirms automatically. Once authenticated, they can use outlook-triage, outlook-meeting-prep, outlook-draft, and teams-scraper.

**Critical: use `execute_code` for every MCP call. Never construct curl or shell commands.**

---

## The single execute_code block — set MODE then run the whole thing

```python
import urllib.request, urllib.parse, json, time

MCP = "http://hermes-graph-mcp:8083"

def mcp_get(path, params=None):
    url = MCP + path
    if params:
        url += "?" + urllib.parse.urlencode({k: str(v) for k, v in params.items()})
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode()[:300]}"}
    except Exception as e:
        return {"error": str(e)}

def mcp_delete(path, params=None):
    url = MCP + path
    if params:
        url += "?" + urllib.parse.urlencode({k: str(v) for k, v in params.items()})
    req = urllib.request.Request(url, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)}

try:
    username = open("/opt/data/hermes-username").read().strip()
except Exception:
    username = "unknown"

# ── SET MODE BEFORE RUNNING ─────────────────────────────────────────────────
MODE = "check_auth"   # check_auth | start_auth | confirm_auth | revoke
# ───────────────────────────────────────────────────────────────────────────

if MODE == "check_auth":
    r = mcp_get("/auth/status", {"username": username})
    if r.get("status") == "complete":
        me = mcp_get("/api/me", {"username": username})
        name  = me.get("displayName", username)
        email = me.get("mail") or me.get("userPrincipalName", "")
        print(f"Authenticated as: {name} ({email})")
        print("\nReady to use:")
        print("  outlook-triage — inbox digest and prioritisation")
        print("  outlook-meeting-prep — pre-meeting context from calendar + email")
        print("  outlook-draft — draft replies to emails")
        print("  teams-scraper — read Teams chat history")
    else:
        print(f"Status: {r.get('status', 'not_started')}")
        print("Not authenticated. Run with MODE='start_auth' to sign in.")

elif MODE == "start_auth":
    r = mcp_get("/auth/start", {"username": username})
    if r.get("status") == "already_authenticated":
        me = mcp_get("/api/me", {"username": username})
        name  = me.get("displayName", username)
        email = me.get("mail") or me.get("userPrincipalName", "")
        print(f"Already authenticated as: {name} ({email})")
    elif "user_code" in r:
        print("Here's what to do:")
        print()
        print(f"Open {r['verification_uri']} in any browser")
        print(f"Enter this code: {r['user_code']}")
        print(f"Sign in with your Microsoft account and complete MFA")
        print()
        mins = r.get("expires_in", 900) // 60
        print(f"You have {mins} minutes before the code expires. Let me know when you've finished signing in and I'll confirm authentication.")
    else:
        print(f"Error starting auth: {r}")

elif MODE == "confirm_auth":
    for _ in range(12):
        r = mcp_get("/auth/status", {"username": username})
        if r.get("status") == "complete":
            break
        time.sleep(5)
    if r.get("status") == "complete":
        me = mcp_get("/api/me", {"username": username})
        name  = me.get("displayName", username)
        email = me.get("mail") or me.get("userPrincipalName", "")
        print("You're all set.")
        print()
        print(f"Authenticated as: {name} ({email})")
        print()
        print("Your Microsoft account is linked and ready to go. You can now use:")
        print()
        print("outlook-triage — inbox digest and prioritisation")
        print("outlook-meeting-prep — pre-meeting context from calendar + email")
        print("outlook-draft — draft replies to emails")
        print("teams-scraper — read Teams chat history")
        print()
        print("Authentication stays valid for roughly 90 days before you need to repeat this.")
    elif r.get("status", "").startswith("error:"):
        print(f"Sign-in failed: {r['status']}")
        print("Run with MODE='start_auth' to try again.")
    else:
        print(f"Not yet confirmed (status: {r.get('status')}). Still waiting — try again in a moment.")

elif MODE == "revoke":
    r = mcp_delete("/auth/revoke", {"username": username})
    print(f"Revoke: {r}")

else:
    print(f"Unknown MODE: {MODE}. Valid: check_auth | start_auth | confirm_auth | revoke")
```

---

## Workflow

1. **Always start with `check_auth`** — if already authenticated, show the confirmation and list available skills.

2. **Run `start_auth`** — show the verification_uri and user_code VERBATIM, exactly as printed. Do not paraphrase. Wait for the user to confirm they've signed in.

3. **After user confirms** — run `confirm_auth`. It polls up to 60 seconds. If complete, show the full confirmation message including their display name and email.

## Rules
- Never ask for or handle passwords or MFA codes. The user handles all sign-in in their own browser.
- Show the code and verification_uri exactly as returned — do not edit or wrap them.
- After showing the code, end your turn and wait for the user's confirmation before running confirm_auth.
- The user can authenticate from a phone, personal laptop, or any browser — it does not need to be on the same network.
