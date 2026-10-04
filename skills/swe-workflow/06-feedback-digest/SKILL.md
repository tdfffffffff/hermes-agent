---
name: guardian-feedback-digest
version: 3.0.0
description: Reads all guardian reports and prior proposals in /opt/outputs/, synthesises cross-cycle learning (pattern confidence, regression detection, knowledge-base growth), and generates a self-contained HTML dashboard. Does NOT modify any skill — all edits require explicit human approval (Tier 3).
tools:
  - terminal
  - read_file
  - execute_code
---

## Overview

This skill is Tier 2 of the guardian self-improvement loop. It operates across **multiple learning cycles** — reading both guardian reports and prior proposals to build a longitudinal picture of what the system has learned, what keeps recurring, what has been resolved, and where the checklist still has blind spots.

**This skill MUST NOT call hermes-agent-skill-authoring.**
**This skill MUST NOT modify code-and-api-guardian or any other skill.**

---

## Step 1 — Collect Reports

```bash
ls /opt/outputs/guardian-report-*.md 2>/dev/null | sort
ls /opt/outputs/guardian-improvement-proposal-*.md 2>/dev/null | sort
```

If no guardian reports found: output "No guardian reports found — run code-and-api-guardian first." Stop.

---

## Step 2 — Load Learning History

Use `execute_code` to parse prior proposals and build the memory baseline.

```python
import os, re, glob

def load_prior_proposals():
    results = []
    for path in sorted(glob.glob('/opt/outputs/guardian-improvement-proposal-*.md')):
        date_m = re.search(r'(\d{4}-\d{2}-\d{2})', os.path.basename(path))
        if not date_m:
            continue
        with open(path) as f:
            content = f.read()
        reports_m = re.search(r'Reports read:\s*(\d+)', content)
        patterns_m = re.findall(r'\[P\d+\]\s+(\w+)', content)
        proposed_m = re.findall(r'Checklist:\s*(\S+)', content)
        results.append({
            'date':            date_m.group(1),
            'reports_read':    int(reports_m.group(1)) if reports_m else 0,
            'pattern_types':   patterns_m,
            'pattern_count':   len(patterns_m),
            'change_count':    len(proposed_m),
            'path':            path,
            'snippet':         content[:400],
        })
    return results

def load_report_metadata():
    results = []
    for path in sorted(glob.glob('/opt/outputs/guardian-report-*.md')):
        name = os.path.basename(path)
        date_m = re.search(r'(\d{4}-\d{2}-\d{2})', name)
        date = date_m.group(1) if date_m else 'unknown'
        with open(path) as f:
            content = f.read()
        findings = re.findall(r'\b(F\d+)\b', content)
        sev_c = len(re.findall(r'Critical', content))
        sev_h = len(re.findall(r'\bHigh\b', content))
        sev_m = len(re.findall(r'\bMedium\b', content))
        sev_l = len(re.findall(r'\bLow\b', content))
        notes_m = re.search(r'REVIEWER NOTES([\s\S]{0,500}?)(?:\n---|\Z)', content)
        notes_text = notes_m.group(1).strip() if notes_m else ''
        has_notes = bool(notes_text) and '[' not in notes_text[:30]
        results.append({
            'path': path, 'name': name, 'date': date,
            'finding_count': len(set(findings)),
            'critical': sev_c, 'high': sev_h, 'medium': sev_m, 'low': sev_l,
            'has_notes': has_notes, 'notes_text': notes_text if has_notes else '',
        })
    return results

def detect_version_series(reports):
    """Group reports by artifact name to find multi-version scans."""
    groups = {}
    for r in reports:
        # Strip date and extension to get artifact key
        key = re.sub(r'-?\d{4}-\d{2}-\d{2}', '', r['name'])
        key = re.sub(r'guardian-report-', '', key)
        key = re.sub(r'\.md$', '', key)
        key = re.sub(r'-v\d+', '', key)
        groups.setdefault(key, []).append(r)
    series = {k: sorted(v, key=lambda x: x['date']) for k, v in groups.items() if len(v) > 1}
    regressions = []
    for artifact, versions in series.items():
        for i in range(1, len(versions)):
            prev, curr = versions[i-1], versions[i]
            if curr['critical'] > prev['critical'] or curr['high'] > prev['high']:
                regressions.append({
                    'artifact': artifact,
                    'prev': prev, 'curr': curr,
                    'delta_critical': curr['critical'] - prev['critical'],
                    'delta_high': curr['high'] - prev['high'],
                })
    return series, regressions

prior_proposals = load_prior_proposals()
all_reports     = load_report_metadata()
version_series, regressions = detect_version_series(all_reports)

reports_with_notes = sum(1 for r in all_reports if r['has_notes'])
learning_cycle     = len(prior_proposals) + 1
corpus_growth      = len(all_reports) - (prior_proposals[-1]['reports_read'] if prior_proposals else 0)

print(f"Learning cycle: {learning_cycle}")
print(f"Total reports: {len(all_reports)}")
print(f"Reports with reviewer notes: {reports_with_notes}")
print(f"New reports since last cycle: {corpus_growth}")
print(f"Version series detected: {list(version_series.keys())}")
print(f"Regressions: {len(regressions)}")
for p in prior_proposals:
    print(f"  Prior proposal {p['date']}: {p['reports_read']} reports, {p['pattern_count']} patterns")
```

