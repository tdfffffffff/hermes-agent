---
name: gmail-meeting-prep
version: 1.1.0
description: Pre-meeting brief — fetches Google Calendar events for today or upcoming days, identifies attendees, then searches Gmail for recent threads with those attendees to synthesise a one-paragraph context brief. Supports weekly overview mode.
tools:
  - execute_code
---

## Overview

Fetches calendar events from `hermes-gmail-mcp` and cross-references recent Gmail threads with attendees to give a concise pre-meeting brief. Handles Google sign-in inline.

**Critical: use `execute_code` for every MCP call. Never construct curl or shell commands.**

---

## The execute_code block — set MEETING_HINT and PHASE, then run

```python
import urllib.request, urllib.parse, json, re

MCP = "http://hermes-gmail-mcp:8084"

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

try:
    username = open("/opt/data/hermes-username").read().strip()
except Exception:
    username = "unknown"

# ── SET THESE BEFORE RUNNING ─────────────────────────────────────────────────
PHASE        = "calendar"   # calendar | email_context
MEETING_HINT = ""           # partial meeting title or attendee name; blank = all
DAYS         = 1            # days ahead to look (1 = today, 7 = full week)
WEEKLY_VIEW  = False        # set True when user asks for week/upcoming overview (skips email search)
WEEKS_BACK   = 0            # 0 = current/upcoming, 1 = last week, 2 = two weeks ago
DAYS_BACK    = 0            # exact days to look back (e.g. 3 = 3 days ago); overrides weeks_back when > 0
MONTHS_BACK  = 0            # e.g. 1 = last month (full calendar month); overrides days_back/weeks_back
MONTH_VIEW   = False        # set True for full current calendar month (1st to last day)
ATTENDEES    = []           # set from calendar output before running PHASE="email_context"
# ─────────────────────────────────────────────────────────────────────────────

# Auth check
auth = mcp_get("/auth/status", {"username": username})
if auth.get("status") != "complete":
    r = mcp_get("/auth/start", {"username": username})
    if r.get("status") == "already_authenticated":
        pass
    elif "auth_url" in r:
        print("Sign-in required to access your calendar.\n")
        print("Open this link in your browser to sign in:")
        print(f"  {r['auth_url']}\n")
        print("Come back and tell me when you're signed in.")
        raise SystemExit(0)
    else:
        print(f"Auth error: {r}")
        raise SystemExit(0)

auth = mcp_get("/auth/status", {"username": username})
if auth.get("status") != "complete":
    print("Not yet authenticated. Please try again.")
    raise SystemExit(0)

# ── PHASE: calendar ───────────────────────────────────────────────────────────
if PHASE == "calendar":
    import time as _time
    print(f"⚠ LIVE_CALENDAR_FETCH — timestamp {int(_time.time())} — do not use data from any prior turn")
    _cal_params = {"username": username, "days": DAYS, "top": 20}
    if WEEKLY_VIEW:
        _cal_params["week_view"] = "true"
    if WEEKS_BACK > 0:
        _cal_params["weeks_back"] = WEEKS_BACK
    if DAYS_BACK > 0:
        _cal_params["days_back"] = DAYS_BACK
    if MONTHS_BACK > 0:
        _cal_params["months_back"] = MONTHS_BACK
    if MONTH_VIEW:
        _cal_params["month_view"] = "true"
        _cal_params["top"] = 50
    r = mcp_get("/api/calendar", _cal_params)
    if "error" in r:
        print(f"Calendar error: {r['error']}")
        if r.get("detail"):
            print(f"Detail: {r['detail'][:300]}")
        raise SystemExit(0)

    events = r.get("value", [])
    if not events:
        _label = "today" if DAYS <= 1 else f"the next {DAYS} days"
        print(f"No meetings found for {_label}.")
        raise SystemExit(0)

    # Filter by hint if provided (only when not weekly view)
    if MEETING_HINT and not WEEKLY_VIEW:
        hint = MEETING_HINT.lower()
        matched = [e for e in events if
                   hint in e.get("summary", "").lower() or
                   any(hint in a.get("displayName", "").lower() or
                       hint in a.get("email", "").lower()
                       for a in e.get("attendees", []))]
        if matched:
            events = matched
        else:
            print(f"No meetings found matching '{MEETING_HINT}'. Here are all your meetings:\n")

    if MONTH_VIEW:
        _range_label = "THIS MONTH"
    elif MONTHS_BACK == 1:
        _range_label = "LAST MONTH"
    elif MONTHS_BACK > 1:
        _range_label = f"{MONTHS_BACK} MONTHS AGO"
    elif DAYS_BACK == 1:
        _range_label = "YESTERDAY"
    elif DAYS_BACK > 1:
        _range_label = f"{DAYS_BACK} DAYS AGO"
    elif WEEKS_BACK == 1:
        _range_label = "LAST WEEK"
    elif WEEKS_BACK > 1:
        _range_label = f"{WEEKS_BACK} WEEKS AGO"
    elif DAYS <= 1:
        _range_label = "TODAY"
    elif DAYS <= 7:
        _range_label = "THIS WEEK"
    else:
        _range_label = f"NEXT {DAYS} DAYS"
    print(f"MEETINGS {_range_label} ({len(events)} found)")
    print("=" * 60)

    if WEEKLY_VIEW:
        print("⚠ WEEKLY_OVERVIEW — show all meetings grouped by day. Do not ask for email search.")
        print()
    elif len(events) == 1:
        print("⚠ CONFIRM_MEETING — ask the user: 'Is this the meeting you'd like to prep for?' before proceeding.")
        print()
    elif len(events) > 1:
        print("⚠ DISAMBIGUATION_REQUIRED — multiple meetings found. List ALL of them below and ask the user which one to prep for. Do not proceed to email search until the user explicitly picks one.")
        print()

    _current_day = ""
    for i, e in enumerate(events, 1):
        start = str(e.get("start", ""))[:16].replace("T", " ")
        end   = str(e.get("end",   ""))[:16].replace("T", " ")
        _day  = start[:10]
        if WEEKLY_VIEW and _day != _current_day:
            _current_day = _day
            print(f"\n── {_day} ──────────────────────────────────────────")
        loc      = e.get("location", "")
        online   = e.get("online", False)
        platform = e.get("platform", "")
        join_url = e.get("join_url", "")
        desc  = e.get("description", "")
        atts  = e.get("attendees", [])
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

    if not WEEKLY_VIEW:
        print("⚠ EMAIL_SEARCH_TARGETS — set ATTENDEES from THIS list only (you are excluded):")
        _seen_att = set()
        for e in events:
            for a in e.get("attendees", []):
                if a.get("self"):
                    continue
                _key = a.get("email", "")
                if _key and _key not in _seen_att:
                    _seen_att.add(_key)
                    print(f"  {a.get('displayName', '')} | {_key}")
        if not _seen_att:
            print("  (no other attendees — skip email search)")

# ── PHASE: email_context ──────────────────────────────────────────────────────
elif PHASE == "email_context":
    if not ATTENDEES:
        print("ERROR: ATTENDEES is empty. Run PHASE='calendar' first and set ATTENDEES from the output.")
        raise SystemExit(0)

    emails_r = mcp_get("/api/emails", {"username": username, "days": 14, "top": 50})
    if "error" in emails_r:
        print(f"Email error: {emails_r['error']}")
        raise SystemExit(0)

    all_emails = emails_r.get("value", [])
    print("RECENT EMAIL CONTEXT")
    print("=" * 60)

    _noise_from = {"no-reply", "noreply", "mailer-daemon", "accounts.google.com",
                   "googlemail", "google.com"}

    def _is_noise(m):
        frm = m.get("from", "").lower()
        return any(n in frm for n in _noise_from)

    seen_ids  = set()
    found_any = False
    for name in ATTENDEES[:4]:
        needle = name.lower().strip()
        if not needle:
            continue
        related = [m for m in all_emails if
                   m.get("id") not in seen_ids and
                   not _is_noise(m) and (
                   needle in m.get("from",        "").lower() or
                   needle in m.get("to",          "").lower() or
                   needle in m.get("bodyPreview", "").lower())][:5]
        for m in related:
            seen_ids.add(m.get("id"))
            found_any = True
            date  = str(m.get("receivedDateTime", ""))[:10]
            subj  = m.get("subject", "(no subject)")
            frm   = m.get("from", "")
            # Fetch full email body — do not rely on bodyPreview snippet
            full_msg = mcp_get(f"/api/emails/{m['id']}", {"username": username})
            body = full_msg.get("body", m.get("bodyPreview", ""))[:2000]
            print(f"\n[{date}] {subj}")
            print(f"  From: {frm}")
            if body:
                print(f"  Body:\n{body}")

    if not found_any:
        print("No relevant email threads found with these attendees.")

    print("\n--- END OF EMAIL CONTEXT ---")
    print("Format the email findings and brief as instructed in Step 5.")

else:
    print(f"Unknown PHASE: {PHASE}. Valid: calendar | email_context")
```

