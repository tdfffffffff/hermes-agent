"""
hermes-framework-mcp — Compliance Framework MCP Server
Serves a local SQLite DB seeded with CIS Controls v8, OWASP Top 10 2021,
NIST CSF, and MITRE ATT&CK techniques. Maps Guardian findings to controls
and attack techniques for compliance-mapper and tabletop-generator.

Exposes:
  /sse                    MCP SSE endpoint
  /messages               MCP POST messages
  /api/search_controls    REST: search controls by keyword / framework
  /api/map_finding        REST: map a vuln type to controls + techniques
  /api/get_techniques     REST: get ATT&CK techniques for a tactic or keyword
  /health                 Health check
"""

import json
import sqlite3
import os
from contextlib import contextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent
import uvicorn

app = FastAPI(title="Hermes Framework MCP", docs_url="/docs")
mcp_server = Server("hermes-framework-mcp")
sse_transport = SseServerTransport("/messages")

DB_PATH = "/tmp/frameworks.db"

# ── Seed data ─────────────────────────────────────────────────────────

CONTROLS = [
    # CIS Controls v8
    ("CIS", "CIS-3.3",  "Configure Data Access Control Lists",
     "Configure data access control lists based on a user's need to know. Apply data access controls at the directory, file, network share, claims, application, and database levels.", "Data Protection",
     "access control,permissions,authorization,files,data,rbac"),
    ("CIS", "CIS-3.11", "Encrypt Sensitive Data at Rest",
     "Encrypt sensitive data at rest on servers, applications, and databases containing sensitive data. Storage encryption, such as BitLocker or dm-crypt, is preferred over application-level encryption.", "Data Protection",
     "encryption,at rest,database,disk,sensitive data"),
    ("CIS", "CIS-4.1",  "Establish and Maintain a Secure Configuration Process",
     "Establish and maintain a documented process for reviewing and updating all system configurations periodically. Establish a secure baseline configuration and apply it to all systems.", "Secure Configuration",
     "baseline,configuration,hardening,docker,container,secure default"),
    ("CIS", "CIS-4.8",  "Uninstall or Disable Unnecessary Services",
     "Uninstall or disable unnecessary services on enterprise assets and software, such as an unused file sharing service, web application module, or service function.", "Secure Configuration",
     "attack surface,unnecessary services,ports,exposed,disable"),
    ("CIS", "CIS-5.2",  "Use Unique Passwords",
     "Use unique passwords for all enterprise assets. Best practice implementation includes 16+ characters, uppercase/lowercase, numbers, special characters. No password reuse.", "Account Management",
     "password,credential,secret,hardcoded,api key,token"),
    ("CIS", "CIS-5.4",  "Restrict Administrator Privileges to Dedicated Admin Accounts",
     "Restrict administrator privileges to dedicated administrator accounts on enterprise assets. Conduct general computing activities, such as internet browsing, from the user's primary, non-privileged account.", "Account Management",
     "admin,root,privilege,least privilege,sudo"),
    ("CIS", "CIS-6.7",  "Centralize Access Control",
     "Centralize access control for all enterprise assets through a directory service or SSO provider, where supported.", "Access Control Management",
     "authentication,sso,ldap,oauth,jwt,identity,missing auth,unauthenticated"),
    ("CIS", "CIS-6.8",  "Define and Maintain Role-Based Access Control",
     "Define and maintain role-based access control, through determining and documenting the access rights necessary for each role within the enterprise and for each system, based on the least privilege principle.", "Access Control Management",
     "rbac,role,authorization,iam,permissions,broken access control,idor"),
    ("CIS", "CIS-7.3",  "Perform Automated Operating System Patch Management",
     "Perform automated operating system patch management using a CVSS score of 4 or higher as the priority. Ensure all patches are applied within 30 days.", "Vulnerability Management",
     "patch,update,outdated,cve,vulnerability,dependency,component"),
    ("CIS", "CIS-7.7",  "Remediate Detected Vulnerabilities",
     "Remediate detected vulnerabilities in software through processes and tooling. Use a risk-based prioritization and SLA. Use a CVSS score to guide severity.", "Vulnerability Management",
     "remediation,vulnerability,patch,fix,outdated component,dependency"),
    ("CIS", "CIS-8.2",  "Collect Audit Logs",
     "Collect audit logs of events that could indicate unusual or potentially harmful activity. Retain logs for at least 90 days.", "Audit Log Management",
     "logging,audit,monitoring,events,missing log,insufficient logging"),
    ("CIS", "CIS-8.5",  "Collect Detailed Audit Logs",
     "Configure detailed audit logging for enterprise assets containing sensitive data. Include event source, date/time, user, source IP, success/failure.", "Audit Log Management",
     "detailed log,audit trail,monitoring,security event,siem"),
    ("CIS", "CIS-12.4", "Establish and Maintain Architecture Diagram(s)",
     "Establish and maintain architecture diagram(s) and/or other system-level documentation that includes all ports, protocols, and services being used.", "Network Infrastructure",
     "network,firewall,port,protocol,ssrf,network rule,egress,ingress"),
    ("CIS", "CIS-16.1", "Establish and Maintain a Secure Application Development Process",
     "Establish and maintain a secure application development process including SAST, DAST, code review, threat modeling, and security requirements.", "Application Software Security",
     "sdlc,secure development,code review,sast,dast,devsecops"),
    ("CIS", "CIS-16.10","Apply Secure Design Principles in Application Architectures",
     "Apply secure design principles such as minimal attack surface, defense in depth, fail securely, and least privilege. Apply especially for insecure deserialization and injection risks.", "Application Software Security",
     "secure design,architecture,deserialization,least privilege,defense in depth"),
    ("CIS", "CIS-16.12","Implement Code-Level Security Checks",
     "Implement code-level security checks, such as using a static analysis tool against all internally-developed software to identify coding errors before production. Addresses injection, XSS, path traversal.", "Application Software Security",
     "sast,static analysis,code scan,injection,xss,sql,command injection,code review"),

    # OWASP Top 10 2021
    ("OWASP", "OWASP-A01", "Broken Access Control",
     "Access control enforces policy such that users cannot act outside of their intended permissions. Failures include IDOR, privilege escalation, path traversal, CORS misconfiguration.", "Access Control",
     "access control,idor,path traversal,privilege escalation,authorization,broken access"),
    ("OWASP", "OWASP-A02", "Cryptographic Failures",
     "Failures related to cryptography which often lead to sensitive data exposure. Includes weak algorithms, hardcoded keys, missing encryption at rest/transit, clear-text storage of secrets.", "Cryptography",
     "encryption,crypto,tls,ssl,weak algorithm,sensitive data,plaintext,at rest"),
    ("OWASP", "OWASP-A03", "Injection",
     "Injection flaws, such as SQL, NoSQL, OS, and LDAP injection, occur when untrusted data is sent to an interpreter as part of a command or query. Also includes XSS and command injection.", "Injection",
     "sql injection,sqli,command injection,xss,injection,ldap,nosql,os command"),
    ("OWASP", "OWASP-A04", "Insecure Design",
     "Insecure design is a broad category representing different weaknesses including missing or ineffective control design. Lack of threat modeling, secure design patterns, and reference architectures.", "Design",
     "insecure design,threat model,architecture,missing control,security requirement"),
    ("OWASP", "OWASP-A05", "Security Misconfiguration",
     "Improper configuration of permissions, unnecessary features, default accounts, error handling, and software not updated. Includes XXE and missing security hardening.", "Configuration",
     "misconfiguration,xxe,xml,default config,unnecessary feature,security header,hardening"),
    ("OWASP", "OWASP-A06", "Vulnerable and Outdated Components",
     "Components such as libraries, frameworks, and software modules run with the same privileges as the application. Outdated or vulnerable components can undermine application defenses.", "Components",
     "outdated,vulnerable component,dependency,library,framework,cve,patch,npm,pip"),
    ("OWASP", "OWASP-A07", "Identification and Authentication Failures",
     "Authentication weaknesses including missing authentication, weak passwords, insecure credential storage, session fixation, missing MFA. Includes hardcoded credentials.", "Authentication",
     "authentication,hardcoded credential,password,session,jwt,token,missing auth,brute force"),
    ("OWASP", "OWASP-A08", "Software and Data Integrity Failures",
     "Failures relating to code and infrastructure that does not protect against integrity violations. Includes insecure deserialization, CI/CD pipeline attacks, auto-update without integrity checks.", "Integrity",
     "deserialization,integrity,pipeline,supply chain,update,pickle,yaml load"),
    ("OWASP", "OWASP-A09", "Security Logging and Monitoring Failures",
     "Without logging and monitoring, breaches cannot be detected. Insufficient logging of security-relevant events, missing alerting, logs not monitored, cleartext credentials in logs.", "Logging",
     "logging,monitoring,audit,alert,missing log,insufficient logging,detection"),
    ("OWASP", "OWASP-A10", "Server-Side Request Forgery (SSRF)",
     "SSRF flaws occur whenever a web application fetches a remote resource without validating the user-supplied URL, allowing attackers to coerce the server to internal resources.", "SSRF",
     "ssrf,server-side request forgery,url,fetch,internal network,metadata"),

    # NIST CSF
    ("NIST_CSF", "NIST-PR.AC-1", "Identity and Credential Management",
     "Identities and credentials are issued, managed, verified, revoked, and audited for authorized devices, users, and processes.", "Protect: Identity Management",
     "identity,credential,password,api key,token,hardcoded,account management"),
    ("NIST_CSF", "NIST-PR.AC-3", "Remote Access Management",
     "Remote access is managed, including authentication and authorisation controls for remote sessions.", "Protect: Identity Management",
     "remote access,vpn,authentication,authorisation,ssh,missing auth"),
    ("NIST_CSF", "NIST-PR.AC-4", "Access Permissions Management",
     "Access permissions and authorizations are managed, incorporating the principles of least privilege and separation of duties.", "Protect: Identity Management",
     "least privilege,rbac,iam,permissions,broken access,over-broad,file permissions"),
    ("NIST_CSF", "NIST-PR.DS-1", "Data-at-Rest Protection",
     "Data-at-rest is protected using encryption or other access controls consistent with the data classification.", "Protect: Data Security",
     "encryption,at rest,database,disk,sensitive data,storage"),
    ("NIST_CSF", "NIST-PR.DS-5", "Data Leak Protection",
     "Protections against data leaks are implemented, including input validation, output encoding, and monitoring for unusual data transfers.", "Protect: Data Security",
     "data leak,injection,xss,sql,input validation,output encoding,path traversal"),
    ("NIST_CSF", "NIST-PR.IP-1", "Baseline Configuration",
     "A baseline configuration of information technology/industrial control systems is created and maintained incorporating security principles.", "Protect: Information Protection",
     "baseline,configuration,hardening,deserialization,secure default,docker"),
    ("NIST_CSF", "NIST-PR.PT-3", "Least Functionality",
     "The principle of least functionality is incorporated by configuring systems to provide only essential capabilities.", "Protect: Protective Technology",
     "least functionality,unnecessary services,attack surface,container root,privilege"),
    ("NIST_CSF", "NIST-PR.PT-4", "Communications Protection",
     "Communications and control networks are protected using network segmentation, firewalls, and encrypted channels.", "Protect: Protective Technology",
     "network,firewall,ssrf,tls,encryption in transit,network rule,egress"),
    ("NIST_CSF", "NIST-ID.RA-1", "Asset Vulnerability Identification",
     "Asset vulnerabilities are identified and documented, including CVE scanning, dependency tracking, and threat intelligence feeds.", "Identify: Risk Assessment",
     "vulnerability,cve,dependency,outdated,component,scan,patch"),
    ("NIST_CSF", "NIST-DE.AE-3", "Event Correlation",
     "Event data are collected and correlated from multiple sources and sensors to detect anomalies and security events.", "Detect: Anomalies and Events",
     "logging,siem,correlation,monitoring,missing log,audit,detection"),
    ("NIST_CSF", "NIST-DE.CM-7", "Unauthorized Activity Monitoring",
     "Monitoring for unauthorized personnel, connections, devices, and software is performed.", "Detect: Continuous Monitoring",
     "monitoring,unauthorized,anomaly,detection,baseline,alert"),
]

