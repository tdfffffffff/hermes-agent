"""
Hermes Wrapper — OpenAI-compatible streaming gateway for OpenWebUI → Hermes Agent.

Routes /v1/chat/completions to the correct Hermes container via docker exec.

Auth modes (evaluated in order):
  1. Per-user API key  — Bearer sk-hermes-<hex>  → key resolves to a username,
                         container routed from key (X-OpenWebUI-User-Name ignored).
  2. Shared admin key  — Bearer <WRAPPER_API_KEY> → username from
                         X-OpenWebUI-User-Name header (existing OpenWebUI behaviour).

Per-user keys are stored in USER_KEYS_FILE and written to each user's profile dir
on provisioning so admins can retrieve them: /data/hermes/profiles/<user>/.api-key

Auto-provisioning: if a user's container does not exist, it is created
automatically on first request — no manual intervention required.

Security controls:
  - Per-user API key authentication (new) with shared admin key fallback
  - Rate limiting (20 req/min per IP)
  - Input sanitisation (strip control chars, length cap)
  - Username sanitisation (alphanumeric/hyphen/underscore only)
  - Container prefix enforcement (only hermes-* containers can be exec'd)
  - Container existence check before exec
  - ANSI escape code stripping on output
  - Atomic key file writes (tmp + os.replace) to prevent corruption
  - Docker socket access is intentional — documented trade-off (see README)
"""

import asyncio
import json
import os
import re
import shutil
import threading
import time
import uuid

import docker
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# ── Config ────────────────────────────────────────────────────────────

WRAPPER_API_KEY  = os.environ["WRAPPER_API_KEY"]
LITELLM_KEY      = os.environ["LITELLM_KEY"]
MAX_INPUT_LEN    = 32_000
CONTAINER_PREFIX = "hermes-"
DATA_ROOT        = "/data"
USER_KEYS_FILE   = f"{DATA_ROOT}/hermes/api-keys.json"

TEMPLATE_PROFILE = f"{DATA_ROOT}/hermes/profiles/engineer-a/config.yaml"
TEMPLATE_STATE   = f"{DATA_ROOT}/hermes/state/engineer-a/config.yaml"
TEMPLATE_SKILLS  = f"{DATA_ROOT}/hermes/skills-template"

# ── App setup ─────────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address, default_limits=["20/minute"])
app = FastAPI(title="Hermes Wrapper", docs_url=None, redoc_url=None)
app.state.limiter = limiter

docker_client = docker.from_env()

_keys_lock = threading.Lock()


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"error": "Rate limit exceeded"})


# ── Security helpers ──────────────────────────────────────────────────

def sanitize_input(text: str) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text[:MAX_INPUT_LEN]


