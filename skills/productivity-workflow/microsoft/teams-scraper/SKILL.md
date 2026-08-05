---
name: teams-scraper
version: 4.0.0
description: Requirements gathering and meeting notes from Teams chats. Reads Teams chat history, extracts requirements/decisions/action items, then generates structured notes or a PPTX slide deck. Signs in automatically if not yet authenticated.
tools:
  - execute_code
  - write_file
---

## Overview

Reads Teams group chat or DM history via `hermes-graph-mcp`, extracts structured information (requirements, decisions, action items, open questions), and produces meeting notes or a PPTX slide deck. Handles Microsoft sign-in inline — no need to run a separate auth skill first.

**Critical: use `execute_code` for every MCP call. Never construct curl or shell commands.**

---

## The single execute_code block — set MODE then run

```python
import urllib.request, urllib.parse, json, re, os, sys
from datetime import datetime

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
        return {"error": f"HTTP {e.code}", "detail": body[:600]}
    except Exception as e:
        return {"error": str(e)}

def strip_html(text):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', text or '')).strip()

try:
    username = open("/opt/data/hermes-username").read().strip()
except Exception:
    username = "unknown"

# ── SET THESE BEFORE RUNNING ────────────────────────────────────────────────
MODE        = "list_chats"   # list_chats | read_chat | gen_pptx
PERSON_NAME = ""             # list_chats: partial name to find the right chat
CHAT_ID     = ""             # read_chat / gen_pptx: set from list_chats output
TOP         = 100            # read_chat: max messages to fetch

# gen_pptx — fill these from the chat content before running
PPTX_TITLE    = "Meeting Notes"
PPTX_SUBTITLE = "Generated from Teams chat"
PPTX_SLIDES   = [
    # ("Slide Title", ["bullet 1", "bullet 2"]),
]
PPTX_SLUG     = "teams-notes"
# ───────────────────────────────────────────────────────────────────────────

# Auth check — start sign-in flow inline if not authenticated
auth = mcp_get("/auth/status", {"username": username})
if auth.get("status") != "complete":
    r = mcp_get("/auth/start", {"username": username})
    if r.get("status") == "already_authenticated":
        pass
    elif "user_code" in r:
        print("Sign-in required to access Teams.")
        print()
        print(f"1. Open: {r['verification_uri']}")
        print(f"2. Enter code: {r['user_code']}")
        print("3. Sign in with your Microsoft account and complete MFA")
        print()
        mins = r.get("expires_in", 900) // 60
        print(f"Code valid for {mins} minutes.")
        print("Once signed in, tell me and I'll list your chats.")
        raise SystemExit(0)
    else:
        print(f"Auth error: {r}")
        raise SystemExit(0)

auth = mcp_get("/auth/status", {"username": username})
if auth.get("status") != "complete":
    print("Authentication not yet confirmed. Please try again in a moment.")
    raise SystemExit(0)

def _teams_error(r):
    detail = r.get("detail", "")
    err    = r.get("error", "")
    if "AADSTS500014" in detail or "disabled" in detail.lower():
        print("The authentication token is valid but we're hitting a service principal issue on the Microsoft Graph side:")
        print()
        print("  AADSTS500014: The service principal for resource '<your-azure-app-id>' is disabled.")
        print()
        print("This means the Azure AD app registration used to call the Teams API has been disabled.")
        print("This is an infrastructure-level issue, not a problem with your login.")
        print()
        print("To unblock: contact your IT/Azure admin and ask them to re-enable the service principal")
        print("for app ID <your-azure-app-id> in Azure Active Directory > Enterprise Applications.")
    elif "401" in err:
        print("Authentication expired. Ask me to sign in again.")
    else:
        print(f"Error: {err}")
        if detail:
            print(f"Detail: {detail[:300]}")

if MODE == "list_chats":
    r = mcp_get("/api/chats", {"username": username, "top": 30})
    if "error" in r:
        _teams_error(r)
        raise SystemExit(0)

    chats = r.get("value", [])
    if not chats:
        print("No Teams chats found.")
        raise SystemExit(0)

    hint = PERSON_NAME.lower()
    if hint:
        matched = [c for c in chats if any(
            hint in m.get("displayName", "").lower()
            for m in c.get("members", [])
        )]
        if not matched:
            matched = chats
            print(f"No chats found with '{PERSON_NAME}'. Showing all chats:\n")
    else:
        matched = chats

    for c in matched[:15]:
        topic   = c.get("topic") or "(no topic)"
        updated = str(c.get("lastUpdatedDateTime", ""))[:10]
        members = [m.get("displayName", "?") for m in c.get("members", [])[:5]]
        ctype   = c.get("chatType", "")
        print(f"{updated}  [{ctype}]  {topic}")
        print(f"  Members: {', '.join(members)}")
        print(f"  ID: {c['id']}")
        print()
    print("Copy the ID of the chat you want to read and set it as CHAT_ID with MODE='read_chat'.")

elif MODE == "read_chat":
    if not CHAT_ID:
        print("ERROR: CHAT_ID is empty. Run MODE='list_chats' first and paste the chat ID.")
        raise SystemExit(0)

    r = mcp_get(f"/api/chats/{CHAT_ID}/messages", {"username": username, "top": TOP})
    if "error" in r:
        _teams_error(r)
        raise SystemExit(0)

    msgs = r.get("value", [])
    convos = []
    for m in reversed(msgs):
        if m.get("messageType") != "message":
            continue
        sender = m.get("from", {}).get("user", {}).get("displayName", "Unknown")
        body   = strip_html(m.get("body", {}).get("content", ""))
        dt     = str(m.get("createdDateTime", ""))[:16].replace("T", " ")
        if body:
            convos.append({"sender": sender, "time": dt, "body": body})

    if not convos:
        print("No messages found in this chat.")
        raise SystemExit(0)

    print(f"TEAMS CHAT TRANSCRIPT ({len(convos)} messages)")
    print("=" * 60)
    print()
    for c in convos:
        print(f"[{c['time']}] {c['sender']}:")
        print(f"  {c['body'][:300]}")
        print()
    print("--- END OF TRANSCRIPT ---")
    print(f"\nTotal: {len(convos)} messages")

elif MODE == "gen_pptx":
    if not PPTX_SLIDES:
        print("ERROR: PPTX_SLIDES is empty. Read the chat first, then fill PPTX_SLIDES from the content.")
        raise SystemExit(0)

    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "python-pptx", "-q"])
    from pptx import Presentation
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width  = Inches(13.33)
    prs.slide_height = Inches(7.5)

    # Title slide
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = PPTX_TITLE
    slide.placeholders[1].text = PPTX_SUBTITLE

    # Content slides
    for slide_title, bullets in PPTX_SLIDES:
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = slide_title
        tf = slide.placeholders[1].text_frame
        tf.clear()
        for i, b in enumerate(bullets):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = b
            p.level = 0

    date_str = datetime.now().strftime("%Y-%m-%d")
    out = f"/opt/outputs/{PPTX_SLUG}-{date_str}.pptx"
    os.makedirs("/opt/outputs", exist_ok=True)
    prs.save(out)
    print(f"Saved: {out}")
    print("Download via the /outputs/ endpoint or SCP.")

else:
    print(f"Unknown MODE: {MODE}. Valid: list_chats | read_chat | gen_pptx")
```