---

## Workflow

**Step 1 — Auth:**
Run with `PHASE = "calendar"`. If output contains "Sign-in required", show the link verbatim, end your turn, and wait. When user confirms, re-run.

If re-run succeeds (no "Sign-in required" in output), show a welcome confirmation **before** proceeding to the calendar:

> ✅ Authentication complete! Your Gmail and Google Calendar are now connected and ready to use.
>
> Here's what I can do:
> - Check today's or upcoming meetings
> - Get a weekly overview of all your meetings
> - Filter by person or meeting title
> - Search recent email threads with your attendees
> - Synthesise a one-paragraph pre-meeting brief
>
> For example:
> - "Do I have any meetings today?"
> - "Brief me on my meetings for the week"
> - "Prep me for my 2pm meeting"
> - "What was last discussed with Wei Ming before our sync?"
>
> What would you like to do?

Then proceed to answer the user's original request.

**Step 2 — Detect request type:**

- If the user asks for a **specific meeting** (e.g. "prep me for my sync", "brief me on the 2pm"): set `DAYS = 1`, `WEEKLY_VIEW = False`, set `MEETING_HINT` if a title/person is mentioned.
- If the user asks for a **weekly or multi-day overview** (e.g. "brief me on my week", "what meetings do I have this week", "what's on my calendar Monday"): set `DAYS = 7`, `WEEKLY_VIEW = True`. Always re-run fresh — never reuse data from a prior turn.
- If the user asks for **next N days** (e.g. "next 3 days", "next 4 days", "next 2 days"): set `DAYS` to exactly the number they stated — never round up or substitute 7. Set `WEEKLY_VIEW = False`. `DAYS = 3` means 3 days from today; `DAYS = 4` means 4 days from today.
- If the user asks about **past meetings** (e.g. "remind me of last week's sprint", "what was discussed in Monday's meeting", "brief me on last week"): set `WEEKLY_VIEW = True`, `WEEKS_BACK = 1` for last week, `WEEKS_BACK = 2` for two weeks ago. For a specific past day, set `WEEKLY_VIEW = False`, `WEEKS_BACK = 1`, `DAYS = 1`, and `MEETING_HINT` to the meeting name.

