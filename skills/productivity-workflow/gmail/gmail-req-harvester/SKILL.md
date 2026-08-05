---
name: gmail-req-harvester
version: 1.0.0
description: Reads a Gmail email thread (and optionally uploaded files), extracts requirement-like statements, then produces a change log (markdown) and a new slide deck (PPTX) or report (DOCX) for review.
tools:
  - execute_code
  - write_file
---

## Overview

Searches Gmail for threads with a named person or topic, presents a disambiguation list, reads confirmed threads, extracts requirements, and generates a **change log** plus your choice of **PPTX** or **DOCX** output. Handles Google sign-in inline.

**Critical: use `execute_code` for every MCP call. Never construct curl or shell commands.**

---

## The execute_code block — set MODE and variables, then run

```python
import urllib.request, urllib.parse, json, os, sys, re
from datetime import datetime

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
MODE         = "search"   # search | read_threads | save_reqs | gen_pptx | gen_docx | gen_both
PERSON       = ""         # name or partial email to search for
TOPIC        = ""         # optional additional keyword
DAYS         = 7          # how far back to search
THREAD_IDS   = []         # set from search output — message IDs confirmed by user
OUTPUT_SLUG  = "requirements"  # slug used in output filenames
REQUIREMENTS = [
    # ("Section / Slide Title", ["bullet point 1", "bullet point 2"]),
]
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

# ── MODE: search ──────────────────────────────────────────────────────────────
if MODE == "search":
    if not PERSON and not TOPIC:
        print("ERROR: Set PERSON (name/email) and/or TOPIC before searching.")
        raise SystemExit(0)

    r = mcp_get("/api/emails", {"username": username, "days": DAYS, "top": 50, "label": "INBOX"})
    if "error" in r:
        print(f"Error: {r['error']}")
        raise SystemExit(0)

    msgs = r.get("value", [])
    hint = (PERSON + " " + TOPIC).lower().strip()
    matched = [m for m in msgs if
               any(w in m.get("from", "").lower() or
                   w in m.get("subject", "").lower() or
                   w in m.get("bodyPreview", "").lower()
                   for w in hint.split() if w)]

    if not matched:
        print(f"No threads found matching '{PERSON or ''} {TOPIC or ''}'.strip() in the last {DAYS} days.")
        raise SystemExit(0)

    print(f"THREADS FOUND ({len(matched)}) — confirm which to use")
    print("=" * 60)
    for i, m in enumerate(matched, 1):
        date  = str(m.get("receivedDateTime", ""))[:10]
        subj  = m.get("subject", "(no subject)")
        frm   = m.get("from", "")
        prev  = m.get("bodyPreview", "")[:100]
        print(f"\n{i}. [{date}] {subj}")
        print(f"   From: {frm}")
        print(f"   Preview: {prev if prev else '(no preview)'}")
        print(f"   ID: {m['id']}")

    print("\nTell me which thread(s) to use (by number, 'all', or the subject) and I'll read them.")

# ── MODE: read_threads ────────────────────────────────────────────────────────
elif MODE == "read_threads":
    if not THREAD_IDS:
        print("ERROR: THREAD_IDS is empty. Run MODE='search' first and set the IDs confirmed by the user.")
        raise SystemExit(0)

    print(f"READING {len(THREAD_IDS)} THREAD(S)")
    print("=" * 60)
    for tid in THREAD_IDS:
        r = mcp_get(f"/api/emails/{tid}", {"username": username})
        if "error" in r:
            print(f"Error reading {tid}: {r['error']}")
            continue
        print(f"\nFROM:    {r.get('from','')}")
        print(f"TO:      {r.get('to','')}")
        print(f"SUBJECT: {r.get('subject','')}")
        print(f"DATE:    {r.get('date','')}")
        print()
        print(r.get("body", "")[:3000])
        print("\n" + "-" * 60)

    print("\n--- END OF THREADS ---")
    print("Extract requirement-like statements (asks, constraints, decisions, action items) from the above.")
    print("Also incorporate any uploaded files shown in Retrieved sources.")
    print("Show the extracted requirements as a numbered list for user approval before generating output.")

# ── MODE: save_reqs ──────────────────────────────────────────────────────────
elif MODE == "save_reqs":
    if not REQUIREMENTS:
        print("ERROR: REQUIREMENTS is empty.")
        raise SystemExit(0)
    _reqs_file = f"/opt/outputs/{OUTPUT_SLUG}-requirements.json"
    os.makedirs("/opt/outputs", exist_ok=True)
    _payload = {
        "title_label": PERSON or TOPIC or OUTPUT_SLUG,
        "requirements": [
            {"title": t, "bullets": b} for t, b in REQUIREMENTS
        ]
    }
    json.dump(_payload, open(_reqs_file, "w"), indent=2)
    print(f"✅ Requirements saved: {_reqs_file}")
    print(f"   {len(REQUIREMENTS)} requirement groups ready for generation.")

# ── MODE: gen_pptx ────────────────────────────────────────────────────────────
elif MODE in ("gen_pptx", "gen_both"):
    _reqs_file = f"/opt/outputs/{OUTPUT_SLUG}-requirements.json"
    if not os.path.exists(_reqs_file):
        print(f"ERROR: Requirements file not found: {_reqs_file}")
        print("Run MODE='save_reqs' first to save the approved requirements.")
        raise SystemExit(0)
    _reqs = json.load(open(_reqs_file))
    _title_label = _reqs.get("title_label", OUTPUT_SLUG)

    sys.path.insert(0, "/opt/outputs/pypackages")
    from pptx import Presentation
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width  = Inches(13.33)
    prs.slide_height = Inches(7.5)

    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = "Requirements Update"
    slide.placeholders[1].text = f"{_title_label} — {datetime.now().strftime('%d %b %Y')}"

    for item in _reqs["requirements"]:
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = item["title"]
        tf = slide.placeholders[1].text_frame
        tf.clear()
        for i, b in enumerate(item["bullets"]):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text  = b
            p.level = 0

    date_str = datetime.now().strftime("%Y-%m-%d")
    out_pptx = f"/opt/outputs/{OUTPUT_SLUG}-{date_str}.pptx"
    os.makedirs("/opt/outputs", exist_ok=True)
    prs.save(out_pptx)
    print(f"✅ PPTX saved: {out_pptx}")

    if MODE == "gen_both":
        from docx import Document
        doc = Document()
        doc.add_heading(f"Requirements Update — {_title_label}", 0)
        doc.add_paragraph(f"Generated: {datetime.now().strftime('%d %b %Y')}")
        doc.add_paragraph("")
        for item in _reqs["requirements"]:
            doc.add_heading(item["title"], level=1)
            for b in item["bullets"]:
                doc.add_paragraph(b, style="List Bullet")
        out_docx = f"/opt/outputs/{OUTPUT_SLUG}-{date_str}.docx"
        doc.save(out_docx)
        print(f"✅ DOCX saved: {out_docx}")

# ── MODE: gen_docx ────────────────────────────────────────────────────────────
elif MODE == "gen_docx":
    _reqs_file = f"/opt/outputs/{OUTPUT_SLUG}-requirements.json"
    if not os.path.exists(_reqs_file):
        print(f"ERROR: Requirements file not found: {_reqs_file}")
        print("Run MODE='save_reqs' first.")
        raise SystemExit(0)
    _reqs = json.load(open(_reqs_file))
    _title_label = _reqs.get("title_label", OUTPUT_SLUG)

    sys.path.insert(0, "/opt/outputs/pypackages")
    from docx import Document
    doc = Document()
    doc.add_heading(f"Requirements Update — {_title_label}", 0)
    doc.add_paragraph(f"Generated: {datetime.now().strftime('%d %b %Y')}")
    doc.add_paragraph("")
    for item in _reqs["requirements"]:
        doc.add_heading(item["title"], level=1)
        for b in item["bullets"]:
            doc.add_paragraph(b, style="List Bullet")

    date_str = datetime.now().strftime("%Y-%m-%d")
    out_docx  = f"/opt/outputs/{OUTPUT_SLUG}-{date_str}.docx"
    os.makedirs("/opt/outputs", exist_ok=True)
    doc.save(out_docx)
    print(f"✅ DOCX saved: {out_docx}")

else:
    print(f"Unknown MODE: {MODE}. Valid: search | read_threads | gen_pptx | gen_docx | gen_both")
```