def sanitize_username(username: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "", username)[:64].replace("_", "-")


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b(?:[@-Z\\-_]|\[[0-9;]*[ -/]*[@-~])", "", text)


# ── Per-user API key management ───────────────────────────────────────

def _read_keys_file() -> dict:
    """Read the keys file without locking — callers that need atomicity must hold _keys_lock."""
    if os.path.exists(USER_KEYS_FILE):
        with open(USER_KEYS_FILE) as f:
            return json.load(f)
    return {}


def _write_keys_file(keys: dict) -> None:
    """Atomically write the keys file. Caller must hold _keys_lock."""
    os.makedirs(os.path.dirname(USER_KEYS_FILE), exist_ok=True)
    tmp = USER_KEYS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(keys, f, indent=2)
    os.replace(tmp, USER_KEYS_FILE)


def get_username_for_key(api_key: str) -> str | None:
    """Return the username bound to api_key, or None if not found."""
    return _read_keys_file().get(api_key)


def add_user_key(username: str) -> str:
    """
    Atomically generate a fresh key for username (revoking any prior key)
    and persist it. Returns the new key.
    """
    with _keys_lock:
        keys = _read_keys_file()
        keys = {k: v for k, v in keys.items() if v != username}
        new_key = f"sk-hermes-{uuid.uuid4().hex}"
        keys[new_key] = username
        _write_keys_file(keys)
    return new_key


def revoke_user_key(username: str) -> bool:
    """Remove all keys belonging to username. Returns True if any were removed."""
    with _keys_lock:
        keys = _read_keys_file()
        new_keys = {k: v for k, v in keys.items() if v != username}
        if len(new_keys) == len(keys):
            return False
        _write_keys_file(new_keys)
    return True


def resolve_auth(authorization: str | None, username_header: str) -> tuple[str, bool]:
    """
    Validate the Bearer token and return (username, used_admin_key).

    Per-user key  → (bound_username, False) — routing ignores the header.
    Shared admin key → (header_username,  True) — routing uses the header.
    Invalid       → raises HTTP 401.
    """
    token = ""
    if authorization:
        token = authorization.removeprefix("Bearer ").strip()

    if not token:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    # Per-user key takes priority
    if token != WRAPPER_API_KEY:
        username = get_username_for_key(token)
        if username:
            return username, False
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Shared admin key — fall back to header-based routing
    safe = sanitize_username(username_header)
    if not safe:
        raise HTTPException(
            status_code=401,
            detail="Shared key requires X-OpenWebUI-User-Name header"
        )
    return safe, True


# ── Auto-provisioning ─────────────────────────────────────────────────

def provision_user(username: str, container_name: str) -> str:
    """
    Provision a new Hermes container for a first-time user.
    Generates a per-user API key, writes it to the user's profile dir,
    creates host directories, copies template configs, starts the container.
    Blocks until running (max 30s). Returns the generated API key.
    Raises RuntimeError on failure.
    """
    profile_dir  = f"{DATA_ROOT}/hermes/profiles/{username}"
    state_dir    = f"{DATA_ROOT}/hermes/state/{username}"
    logs_dir     = f"{DATA_ROOT}/logs/{username}"
    outputs_dir  = f"{DATA_ROOT}/outputs/{username}"
    datasets_dir = f"{DATA_ROOT}/datasets"

    for d in [profile_dir, state_dir, logs_dir, outputs_dir, datasets_dir]:
        os.makedirs(d, exist_ok=True)

    shutil.copy2(TEMPLATE_PROFILE, f"{profile_dir}/config.yaml")
    shutil.copy2(TEMPLATE_STATE,   f"{state_dir}/config.yaml")

    # Seed base skills from template; only if user has no skills dir yet (preserves isolation)
    _skills_dst = f"{state_dir}/skills"
    if os.path.isdir(TEMPLATE_SKILLS) and not os.path.exists(_skills_dst):
        shutil.copytree(TEMPLATE_SKILLS, _skills_dst)

    for root_dir, dirs, files in os.walk(state_dir):
        try:
            os.chown(root_dir, 10000, 10000)
        except FileNotFoundError:
            pass
        for f in files:
            try:
                os.chown(os.path.join(root_dir, f), 10000, 10000)
            except FileNotFoundError:
                pass

    # Generate and persist per-user key
    user_key = add_user_key(username)
    key_file = f"{profile_dir}/.api-key"
    with open(key_file, "w") as f:
        f.write(user_key + "\n")
    os.chmod(key_file, 0o600)
    print(f"[provision] API key for '{username}': {user_key}", flush=True)

    docker_client.containers.run(
        image="nousresearch/hermes-agent:latest",
        name=container_name,
        detach=True,
        network="hermes-net",
        stdin_open=True,
        tty=True,
        environment={
            "HERMES_DASHBOARD":          "true",
            "HERMES_DASHBOARD_HOST":     "0.0.0.0",
            "HERMES_DASHBOARD_PORT":     "9119",
            "HERMES_DASHBOARD_INSECURE": "true",
            "OPENAI_API_KEY":            LITELLM_KEY,
            "OPENAI_API_BASE":           "http://hermes-litellm-proxy:4000",
        },
        volumes={
            profile_dir:  {"bind": "/root/.hermes", "mode": "rw"},
            state_dir:    {"bind": "/opt/data",      "mode": "rw"},
            datasets_dir: {"bind": "/opt/datasets",  "mode": "ro"},
            outputs_dir:  {"bind": "/opt/outputs",   "mode": "rw"},
        },
        security_opt=["no-new-privileges:true"],
        cap_drop=["ALL"],
        cap_add=["SETGID", "SETUID", "DAC_OVERRIDE"],
        read_only=True,
        tmpfs={"/tmp": "size=512m", "/run": "size=64m,exec"},
        mem_limit="4g",
        restart_policy={"Name": "unless-stopped"},
    )

    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            c = docker_client.containers.get(container_name)
            if c.status == "running":
                time.sleep(8)
                return user_key
        except docker.errors.NotFound:
            pass
        time.sleep(1)

    raise RuntimeError(f"Container {container_name} did not reach running state within 30s")


# ── Welcome stream (first-login provisioning) ────────────────────────

async def _welcome_stream(model: str, api_key: str):
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    msg = (
        "Your Hermes container has been provisioned.\n\n"
        f"Your personal API key is:\n\n`{api_key}`\n\n"
        "Save this key, then update it in your OpenWebUI connection settings "
        "(Settings → Connections → API Key). Once updated, resend your message."
    )
    chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [{"index": 0, "delta": {"content": msg}, "finish_reason": None}],
    }
    yield f"data: {json.dumps(chunk)}\n\n"
    stop_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(stop_chunk)}\n\n"
    yield "data: [DONE]\n\n"


