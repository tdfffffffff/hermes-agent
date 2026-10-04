---
name: tabletop-generator
version: 1.0.0
description: Generates realistic end-to-end tabletop exercise scenarios from Guardian scan findings or compliance gaps. Queries the hermes-framework-mcp server for relevant MITRE ATT&CK techniques, then builds a facilitator-ready exercise with threat actor profile, phased attack narrative, inject questions, and expected controls.
tools:
  - execute_code
  - write_file
  - memory
---

## Overview

You receive security findings (from a Guardian scan or Compliance Mapper report) and a brief system description. You build a realistic tabletop exercise: a threat scenario grounded in the actual identified gaps, structured for a facilitated team session.

This is NOT a theoretical exercise — every attack step should exploit a real finding from the scan/compliance report. The goal is to help the team think through what an actual attacker would do given what you already know about the system's weaknesses.

---

## Step 1 — Receive Input

Accept input in any of these forms:
- Pasted Guardian scan report or compliance mapper output
- File path to a report in `/opt/outputs/`
- Brief description: "Our API has SQL injection in the search endpoint and hardcoded DB credentials"

Ask one question if needed: "What type of system is this? (web app, API, data pipeline, internal tool)"

---

## Step 2 — Extract Gaps and Context

From the input, identify:
1. **System type** — web app, API, data pipeline, container-based service, etc.
2. **Key vulnerabilities** — list the exploitable findings (focus on Critical/High)
3. **Entry points** — what does the attacker face first? (public API, web UI, internal tool?)
4. **Crown jewels** — what data or capability would an attacker want? (PII, credentials, code, internal systems)

---

## Step 3 — Query Framework MCP for ATT&CK Techniques

For each key vulnerability type, query the framework MCP to get relevant ATT&CK techniques:

```python
import urllib.request, urllib.parse, json

def get_techniques_for_vuln(vuln_type):
    url = "http://hermes-framework-mcp:8082/api/map_finding?" + urllib.parse.urlencode({"vuln_type": vuln_type})
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read().decode()).get("techniques", [])
    except Exception as e:
        return []

# Also get techniques by tactic for building the narrative arc
def get_techniques_by_tactic(tactic):
    url = "http://hermes-framework-mcp:8082/api/get_techniques?" + urllib.parse.urlencode({"tactic": tactic})
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return []

vuln_types = ["sql injection", "hardcoded credential"]   # replace with actual
all_techniques = {}
for vt in vuln_types:
    for tech in get_techniques_for_vuln(vt):
        all_techniques[tech["technique_id"]] = tech

print(json.dumps(all_techniques, indent=2))
```

---

## Step 4 — Build the Tabletop Scenario

Structure the exercise in FIVE phases following the ATT&CK lifecycle. Each phase must:
- Reference a real finding or gap from the scan
- Include the ATT&CK technique ID and name
- Have 2–3 inject questions for the facilitator

**Phases:**
1. **Initial Access** — how does the attacker get in? (exploit the entry point)
2. **Execution & Discovery** — what do they run and discover after getting in?
3. **Credential Access / Lateral Movement** — how do they escalate or move?
4. **Collection & Exfiltration** — what do they take and how?
5. **Impact** — what is the worst-case outcome if undetected?

Format each phase as:

```
PHASE N — [PHASE NAME]
ATT&CK: [T-ID] [Technique Name]
Gap exploited: [Finding ID + description]

Narrative:
[2–3 sentences describing what the attacker does, how they exploit the gap, what they gain]

Inject questions:
1. [Question for the team — focus on detection: "Would your monitoring catch this?"]
2. [Question on response: "Who gets paged? What's the runbook?"]
3. [Question on prevention: "What control should have stopped this?"]

Expected controls that should have triggered:
- [Control ID: what it would have done]
```

---

## Step 5 — Generate HTML Output

Use `execute_code` to save the tabletop exercise as a self-contained HTML file.