TECHNIQUES = [
    ("T1190", "Exploit Public-Facing Application", "Initial Access",
     "Adversaries may attempt to exploit a weakness in an Internet-facing host or system to initially access a network. Includes SQL injection, RCE, path traversal on web apps and APIs.",
     "web application,api,exploit,sql injection,rce,path traversal,public facing,vulnerability"),
    ("T1078", "Valid Accounts", "Initial Access",
     "Adversaries may obtain and abuse credentials of existing accounts to gain initial access. Includes stolen credentials, weak passwords, and hardcoded secrets in code.",
     "credential,password,account,hardcoded,api key,token,brute force,stolen"),
    ("T1110", "Brute Force", "Credential Access",
     "Adversaries may use brute force techniques to gain access to accounts without multi-factor authentication. Includes password spray, credential stuffing.",
     "brute force,password spray,credential stuffing,authentication,missing rate limit,mfa"),
    ("T1552", "Unsecured Credentials", "Credential Access",
     "Adversaries may search compromised systems to find and obtain insecurely stored credentials. Includes credentials in code files, environment variables, configuration files.",
     "hardcoded credential,secret,api key,password,environment variable,config file,token"),
    ("T1059", "Command and Scripting Interpreter", "Execution",
     "Adversaries may abuse command and script interpreters to execute commands, scripts, or binaries. Includes OS command injection and eval/exec on user-controlled input.",
     "command injection,shell,eval,exec,script,os command,subprocess,bash"),
    ("T1068", "Exploitation for Privilege Escalation", "Privilege Escalation",
     "Adversaries may exploit software vulnerabilities in an attempt to elevate privileges. Includes exploiting container misconfigurations like running as root.",
     "privilege escalation,exploit,root,container,sudo,suid,permission"),
    ("T1083", "File and Directory Discovery", "Discovery",
     "Adversaries may enumerate files and directories or may search in specific locations of a host or network share for certain information. Enabled by path traversal vulnerabilities.",
     "path traversal,directory traversal,file discovery,enumeration,listing"),
    ("T1070", "Indicator Removal", "Defense Evasion",
     "Adversaries may delete or alter generated artifacts on a host system, including logs, to hide activity. Insufficient logging means attackers can operate without trace.",
     "log deletion,audit,missing log,insufficient logging,evidence removal,defense evasion"),
    ("T1005", "Data from Local System", "Collection",
     "Adversaries may search local system sources, such as file systems and configuration files, to find files of interest and sensitive data prior to exfiltration.",
     "data collection,file,config,sensitive data,credential,exfiltration,local system"),
    ("T1041", "Exfiltration Over C2 Channel", "Exfiltration",
     "Adversaries may steal data by exfiltrating it over an existing command and control channel. Encrypted or obfuscated to blend in with normal traffic.",
     "exfiltration,data theft,c2,command control,data leak,outbound"),
    ("T1090", "Proxy", "Command and Control",
     "Adversaries may use a connection proxy to direct network traffic between systems or act as an intermediary for network communications. Exploits SSRF to pivot to internal systems.",
     "ssrf,proxy,internal network,metadata,cloud metadata,pivoting"),
    ("T1486", "Data Encrypted for Impact", "Impact",
     "Adversaries may encrypt data on target systems or on large numbers of systems in a network to interrupt availability to system and network resources (ransomware).",
     "ransomware,encryption,impact,availability,data encrypted"),
    ("T1499", "Endpoint Denial of Service", "Impact",
     "Adversaries may perform Endpoint Denial of Service (DoS) attacks to degrade or block the availability of services to users.",
     "dos,denial of service,availability,flood,resource exhaustion"),
    ("T1136", "Create Account", "Persistence",
     "Adversaries may create an account to maintain access to victim systems. Includes creating local, domain, or cloud accounts after initial access.",
     "account creation,persistence,backdoor,user,admin account"),
    ("T1505", "Server Software Component", "Persistence",
     "Adversaries may install backdoors via legitimate server software to establish persistent access. Includes web shells and malicious plugins.",
     "webshell,backdoor,plugin,persistence,server component"),
]

