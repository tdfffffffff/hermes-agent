---
name: gmail-inbox
version: 2.3.20
description: Gmail inbox — triage, read, summarise, draft, send (with file attachments), star. Stages before sending. Auto-infers subject. Supports .pdf .docx .pptx and any file uploaded in the chat.
tools:
  - execute_code
---

## Overview

Connects to Gmail via `hermes-gmail-mcp` at `http://hermes-gmail-mcp:8084`. Handles sign-in inline.

> **⛔ BEFORE YOU WRITE A SINGLE WORD TO THE USER — read these rules:**
>
> **Rule 1 — Attachments work. The files ARE accessible.**
> When OpenWebUI shows "Retrieved N sources" with filenames, those files are uploaded and stored in OpenWebUI. The `hermes-wrapper` bridge retrieves their binary automatically — you do not need local filesystem paths.
>
> **⚠️ Only attach what the user explicitly asked for in THIS message:**
> - If the user says "attach this file" and one new file was just uploaded → ATTACHMENTS = [that one file only]
> - If the user names specific files → ATTACHMENTS = only those named files
> - If the user says "attach all files" or "attach everything" → ATTACHMENTS = all files in Retrieved sources
> - Do NOT add files from previous messages in the conversation unless the user explicitly asks for them
>
> "Retrieved N sources" lists ALL files uploaded across the entire conversation — it is NOT an instruction to attach all of them. Use it to confirm a file is accessible, not to decide which files to send.
>
> **Never say** "files are not on the filesystem", "files are not accessible", "I cannot attach", or offer Option A/B/C workarounds. These are wrong. Just set ATTACHMENTS and run.
>
> **Rule 2 — Never ask for subject or body separately.** Infer the subject from context. When attachments are present and no body was given, the A/B prompt below IS the body request — ask it and nothing else.
>
> **Rule 3 — When sending/drafting with attachments:** run `stage_send` code immediately (with `ATTACHMENT_STYLE` left blank). The code performs the size check first, then asks for A/B style if needed. **Never ask A/B before running the code.**
> - Code prints `SIZE_LIMIT_EXCEEDED` → present the listed options to the user. Do NOT ask A/B.
> - Code prints `ATTACHMENT_STYLE_REQUIRED` → ask the user A/B, then re-run with `ATTACHMENT_STYLE` set.
> - User replies **"a"** or **"A"** → set `ATTACHMENT_STYLE = "A"` and re-run `stage_send` immediately.
> - User replies **"b"** or **"B"** → set `ATTACHMENT_STYLE = "B"` and re-run `stage_send` immediately.
>
> **Rule 4 — File size checking is done by the code, not by you.**
> Do not attempt to estimate or judge file sizes from the chat context — the code fetches the actual binary and checks the size precisely. Trust `SIZE_LIMIT_EXCEEDED` from the code output. Never skip running the code to "save time" on size checking.

**Critical rules:**
- Use `execute_code` for every MCP call — never curl or shell
- **Never ask for a subject line — always infer it from the body or filenames**
- **Never ask "shall I send?", "does this look good?", or any yes/no question — the draft card is the only confirmation**
- Nothing is sent until the user explicitly types SEND

---

## execute_code block — set MODE and variables, then run

