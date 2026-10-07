import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { getMe, sendChat } from "./api";
import AgentSteps from "./components/AgentSteps";
import Sidebar from "./components/Sidebar";
import ToolResults from "./components/ToolResults";
import type { SpecView, Turn, Workflow } from "./types";

const STORAGE_KEY = "sdtm-agent-session";

interface Session {
  studyId: string;
  turns: Turn[];
  workflow: Workflow;
}

function loadSession(): Session {
  try {
    const saved = sessionStorage.getItem(STORAGE_KEY);
    if (saved) return JSON.parse(saved) as Session;
  } catch {
    /* storage unavailable */
  }
  return { studyId: "", turns: [], workflow: {} };
}

export default function App() {
  const [session, setSession] = useState<Session>(loadSession);
  const [me, setMe] = useState({ user: "", endpoint: "" });
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const { studyId, turns, workflow } = session;

  useEffect(() => {
    getMe().then(setMe).catch(() => setMe({ user: "unknown", endpoint: "unavailable" }));
  }, []);

  useEffect(() => {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    } catch {
      /* storage unavailable */
    }
  }, [session]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns.length, busy]);

  async function send(text: string, approveSpecIds: string[] = []) {
    if (!text.trim() || busy || !studyId) return;
    const history: Turn[] = [...turns, { role: "user", content: text }];
    setSession((s) => ({ ...s, turns: history }));
    setInput("");
    setBusy(true);
    try {
      const resp = await sendChat({
        messages: history.filter((t) => !t.error).map((t) => ({ role: t.role, content: t.content })),
        study_id: studyId,
        workflow,
        approve_spec_ids: approveSpecIds,
      });
      const answer =
        [...resp.messages].reverse().find((m) => m.role === "assistant" && m.content)?.content ??
        "_The agent returned no answer._";
      setSession((s) => ({
        ...s,
        workflow: resp.workflow ?? s.workflow,
        turns: [...history, { role: "assistant", content: answer, steps: resp.messages }],
      }));
    } catch (err) {
      setSession((s) => ({
        ...s,
        turns: [...history, { role: "assistant", content: `⚠️ ${(err as Error).message}`, error: true }],
      }));
    } finally {
      setBusy(false);
    }
  }

  function approve(spec: SpecView) {
    send(`I approve ${spec.domain} mapping spec ${spec.spec_id} version ${spec.version}.`, [
      `${spec.spec_id}:${spec.version}`,
    ]);
  }

  return (
    <div className="layout">
      <Sidebar
        user={me.user}
        endpoint={me.endpoint}
        studyId={studyId}
        onStudyChange={(id) => setSession((s) => ({ ...s, studyId: id }))}
        workflow={workflow}
        busy={busy}
        onExample={(t) => send(t)}
        onReset={() => setSession((s) => ({ ...s, turns: [], workflow: {} }))}
      />
      <main className="chat">
        <header>
          <h1>SDTM Mapping Assistant</h1>
          {!studyId && <div className="note">Enter a study ID in the sidebar to start.</div>}
        </header>
        <div className="messages">
          {turns.map((t, i) => (
            <div key={i} className={`msg ${t.role}${t.error ? " error" : ""}`}>
              {t.steps && (
                <ToolResults steps={t.steps} workflow={workflow} busy={busy} onApprove={approve} />
              )}
              <div className="bubble">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{t.content}</ReactMarkdown>
              </div>
              {t.steps && <AgentSteps steps={t.steps} />}
            </div>
          ))}
          {busy && (
            <div className="msg assistant">
              <div className="bubble thinking">Working…</div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
        >
          <textarea
            value={input}
            placeholder={studyId ? "Ask the SDTM mapping agent…" : "Enter a study ID first"}
            disabled={!studyId || busy}
            rows={2}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(input);
              }
            }}
          />
          <button className="primary" type="submit" disabled={!studyId || busy || !input.trim()}>
            Send
          </button>
        </form>
      </main>
    </div>
  );
}
