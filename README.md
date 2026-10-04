# Hermes Agentic AI Platform

> Exploration of Agentic AI Platforms and Security Hardening: a hardened, multi-user agentic AI platform built on Hermes Agent, with two operational use cases for analysts.

---

## Architecture

```
Browser / VS Code Extension
        |
   OpenWebUI  (port 3000)
        |
 Hermes Wrapper  (port 5000)        ← FastAPI security gateway
        |                             - Per-user API key auth
        |                             - Rate limiting (20 req/min)
        |                             - Input sanitisation
        |                             - Container isolation
        |
 Hermes Agent containers            ← One sandboxed container per analyst
   hermes-<username>                  nousresearch/hermes-agent:latest
        |
   LiteLLM Proxy  (port 4000)       ← Model routing + audit log
        |
 Azure AI Foundry / Anthropic       ← Claude Sonnet 4.6 (primary)
        |                              DeepSeek-R1, Llama-3.3-70B (available)
 MCP Servers (ports 8081–8085)      ← External API bridges
   hermes-cve-mcp      :8081         CVE / NVD vulnerability data
   hermes-framework-mcp :8082        Security frameworks (MAS-TRM, PDPA…)
   hermes-graph-mcp    :8083        Microsoft Graph (Outlook, Teams, Calendar)
   hermes-gmail-mcp    :8084        Google Gmail + Calendar
   hermes-mailpit-mcp  :8085        Mailpit on-prem email simulation
```

---

## Repository Structure

```
hermes-platform/
├── README.md
├── .gitignore
│
├── deployment/
│   ├── docker-compose.yml          ← full platform stack (OpenWebUI, Wrapper, LiteLLM, MCPs)
│   ├── litellm-config.yaml         ← model list + Azure AI Foundry routing (env var placeholders)
│   ├── patches/
│   │   └── misc.py                 ← OpenWebUI empty-content-block bug fix patch
│   └── scripts/
│       ├── provision-user.sh       ← create new analyst container + API key + welcome chat
│       ├── hermes-auto-provision.py ← auto-provision on first login (OpenWebUI function)
│       └── start-hermes-tunnel.sh  ← run this each session to open Azure Bastion tunnel
│
├── hermes-wrapper/                 ← FastAPI security gateway (authentication, rate limiting, routing)
│   ├── app.py
│   ├── requirements.txt
│   └── Dockerfile
│
├── mcp-servers/                    ← External API bridge servers (one per integration)
│   ├── hermes-cve-mcp/             ← CVE / NVD vulnerability data (:8081)
│   ├── hermes-framework-mcp/       ← Security frameworks: MAS-TRM, PDPA, ISO 27001 (:8082)
│   ├── hermes-graph-mcp/           ← Microsoft Graph: Outlook, Teams, Calendar (:8083)
│   ├── hermes-gmail-mcp/           ← Google Gmail + Calendar API (:8084)
│   └── hermes-mailpit-mcp/         ← Mailpit on-prem email simulation (:8085)
│
├── skills/
│   ├── swe-workflow/               ← Use Case 1: Secure SWE Pipeline
│   │   ├── 01-design-advisor/
│   │   ├── 02-adversarial-interview/
│   │   ├── 03-guardian/
│   │   ├── 04-compliance-mapper/
│   │   ├── 05-tabletop-generator/
│   │   ├── 06-feedback-digest/
│   │   └── utilities/
│   │       ├── report-formatter/
│   │       └── skill-router/
│   └── productivity-workflow/      ← Use Case 2: Analyst Productivity
│       ├── gmail/
│       │   ├── gmail-inbox/
│       │   ├── gmail-meeting-prep/
│       │   └── gmail-req-harvester/
│       ├── mailpit-simulation/
│       │   ├── mailpit-inbox/
│       │   ├── mailpit-meeting-prep/
│       │   └── mailpit-req-harvester/
│       └── microsoft/              ← Code complete; Graph API pending admin consent
│           ├── ms-auth-setup/
│           ├── outlook-triage/
│           ├── outlook-meeting-prep/
│           ├── outlook-draft/
│           └── teams-scraper/
│
├── vscode-extension/
│   └── hermes-guardian/            ← VS Code extension for code security scanning
│
├── kubernetes/                     ← AKS migration (future production deployment)
│   ├── k8s/                        ← Kubernetes manifests (namespaces, deployments, services)
│   └── migrate/                    ← Migration scripts (backup → push images → deploy → test)
│
└── docs/
    └── deployment-architecture.html  ← deployment architecture diagram
```