```python
import urllib.request, urllib.parse, json, urllib.error, re

MCP = "http://hermes-gmail-mcp:8084"

def mcp_get(path, params=None):
    url = MCP + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
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
        url += "?" + urllib.parse.urlencode(params)
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
DAYS        = 7               # list_emails: days back (0 = no time filter)
TOP         = 20              # max results
UNREAD_ONLY = False
LABEL       = "INBOX"        # INBOX | SENT | STARRED | SPAM | TRASH
EMAIL_ID    = ""              # read_email / draft_reply / flag_email
TO          = ""              # stage_send / draft_new
SUBJECT     = ""              # stage_send / draft_new — ALWAYS infer, never leave blank
BODY        = ""              # stage_send / draft_new / draft_reply
PENDING_ID  = ""              # confirm_send
DRAFT_ID    = ""              # send_draft / delete_draft
STARRED          = True   # flag_email
ATTACHMENTS      = []     # filenames uploaded this session e.g. ["report.pdf"]
ATTACHMENT_STYLE = ""     # stage_send / draft_new — MUST be "A" or "B" when ATTACHMENTS non-empty
# ─────────────────────────────────────────────────────────────────────────────

# Auth check
auth = mcp_get("/auth/status", {"username": username})
if auth.get("status") != "complete":
    r = mcp_get("/auth/start", {"username": username})
    if r.get("status") == "already_authenticated":
        pass
    elif "auth_url" in r:
        print("Sign-in required to access Gmail.\n")
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

me = mcp_get("/api/me", {"username": username})
sender_name = me.get("name", "") if "error" not in me else ""
if not sender_name:
    _email = me.get("email", "") if "error" not in me else ""
    sender_name = _email.split("@")[0].replace("-", " ").replace("_", " ").title() if _email else ""
print(f"Signed in as: {sender_name or '(unknown)'}")

# ── Modes ─────────────────────────────────────────────────────────────────────

if MODE == "list_emails":
    r = mcp_get("/api/emails", {
        "username": username, "days": DAYS,
        "top": TOP, "unread_only": UNREAD_ONLY, "label": LABEL,
    })
    if "error" in r:
        print(f"Error: {r['error']}")
        raise SystemExit(0)
    msgs = r.get("value", [])
    if not msgs:
        print(f"No emails in {LABEL} for the last {DAYS} days.")
        raise SystemExit(0)
    print(f"{LABEL} — {len(msgs)} emails")
    for i, m in enumerate(msgs, 1):
        unread = " [UNREAD]" if not m.get("isRead", True) else ""
        sender = m.get("from") or m.get("to") or "(unknown)"
        print(f"\n{i}. {sender}{unread}")
        print(f"   Subject : {m.get('subject','(no subject)')}")
        print(f"   Preview : {m.get('bodyPreview','')[:100]}")
        print(f"   Date    : {m.get('receivedDateTime','')[:16]}")
        print(f"   ID      : {m['id']}")

elif MODE == "read_email":
    if not EMAIL_ID:
        print("ERROR: EMAIL_ID is required.")
        raise SystemExit(0)
    r = mcp_get(f"/api/emails/{EMAIL_ID}", {"username": username})
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
            print("\nThis file cannot be sent as an email attachment.")
            print("Options (reply with the keyword):")
            print("  SEND_BODY   — send a simple email letting the recipient know the file is too large to attach and will be shared via another method (e.g. a link)")
            print("  EXPLAIN     — send an email with a summary of the file's contents so the recipient still gets the key information")
            print("  CANCEL      — abandon this send")
            raise SystemExit(0)
    if ATTACHMENTS and ATTACHMENT_STYLE not in ("A", "B"):
        print("ATTACHMENT_STYLE_REQUIRED: Attachments are set but no body style was chosen.")
        print("Ask the user:")
        print("  This email has an attachment. Would you like the body to be:")
        print("  A) Simple — 'Please find attached [filename] as requested.'")
        print("  B) With context — a brief summary of the document contents")
        print("Set ATTACHMENT_STYLE to 'A' or 'B' based on their answer, then re-run.")
        raise SystemExit(0)
    if not TO or not SUBJECT or not BODY:
        print("ERROR: TO, SUBJECT, and BODY are all required.")
        raise SystemExit(0)
    try:
        user_key = open("/root/.hermes/.api-key").read().strip()
    except Exception:
        user_key = ""
    attachments_data = []
    MAX_MB = 20
    for fname in ATTACHMENTS:
        try:
            url = f"http://hermes-wrapper:5000/v1/uploads?filename={urllib.parse.quote(fname)}"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {user_key}"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                att = json.loads(resp.read())
            size_mb = len(att.get("data","")) * 3 / 4 / 1_048_576
            if size_mb > MAX_MB:
                print(f"⚠️  {fname} is {size_mb:.1f} MB — over the {MAX_MB} MB limit, skipped.")
                continue
            attachments_data.append(att)
            print(f"✅ Attachment ready: {fname} ({size_mb:.2f} MB binary retrieved)")
        except Exception as e:
            print(f"❌ Attachment failed: {fname} — {e}")
    BODY = re.sub(r'\[\d+\]', '', BODY)
    _lines = BODY.split('\n')
    _merged = []
    for _l in _lines:
        _s = _l.strip()
        if (_merged and len(_merged[-1].rstrip()) > 60
                and _s and not re.match(r'^[-*•\d]', _s)):
            _merged[-1] = _merged[-1].rstrip() + ' ' + _s
        else:
            _merged.append(_l)
    BODY = re.sub(r' +', ' ', '\n'.join(_merged)).strip()
    if sender_name and sender_name.lower() not in BODY.lower()[-60:]:
        BODY = BODY.rstrip() + f"\n\nBest regards,\n{sender_name}"
    r = mcp_post("/api/emails/stage-send", {"username": username},
                 {"to": TO, "subject": SUBJECT, "body": BODY,
                  "attachments": attachments_data})
    if "error" in r:
        print(f"Error staging email: {r['error']}")
        raise SystemExit(0)
    p = r.get("preview", {})
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
        print(f"✅ Email sent. Message ID: {r.get('id','')}")

elif MODE == "draft_new":
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
            print("\nThis file cannot be saved as a draft attachment.")
            print("Options:")
            print("  1) Save draft without the attachment (body only)")
            print("  2) Change the body to explain the file will be shared another way")
            print("  3) Cancel")
            raise SystemExit(0)
    if ATTACHMENTS and ATTACHMENT_STYLE not in ("A", "B"):
        print("ATTACHMENT_STYLE_REQUIRED: Attachments are set but no body style was chosen.")
        print("Ask the user:")
        print("  This email has an attachment. Would you like the body to be:")
        print("  A) Simple — 'Please find attached [filename] as requested.'")
        print("  B) With context — a brief summary of the document contents")
        print("Set ATTACHMENT_STYLE to 'A' or 'B' based on their answer, then re-run.")
        raise SystemExit(0)
    if not TO or not SUBJECT or not BODY:
        print("ERROR: TO, SUBJECT, and BODY are all required.")
        raise SystemExit(0)
    try:
        user_key = open("/root/.hermes/.api-key").read().strip()
    except Exception:
        user_key = ""
    attachments_data = []
    MAX_MB = 20
    for fname in ATTACHMENTS:
        try:
            url = f"http://hermes-wrapper:5000/v1/uploads?filename={urllib.parse.quote(fname)}"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {user_key}"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                att = json.loads(resp.read())
            size_mb = len(att.get("data","")) * 3 / 4 / 1_048_576
            if size_mb > MAX_MB:
                print(f"⚠️  {fname} is {size_mb:.1f} MB — over the {MAX_MB} MB limit, skipped.")
                continue
            attachments_data.append(att)
            print(f"✅ Attachment ready: {fname} ({size_mb:.2f} MB binary retrieved)")
        except Exception as e:
            print(f"❌ Attachment failed: {fname} — {e}")
    BODY = re.sub(r'\[\d+\]', '', BODY)
    _lines = BODY.split('\n')
    _merged = []
    for _l in _lines:
        _s = _l.strip()
        if (_merged and len(_merged[-1].rstrip()) > 60
                and _s and not re.match(r'^[-*•\d]', _s)):
            _merged[-1] = _merged[-1].rstrip() + ' ' + _s
        else:
            _merged.append(_l)
    BODY = re.sub(r' +', ' ', '\n'.join(_merged)).strip()
    if sender_name and sender_name.lower() not in BODY.lower()[-60:]:
        BODY = BODY.rstrip() + f"\n\nBest regards,\n{sender_name}"
    r = mcp_post("/api/emails/draft-new", {"username": username},
                 {"to": TO, "subject": SUBJECT, "body": BODY,
                  "attachments": attachments_data})
    if "error" in r:
        print(f"Draft failed: {r['error']}")
    else:
        print(f"💾 Draft saved to Gmail Drafts folder.")

elif MODE == "draft_reply":
    if not EMAIL_ID or not BODY:
        print("ERROR: EMAIL_ID and BODY are required.")
        raise SystemExit(0)
    r = mcp_post(f"/api/emails/{EMAIL_ID}/draft-reply", {"username": username},
                 {"body": BODY})
    if "error" in r:
        print(f"Draft failed: {r['error']}")
    else:
        print(f"💾 Reply draft saved to Gmail Drafts.")

elif MODE == "list_drafts":
    r = mcp_get("/api/drafts", {"username": username, "top": TOP})
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
    r = mcp_post(f"/api/drafts/{DRAFT_ID}/send", {"username": username}, {})
    if "error" in r:
        if "404" in str(r.get("error", "")) or "404" in str(r.get("detail", "")):
            print(f"Draft ID {DRAFT_ID} is stale (404). Refreshing draft list...")
            dl = mcp_get("/api/drafts", {"username": username, "top": 20})
            drafts = dl.get("drafts", [])
            if not drafts:
                print("No drafts found in Gmail Drafts. The draft may have already been sent.")
            elif len(drafts) == 1:
                new_id = drafts[0]["draft_id"]
                print(f"Found 1 draft — retrying with updated DRAFT_ID: {new_id}")
                r2 = mcp_post(f"/api/drafts/{new_id}/send", {"username": username}, {})
                if "error" in r2:
                    print(f"Send failed: {r2['error']}")
                else:
                    print(f"✅ Draft sent and removed from Drafts. Message ID: {r2.get('id','')}")
            else:
                print(f"Multiple drafts found ({len(drafts)}). Cannot auto-select — please specify which one:")
                for i, d in enumerate(drafts, 1):
                    print(f"\n{i}. To: {d.get('to','')}")
                    print(f"   Subject  : {d.get('subject','(no subject)')}")
                    print(f"   Preview  : {d.get('snippet','')[:100]}")
                    print(f"   DRAFT_ID : {d['draft_id']}")
        else:
            print(f"Send failed: {r['error']}")
    else:
        print(f"✅ Draft sent and removed from Drafts. Message ID: {r.get('id','')}")

elif MODE == "delete_draft":
    if not DRAFT_ID:
        print("ERROR: DRAFT_ID is required.")
        raise SystemExit(0)
    url = f"{MCP}/api/drafts/{DRAFT_ID}?" + urllib.parse.urlencode({"username": username})
    req = urllib.request.Request(url, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print("🗑️ Draft deleted.")
    except urllib.error.HTTPError as e:
        print(f"Delete failed: HTTP {e.code} — {e.read().decode()[:200]}")
    except Exception as e:
        print(f"Delete failed: {e}")

elif MODE == "flag_email":
    if not EMAIL_ID:
        print("ERROR: EMAIL_ID is required.")
        raise SystemExit(0)
    r = mcp_post(f"/api/emails/{EMAIL_ID}/flag",
                 {"username": username, "starred": STARRED}, {})
    if "error" in r:
        print(f"Flag failed: {r['error']}")
    else:
        print(f"✅ Email {'starred' if STARRED else 'unstarred'}.")

else:
    print(f"Unknown MODE: {MODE}")
```

