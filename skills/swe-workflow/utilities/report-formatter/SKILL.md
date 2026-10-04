---
name: report-formatter
version: 2.0.0
description: Formats raw security findings into a structured security report. Shared output template used by code-and-api-guardian, code-reviewer, and any other security skills. v2 adds the Reviewer Notes field required for the self-improvement feedback loop.
tools:
  - read_file
  - execute_code
---

## Overview

Takes raw findings as input and produces a consistently structured security report. All security skills should route their final output through this formatter rather than inventing their own report shape.

---

## Input

Accept findings in any format — plain text, bullet points, JSON, or a mix. The skill extracts and structures the content; the caller does not need to pre-format.

Required inputs (ask if missing):
- What was reviewed (filename, endpoint, artifact description)
- List of findings (each with: what was found, where, why it matters)
- Artifact type if known

---

## Output Format

Produce the following structure exactly. Do not add extra sections or rearrange the order.

```
OFFICIAL (OPEN) \ SENSITIVE NORMAL
=======================================
SECURITY REPORT
Reviewed: [filename, endpoint, or artifact description]
Date: [YYYY-MM-DD]
=======================================

EXECUTIVE SUMMARY
[2-3 sentences covering: what was reviewed, the highest-severity finding,
and the single most important recommended action]

FINDINGS
| ID | Description | Severity | Affected Component | Status |
|----|-------------|----------|--------------------|--------|
| F1 | [finding]   | Critical | [component/line]   | Open   |
| F2 | ...         | High     | ...                | Open   |

Severity scale:
  Critical — exploitable right now with direct impact
  High     — likely exploitable under realistic conditions
  Medium   — bad practice with low immediate risk
  Low      — minor issue, informational
  Pass     — no issue found

Each Description must state a concrete exploitability reason:
  GOOD: "Allows any host on the internet to reach port 22 directly via 0.0.0.0/0 inbound rule"
  BAD:  "This looks risky"

RECOMMENDED ACTIONS (severity order — Critical first)
1. [Specific change, exact file/line/resource, not generic advice]
2. ...

NEXT REVIEW DATE: [today + 30 days]

REVIEWER NOTES
[Leave blank — human reviewer fills in after reading the report.
Use this field to flag false positives, missed findings, or noisy rules.
This field is read automatically by guardian-feedback-digest
to generate continuous improvement proposals.]
```

---

## Saving the Report

Save to the path specified by the calling skill. If no path was given, default to:
```
/opt/outputs/security-report-[artifact-name]-[YYYY-MM-DD].md
```

Confirm the file path after saving.

---

## Important Rules

- The Reviewer Notes field is mandatory — include it even if blank, and never pre-fill it
- Severity must always include a concrete exploitability reason in the Description
- Do not add a "Methodology" or "Tools Used" section — keep the report focused on findings and actions
- The classification header (`OFFICIAL (OPEN) \ SENSITIVE NORMAL`) must always be the first line
