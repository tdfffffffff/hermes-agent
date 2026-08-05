"""
title: Hermes HTML Dashboard
id: hermes_html_dashboard
description: Detects /opt/outputs/*.html paths in Hermes skill responses and renders the dashboard as an HTML artifact — mirrors the VS Code extension's dual-panel behaviour for Guardian, Legacy, Compliance Mapper, Tabletop, and Feedback Digest.
author: Hermes Platform
version: 1.0.0
"""

import re
import httpx
from typing import Callable, Awaitable, Optional
from pydantic import BaseModel, Field


class Filter:
    class Valves(BaseModel):
        wrapper_url: str = Field(
            default="http://hermes-wrapper:5000",
            description="Hermes wrapper base URL (internal Docker hermes-net address)",
        )
        wrapper_api_key: str = Field(
            default=os.environ.get("WRAPPER_API_KEY", ""),
            description="Hermes wrapper WRAPPER_API_KEY value",
        )
        enabled: bool = Field(
            default=True,
            description="Enable HTML dashboard rendering for all Hermes skills",
        )

    def __init__(self):
        self.valves = self.Valves()

    async def outlet(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __event_emitter__: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> dict:
        if not self.valves.enabled:
            return body

        messages = body.get("messages", [])
        if not messages:
            return body

        last = messages[-1]
        if last.get("role") != "assistant":
            return body

        content = last.get("content", "")
        if not content:
            return body

        # Same regex as VS Code extension showBestReport()
        # Take the LAST match — input report paths appear first, the skill's own
        # output path is always printed last by execute_code.
        html_paths = re.findall(r"/opt/outputs/([^\s)]+\.html)", content)
        if not html_paths:
            return body

        filename = html_paths[-1]

        # Auth: admin key + X-OpenWebUI-User-Name header, same as OpenWebUI→wrapper flow
        username = (__user__ or {}).get("name", "")
        headers = {
            "Authorization": f"Bearer {self.valves.wrapper_api_key}",
            "X-OpenWebUI-User-Name": username,
        }

        # Fetch the HTML file from the wrapper /outputs/ endpoint
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self.valves.wrapper_url}/outputs/{filename}",
                    headers=headers,
                )
            if resp.status_code != 200:
                return body
            html_content = resp.text
        except Exception:
            return body

        # Strip Google Fonts — VS Code extension does the same (webview blocks external requests)
        html_content = re.sub(
            r"<link[^>]*fonts\.googleapis\.com[^>]*>",
            "",
            html_content,
            flags=re.IGNORECASE,
        )

        artifact = f"\n\n```html\n{html_content}\n```"

        # Primary: event emitter appends to the live message stream
        if __event_emitter__:
            try:
                await __event_emitter__(
                    {"type": "message", "data": {"content": artifact}}
                )
            except Exception:
                pass

        # Guaranteed fallback: modify body so the artifact is stored and displayed
        # even if the event emitter path is unavailable in this OpenWebUI version
        last["content"] = content + artifact

        return body
