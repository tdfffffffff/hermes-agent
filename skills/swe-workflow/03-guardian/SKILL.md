---
name: code-and-api-guardian
version: 1.0.0
description: Unified security analysis for AI engineers. Triages input (Python/bash scripts, Dockerfiles, IaC, RAG pipelines, live API traces) and routes to the appropriate checklist. All findings output via report-formatter structure to /opt/outputs/.
tools:
  - terminal
  - read_file
  - execute_code
  - memory
---

## Overview

Single entry point for security analysis. Input can be: Python/bash scripts, Dockerfiles, docker-compose files, Terraform/ARM/Bicep/NSG configs, RAG pipeline code, live API failure traces, or any mix. Triage automatically — never ask the user to choose a path unless input is genuinely ambiguous.

---

## Step 1 — Triage

Classify the input before doing anything else:

| Signal in input | Route |
|-----------------|-------|
| Source code file / paste, no API failure description | STATIC only |
| HTTP status code, endpoint URL, curl output, or API error description | LIVE only |
| Source code AND an API failure trace/description together | BOTH |
| Vague description with no code and no trace | Ask: "Is this a code review, API debug, or both?" |

---

## Step 2A — Static Path: Artifact Type Sub-Router

Before running any checklist, identify the artifact type:

| Type | Detection |
|------|-----------|
| **General script** | `.py`, `.sh`, `.bash`, or general scripting syntax |
| **Dockerfile / docker-compose** | `FROM`, `RUN`, `EXPOSE`, `services:` with `image:` key |
| **Cloud / IaC** | Terraform `.tf`, ARM JSON, Bicep, NSG rule JSON/YAML |
| **RAG / data pipeline** | Functions named ingest/embed/retrieve/chunk; vector store calls; LangChain/LlamaIndex/FAISS imports |

If the artifact spans two types, run both matching checklists and merge findings.

### Checklist A1 — General Script (Python / Bash)

Record exact line numbers for every finding.

1. **Hardcoded secrets / credentials** — API keys, passwords, tokens, or base64 blobs assigned to variables; `os.environ.get()` calls with hardcoded fallback defaults
2. **Command injection** — `subprocess.run(..., shell=True)` with any user-controlled input; `os.system()` calls; bash `eval`/`exec` with variables; f-string or string concatenation into shell commands
3. **Insecure file permissions** — `os.chmod(..., 0o777)` or `0o666`; `chmod 777` or `chmod a+w` in bash
4. **Unsafe subprocess calls** — `shell=True` even with no user input (allows shell metacharacters); `os.popen()`; `subprocess.Popen` with unchecked return codes
5. **Unvalidated user input** — `input()` or `sys.argv` values passed to file operations, SQL queries, shell commands, or network calls without validation or sanitisation
6. **Container escape risks** — mounting `/var/run/docker.sock`; running as root inside a container; `--privileged` flag; volume mounts including host-sensitive paths (`/etc`, `/proc`, `/sys`)

### Checklist A2 — Dockerfile / docker-compose

1. **Running as root** — no `USER` instruction (defaults to root); explicit `USER root`
2. **Unpinned / `:latest` base image** — must use a specific version tag or digest; `:latest` allows silent supply-chain drift
3. **Secrets baked into image layers** — `ENV API_KEY=...` with a value; `ARG SECRET=...` with a default; `COPY .env /app/` or `COPY credentials.json /app/`; these persist in layer history even if later `RUN rm`'d
4. **Missing platform hardening flags** — flag any absent from: `read_only: true`, `cap_drop: [ALL]`, `security_opt: no-new-privileges:true`, `tmpfs` mounts for `/tmp` and `/run`
5. **Unnecessarily exposed ports** — `EXPOSE` on ports the service does not actually use
6. **Mounted Docker socket** — `- /var/run/docker.sock:/var/run/docker.sock` is a container-to-host escape vector; always Critical