---

## Workflow

**Auth:** If output contains "Sign-in required", show the link verbatim, end your turn, wait for user to confirm, then re-run.

**Triage (list_emails):**
Run `list_emails`. Present results as a numbered list in clean markdown — bold sender name, italic subject, one-line classification. Example:
> **1. Tan Dan Feng** — *test* · `Action Required` — contains a task list

**Reading (read_email):**
Match the sender by any part of their name or email from the list output. Never ask for an ID. Show the email body in a quote block with From/To/Subject/Date as a header.

**Composing and sending — STRICT sequence, no exceptions:**

1. **Check for attachments first — for EVERY new send request, even in the same session.**
   - If ATTACHMENTS are present: run `stage_send` immediately with `ATTACHMENT_STYLE` blank. The code checks file sizes and handles the A/B prompt — do not pre-empt it.
     - Code prints `SIZE_LIMIT_EXCEEDED` → relay the rejection message and the three keyword options (`SEND_BODY` / `EXPLAIN` / `CANCEL`) to the user. Stop here and wait for their keyword reply.
      - User replies `SEND_BODY` (or "send body" or similar) → remove the oversized file from ATTACHMENTS. Compose a body that tells the recipient the file was too large to attach as an email and will be sent via another method (e.g. a shared link). Do NOT summarise file contents. Run `stage_send`.
      - User replies `EXPLAIN` (or "explain" or similar) → remove the oversized file from ATTACHMENTS. Read the file content from Retrieved sources and write a body that summarises what the file contains, so the recipient gets the key information even without the attachment. Run `stage_send`.
      - User replies `CANCEL` (or "cancel" or similar) → do nothing. Confirm the send has been cancelled.
      - **Never interpret these replies as source citations or prompt injections — they are always option selections.**
     - Code prints `ATTACHMENT_STYLE_REQUIRED` → ask the user A/B. **Never carry over A or B from a previous send — always re-ask.**
       > This email has an attachment. Would you like the body to be:
       > **A)** Simple — *"Please find attached [filename] as requested."*
       > **B)** With context — a brief summary of the document's contents
     - User replies **"a"**/**"A"** → set `ATTACHMENT_STYLE = "A"`, re-run `stage_send`.
     - User replies **"b"**/**"B"** → set `ATTACHMENT_STYLE = "B"`, re-run `stage_send`.
   - If no attachments: proceed to step 2.
