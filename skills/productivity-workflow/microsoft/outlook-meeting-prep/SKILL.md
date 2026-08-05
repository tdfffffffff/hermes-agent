---
name: outlook-meeting-prep
version: 4.0.0
description: Fetches upcoming calendar events and recent email threads with attendees to generate a pre-meeting brief. Signs in automatically if not yet authenticated.
tools:
  - execute_code
---

## Overview

Fetches calendar events and relevant emails from `hermes-graph-mcp` to generate a meeting brief with attendee context and suggested talking points. Handles Microsoft sign-in inline — no need to run a separate auth skill first.

**Critical: use `execute_code` for every MCP call. Never construct curl or shell commands.**

---

## The single execute_code block — set MEETING_HINT then run

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

# ── SET THESE BEFORE RUNNING ─────────────────────────────────────────────────
MEETING_HINT = ""   # partial meeting name or attendee — leave blank for next upcoming meeting
DAYS         = 2    # how many days ahead to look for meetings
# ───────────────────────────────────────────────────────────────────────────

# 1. Auth check — start sign-in flow inline if not authenticated
auth = mcp_get("/auth/status", {"username": username})
if auth.get("status") != "complete":
    r = mcp_get("/auth/start", {"username": username})
    if r.get("status") == "already_authenticated":
        pass
    elif "user_code" in r:
        print("Sign-in required to access your calendar.")
        print()
        print(f"1. Open: {r['verification_uri']}")
        print(f"2. Enter code: {r['user_code']}")
        print("3. Sign in with your Microsoft account and complete MFA")
        print()
        mins = r.get("expires_in", 900) // 60
        print(f"Code valid for {mins} minutes.")
        print("Once signed in, tell me and I'll pull your upcoming meetings.")
        raise SystemExit(0)
    else:
        print(f"Auth error: {r}")
        raise SystemExit(0)

auth = mcp_get("/auth/status", {"username": username})
if auth.get("status") != "complete":
    print("Authentication not yet confirmed. Please try again in a moment.")
    raise SystemExit(0)

# 2. Fetch calendar
r = mcp_get("/api/calendar", {"username": username, "days": DAYS, "top": 10})

if "error" in r:
    detail = r.get("detail", "")
    if "MailboxNotEnabledForRESTAPI" in detail:
        print("Calendar access issue. The Microsoft Graph API is returning:")
        print()
        print('  MailboxNotEnabledForRESTAPI — "The mailbox is either inactive, soft-deleted, or is hosted on-premise."')
        print()
        print("This confirms that your mailbox (email and calendar) is hosted on an on-premises Exchange server,")
        print("which Microsoft Graph API cannot reach. This affects all Outlook-related features.")
        print()
        print("To unblock, your IT team would need to either:")
        print("  • Migrate your mailbox to Exchange Online (cloud), or")
        print("  • Set up Exchange Web Services (EWS) access for on-prem Exchange.")
    elif "401" in r["error"]:
        print("Authentication expired. Ask me to sign in again.")
    else:
        print(f"Error fetching calendar: {r['error']}")
        if detail:
            print(f"Detail: {detail[:300]}")
    raise SystemExit(0)

events = r.get("value", [])
if not events:
    print(f"No meetings found in the next {DAYS} days.")
    raise SystemExit(0)

# 3. Find matching meeting
if MEETING_HINT:
    hint_lower = MEETING_HINT.lower()
    matched = [e for e in events if hint_lower in e.get("subject", "").lower()
               or any(hint_lower in a.get("emailAddress", {}).get("name", "").lower()
                      for a in e.get("attendees", []))]
    meeting = matched[0] if matched else events[0]
else:
    meeting = events[0]

# 4. Print meeting details
subject   = meeting.get("subject", "(no subject)")
start     = str(meeting.get("start", {}).get("dateTime", ""))[:16].replace("T", " ")
end       = str(meeting.get("end", {}).get("dateTime", ""))[:16].replace("T", " ")
location  = meeting.get("location", {}).get("displayName", "")
preview   = meeting.get("bodyPreview", "")[:300]
attendees = meeting.get("attendees", [])

print(f"MEETING BRIEF: {subject}")
print("=" * 60)
print(f"When    : {start} – {end}")
if location:
    print(f"Where   : {location}")
print(f"Invitees: {len(attendees)}")
for a in attendees:
    name  = a.get("emailAddress", {}).get("name", "")
    email = a.get("emailAddress", {}).get("address", "")
    print(f"  • {name} ({email})")
if preview:
    print(f"\nAgenda/Notes:\n  {preview}")
print()

# 5. Fetch recent emails from attendees (up to 3)
attendee_names = [a.get("emailAddress", {}).get("name", "") for a in attendees[:3]
                  if a.get("emailAddress", {}).get("address", "") != username]
if attendee_names:
    print("RECENT EMAIL CONTEXT")
    print("-" * 60)
    emails_r = mcp_get("/api/emails", {"username": username, "days": 14, "top": 30})
    if "value" in emails_r:
        for name in attendee_names:
            name_lower = name.lower().split()[0] if name else ""
            related = [m for m in emails_r["value"]
                       if name_lower and name_lower in m.get("from", {}).get("emailAddress", {}).get("name", "").lower()][:2]
            if related:
                print(f"\nWith {name}:")
                for m in related:
                    date  = str(m.get("receivedDateTime", ""))[:10]
                    subj  = m.get("subject", "(no subject)")
                    bprev = m.get("bodyPreview", "")[:100]
                    print(f"  [{date}] {subj}")
                    if bprev:
                        print(f"    {bprev}")

print()
print("SUGGESTED TALKING POINTS")
print("-" * 60)
print("(Generate 3-5 talking points based on the meeting subject, agenda, and email context above)")
```

---

## Workflow

1. Ask the user for a meeting name or just run with `MEETING_HINT = ""` to get the next upcoming meeting.
   - If not authenticated: show the sign-in code and URL verbatim. End your turn and wait for the user to confirm sign-in. Then re-run.

2. Run the block. It fetches calendar + recent email threads with attendees.

3. After the output, synthesise 3-5 talking points based on the meeting subject, agenda, and any relevant email context.

4. End with: "Anything else you'd like to prepare? I can draft a pre-meeting email — just ask."

## Rules
- Use `execute_code` for all MCP calls.
- If the block shows a sign-in code: show it verbatim, end your turn, wait for the user to confirm before re-running.
- If MailboxNotEnabledForRESTAPI: print the full error message. This is a known infrastructure limitation.
- Set MEETING_HINT from the user's request (e.g. "weekly sync" or "John Smith").
