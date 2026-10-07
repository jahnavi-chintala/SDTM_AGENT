import type { AgentMessage } from "../types";

function pretty(text: string): string {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

/** Collapsible trace of tool calls and raw results for one assistant turn. */
export default function AgentSteps({ steps }: { steps: AgentMessage[] }) {
  const toolCount = steps.filter((s) => s.role === "tool").length;
  if (!toolCount) return null;
  return (
    <details className="steps">
      <summary>Agent steps ({toolCount} tool calls)</summary>
      {steps.map((s, i) => (
        <div key={i}>
          {s.tool_calls?.map((tc) => (
            <div key={tc.id} className="step">
              <div className="step-title">→ {tc.function.name}</div>
              <pre>{pretty(tc.function.arguments || "{}")}</pre>
            </div>
          ))}
          {s.role === "tool" && (
            <div className="step">
              <div className="step-title">← {s.name}</div>
              <pre className="result">{pretty(s.content)}</pre>
            </div>
          )}
        </div>
      ))}
    </details>
  );
}
