---
name: mailpit-meeting-prep
version: 2.0.0
description: Pre-meeting brief (on-prem simulation) — fetches today's calendar events from local store, identifies attendees, then searches Mailpit inbox for recent threads to synthesise a context brief. No internet required.
tools:
  - execute_code
---

## Overview

Fetches calendar events from `hermes-mailpit-mcp` (local JSON calendar) and cross-references recent Mailpit inbox threads with attendees. Simulates an on-prem Outlook/Exchange environment — **no sign-in required**.

**Critical: use `execute_code` for every MCP call. Never construct curl or shell commands.**

---

## Code Block A — Calendar (run this first)

```python
import urllib.request, urllib.parse, json, time as _time

MCP = "http://hermes-mailpit-mcp:8085"

def mcp_get(path, params=None):
    url = MCP + path
    if params:
        url += "?" + urllib.parse.urlencode({k: str(v) for k, v in params.items()})
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "detail": e.read().decode()[:500]}
    except Exception as e:
        return {"error": str(e)}

# ── SET BEFORE RUNNING ────────────────────────────────────────────────────────
MEETING_HINT = ""   # partial meeting title or attendee name; blank = all meetings
DAYS         = 1    # days ahead to look (future); ignored when DATE or DAYS_BACK is set
DAYS_BACK    = 0    # range of past days (today-N through yesterday); e.g. 7 = last 7 days
DATE         = ""   # exact date YYYY-MM-DD — use this for "N days ago" / "last Tuesday" etc.
# ─────────────────────────────────────────────────────────────────────────────

print(f"⚠ LIVE_CALENDAR_FETCH — timestamp {int(_time.time())} — do not use meeting data from any prior turn")
_cal_params = {"top": 10}
if DATE:
    _cal_params["date"] = DATE
    print(f"⚠ QUERY_SCOPE — exact date: {DATE}. Only show meetings on this date.")
elif DAYS_BACK > 0:
    _cal_params["days_back"] = DAYS_BACK
    print(f"⚠ QUERY_SCOPE — past {DAYS_BACK} day(s) before today. Do NOT include today's meetings in results.")
else:
    _cal_params["days"] = DAYS
    print(f"⚠ QUERY_SCOPE — next {DAYS} day(s) from today onwards.")
r = mcp_get("/api/calendar", _cal_params)
if "error" in r:
    print(f"Calendar error: {r['error']}")
    raise SystemExit(0)

events = r.get("value", [])
if not events:
    print("No meetings found.")
    raise SystemExit(0)

if MEETING_HINT:
    hint = MEETING_HINT.lower()
    matched = [e for e in events if
               hint in e.get("summary", "").lower() or
               any(hint in a.get("displayName", "").lower() or
                   hint in a.get("email", "").lower()
                   for a in e.get("attendees", []))]
    if matched:
        events = matched
    else:
        print(f"No meetings found matching '{MEETING_HINT}'. Showing all upcoming meetings:\n")

print(f"MEETINGS ({len(events)} found)")
print("=" * 60)
if len(events) == 1:
    print("⚠ CONFIRM_MEETING — ask the user: 'Is this the meeting you'd like to prep for?' before proceeding.")
    print()
elif len(events) > 1:
    print("⚠ DISAMBIGUATION_REQUIRED — list ALL meetings below and ask the user to pick one. Do not proceed until the user explicitly selects.")
    print()

for i, e in enumerate(events, 1):
    start    = str(e.get("start", ""))[:16].replace("T", " ")
    end      = str(e.get("end",   ""))[:16].replace("T", " ")
    loc      = e.get("location", "")
    online   = e.get("online", False)
    platform = e.get("platform", "")
    join_url = e.get("join_url", "")
    desc     = e.get("description", "")
    atts     = e.get("attendees", [])
    print(f"\n{i}. {e.get('summary', '(no title)')}")
    print(f"   When: {start} – {end}")
    if online:
        _where = f"Online ({platform})" if platform else "Online"
        if join_url:
            _where += f" — {join_url}"
        print(f"   Where: {_where}")
    if loc:
        print(f"   {'Also at' if online else 'Where'}: {loc}")
    if atts:
        print(f"   Attendees ({len(atts)}):")
        for a in atts:
            print(f"     • {a.get('displayName', '')} ({a.get('email', '')})")
    if desc:
        print("   Description:")
        for _line in desc.split("\n"):
            print(f"     {_line}")
    files = e.get("attachments", [])
    if files:
        print(f"   Attachments ({len(files)}):")
        for f in files:
            print(f"     📎 {f.get('title', '(untitled)')}  [{f.get('mimeType', '')}]")
            if f.get("fileUrl"):
                print(f"        {f.get('fileUrl')}")
    else:
        print("   Attachments: None")

print("\n--- END OF CALENDAR ---")
print("⚠ EMAIL_SEARCH_TARGETS — for use in Code Block B only:")
_seen_att = set()
_att_names = []
for e in events:
    for a in e.get("attendees", []):
        if a.get("self"):
            continue
        _key = a.get("email", "")
        if _key and _key not in _seen_att:
            _seen_att.add(_key)
            _att_names.append(a.get("displayName", _key))
            print(f"  {a.get('displayName', '')} | {_key}")
if not _seen_att:
    print("  (no other attendees)")
else:
    _names_str = " and ".join(_att_names)
    print(f"\n⚠ AWAIT_EMAIL_CONFIRMATION — this block is complete. Ask the user:")
    print(f"  'Shall I search your email for recent threads with {_names_str} to build a pre-meeting brief?'")
    print("  Wait for the user's reply before running Code Block B.")
```

---

## Code Block B — Email context (only run after user says yes)