---

## Workflow

**Step 1 — Auth:**
Run with `MODE = "search"`. If output contains "Sign-in required", show the link verbatim, end your turn, wait for confirmation, then re-run.

If re-run succeeds (no "Sign-in required" in output), show a welcome confirmation **before** proceeding to search:

> ✅ Authentication complete! Your Gmail is now connected and ready to use.
>
> Here's what I can do:
> - Search your inbox for emails from a specific person or about a topic
> - Extract requirement-like statements (asks, constraints, decisions, action items)
> - Generate a PPTX slide deck, a DOCX report, or both from the extracted requirements
> - Save a markdown change log mapping each requirement to its affected slide or section
>
> For example:
> - "Extract requirements from emails with John about the project proposal"
> - "Find emails about the Q3 planning document from the last 2 weeks"
> - "Pull requirements from my thread with Sarah and generate a slide deck"
>
> What would you like to do?

Then proceed to answer the user's original request.

**Step 2 — Search:**
Set `PERSON` (and optionally `TOPIC`) from the user's request. Run. Present the disambiguation list:
> "Found 4 threads with John about the proposal. Which should I use? (reply with numbers, 'all', or the subject)"

Wait for the user to confirm before reading anything.

**Step 3 — Read threads:**
Set `MODE = "read_threads"` and `THREAD_IDS = [...]` from the confirmed IDs. Run.