**Step 3 — Show meetings:**
Always re-run the calendar code on each new user request — never reuse meeting data from a previous turn in the conversation.

Print the calendar output. Show **every meeting** returned by the code — never silently drop or skip any event.

**Weekly overview (WEEKLY_VIEW = True):**
- Show all meetings grouped by day as printed in the code output
- Do **not** ask for email search — present the full week schedule directly
- End with: *"Would you like me to prep for any of these in detail? I can search your email for context on any meeting — just say which one."*

**Past meeting recall (WEEKS_BACK >= 1):**
- Show meetings from the specified past week, grouped by day
- If the user asked about a specific past meeting, offer to search email threads from around that time for context
- Do not surface EMAIL_SEARCH_TARGETS automatically — only offer if the user wants a brief on a specific past meeting

**Single meeting prep (WEEKLY_VIEW = False):**
If the output contains **more than 1 meeting** (i.e. ≥ 2 events returned):
- Show all of them with their full details (time, attendees, description, attachments)
- Then ask: "Which meeting would you like to prep for?" — wait for the user to choose before proceeding
- **Never auto-select** a single meeting based on MEETING_HINT or prior context

For each meeting, present any attachments listed in the output:
- If attachments are present: for each one, infer what it likely is from its filename and MIME type and give a one-sentence description.
- If "Attachments: None": state clearly "No attachments for this meeting."

**Step 4 — Confirmation checkpoint (single meeting only):**
Read the `⚠ EMAIL_SEARCH_TARGETS` list from the code output — these are the only people to search email for. Ask:
> "Shall I search your Gmail for recent threads with [name from EMAIL_SEARCH_TARGETS] to build a pre-meeting brief?"

Do not use attendee names from the meeting display above — only the `⚠ EMAIL_SEARCH_TARGETS` list.