# ── Core streaming logic ──────────────────────────────────────────────

async def stream_hermes(model: str, container_name: str, user_message: str):
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def _run_in_thread():
        try:
            container = docker_client.containers.get(container_name)
            _, stream = container.exec_run(
                cmd=[
                    "sh", "-c",
                    ". /opt/hermes/.venv/bin/activate && "
                    "hermes -z \"$HERMES_MSG\" --continue"
                ],
                environment={"HERMES_MSG": user_message},
                stream=True,
                demux=False,
            )
            for raw_chunk in stream:
                if raw_chunk:
                    text = strip_ansi(raw_chunk.decode("utf-8", errors="replace"))
                    if text.strip():
                        asyncio.run_coroutine_threadsafe(queue.put(text), loop)
        except docker.errors.NotFound:
            asyncio.run_coroutine_threadsafe(
                queue.put(f"[Error: container '{container_name}' not found]"), loop
            )
        except Exception as e:
            asyncio.run_coroutine_threadsafe(queue.put(f"[Error: {e}]"), loop)
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(None), loop)

    loop.run_in_executor(None, _run_in_thread)

    while True:
        text = await queue.get()
        if text is None:
            break
        chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "model": model,
            "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
        }
        yield f"data: {json.dumps(chunk)}\n\n"

    stop_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(stop_chunk)}\n\n"
    yield "data: [DONE]\n\n"


# ── Endpoints ─────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/outputs/{filename}")
async def serve_output(
    filename: str,
    authorization: str = Header(None),
    x_openwebui_user_name: str = Header(None, alias="X-OpenWebUI-User-Name"),
    token: str = Query(None),
):
    if token and not authorization:
        authorization = f"Bearer {token}"
    username, _ = resolve_auth(authorization, x_openwebui_user_name or "")
    safe_user = sanitize_username(username)
    if not safe_user:
        raise HTTPException(status_code=403, detail="Invalid username")
    safe_name = os.path.basename(filename)
    if not safe_name or ".." in safe_name:
        raise HTTPException(status_code=400, detail="Invalid filename")
    file_path = os.path.join(DATA_ROOT, "outputs", safe_user, safe_name)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Not found")
    suffix = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
    media = {"html": "text/html", "md": "text/markdown", "json": "application/json"}.get(
        suffix, "application/octet-stream"
    )
    return FileResponse(file_path, media_type=media)



WEBUI_DATA_DIR  = "/data/webui-data"
WEBUI_DB_PATH   = f"{WEBUI_DATA_DIR}/webui.db"
WEBUI_UPLOADS   = f"{WEBUI_DATA_DIR}/uploads"