# Vulnerability type → (controls, techniques) mappings
VULN_MAPPINGS = {
    "sql injection":              (["OWASP-A03","CIS-16.12","NIST-PR.DS-5"],           ["T1190","T1059"]),
    "sqli":                       (["OWASP-A03","CIS-16.12","NIST-PR.DS-5"],           ["T1190","T1059"]),
    "xss":                        (["OWASP-A03","CIS-16.12","NIST-PR.DS-5"],           ["T1059"]),
    "cross-site scripting":       (["OWASP-A03","CIS-16.12","NIST-PR.DS-5"],           ["T1059"]),
    "path traversal":             (["OWASP-A01","CIS-16.12","NIST-PR.DS-5"],           ["T1190","T1083"]),
    "directory traversal":        (["OWASP-A01","CIS-16.12","NIST-PR.DS-5"],           ["T1190","T1083"]),
    "command injection":          (["OWASP-A03","CIS-16.12","NIST-PR.DS-5"],           ["T1059","T1190"]),
    "os command injection":       (["OWASP-A03","CIS-16.12","NIST-PR.DS-5"],           ["T1059","T1190"]),
    "ssrf":                       (["OWASP-A10","NIST-PR.PT-4","CIS-12.4"],            ["T1090","T1005"]),
    "server-side request forgery":(["OWASP-A10","NIST-PR.PT-4","CIS-12.4"],            ["T1090","T1005"]),
    "xxe":                        (["OWASP-A05","CIS-16.12","NIST-PR.DS-5"],           ["T1190"]),
    "xml external entity":        (["OWASP-A05","CIS-16.12","NIST-PR.DS-5"],           ["T1190"]),
    "hardcoded credential":       (["OWASP-A07","CIS-5.2","NIST-PR.AC-1"],             ["T1552","T1078"]),
    "hardcoded password":         (["OWASP-A07","CIS-5.2","NIST-PR.AC-1"],             ["T1552","T1078"]),
    "hardcoded secret":           (["OWASP-A07","CIS-5.2","NIST-PR.AC-1"],             ["T1552","T1078"]),
    "secrets in image":           (["OWASP-A07","CIS-5.2","NIST-PR.AC-1"],             ["T1552"]),
    "missing authentication":     (["OWASP-A07","CIS-6.7","NIST-PR.AC-3"],             ["T1078","T1110"]),
    "broken authentication":      (["OWASP-A07","CIS-6.7","NIST-PR.AC-3"],             ["T1078","T1110"]),
    "broken access control":      (["OWASP-A01","CIS-6.8","NIST-PR.AC-4"],             ["T1078","T1068"]),
    "idor":                       (["OWASP-A01","CIS-6.8","NIST-PR.AC-4"],             ["T1078"]),
    "insecure deserialization":   (["OWASP-A08","CIS-16.10","NIST-PR.IP-1"],           ["T1059","T1190"]),
    "deserialization":            (["OWASP-A08","CIS-16.10","NIST-PR.IP-1"],           ["T1059","T1190"]),
    "outdated component":         (["OWASP-A06","CIS-7.7","NIST-ID.RA-1"],             ["T1190"]),
    "vulnerable dependency":      (["OWASP-A06","CIS-7.7","NIST-ID.RA-1"],             ["T1190"]),
    "missing logging":            (["OWASP-A09","CIS-8.2","NIST-DE.AE-3"],             ["T1070"]),
    "insufficient logging":       (["OWASP-A09","CIS-8.2","NIST-DE.AE-3"],             ["T1070"]),
    "insecure file permissions":  (["CIS-3.3","NIST-PR.AC-4","OWASP-A01"],             ["T1083","T1005"]),
    "container running as root":  (["CIS-4.1","NIST-PR.PT-3","CIS-5.4"],              ["T1068"]),
    "container escape":           (["CIS-4.1","NIST-PR.PT-3","CIS-4.8"],              ["T1068","T1190"]),
    "wide-open network rules":    (["CIS-12.4","NIST-PR.PT-4","OWASP-A05"],           ["T1190","T1090"]),
    "open network rules":         (["CIS-12.4","NIST-PR.PT-4","OWASP-A05"],           ["T1190"]),
    "over-broad iam":             (["CIS-6.8","NIST-PR.AC-4","CIS-5.4"],              ["T1078","T1068"]),
    "over-permissive roles":      (["CIS-6.8","NIST-PR.AC-4","CIS-5.4"],              ["T1078","T1068"]),
    "prompt injection":           (["OWASP-A03","CIS-16.12","NIST-PR.DS-5"],           ["T1059","T1190"]),
    "unsafe subprocess":          (["OWASP-A03","CIS-16.12","NIST-PR.DS-5"],           ["T1059"]),
    "unvalidated input":          (["OWASP-A03","CIS-16.12","NIST-PR.DS-5"],           ["T1190","T1059"]),
    "csrf":                       (["OWASP-A01","CIS-16.12","NIST-PR.DS-5"],           ["T1059"]),
}