**Step 5 — Email context (single meeting only):**
Set `PHASE = "email_context"` and `ATTENDEES = ["Name1", "Name2", ...]` using **only the names from `⚠ EMAIL_SEARCH_TARGETS`** — never from the meeting attendees display. Re-run.

**Step 6 — Present email findings + brief:**
Use this exact structure:

---
**📅 [Meeting Title]** — [Day, Date] · [Start]–[End]
[Online (Platform) — join_url] or [Venue]
👥 [Attendee 1], [Attendee 2]

---
**📬 Recent Email Context**

**[Date] Subject line** *(from: Sender Name)*
- [Bullet point extracted verbatim from email body]
- [Next bullet point — include ALL items, never truncate]

*(repeat for each thread — omit threads with no meaningful content)*

If no relevant threads: *No relevant recent email threads found with these attendees.*

---
**📋 Pre-Meeting Brief**
[One short paragraph — what matters most going in: open items, unresolved asks, context the user needs. Conversational, not a bullet list.]

---

*Anything else you'd like to prepare? I can draft a pre-meeting email — just say the word.*

## Rules
- Use `execute_code` for all MCP calls.
- **Always confirm the attendee list with the user before searching email** — never skip the confirmation checkpoint.
- **ATTENDEES for email search must come from the `⚠ EMAIL_SEARCH_TARGETS` section only** — never from the meeting attendees display.
- If sign-in required: show the URL verbatim, end your turn, wait for confirmation before re-running.
- After successful auth (user just said "done" / "signed in"): always show the welcome confirmation before proceeding — never silently continue.
- Always show attachment status for every meeting: describe each attachment by name/type, or explicitly state "No attachments" — never silently omit this field.
- Show the event Description exactly as printed in the code output — preserve every line, bullet point, and note verbatim. Never summarise, reformat, or join lines with commas.
- Always re-run the calendar code at the start of each new prep request — the code prints a `⚠ LIVE_CALENDAR_FETCH` marker with a fresh timestamp. If that marker is not in the current turn's code output, the data is stale — re-run before answering.
- Never skip or silently drop a meeting from the output. If the code returns N events, show all N.
- If exactly 1 meeting is returned (single meeting mode), ask "Is this the meeting you'd like to prep for?" before proceeding — never auto-proceed even with 1 result.
- If ≥ 2 meetings are returned (single meeting mode), show all of them and ask the user which one to prep for. Never auto-select.
- Do not show attendees' email addresses to the user unless they specifically ask.
- Always use the Step 6 format template exactly: meeting header → email threads with bullet points → one-paragraph brief → closing line.
- Never collapse email content into one paragraph without first showing the per-thread bullet breakdown.
- **Include ALL bullet points from the email body verbatim — never truncate, summarise, or add "(preview cut off)" commentary.** The code fetches the full email body; present it completely.
- **Never use markdown headers (#, ##, ###) or bold (**text**) when presenting meeting listings.** Use plain text only — the code output is already formatted. Relay it without adding additional markdown styling.
- Omit threads that contain no meaningful content (automated notifications, one-word greetings, account setup emails).
- For weekly overview requests: set DAYS=7 and WEEKLY_VIEW=True. Never do email search in weekly mode — offer it as a follow-up.
- For past meeting queries: set WEEKS_BACK=1 (last week) or WEEKS_BACK=2 (two weeks ago). Use WEEKLY_VIEW=True for a full past week view, or WEEKLY_VIEW=False + DAYS=1 for a specific past day.
- **Never substitute DAYS=7 when the user says "next N days".** Use the exact N they stated. Do not round up.
- If the user asks for **this month / the month** (e.g. "brief me on my meetings for the month", "what meetings do I have this month", "show me July's meetings"): set `MONTH_VIEW = True`, `WEEKLY_VIEW = False`. This returns the full current calendar month from the 1st to the last day, including past meetings.
- If the user asks about **N months ago / last month** (e.g. "one month ago", "last month", "June meetings"): set `MONTHS_BACK = 1` (or the relevant number), `WEEKLY_VIEW = False`. The API returns the full calendar month.
- If the user asks about **N days ago** (e.g. "3 days ago", "what meetings did I have on Monday" when Monday was 2 days ago): set `DAYS_BACK` to the exact number of days back, `DAYS = 1`, `WEEKLY_VIEW = False`. Calculate DAYS_BACK from today — if today is Thursday and user says "Monday", DAYS_BACK = 3. Starts from any day including weekends.
---
name: gmail-meeting-prep
version: 1.1.0
description: Pre-meeting brief — fetches Google Calendar events for today or upcoming days, identifies attendees, then searches Gmail for recent threads with those attendees to synthesise a one-paragraph context brief. Supports weekly overview mode.
tools:
  - execute_code
---

## Overview

Fetches calendar events from `hermes-gmail-mcp` and cross-references recent Gmail threads with attendees to give a concise pre-meeting brief. Handles Google sign-in inline.

**Critical: use `execute_code` for every MCP call. Never construct curl or shell commands.**

---

## The execute_code block — set MEETING_HINT and PHASE, then run

```python
import urllib.request, urllib.parse, json, re

MCP = "http://hermes-gmail-mcp:8084"

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

try:
    username = open("/opt/data/hermes-username").read().strip()
except Exception:
    username = "unknown"

# ── SET THESE BEFORE RUNNING ─────────────────────────────────────────────────
PHASE        = "calendar"   # calendar | email_context
MEETING_HINT = ""           # partial meeting title or attendee name; blank = all
DAYS         = 1            # days ahead to look (1 = today, 7 = full week)
WEEKLY_VIEW  = False        # set True when user asks for week/upcoming overview (skips email search)
WEEKS_BACK   = 0            # 0 = current/upcoming, 1 = last week, 2 = two weeks ago
DAYS_BACK    = 0            # exact days to look back (e.g. 3 = 3 days ago); overrides weeks_back when > 0
MONTHS_BACK  = 0            # e.g. 1 = last month (full calendar month); overrides days_back/weeks_back
MONTH_VIEW   = False        # set True for full current calendar month (1st to last day)
ATTENDEES    = []           # set from calendar output before running PHASE="email_context"
# ─────────────────────────────────────────────────────────────────────────────

# Auth check
auth = mcp_get("/auth/status", {"username": username})
if auth.get("status") != "complete":
    r = mcp_get("/auth/start", {"username": username})
    if r.get("status") == "already_authenticated":
        pass
    elif "auth_url" in r:
        print("Sign-in required to access your calendar.\n")
        print("Open this link in your browser to sign in:")
        print(f"  {r['auth_url']}\n")
        print("Come back and tell me when you're signed in.")
        raise SystemExit(0)
    else:
        print(f"Auth error: {r}")
        raise SystemExit(0)

auth = mcp_get("/auth/status", {"username": username})
if auth.get("status") != "complete":
    print("Not yet authenticated. Please try again.")
    raise SystemExit(0)

# ── PHASE: calendar ───────────────────────────────────────────────────────────
if PHASE == "calendar":
    import time as _time
    print(f"⚠ LIVE_CALENDAR_FETCH — timestamp {int(_time.time())} — do not use data from any prior turn")
    _cal_params = {"username": username, "days": DAYS, "top": 20}
    if WEEKLY_VIEW:
        _cal_params["week_view"] = "true"
    if WEEKS_BACK > 0:
        _cal_params["weeks_back"] = WEEKS_BACK
    if DAYS_BACK > 0:
        _cal_params["days_back"] = DAYS_BACK
    if MONTHS_BACK > 0:
        _cal_params["months_back"] = MONTHS_BACK
    if MONTH_VIEW:
        _cal_params["month_view"] = "true"
        _cal_params["top"] = 50
    r = mcp_get("/api/calendar", _cal_params)
    if "error" in r:
        print(f"Calendar error: {r['error']}")
        if r.get("detail"):
            print(f"Detail: {r['detail'][:300]}")
        raise SystemExit(0)

    events = r.get("value", [])
    if not events:
        _label = "today" if DAYS <= 1 else f"the next {DAYS} days"
        print(f"No meetings found for {_label}.")
        raise SystemExit(0)

    # Filter by hint if provided (only when not weekly view)
    if MEETING_HINT and not WEEKLY_VIEW:
        hint = MEETING_HINT.lower()
        matched = [e for e in events if
                   hint in e.get("summary", "").lower() or
                   any(hint in a.get("displayName", "").lower() or
                       hint in a.get("email", "").lower()
                       for a in e.get("attendees", []))]
        if matched:
            events = matched
        else:
            print(f"No meetings found matching '{MEETING_HINT}'. Here are all your meetings:\n")

    if MONTH_VIEW:
        _range_label = "THIS MONTH"
    elif MONTHS_BACK == 1:
        _range_label = "LAST MONTH"
    elif MONTHS_BACK > 1:
        _range_label = f"{MONTHS_BACK} MONTHS AGO"
    elif DAYS_BACK == 1:
        _range_label = "YESTERDAY"
    elif DAYS_BACK > 1:
        _range_label = f"{DAYS_BACK} DAYS AGO"
    elif WEEKS_BACK == 1:
        _range_label = "LAST WEEK"
    elif WEEKS_BACK > 1:
        _range_label = f"{WEEKS_BACK} WEEKS AGO"
    elif DAYS <= 1:
        _range_label = "TODAY"
    elif DAYS <= 7:
        _range_label = "THIS WEEK"
    else:
        _range_label = f"NEXT {DAYS} DAYS"
    print(f"MEETINGS {_range_label} ({len(events)} found)")
    print("=" * 60)

    if WEEKLY_VIEW:
        print("⚠ WEEKLY_OVERVIEW — show all meetings grouped by day. Do not ask for email search.")
        print()
    elif len(events) == 1:
        print("⚠ CONFIRM_MEETING — ask the user: 'Is this the meeting you'd like to prep for?' before proceeding.")
        print()
    elif len(events) > 1:
        print("⚠ DISAMBIGUATION_REQUIRED — multiple meetings found. List ALL of them below and ask the user which one to prep for. Do not proceed to email search until the user explicitly picks one.")
        print()

    _current_day = ""
    for i, e in enumerate(events, 1):
        start = str(e.get("start", ""))[:16].replace("T", " ")
        end   = str(e.get("end",   ""))[:16].replace("T", " ")
        _day  = start[:10]
        if WEEKLY_VIEW and _day != _current_day:
            _current_day = _day
            print(f"\n── {_day} ──────────────────────────────────────────")
        loc      = e.get("location", "")
        online   = e.get("online", False)
        platform = e.get("platform", "")
        join_url = e.get("join_url", "")
        desc  = e.get("description", "")
        atts  = e.get("attendees", [])
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

    if not WEEKLY_VIEW:
        print("⚠ EMAIL_SEARCH_TARGETS — set ATTENDEES from THIS list only (you are excluded):")
        _seen_att = set()
        for e in events:
            for a in e.get("attendees", []):
                if a.get("self"):
                    continue
                _key = a.get("email", "")
                if _key and _key not in _seen_att:
                    _seen_att.add(_key)
                    print(f"  {a.get('displayName', '')} | {_key}")
        if not _seen_att:
            print("  (no other attendees — skip email search)")

# ── PHASE: email_context ──────────────────────────────────────────────────────
elif PHASE == "email_context":
    if not ATTENDEES:
        print("ERROR: ATTENDEES is empty. Run PHASE='calendar' first and set ATTENDEES from the output.")
        raise SystemExit(0)

    emails_r = mcp_get("/api/emails", {"username": username, "days": 14, "top": 50})
    if "error" in emails_r:
        print(f"Email error: {emails_r['error']}")
        raise SystemExit(0)

    all_emails = emails_r.get("value", [])
    print("RECENT EMAIL CONTEXT")
    print("=" * 60)

    _noise_from = {"no-reply", "noreply", "mailer-daemon", "accounts.google.com",
                   "googlemail", "google.com"}

    def _is_noise(m):
        frm = m.get("from", "").lower()
        return any(n in frm for n in _noise_from)

    seen_ids  = set()
    found_any = False
    for name in ATTENDEES[:4]:
        needle = name.lower().strip()
        if not needle:
            continue
        related = [m for m in all_emails if
                   m.get("id") not in seen_ids and
                   not _is_noise(m) and (
                   needle in m.get("from",        "").lower() or
                   needle in m.get("to",          "").lower() or
                   needle in m.get("bodyPreview", "").lower())][:5]
        for m in related:
            seen_ids.add(m.get("id"))
            found_any = True
            date  = str(m.get("receivedDateTime", ""))[:10]
            subj  = m.get("subject", "(no subject)")
            frm   = m.get("from", "")
            # Fetch full email body — do not rely on bodyPreview snippet
            full_msg = mcp_get(f"/api/emails/{m['id']}", {"username": username})
            body = full_msg.get("body", m.get("bodyPreview", ""))[:2000]
            print(f"\n[{date}] {subj}")
            print(f"  From: {frm}")
            if body:
                print(f"  Body:\n{body}")

    if not found_any:
        print("No relevant email threads found with these attendees.")

    print("\n--- END OF EMAIL CONTEXT ---")
    print("Format the email findings and brief as instructed in Step 5.")

else:
    print(f"Unknown PHASE: {PHASE}. Valid: calendar | email_context")
```

---

## Workflow

**Step 1 — Auth:**
Run with `PHASE = "calendar"`. If output contains "Sign-in required", show the link verbatim, end your turn, and wait. When user confirms, re-run.

If re-run succeeds (no "Sign-in required" in output), show a welcome confirmation **before** proceeding to the calendar:

> ✅ Authentication complete! Your Gmail and Google Calendar are now connected and ready to use.
>
> Here's what I can do:
> - Check today's or upcoming meetings
> - Get a weekly overview of all your meetings
> - Filter by person or meeting title
> - Search recent email threads with your attendees
> - Synthesise a one-paragraph pre-meeting brief
>
> For example:
> - "Do I have any meetings today?"
> - "Brief me on my meetings for the week"
> - "Prep me for my 2pm meeting"
> - "What was last discussed with Wei Ming before our sync?"
>
> What would you like to do?

Then proceed to answer the user's original request.

**Step 2 — Detect request type:**

- If the user asks for a **specific meeting** (e.g. "prep me for my sync", "brief me on the 2pm"): set `DAYS = 1`, `WEEKLY_VIEW = False`, set `MEETING_HINT` if a title/person is mentioned.
- If the user asks for a **weekly or multi-day overview** (e.g. "brief me on my week", "what meetings do I have this week", "what's on my calendar Monday"): set `DAYS = 7`, `WEEKLY_VIEW = True`. Always re-run fresh — never reuse data from a prior turn.
- If the user asks for **next N days** (e.g. "next 3 days", "next 4 days", "next 2 days"): set `DAYS` to exactly the number they stated — never round up or substitute 7. Set `WEEKLY_VIEW = False`. `DAYS = 3` means 3 days from today; `DAYS = 4` means 4 days from today.
- If the user asks about **past meetings** (e.g. "remind me of last week's sprint", "what was discussed in Monday's meeting", "brief me on last week"): set `WEEKLY_VIEW = True`, `WEEKS_BACK = 1` for last week, `WEEKS_BACK = 2` for two weeks ago. For a specific past day, set `WEEKLY_VIEW = False`, `WEEKS_BACK = 1`, `DAYS = 1`, and `MEETING_HINT` to the meeting name.

**Step 3 — Show meetings:**
Always re-run the calendar code on each new user request — never reuse meeting data from a previous turn in the conversation.

Print the calendar output. Show **every meeting** returned by the code — never silently drop or skip any event.

**Weekly overview (WEEKLY_VIEW = True):**
- Show all meetings grouped by day as printed in the code output
- Do **not** ask for email search — present the full week schedule directly
- End with: *"Would you like me to prep for any of these in detail? I can search your email for context on any meeting — just say which one."*

**Past meeting recall (WEEKS_BACK >= 1):**
- Show meetings from the specified past week, grouped by day
- If the user asked about a specific past meeting, offer to search email threads from around that time for context
- Do not surface EMAIL_SEARCH_TARGETS automatically — only offer if the user wants a brief on a specific past meeting

**Single meeting prep (WEEKLY_VIEW = False):**
If the output contains **more than 1 meeting** (i.e. ≥ 2 events returned):
- Show all of them with their full details (time, attendees, description, attachments)
- Then ask: "Which meeting would you like to prep for?" — wait for the user to choose before proceeding
- **Never auto-select** a single meeting based on MEETING_HINT or prior context

For each meeting, present any attachments listed in the output:
- If attachments are present: for each one, infer what it likely is from its filename and MIME type and give a one-sentence description.
- If "Attachments: None": state clearly "No attachments for this meeting."

**Step 4 — Confirmation checkpoint (single meeting only):**
Read the `⚠ EMAIL_SEARCH_TARGETS` list from the code output — these are the only people to search email for. Ask:
> "Shall I search your Gmail for recent threads with [name from EMAIL_SEARCH_TARGETS] to build a pre-meeting brief?"

Do not use attendee names from the meeting display above — only the `⚠ EMAIL_SEARCH_TARGETS` list.

**Step 5 — Email context (single meeting only):**
Set `PHASE = "email_context"` and `ATTENDEES = ["Name1", "Name2", ...]` using **only the names from `⚠ EMAIL_SEARCH_TARGETS`** — never from the meeting attendees display. Re-run.

**Step 6 — Present email findings + brief:**
Use this exact structure:

---
**📅 [Meeting Title]** — [Day, Date] · [Start]–[End]
[Online (Platform) — join_url] or [Venue]
👥 [Attendee 1], [Attendee 2]

---
**📬 Recent Email Context**

**[Date] Subject line** *(from: Sender Name)*
- [Bullet point extracted verbatim from email body]
- [Next bullet point — include ALL items, never truncate]

*(repeat for each thread — omit threads with no meaningful content)*

If no relevant threads: *No relevant recent email threads found with these attendees.*

---
**📋 Pre-Meeting Brief**
[One short paragraph — what matters most going in: open items, unresolved asks, context the user needs. Conversational, not a bullet list.]

---

*Anything else you'd like to prepare? I can draft a pre-meeting email — just say the word.*

## Rules
- Use `execute_code` for all MCP calls.
- **Always confirm the attendee list with the user before searching email** — never skip the confirmation checkpoint.
- **ATTENDEES for email search must come from the `⚠ EMAIL_SEARCH_TARGETS` section only** — never from the meeting attendees display.
- If sign-in required: show the URL verbatim, end your turn, wait for confirmation before re-running.
- After successful auth (user just said "done" / "signed in"): always show the welcome confirmation before proceeding — never silently continue.
- Always show attachment status for every meeting: describe each attachment by name/type, or explicitly state "No attachments" — never silently omit this field.
- Show the event Description exactly as printed in the code output — preserve every line, bullet point, and note verbatim. Never summarise, reformat, or join lines with commas.
- Always re-run the calendar code at the start of each new prep request — the code prints a `⚠ LIVE_CALENDAR_FETCH` marker with a fresh timestamp. If that marker is not in the current turn's code output, the data is stale — re-run before answering.
- Never skip or silently drop a meeting from the output. If the code returns N events, show all N.
- If exactly 1 meeting is returned (single meeting mode), ask "Is this the meeting you'd like to prep for?" before proceeding — never auto-proceed even with 1 result.
- If ≥ 2 meetings are returned (single meeting mode), show all of them and ask the user which one to prep for. Never auto-select.
- Do not show attendees' email addresses to the user unless they specifically ask.
- Always use the Step 6 format template exactly: meeting header → email threads with bullet points → one-paragraph brief → closing line.
- Never collapse email content into one paragraph without first showing the per-thread bullet breakdown.
- **Include ALL bullet points from the email body verbatim — never truncate, summarise, or add "(preview cut off)" commentary.** The code fetches the full email body; present it completely.
- **Never use markdown headers (#, ##, ###) or bold (**text**) when presenting meeting listings.** Use plain text only — the code output is already formatted. Relay it without adding additional markdown styling.
- Omit threads that contain no meaningful content (automated notifications, one-word greetings, account setup emails).
- For weekly overview requests: set DAYS=7 and WEEKLY_VIEW=True. Never do email search in weekly mode — offer it as a follow-up.
- For past meeting queries: set WEEKS_BACK=1 (last week) or WEEKS_BACK=2 (two weeks ago). Use WEEKLY_VIEW=True for a full past week view, or WEEKLY_VIEW=False + DAYS=1 for a specific past day.
- **Never substitute DAYS=7 when the user says "next N days".** Use the exact N they stated. Do not round up.
- If the user asks for **this month / the month** (e.g. "brief me on my meetings for the month", "what meetings do I have this month", "show me July's meetings"): set `MONTH_VIEW = True`, `WEEKLY_VIEW = False`. This returns the full current calendar month from the 1st to the last day, including past meetings.
- If the user asks about **N months ago / last month** (e.g. "one month ago", "last month", "June meetings"): set `MONTHS_BACK = 1` (or the relevant number), `WEEKLY_VIEW = False`. The API returns the full calendar month.
- If the user asks about **N days ago** (e.g. "3 days ago", "what meetings did I have on Monday" when Monday was 2 days ago): set `DAYS_BACK` to the exact number of days back, `DAYS = 1`, `WEEKLY_VIEW = False`. Calculate DAYS_BACK from today — if today is Thursday and user says "Monday", DAYS_BACK = 3. Starts from any day including weekends.
