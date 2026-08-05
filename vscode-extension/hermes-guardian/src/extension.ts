import * as vscode from 'vscode';
import * as http from 'http';

const HERMES_HOST = 'localhost';

export function activate(context: vscode.ExtensionContext) {
    const cmd = vscode.commands.registerCommand('hermes.scanFile', async () => {
        const editor = vscode.window.activeTextEditor;
        if (!editor) {
            vscode.window.showErrorMessage('No file open to scan.');
            return;
        }

        const code = editor.document.getText();
        const filename = editor.document.fileName.split('/').pop() || 'unknown';

        await vscode.window.withProgress(
            {
                location: vscode.ProgressLocation.Notification,
                title: `Guardian scanning ${filename}...`,
                cancellable: false
            },
            async () => {
                try {
                    const report = await callHermes(code, filename);
                    await showBestReport(report, filename, 'Guardian');
                } catch (err) {
                    vscode.window.showErrorMessage(`Hermes error: ${err}`);
                }
            }
        );
    });

    const legacyCmd = vscode.commands.registerCommand('hermes.legacyReview', async () => {
        const editor = vscode.window.activeTextEditor;
        if (!editor) {
            vscode.window.showErrorMessage('No file open to review.');
            return;
        }

        const lang = editor.document.languageId;
        if (lang !== 'python' && lang !== 'shellscript') {
            vscode.window.showWarningMessage('Legacy Code Review only supports Python and Bash files.');
            return;
        }

        const code = editor.document.getText();
        const filename = editor.document.fileName.split('/').pop() || 'unknown';

        await vscode.window.withProgress(
            {
                location: vscode.ProgressLocation.Notification,
                title: `Legacy Review scanning ${filename}...`,
                cancellable: false
            },
            async () => {
                try {
                    const report = await callHermes(code, filename, 'Use the code-reviewer skill');
                    await showBestReport(report, filename, 'Legacy Review');
                } catch (err) {
                    vscode.window.showErrorMessage(`Hermes error: ${err}`);
                }
            }
        );
    });

    const complianceCmd = vscode.commands.registerCommand('hermes.complianceMapper', async () => {
        const reportFile = await vscode.window.showInputBox({
            prompt: 'Enter the Guardian report filename in /opt/outputs/',
            placeHolder: 'guardian-report-myfile-2026-07-10.md',
            validateInput: v => v ? null : 'Enter a filename'
        });
        if (!reportFile) { return; }

        await vscode.window.withProgress(
            {
                location: vscode.ProgressLocation.Notification,
                title: 'Compliance Mapper running...',
                cancellable: false
            },
            async () => {
                try {
                    const report = await callHermes(
                        '',
                        reportFile,
                        `Use the compliance-mapper skill to map the findings in /opt/outputs/${reportFile} to CIS Controls, OWASP Top 10, and NIST CSF. Generate the compliance coverage matrix report`
                    );
                    await showBestReport(report, reportFile, 'Compliance Mapper');
                } catch (err) {
                    vscode.window.showErrorMessage(`Hermes error: ${err}`);
                }
            }
        );
    });

    const tabletopCmd = vscode.commands.registerCommand('hermes.tabletopGenerator', async () => {
        const reportFile = await vscode.window.showInputBox({
            prompt: 'Enter the Guardian/Compliance report filename in /opt/outputs/',
            placeHolder: 'guardian-report-myfile-2026-07-10.md',
            validateInput: v => v ? null : 'Enter a filename'
        });
        if (!reportFile) { return; }

        await vscode.window.withProgress(
            {
                location: vscode.ProgressLocation.Notification,
                title: 'Tabletop Generator running...',
                cancellable: false
            },
            async () => {
                try {
                    const report = await callHermes(
                        '',
                        reportFile,
                        `Use the tabletop-generator skill to build a tabletop exercise from the findings in /opt/outputs/${reportFile}. Generate a full 5-phase facilitator-ready scenario with ATT&CK techniques`
                    );
                    await showBestReport(report, reportFile, 'Tabletop Generator');
                } catch (err) {
                    vscode.window.showErrorMessage(`Hermes error: ${err}`);
                }
            }
        );
    });

    const digestCmd = vscode.commands.registerCommand('hermes.feedbackDigest', async () => {
        const confirm = await vscode.window.showInformationMessage(
            'Run Guardian Feedback Digest? This reads all past reports in /opt/outputs/ and proposes checklist improvements.',
            'Run', 'Cancel'
        );
        if (confirm !== 'Run') { return; }

        await vscode.window.withProgress(
            {
                location: vscode.ProgressLocation.Notification,
                title: 'Guardian Feedback Digest running...',
                cancellable: false
            },
            async () => {
                try {
                    const report = await callDigest();
                    await showBestReport(report, 'feedback-digest', 'Feedback Digest');
                } catch (err) {
                    vscode.window.showErrorMessage(`Hermes error: ${err}`);
                }
            }
        );
    });

    context.subscriptions.push(cmd);
    context.subscriptions.push(legacyCmd);
    context.subscriptions.push(digestCmd);
    context.subscriptions.push(complianceCmd);
    context.subscriptions.push(tabletopCmd);
}