Also read any uploaded files the user provided — they appear in "Retrieved N sources" and are directly readable from context. Do not attempt to fetch their binary.

**Always display the full email content to the user first**, in this format for each thread:

> **From:** ...
> **Subject:** ...
> **Date:** ...
>
> [full body text exactly as printed by the code — do not summarise or truncate]
> ---

Only after showing all thread content: extract requirement-like statements. Show them as a numbered list, then ask for approval or edits:

> Extracted N requirements:
> 1. [requirement]
> 2. [requirement]
> ...
>
> Are these correct? Reply **yes** to proceed, or tell me what to change — for example:
> - "Remove requirement 3"
> - "Change requirement 1 to say X"
> - "Add a requirement for Y"

**Step 3b — Apply edits (if requested):**
If the user requests changes, update the list in your context and show the revised numbered list again. Re-ask for approval — do not proceed to output generation until the user explicitly says **yes**.

**Step 3c — Format selection (after approval):**
Once the user approves the requirements, ask:

> "Great — would you like me to generate:
> - A **PPTX** (PowerPoint slide deck)
> - A **DOCX** (Word document)
> - **Both**"

Wait for the user's choice before running any generation code.

**Step 4 — Change log (write_file):**
Before generating PPTX/DOCX, use `write_file` to save a markdown change log at `/opt/outputs/{OUTPUT_SLUG}-{date}.md`:

```markdown
# Requirements Change Log
Generated: DD Mon YYYY | Source: [person/topic]

## Extracted Requirements
1. [Requirement 1]
2. [Requirement 2]
...

## Change Log
| # | Requirement | Affected Slide / Section |
|---|---|---|
| 1 | [req] | [slide/section] |
```

**Step 5 — Save requirements (always run first after approval):**
Set `MODE = "save_reqs"`, fill `REQUIREMENTS = [("Title", ["bullet 1", "bullet 2"]), ...]` from the approved list, set `OUTPUT_SLUG`. Run. This writes a JSON file so the next step has no data to fill in.

**Step 6 — Generate output:**
Based on the user's format choice, set only `MODE` and `OUTPUT_SLUG` (no REQUIREMENTS needed — read from file):

- PPTX / PowerPoint → `MODE = "gen_pptx"`
- DOCX / Word document → `MODE = "gen_docx"`
- Both → `MODE = "gen_both"`

Run. Files saved to `/opt/outputs/`.

**Step 6 — Deliver:**
> "Pulled 6 requirements from the thread — here's your updated deck and change log. Download from /opt/outputs/."

## Rules
- Use `execute_code` for all MCP calls.
- **Always show the disambiguation list before reading any thread content** — never skip to reading without user confirmation.
- **Always display the full email body to the user before showing extracted requirements** — never skip straight to the requirements list.
- **Always show extracted requirements and offer the user a chance to edit** before asking for the output format.
- **Always re-show the full revised requirements list after any edit** and ask for approval again before proceeding.
- **Always ask for output format (PPTX / DOCX / both) as a separate step after approval** — never assume the format.
- **Never generate PPTX/DOCX without the user explicitly approving the requirements and selecting a format.**
- **Always run MODE="save_reqs" before gen_pptx/gen_docx/gen_both** — never pass REQUIREMENTS inline to the gen step.
- Uploaded files in "Retrieved N sources" are readable directly from context — do not try to call MCP to fetch their binary.
- Never generate output without `REQUIREMENTS` being filled — exit with an error if it's empty.
- If sign-in required: show the URL verbatim, end your turn, wait for confirmation before re-running.
- After successful auth (user just said "done" / "signed in"): always show the welcome confirmation before proceeding — never silently continue.
---
name: gmail-req-harvester
version: 1.0.0
description: Reads a Gmail email thread (and optionally uploaded files), extracts requirement-like statements, then produces a change log (markdown) and a new slide deck (PPTX) or report (DOCX) for review.
tools:
  - execute_code
  - write_file