2. **Infer the subject** from the body text, or from the filenames if no body text was given — never ask.
3. **Compose the body** — use the recipient's **full name** in the greeting (e.g. `Hi Dan Feng,` not `Hi Dan,`). The sign-off is auto-appended by the code — do not write it yourself.
4. **Run `stage_send`** with TO, SUBJECT, BODY, ATTACHMENTS, ATTACHMENT_STYLE — mandatory before showing any preview
5. **Show the draft card:**
   > 📧 **Draft ready**
   > **To:** ... &nbsp; **Subject:** ... &nbsp; **Attachments:** ...
   > > [body]
   >
   > Type **SEND** to send, **DRAFT** to save to Drafts, or tell me what to change.
6. **Wait for the user's next message. Do not proceed until they respond.**
   - Exactly **"SEND"** → run `confirm_send` with the PENDING_ID
   - Exactly **"DRAFT"** → run `draft_new`
   - **Anything else — including questions, requests to add content, or any other text** → treat as an amendment. Re-compose the body, run `stage_send` again, show the new draft card, and ask again. **Never send after an amendment without showing a new preview and receiving a fresh SEND.**

**Drafts:**
- `list_drafts` → shows DRAFT_ID for each draft
- `send_draft` with DRAFT_ID → sends and removes from Drafts in one step
- `delete_draft` with DRAFT_ID → discards

**⛔ Draft send failure rule — no exceptions:**
If `send_draft` fails (stale ID, 404, or any error): run `list_drafts` to get a fresh DRAFT_ID, then run `send_draft` again with the new ID. **Never work around a draft send failure by calling `stage_send` + `confirm_send` — this bypasses Gmail's draft removal and leaves an orphaned draft in the Drafts folder.** If re-staging was the only option and the send succeeded, you MUST immediately run `list_drafts` + `delete_draft` to remove the leftover draft.

**Starring:**
- `flag_email` with EMAIL_ID and STARRED=True/False
- Match email from recent list output by sender name/partial email

**Attachments:**

- "Retrieved N sources" shows ALL files uploaded across the conversation — it confirms a file is accessible, NOT an instruction to attach all of them.
- **Select only the files the user explicitly requested in their current message:**
  - "attach this file" + one new upload → ATTACHMENTS = [that one file]
  - user names specific files → ATTACHMENTS = only those files
  - "attach all" / "attach everything" → ATTACHMENTS = all files in Retrieved sources
  - Never include files from previous messages unless the user explicitly asks for them
