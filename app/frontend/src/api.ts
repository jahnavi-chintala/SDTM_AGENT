import type { AgentMessage, Workflow } from "./types";

export interface ChatResponse {
  messages: AgentMessage[];
  workflow: Workflow;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, init);
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const body = await resp.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return resp.json() as Promise<T>;
}

export function getMe(): Promise<{ user: string; endpoint: string }> {
  return request("/api/me");
}

export function sendChat(body: {
  messages: { role: string; content: string }[];
  study_id: string;
  workflow: Workflow;
  approve_spec_ids: string[];
}): Promise<ChatResponse> {
  return request("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