@app.get("/v1/uploads")
async def get_upload(
    filename: str = Query(...),
    authorization: str = Header(None),
    x_openwebui_user_name: str = Header(None, alias="X-OpenWebUI-User-Name"),
):
    username, _ = resolve_auth(authorization, x_openwebui_user_name or "")
    safe_user = sanitize_username(username)
    if not safe_user:
        raise HTTPException(status_code=403, detail="Invalid username")

    owui_username = safe_user.replace("-", "_")
    safe_fname = os.path.basename(filename)
    if not safe_fname or ".." in safe_fname:
        raise HTTPException(status_code=400, detail="Invalid filename")

    try:
        import sqlite3, base64 as b64, mimetypes
        conn = sqlite3.connect(f"file:{WEBUI_DB_PATH}?mode=ro", uri=True, timeout=5)
        cur  = conn.cursor()
        # try exact match, then hyphen→underscore, then hyphen→space
        row = None
        for candidate in [safe_user, safe_user.replace("-", "_"), safe_user.replace("-", " ")]:
            cur.execute("SELECT id FROM user WHERE name = ?", (candidate,))
            row = cur.fetchone()
            if row:
                break
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail=f"User '{owui_username}' not found in OpenWebUI")
        user_id = row[0]
        cur.execute("SELECT id FROM file WHERE user_id = ? AND filename = ?", (user_id, safe_fname))
        file_row = cur.fetchone()
        conn.close()
        if not file_row:
            raise HTTPException(status_code=404, detail=f"No upload '{safe_fname}' found for this user")
        file_path = os.path.join(WEBUI_UPLOADS, f"{file_row[0]}_{safe_fname}")
        if not os.path.isfile(file_path):
            raise HTTPException(status_code=404, detail="File not on disk")
        with open(file_path, "rb") as fh:
            data = b64.b64encode(fh.read()).decode()
        EXTRA_TYPES = {
            ".docx":  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xlsx":  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".pptx":  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".doc":   "application/msword",
            ".xls":   "application/vnd.ms-excel",
            ".ppt":   "application/vnd.ms-powerpoint",
        }
        ext = os.path.splitext(safe_fname)[1].lower()
        mime, _ = mimetypes.guess_type(safe_fname)
        mime = mime or EXTRA_TYPES.get(ext, "application/octet-stream")
        return {"filename": safe_fname, "data": data, "mime_type": mime}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/keys/me")
async def get_my_key(
    authorization: str = Header(None),
    x_openwebui_user_name: str = Header(None, alias="X-OpenWebUI-User-Name"),
):
    """Return the caller's own per-user API key — used by the OpenWebUI function to build isolated links."""
    username, _ = resolve_auth(authorization, x_openwebui_user_name or "")
    safe = sanitize_username(username)
    keys = _read_keys_file()
    my_key = next((k for k, v in keys.items() if v == safe), None)
    if not my_key:
        raise HTTPException(status_code=404, detail="No API key for this user")
    return {"username": safe, "key": my_key}


@app.post("/v1/admin/provision/{username}")
async def admin_provision_user(username: str, authorization: str = Header(None)):
    """Admin-triggered pre-provisioning. Used by the auto-provisioner to set up containers before the user sends their first message."""
    _require_admin(authorization)
    safe = sanitize_username(username)
    if not safe:
        raise HTTPException(status_code=400, detail="Invalid username")
    container_name = f"{CONTAINER_PREFIX}{safe}"
    try:
        docker_client.containers.get(container_name)
        keys = _read_keys_file()
        existing_key = next((k for k, v in keys.items() if v == safe), None)
        return {"status": "already_provisioned", "username": safe, "api_key": existing_key}
    except docker.errors.NotFound:
        loop = asyncio.get_event_loop()
        user_key = await loop.run_in_executor(None, provision_user, safe, container_name)
        return {"status": "provisioned", "username": safe, "api_key": user_key}


@app.get("/v1/models")
async def list_models(authorization: str = Header(None)):
    return {
        "object": "list",
        "data": [
            {"id": "hermes-agent", "object": "model", "owned_by": "hermes"}
        ],
    }


