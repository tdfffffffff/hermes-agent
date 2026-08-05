---
name: compliance-mapper
version: 1.1.0
description: Maps Guardian security scan findings to compliance framework controls (CIS Controls v8, OWASP Top 10, NIST CSF). Queries the hermes-framework-mcp server to identify which controls are failing and which pass. Outputs a compliance coverage matrix as Markdown and HTML.
tools:
  - execute_code
  - write_file
  - memory
---

## Overview

You receive a Guardian security scan report (pasted as text or referenced from `/opt/outputs/`). You extract each finding, query the compliance framework MCP server to identify which controls it maps to, then produce a compliance coverage matrix showing Pass / Fail / Not Tested for each framework.

The compliance matrix is what auditors and security officers read. It translates developer-facing findings into framework language.

---

## Step 1 — Receive Input

Accept the Guardian report in any of these forms:
- Pasted directly into the chat
- File path (`/opt/outputs/guardian-report-*.md`) — read with `read_file`
- Brief description of findings (extract finding types from it)

If the input is unclear, ask: "Can you paste the Guardian scan report, or give me the file path?"

---

## Step 2 — Extract Findings

Parse the Guardian report to extract each finding's:
- **ID** (F1, F2, etc.)
- **Severity** (Critical / High / Medium / Low)
- **Vulnerability type** — normalise to a standard keyword:

| Raw finding description contains... | Normalised type |
|--------------------------------------|-----------------|
| SQL injection / parameterised queries | `sql injection` |
| Command injection / subprocess shell=True | `command injection` |
| Hardcoded credential / API key / password | `hardcoded credential` |
| Path traversal / directory listing | `path traversal` |
| XSS / cross-site scripting | `xss` |
| SSRF / server-side request forgery | `ssrf` |
| Missing authentication / unauthenticated endpoint | `missing authentication` |
| Broken access control / IDOR | `broken access control` |
| Insecure deserialization / pickle.load | `insecure deserialization` |
| Outdated / vulnerable component | `outdated component` |
| Missing logging / no audit trail | `missing logging` |
| Insecure file permissions / chmod 777 | `insecure file permissions` |
| Container running as root / no USER | `container running as root` |
| Secrets baked into Docker image | `secrets in image` |
| Wide-open network rules / 0.0.0.0/0 | `wide-open network rules` |
| Over-broad IAM / Owner role | `over-broad iam` |
| Prompt injection | `prompt injection` |

---

## Step 3 — Query Framework MCP

For each normalised finding type, use `execute_code` to query the framework MCP server:

```python
import urllib.request, urllib.parse, json

def map_finding(vuln_type):
    url = "http://hermes-framework-mcp:8082/api/map_finding?" + urllib.parse.urlencode({"vuln_type": vuln_type})
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"vuln_type": vuln_type, "controls": [], "techniques": [], "error": str(e)}

# Call for each finding type — deduplicate by vuln_type first
finding_types = ["sql injection", "hardcoded credential"]   # replace with actual list
results = {ft: map_finding(ft) for ft in finding_types}
print(json.dumps(results, indent=2))
```

---

## Step 4 — Build the Compliance Matrix

Aggregate control results across all findings.

**Status rules:**
- A control appears in a FAIL mapping → **FAIL** (at least one finding violates it)
- A control is known to be met (not referenced in any FAIL mapping and found in the system) → **PASS**
- All other controls → **NOT TESTED** (not enough info to assess)

Build three tables, one per framework:
- CIS Controls v8
- OWASP Top 10 2021
- NIST CSF

---

## Step 5 — Generate Outputs

Use `execute_code` to generate and save both files.