```python
import urllib.request, urllib.parse, json

MCP = "http://hermes-mailpit-mcp:8085"

def mcp_get(path, params=None):
    url = MCP + path
    if params:
        url += "?" + urllib.parse.urlencode({k: str(v) for k, v in params.items()})
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "detail": e.read().decode()[:500]}
    except Exception as e:
        return {"error": str(e)}

# ── SET BEFORE RUNNING ────────────────────────────────────────────────────────
MEETING_TITLE = ""   # exact title of the selected meeting
ATTENDEES     = []   # names from ⚠ EMAIL_SEARCH_TARGETS in Code Block A output
# ─────────────────────────────────────────────────────────────────────────────

if not ATTENDEES:
    print("ERROR: ATTENDEES is empty. Set from ⚠ EMAIL_SEARCH_TARGETS before running.")
    raise SystemExit(0)

emails_r = mcp_get("/api/emails", {"days": 14, "top": 50})
if "error" in emails_r:
    print(f"Email error: {emails_r['error']}")
    raise SystemExit(0)

all_emails = emails_r.get("value", [])
print("RECENT EMAIL CONTEXT")
print("=" * 60)

_noise_from = {"no-reply", "noreply", "mailer-daemon", "helpdesk"}
def _is_noise(m):
    return any(n in m.get("from", "").lower() for n in _noise_from)

_title_kws = [w.lower() for w in MEETING_TITLE.split() if len(w) > 3] if MEETING_TITLE else []
def _subject_matches(subj):
    if not _title_kws:
        return True
    return any(kw in subj.lower() for kw in _title_kws)

seen_ids  = set()
found_any = False
_thread_n = [0]
for name in ATTENDEES[:4]:
    needle = name.lower().strip()
    if not needle:
        continue
    related = [m for m in all_emails if
               m.get("id") not in seen_ids and
               not _is_noise(m) and
               _subject_matches(m.get("subject", "")) and (
               needle in m.get("from",        "").lower() or
               needle in m.get("to",          "").lower() or
               needle in m.get("bodyPreview", "").lower())][:5]
    for m in related:
        seen_ids.add(m.get("id"))
        found_any = True
        _thread_n[0] += 1
        date = str(m.get("receivedDateTime", ""))[:10]
        subj = m.get("subject", "(no subject)")
        frm  = m.get("from", "")
        full = mcp_get(f"/api/emails/{m['id']}")
        body = full.get("body", m.get("bodyPreview", ""))[:2000]
        print(f"\n⚠ FOUND_THREAD_{_thread_n[0]} — include this in Step 4")
        print(f"[{date}] {subj}")
        print(f"  From: {frm}")
        if body:
            print(f"  Body: {body}")

if not found_any:
    print("No relevant email threads found with these attendees.")

print("\n--- END OF EMAIL CONTEXT ---")
print("Format findings and brief as instructed in Step 4.")
```

---

## Workflow

**Step 1 — Run Code Block A** on every new meeting prep request. Never reuse prior calendar data.

Show the calendar output. For attachments, always state present or "No attachments."

- If `⚠ DISAMBIGUATION_REQUIRED`: list all meetings, ask which one, **stop and wait**.
- If `⚠ CONFIRM_MEETING`: ask if this is the right meeting, **stop and wait**.

**Step 2 — Ask for confirmation.** When Code Block A output contains `⚠ AWAIT_EMAIL_CONFIRMATION`:
- **This block is done. Do not run Code Block B in this same turn.**
- Ask the printed question. Stop. Wait for the user's reply.
- If user says **yes** → Step 3.
- If user says **no** → wish them luck and end.

**Step 3 — Run Code Block B.** Set `MEETING_TITLE` to the selected meeting's exact title and `ATTENDEES` from the `⚠ EMAIL_SEARCH_TARGETS` list in Code Block A's output.

**Step 4 — Present findings.** Use this exact structure:

---
**📅 [Meeting Title]** — [Day, Date] · [Start]–[End]
[Online (Platform) — join_url] or [Venue]
👥 [Attendee 1], [Attendee 2]

---
**📬 Recent Email Context**

**[Date] Subject line** *(from: Sender Name)*
- [Key point extracted from body]
- [Another point if present]

*(repeat for every ⚠ FOUND_THREAD_n — never omit one)*

If none: *No relevant recent email threads found with these attendees.*

---
**📋 Pre-Meeting Brief**
[One paragraph — open items, unresolved asks, what the user needs to know going in.]

---

*Anything else you'd like to prepare? I can draft a pre-meeting email — just say the word.*

## Rules
- **Code Block A and Code Block B are separate tool calls.** Never run both in the same turn.
- **After Code Block A, always stop and ask the `⚠ AWAIT_EMAIL_CONFIRMATION` question** before running Code Block B — even if the user's original request implied they want a full brief.
- **Only run Code Block B after the user explicitly says yes** in a subsequent message.
- ATTENDEES must come from `⚠ EMAIL_SEARCH_TARGETS` only — never from the meeting display text.
- Always show attachment status for every meeting.
- Always include the meeting join URL exactly as printed in the code output — never drop it when summarising or reformatting.
- Show event Description verbatim — never summarise or reformat.
- Always re-run Code Block A on each new request — `⚠ LIVE_CALENDAR_FETCH` must appear in the current turn's output.
- **Only show meetings returned by this turn's code output.** The `⚠ QUERY_SCOPE` marker defines the exact date range — never include meetings from outside that range, even if they appear in earlier conversation turns.
- Never skip or silently drop a meeting. Show all returned events.
- **Never omit a ⚠ FOUND_THREAD from Step 4** — the noise filter runs in code; present everything it surfaced.