```python
import os, json

def generate_tabletop_page(system_name, scan_date, threat_actor, phases, debrief_questions):
    """
    threat_actor: {name, motivation, skill_level, target}
    phases: list of {phase_num, phase_name, technique_id, technique_name, tactic,
                     gap_ref, narrative, injects, expected_controls}
    debrief_questions: list of strings
    """

    TACTIC_COLOR = {
        "Initial Access":       "#fb7185",
        "Execution":            "#fbbf24",
        "Credential Access":    "#f97316",
        "Privilege Escalation": "#f97316",
        "Lateral Movement":     "#a78bfa",
        "Collection":           "#22d3ee",
        "Exfiltration":         "#22d3ee",
        "Impact":               "#ef4444",
        "Defense Evasion":      "#94a3b8",
        "Discovery":            "#fbbf24",
    }

    phases_html = ""
    for p in phases:
        col = TACTIC_COLOR.get(p.get("tactic", ""), "#94a3b8")
        injects_html = "".join(f'<li class="inject-item"><span class="inject-num">{i+1}</span><span>{q}</span></li>'
                               for i, q in enumerate(p.get("injects", [])))
        controls_html = "".join(f'<li class="ctrl-item">· {c}</li>'
                                for c in p.get("expected_controls", []))
        phases_html += f'''
        <div class="phase-card" style="border-left-color:{col}">
          <div class="phase-header">
            <div>
              <span class="phase-label">PHASE {p["phase_num"]}</span>
              <span class="phase-name">{p["phase_name"]}</span>
            </div>
            <div class="phase-meta">
              <span class="attack-badge" style="background:rgba(255,255,255,0.05);color:{col}">
                {p.get("technique_id","")} · {p.get("technique_name","")}
              </span>
              <span class="tactic-badge" style="color:{col}">{p.get("tactic","")}</span>
            </div>
          </div>
          <div class="gap-ref">Gap exploited: <strong>{p.get("gap_ref","")}</strong></div>
          <div class="narrative">{p.get("narrative","")}</div>
          <div class="subsection-title">Inject questions</div>
          <ul class="inject-list">{injects_html}</ul>
          <div class="subsection-title">Expected controls</div>
          <ul class="ctrl-list">{controls_html}</ul>
        </div>'''

    debrief_html = "".join(f'<li class="debrief-item"><span class="debrief-num">{i+1}</span><span>{q}</span></li>'
                           for i, q in enumerate(debrief_questions))

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{system_name} — Tabletop Exercise</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{font-family:"JetBrains Mono",monospace;background:#020617;min-height:100vh;padding:2rem;color:white}}
  .container{{max-width:1100px;margin:0 auto}}
  .header{{margin-bottom:2rem}}
  .header-row{{display:flex;align-items:center;gap:1rem;margin-bottom:.5rem}}
  .pulse-dot{{width:12px;height:12px;background:#ef4444;border-radius:50%;animation:pulse 1.5s infinite;flex-shrink:0}}
  @keyframes pulse{{0%,100%{{opacity:1;box-shadow:0 0 0 0 rgba(239,68,68,.4)}}50%{{opacity:.7;box-shadow:0 0 0 6px rgba(239,68,68,0)}}}}
  h1{{font-size:1.4rem;font-weight:700}}
  .subtitle{{color:#94a3b8;font-size:.8rem;margin-left:1.75rem}}
  .section-title{{font-size:.68rem;font-weight:600;letter-spacing:.1em;color:#475569;text-transform:uppercase;margin:2rem 0 .75rem;padding-bottom:.4rem;border-bottom:1px solid #1e293b}}
  .threat-card{{background:rgba(136,19,55,0.12);border:1px solid rgba(251,113,133,.25);border-radius:.75rem;padding:1.25rem;margin-bottom:2rem}}
  .threat-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;margin-top:.75rem}}
  .threat-field label{{display:block;color:#64748b;font-size:.65rem;font-weight:600;letter-spacing:.06em;margin-bottom:.2rem}}
  .threat-field span{{color:#e2e8f0;font-size:.8rem}}
  .phase-card{{background:rgba(15,23,42,.5);border:1px solid #1e293b;border-left:3px solid #334155;border-radius:.5rem;padding:1.25rem;margin-bottom:1rem}}
  .phase-header{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:.75rem;flex-wrap:wrap;gap:.5rem}}
  .phase-label{{color:#475569;font-size:.65rem;font-weight:600;display:block;margin-bottom:.2rem}}
  .phase-name{{color:#e2e8f0;font-size:.95rem;font-weight:700;display:block}}
  .phase-meta{{display:flex;flex-direction:column;align-items:flex-end;gap:.3rem}}
  .attack-badge{{font-size:.68rem;padding:.2rem .5rem;border-radius:.25rem;font-weight:600}}
  .tactic-badge{{font-size:.65rem;font-weight:600}}
  .gap-ref{{color:#64748b;font-size:.72rem;margin-bottom:.75rem;padding:.4rem .6rem;background:rgba(30,41,59,.4);border-radius:.25rem}}
  .gap-ref strong{{color:#fbbf24}}
  .narrative{{color:#94a3b8;font-size:.8rem;line-height:1.6;margin-bottom:1rem}}
  .subsection-title{{color:#475569;font-size:.65rem;font-weight:600;letter-spacing:.07em;text-transform:uppercase;margin-bottom:.4rem}}
  .inject-list,.ctrl-list{{list-style:none;margin-bottom:.875rem}}
  .inject-item,.debrief-item{{display:flex;gap:.6rem;padding:.4rem 0;font-size:.78rem;color:#94a3b8;border-bottom:1px solid #0f172a;align-items:flex-start}}
  .inject-num,.debrief-num{{min-width:1.4rem;color:#334155;font-size:.68rem;font-weight:700;flex-shrink:0;padding-top:.1rem}}
  .ctrl-item{{color:#64748b;font-size:.75rem;padding:.25rem 0}}
  .debrief-card{{background:rgba(76,29,149,.12);border:1px solid rgba(167,139,250,.25);border-radius:.75rem;padding:1.25rem}}
  .footer{{text-align:center;margin-top:1.5rem;color:#475569;font-size:.72rem}}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="header-row">
      <div class="pulse-dot"></div>
      <h1>{system_name} — Tabletop Exercise</h1>
    </div>
    <p class="subtitle">Security Tabletop Exercise &nbsp;·&nbsp; {scan_date} &nbsp;·&nbsp; Generated by Tabletop Generator</p>
  </div>

  <p class="section-title">Threat Actor Profile</p>
  <div class="threat-card">
    <div class="threat-grid">
      <div class="threat-field"><label>Actor Name</label><span>{threat_actor.get("name","")}</span></div>
      <div class="threat-field"><label>Motivation</label><span>{threat_actor.get("motivation","")}</span></div>
      <div class="threat-field"><label>Skill Level</label><span>{threat_actor.get("skill_level","")}</span></div>
      <div class="threat-field"><label>Target</label><span>{threat_actor.get("target","")}</span></div>
    </div>
  </div>

  <p class="section-title">Attack Phases</p>
  {phases_html}

  <p class="section-title">Debrief Questions</p>
  <div class="debrief-card">
    <ul class="inject-list">{debrief_html}</ul>
  </div>

  <p class="footer">OFFICIAL (OPEN) &nbsp;·&nbsp; {scan_date} &nbsp;·&nbsp; NOT FOR DISTRIBUTION OUTSIDE EXERCISE</p>
</div>
</body>
</html>'''
    return html

# ══════════════════════════════════════════════════════════════════════
# FILL IN FROM THE ACTUAL SCAN / COMPLIANCE REPORT.
# ══════════════════════════════════════════════════════════════════════

system_name = "SYSTEM_NAME"
scan_date   = "YYYY-MM-DD"

threat_actor = {
    "name":        "External opportunistic attacker",
    "motivation":  "Data exfiltration / credential harvesting",
    "skill_level": "Intermediate — uses known exploit tooling",
    "target":      "Exposed API endpoints and database credentials",
}

phases = [
    {
        "phase_num":          1,
        "phase_name":         "Initial Access",
        "technique_id":       "T1190",
        "technique_name":     "Exploit Public-Facing Application",
        "tactic":             "Initial Access",
        "gap_ref":            "F1 (Critical) — SQL injection in /api/search",
        "narrative":          (
            "The attacker discovers the public API via passive reconnaissance. "
            "Using a basic payload in the search parameter, they confirm SQL injection "
            "and extract database table names. No WAF or input validation stops them."
        ),
        "injects": [
            "Does your API gateway or WAF log and block SQL metacharacters in query params? Who reviews those alerts?",
            "How quickly would the on-call team detect a spike in malformed API requests at 3 AM?",
            "What data is accessible via the vulnerable endpoint? Is it subject to data classification controls?",
        ],
        "expected_controls": [
            "CIS-16.12: Code-level input validation / parameterised queries should have prevented this",
            "OWASP-A03: Injection prevention — not met per Guardian scan",
            "NIST-PR.DS-5: Input validation as a data leak control — not met",
        ],
    },
    # Add more phases based on the actual findings
]

debrief_questions = [
    "Which phase would your current monitoring have detected first — and how long would detection take?",
    "If you discovered exfiltration 48 hours after it started, what data would already be gone?",
    "Which of the failing controls, if remediated first, would have had the biggest impact on stopping this attack?",
    "Who owns the incident response runbook for an API compromise? Is it up to date?",
    "What would you change about your logging or alerting based on this exercise?",
]

html = generate_tabletop_page(system_name, scan_date, threat_actor, phases, debrief_questions)
slug = system_name.lower().replace(" ", "-")
out  = f"/opt/outputs/tabletop-{slug}-{scan_date}.html"
os.makedirs("/opt/outputs", exist_ok=True)
with open(out, "w") as fh:
    fh.write(html)
print(f"Saved: {out} ({len(html):,} bytes)")
```

---

## Important Rules

- Every attack phase must reference a real finding from the scan — no hypothetical gaps
- Always query the framework MCP for ATT&CK techniques — do not invent technique IDs
- The scenario must be realistic and usable by a real facilitator — avoid vague inject questions
- Include exactly 5 phases following the ATT&CK lifecycle progression
- Inject questions should test detection, response, AND prevention — at least one each per phase
- The report is marked "NOT FOR DISTRIBUTION OUTSIDE EXERCISE" — remind the user of this