---

## Overview

Searches Gmail for threads with a named person or topic, presents a disambiguation list, reads confirmed threads, extracts requirements, and generates a **change log** plus your choice of **PPTX** or **DOCX** output. Handles Google sign-in inline.

**Critical: use `execute_code` for every MCP call. Never construct curl or shell commands.**

---

## The execute_code block — set MODE and variables, then run

```python
import urllib.request, urllib.parse, json, os, sys, re
from datetime import datetime

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
MODE         = "search"   # search | read_threads | save_reqs | gen_pptx | gen_docx | gen_both
PERSON       = ""         # name or partial email to search for
TOPIC        = ""         # optional additional keyword
DAYS         = 7          # how far back to search
THREAD_IDS   = []         # set from search output — message IDs confirmed by user
OUTPUT_SLUG  = "requirements"  # slug used in output filenames
REQUIREMENTS = [
    # ("Section / Slide Title", ["bullet point 1", "bullet point 2"]),
]
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

# ── MODE: search ──────────────────────────────────────────────────────────────
if MODE == "search":
    if not PERSON and not TOPIC:
        print("ERROR: Set PERSON (name/email) and/or TOPIC before searching.")
        raise SystemExit(0)

    r = mcp_get("/api/emails", {"username": username, "days": DAYS, "top": 50, "label": "INBOX"})
    if "error" in r:
        print(f"Error: {r['error']}")
        raise SystemExit(0)

    msgs = r.get("value", [])
    hint = (PERSON + " " + TOPIC).lower().strip()
    matched = [m for m in msgs if
               any(w in m.get("from", "").lower() or
                   w in m.get("subject", "").lower() or
                   w in m.get("bodyPreview", "").lower()
                   for w in hint.split() if w)]

    if not matched:
        print(f"No threads found matching '{PERSON or ''} {TOPIC or ''}'.strip() in the last {DAYS} days.")
        raise SystemExit(0)

    print(f"THREADS FOUND ({len(matched)}) — confirm which to use")
    print("=" * 60)
    for i, m in enumerate(matched, 1):
        date  = str(m.get("receivedDateTime", ""))[:10]
        subj  = m.get("subject", "(no subject)")
        frm   = m.get("from", "")
        prev  = m.get("bodyPreview", "")[:100]
        print(f"\n{i}. [{date}] {subj}")
        print(f"   From: {frm}")
        print(f"   Preview: {prev if prev else '(no preview)'}")
        print(f"   ID: {m['id']}")

    print("\nTell me which thread(s) to use (by number, 'all', or the subject) and I'll read them.")

# ── MODE: read_threads ────────────────────────────────────────────────────────
elif MODE == "read_threads":
    if not THREAD_IDS:
        print("ERROR: THREAD_IDS is empty. Run MODE='search' first and set the IDs confirmed by the user.")
        raise SystemExit(0)

    print(f"READING {len(THREAD_IDS)} THREAD(S)")
    print("=" * 60)
    for tid in THREAD_IDS:
        r = mcp_get(f"/api/emails/{tid}", {"username": username})
        if "error" in r:
            print(f"Error reading {tid}: {r['error']}")
            continue
        print(f"\nFROM:    {r.get('from','')}")
        print(f"TO:      {r.get('to','')}")
        print(f"SUBJECT: {r.get('subject','')}")
        print(f"DATE:    {r.get('date','')}")
        print()
        print(r.get("body", "")[:3000])
        print("\n" + "-" * 60)

    print("\n--- END OF THREADS ---")
    print("Extract requirement-like statements (asks, constraints, decisions, action items) from the above.")
    print("Also incorporate any uploaded files shown in Retrieved sources.")
    print("Show the extracted requirements as a numbered list for user approval before generating output.")

# ── MODE: save_reqs ──────────────────────────────────────────────────────────
elif MODE == "save_reqs":
    if not REQUIREMENTS:
        print("ERROR: REQUIREMENTS is empty.")
        raise SystemExit(0)
    _reqs_file = f"/opt/outputs/{OUTPUT_SLUG}-requirements.json"
    os.makedirs("/opt/outputs", exist_ok=True)
    _payload = {
        "title_label": PERSON or TOPIC or OUTPUT_SLUG,
        "requirements": [
            {"title": t, "bullets": b} for t, b in REQUIREMENTS
        ]
    }
    json.dump(_payload, open(_reqs_file, "w"), indent=2)
    print(f"✅ Requirements saved: {_reqs_file}")
    print(f"   {len(REQUIREMENTS)} requirement groups ready for generation.")

# ── MODE: gen_pptx ────────────────────────────────────────────────────────────
elif MODE in ("gen_pptx", "gen_both"):
    _reqs_file = f"/opt/outputs/{OUTPUT_SLUG}-requirements.json"
    if not os.path.exists(_reqs_file):
        print(f"ERROR: Requirements file not found: {_reqs_file}")
        print("Run MODE='save_reqs' first to save the approved requirements.")
        raise SystemExit(0)
    _reqs = json.load(open(_reqs_file))
    _title_label = _reqs.get("title_label", OUTPUT_SLUG)

    sys.path.insert(0, "/opt/outputs/pypackages")
    from pptx import Presentation
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width  = Inches(13.33)
    prs.slide_height = Inches(7.5)

    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = "Requirements Update"
    slide.placeholders[1].text = f"{_title_label} — {datetime.now().strftime('%d %b %Y')}"

    for item in _reqs["requirements"]:
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = item["title"]
        tf = slide.placeholders[1].text_frame
        tf.clear()
        for i, b in enumerate(item["bullets"]):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text  = b
            p.level = 0

    date_str = datetime.now().strftime("%Y-%m-%d")
    out_pptx = f"/opt/outputs/{OUTPUT_SLUG}-{date_str}.pptx"
    os.makedirs("/opt/outputs", exist_ok=True)
    prs.save(out_pptx)
    print(f"✅ PPTX saved: {out_pptx}")

    if MODE == "gen_both":
        from docx import Document
        doc = Document()
        doc.add_heading(f"Requirements Update — {_title_label}", 0)
        doc.add_paragraph(f"Generated: {datetime.now().strftime('%d %b %Y')}")
        doc.add_paragraph("")
        for item in _reqs["requirements"]:
            doc.add_heading(item["title"], level=1)
            for b in item["bullets"]:
                doc.add_paragraph(b, style="List Bullet")
        out_docx = f"/opt/outputs/{OUTPUT_SLUG}-{date_str}.docx"
        doc.save(out_docx)
        print(f"✅ DOCX saved: {out_docx}")

# ── MODE: gen_docx ────────────────────────────────────────────────────────────
elif MODE == "gen_docx":
    _reqs_file = f"/opt/outputs/{OUTPUT_SLUG}-requirements.json"
    if not os.path.exists(_reqs_file):
        print(f"ERROR: Requirements file not found: {_reqs_file}")
        print("Run MODE='save_reqs' first.")
        raise SystemExit(0)
    _reqs = json.load(open(_reqs_file))
    _title_label = _reqs.get("title_label", OUTPUT_SLUG)

    sys.path.insert(0, "/opt/outputs/pypackages")
    from docx import Document
    doc = Document()
    doc.add_heading(f"Requirements Update — {_title_label}", 0)
    doc.add_paragraph(f"Generated: {datetime.now().strftime('%d %b %Y')}")
    doc.add_paragraph("")
    for item in _reqs["requirements"]:
        doc.add_heading(item["title"], level=1)
        for b in item["bullets"]:
            doc.add_paragraph(b, style="List Bullet")

    date_str = datetime.now().strftime("%Y-%m-%d")
    out_docx  = f"/opt/outputs/{OUTPUT_SLUG}-{date_str}.docx"
    os.makedirs("/opt/outputs", exist_ok=True)
    doc.save(out_docx)
    print(f"✅ DOCX saved: {out_docx}")

else:
    print(f"Unknown MODE: {MODE}. Valid: search | read_threads | gen_pptx | gen_docx | gen_both")
```