---

## Use Case 1: SWE Security Workflow

A 5-stage pipeline that guides software engineers through security design and code review, with a self-improvement feedback loop.

| Stage | Skill | Description |
|---|---|---|
| 1 | `design-advisor` | System design intake — captures architecture, data flows, threat model scope |
| 2 | `adversarial-design-interview` | Socratic threat-model interview (SW or ML mode) |
| 3 | `code-and-api-guardian` | Code & API security scan — Python, Docker, IaC, RAG pipelines |
| 4 | `compliance-mapper` | Maps findings to MAS-TRM, PDPA, your security frameworks |
| 5 | `tabletop-generator` | Generates tabletop exercise scenarios from threat model |
| ↩ | `guardian-feedback-digest` | Self-improvement: analyses Guardian reports, proposes checklist updates |

Also included: `report-formatter` (standardised output), `skill-router` (skill navigation).

---

## Use Case 2: Analyst Productivity Workflow

Email and calendar intelligence skills for analysts, with on-premises and cloud variants.

**Gmail (Google Workspace):**
- `gmail-inbox` — Triage and summarise inbox
- `gmail-meeting-prep` — Pull agenda, attendees, relevant emails for a meeting
- `gmail-req-harvester` — Extract requirements from email threads → PPTX/DOCX output

> **Gmail test setup (manual):** The Gmail skills require a pre-populated inbox. Before testing, send yourself a representative set of emails: at least one meeting invite with an agenda, one requirements-related thread with multiple replies, and a general triage mix (action items, FYIs, threads). There is no automated seed script for Gmail — the inbox must be created by the tester. Authenticate first by running `ms-auth-setup` equivalent for Gmail (the skill prompts for device-code OAuth on first use).

**Mailpit Simulation (on-premises stand-in):**
- `mailpit-inbox`, `mailpit-meeting-prep`, `mailpit-req-harvester` — Same skills backed by Mailpit SMTP/REST (no cloud dependency)
- Seed the Mailpit inbox before testing: `python3 mcp-servers/hermes-mailpit-mcp/seed_emails.py` (requires Mailpit running on localhost:1025)

**Microsoft (Graph API — pending admin consent):**
- `ms-auth-setup` — Device-code OAuth flow (no browser needed)
- `outlook-triage`, `outlook-meeting-prep`, `outlook-draft` — Outlook email skills
- `teams-scraper` — Teams chat extraction

> Note: Microsoft downstream APIs (Exchange, Teams SP) are blocked by on-premises infrastructure and require admin consent before they become fully operational.

---

## Security Features

| Control | Implementation |
|---|---|
| Per-user container isolation | One `hermes-<username>` container per analyst; no shared state |
| Per-user API keys | `sk-hermes-<hex>` keys; stored in `/data/hermes/api-keys.json` |
| Container hardening | `cap_drop: ALL`, `no-new-privileges`, `read_only` FS, `tmpfs /tmp`, `mem_limit 4g` |
| Input sanitisation | Strips control chars, caps at 32,000 chars (`sanitize_input()`) |
| Rate limiting | 20 requests/min per IP via slowapi |
| ⚠ Marker enforcement | Skills emit machine-readable markers from code output — LLM cannot contradict its own code output, creating hard behavioural constraints |
| Audit logging | LiteLLM PostgreSQL backend logs all model requests with user attribution |
| OWASP LLM Top 10 | 6/10 fully covered, 3/10 partially covered (see docs for detail) |

---

## Prerequisites

- Azure subscription with permission to create VMs and a Bastion host
- Azure AI Foundry deployment with at least one model (Claude Sonnet 4.6 recommended)
- Corporate SSL certificate bundle (`certbundle.crt`) — required for Azure endpoint TLS from the VM
- A local machine with the [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) installed (for Bastion tunnel)

---

## Setup

### Step 1 — Provision the Azure VM

Create a VM matching this spec (no public IP):

| Setting | Value |
|---|---|
| Image | Ubuntu Server 24.04 LTS |
| Size | Standard_D8as_v5 (8 vCPU, 32 GB RAM) |
| Authentication | SSH public key only |
| Public inbound ports | None |
| Data disk | 256 GB Premium SSD |