---

## Step 3 — Extract Reviewer Notes and Analyse Patterns

For each report, extract the REVIEWER NOTES section. Then across all notes identify:

1. **False positive patterns** — checks that fired but were not real issues
2. **Missed finding patterns** — things the skill should have caught but did not (highest priority)
3. **Noisy rules** — checks that fire consistently at low signal
4. **Cross-report structural patterns** — findings that appear in >50% of reports (even without reviewer notes)

For each pattern, determine:
- `first_detected`: earliest report date it appeared, OR date from a prior proposal if it was flagged before
- `status`: `NEWLY_DETECTED` if not in any prior proposal, `RECURRING` if it appeared in a prior proposal
- `confidence`: occurrences / total relevant reports (0.0–1.0)
- `trend`: `growing` if confidence increased since last cycle, `stable`, or `declining`
- `report_sources`: list of report filenames that triggered this pattern
- Which pattern IDs (`P1`, `P2`, …) appeared in each report (for the heatmap)

For each pattern, also define a `keywords` list — short strings (case-insensitive) that reliably identify it in a report body (e.g. `['SLACK_RETYRY_CONFIG', 'RETYRY_CONFIG']`). These are used in Step 3a to auto-populate the heatmap without manual mapping.

---

## Step 3a — Keyword Mapping (no code to run)

After deciding on patterns in Step 3, add a `keywords` list to each one — short strings (case-insensitive) that reliably identify it in a report body (e.g. `['SLACK_RETYRY_CONFIG', 'RETYRY_CONFIG']`). Step 4 uses these to auto-populate the heatmap and back-fill `count`, `confidence`, and `report_sources` — do not set those fields manually.

---

## Step 4 — Generate HTML Output

Run this entire block as a single `execute_code` call. It re-loads all corpus data itself so it is fully self-contained.