---

## Workflow

**Step 1 — Auth:**
Run with `MODE = "search"`. If output contains "Sign-in required", show the link verbatim, end your turn, wait for confirmation, then re-run.

If re-run succeeds (no "Sign-in required" in output), show a welcome confirmation **before** proceeding to search:

> ✅ Authentication complete! Your Gmail is now connected and ready to use.
>
> Here's what I can do:
> - Search your inbox for emails from a specific person or about a topic
> - Extract requirement-like statements (asks, constraints, decisions, action items)
> - Generate a PPTX slide deck, a DOCX report, or both from the extracted requirements
> - Save a markdown change log mapping each requirement to its affected slide or section
>
> For example:
> - "Extract requirements from emails with John about the project proposal"
> - "Find emails about the Q3 planning document from the last 2 weeks"
> - "Pull requirements from my thread with Sarah and generate a slide deck"
>
> What would you like to do?

Then proceed to answer the user's original request.

**Step 2 — Search:**
Set `PERSON` (and optionally `TOPIC`) from the user's request. Run. Present the disambiguation list:
> "Found 4 threads with John about the proposal. Which should I use? (reply with numbers, 'all', or the subject)"

Wait for the user to confirm before reading anything.

**Step 3 — Read threads:**
Set `MODE = "read_threads"` and `THREAD_IDS = [...]` from the confirmed IDs. Run.

