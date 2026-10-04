"""
One-off script to seed Mailpit with realistic realistic demo emails.
Run from the VM: python3 /data/mailpit-mcp/seed_emails.py
"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

SMTP_HOST = "localhost"
SMTP_PORT = 1025


def send(frm: str, to: str, subject: str, body: str):
    msg = MIMEMultipart()
    msg["From"] = frm
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as s:
        s.sendmail(frm, [to], msg.as_string())
    print(f"  Sent: {subject}")


EMAILS = [
    # ── General inbox ─────────────────────────────────────────────────────────
    (
        "Alex Chen <colleague@example.com>",
        "demo@example.com",
        "Re: Platform access for new joiners",
        """Hi,

Just a heads-up — three new engineers are joining next Monday and will need access to the Hermes platform.
Can you provision accounts for them before EOD Friday?

Their names are:
- Tan Jia Wei
- Priya Nair
- Lim Cheng Huat

Please also make sure they're added to the project Slack channel.

Thanks,
Wei Ming""",
    ),
    (
        "Sam Lee <manager@example.com>",
        "demo@example.com",
        "Sprint 12 retrospective — action items",
        """Hi team,

Following up on yesterday's retro. Here are the agreed action items:

1. Fix the flaky integration tests in the auth module — assign to Wei Ming, due Thu
2. Update the onboarding documentation to reflect the new API key flow — assign to Demo User, due Fri
3. Schedule a knowledge transfer session for the CVE scanner — assign to Raj, next sprint

Also, reminder that Sprint 13 planning is tomorrow at 9am in Conference Room B.

Best,
Sarah""",
    ),
    (
        "IT Helpdesk <helpdesk@example.com>",
        "demo@example.com",
        "VPN certificate renewal — action required by 25 Jul",
        """Dear user,

Your VPN certificate is due to expire on 25 July 2026.
Please renew it before the expiry date to avoid loss of remote access.

Steps:
1. Open the IT Portal at https://itportal.example.com
2. Navigate to My Certificates → Renew
3. Follow the on-screen instructions

If you encounter any issues, contact helpdesk@example.com or call ext. 1234.

IT Helpdesk
[Organisation]""",
    ),
    # ── Requirements thread (for req-harvester demo) ──────────────────────────
    (
        "Jordan Tan <pm@example.com>",
        "demo@example.com",
        "Requirements update — Hermes Phase 2",
        """Hi,

Following the stakeholder review last Friday, here are the updated requirements for Phase 2:

1. The dashboard must display real-time agent activity with a refresh interval of ≤5 seconds.
2. All audit logs must be exportable as CSV and PDF.
3. User roles must support three tiers: Admin, Analyst, and Read-Only.
4. The system must support SSO via SAML 2.0 — this is a hard requirement from the CISO.
5. API rate limits must be configurable per user role (default: 100 req/min for Analyst, 500 for Admin).
6. All skills must be sandboxed — no cross-user data access.
7. The platform must achieve 99.5% uptime measured monthly.

Please confirm these are captured correctly before I send them to the steering committee.

Thanks,
Raj""",
    ),
    (
        "Jordan Tan <pm@example.com>",
        "demo@example.com",
        "Re: Requirements update — Hermes Phase 2",
        """Hi,

One more item I forgot to include:

8. The platform must support dark mode — this was specifically requested by the analysts during the UX review.

Also, item 4 (SAML 2.0) — the CISO has asked that we also support local fallback authentication in case the SSO provider is unavailable. Please add this as a sub-requirement.

Let me know if you need anything else.

Raj""",
    ),
    # ── Meeting prep context (for meeting-prep demo) ──────────────────────────
    (
        "Alex Chen <colleague@example.com>",
        "demo@example.com",
        "Sprint Planning prep — items to discuss",
        """Hi,

Before tomorrow's Sprint Planning, a few things I'd like to raise:

- The authentication service refactor is still in progress — we should decide whether to include it in Sprint 13 or push to Sprint 14.
- The new CVE scanner integration is blocked on the API key from the vendor. Chase status before the meeting?
- We're over-allocated on frontend work this sprint. Suggest we drop the dark mode ticket to the icebox for now.

See you tomorrow at 9am!

Wei Ming""",
    ),
    (
        "Sam Lee <manager@example.com>",
        "demo@example.com",
        "Re: Sprint Planning prep — items to discuss",
        """Thanks Wei Ming,

Agreed on pushing the auth refactor to Sprint 14 — let's not rush it.

On the CVE scanner API key: I've already followed up with the vendor yesterday. They said 3–5 business days. So we should have it by end of next week.

See everyone tomorrow.

Sarah""",
    ),
]


if __name__ == "__main__":
    print(f"Seeding {len(EMAILS)} emails into Mailpit at {SMTP_HOST}:{SMTP_PORT}...")
    for frm, to, subj, body in EMAILS:
        send(frm, to, subj, body)
    print("Done. Open http://localhost:8025 to verify.")