---

## Workflow

**Step 1 — Auth:**
Run with `MODE = "list_chats"`. If not authenticated, a sign-in code will print. Show it verbatim, end your turn, and wait. When the user confirms they've signed in, re-run.

**Step 2 — Find the chat:**
Set `PERSON_NAME` to narrow results. Show the list and ask which chat to read.

**Step 3 — Read the transcript:**
Set `CHAT_ID` and run with `MODE = "read_chat"`. Print the transcript.

**Step 4 — Extract structured info:**
After the transcript, synthesise the following and write them to a markdown file using `write_file` at `/opt/outputs/teams-notes-<slug>-<date>.md`:

- **Requirements** — things the team said need to be built, changed, or done
- **Decisions** — things that were agreed on
- **Action Items** — specific tasks with owners and due dates (if mentioned)
- **Open Questions** — unresolved issues or pending decisions

**Step 5 — Output format:**
Ask the user: "Would you like a PPTX presentation as well?"

- If yes: Fill `PPTX_TITLE`, `PPTX_SUBTITLE`, `PPTX_SLIDES` from the extracted content above. **Show the outline to the user first for approval**, then run with `MODE = "gen_pptx"`.

## Rules
- Use `execute_code` for all MCP calls. No curl or shell.
- If the block shows a sign-in code: show it verbatim, end your turn, wait for confirmation before re-running.
- If AADSTS500014: print the full error message with the service principal explanation. Known infrastructure limitation.
- Never read DMs without the user explicitly requesting it.
- Always save the markdown output to `/opt/outputs/` with `write_file`.
- Show the PPTX slide outline to the user for approval before running `gen_pptx`.