```python
import os, re, glob
from datetime import date as _date

# ── Corpus helpers (self-contained — re-run here so no state dependency on Step 2) ──

def load_prior_proposals():
    results = []
    for path in sorted(glob.glob('/opt/outputs/guardian-improvement-proposal-*.md')):
        date_m = re.search(r'(\d{4}-\d{2}-\d{2})', os.path.basename(path))
        if not date_m:
            continue
        with open(path) as f:
            content = f.read()
        reports_m  = re.search(r'Reports read:\s*(\d+)', content)
        pattern_ts = re.findall(r'\[P\d+\]\s+(\w+)', content)
        proposed_m = re.findall(r'Checklist:\s*(\S+)', content)
        results.append({
            'date':          date_m.group(1),
            'reports_read':  int(reports_m.group(1)) if reports_m else 0,
            'pattern_types': pattern_ts,
            'pattern_count': len(pattern_ts),
            'change_count':  len(proposed_m),
        })
    return results

def load_report_metadata():
    results = []
    for path in sorted(glob.glob('/opt/outputs/guardian-report-*.md')):
        name   = os.path.basename(path)
        date_m = re.search(r'(\d{4}-\d{2}-\d{2})', name)
        date   = date_m.group(1) if date_m else 'unknown'
        with open(path) as f:
            content = f.read()
        findings  = re.findall(r'\b(F\d+)\b', content)
        notes_m   = re.search(r'REVIEWER NOTES([\s\S]{0,500}?)(?:\n---|\Z)', content)
        notes_txt = notes_m.group(1).strip() if notes_m else ''
        has_notes = bool(notes_txt) and '[' not in notes_txt[:30]
        results.append({
            'path': path, 'name': name, 'date': date,
            'finding_count': len(set(findings)),
            'critical': len(re.findall(r'Critical', content)),
            'high':     len(re.findall(r'\bHigh\b',     content)),
            'medium':   len(re.findall(r'\bMedium\b',   content)),
            'low':      len(re.findall(r'\bLow\b',      content)),
            'has_notes': has_notes,
        })
    return results

def detect_version_series(reports):
    groups = {}
    for r in reports:
        key = re.sub(r'-?\d{4}-\d{2}-\d{2}', '', r['name'])
        key = re.sub(r'guardian-report-', '', key)
        key = re.sub(r'\.md$', '', key)
        key = re.sub(r'-v\d+', '', key)
        groups.setdefault(key, []).append(r)
    regressions = []
    for artifact, versions in groups.items():
        versions = sorted(versions, key=lambda x: x['date'])
        if len(versions) < 2:
            continue
        for i in range(1, len(versions)):
            prev, curr = versions[i-1], versions[i]
            if curr['critical'] > prev['critical'] or curr['high'] > prev['high']:
                regressions.append({
                    'artifact':       artifact,
                    'prev':           prev,
                    'curr':           curr,
                    'delta_critical': curr['critical'] - prev['critical'],
                    'delta_high':     curr['high']     - prev['high'],
                })
    return regressions

def build_report_timeline(patterns, all_reports):
    timeline = []
    for r in sorted(all_reports, key=lambda x: x['date']):
        with open(r['path']) as f:
            content = f.read()
        triggered = [
            p['id'] for p in patterns
            if any(kw.lower() in content.lower() for kw in p.get('keywords', []))
        ]
        timeline.append({
            'date': r['date'], 'label': r['date'][5:],
            'filename': r['name'], 'patterns': triggered,
        })
    for p in patterns:
        sources         = [e['filename'] for e in timeline if p['id'] in e['patterns']]
        p['count']          = len(sources)
        p['report_sources'] = sources
        p['confidence']     = round(len(sources) / len(all_reports), 2) if all_reports else 0.0
    return timeline

# ── Load corpus ──────────────────────────────────────────────────────
prior_proposals = load_prior_proposals()
all_reports     = load_report_metadata()
regressions     = detect_version_series(all_reports)

reports_with_notes = sum(1 for r in all_reports if r['has_notes'])
learning_cycle     = len(prior_proposals) + 1
new_since_last     = len(all_reports) - (prior_proposals[-1]['reports_read'] if prior_proposals else 0)

def generate_proposal_page(
    gen_date, learning_cycle, all_reports, prior_proposals,
    low_data_warning, patterns, proposed_changes, not_proposed,
    report_timeline, regressions
):
    """
    patterns: list of {
        id, type, description, example_note, count, confidence (0-1),
        status ('NEWLY_DETECTED'|'RECURRING'), first_detected, trend ('growing'|'stable'|'declining'),
        report_sources: [filenames]
    }
    proposed_changes: list of {
        checklist, change_type, proposed_text, current_text (optional),
        evidence, evidence_sources: [filenames], blind_spot_risk,
        reduces_noise (bool), improves_detection (bool)
    }
    not_proposed: list of {description, reason}
    report_timeline: list of {date, label, filename, patterns: [pattern_ids]}
    regressions: list of {artifact, prev, curr, delta_critical, delta_high}
    prior_proposals: list of {date, reports_read, pattern_count, change_count}
    """

    TYPE_COLOR = {
        'false_positive': '#fb7185',
        'missed_finding': '#fbbf24',
        'noisy_rule':     '#a78bfa',
        'other':          '#64748b',
    }
    TYPE_LABEL = {
        'false_positive': 'FALSE POSITIVE',
        'missed_finding': 'MISSED FINDING',
        'noisy_rule':     'NOISY RULE',
        'other':          'OTHER',
    }
    CHECKLIST_COLOR = {
        'A1': '#fb7185', 'A2': '#fbbf24', 'A3': '#a78bfa',
        'A4': '#22d3ee', 'Live': '#34d399',
    }
    TREND_ICON  = {'growing': '↑', 'stable': '→', 'declining': '↓'}
    TREND_COLOR = {'growing': '#fb7185', 'stable': '#64748b', 'declining': '#34d399'}

    total_reports       = len(all_reports)
    reports_with_notes  = sum(1 for r in all_reports if r['has_notes'])
    new_since_last      = total_reports - (prior_proposals[-1]['reports_read'] if prior_proposals else 0)
    recurring_count     = sum(1 for p in patterns if p.get('status') == 'RECURRING')
    new_pattern_count   = sum(1 for p in patterns if p.get('status') == 'NEWLY_DETECTED')

    # ── Warning banner ──────────────────────────────────────────────────
    warning_html = ''
    if low_data_warning:
        warning_html = '<div class="warning-banner">⚠ Fewer than 3 reports have reviewer notes — patterns derived from structural analysis only. Confidence scores may not reflect real reviewer signal.</div>'

    # ── Learning heatmap ────────────────────────────────────────────────
    pattern_ids = [p['id'] for p in patterns]
    # Limit timeline columns to 12 most recent to avoid overflow
    tl = report_timeline[-12:] if len(report_timeline) > 12 else report_timeline
    heatmap_heads = ''.join(
        f'<th class="hm-col" title="{e["filename"]}">{e["label"]}</th>' for e in tl
    )
    heatmap_rows = ''
    for p in patterns:
        col = TYPE_COLOR.get(p['type'], '#64748b')
        cells = ''
        for e in tl:
            hit = p['id'] in e.get('patterns', [])
            bg  = f'background:{col};opacity:0.55' if hit else 'background:rgba(30,41,59,0.4)'
            cells += f'<td class="hm-cell" style="{bg}"></td>'
        heatmap_rows += f'''
        <tr>
          <td class="hm-pid" style="color:{col}">{p["id"]}</td>
          <td class="hm-pdesc">{p["description"][:55]}{"…" if len(p["description"])>55 else ""}</td>
          {cells}
        </tr>'''

    heatmap_html = f'''
    <div class="heatmap-wrap">
      <table class="heatmap">
        <thead><tr>
          <th class="hm-pid-col"></th>
          <th class="hm-desc-col">Pattern</th>
          {heatmap_heads}
        </tr></thead>
        <tbody>{heatmap_rows}</tbody>
      </table>
      <div class="hm-legend">
        {"".join(f'<span class="hm-leg-item"><span class="hm-leg-dot" style="background:{TYPE_COLOR[t]}"></span>{TYPE_LABEL[t]}</span>' for t in TYPE_COLOR)}
      </div>
    </div>''' if tl and pattern_ids else ''

    # ── Regression alerts ───────────────────────────────────────────────
    regression_html = ''
    for reg in regressions:
        reg_lines = ''
        for label, delta, col in [
            ('Critical', reg['delta_critical'], '#fb7185'),
            ('High',     reg['delta_high'],     '#fbbf24'),
        ]:
            if delta > 0:
                reg_lines += f'<span class="reg-delta" style="color:{col}">+{delta} {label}</span>'
        prev_date = reg['prev']['date']
        curr_date = reg['curr']['date']
        regression_html += f'''
        <div class="reg-card">
          <div class="reg-header">
            <span class="reg-badge">REGRESSION DETECTED</span>
            <span class="reg-artifact">{reg["artifact"]}</span>
          </div>
          <div class="reg-body">
            <div class="reg-compare">
              <div class="reg-ver">
                <div class="reg-ver-label">{prev_date}</div>
                <div class="reg-counts">
                  <span style="color:#fb7185">{reg["prev"]["critical"]}C</span>
                  <span style="color:#fbbf24">{reg["prev"]["high"]}H</span>
                </div>
              </div>
              <div class="reg-arrow">→</div>
              <div class="reg-ver">
                <div class="reg-ver-label">{curr_date}</div>
                <div class="reg-counts">
                  <span style="color:#fb7185">{reg["curr"]["critical"]}C</span>
                  <span style="color:#fbbf24">{reg["curr"]["high"]}H</span>
                </div>
              </div>
              <div class="reg-deltas">{reg_lines}</div>
            </div>
            <div class="reg-note">New or worsened findings introduced between versions. Guardian detected this automatically by comparing scan history for the same artifact.</div>
          </div>
        </div>'''

    # ── Pattern cards ───────────────────────────────────────────────────
    patterns_html = ''
    for p in patterns:
        col          = TYPE_COLOR.get(p['type'], '#64748b')
        lbl          = TYPE_LABEL.get(p['type'], p['type'].upper())
        pct          = int(p['confidence'] * 100)
        trend_icon   = TREND_ICON.get(p['trend'], '→')
        trend_col    = TREND_COLOR.get(p['trend'], '#64748b')
        status_col   = '#fbbf24' if p['status'] == 'NEWLY_DETECTED' else '#a78bfa'
        status_label = 'NEWLY DETECTED' if p['status'] == 'NEWLY_DETECTED' else f'RECURRING · since {p.get("first_detected","?")}'
        sources_html = ''.join(
            f'<span class="source-pill">{os.path.basename(s)[:40]}</span>'
            for s in p.get('report_sources', [])[:5]
        )
        patterns_html += f'''
        <div class="pattern-card" style="border-left-color:{col}">
          <div class="pattern-header">
            <div class="pattern-badges">
              <span class="type-badge" style="color:{col};background:rgba(255,255,255,0.05)">{lbl}</span>
              <span class="status-badge" style="color:{status_col};border-color:{status_col}">{status_label}</span>
            </div>
            <span class="trend-badge" style="color:{trend_col}" title="Trend vs prior cycle">{trend_icon} {p["trend"]}</span>
          </div>
          <div class="pattern-desc">{p["description"]}</div>
          <div class="confidence-row">
            <span class="conf-label">Confidence</span>
            <div class="conf-bar-bg">
              <div class="conf-bar-fill" style="--pct:{pct}%;background:{col}"></div>
            </div>
            <span class="conf-pct" style="color:{col}">{pct}%</span>
            <span class="conf-sub">({p["count"]}/{total_reports} reports)</span>
          </div>
          {"<div class='example-note'><span class='note-label'>Example note:</span> " + p["example_note"] + "</div>" if p.get("example_note") else ""}
          {"<div class='source-pills'>" + sources_html + "</div>" if sources_html else ""}
        </div>'''

    # ── Proposed changes ────────────────────────────────────────────────
    changes_html = ''
    for i, c in enumerate(proposed_changes):
        cl_col     = CHECKLIST_COLOR.get(c['checklist'], '#94a3b8')
        noise_tag  = '<span class="impact-tag" style="color:#34d399;border-color:#34d399">↓ reduces noise</span>' if c.get('reduces_noise') else ''
        detect_tag = '<span class="impact-tag" style="color:#fbbf24;border-color:#fbbf24">↑ improves detection</span>' if c.get('improves_detection') else ''
        diff_html  = ''
        if c.get('current_text'):
            diff_html = f'''
            <div class="diff-block">
              <div class="diff-row">
                <span class="diff-label minus">BEFORE</span>
                <div class="diff-text before-text">{c["current_text"]}</div>
              </div>
              <div class="diff-row">
                <span class="diff-label plus">AFTER</span>
                <div class="diff-text after-text">{c["proposed_text"]}</div>
              </div>
            </div>'''
        else:
            diff_html = f'<div class="proposed-text">{c["proposed_text"]}</div>'

        changes_html += f'''
        <div class="change-card">
          <div class="change-header">
            <div class="change-meta">
              <span class="change-num">CHANGE {i+1}</span>
              <span class="checklist-badge" style="color:{cl_col};border-color:{cl_col}">Checklist {c["checklist"]}</span>
              <span class="changetype-badge">{c["change_type"]}</span>
            </div>
            <div class="impact-tags">{noise_tag}{detect_tag}</div>
          </div>
          <div class="change-field">
            <div class="field-label">Proposed change</div>
            {diff_html}
          </div>
          <div class="change-field">
            <div class="field-label">Evidence</div>
            <div class="field-body">{c["evidence"]}</div>
          </div>
          <div class="change-field risk-field">
            <div class="field-label">Blind spot risk if applied</div>
            <div class="field-body risk-text">{c["blind_spot_risk"]}</div>
          </div>
        </div>'''

    # ── Prior proposal history ──────────────────────────────────────────
    history_html = ''
    for pp in prior_proposals:
        history_html += f'''
        <div class="history-entry">
          <div class="history-dot"></div>
          <div class="history-body">
            <div class="history-date">{pp["date"]}</div>
            <div class="history-stats">
              {pp["reports_read"]} reports analysed &nbsp;·&nbsp;
              {pp["pattern_count"]} patterns found &nbsp;·&nbsp;
              {pp["change_count"]} changes proposed
            </div>
          </div>
        </div>'''
    if not history_html:
        history_html = '<div class="field-body" style="color:#475569">No prior proposals — this is the first learning cycle.</div>'

    # ── Not proposed ───────────────────────────────────────────────────
    np_html = ''
    for np in not_proposed:
        np_html += f'<div class="np-row"><div class="np-desc">{np["description"]}</div><div class="np-reason">Not proposed: {np["reason"]}</div></div>'
    if not np_html:
        np_html = '<div class="np-desc" style="color:#475569">None.</div>'

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Guardian Learning Digest — Cycle {learning_cycle}</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{font-family:"JetBrains Mono",monospace;background:#020617;min-height:100vh;padding:2rem;color:white}}
  .container{{max-width:1200px;margin:0 auto}}
  .header{{margin-bottom:2rem}}
  .header-row{{display:flex;align-items:center;gap:1rem;margin-bottom:.5rem;flex-wrap:wrap}}
  .pulse-dot{{width:12px;height:12px;background:#fbbf24;border-radius:50%;animation:pulse 2s infinite;flex-shrink:0}}
  @keyframes pulse{{0%,100%{{opacity:1;box-shadow:0 0 0 0 rgba(251,191,36,.4)}}50%{{opacity:.7;box-shadow:0 0 0 6px rgba(251,191,36,0)}}}}
  h1{{font-size:1.35rem;font-weight:700}}
  .cycle-badge{{display:inline-block;color:#fbbf24;border:1px solid rgba(251,191,36,.5);border-radius:1rem;font-size:.65rem;font-weight:700;padding:.2rem .65rem;letter-spacing:.07em;margin-left:.75rem;vertical-align:middle}}
  .advisory-tag{{display:inline-block;color:#64748b;border:1px solid #1e293b;border-radius:.25rem;font-size:.6rem;font-weight:700;padding:.15rem .45rem;margin-left:.5rem;letter-spacing:.05em;vertical-align:middle}}
  .subtitle{{color:#94a3b8;font-size:.78rem;margin-left:1.75rem}}
  .summary-bar{{display:flex;gap:1.25rem;margin:1.5rem 0;flex-wrap:wrap}}
  .stat-box{{background:rgba(15,23,42,.6);border:1px solid #1e293b;border-radius:.75rem;padding:.75rem 1.25rem;text-align:center;min-width:130px}}
  .stat-num{{font-size:1.75rem;font-weight:700}}
  .stat-label{{color:#64748b;font-size:.65rem;margin-top:.2rem}}
  .section-title{{font-size:.65rem;font-weight:600;letter-spacing:.12em;color:#475569;text-transform:uppercase;margin:2rem 0 .75rem;padding-bottom:.4rem;border-bottom:1px solid #1e293b;display:flex;align-items:center;gap:.5rem}}
  .section-count{{color:#334155;font-weight:400;font-size:.6rem}}
  .warning-banner{{background:rgba(251,191,36,.08);border:1px solid rgba(251,191,36,.3);border-radius:.5rem;padding:.75rem 1rem;color:#fbbf24;font-size:.75rem;margin-bottom:1.25rem}}
  /* Heatmap */
  .heatmap-wrap{{overflow-x:auto;margin-bottom:1.5rem;background:rgba(15,23,42,.4);border:1px solid #1e293b;border-radius:.5rem;padding:1rem}}
  .heatmap{{border-collapse:collapse;width:100%;font-size:.68rem}}
  .heatmap th{{color:#334155;font-weight:600;padding:.3rem .4rem;text-align:center;font-size:.6rem;white-space:nowrap}}
  .hm-pid-col{{width:2.5rem}}
  .hm-desc-col{{width:14rem;text-align:left!important}}
  .hm-col{{width:3.5rem}}
  .hm-pid{{color:#64748b;font-weight:700;padding:.3rem .4rem;font-size:.68rem}}
  .hm-pdesc{{color:#94a3b8;padding:.3rem .5rem;font-size:.7rem}}
  .hm-cell{{width:3.5rem;height:1.8rem;border-radius:.2rem;margin:.1rem;border:1px solid #0f172a;transition:opacity .2s}}
  .hm-legend{{display:flex;gap:1rem;margin-top:.75rem;flex-wrap:wrap}}
  .hm-leg-item{{display:flex;align-items:center;gap:.35rem;font-size:.65rem;color:#64748b}}
  .hm-leg-dot{{width:10px;height:10px;border-radius:2px}}
  /* Regression */
  .reg-card{{background:rgba(136,19,55,0.1);border:1px solid rgba(251,113,133,.2);border-radius:.5rem;padding:1rem 1.25rem;margin-bottom:.75rem}}
  .reg-header{{display:flex;align-items:center;gap:.75rem;margin-bottom:.75rem}}
  .reg-badge{{color:#fb7185;border:1px solid rgba(251,113,133,.4);border-radius:.25rem;font-size:.6rem;font-weight:700;padding:.15rem .45rem;letter-spacing:.06em}}
  .reg-artifact{{color:#e2e8f0;font-size:.8rem;font-weight:600}}
  .reg-compare{{display:flex;align-items:center;gap:1rem;margin-bottom:.5rem}}
  .reg-ver{{text-align:center}}
  .reg-ver-label{{color:#64748b;font-size:.65rem;margin-bottom:.25rem}}
  .reg-counts{{display:flex;gap:.5rem;font-size:.85rem;font-weight:700}}
  .reg-arrow{{color:#334155;font-size:1.2rem}}
  .reg-deltas{{display:flex;gap:.5rem;align-items:center}}
  .reg-delta{{font-size:.75rem;font-weight:700;background:rgba(15,23,42,.4);padding:.2rem .5rem;border-radius:.25rem}}
  .reg-note{{color:#64748b;font-size:.72rem;margin-top:.5rem;border-top:1px solid rgba(251,113,133,.1);padding-top:.5rem}}
  /* Pattern cards */
  .pattern-card{{background:rgba(15,23,42,.5);border:1px solid #1e293b;border-left:3px solid #334155;border-radius:.5rem;padding:1rem 1.25rem;margin-bottom:.75rem}}
  .pattern-header{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:.6rem;gap:.5rem;flex-wrap:wrap}}
  .pattern-badges{{display:flex;gap:.4rem;align-items:center;flex-wrap:wrap}}
  .type-badge{{font-size:.62rem;font-weight:700;padding:.2rem .5rem;border-radius:.25rem;letter-spacing:.05em}}
  .status-badge{{font-size:.6rem;font-weight:600;padding:.15rem .45rem;border-radius:.25rem;border:1px solid;letter-spacing:.04em}}
  .trend-badge{{font-size:.7rem;font-weight:600}}
  .pattern-desc{{color:#94a3b8;font-size:.8rem;line-height:1.6;margin-bottom:.75rem}}
  .confidence-row{{display:flex;align-items:center;gap:.6rem;margin-bottom:.6rem}}
  .conf-label{{color:#334155;font-size:.65rem;min-width:5rem}}
  .conf-bar-bg{{flex:1;height:6px;background:rgba(30,41,59,.8);border-radius:3px;overflow:hidden}}
  .conf-bar-fill{{height:100%;border-radius:3px;width:var(--pct);animation:grow .8s ease-out forwards}}
  @keyframes grow{{from{{width:0}}to{{width:var(--pct)}}}}
  .conf-pct{{font-size:.72rem;font-weight:700;min-width:2.5rem}}
  .conf-sub{{color:#334155;font-size:.65rem}}
  .example-note{{color:#64748b;font-size:.7rem;padding:.4rem .6rem;background:rgba(30,41,59,.4);border-radius:.25rem;margin-bottom:.5rem}}
  .note-label{{color:#475569}}
  .source-pills{{display:flex;flex-wrap:wrap;gap:.35rem;margin-top:.35rem}}
  .source-pill{{background:rgba(30,41,59,.6);border:1px solid #1e293b;border-radius:.25rem;color:#475569;font-size:.6rem;padding:.15rem .4rem}}
  /* Changes */
  .change-card{{background:rgba(15,23,42,.5);border:1px solid #1e293b;border-radius:.5rem;padding:1.25rem;margin-bottom:.75rem}}
  .change-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;flex-wrap:wrap;gap:.5rem}}
  .change-meta{{display:flex;align-items:center;gap:.5rem;flex-wrap:wrap}}
  .change-num{{color:#475569;font-size:.62rem;font-weight:700}}
  .checklist-badge{{font-size:.65rem;font-weight:700;padding:.2rem .5rem;border-radius:.25rem;border:1px solid;background:rgba(255,255,255,0.04)}}
  .changetype-badge{{font-size:.65rem;color:#64748b;background:rgba(30,41,59,.6);padding:.2rem .5rem;border-radius:.25rem}}
  .impact-tags{{display:flex;gap:.4rem;flex-wrap:wrap}}
  .impact-tag{{font-size:.6rem;font-weight:700;padding:.15rem .4rem;border-radius:.25rem;border:1px solid}}
  .change-field{{margin-bottom:.75rem}}
  .field-label{{color:#475569;font-size:.62rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;margin-bottom:.3rem}}
  .field-body{{color:#94a3b8;font-size:.78rem;line-height:1.6}}
  .diff-block{{border:1px solid #1e293b;border-radius:.35rem;overflow:hidden;margin-bottom:.25rem}}
  .diff-row{{display:flex;gap:0;align-items:stretch}}
  .diff-label{{min-width:3.5rem;display:flex;align-items:center;justify-content:center;font-size:.6rem;font-weight:700;letter-spacing:.06em;padding:.5rem}}
  .diff-label.minus{{background:rgba(136,19,55,.2);color:#fb7185;border-right:1px solid rgba(251,113,133,.2)}}
  .diff-label.plus{{background:rgba(6,78,59,.2);color:#34d399;border-right:1px solid rgba(52,211,153,.2)}}
  .diff-text{{padding:.5rem .75rem;font-size:.75rem;line-height:1.5;flex:1;color:#94a3b8}}
  .before-text{{background:rgba(136,19,55,.08);text-decoration:line-through;color:#64748b}}
  .after-text{{background:rgba(6,78,59,.08);color:#e2e8f0}}
  .proposed-text{{color:#e2e8f0;background:rgba(30,41,59,.5);border-left:2px solid #fbbf24;padding:.5rem .75rem;border-radius:0 .25rem .25rem 0;font-size:.78rem;line-height:1.5}}
  .risk-field{{padding-top:.75rem;border-top:1px solid #0f172a}}
  .risk-text{{color:#fb7185}}
  /* History */
  .history-timeline{{padding-left:1rem}}
  .history-entry{{display:flex;gap:.75rem;align-items:flex-start;padding:.5rem 0;border-left:1px solid #1e293b;margin-left:.35rem;padding-left:.75rem;position:relative}}
  .history-dot{{width:8px;height:8px;background:#a78bfa;border-radius:50%;position:absolute;left:-.45rem;top:.6rem;border:2px solid #020617;flex-shrink:0}}
  .history-date{{color:#a78bfa;font-size:.72rem;font-weight:700;margin-bottom:.2rem}}
  .history-stats{{color:#64748b;font-size:.7rem}}
  /* Not proposed */
  .np-row{{padding:.6rem 0;border-bottom:1px solid #0f172a}}
  .np-desc{{color:#94a3b8;font-size:.78rem;margin-bottom:.2rem}}
  .np-reason{{color:#475569;font-size:.7rem}}
  /* Next step */
  .next-step{{margin-top:1.75rem;background:rgba(76,29,149,.12);border:1px solid rgba(167,139,250,.3);border-radius:.75rem;padding:1.1rem 1.25rem;font-size:.78rem;color:#94a3b8;line-height:1.7}}
  .next-step strong{{color:#a78bfa}}
  code{{background:#0f172a;padding:2px 6px;border-radius:3px;font-size:.72rem;color:#e2e8f0}}
  .footer{{text-align:center;margin-top:1.5rem;color:#334155;font-size:.7rem}}
</style>
</head>
<body>
<div class="container">

  <div class="header">
    <div class="header-row">
      <div class="pulse-dot"></div>
      <h1>Guardian Learning Digest
        <span class="cycle-badge">CYCLE {learning_cycle}</span>
        <span class="advisory-tag">ADVISORY</span>
      </h1>
    </div>
    <p class="subtitle">Self-Improvement Loop — Tier 2 &nbsp;·&nbsp; {gen_date} &nbsp;·&nbsp; Generated by Guardian Feedback Digest v3</p>
  </div>

  <div class="summary-bar">
    <div class="stat-box"><div class="stat-num" style="color:#94a3b8">{total_reports}</div><div class="stat-label">Reports in Corpus</div></div>
    <div class="stat-box"><div class="stat-num" style="color:#fbbf24">+{new_since_last}</div><div class="stat-label">New Since Last Cycle</div></div>
    <div class="stat-box"><div class="stat-num" style="color:#34d399">{reports_with_notes}</div><div class="stat-label">Reviewer Annotations</div></div>
    <div class="stat-box"><div class="stat-num" style="color:#fb7185">{new_pattern_count}</div><div class="stat-label">New Patterns</div></div>
    <div class="stat-box"><div class="stat-num" style="color:#a78bfa">{recurring_count}</div><div class="stat-label">Recurring Patterns</div></div>
    <div class="stat-box"><div class="stat-num" style="color:#22d3ee">{len(proposed_changes)}</div><div class="stat-label">Changes Proposed</div></div>
  </div>

  {warning_html}

  <p class="section-title">Pattern Emergence Heatmap <span class="section-count">— which patterns appeared in which reports</span></p>
  {heatmap_html if heatmap_html else '<div class="field-body" style="color:#475569">No report timeline data — populate report_timeline to enable this view.</div>'}

  {"<p class='section-title'>Regression Alerts <span class='section-count'>— artifacts where quality degraded between versions</span></p>" + regression_html if regressions else ""}

  <p class="section-title">Pattern Knowledge Base <span class="section-count">— {len(patterns)} patterns identified</span></p>
  {patterns_html if patterns_html else '<div class="field-body" style="color:#475569">No patterns identified yet — populate the patterns list.</div>'}

  <p class="section-title">Proposed Checklist Changes <span class="section-count">— requires human approval before any edit is applied</span></p>
  {changes_html if changes_html else '<div class="field-body" style="color:#475569">No changes proposed this cycle.</div>'}

  <p class="section-title">Patterns Considered But Not Proposed</p>
  <div style="background:rgba(15,23,42,.35);border:1px solid #1e293b;border-radius:.5rem;padding:.75rem 1rem">{np_html}</div>

  <p class="section-title">Learning History <span class="section-count">— {len(prior_proposals)} prior cycle{"s" if len(prior_proposals)!=1 else ""}</span></p>
  <div class="history-timeline">{history_html}</div>

  <div class="next-step">
    <strong>Next step — Tier 3 (Human Approval Required)</strong><br><br>
    This proposal has <strong>no effect</strong> until a human reviews the proposed changes above and explicitly runs
    <code>hermes-agent-skill-authoring</code> to apply approved edits to <code>code-and-api-guardian</code>.<br><br>
    Proposals favour tightening over removal — a tighter condition is safer than no check at all.
    Once changes are applied, re-run Guardian on existing artifacts and check whether flagged patterns decline in the next digest cycle.
  </div>

  <p class="footer">OFFICIAL (OPEN) &nbsp;·&nbsp; {gen_date} &nbsp;·&nbsp; PROPOSAL ONLY — NOT APPLIED &nbsp;·&nbsp; Cycle {learning_cycle} of {len(prior_proposals)+1}</p>
</div>
</body>
</html>'''
    return html


# ══════════════════════════════════════════════════════════════════════
# FILL IN from Steps 2–3 analysis. Replace ALL placeholder comments.
# ══════════════════════════════════════════════════════════════════════

gen_date         = _date.today().isoformat()
low_data_warning = reports_with_notes < 3

# One entry per pattern. Set id/type/description/keywords/status/first_detected/trend.
# Do NOT set count/confidence/report_sources — build_report_timeline fills those below.
patterns = [
    # {
    #     'id':             'P1',
    #     'type':           'noisy_rule',     # false_positive | missed_finding | noisy_rule | other
    #     'description':    'SLACK_RETYRY_CONFIG typo fires consistently across reports',
    #     'keywords':       ['SLACK_RETYRY_CONFIG', 'RETYRY_CONFIG'],
    #     'example_note':   '',              # leave blank if no reviewer notes
    #     'status':         'RECURRING',    # NEWLY_DETECTED | RECURRING
    #     'first_detected': '2026-07-14',
    #     'trend':          'stable',       # growing | stable | declining
    # },
]

# Auto-populates heatmap columns and back-fills count/confidence/report_sources on each pattern.
report_timeline = build_report_timeline(patterns, all_reports)

proposed_changes = [
    # {
    #     'checklist':          'A2',
    #     'change_type':        'Add check',
    #     'proposed_text':      'Flag env-var name mismatches ...',
    #     'current_text':       '',         # leave blank if no before-text available
    #     'evidence':           'Seen in reports X, Y, Z',
    #     'evidence_sources':   ['report-x.md'],
    #     'blind_spot_risk':    '...',
    #     'reduces_noise':      True,
    #     'improves_detection': False,
    # },
]

not_proposed = [
    # {'description': '...', 'reason': '...'},
]

html = generate_proposal_page(
    gen_date, learning_cycle, all_reports, prior_proposals,
    low_data_warning, patterns, proposed_changes, not_proposed,
    report_timeline, regressions
)
out = f'/opt/outputs/guardian-improvement-proposal-{gen_date}.html'
os.makedirs('/opt/outputs', exist_ok=True)
with open(out, 'w') as fh:
    fh.write(html)
print(f'Saved: {out} ({len(html):,} bytes)')
```

---

## Important Rules

- Never call hermes-agent-skill-authoring or any skill management command
- Never modify code-and-api-guardian, report-formatter, or any other skill
- Run Step 2 code first (corpus metadata), then Step 3 analysis, then Step 3a (timeline auto-build), then Step 4 (HTML generation) — in that order
- Only manually populate: `patterns` (with `id`, `type`, `description`, `keywords`, `status`, `first_detected`, `trend`), `proposed_changes`, and `not_proposed`
- Never manually set `count`, `confidence`, or `report_sources` on a pattern — Step 3a fills these from keywords
- Populate all lists from actual analysis — do not leave placeholder comments in the saved output
- The ADVISORY tag and footer marking must always appear in the output
- Proposals favour tightening over removing — a tighter condition is safer than no check at all