### Checklist A3 — Cloud / IaC (Terraform, ARM, Bicep, NSG Rules)

1. **Wide-open inbound rules** — `source_address_prefix: "*"` or `"0.0.0.0/0"` with `destination_port_range: "*"` or sensitive ports (22, 3389, 6443, management ports); Critical
2. **Publicly readable storage** — blob containers with `public_access: blob` or `container`; any storage resource with a public endpoint and no auth requirement
3. **Over-broad IAM roles** — assigning `Owner`, `Contributor`, or a wildcard `*` action on `*` resource where a scoped built-in role would cover the workload
4. **Over-permissive Key Vault access policies** — granting `list`/`set`/`delete` on secrets or keys when the workload only needs `get`
5. **Inbound allow without matching outbound restriction** — a rule permits traffic in, but no rule limits what that resource can reach outbound; flag where deny-default-outbound is the expected baseline

### Checklist A4 — RAG / Data Pipeline

1. **Prompt injection via retrieval** — `ingest()` or `load_documents()` accepts content from untrusted sources (uploaded files, emails, external URLs) without sanitisation; malicious instructions embedded in ingested docs can later be retrieved and influence agent behaviour
2. **Missing per-user access control at retrieval** — `retrieve()` or `similarity_search()` returns chunks without checking whether the requesting user has permission to view the source document; can expose restricted content across tenants/users
3. **Unencrypted vector store / chunk storage** — embeddings or raw chunks written to disk or a remote store without encryption-at-rest consistent with the source document's data classification
4. **No provenance / citation tracking** — retrieved chunks have no metadata linking them to their source document; makes it impossible to audit answers or redact a compromised source
5. **Unsafe model / artifact loading** — `pickle.load()` or `torch.load()` from untrusted sources; `yaml.load()` without `Loader=yaml.SafeLoader`; `eval()` on external content; deserialising untrusted ML artifacts is equivalent to arbitrary code execution

---

## Step 2B — Live API Debug Path

Walk these layers **in strict order**. Do not skip a layer because a later one seems more likely. Resolve each before advancing.

Issue actual `curl` commands via terminal where the agent has network reach. If it does not, reason through the trace the user provided.

**Layer 1 — Connectivity** — can we reach the host at all?
```bash
curl -v --max-time 5 https://HOST/
```
If timeout or DNS failure: report connectivity failure, stop, do not proceed to TLS.

**Layer 1.5 — Timeouts** — connect-slow vs read-slow?
```bash
curl --connect-timeout 5 --max-time 30 https://HOST/
```
Connect timeout = network/firewall issue. Read timeout = server-side processing issue.

**Layer 2 — TLS / SSL** — cert valid and trusted?
```bash
curl -v --cacert /etc/ssl/certs/certbundle.crt https://HOST/
```
The environment uses a corporate cert bundle at `/etc/ssl/certs/certbundle.crt`. Add `--cacert` flag if TLS handshake fails.

**Layer 3 — Auth** — credentials correct and unexpired?
- Check token format: Bearer vs Basic vs API key header name
- Decode JWT expiry if applicable:
```bash
python3 -c "import base64,json; tok='YOUR_TOKEN'; print(json.loads(base64.b64decode(tok.split('.')[1]+'==').decode()))"
```
- Test a minimal request with a freshly-obtained token

**Layer 4 — Request format** — payload matches server expectations?
- Compare `Content-Type` header against what the server accepts
- Check for missing required fields or unexpected field names
- Validate JSON structure against any available schema or documentation

**Layer 5 — Response parsing** — client code handles what came back?
- A `200 OK` can contain an error in the body; check `response.json()["error"]` not just `response.status_code`
- Check encoding: UTF-8 vs Latin-1 mismatches in response body

**Layer 6 — Semantics** — data means what we assume?
- Timestamps in unexpected timezone
- Pagination: is this page 1 of 10, assumed to be all results?
- Null vs missing key: different meaning in some APIs