// ── Hermes API call ────────────────────────────────────────────────────────
function callHermes(code: string, filename: string, skillPrefix = 'Use the code-and-api-guardian skill to scan this file'): Promise<string> {
    return new Promise((resolve, reject) => {
        const config = vscode.workspace.getConfiguration('hermesGuardian');
        const container = config.get<string>('containerName') || '';
        const apiKey = config.get<string>('apiKey') || '';
        const port = config.get<number>('port') || 5000;

        if (!apiKey) {
            reject(new Error('API key not set. Go to Settings → Extensions → Hermes Guardian and enter your API key (sk-hermes-...).'));
            return;
        }

        const isUserKey = apiKey.startsWith('sk-hermes-');

        if (!isUserKey && !container) {
            reject(new Error('Container name not set. When using the shared admin key, set your container name in Hermes Guardian settings.'));
            return;
        }

        const prompt = `${skillPrefix} (${filename}):\n\n${code}`;
        const model = isUserKey ? 'hermes-agent' : container;

        const body = JSON.stringify({
            model,
            messages: [{ role: 'user', content: prompt }],
            stream: true
        });

        const usernameHeader = container.startsWith('hermes-') ? container.slice(7) : container;

        const reqHeaders: Record<string, string | number> = {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${apiKey}`,
            'Content-Length': Buffer.byteLength(body)
        };
        if (!isUserKey && usernameHeader) {
            reqHeaders['X-OpenWebUI-User-Name'] = usernameHeader;
        }

        const options: http.RequestOptions = {
            hostname: HERMES_HOST,
            port: port,
            path: '/v1/chat/completions',
            method: 'POST',
            headers: reqHeaders
        };

        let fullText = '';

        const req = http.request(options, (res: http.IncomingMessage) => {
            let buffer = '';

            res.on('data', (chunk: Buffer) => {
                buffer += chunk.toString();
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const data = line.slice(6).trim();
                        if (data === '[DONE]') { continue; }
                        try {
                            const parsed = JSON.parse(data);
                            const content = parsed.choices?.[0]?.delta?.content;
                            if (content) { fullText += content; }
                        } catch { /* ignore malformed chunks */ }
                    }
                }
            });

            res.on('end', () => resolve(fullText));
            res.on('error', reject);
        });

        req.on('error', reject);
        req.write(body);
        req.end();
    });
}

function callDigest(): Promise<string> {
    return callHermes(
        '',
        '',
        'Use the guardian-feedback-digest skill to analyse all reports in /opt/outputs/ and generate a checklist improvement proposal. Ignore the filename parameter'
    );
}

// ── Text helpers ───────────────────────────────────────────────────────────

/** Strip sh: shell error lines that leak from the Hermes agent runtime. */
function filterShErrors(text: string): string {
    return text
        .split('\n')
        .filter(line => {
            // sh/bash/dash/ksh with or without path prefix, with or without line number
            // Covers: "sh: 1: cmd: not found", "/bin/sh: cmd: not found", "bash: pip: command not found"
            return !line.match(/^(\/[\w/]+\/)?(sh|bash|dash|ksh|zsh):\s+(\d+:\s+)?.+:\s+(not found|command not found|Permission denied|Syntax error|No such file|Bad substitution|cannot execute)/i);
        })
        .join('\n')
        .replace(/^\n+/, '')
        .trim();
}

function escapeHtml(text: string): string {
    return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

function inlineMarkdown(text: string): string {
    return escapeHtml(text)
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/\*([^*]+)\*/g, '<em>$1</em>')
        .replace(/`([^`]+)`/g, '<code>$1</code>');
}

/** Convert Guardian-style markdown to HTML. */
function markdownToHtml(md: string): string {
    const lines = md.split('\n');
    let html = '';
    let inCodeBlock = false;
    let inTable = false;
    let tableHasHeader = false;
    let inList = false;
    let inOrderedList = false;

    const closeOpenBlocks = () => {
        if (inList)        { html += '</ul>\n';              inList = false; }
        if (inOrderedList) { html += '</ol>\n';              inOrderedList = false; }
        if (inTable)       { html += '</tbody></table>\n';   inTable = false; tableHasHeader = false; }
    };

    for (const line of lines) {
        // ── Code block fence ──────────────────────────────────────────────
        if (line.startsWith('```')) {
            if (inCodeBlock) {
                html += '</code></pre>\n';
                inCodeBlock = false;
            } else {
                closeOpenBlocks();
                const lang = escapeHtml(line.slice(3).trim() || 'text');
                html += `<pre><code class="lang-${lang}">`;
                inCodeBlock = true;
            }
            continue;
        }

        if (inCodeBlock) {
            html += escapeHtml(line) + '\n';
            continue;
        }

        // ── Table row ─────────────────────────────────────────────────────
        if (line.startsWith('|')) {
            // Separator row (|---|---|) — marks end of header
            if (line.match(/^\|[\s\-|:]+\|$/)) {
                tableHasHeader = true;
                if (inTable) { html += '</thead>\n<tbody>\n'; }
                continue;
            }
            const cells = line.split('|').slice(1, -1).map(c => c.trim());
            if (!inTable) {
                closeOpenBlocks();
                html += '<table>\n<thead>\n';
                inTable = true;
                tableHasHeader = false;
            }
            const tag = (!tableHasHeader) ? 'th' : 'td';
            html += '<tr>' + cells.map(c => `<${tag}>${inlineMarkdown(c)}</${tag}>`).join('') + '</tr>\n';
            continue;
        } else if (inTable) {
            html += '</tbody></table>\n';
            inTable = false;
            tableHasHeader = false;
        }

        // ── Headings ──────────────────────────────────────────────────────
        if (line.startsWith('### ')) {
            closeOpenBlocks();
            html += `<h3>${inlineMarkdown(line.slice(4))}</h3>\n`;
        } else if (line.startsWith('## ')) {
            closeOpenBlocks();
            html += `<h2>${inlineMarkdown(line.slice(3))}</h2>\n`;
        } else if (line.startsWith('# ')) {
            closeOpenBlocks();
            html += `<h1>${inlineMarkdown(line.slice(2))}</h1>\n`;
        }
        // ── Horizontal rule ───────────────────────────────────────────────
        else if (line.match(/^(-{3,}|={3,})$/)) {
            closeOpenBlocks();
            html += '<hr>\n';
        }
        // ── Ordered list ──────────────────────────────────────────────────
        else if (line.match(/^\d+\. /)) {
            if (inList)  { html += '</ul>\n'; inList = false; }
            if (!inOrderedList) { html += '<ol>\n'; inOrderedList = true; }
            html += `<li>${inlineMarkdown(line.replace(/^\d+\. /, ''))}</li>\n`;
        }
        // ── Unordered list ────────────────────────────────────────────────
        else if (line.match(/^[-*] /)) {
            if (inOrderedList) { html += '</ol>\n'; inOrderedList = false; }
            if (!inList) { html += '<ul>\n'; inList = true; }
            html += `<li>${inlineMarkdown(line.slice(2))}</li>\n`;
        }
        // ── Indented continuation / code-like line ────────────────────────
        else if (line.startsWith('  ') && line.trim()) {
            html += `<p class="indent">${inlineMarkdown(line.trim())}</p>\n`;
        }
        // ── Blank line ────────────────────────────────────────────────────
        else if (line.trim() === '') {
            closeOpenBlocks();
            html += '\n';
        }
        // ── Paragraph ─────────────────────────────────────────────────────
        else {
            closeOpenBlocks();
            html += `<p>${inlineMarkdown(line)}</p>\n`;
        }
    }

    if (inCodeBlock)   { html += '</code></pre>\n'; }
    if (inTable)       { html += '</tbody></table>\n'; }
    if (inList)        { html += '</ul>\n'; }
    if (inOrderedList) { html += '</ol>\n'; }

    return html;
}

// ── Panel display ──────────────────────────────────────────────────────────

/**
 * Fetch a file from the user's /opt/outputs/ via the wrapper's /outputs/ endpoint.
 * Returns file content on success, null if unavailable.
 */
function fetchOutputFile(filename: string): Promise<string | null> {
    return new Promise((resolve) => {
        const config = vscode.workspace.getConfiguration('hermesGuardian');
        const apiKey = config.get<string>('apiKey') || '';
        const port = config.get<number>('port') || 5000;
        const container = config.get<string>('containerName') || '';
        const isUserKey = apiKey.startsWith('sk-hermes-');
        const usernameHeader = container.startsWith('hermes-') ? container.slice(7) : container;

        const reqHeaders: Record<string, string> = { 'Authorization': `Bearer ${apiKey}` };
        if (!isUserKey && usernameHeader) {
            reqHeaders['X-OpenWebUI-User-Name'] = usernameHeader;
        }

        const options: http.RequestOptions = {
            hostname: HERMES_HOST,
            port,
            path: `/outputs/${encodeURIComponent(filename)}`,
            method: 'GET',
            headers: reqHeaders
        };

        let data = '';
        const req = http.request(options, (res: http.IncomingMessage) => {
            if (res.statusCode !== 200) { resolve(null); return; }
            res.on('data', (chunk: Buffer) => { data += chunk.toString(); });
            res.on('end', () => resolve(data || null));
            res.on('error', () => resolve(null));
        });
        req.on('error', () => resolve(null));
        req.end();
    });
}

/**
 * Display the report.
 * 1. Filter sh: errors from the streamed response.
 * 2. If the skill saved an HTML file, fetch and show that (the proper dashboard).
 * 3. If not, fall back to markdown-to-HTML renderer.
 * 4. Always show raw markdown in a second panel (col 3).
 */
async function showBestReport(rawReport: string, filename: string, label: string) {
    const clean = filterShErrors(rawReport);

    // Raw markdown always visible in col 3
    const mdPanel = vscode.window.createWebviewPanel(
        'hermesMdReport',
        `${label} (MD) — ${filename}`,
        vscode.ViewColumn.Three,
        { enableScripts: false, retainContextWhenHidden: true }
    );
    mdPanel.webview.html = buildMarkdownPage(clean, label, filename);

    // Try skill-generated HTML first (the dashboard format).
    // Use the last HTML path in the response — earlier paths are inputs (e.g. the Guardian report
    // passed to the compliance mapper), while the output file is always listed last.
    const htmlMatches = [...clean.matchAll(/\/opt\/outputs\/([^\s)]+\.html)/g)];
    const htmlMatch = htmlMatches.length > 0 ? htmlMatches[htmlMatches.length - 1] : null;
    if (htmlMatch) {
        const skillHtml = await fetchOutputFile(htmlMatch[1]);
        if (skillHtml) {
            const panel = vscode.window.createWebviewPanel(
                'hermesHtmlReport',
                `${label} — ${filename}`,
                vscode.ViewColumn.Two,
                { enableScripts: false, retainContextWhenHidden: true }
            );
            // Strip Google Fonts link — VS Code webview blocks external requests
            panel.webview.html = skillHtml.replace(/<link[^>]*fonts\.googleapis\.com[^>]*>/gi, '');
            return;
        }
    }

    // Fallback: render markdown as HTML
    const htmlPanel = vscode.window.createWebviewPanel(
        'hermesHtmlReport',
        `${label} — ${filename}`,
        vscode.ViewColumn.Two,
        { enableScripts: false, retainContextWhenHidden: true }
    );
    htmlPanel.webview.html = buildHtmlPage(markdownToHtml(clean), label, filename);
}

function buildHtmlPage(bodyHtml: string, label: string, filename: string): string {
    return `<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         padding: 20px 28px; line-height: 1.65; background: #1e1e1e; color: #d4d4d4;
         max-width: 900px; margin: 0 auto; }
  h1 { color: #569cd6; font-size: 1.3em; border-bottom: 1px solid #444; padding-bottom: 6px; }
  h2 { color: #4ec9b0; font-size: 1.1em; margin-top: 1.4em; }
  h3 { color: #ce9178; font-size: 1em; }
  hr { border: none; border-top: 1px solid #444; margin: 16px 0; }
  p  { margin: 6px 0; }
  p.indent { margin-left: 1.5em; color: #9cdcfe; }
  strong { color: #dcdcaa; }
  code { background: #2d2d2d; color: #ce9178; padding: 1px 5px;
         border-radius: 3px; font-family: 'Cascadia Code', Consolas, monospace; font-size: 0.9em; }
  pre  { background: #2d2d2d; padding: 12px 16px; border-radius: 6px;
         overflow-x: auto; border-left: 3px solid #569cd6; }
  pre code { background: none; padding: 0; color: #d4d4d4; }
  table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 0.92em; }
  th { background: #2d2d2d; color: #4ec9b0; padding: 7px 10px;
       text-align: left; border: 1px solid #444; }
  td { padding: 6px 10px; border: 1px solid #333; vertical-align: top; }
  tr:nth-child(even) td { background: #252525; }
  ul, ol { padding-left: 1.6em; margin: 6px 0; }
  li { margin: 3px 0; }
  .header { background: #252525; border-left: 4px solid #569cd6;
            padding: 8px 14px; margin-bottom: 16px; font-size: 0.85em; color: #888; }
</style>
</head>
<body>
<div class="header">${escapeHtml(label)} &nbsp;·&nbsp; ${escapeHtml(filename)}</div>
${bodyHtml}
</body>
</html>`;
}

function buildMarkdownPage(md: string, label: string, filename: string): string {
    const escaped = escapeHtml(md);
    return `<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body { font-family: 'Cascadia Code', Consolas, 'Courier New', monospace;
         padding: 20px 28px; line-height: 1.6; background: #1e1e1e; color: #d4d4d4;
         font-size: 0.88em; }
  pre { white-space: pre-wrap; word-wrap: break-word; margin: 0; }
  .header { color: #888; margin-bottom: 14px; font-size: 0.9em;
            border-bottom: 1px solid #333; padding-bottom: 8px; }
</style>
</head>
<body>
<div class="header">${escapeHtml(label)} (Markdown) &nbsp;·&nbsp; ${escapeHtml(filename)}</div>
<pre>${escaped}</pre>
</body>
</html>`;
}

export function deactivate() {}