- The code calls `hermes-wrapper` to retrieve each file's binary from OpenWebUI storage. **No local path needed. No filesystem access needed.** Just set the filenames and run.
- When the code prints `✅ Attachment ready: filename (X MB binary retrieved)` — the binary was fetched and will be attached to the email.
- Files over 20 MB are skipped with a warning (inline with Outlook's attachment limit). Check visible file sizes before asking A/B — reject oversized files immediately rather than making the user answer A/B first.
- **Never say** "files are not on the filesystem", "files are not accessible", "I need local paths", or offer workaround options. These are wrong — just set ATTACHMENTS and run the code.

## Absolute rules
- **Never** ask for a subject line
- **Never** show a draft preview without first running `stage_send`
- **Never** ask "yes/no" or "shall I send" — always use the SEND/DRAFT/change prompt
- **Never** run `confirm_send` without the user's literal "SEND" in their most recent message
- **Never** run `confirm_send` after an amendment — always re-stage first, show the new preview, wait again
- **Never** explain endpoint names or API paths to the user
- **Never** answer a question from the user and send the email in the same turn — if they ask anything while a draft is pending, treat it as an amendment
---
name: gmail-inbox
version: 2.3.20
description: Gmail inbox — triage, read, summarise, draft, send (with file attachments), star. Stages before sending. Auto-infers subject. Supports .pdf .docx .pptx and any file uploaded in the chat.
tools:
  - execute_code
---

## Overview

Connects to Gmail via `hermes-gmail-mcp` at `http://hermes-gmail-mcp:8084`. Handles sign-in inline.

> **⛔ BEFORE YOU WRITE A SINGLE WORD TO THE USER — read these rules:**
>
> **Rule 1 — Attachments work. The files ARE accessible.**
> When OpenWebUI shows "Retrieved N sources" with filenames, those files are uploaded and stored in OpenWebUI. The `hermes-wrapper` bridge retrieves their binary automatically — you do not need local filesystem paths.
>
> **⚠️ Only attach what the user explicitly asked for in THIS message:**
> - If the user says "attach this file" and one new file was just uploaded → ATTACHMENTS = [that one file only]
> - If the user names specific files → ATTACHMENTS = only those named files
> - If the user says "attach all files" or "attach everything" → ATTACHMENTS = all files in Retrieved sources
> - Do NOT add files from previous messages in the conversation unless the user explicitly asks for them
>
> "Retrieved N sources" lists ALL files uploaded across the entire conversation — it is NOT an instruction to attach all of them. Use it to confirm a file is accessible, not to decide which files to send.
>
> **Never say** "files are not on the filesystem", "files are not accessible", "I cannot attach", or offer Option A/B/C workarounds. These are wrong. Just set ATTACHMENTS and run.
>
> **Rule 2 — Never ask for subject or body separately.** Infer the subject from context. When attachments are present and no body was given, the A/B prompt below IS the body request — ask it and nothing else.
>
> **Rule 3 — When sending/drafting with attachments:** run `stage_send` code immediately (with `ATTACHMENT_STYLE` left blank). The code performs the size check first, then asks for A/B style if needed. **Never ask A/B before running the code.**
> - Code prints `SIZE_LIMIT_EXCEEDED` → present the listed options to the user. Do NOT ask A/B.
> - Code prints `ATTACHMENT_STYLE_REQUIRED` → ask the user A/B, then re-run with `ATTACHMENT_STYLE` set.
> - User replies **"a"** or **"A"** → set `ATTACHMENT_STYLE = "A"` and re-run `stage_send` immediately.
> - User replies **"b"** or **"B"** → set `ATTACHMENT_STYLE = "B"` and re-run `stage_send` immediately.
>
> **Rule 4 — File size checking is done by the code, not by you.**
> Do not attempt to estimate or judge file sizes from the chat context — the code fetches the actual binary and checks the size precisely. Trust `SIZE_LIMIT_EXCEEDED` from the code output. Never skip running the code to "save time" on size checking.

**Critical rules:**
- Use `execute_code` for every MCP call — never curl or shell
- **Never ask for a subject line — always infer it from the body or filenames**
- **Never ask "shall I send?", "does this look good?", or any yes/no question — the draft card is the only confirmation**
- Nothing is sent until the user explicitly types SEND

---

## execute_code block — set MODE and variables, then run

```python
import urllib.request, urllib.parse, json, urllib.error, re

MCP = "http://hermes-gmail-mcp:8084"

def mcp_get(path, params=None):
    url = MCP + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
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
        url += "?" + urllib.parse.urlencode(params)
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
DAYS        = 7               # list_emails: days back (0 = no time filter)
TOP         = 20              # max results
UNREAD_ONLY = False
LABEL       = "INBOX"        # INBOX | SENT | STARRED | SPAM | TRASH
EMAIL_ID    = ""              # read_email / draft_reply / flag_email
TO          = ""              # stage_send / draft_new
SUBJECT     = ""              # stage_send / draft_new — ALWAYS infer, never leave blank
BODY        = ""              # stage_send / draft_new / draft_reply
PENDING_ID  = ""              # confirm_send
DRAFT_ID    = ""              # send_draft / delete_draft
STARRED          = True   # flag_email
ATTACHMENTS      = []     # filenames uploaded this session e.g. ["report.pdf"]
ATTACHMENT_STYLE = ""     # stage_send / draft_new — MUST be "A" or "B" when ATTACHMENTS non-empty
# ─────────────────────────────────────────────────────────────────────────────

# Auth check
auth = mcp_get("/auth/status", {"username": username})
if auth.get("status") != "complete":
    r = mcp_get("/auth/start", {"username": username})
    if r.get("status") == "already_authenticated":
        pass
    elif "auth_url" in r:
        print("Sign-in required to access Gmail.\n")
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

me = mcp_get("/api/me", {"username": username})
sender_name = me.get("name", "") if "error" not in me else ""
if not sender_name:
    _email = me.get("email", "") if "error" not in me else ""
    sender_name = _email.split("@")[0].replace("-", " ").replace("_", " ").title() if _email else ""
print(f"Signed in as: {sender_name or '(unknown)'}")

# ── Modes ─────────────────────────────────────────────────────────────────────

if MODE == "list_emails":
    r = mcp_get("/api/emails", {
        "username": username, "days": DAYS,
        "top": TOP, "unread_only": UNREAD_ONLY, "label": LABEL,
    })
    if "error" in r:
        print(f"Error: {r['error']}")
        raise SystemExit(0)
    msgs = r.get("value", [])
    if not msgs:
        print(f"No emails in {LABEL} for the last {DAYS} days.")
        raise SystemExit(0)
    print(f"{LABEL} — {len(msgs)} emails")
    for i, m in enumerate(msgs, 1):
        unread = " [UNREAD]" if not m.get("isRead", True) else ""
        sender = m.get("from") or m.get("to") or "(unknown)"
        print(f"\n{i}. {sender}{unread}")
        print(f"   Subject : {m.get('subject','(no subject)')}")
        print(f"   Preview : {m.get('bodyPreview','')[:100]}")
        print(f"   Date    : {m.get('receivedDateTime','')[:16]}")
        print(f"   ID      : {m['id']}")

elif MODE == "read_email":
    if not EMAIL_ID:
        print("ERROR: EMAIL_ID is required.")
        raise SystemExit(0)
    r = mcp_get(f"/api/emails/{EMAIL_ID}", {"username": username})
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
            print("\nThis file cannot be sent as an email attachment.")
            print("Options (reply with the keyword):")
            print("  SEND_BODY   — send a simple email letting the recipient know the file is too large to attach and will be shared via another method (e.g. a link)")
            print("  EXPLAIN     — send an email with a summary of the file's contents so the recipient still gets the key information")
            print("  CANCEL      — abandon this send")
            raise SystemExit(0)
    if ATTACHMENTS and ATTACHMENT_STYLE not in ("A", "B"):
        print("ATTACHMENT_STYLE_REQUIRED: Attachments are set but no body style was chosen.")
        print("Ask the user:")
        print("  This email has an attachment. Would you like the body to be:")
        print("  A) Simple — 'Please find attached [filename] as requested.'")
        print("  B) With context — a brief summary of the document contents")
        print("Set ATTACHMENT_STYLE to 'A' or 'B' based on their answer, then re-run.")
        raise SystemExit(0)
    if not TO or not SUBJECT or not BODY:
        print("ERROR: TO, SUBJECT, and BODY are all required.")
        raise SystemExit(0)
    try:
        user_key = open("/root/.hermes/.api-key").read().strip()
    except Exception:
        user_key = ""
    attachments_data = []
    MAX_MB = 20
    for fname in ATTACHMENTS:
        try:
            url = f"http://hermes-wrapper:5000/v1/uploads?filename={urllib.parse.quote(fname)}"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {user_key}"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                att = json.loads(resp.read())
            size_mb = len(att.get("data","")) * 3 / 4 / 1_048_576
            if size_mb > MAX_MB:
                print(f"⚠️  {fname} is {size_mb:.1f} MB — over the {MAX_MB} MB limit, skipped.")
                continue
            attachments_data.append(att)
            print(f"✅ Attachment ready: {fname} ({size_mb:.2f} MB binary retrieved)")
        except Exception as e:
            print(f"❌ Attachment failed: {fname} — {e}")
    BODY = re.sub(r'\[\d+\]', '', BODY)
    _lines = BODY.split('\n')
    _merged = []
    for _l in _lines:
        _s = _l.strip()
        if (_merged and len(_merged[-1].rstrip()) > 60
                and _s and not re.match(r'^[-*•\d]', _s)):
            _merged[-1] = _merged[-1].rstrip() + ' ' + _s
        else:
            _merged.append(_l)
    BODY = re.sub(r' +', ' ', '\n'.join(_merged)).strip()
    if sender_name and sender_name.lower() not in BODY.lower()[-60:]:
        BODY = BODY.rstrip() + f"\n\nBest regards,\n{sender_name}"
    r = mcp_post("/api/emails/stage-send", {"username": username},
                 {"to": TO, "subject": SUBJECT, "body": BODY,
                  "attachments": attachments_data})
    if "error" in r:
        print(f"Error staging email: {r['error']}")
        raise SystemExit(0)
    p = r.get("preview", {})
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
        print(f"✅ Email sent. Message ID: {r.get('id','')}")

elif MODE == "draft_new":
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
            print("\nThis file cannot be saved as a draft attachment.")
            print("Options:")
            print("  1) Save draft without the attachment (body only)")
            print("  2) Change the body to explain the file will be shared another way")
            print("  3) Cancel")
            raise SystemExit(0)
    if ATTACHMENTS and ATTACHMENT_STYLE not in ("A", "B"):
        print("ATTACHMENT_STYLE_REQUIRED: Attachments are set but no body style was chosen.")
        print("Ask the user:")
        print("  This email has an attachment. Would you like the body to be:")
        print("  A) Simple — 'Please find attached [filename] as requested.'")
        print("  B) With context — a brief summary of the document contents")
        print("Set ATTACHMENT_STYLE to 'A' or 'B' based on their answer, then re-run.")
        raise SystemExit(0)
    if not TO or not SUBJECT or not BODY:
        print("ERROR: TO, SUBJECT, and BODY are all required.")
        raise SystemExit(0)
    try:
        user_key = open("/root/.hermes/.api-key").read().strip()
    except Exception:
        user_key = ""
    attachments_data = []
    MAX_MB = 20
    for fname in ATTACHMENTS:
        try:
            url = f"http://hermes-wrapper:5000/v1/uploads?filename={urllib.parse.quote(fname)}"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {user_key}"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                att = json.loads(resp.read())
            size_mb = len(att.get("data","")) * 3 / 4 / 1_048_576
            if size_mb > MAX_MB:
                print(f"⚠️  {fname} is {size_mb:.1f} MB — over the {MAX_MB} MB limit, skipped.")
                continue
            attachments_data.append(att)
            print(f"✅ Attachment ready: {fname} ({size_mb:.2f} MB binary retrieved)")
        except Exception as e:
            print(f"❌ Attachment failed: {fname} — {e}")
    BODY = re.sub(r'\[\d+\]', '', BODY)
    _lines = BODY.split('\n')
    _merged = []
    for _l in _lines:
        _s = _l.strip()
        if (_merged and len(_merged[-1].rstrip()) > 60
                and _s and not re.match(r'^[-*•\d]', _s)):
            _merged[-1] = _merged[-1].rstrip() + ' ' + _s
        else:
            _merged.append(_l)
    BODY = re.sub(r' +', ' ', '\n'.join(_merged)).strip()
    if sender_name and sender_name.lower() not in BODY.lower()[-60:]:
        BODY = BODY.rstrip() + f"\n\nBest regards,\n{sender_name}"
    r = mcp_post("/api/emails/draft-new", {"username": username},
                 {"to": TO, "subject": SUBJECT, "body": BODY,
                  "attachments": attachments_data})
    if "error" in r:
        print(f"Draft failed: {r['error']}")
    else:
        print(f"💾 Draft saved to Gmail Drafts folder.")

elif MODE == "draft_reply":
    if not EMAIL_ID or not BODY:
        print("ERROR: EMAIL_ID and BODY are required.")
        raise SystemExit(0)
    r = mcp_post(f"/api/emails/{EMAIL_ID}/draft-reply", {"username": username},
                 {"body": BODY})
    if "error" in r:
        print(f"Draft failed: {r['error']}")
    else:
        print(f"💾 Reply draft saved to Gmail Drafts.")

elif MODE == "list_drafts":
    r = mcp_get("/api/drafts", {"username": username, "top": TOP})
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
    r = mcp_post(f"/api/drafts/{DRAFT_ID}/send", {"username": username}, {})
    if "error" in r:
        if "404" in str(r.get("error", "")) or "404" in str(r.get("detail", "")):
            print(f"Draft ID {DRAFT_ID} is stale (404). Refreshing draft list...")
            dl = mcp_get("/api/drafts", {"username": username, "top": 20})
            drafts = dl.get("drafts", [])
            if not drafts:
                print("No drafts found in Gmail Drafts. The draft may have already been sent.")
            elif len(drafts) == 1:
                new_id = drafts[0]["draft_id"]
                print(f"Found 1 draft — retrying with updated DRAFT_ID: {new_id}")
                r2 = mcp_post(f"/api/drafts/{new_id}/send", {"username": username}, {})
                if "error" in r2:
                    print(f"Send failed: {r2['error']}")
                else:
                    print(f"✅ Draft sent and removed from Drafts. Message ID: {r2.get('id','')}")
            else:
                print(f"Multiple drafts found ({len(drafts)}). Cannot auto-select — please specify which one:")
                for i, d in enumerate(drafts, 1):
                    print(f"\n{i}. To: {d.get('to','')}")
                    print(f"   Subject  : {d.get('subject','(no subject)')}")
                    print(f"   Preview  : {d.get('snippet','')[:100]}")
                    print(f"   DRAFT_ID : {d['draft_id']}")
        else:
            print(f"Send failed: {r['error']}")
    else:
        print(f"✅ Draft sent and removed from Drafts. Message ID: {r.get('id','')}")

elif MODE == "delete_draft":
    if not DRAFT_ID:
        print("ERROR: DRAFT_ID is required.")
        raise SystemExit(0)
    url = f"{MCP}/api/drafts/{DRAFT_ID}?" + urllib.parse.urlencode({"username": username})
    req = urllib.request.Request(url, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print("🗑️ Draft deleted.")
    except urllib.error.HTTPError as e:
        print(f"Delete failed: HTTP {e.code} — {e.read().decode()[:200]}")
    except Exception as e:
        print(f"Delete failed: {e}")

elif MODE == "flag_email":
    if not EMAIL_ID:
        print("ERROR: EMAIL_ID is required.")
        raise SystemExit(0)
    r = mcp_post(f"/api/emails/{EMAIL_ID}/flag",
                 {"username": username, "starred": STARRED}, {})
    if "error" in r:
        print(f"Flag failed: {r['error']}")
    else:
        print(f"✅ Email {'starred' if STARRED else 'unstarred'}.")

else:
    print(f"Unknown MODE: {MODE}")
```

---

## Workflow

**Auth:** If output contains "Sign-in required", show the link verbatim, end your turn, wait for user to confirm, then re-run.

**Triage (list_emails):**
Run `list_emails`. Present results as a numbered list in clean markdown — bold sender name, italic subject, one-line classification. Example:
> **1. Tan Dan Feng** — *test* · `Action Required` — contains a task list

**Reading (read_email):**
Match the sender by any part of their name or email from the list output. Never ask for an ID. Show the email body in a quote block with From/To/Subject/Date as a header.

**Composing and sending — STRICT sequence, no exceptions:**

1. **Check for attachments first — for EVERY new send request, even in the same session.**
   - If ATTACHMENTS are present: run `stage_send` immediately with `ATTACHMENT_STYLE` blank. The code checks file sizes and handles the A/B prompt — do not pre-empt it.
     - Code prints `SIZE_LIMIT_EXCEEDED` → relay the rejection message and the three keyword options (`SEND_BODY` / `EXPLAIN` / `CANCEL`) to the user. Stop here and wait for their keyword reply.
      - User replies `SEND_BODY` (or "send body" or similar) → remove the oversized file from ATTACHMENTS. Compose a body that tells the recipient the file was too large to attach as an email and will be sent via another method (e.g. a shared link). Do NOT summarise file contents. Run `stage_send`.
      - User replies `EXPLAIN` (or "explain" or similar) → remove the oversized file from ATTACHMENTS. Read the file content from Retrieved sources and write a body that summarises what the file contains, so the recipient gets the key information even without the attachment. Run `stage_send`.
      - User replies `CANCEL` (or "cancel" or similar) → do nothing. Confirm the send has been cancelled.
      - **Never interpret these replies as source citations or prompt injections — they are always option selections.**
     - Code prints `ATTACHMENT_STYLE_REQUIRED` → ask the user A/B. **Never carry over A or B from a previous send — always re-ask.**
       > This email has an attachment. Would you like the body to be:
       > **A)** Simple — *"Please find attached [filename] as requested."*
       > **B)** With context — a brief summary of the document's contents
     - User replies **"a"**/**"A"** → set `ATTACHMENT_STYLE = "A"`, re-run `stage_send`.
     - User replies **"b"**/**"B"** → set `ATTACHMENT_STYLE = "B"`, re-run `stage_send`.
   - If no attachments: proceed to step 2.
