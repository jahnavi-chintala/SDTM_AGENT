import type { RunResult, ValidationReport } from "../types";
import DataTable from "./DataTable";

export function ValidationView({ report }: { report: ValidationReport }) {
  return (
    <div className="card">
      <div className="card-head">
        <strong>
          Validation of <code>{report.table ?? report.table_name}</code>
        </strong>
        <span className={report.passed ? "badge ok" : "badge err"}>
          {report.passed ? "passed" : `${report.error_count} errors`}
        </span>
      </div>
      <div className="muted small">
        {report.record_count} records · {report.warning_count} warnings
      </div>
      {report.findings.length > 0 && (
        <DataTable
          columns={["severity", "rule", "variable", "message", "count", "examples"]}
          rows={report.findings.map((f) => [f.severity, f.rule, f.variable, f.message, f.count, f.examples.join(", ")])}
          highlight={(r) => (r[0] === "error" ? "row-err" : undefined)}
        />
      )}
    </div>
  );
}

export function RunView({ run }: { run: RunResult }) {
  const state = run.result_state ?? run.life_cycle_state ?? "UNKNOWN";
  const cls = state === "SUCCESS" ? "badge ok" : ["FAILED", "INTERNAL_ERROR", "TIMEDOUT", "CANCELED"].includes(state) ? "badge err" : "badge warn";
  return (
    <>
      <div className="card">
        <div className="card-head">
          <strong>
            Transform run{" "}
            {run.run_page_url ? (
              <a href={run.run_page_url} target="_blank" rel="noreferrer">
                {run.run_id}
              </a>
            ) : (
              run.run_id
            )}
          </strong>
          <span className={cls}>{state}</span>
        </div>
        {run.target_table && (
          <div className="muted small">
            Output: <code>{run.target_table}</code>
          </div>
        )}
      </div>
      {run.validation && <ValidationView report={run.validation} />}
    </>
  );
}