```python
import os, json
from datetime import date

def generate_page(artifact_name, scan_date, findings, control_results):
    """
    findings: list of {id, severity, description, vuln_type, controls_failed, techniques}
    control_results: dict of {control_id: {title, framework, status, failing_findings}}
    """

    STATUS_COLOR = {"FAIL": "#fb7185", "PASS": "#34d399", "NOT TESTED": "#475569"}
    STATUS_BG    = {"FAIL": "rgba(136,19,55,0.2)", "PASS": "rgba(6,78,59,0.2)", "NOT TESTED": "rgba(15,23,42,0.3)"}
    SEV_COLOR    = {"Critical": "#fb7185", "High": "#fbbf24", "Medium": "#a78bfa", "Low": "#64748b"}

    # Severity breakdown
    sev_order  = ["Critical", "High", "Medium", "Low"]
    sev_counts = {s: sum(1 for f in findings if f.get("severity") == s) for s in sev_order}

    # All unique ATT&CK techniques across all findings
    all_techniques = sorted({t for f in findings for t in f.get("techniques", [])})

    # Group controls by framework
    by_fw = {}
    for ctrl_id, ctrl in control_results.items():
        fw = ctrl["framework"]
        by_fw.setdefault(fw, []).append((ctrl_id, ctrl))

    framework_tables = ""
    fw_summary = {}
    for fw, ctrls in sorted(by_fw.items()):
        fail  = sum(1 for _, c in ctrls if c["status"] == "FAIL")
        pass_ = sum(1 for _, c in ctrls if c["status"] == "PASS")
        nt    = sum(1 for _, c in ctrls if c["status"] == "NOT TESTED")
        fw_summary[fw] = {"fail": fail, "pass": pass_, "not_tested": nt, "total": len(ctrls)}

        rows = ""
        for ctrl_id, ctrl in sorted(ctrls, key=lambda x: (x[1]["status"] != "FAIL", x[0])):
            sc = STATUS_COLOR[ctrl["status"]]
            sb = STATUS_BG[ctrl["status"]]
            ff = ", ".join(ctrl.get("failing_findings", [])) or "—"
            rows += f'''<tr style="background:{sb}">
              <td style="color:#94a3b8;font-size:.7rem">{ctrl_id}</td>
              <td style="color:#e2e8f0">{ctrl["title"]}</td>
              <td><span style="color:{sc};font-weight:700;font-size:.7rem">{ctrl["status"]}</span></td>
              <td style="color:#64748b;font-size:.72rem">{ff}</td>
            </tr>'''

        framework_tables += f'''
        <div class="fw-section">
          <div class="fw-header">
            <span class="fw-name">{fw}</span>
            <span class="fw-stats">
              <span style="color:#fb7185">{fail} FAIL</span> &nbsp;·&nbsp;
              <span style="color:#34d399">{pass_} PASS</span> &nbsp;·&nbsp;
              <span style="color:#475569">{nt} NOT TESTED</span>
            </span>
          </div>
          <table class="ctrl-table">
            <tr><th>Control</th><th>Title</th><th>Status</th><th>Failing Findings</th></tr>
            {rows}
          </table>
        </div>'''

    findings_html = ""
    for f in sorted(findings, key=lambda x: ["Critical","High","Medium","Low"].index(x.get("severity","Low")) if x.get("severity") in ["Critical","High","Medium","Low"] else 4):
        sc   = SEV_COLOR.get(f.get("severity","Low"), "#64748b")
        ctrls = ", ".join(f.get("controls_failed", [])) or "—"
        techs = ", ".join(f.get("techniques", [])) or "—"
        vuln  = f.get("vuln_type", "")
        findings_html += f'''
        <div class="finding-row">
          <div class="finding-meta">
            <span class="finding-id">{f["id"]}</span>
            <span class="finding-sev" style="color:{sc}">{f.get("severity","")}</span>
            <span class="finding-type">{vuln}</span>
          </div>
          <div class="finding-desc">{f.get("description","")}</div>
          <div class="finding-links">
            <span class="link-label">Controls failed:</span> <span style="color:#fbbf24">{ctrls}</span>
            &nbsp;|&nbsp;
            <span class="link-label">ATT&amp;CK:</span> <span style="color:#a78bfa">{techs}</span>
          </div>
        </div>'''

    total_fail       = sum(v["fail"]       for v in fw_summary.values())
    total_pass       = sum(v["pass"]       for v in fw_summary.values())
    total_not_tested = sum(v["not_tested"] for v in fw_summary.values())

    # Severity stat boxes — only show severities with at least one finding
    sev_stats_html = "".join(
        f'<div class="stat-box"><div class="stat-num" style="color:{SEV_COLOR.get(s,"#64748b")}">{sev_counts[s]}</div><div class="stat-label">{s} Findings</div></div>'
        for s in sev_order if sev_counts.get(s, 0) > 0
    )

    # ATT&CK techniques chips
    att_html = ""
    if all_techniques:
        chips = " ".join(f'<span class="tech-chip">{t}</span>' for t in all_techniques)
        att_html = f'<p class="section-title">ATT&amp;CK Techniques Exposed</p><div class="tech-row">{chips}</div>'

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{artifact_name} — Compliance Coverage Report</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{font-family:"JetBrains Mono",monospace;background:#020617;min-height:100vh;padding:2rem;color:white}}
  .container{{max-width:1200px;margin:0 auto}}
  .header{{margin-bottom:2rem}}
  .header-row{{display:flex;align-items:center;gap:1rem;margin-bottom:.5rem}}
  .pulse-dot{{width:12px;height:12px;background:#fb7185;border-radius:50%;animation:pulse 2s infinite;flex-shrink:0}}
  @keyframes pulse{{0%,100%{{opacity:1;box-shadow:0 0 0 0 rgba(251,113,133,.4)}}50%{{opacity:.7;box-shadow:0 0 0 6px rgba(251,113,133,0)}}}}
  h1{{font-size:1.4rem;font-weight:700}}
  .subtitle{{color:#94a3b8;font-size:.8rem;margin-left:1.75rem}}
  .summary-bar{{display:flex;gap:1.5rem;margin:1.5rem 0;flex-wrap:wrap;align-items:stretch}}
  .stat-box{{background:rgba(15,23,42,.6);border:1px solid #1e293b;border-radius:.75rem;padding:.75rem 1.25rem;text-align:center}}
  .stat-num{{font-size:1.8rem;font-weight:700}}
  .stat-label{{color:#64748b;font-size:.68rem;margin-top:.2rem}}
  .divider{{width:1px;background:#1e293b;margin:0 .25rem;align-self:stretch}}
  .section-title{{font-size:.68rem;font-weight:600;letter-spacing:.1em;color:#475569;text-transform:uppercase;margin:2rem 0 .75rem;padding-bottom:.4rem;border-bottom:1px solid #1e293b}}
  .finding-row{{background:rgba(15,23,42,.5);border:1px solid #1e293b;border-radius:.5rem;padding:.875rem 1rem;margin-bottom:.5rem}}
  .finding-meta{{display:flex;gap:.75rem;align-items:center;margin-bottom:.35rem}}
  .finding-id{{color:#475569;font-size:.7rem;font-weight:700}}
  .finding-sev{{font-size:.72rem;font-weight:700}}
  .finding-type{{font-size:.68rem;color:#64748b;background:#0f172a;padding:1px 6px;border-radius:3px;border:1px solid #1e293b}}
  .finding-desc{{color:#94a3b8;font-size:.78rem;margin-bottom:.4rem}}
  .finding-links{{font-size:.7rem;color:#475569}}
  .link-label{{color:#334155}}
  .fw-section{{margin-bottom:2rem}}
  .fw-header{{display:flex;justify-content:space-between;align-items:center;background:rgba(30,41,59,.5);border:1px solid #1e293b;border-radius:.5rem .5rem 0 0;padding:.6rem 1rem;font-size:.75rem;font-weight:700;color:#e2e8f0}}
  .fw-name{{color:#9cdcfe}}
  .fw-stats{{font-size:.7rem;font-weight:400}}
  .ctrl-table{{width:100%;border-collapse:collapse}}
  .ctrl-table th{{text-align:left;color:#475569;font-size:.65rem;font-weight:600;padding:.4rem .75rem;background:rgba(15,23,42,.6);border-bottom:1px solid #1e293b}}
  .ctrl-table td{{padding:.4rem .75rem;border-bottom:1px solid #0f172a;font-size:.75rem;vertical-align:top}}
  .tech-row{{display:flex;flex-wrap:wrap;gap:.5rem;margin-bottom:1.5rem}}
  .tech-chip{{background:rgba(167,139,250,.15);border:1px solid rgba(167,139,250,.3);border-radius:999px;padding:.25rem .75rem;font-size:.68rem;color:#a78bfa}}
  .next-step{{margin-top:1.5rem;background:rgba(76,29,149,.15);border:1px solid rgba(167,139,250,.3);border-radius:.75rem;padding:1rem 1.25rem;font-size:.8rem;color:#94a3b8}}
  .next-step strong{{color:#a78bfa}}
  code{{background:#0f172a;padding:2px 6px;border-radius:3px;font-size:.75rem;color:#e2e8f0}}
  .footer{{text-align:center;margin-top:1.5rem;color:#475569;font-size:.72rem}}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="header-row">
      <div class="pulse-dot"></div>
      <h1>{artifact_name} — Compliance Coverage Report</h1>
    </div>
    <p class="subtitle">Frameworks: CIS Controls v8 · OWASP Top 10 2021 · NIST CSF &nbsp;·&nbsp; {scan_date} &nbsp;·&nbsp; Generated by Compliance Mapper</p>
  </div>

  <div class="summary-bar">
    <div class="stat-box"><div class="stat-num" style="color:#fb7185">{total_fail}</div><div class="stat-label">Controls Failing</div></div>
    <div class="stat-box"><div class="stat-num" style="color:#34d399">{total_pass}</div><div class="stat-label">Controls Passing</div></div>
    <div class="stat-box"><div class="stat-num" style="color:#475569">{total_not_tested}</div><div class="stat-label">Not Tested</div></div>
    <div class="divider"></div>
    {sev_stats_html}
  </div>

  {att_html}

  <p class="section-title">Findings → Framework Mapping</p>
  {findings_html}

  <p class="section-title">Framework Coverage</p>
  {framework_tables}

  <div class="next-step">
    <strong>Next step:</strong> Run the tabletop exercise generator to build a realistic attack scenario from these gaps.<br>
    Start a new chat and type: <code>Use the tabletop-generator skill. Here are my compliance gaps: [paste this report]</code>
  </div>

  <p class="footer">OFFICIAL (OPEN) &nbsp;·&nbsp; {scan_date}</p>
</div>
</body>
</html>'''
    return html


# ══════════════════════════════════════════════════════════════════════
# FILL IN FROM THE ACTUAL GUARDIAN REPORT. Replace all placeholders.
# ══════════════════════════════════════════════════════════════════════

artifact_name = "ARTIFACT_NAME"   # e.g. "auth-service.py"
scan_date     = "YYYY-MM-DD"

# Extract these from the Guardian report — one entry per finding
raw_findings = [
    {"id": "F1", "severity": "Critical", "description": "Raw description from Guardian report", "vuln_type": "sql injection"},
    {"id": "F2", "severity": "High",     "description": "Raw description from Guardian report", "vuln_type": "hardcoded credential"},
    # Add all findings from the Guardian report
]

# Query the framework MCP for each unique vuln type
import urllib.request, urllib.parse, json

def map_finding(vuln_type):
    url = "http://hermes-framework-mcp:8082/api/map_finding?" + urllib.parse.urlencode({"vuln_type": vuln_type})
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"vuln_type": vuln_type, "controls": [], "techniques": [], "error": str(e)}

# Build enriched findings and control_results
enriched = []
control_results = {}

for f in raw_findings:
    mapped    = map_finding(f["vuln_type"])
    ctrl_ids  = [c["control_id"] for c in mapped.get("controls", [])]
    tech_ids  = [t["technique_id"] for t in mapped.get("techniques", [])]
    enriched.append({**f, "controls_failed": ctrl_ids, "techniques": tech_ids})
    for ctrl in mapped.get("controls", []):
        cid = ctrl["control_id"]
        if cid not in control_results:
            control_results[cid] = {
                "title":            ctrl["title"],
                "framework":        ctrl["framework"],
                "status":           "FAIL",
                "failing_findings": [],
            }
        control_results[cid]["failing_findings"].append(f["id"])

html = generate_page(artifact_name, scan_date, enriched, control_results)
slug = artifact_name.lower().replace(" ", "-").replace("/", "-")
out  = f"/opt/outputs/compliance-{slug}-{scan_date}.html"
os.makedirs("/opt/outputs", exist_ok=True)
with open(out, "w") as fh:
    fh.write(html)
print(f"Saved: {out} ({len(html):,} bytes)")

# ── Markdown summary ───────────────────────────────────────────────────────
sev_order  = ["Critical", "High", "Medium", "Low"]
sev_counts = {s: sum(1 for f in enriched if f.get("severity") == s) for s in sev_order}
sev_line   = "  ·  ".join(f"{sev_counts[s]} {s}" for s in sev_order if sev_counts.get(s, 0) > 0)

by_fw      = {}
for cid, ctrl in control_results.items():
    by_fw.setdefault(ctrl["framework"], []).append((cid, ctrl))

fail_count = sum(1 for c in control_results.values() if c["status"] == "FAIL")
pass_count = sum(1 for c in control_results.values() if c["status"] == "PASS")

all_techniques = sorted({t for f in enriched for t in f.get("techniques", [])})

md_lines = [
    f"# Compliance Coverage Report — {artifact_name}",
    f"",
    f"**Date:** {scan_date}  ",
    f"**Frameworks:** CIS Controls v8 · OWASP Top 10 2021 · NIST CSF  ",
    f"**Classification:** OFFICIAL (OPEN)",
    f"",
    f"---",
    f"",
    f"## Executive Summary",
    f"",
    f"{len(enriched)} findings mapped across {len(by_fw)} framework(s). "
    f"**{fail_count} controls FAILING**, {pass_count} PASSING. "
    f"Severity breakdown: {sev_line}.",
    f"",
    f"---",
    f"",
]

# Per-framework sections
for fw, ctrls in sorted(by_fw.items()):
    fail_ctrls = [(cid, c) for cid, c in ctrls if c["status"] == "FAIL"]
    pass_ctrls = [(cid, c) for cid, c in ctrls if c["status"] == "PASS"]
    md_lines += [f"## {fw}", f""]
    if fail_ctrls or pass_ctrls:
        md_lines += [
            "| Control | Title | Status | Failing Findings |",
            "|---------|-------|--------|-----------------|",
        ]
        for cid, ctrl in sorted(fail_ctrls):
            ff = ", ".join(ctrl.get("failing_findings", [])) or "—"
            md_lines.append(f"| {cid} | {ctrl['title']} | **FAIL** | {ff} |")
        for cid, ctrl in sorted(pass_ctrls):
            md_lines.append(f"| {cid} | {ctrl['title']} | PASS | — |")
    md_lines.append("")

# Findings detail table
md_lines += [
    "## Findings Detail",
    "",
    "| ID | Severity | Vulnerability Type | Controls Failed | ATT&CK Techniques |",
    "|----|----------|--------------------|-----------------|-------------------|",
]
for f in enriched:
    ctrls = ", ".join(f.get("controls_failed", [])) or "—"
    techs = ", ".join(f.get("techniques", [])) or "—"
    md_lines.append(f"| {f['id']} | {f['severity']} | {f.get('vuln_type','')} | {ctrls} | {techs} |")

# ATT&CK summary
if all_techniques:
    md_lines += ["", "## ATT&CK Techniques Exposed", ""]
    for t in all_techniques:
        md_lines.append(f"- {t}")

# Next step and reviewer notes
md_lines += [
    "",
    "---",
    "",
    "## Next Step",
    "",
    "Use the **tabletop-generator** skill with this report to build a realistic attack scenario from these compliance gaps.",
    "",
    "---",
    "",
    "## Reviewer Notes",
    "",
    "_Leave blank — human reviewer fills in to flag false positives or missed findings._  ",
    "_Read by guardian-feedback-digest._",
    "",
    f"OFFICIAL (OPEN) · {scan_date}",
]

md_out = f"/opt/outputs/compliance-{slug}-{scan_date}.md"
with open(md_out, "w") as fh:
    fh.write("\n".join(md_lines))
print(f"Saved: {md_out}")
```

---

## Important Rules

- Always query the framework MCP server — do not guess control mappings from memory
- If the MCP server is unreachable, state so explicitly and do not fabricate results
- Every failing control must reference the finding ID that caused it to fail
- Save both `.html` and `.md` outputs
- The HTML must open standalone in a browser (no external dependencies except Google Fonts)
- Recommend tabletop-generator as the next step at the end of every report