Configure the NSG:
- Inbound: deny all by default; allow TCP 22 from `AzureBastionSubnet` service tag only
- Outbound: allow HTTPS 443 to `AzureCloud`; deny all else

Create an Azure Bastion host (Standard tier, 2 instances) in the same VNet.

### Step 2 — Connect via Bastion tunnel

Fill in your values in `deployment/scripts/start-hermes-tunnel.sh`, then run it each session:

```bash
bash deployment/scripts/start-hermes-tunnel.sh
# Opens tunnel: localhost:3000 → OpenWebUI, localhost:5000 → Wrapper, localhost:8025 → Mailpit
```

All subsequent steps run **inside the VM** over this tunnel.

### Step 3 — Prepare the VM

```bash
# OS update and security tools
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl git wget unzip fail2ban ufw apparmor auditd

# Mount data disk (replace /dev/sdb with your disk device)
sudo mkfs.ext4 /dev/sdb
sudo mkdir -p /data && sudo mount /dev/sdb /data
UUID=$(sudo blkid -s UUID -o value /dev/sdb)
echo "UUID=$UUID /data ext4 defaults,nofail 0 2" | sudo tee -a /etc/fstab
sudo mkdir -p /data/hermes /data/models /data/logs /data/litellm /data/openwebui
sudo chown -R $USER:$USER /data

# Install Docker
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER && newgrp docker

# Create isolated Docker network
docker network create --driver bridge --subnet 172.20.0.0/16 hermes-net
```

Harden the host OS as well (SSH key-only login, UFW, fail2ban, auditd).

### Step 4 — Clone the repo and configure

```bash
git clone <your-gitlab-url> /data/hermes-platform
cd /data/hermes-platform

# Copy your corporate SSL cert
cp /path/to/certbundle.crt deployment/certbundle.crt

# Apply the OpenWebUI patch (fixes empty content-block bug with Claude)
cp deployment/patches/misc.py /data/openwebui/patches/misc.py

# Set environment variables (add to ~/.bashrc for persistence)
export AZURE_API_BASE="https://<your-foundry-endpoint>"
export AZURE_API_KEY="<your-azure-ai-foundry-key>"
export AZURE_API_VERSION="2024-02-15-preview"
export AZURE_ANTHROPIC_API_BASE="https://<your-anthropic-endpoint>"
export WRAPPER_API_KEY="$(openssl rand -hex 24)"
export LITELLM_MASTER_KEY="$(openssl rand -hex 32)"

# Copy LiteLLM config
cp deployment/litellm-config.yaml /data/litellm/config.yaml
```

### Step 5 — Start the stack

```bash
docker compose -f deployment/docker-compose.yml up -d

# Verify all containers are running
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

### Step 6 — Provision your first user

```bash
bash deployment/scripts/provision-user.sh <username>
# Creates: hermes-<username> container, unique API key, skills profile, welcome chat
```

Access OpenWebUI at `http://localhost:3000` (via Bastion tunnel). Log in with the username you provisioned.

### Step 7 — Seed test data (optional)

```bash
# Mailpit — inject realistic realistic demo emails
python3 mcp-servers/hermes-mailpit-mcp/seed_emails.py

# Gmail — no seed script; manually send yourself a representative set of emails:
#   - At least one meeting invite with an agenda
#   - At least one requirements-related thread with multiple replies
#   - A general triage mix (action items, FYIs, threads)
# Then authenticate: open a skill in OpenWebUI and follow the device-code OAuth prompt.
```

---

## Adding More Users

Each new analyst gets their own isolated container and API key:

```bash
bash deployment/scripts/provision-user.sh <username>
# The generated API key is printed and saved to /data/hermes/profiles/<username>/.api-key
# Share it with the analyst — they enter it as the OpenWebUI API key
```

Auto-provisioning on first login is also available via `deployment/scripts/hermes-auto-provision.py` (configured as an OpenWebUI startup function).

---

## Known Limitations

| Limitation | Status |
|---|---|
| Outlook/Teams blocked by on-prem Exchange | Pending admin consent for Graph API |
| Docker socket bind-mount in wrapper | Intentional trade-off |
| All user containers on same Docker bridge network | Accepted risk for prototype scope |
| API keys stored as local files (no rotation) | Future work: Vault/AKV integration |

---

## Future Deployment: AKS

Kubernetes manifests and migration scripts for deploying to Azure AKS are in `kubernetes/`.

