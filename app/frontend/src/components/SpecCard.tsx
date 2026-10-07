import type { SpecView } from "../types";
import DataTable, { fromRecords } from "./DataTable";

interface Props {
  spec: SpecView;
  latestVersion?: number;
  /** Current status of this version from the workflow state (e.g. approved after the card was shown). */
  liveStatus?: string;
  busy: boolean;
  onApprove: (spec: SpecView) => void;
}

const STATUS_CLASS: Record<string, string> = {
  approved: "badge ok",
  draft: "badge warn",
  rejected: "badge err",
  superseded: "badge",
};

export default function SpecCard({ spec, latestVersion, liveStatus, busy, onApprove }: Props) {
  const status = liveStatus ?? spec.status;
  const errors = spec.issues.filter((i) => i.severity === "error");
  const warnings = spec.issues.filter((i) => i.severity === "warning");
  const outdated = latestVersion !== undefined && latestVersion > spec.version;
  const [cols, rows] = fromRecords(spec.mapping_table, ["target", "from", "transform", "confidence", "rationale"]);

  let blocker = "";
  if (status !== "draft") blocker = `Spec is ${status}`;
  else if (outdated) blocker = `Superseded by v${latestVersion}`;
  else if (errors.length) blocker = `Fix ${errors.length} error(s) first`;

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <strong>
            {spec.domain} mapping spec <code>{spec.spec_id}</code> v{spec.version}
          </strong>{" "}
          <span className={outdated ? "badge" : (STATUS_CLASS[status] ?? "badge")}>{outdated ? `superseded by v${latestVersion}` : status}</span>
          <div className="muted small">
            <code>{spec.source_table}</code> → <code>{spec.target_table}</code>
          </div>
        </div>
        {status === "draft" && !outdated && (
          <button
            className="primary"
            disabled={busy || !!blocker}
            title={blocker || "Approve this exact version; you are recorded as the approver"}
            onClick={() => onApprove(spec)}
          >
            Approve v{spec.version}
          </button>
        )}
      </div>
      {blocker && status === "draft" && !outdated && <div className="muted small">{blocker}</div>}

      <DataTable
        columns={cols}
        rows={rows}
        highlight={(r) => (r[3] === "low" ? "row-low" : undefined)}
      />

      {spec.unpivot && (
        <div className="small">
          <strong>Unpivot:</strong> {spec.unpivot.tests.map((t) => `${t.source_column} → ${t.testcd}`).join(", ")}
        </div>
      )}
      {spec.filter && (
        <div className="small">
          <strong>Filter:</strong> <code>{spec.filter}</code>
        </div>
      )}
      {spec.notes && <div className="note">{spec.notes}</div>}

      {spec.issues.length > 0 && (
        <details open={errors.length > 0}>
          <summary>
            Spec checks: <span className={errors.length ? "text-err" : ""}>{errors.length} errors</span>,{" "}
            {warnings.length} warnings
          </summary>
          <DataTable
            columns={["severity", "variable", "rule", "message"]}
            rows={spec.issues.map((i) => [i.severity, i.variable, i.rule, i.message])}
            highlight={(r) => (r[0] === "error" ? "row-err" : undefined)}
          />
        </details>
      )}
    </div>
  );
}
