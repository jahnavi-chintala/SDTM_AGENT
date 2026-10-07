import type { AgentMessage, PreviewResult, RunResult, SpecView, ValidationReport, Workflow } from "../types";
import DataTable from "./DataTable";
import SpecCard from "./SpecCard";
import { RunView, ValidationView } from "./ValidationView";

const SPEC_TOOLS = new Set(["generate_mapping", "update_mapping", "get_mapping"]);

export function parseToolResults(steps: AgentMessage[]): { name: string; result: Record<string, unknown> }[] {
  return steps
    .filter((s) => s.role === "tool")
    .map((s) => {
      try {
        return { name: s.name ?? "", result: JSON.parse(s.content || "{}") };
      } catch {
        return { name: s.name ?? "", result: { raw: s.content } };
      }
    });
}

interface Props {
  steps: AgentMessage[];
  workflow: Workflow;
  busy: boolean;
  onApprove: (spec: SpecView) => void;
}

/** Rich rendering of the tool results in one assistant turn. */
export default function ToolResults({ steps, workflow, busy, onApprove }: Props) {
  return (
    <>
      {parseToolResults(steps).map(({ name, result }, i) => {
        if ("error" in result) return null;
        if (SPEC_TOOLS.has(name) && result.spec_id) {
          const spec = result as unknown as SpecView;
          const live = workflow.specs?.[spec.spec_id];
          return (
            <SpecCard
              key={i}
              spec={spec}
              latestVersion={live?.version}
              liveStatus={live?.version === spec.version ? live.status : undefined}
              busy={busy}
              onApprove={onApprove}
            />
          );
        }
        if (name === "preview_transform" && result.columns) {
          const p = result as unknown as PreviewResult;
          return (
            <div className="card" key={i}>
              <strong>
                Preview of spec <code>{p.spec_id}</code> v{p.version}
              </strong>
              <DataTable columns={p.columns} rows={p.rows} />
              <details>
                <summary>SQL</summary>
                <pre>{p.sql}</pre>
              </details>
            </div>
          );
        }
        if (name === "validate_output" && "findings" in result) {
          return <ValidationView key={i} report={result as unknown as ValidationReport} />;
        }
        if ((name === "execute_transform" || name === "get_transform_status") && result.run_id) {
          return <RunView key={i} run={result as unknown as RunResult} />;
        }
        return null;
      })}
    </>
  );
}