2. **Infer the subject** from the body text, or from the filenames if no body text was given — never ask.
3. **Compose the body** — use the recipient's **full name** in the greeting (e.g. `Hi Dan Feng,` not `Hi Dan,`). The sign-off is auto-appended by the code — do not write it yourself.
4. **Run `stage_send`** with TO, SUBJECT, BODY, ATTACHMENTS, ATTACHMENT_STYLE — mandatory before showing any preview
5. **Show the draft card:**
   > 📧 **Draft ready**
   > **To:** ... &nbsp; **Subject:** ... &nbsp; **Attachments:** ...
   > > [body]
   >
   > Type **SEND** to send, **DRAFT** to save to Drafts, or tell me what to change.
6. **Wait for the user's next message. Do not proceed until they respond.**
   - Exactly **"SEND"** → run `confirm_send` with the PENDING_ID
   - Exactly **"DRAFT"** → run `draft_new`
   - **Anything else — including questions, requests to add content, or any other text** → treat as an amendment. Re-compose the body, run `stage_send` again, show the new draft card, and ask again. **Never send after an amendment without showing a new preview and receiving a fresh SEND.**

**Drafts:**
- `list_drafts` → shows DRAFT_ID for each draft
- `send_draft` with DRAFT_ID → sends and removes from Drafts in one step
- `delete_draft` with DRAFT_ID → discards

