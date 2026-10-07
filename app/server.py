"""Backend for the SDTM Mapping Agent chat UI (Databricks App).

Serves the built React frontend (static/) and exposes a small API that
forwards chat turns to the agent's Model Serving endpoint. Credentials stay
server-side: the app's service principal (default) or the signed-in user's
token (SDTM_APP_AUTH=user) calls the endpoint. The user's identity always
comes from the Databricks Apps SSO headers, never from the browser.
"""

import os
import re
from pathlib import Path
from typing import Any

import requests
from databricks.sdk import WorkspaceClient
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

SERVING_ENDPOINT = os.environ.get("SERVING_ENDPOINT", "sdtm-mapping-agent")
AUTH_MODE = os.environ.get("SDTM_APP_AUTH", "service_principal")
TIMEOUT_SECONDS = 300
STATIC_DIR = Path(__file__).parent / "static"
_APPROVAL_TOKEN = re.compile(r"^[A-Za-z0-9]{1,64}:\d{1,6}$")

app = FastAPI(title="SDTM Mapping Agent UI")
_workspace: WorkspaceClient | None = None


def workspace() -> WorkspaceClient:
    global _workspace
    if _workspace is None:
        _workspace = WorkspaceClient()
    return _workspace


class ChatMessage(BaseModel):
    role: str
    content: str = ""


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    study_id: str | None = None
    workflow: dict[str, Any] = Field(default_factory=dict)
    approve_spec_ids: list[str] = Field(default_factory=list)


def current_user(request: Request) -> str:
    h = request.headers
    return h.get("x-forwarded-email") or h.get("x-forwarded-preferred-username") or "local-user"


def endpoint_headers(request: Request) -> dict[str, str]:
    user_token = request.headers.get("x-forwarded-access-token")
    if AUTH_MODE == "user" and user_token:
        return {"Authorization": f"Bearer {user_token}"}
    return workspace().config.authenticate()


def build_payload(req: ChatRequest, user: str) -> dict[str, Any]:
    """Agent request: only user/assistant text from the browser, plus server-set identity."""
    bad = [t for t in req.approve_spec_ids if not _APPROVAL_TOKEN.match(t)]
    if bad:
        raise HTTPException(status_code=400, detail=f"Invalid approval token(s): {bad}")
    messages = [
        {"role": m.role, "content": m.content}
        for m in req.messages
        if m.role in ("user", "assistant") and m.content
    ]
    if not messages or messages[-1]["role"] != "user":
        raise HTTPException(status_code=400, detail="The last message must be from the user")
    if req.study_id:
        messages.insert(0, {"role": "system", "content": f"The user is working on study {req.study_id}."})
    return {
        "messages": messages,
        "custom_inputs": {"user": user, "approve_spec_ids": req.approve_spec_ids, "workflow": req.workflow},
    }


@app.get("/api/me")
def me(request: Request) -> dict[str, str]:
    return {"user": current_user(request), "endpoint": SERVING_ENDPOINT}


@app.post("/api/chat")
def chat(req: ChatRequest, request: Request) -> dict[str, Any]:
    payload = build_payload(req, current_user(request))
    host = workspace().config.host.rstrip("/")
    try:
        resp = requests.post(
            f"{host}/serving-endpoints/{SERVING_ENDPOINT}/invocations",
            headers={**endpoint_headers(request), "Content-Type": "application/json"},
            json=payload,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Agent endpoint unreachable: {exc}") from exc
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Agent endpoint returned {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    return {
        "messages": data.get("messages", []),
        "workflow": (data.get("custom_outputs") or {}).get("workflow", req.workflow),
    }


if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("DATABRICKS_APP_PORT", "8000")))