---

## Step 2C — Both Paths

Run Step 2A first (static). Surface findings. Then run Step 2B (live). Where a static finding and a live finding share a root cause (e.g. wrong env var → stale token → 401), group them as one finding with a combined fix.

---

## Step 3 — Output Format

Format all findings as follows. Do not invent a different structure.

```
OFFICIAL (OPEN) \ SENSITIVE NORMAL
=======================================
GUARDIAN SECURITY REPORT
Artifact: [filename or endpoint]
Artifact Type: [General Script / Dockerfile / Cloud IaC / RAG Pipeline / Live API / Mixed]
Paths run: [Static / Live / Both]
Date: [YYYY-MM-DD]
=======================================

EXECUTIVE SUMMARY
[2-3 sentences: what was reviewed, the most critical finding, recommended immediate action]

FINDINGS
| ID | Description | Severity | Affected Component | Line / Layer | Status |
|----|-------------|----------|--------------------|--------------|--------|
| F1 | ...         | Critical | ...                | L14          | Open   |

Severity: Critical (exploitable now) / High (likely exploitable) / Medium (bad practice, low immediate risk) / Low (minor) / Pass
Each Description MUST be 3+ sentences: (1) what the vulnerable code does and what makes it insecure — name the specific function, variable, or line; (2) the concrete exploit path — describe how an attacker triggers or abuses this, including any preconditions; (3) the impact — what the attacker gains (credential theft, RCE, auth bypass, data exfiltration, etc.). Write a narrative a developer can act on — not a label.

**F1 — High — [component] (issue type) — L64, L109**
Description of the finding and why it is exploitable.

> **Recommended Fix**
> WHY: one-sentence explanation of the attack vector this closes

**BEFORE** *(L64)*
```language
exact insecure code from file
```
**AFTER**
```language
corrected replacement snippet
```

---

[Repeat for each finding]

RECOMMENDED ACTIONS
| Finding | Severity | Lines | Action | Timeframe |
|---------|----------|-------|--------|-----------|
| F1 | High | L64, L109 | Validate paths against allow-list | Immediately |

Timeframe: Critical/High → Immediately · Medium → This sprint · Low → Next window

Rules:
- Quote real code from the file — never use placeholder names like `your_variable`
- Every Critical/High finding must have BEFORE/AFTER in the fix block above
- If the fix spans multiple lines, show the full changed block
- For secrets/hardcoded credentials: show the full line and recommend the specific env var name to use

NEXT REVIEW DATE: [today + 30 days]

REVIEWER NOTES
[Leave blank — human reviewer fills in to flag false positives, missed findings, or noise.
This field is read by guardian-feedback-digest for continuous improvement.]
```

Save to:
```
/opt/outputs/guardian-report-[artifact-name]-[YYYY-MM-DD].md
```

---

## Step 4 — HTML Dashboard (MANDATORY — do not respond to the user until this prints "Saved:")

Immediately after saving the markdown report, run this `execute_code` block. Fill in only the DATA SECTION at the top with values from the actual scan. Do not modify anything below the DATA SECTION.