**⛔ Draft send failure rule — no exceptions:**
If `send_draft` fails (stale ID, 404, or any error): run `list_drafts` to get a fresh DRAFT_ID, then run `send_draft` again with the new ID. **Never work around a draft send failure by calling `stage_send` + `confirm_send` — this bypasses Gmail's draft removal and leaves an orphaned draft in the Drafts folder.** If re-staging was the only option and the send succeeded, you MUST immediately run `list_drafts` + `delete_draft` to remove the leftover draft.

**Starring:**
- `flag_email` with EMAIL_ID and STARRED=True/False
- Match email from recent list output by sender name/partial email

**Attachments:**

- "Retrieved N sources" shows ALL files uploaded across the conversation — it confirms a file is accessible, NOT an instruction to attach all of them.
- **Select only the files the user explicitly requested in their current message:**
  - "attach this file" + one new upload → ATTACHMENTS = [that one file]
  - user names specific files → ATTACHMENTS = only those files
  - "attach all" / "attach everything" → ATTACHMENTS = all files in Retrieved sources
  - Never include files from previous messages unless the user explicitly asks for them
- The code calls `hermes-wrapper` to retrieve each file's binary from OpenWebUI storage. **No local path needed. No filesystem access needed.** Just set the filenames and run.
- When the code prints `✅ Attachment ready: filename (X MB binary retrieved)` — the binary was fetched and will be attached to the email.
- Files over 20 MB are skipped with a warning (inline with Outlook's attachment limit). Check visible file sizes before asking A/B — reject oversized files immediately rather than making the user answer A/B first.
- **Never say** "files are not on the filesystem", "files are not accessible", "I need local paths", or offer workaround options. These are wrong — just set ATTACHMENTS and run the code.

## Absolute rules
- **Never** ask for a subject line
- **Never** show a draft preview without first running `stage_send`
- **Never** ask "yes/no" or "shall I send" — always use the SEND/DRAFT/change prompt
- **Never** run `confirm_send` without the user's literal "SEND" in their most recent message
- **Never** run `confirm_send` after an amendment — always re-stage first, show the new preview, wait again
- **Never** explain endpoint names or API paths to the user
- **Never** answer a question from the user and send the email in the same turn — if they ask anything while a draft is pending, treat it as an amendment
