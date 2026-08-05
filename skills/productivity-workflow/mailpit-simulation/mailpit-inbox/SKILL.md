---
name: mailpit-inbox
version: 1.0.0
description: On-prem email inbox (Mailpit simulation) — triage, read, summarise, draft, send, star. Simulates an on-prem Outlook environment with no internet connection required.
tools:
  - execute_code
---

## Overview

Connects to `hermes-mailpit-mcp` at `http://hermes-mailpit-mcp:8085`. **No sign-in required** — this simulates an on-prem email environment (Mailpit), representing an on-prem Outlook/Exchange setup without internet access.

> **⛔ BEFORE YOU WRITE A SINGLE WORD TO THE USER — read these rules:**
>
> **Rule 1 — Attachments work. The files ARE accessible.**
> When OpenWebUI shows "Retrieved N sources" with filenames, those files are uploaded and stored in OpenWebUI. The `hermes-wrapper` bridge retrieves their binary automatically — you do not need local filesystem paths.
>
> **⚠ ATTACHMENT_SCOPE — set ATTACHMENTS BEFORE running any code:**
> - User says "this file" / "attach this" / "only this" → ATTACHMENTS = [the filename shown inline in the user's message, e.g. `the_deep_sea_large.pptx` shown above their text]. There will always be exactly one — use it.
> - User names a specific file by name → ATTACHMENTS = [that filename]
> - User says "attach all" / "attach everything" → ATTACHMENTS = all filenames in Retrieved sources
> - Do NOT include files from earlier messages unless the user explicitly names them
>
> **The correct filename is always visible inline in the user's message (shown as a chip above their text). Read it directly — never ask.**
>
> **Rule 2 — Never ask for subject or body separately.** Infer the subject from context.
>
> **Rule 3 — When sending/drafting with attachments:** run `stage_send` immediately with `ATTACHMENT_STYLE` blank. The code checks size first, then asks A/B if needed.
>
> **Rule 4 — File size checking is done by the code, not by you.**

**Critical rules:**
- Use `execute_code` for every MCP call — never curl or shell
- **Never ask for a subject line — always infer it from the body or filenames**
- **Never ask "shall I send?" — the draft card is the only confirmation**
- Nothing is sent until the user explicitly types SEND

---

## execute_code block — set MODE and variables, then run

```python
import urllib.request, urllib.parse, json, urllib.error, re

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

def mcp_post(path, params, body):
    url = MCP + path
    if params:
        url += "?" + urllib.parse.urlencode({k: str(v) for k, v in params.items()})
    data = json.dumps(body).encode()
    req  = urllib.request.Request(url, data=data,
           headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
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
MODE        = "list_emails"   # list_emails | read_email | stage_send | confirm_send
                              # draft_new | draft_reply | list_drafts | send_draft | delete_draft | flag_email
DAYS        = 7               # list_emails: days back (0 = no filter)
TOP         = 20              # max results
EMAIL_ID    = ""              # read_email / draft_reply / flag_email
TO          = ""              # stage_send / draft_new
SUBJECT     = ""              # stage_send / draft_new — ALWAYS infer, never leave blank
BODY        = ""              # stage_send / draft_new / draft_reply
PENDING_ID  = ""              # confirm_send
DRAFT_ID    = ""              # send_draft / delete_draft
STARRED          = True       # flag_email
ATTACHMENTS      = []         # filenames uploaded this session e.g. ["report.pdf"]
ATTACHMENT_STYLE = ""         # stage_send — "A" or "B" when ATTACHMENTS non-empty
# ─────────────────────────────────────────────────────────────────────────────

# No auth needed for Mailpit
print("📬 Connected to on-prem mail (Mailpit simulation)")

# ── Modes ─────────────────────────────────────────────────────────────────────

if MODE == "list_emails":
    r = mcp_get("/api/emails", {"days": DAYS, "top": TOP})
    if "error" in r:
        print(f"Error: {r['error']}")
        raise SystemExit(0)
    msgs = r.get("value", [])
    if not msgs:
        print(f"No emails in the last {DAYS} days.")
        raise SystemExit(0)
    print(f"INBOX — {len(msgs)} emails")
    for i, m in enumerate(msgs, 1):
        unread = " [UNREAD]" if not m.get("isRead", True) else ""
        sender = m.get("from") or "(unknown)"
        print(f"\n{i}. {sender}{unread}")
        print(f"   Subject : {m.get('subject','(no subject)')}")
        print(f"   Preview : {m.get('bodyPreview','')[:100]}")
        print(f"   Date    : {m.get('receivedDateTime','')[:16]}")
        print(f"   ID      : {m['id']}")

elif MODE == "read_email":
    if not EMAIL_ID:
        print("ERROR: EMAIL_ID is required.")
        raise SystemExit(0)
    r = mcp_get(f"/api/emails/{EMAIL_ID}")
    if "error" in r:
        print(f"Error: {r['error']}")
        raise SystemExit(0)
    print(f"From    : {r.get('from','')}")
    print(f"To      : {r.get('to','')}")
    print(f"Subject : {r.get('subject','')}")
    print(f"Date    : {r.get('date','')}")
    print()
    print(r.get("body","")[:3000])

elif MODE == "stage_send":
    if ATTACHMENTS:
        try:
            _pf_key = open("/root/.hermes/.api-key").read().strip()
        except Exception:
            _pf_key = ""
        _oversized = []
        for _pf_fname in ATTACHMENTS:
            try:
                _pf_url = f"http://hermes-wrapper:5000/v1/uploads?filename={urllib.parse.quote(_pf_fname)}"
                _pf_req = urllib.request.Request(_pf_url, headers={"Authorization": f"Bearer {_pf_key}"})
                with urllib.request.urlopen(_pf_req, timeout=30) as _pf_resp:
                    _pf_att = json.loads(_pf_resp.read())
                _pf_mb = len(_pf_att.get("data", "")) * 3 / 4 / 1_048_576
                if _pf_mb > 20:
                    _oversized.append((_pf_fname, round(_pf_mb, 1)))
            except Exception:
                pass
        if _oversized:
            print("SIZE_LIMIT_EXCEEDED")
            for _pf_fn, _pf_sz in _oversized:
                print(f"  ❌ {_pf_fn}: {_pf_sz} MB — exceeds the 20 MB limit")
            print("\nOptions (reply with the keyword):")
            print("  SEND_BODY   — send email noting file will be shared another way")
            print("  EXPLAIN     — send with a summary of the file contents instead")
            print("  CANCEL      — abandon this send")
            raise SystemExit(0)
    if ATTACHMENTS and ATTACHMENT_STYLE not in ("A", "B"):
        print("⚠ ATTACHMENT_STYLE_REQUIRED — STOP. Do not proceed. Ask the user:")
        print("  This email has an attachment. Would you like the body to be:")
        print("  A) Simple — 'Please find attached [filename] as requested.'")
        print("  B) With context — a brief summary of the document contents")
        print("Set ATTACHMENT_STYLE to 'A' or 'B' based on their answer, then re-run stage_send.")
        raise SystemExit(0)
    if not TO or not SUBJECT or not BODY:
        print("ERROR: TO, SUBJECT, and BODY are all required.")
        raise SystemExit(0)
    try:
        user_key = open("/root/.hermes/.api-key").read().strip()
    except Exception:
        user_key = ""
    attachments_data = []
    for fname in ATTACHMENTS:
        try:
            url = f"http://hermes-wrapper:5000/v1/uploads?filename={urllib.parse.quote(fname)}"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {user_key}"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                att = json.loads(resp.read())
            size_mb = len(att.get("data","")) * 3 / 4 / 1_048_576
            if size_mb > 20:
                print(f"SIZE_LIMIT_EXCEEDED")
                print(f"  ❌ {fname}: {size_mb:.1f} MB — exceeds the 20 MB limit")
                print("\nOptions (reply with the keyword):")
                print("  SEND_BODY   — send email noting file will be shared another way")
                print("  EXPLAIN     — send with a summary of the file contents instead")
                print("  CANCEL      — abandon this send")
                raise SystemExit(0)
            attachments_data.append(att)
            print(f"✅ Attachment ready: {fname} ({size_mb:.2f} MB)")
        except Exception as e:
            print(f"❌ Attachment failed: {fname} — {e}")
    BODY = re.sub(r'\[\d+\]', '', BODY).strip()
    r = mcp_post("/api/emails/stage-send", {},
                 {"to": TO, "subject": SUBJECT, "body": BODY,
                  "attachments": attachments_data})
    if "error" in r:
        print(f"Error staging email: {r['error']}")
        raise SystemExit(0)
    p = r.get("preview", {})
    print(f"⚠ STAGE_SEND_RESULT — draft card may now be shown to the user")
    print(f"PENDING_ID: {r['pending_id']}\n")
    print(f"**To:** {p.get('to','')}")
    print(f"**Subject:** {p.get('subject','')}")
    if p.get("attachments"):
        print(f"**Attachments:** {', '.join(p['attachments'])}")
    print()
    print(p.get("body",""))

elif MODE == "confirm_send":
    if not PENDING_ID:
        print("ERROR: PENDING_ID is required.")
        raise SystemExit(0)
    r = mcp_post("/api/emails/confirm-send", {"pending_id": PENDING_ID}, {})
    if "error" in r:
        print(f"Send failed: {r['error']}")
    else:
        print(f"✅ Email sent via on-prem mail server.")

elif MODE == "draft_new":
    if not TO or not SUBJECT or not BODY:
        print("ERROR: TO, SUBJECT, and BODY are all required.")
        raise SystemExit(0)
    try:
        user_key = open("/root/.hermes/.api-key").read().strip()
    except Exception:
        user_key = ""
    attachments_data = []
    for fname in ATTACHMENTS:
        try:
            url = f"http://hermes-wrapper:5000/v1/uploads?filename={urllib.parse.quote(fname)}"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {user_key}"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                att = json.loads(resp.read())
            attachments_data.append(att)
        except Exception as e:
            print(f"❌ Attachment failed: {fname} — {e}")
    r = mcp_post("/api/emails/draft-new", {},
                 {"to": TO, "subject": SUBJECT, "body": BODY,
                  "attachments": attachments_data})
    if "error" in r:
        print(f"Draft failed: {r['error']}")
    else:
        print(f"💾 Draft saved.")

elif MODE == "draft_reply":
    if not EMAIL_ID or not BODY:
        print("ERROR: EMAIL_ID and BODY are required.")
        raise SystemExit(0)
    r = mcp_post(f"/api/emails/{EMAIL_ID}/draft-reply", {}, {"body": BODY})
    if "error" in r:
        print(f"Draft failed: {r['error']}")
    else:
        print(f"💾 Reply draft saved.")

elif MODE == "list_drafts":
    r = mcp_get("/api/drafts", {"top": TOP})
    if "error" in r:
        print(f"Error: {r['error']}")
        raise SystemExit(0)
    drafts = r.get("drafts", [])
    if not drafts:
        print("No drafts found.")
        raise SystemExit(0)
    print(f"Drafts ({len(drafts)})")
    for i, d in enumerate(drafts, 1):
        print(f"\n{i}. To: {d.get('to','')}")
        print(f"   Subject  : {d.get('subject','(no subject)')}")
        print(f"   Preview  : {d.get('snippet','')[:100]}")
        print(f"   DRAFT_ID : {d['draft_id']}")

elif MODE == "send_draft":
    if not DRAFT_ID:
        print("ERROR: DRAFT_ID is required.")
        raise SystemExit(0)
    r = mcp_post(f"/api/drafts/{DRAFT_ID}/send", {}, {})
    if "error" in r:
        if "404" in str(r.get("error","")) or "404" in str(r.get("detail","")):
            print(f"Draft ID {DRAFT_ID} not found. Refreshing draft list...")
            dl = mcp_get("/api/drafts", {"top": 20})
            drafts = dl.get("drafts", [])
            if not drafts:
                print("No drafts found. The draft may have already been sent.")
            elif len(drafts) == 1:
                new_id = drafts[0]["draft_id"]
                print(f"Found 1 draft — retrying with DRAFT_ID: {new_id}")
                r2 = mcp_post(f"/api/drafts/{new_id}/send", {}, {})
                if "error" in r2:
                    print(f"Send failed: {r2['error']}")
                else:
                    print(f"✅ Draft sent.")
            else:
                print(f"Multiple drafts found ({len(drafts)}). Please specify:")
                for i, d in enumerate(drafts, 1):
                    print(f"\n{i}. To: {d.get('to','')}  Subject: {d.get('subject','')}  DRAFT_ID: {d['draft_id']}")
        else:
            print(f"Send failed: {r['error']}")
    else:
        print(f"✅ Draft sent.")

elif MODE == "delete_draft":
    if not DRAFT_ID:
        print("ERROR: DRAFT_ID is required.")
        raise SystemExit(0)
    url = f"{MCP}/api/drafts/{DRAFT_ID}"
    req = urllib.request.Request(url, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print("🗑️ Draft deleted.")
    except Exception as e:
        print(f"Delete failed: {e}")

elif MODE == "flag_email":
    if not EMAIL_ID:
        print("ERROR: EMAIL_ID is required.")
        raise SystemExit(0)
    r = mcp_post(f"/api/emails/{EMAIL_ID}/flag",
                 {"starred": STARRED}, {})
    if "error" in r:
        print(f"Flag failed: {r['error']}")
    else:
        print(f"✅ Email {'starred' if STARRED else 'unstarred'}.")

else:
    print(f"Unknown MODE: {MODE}")
```

---

## Workflow

**This skill uses the on-prem Mailpit simulation — no internet or Google sign-in required.**

**Triage (list_emails):**
Run `list_emails`. Present results as a numbered list — bold sender, italic subject, one-line classification.

**Reading (read_email):**
Match sender from the list output. Show body in a quote block with From/To/Subject/Date header.

**Composing and sending — STRICT sequence:**

1. Check for attachments first. If present, run `stage_send` immediately with `ATTACHMENT_STYLE` blank.
   - `SIZE_LIMIT_EXCEEDED` → relay options (`SEND_BODY` / `EXPLAIN` / `CANCEL`), wait for reply
   - `⚠ ATTACHMENT_STYLE_REQUIRED` → ask A/B, re-run with style set
2. Infer subject from body/filenames — never ask.
3. Compose body. Run `stage_send`.
4. Show draft card:
   > 📧 **Draft ready**
   > **To:** ... **Subject:** ... **Attachments:** ...
   > > [body]
   >
   > Type **SEND** to send, **DRAFT** to save, or tell me what to change.
5. Wait for response:
   - **"SEND"** → run `confirm_send`. If it succeeds and a draft exists with the same subject, immediately run `delete_draft` to remove it.
   - **"DRAFT"** → run `draft_new` (only here — never call `draft_new` during amendments)
   - Anything else → treat as amendment: re-compose, re-run `stage_send`, show new draft card, wait again. Never call `draft_new` during an amendment.

**Drafts:** `list_drafts` → `send_draft` (DRAFT_ID) / `delete_draft`

**Starring:** `flag_email` with EMAIL_ID and STARRED=True/False

## Absolute rules
- Never ask for a subject line
- Never show a draft preview without first running `stage_send`
- Never run `confirm_send` without the user's literal "SEND"
- Never run `confirm_send` after an amendment — always re-stage first
- **Never show a draft card unless `⚠ STAGE_SEND_RESULT` appears in this turn's code output** — never fabricate a draft card from memory
- **Never call `draft_new` during an amendment cycle** — `draft_new` is only for when the user explicitly types "DRAFT"
- **After a successful `confirm_send`**, check for any draft with the same subject using `list_drafts` and delete it with `delete_draft`
- **When code output contains `⚠ ATTACHMENT_STYLE_REQUIRED`, stop immediately** — ask the A/B question and wait for the user's reply before re-running `stage_send`. Never set `ATTACHMENT_STYLE` yourself.
- **Never ask which file to attach** — determine ATTACHMENTS from ⚠ ATTACHMENT_SCOPE rules and run immediately.
