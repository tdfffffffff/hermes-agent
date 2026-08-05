---
name: mailpit-req-harvester
version: 1.0.0
description: Requirements harvester (on-prem simulation) — reads Mailpit email threads, extracts requirement-like statements, generates a change log (markdown) and PPTX/DOCX deliverable. No internet required.
tools:
  - execute_code
  - write_file
---

## Overview

Searches the Mailpit on-prem inbox for threads matching a person or topic, reads confirmed threads, extracts requirements, and generates a **change log** plus PPTX/DOCX output. **No sign-in required** — simulates an on-prem Outlook/Exchange environment.

**Critical: use `execute_code` for every MCP call. Never construct curl or shell commands.**

---

## The execute_code block — set MODE and variables, then run

```python
import urllib.request, urllib.parse, json, os, sys, re
from datetime import datetime

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

# ── SET THESE BEFORE RUNNING ─────────────────────────────────────────────────
MODE         = "search"   # search | read_threads | gen_pptx | gen_docx | gen_both
PERSON       = ""         # name or partial email to search for
TOPIC        = ""         # optional additional keyword
DAYS         = 14         # how far back to search
THREAD_IDS   = []         # set from search output — message IDs confirmed by user
OUTPUT_SLUG  = "requirements"  # slug used in output filenames
REQUIREMENTS = [
    # ("Section / Slide Title", ["bullet point 1", "bullet point 2"]),
]
# ─────────────────────────────────────────────────────────────────────────────

# No auth needed for Mailpit
print("📬 Connected to on-prem mail (Mailpit simulation)")

# ── MODE: search ──────────────────────────────────────────────────────────────
if MODE == "search":
    if not PERSON and not TOPIC:
        print("ERROR: Set PERSON (name/email) and/or TOPIC before searching.")
        raise SystemExit(0)

    r = mcp_get("/api/emails", {"days": DAYS, "top": 50})
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
        print(f"No threads found matching '{(PERSON + ' ' + TOPIC).strip()}' in the last {DAYS} days.")
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
        print(f"   {prev}")
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
        r = mcp_get(f"/api/emails/{tid}")
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

# ── MODE: gen_pptx ────────────────────────────────────────────────────────────
elif MODE in ("gen_pptx", "gen_both"):
    if not REQUIREMENTS:
        print("ERROR: REQUIREMENTS is empty. Fill it from the extracted requirements before running.")
        raise SystemExit(0)
    sys.path.insert(0, "/opt/outputs/pypackages")
    from pptx import Presentation
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width  = Inches(13.33)
    prs.slide_height = Inches(7.5)

    # Title slide
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = "Requirements Update"
    slide.placeholders[1].text = f"{PERSON or TOPIC or OUTPUT_SLUG} — {datetime.now().strftime('%d %b %Y')}"

    # One slide per requirement group
    for title, bullets in REQUIREMENTS:
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = title
        tf = slide.placeholders[1].text_frame
        tf.clear()
        for i, b in enumerate(bullets):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text  = b
            p.level = 0

    date_str = datetime.now().strftime("%Y-%m-%d")
    out_pptx = f"/opt/outputs/{OUTPUT_SLUG}-{date_str}.pptx"
    os.makedirs("/opt/outputs", exist_ok=True)
    prs.save(out_pptx)
    print(f"✅ PPTX saved: {out_pptx}")
    if MODE == "gen_pptx":
        print("Download via the /outputs/ endpoint or SCP.")

    if MODE == "gen_both":
        sys.path.insert(0, "/opt/outputs/pypackages")
        from docx import Document

        doc = Document()
        doc.add_heading(f"Requirements Update — {PERSON or TOPIC or OUTPUT_SLUG}", 0)
        doc.add_paragraph(f"Generated: {datetime.now().strftime('%d %b %Y')}")
        doc.add_paragraph("")
        for title, bullets in REQUIREMENTS:
            doc.add_heading(title, level=1)
            for b in bullets:
                doc.add_paragraph(b, style="List Bullet")
        out_docx = f"/opt/outputs/{OUTPUT_SLUG}-{date_str}.docx"
        doc.save(out_docx)
        print(f"✅ DOCX saved: {out_docx}")
        print("Download via the /outputs/ endpoint or SCP.")

# ── MODE: gen_docx ────────────────────────────────────────────────────────────
elif MODE == "gen_docx":
    if not REQUIREMENTS:
        print("ERROR: REQUIREMENTS is empty. Fill it from the extracted requirements before running.")
        raise SystemExit(0)
    sys.path.insert(0, "/opt/outputs/pypackages")
    from docx import Document

    doc = Document()
    doc.add_heading(f"Requirements Update — {PERSON or TOPIC or OUTPUT_SLUG}", 0)
    doc.add_paragraph(f"Generated: {datetime.now().strftime('%d %b %Y')}")
    doc.add_paragraph("")
    for title, bullets in REQUIREMENTS:
        doc.add_heading(title, level=1)
        for b in bullets:
            doc.add_paragraph(b, style="List Bullet")

    date_str  = datetime.now().strftime("%Y-%m-%d")
    out_docx  = f"/opt/outputs/{OUTPUT_SLUG}-{date_str}.docx"
    os.makedirs("/opt/outputs", exist_ok=True)
    doc.save(out_docx)
    print(f"✅ DOCX saved: {out_docx}")
    print("Download via the /outputs/ endpoint or SCP.")

else:
    print(f"Unknown MODE: {MODE}. Valid: search | read_threads | gen_pptx | gen_docx | gen_both")
```

---

## Workflow

**This skill uses the on-prem Mailpit simulation — no internet or sign-in required.**

**Step 1 — Search:**
Set `PERSON` (and optionally `TOPIC`) from the user's request. Run. Present the disambiguation list:
> "Found 3 threads with Raj about the requirements. Which should I use? (reply with numbers, 'all', or the subject)"

Wait for the user to confirm before reading anything.

**Step 2 — Read threads:**
Set `MODE = "read_threads"` and `THREAD_IDS = [...]` from the confirmed IDs. Run.

Also read any uploaded files the user provided — they appear in "Retrieved N sources" and are directly readable from context. Do not attempt to fetch their binary.

After printing threads: extract requirement-like statements from the content. Show as a numbered list:
> "Extracted 6 requirements:
> 1. Dashboard must refresh every ≤5 seconds
> 2. Audit logs must be exportable as CSV and PDF
> ..."
>
> "Shall I generate the change log and output files from these?"

**Step 3 — Change log (write_file):**
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

**Step 4 — Output format:**
Ask: "Would you like a PPTX slide deck, a DOCX report, or both?"

- PPTX → set `MODE = "gen_pptx"`
- DOCX → set `MODE = "gen_docx"`
- Both → set `MODE = "gen_both"`

Fill `REQUIREMENTS = [("Title", ["bullet 1", "bullet 2"]), ...]` from the extracted list. Run.

**Step 5 — Deliver:**
> "Pulled X requirements from the thread — here's your updated deck and change log. Download from /opt/outputs/."

## Rules
- Use `execute_code` for all MCP calls.
- **Always show the disambiguation list before reading any thread content** — never skip to reading without user confirmation.
- **Always show extracted requirements for user approval before generating output** — never generate PPTX/DOCX without the user saying yes.
- Uploaded files in "Retrieved N sources" are readable directly from context — do not try to call MCP to fetch their binary.
- Never generate output without `REQUIREMENTS` being filled — exit with an error if it's empty.