# ── DB initialisation ─────────────────────────────────────────────────

def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS controls (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            framework   TEXT NOT NULL,
            control_id  TEXT NOT NULL UNIQUE,
            title       TEXT NOT NULL,
            description TEXT NOT NULL,
            category    TEXT,
            keywords    TEXT
        );
        CREATE TABLE IF NOT EXISTS techniques (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            technique_id TEXT NOT NULL UNIQUE,
            name         TEXT NOT NULL,
            tactic       TEXT NOT NULL,
            description  TEXT NOT NULL,
            keywords     TEXT
        );
        CREATE TABLE IF NOT EXISTS vuln_mappings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            vuln_type   TEXT NOT NULL,
            control_ids TEXT NOT NULL,
            tech_ids    TEXT NOT NULL
        );
    """)
    # Seed controls
    cur.executemany(
        "INSERT OR IGNORE INTO controls (framework, control_id, title, description, category, keywords) VALUES (?,?,?,?,?,?)",
        CONTROLS
    )
    # Seed techniques
    cur.executemany(
        "INSERT OR IGNORE INTO techniques (technique_id, name, tactic, description, keywords) VALUES (?,?,?,?,?)",
        TECHNIQUES
    )
    # Seed mappings
    cur.executemany(
        "INSERT OR IGNORE INTO vuln_mappings (vuln_type, control_ids, tech_ids) VALUES (?,?,?)",
        [(k, json.dumps(v[0]), json.dumps(v[1])) for k, v in VULN_MAPPINGS.items()]
    )
    con.commit()
    con.close()

@contextmanager
def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()

# ── Core query functions ──────────────────────────────────────────────

def search_controls(keyword: str = "", frameworks: list = None) -> list:
    with get_db() as con:
        base = "SELECT framework, control_id, title, description, category FROM controls WHERE 1=1"
        params = []
        if keyword:
            base += " AND (LOWER(title) LIKE ? OR LOWER(description) LIKE ? OR LOWER(keywords) LIKE ?)"
            k = f"%{keyword.lower()}%"
            params += [k, k, k]
        if frameworks:
            placeholders = ",".join("?" * len(frameworks))
            base += f" AND framework IN ({placeholders})"
            params += frameworks
        base += " ORDER BY framework, control_id LIMIT 20"
        rows = con.execute(base, params).fetchall()
        return [dict(r) for r in rows]


def map_finding(vuln_type: str) -> dict:
    """Map a vulnerability type to relevant controls and ATT&CK techniques."""
    key = vuln_type.lower().strip()
    with get_db() as con:
        # Try exact match first, then fuzzy
        row = con.execute(
            "SELECT control_ids, tech_ids FROM vuln_mappings WHERE LOWER(vuln_type) = ?", [key]
        ).fetchone()
        if not row:
            row = con.execute(
                "SELECT control_ids, tech_ids FROM vuln_mappings WHERE LOWER(vuln_type) LIKE ?",
                [f"%{key}%"]
            ).fetchone()

        if row:
            control_ids = json.loads(row["control_ids"])
            tech_ids    = json.loads(row["tech_ids"])
        else:
            # Fallback: keyword search on controls
            control_ids = [r["control_id"] for r in search_controls(key)[:4]]
            tech_ids    = []

        controls = []
        for cid in control_ids:
            r = con.execute(
                "SELECT framework, control_id, title, description FROM controls WHERE control_id = ?", [cid]
            ).fetchone()
            if r:
                controls.append(dict(r))

        techniques = []
        for tid in tech_ids:
            r = con.execute(
                "SELECT technique_id, name, tactic, description FROM techniques WHERE technique_id = ?", [tid]
            ).fetchone()
            if r:
                techniques.append(dict(r))

    return {"vuln_type": vuln_type, "controls": controls, "techniques": techniques}


def get_techniques(tactic: str = "", keyword: str = "") -> list:
    with get_db() as con:
        base = "SELECT technique_id, name, tactic, description FROM techniques WHERE 1=1"
        params = []
        if tactic:
            base += " AND LOWER(tactic) LIKE ?"
            params.append(f"%{tactic.lower()}%")
        if keyword:
            base += " AND (LOWER(name) LIKE ? OR LOWER(description) LIKE ? OR LOWER(keywords) LIKE ?)"
            k = f"%{keyword.lower()}%"
            params += [k, k, k]
        rows = con.execute(base + " ORDER BY tactic, technique_id", params).fetchall()
        return [dict(r) for r in rows]

# ── REST endpoints ────────────────────────────────────────────────────

@app.on_event("startup")
def startup():
    init_db()

@app.get("/health")
async def health():
    return {"status": "ok", "service": "hermes-framework-mcp"}

@app.get("/api/search_controls")
async def search_controls_rest(keyword: str = "", frameworks: str = ""):
    fw_list = [f.strip() for f in frameworks.split(",") if f.strip()] if frameworks else []
    return JSONResponse(search_controls(keyword, fw_list or None))

@app.get("/api/map_finding")
async def map_finding_rest(vuln_type: str):
    return JSONResponse(map_finding(vuln_type))

@app.get("/api/get_techniques")
async def get_techniques_rest(tactic: str = "", keyword: str = ""):
    return JSONResponse(get_techniques(tactic, keyword))

@app.get("/api/list_frameworks")
async def list_frameworks():
    with get_db() as con:
        rows = con.execute("SELECT DISTINCT framework FROM controls ORDER BY framework").fetchall()
    return JSONResponse([r["framework"] for r in rows])

# ── MCP tool definitions ──────────────────────────────────────────────

@mcp_server.list_tools()
async def list_tools():
    return [
        Tool(
            name="search_controls",
            description="Search compliance framework controls by keyword and/or framework name (CIS, OWASP, NIST_CSF). Returns matching controls with descriptions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "keyword":    {"type": "string", "description": "Search keyword, e.g. 'authentication' or 'logging'"},
                    "frameworks": {"type": "array", "items": {"type": "string"}, "description": "Filter by framework: ['CIS'], ['OWASP'], ['NIST_CSF'], or multiple"},
                },
            },
        ),
        Tool(
            name="map_finding_to_controls",
            description="Map a vulnerability type from a Guardian scan to relevant compliance controls and MITRE ATT&CK techniques.",
            inputSchema={
                "type": "object",
                "properties": {
                    "vuln_type": {"type": "string", "description": "Vulnerability type, e.g. 'sql injection', 'hardcoded credential'"},
                },
                "required": ["vuln_type"],
            },
        ),
        Tool(
            name="get_attack_techniques",
            description="Get MITRE ATT&CK techniques filtered by tactic phase or keyword, for building tabletop exercise scenarios.",
            inputSchema={
                "type": "object",
                "properties": {
                    "tactic":  {"type": "string", "description": "ATT&CK tactic, e.g. 'Initial Access', 'Credential Access'"},
                    "keyword": {"type": "string", "description": "Keyword to filter techniques, e.g. 'injection', 'credential'"},
                },
            },
        ),
    ]


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "search_controls":
        result = search_controls(arguments.get("keyword", ""), arguments.get("frameworks"))
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    elif name == "map_finding_to_controls":
        result = map_finding(arguments["vuln_type"])
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    elif name == "get_attack_techniques":
        result = get_techniques(arguments.get("tactic", ""), arguments.get("keyword", ""))
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]


# ── MCP SSE endpoints ─────────────────────────────────────────────────

@app.get("/sse")
async def sse_endpoint(request: Request):
    async with sse_transport.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await mcp_server.run(
            streams[0], streams[1],
            mcp_server.create_initialization_options(),
        )

app.mount("/messages", sse_transport.handle_post_message)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8082)