Also read any uploaded files the user provided — they appear in "Retrieved N sources" and are directly readable from context. Do not attempt to fetch their binary.

**Always display the full email content to the user first**, in this format for each thread:

> **From:** ...
> **Subject:** ...
> **Date:** ...
>
> [full body text exactly as printed by the code — do not summarise or truncate]
> ---

Only after showing all thread content: extract requirement-like statements. Show them as a numbered list, then ask for approval or edits:

> Extracted N requirements:
> 1. [requirement]
> 2. [requirement]
> ...
>
> Are these correct? Reply **yes** to proceed, or tell me what to change — for example:
> - "Remove requirement 3"
> - "Change requirement 1 to say X"
> - "Add a requirement for Y"

**Step 3b — Apply edits (if requested):**
If the user requests changes, update the list in your context and show the revised numbered list again. Re-ask for approval — do not proceed to output generation until the user explicitly says **yes**.

**Step 3c — Format selection (after approval):**
Once the user approves the requirements, ask:

> "Great — would you like me to generate:
> - A **PPTX** (PowerPoint slide deck)
> - A **DOCX** (Word document)
> - **Both**"

Wait for the user's choice before running any generation code.

**Step 4 — Change log (write_file):**
Before generating PPTX/DOCX, use `write_file` to save a markdown change log at `/opt/outputs/{OUTPUT_SLUG}-{date}.md`:

```markdown
# Requirements Change Log
Generated: DD Mon YYYY | Source: [person/topic]

## Extracted Requirements
1. [Requirement 1]
2. [Requirement 2]
...

## Change Log
| # | Requirement | Affected Slide / Section |
|---|---|---|
| 1 | [req] | [slide/section] |
```

**Step 5 — Save requirements (always run first after approval):**
Set `MODE = "save_reqs"`, fill `REQUIREMENTS = [("Title", ["bullet 1", "bullet 2"]), ...]` from the approved list, set `OUTPUT_SLUG`. Run. This writes a JSON file so the next step has no data to fill in.

**Step 6 — Generate output:**
Based on the user's format choice, set only `MODE` and `OUTPUT_SLUG` (no REQUIREMENTS needed — read from file):

- PPTX / PowerPoint → `MODE = "gen_pptx"`
- DOCX / Word document → `MODE = "gen_docx"`
- Both → `MODE = "gen_both"`

Run. Files saved to `/opt/outputs/`.

**Step 6 — Deliver:**
> "Pulled 6 requirements from the thread — here's your updated deck and change log. Download from /opt/outputs/."

## Rules
- Use `execute_code` for all MCP calls.
- **Always show the disambiguation list before reading any thread content** — never skip to reading without user confirmation.
- **Always display the full email body to the user before showing extracted requirements** — never skip straight to the requirements list.
- **Always show extracted requirements and offer the user a chance to edit** before asking for the output format.
- **Always re-show the full revised requirements list after any edit** and ask for approval again before proceeding.
- **Always ask for output format (PPTX / DOCX / both) as a separate step after approval** — never assume the format.
- **Never generate PPTX/DOCX without the user explicitly approving the requirements and selecting a format.**
- **Always run MODE="save_reqs" before gen_pptx/gen_docx/gen_both** — never pass REQUIREMENTS inline to the gen step.
- Uploaded files in "Retrieved N sources" are readable directly from context — do not try to call MCP to fetch their binary.
- Never generate output without `REQUIREMENTS` being filled — exit with an error if it's empty.
- If sign-in required: show the URL verbatim, end your turn, wait for confirmation before re-running.
- After successful auth (user just said "done" / "signed in"): always show the welcome confirmation before proceeding — never silently continue.