@app.post("/v1/chat/completions")
@limiter.limit("20/minute")
async def chat_completions(
    request: Request,
    body: dict,
    authorization: str = Header(None),
):
    model    = body.get("model", "hermes-agent")
    messages = body.get("messages", [])

    # ── Authenticate and resolve username ─────────────────────────────
    username_header = request.headers.get("x-openwebui-user-name", "")
    username, used_admin_key = resolve_auth(authorization, username_header)
    safe = sanitize_username(username)
    if not safe:
        raise HTTPException(status_code=403, detail="Invalid username")

    container_name = f"{CONTAINER_PREFIX}{safe}"
    if not container_name.startswith(CONTAINER_PREFIX):
        raise HTTPException(status_code=403, detail="Forbidden container target")

    # ── Container lookup / auto-provision ─────────────────────────────
    try:
        docker_client.containers.get(container_name)
    except docker.errors.NotFound:
        print(f"[wrapper] Auto-provisioning: {username} → {container_name}", flush=True)
        loop = asyncio.get_event_loop()
        try:
            user_key = await loop.run_in_executor(
                None, provision_user, safe, container_name
            )
            print(f"[wrapper] Provisioning complete: {container_name}", flush=True)
            print(f"[wrapper] User key written to /data/hermes/profiles/{safe}/.api-key", flush=True)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Provisioning failed: {e}")
        return StreamingResponse(
            _welcome_stream(model, user_key),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── Extract and sanitise message ──────────────────────────────────
    # For multi-turn conversations, build a full transcript so Hermes retains
    # context across turns (e.g. adversarial interview, iterative analysis).
    turns = [m for m in messages if m.get("role") in ("user", "assistant")]
    if len(turns) > 1:
        parts = []
        for m in messages:
            role    = m.get("role", "")
            content = sanitize_input(m.get("content") or "")
            if role == "user":
                parts.append(f"Engineer: {content}")
            elif role == "assistant":
                parts.append(f"Hermes: {content}")
        user_message = "\n\n".join(parts) if parts else None
    else:
        user_message = next(
            (sanitize_input(m["content"])
             for m in reversed(messages)
             if m.get("role") == "user"),
            None,
        )
    if not user_message:
        raise HTTPException(status_code=400, detail="No user message provided")

    auth_mode = "admin-key" if used_admin_key else "user-key"
    print(f"[wrapper] {auth_mode} | {username} → {container_name} | model={model}", flush=True)

    return StreamingResponse(
        stream_hermes(model, container_name, user_message),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Admin key management endpoints ───────────────────────────────────
# All require the shared WRAPPER_API_KEY.

def _require_admin(authorization: str | None) -> None:
    token = ""
    if authorization:
        token = authorization.removeprefix("Bearer ").strip()
    if token != WRAPPER_API_KEY:
        raise HTTPException(status_code=403, detail="Admin key required")


@app.get("/v1/keys")
async def list_keys(authorization: str = Header(None)):
    """List all username → key pairs. Admin only."""
    _require_admin(authorization)
    keys = _read_keys_file()
    # Return username → key (inverted for readability)
    by_user = {v: k for k, v in keys.items()}
    return {"users": by_user, "count": len(by_user)}


@app.post("/v1/keys/{username}")
async def generate_key(username: str, authorization: str = Header(None)):
    """Generate (or regenerate) a per-user API key. Admin only."""
    _require_admin(authorization)
    safe = sanitize_username(username)
    if not safe:
        raise HTTPException(status_code=400, detail="Invalid username")
    new_key = add_user_key(safe)
    # Write to profile dir if it exists
    key_file = f"{DATA_ROOT}/hermes/profiles/{safe}/.api-key"
    if os.path.isdir(f"{DATA_ROOT}/hermes/profiles/{safe}"):
        with open(key_file, "w") as f:
            f.write(new_key + "\n")
        os.chmod(key_file, 0o600)
    print(f"[keys] Generated key for '{safe}': {new_key}", flush=True)
    return {"username": safe, "api_key": new_key}


@app.delete("/v1/keys/{username}")
async def delete_key(username: str, authorization: str = Header(None)):
    """Revoke a user's API key. Admin only."""
    _require_admin(authorization)
    safe = sanitize_username(username)
    removed = revoke_user_key(safe)
    if not removed:
        raise HTTPException(status_code=404, detail=f"No key found for '{safe}'")
    print(f"[keys] Revoked key for '{safe}'", flush=True)
    return {"username": safe, "revoked": True}