```python
import os, json, datetime, urllib.request, urllib.parse

# ═══ DATA SECTION — fill in from the actual scan ══════════════════════
artifact_name = "FILENAME"          # exact filename, e.g. "auth.py"
artifact_type = "TYPE"              # General Script (Python/Bash) / Dockerfile / Cloud IaC / RAG Pipeline / Live API
paths_run     = "Static"            # Static / Live / Both
scan_date     = "YYYY-MM-DD"        # today's date

exec_summary  = "EXECUTIVE_SUMMARY" # 2-3 sentence summary from the report

findings = [
    # One dict per finding. vuln_type = short keyword for CVE search (e.g. "path traversal", "command injection", "hardcoded secret")
    {"id": "F1", "description": "DESCRIPTION", "severity": "High",
     "component": "COMPONENT", "line": "L1", "status": "Open",
     "vuln_type": "SHORT_CVE_KEYWORD"},
]

actions = [
    # One dict per action, severity-ordered. before/after = exact code snippets from the file.
    {"id": "F1", "severity": "High", "line": "L1",
     "what": "ONE_SENTENCE_FIX",
     "before": "EXACT_INSECURE_CODE_FROM_FILE",
     "after": "CORRECTED_REPLACEMENT",
     "why": "ONE_SENTENCE_ATTACK_VECTOR"},
]
# ══════════════════════════════════════════════════════════════════════

import datetime as _dt
next_review = (_dt.datetime.strptime(scan_date, '%Y-%m-%d') + _dt.timedelta(days=30)).strftime('%Y-%m-%d')
slug = artifact_name.lower().replace(' ','-').replace('/','-').replace('.','-')

# CVE enrichment (best-effort — continues on failure)
cve_enrichment = {}
for f in findings:
    try:
        q = urllib.parse.urlencode({"vuln_type": f.get('vuln_type', f['description'][:40]), "max_results": 2})
        with urllib.request.urlopen(f"http://hermes-cve-mcp:8081/api/search?{q}", timeout=5) as r:
            cve_enrichment[f['id']] = json.loads(r.read().decode())
    except Exception:
        cve_enrichment[f['id']] = {"results": []}

# Colour maps
SC  = {'Critical':'#fb7185','High':'#fbbf24','Medium':'#a78bfa','Low':'#34d399','Pass':'#64748b'}
SBG = {'Critical':'rgba(136,19,55,.15)','High':'rgba(120,53,15,.15)','Medium':'rgba(76,29,149,.15)','Low':'rgba(6,78,59,.15)','Pass':'rgba(15,23,42,.3)'}
SBR = {'Critical':'rgba(251,113,133,.3)','High':'rgba(251,191,36,.3)','Medium':'rgba(167,139,250,.3)','Low':'rgba(52,211,153,.3)','Pass':'#1e293b'}
SBL = {'Critical':'#fb7185','High':'#fbbf24','Medium':'#a78bfa','Low':'#34d399','Pass':'#334155'}

counts = {s: sum(1 for f in findings if f.get('severity')==s) for s in ['Critical','High','Medium','Low']}
total  = len(findings)

sev_boxes = ''.join(
    f'<div class="sev-box" style="border-color:{SBR.get(s,"#1e293b")};background:{SBG.get(s,"rgba(15,23,42,.3)")}">'
    f'<div class="sev-num" style="color:{SC.get(s,"#64748b")}">{counts.get(s,0)}</div>'
    f'<div class="sev-label">{s}</div></div>'
    for s in ['Critical','High','Medium','Low']
)

def _esc(s): return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')

def _timeframe(sev):
    return {'Critical':'Immediately','High':'Immediately','Medium':'This sprint'}.get(sev,'Next window')

action_map = {a['id']: a for a in actions if isinstance(a, dict)}

findings_html = ''
for f in findings:
    sev  = f.get('severity','Low')
    act  = action_map.get(f['id'], {})
    before = _esc(act.get('before',''))
    after  = _esc(act.get('after',''))
    why    = _esc(act.get('why',''))
    fix_block = ''
    if act and (before or after or why):
        fix_block = (
            f'<div class="fix-block">'
            f'<div class="fix-header">RECOMMENDED FIX</div>'
            f'<div class="fix-why">WHY: {why}</div>'
            f'<div class="code-label before-label">BEFORE</div>'
            f'<pre class="code-pre before-pre">{before}</pre>'
            f'<div class="code-label after-label">AFTER</div>'
            f'<pre class="code-pre after-pre">{after}</pre>'
            f'</div>'
        )
    findings_html += (
        f'<div class="finding" style="border-left-color:{SBL.get(sev,"#334155")}">'
        f'<div class="finding-header">'
        f'<div class="finding-title">'
        f'<span class="finding-id">{_esc(f["id"])}</span>'
        f'<span class="finding-component">{_esc(f.get("component",""))}</span>'
        f'</div>'
        f'<div style="display:flex;align-items:center;gap:.5rem">'
        f'<span class="sev-badge" style="color:{SC.get(sev,"#64748b")};background:{SBG.get(sev,"rgba(15,23,42,.3)")};border-color:{SBR.get(sev,"#1e293b")}">{sev}</span>'
        f'<span class="finding-line">{_esc(f.get("line",""))}</span>'
        f'</div>'
        f'</div>'
        f'<div class="finding-desc">{_esc(f.get("description",""))}</div>'
        f'{fix_block}'
        f'<div class="finding-status">Status: <strong>{_esc(f.get("status","Open"))}</strong></div>'
        f'</div>'
    )

cve_rows = ''
for fid, data in cve_enrichment.items():
    for cve in data.get('results',[])[:2]:
        sev   = (cve.get('severity') or '').title()
        score = str(cve.get('cvss_score','—')) if cve.get('cvss_score') else '—'
        cve_rows += (
            f'<tr><td style="font-family:monospace;font-size:.72rem">{fid}</td>'
            f'<td><a href="{cve.get("url","")}" style="color:#9cdcfe;font-family:monospace;font-size:.72rem">{cve.get("id","")}</a></td>'
            f'<td style="font-weight:700;color:{SC.get(sev,"#64748b")};font-size:.72rem">{sev}</td>'
            f'<td style="font-weight:600;color:#e2e8f0;font-size:.72rem">{score}</td>'
            f'<td style="color:#94a3b8;font-size:.72rem">{str(cve.get("description",""))[:120]}…</td></tr>'
        )
if not cve_rows:
    cve_rows = '<tr><td colspan="5" style="color:#475569;text-align:center;padding:20px">CVE enrichment unavailable</td></tr>'

actions_html = (
    '<table style="width:100%;border-collapse:collapse">'
    '<tr>'
    '<th style="text-align:left;color:#475569;font-size:.65rem;font-weight:600;padding:.4rem .75rem;background:rgba(15,23,42,.6);border-bottom:1px solid #1e293b">Finding</th>'
    '<th style="text-align:left;color:#475569;font-size:.65rem;font-weight:600;padding:.4rem .75rem;background:rgba(15,23,42,.6);border-bottom:1px solid #1e293b">Severity</th>'
    '<th style="text-align:left;color:#475569;font-size:.65rem;font-weight:600;padding:.4rem .75rem;background:rgba(15,23,42,.6);border-bottom:1px solid #1e293b">Lines</th>'
    '<th style="text-align:left;color:#475569;font-size:.65rem;font-weight:600;padding:.4rem .75rem;background:rgba(15,23,42,.6);border-bottom:1px solid #1e293b">Action</th>'
    '<th style="text-align:left;color:#475569;font-size:.65rem;font-weight:600;padding:.4rem .75rem;background:rgba(15,23,42,.6);border-bottom:1px solid #1e293b">Timeframe</th>'
    '</tr>'
)
for a in actions:
    if isinstance(a, dict):
        sev = a.get('severity', '')
        tf  = _timeframe(sev)
        actions_html += (
            f'<tr>'
            f'<td style="padding:.4rem .75rem;border-bottom:1px solid #0f172a;font-size:.72rem;color:#e2e8f0;font-family:monospace">{_esc(a.get("id",""))}</td>'
            f'<td style="padding:.4rem .75rem;border-bottom:1px solid #0f172a;font-size:.72rem;font-weight:700;color:{SC.get(sev,"#64748b")}">{_esc(sev)}</td>'
            f'<td style="padding:.4rem .75rem;border-bottom:1px solid #0f172a;font-size:.72rem;color:#94a3b8">{_esc(a.get("line",""))}</td>'
            f'<td style="padding:.4rem .75rem;border-bottom:1px solid #0f172a;font-size:.72rem;color:#94a3b8">{_esc(a.get("what",""))}</td>'
            f'<td style="padding:.4rem .75rem;border-bottom:1px solid #0f172a;font-size:.72rem;color:#64748b">{_esc(tf)}</td>'
            f'</tr>'
        )
    else:
        actions_html += (
            f'<tr><td colspan="5" style="padding:.4rem .75rem;border-bottom:1px solid #0f172a;font-size:.72rem;color:#94a3b8">{_esc(str(a))}</td></tr>'
        )
actions_html += '</table>'

html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{artifact_name} — Guardian Security Report</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{font-family:"JetBrains Mono",monospace;background:#020617;min-height:100vh;padding:2rem;color:white}}
  .container{{max-width:1100px;margin:0 auto}}
  .header{{margin-bottom:2rem}}
  .header-row{{display:flex;align-items:center;gap:1rem;margin-bottom:.5rem}}
  .pulse-dot{{width:12px;height:12px;background:#fb7185;border-radius:50%;animation:pulse 2s infinite;flex-shrink:0}}
  @keyframes pulse{{0%,100%{{opacity:1;box-shadow:0 0 0 0 rgba(251,113,133,.4)}}50%{{opacity:.7;box-shadow:0 0 0 6px rgba(251,113,133,0)}}}}
  h1{{font-size:1.4rem;font-weight:700}}
  .subtitle{{color:#94a3b8;font-size:.8rem;margin-left:1.75rem}}
  .sev-summary{{display:flex;gap:1rem;margin:1.5rem 0;flex-wrap:wrap}}
  .sev-box{{background:rgba(15,23,42,.6);border:1px solid #1e293b;border-radius:.75rem;padding:.75rem 1.25rem;text-align:center}}
  .sev-num{{font-size:1.8rem;font-weight:700}}
  .sev-label{{color:#64748b;font-size:.68rem;margin-top:.2rem}}
  .section-title{{font-size:.68rem;font-weight:600;letter-spacing:.1em;color:#475569;text-transform:uppercase;margin:2rem 0 .75rem;padding-bottom:.4rem;border-bottom:1px solid #1e293b;display:flex;justify-content:space-between;align-items:center}}
  .cnt-badge{{background:#1e293b;color:#94a3b8;font-size:.65rem;padding:2px 8px;border-radius:10px}}
  .exec{{color:#94a3b8;font-size:.8rem;line-height:1.7}}
  .finding{{background:rgba(15,23,42,.5);border:1px solid #1e293b;border-left:3px solid #334155;border-radius:.5rem;padding:1rem;margin-bottom:.5rem}}
  .finding-header{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:.5rem}}
  .finding-title{{display:flex;align-items:center;gap:.6rem;flex-wrap:wrap}}
  .finding-id{{color:#475569;font-size:.7rem;font-weight:700}}
  .finding-component{{font-size:.8rem;color:#e2e8f0;font-weight:600}}
  .finding-line{{font-size:.68rem;color:#334155}}
  .sev-badge{{font-size:.7rem;font-weight:700;padding:2px 8px;border-radius:.25rem;border:1px solid}}
  .finding-desc{{color:#94a3b8;font-size:.78rem;margin-bottom:.35rem;line-height:1.55}}
  .finding-status{{font-size:.7rem;color:#334155}}
  .finding-status strong{{color:#475569}}
  table{{width:100%;border-collapse:collapse}}
  th{{text-align:left;color:#475569;font-size:.65rem;font-weight:600;padding:.4rem .75rem;background:rgba(15,23,42,.6);border-bottom:1px solid #1e293b}}
  td{{padding:.4rem .75rem;border-bottom:1px solid #0f172a;vertical-align:top}}
  tr:last-child td{{border-bottom:none}}
  .note-box{{background:rgba(15,23,42,.5);border:1px solid #1e293b;border-radius:.5rem;padding:.75rem 1rem;font-size:.78rem;color:#94a3b8;margin-top:.75rem}}
  .footer{{text-align:center;margin-top:1.5rem;color:#475569;font-size:.72rem}}
  .fix-block{{margin:.75rem 0 .35rem;background:rgba(2,6,23,.5);border:1px solid #1e293b;border-radius:.5rem;padding:.875rem 1rem}}
  .fix-header{{font-size:.62rem;font-weight:700;letter-spacing:.1em;color:#475569;text-transform:uppercase;margin-bottom:.5rem;padding-bottom:.35rem;border-bottom:1px solid #1e293b}}
  .fix-why{{color:#94a3b8;font-size:.72rem;margin-bottom:.65rem;line-height:1.55}}
  .code-label{{font-size:.6rem;font-weight:700;letter-spacing:.1em;margin:.4rem 0 .15rem}}
  .before-label{{color:#fb7185}}
  .after-label{{color:#34d399}}
  .code-pre{{margin:0 0 .5rem;padding:.5rem .75rem;background:#0f172a;border-radius:.35rem;font-size:.72rem;white-space:pre-wrap;word-break:break-all}}
  .before-pre{{color:#fca5a5;border-left:2px solid rgba(251,113,133,.5)}}
  .after-pre{{color:#86efac;border-left:2px solid rgba(52,211,153,.5)}}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="header-row"><div class="pulse-dot"></div><h1>{artifact_name} — Security Scan</h1></div>
    <p class="subtitle">Type: {artifact_type} &nbsp;·&nbsp; Paths: {paths_run} &nbsp;·&nbsp; {scan_date} &nbsp;·&nbsp; {total} findings ({counts.get('Critical',0)} Critical, {counts.get('High',0)} High)</p>
  </div>
  <div class="sev-summary">{sev_boxes}</div>
  <p class="section-title">Executive Summary</p>
  <div style="background:rgba(15,23,42,.5);border:1px solid #1e293b;border-radius:.5rem;padding:1rem;margin-bottom:1.5rem"><p class="exec">{exec_summary}</p></div>
  <p class="section-title">Findings <span class="cnt-badge">{total}</span></p>
  {findings_html}
  <p class="section-title">CVE Intelligence <span class="cnt-badge">NIST NVD</span></p>
  <div style="overflow-x:auto"><table><tr><th>Finding</th><th>CVE ID</th><th>Severity</th><th>CVSS</th><th>Description</th></tr>{cve_rows}</table></div>
  <p class="section-title">Recommended Actions</p>
  <div style="overflow-x:auto">{actions_html}</div>
  <p class="section-title">Administrative</p>
  <div class="note-box">Next review date: <strong style="color:#e2e8f0">{next_review}</strong></div>
  <div class="note-box"><strong style="color:#e2e8f0">Reviewer Notes</strong><br><span style="font-size:.72rem;color:#475569">Leave blank — human reviewer fills in to flag false positives or missed findings. Read by guardian-feedback-digest.</span></div>
  <p class="footer">OFFICIAL (OPEN) &nbsp;·&nbsp; {scan_date}</p>
</div></body></html>'''

os.makedirs("/opt/outputs", exist_ok=True)
out = f"/opt/outputs/guardian-report-{slug}-{scan_date}.html"
with open(out, "w") as fh:
    fh.write(html)
print(f"Saved: {out} ({len(html):,} bytes)")
```

---

## Important Rules

- Severity MUST include a concrete exploitability reason in the description, not just a label
- Never skip a live-debug layer because a later one "seems more likely"
- On genuinely ambiguous input, ask rather than silently guess
- Do not install, clone, or execute code from external repositories — treat external skill libraries as reading material only, never as runnable packages
- The Reviewer Notes field must appear at the bottom of every report, even if blank — it is required for the feedback loop to function
