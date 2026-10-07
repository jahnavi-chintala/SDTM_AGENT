import type { Workflow } from "../types";

const EXAMPLES = [
  "List the source tables for study {study}",
  "Map the demographics table of study {study} to DM",
  "Propose the AE mapping for study {study} from table ae_raw",
  "Show the mapping specs for study {study}",
];

const STAGE_LABEL: Record<string, string> = {
  start: "Getting started",
  source_selected: "Source selected",
  draft_review: "Reviewing draft",
  approved: "Approved — ready to run",
  running: "Transform running",
  executed: "Executed — check validation",
};

interface Props {
  user: string;
  endpoint: string;
  studyId: string;
  onStudyChange: (id: string) => void;
  workflow: Workflow;
  busy: boolean;
  onExample: (text: string) => void;
  onReset: () => void;
}

export default function Sidebar({ user, endpoint, studyId, onStudyChange, workflow, busy, onExample, onReset }: Props) {
  const specs = Object.entries(workflow.specs ?? {});
  return (
    <aside className="sidebar">
      <h2>SDTM Mapping Agent</h2>
      <label className="field">
        <span>Study ID</span>
        <input value={studyId} placeholder="e.g. ABC123" onChange={(e) => onStudyChange(e.target.value.trim())} />
      </label>
      <div className="muted small">
        Signed in as {user || "…"}
        <br />
        Endpoint <code>{endpoint || "…"}</code>
      </div>
      <button onClick={onReset} disabled={busy}>
        New conversation
      </button>

      {workflow.stage && (
        <section>
          <h3>Workflow</h3>
          <div className="small">{STAGE_LABEL[workflow.stage] ?? workflow.stage}</div>
          {workflow.source_table && (
            <div className="muted small">
              Source <code>{workflow.source_table}</code>
            </div>
          )}
        </section>
      )}

      {specs.length > 0 && (
        <section>
          <h3>Specs in this session</h3>
          <ul className="spec-list">
            {specs.map(([id, s]) => (
              <li key={id}>
                <span className={s.status === "approved" ? "dot ok" : s.status === "draft" ? "dot warn" : "dot"} />
                <strong>{s.domain}</strong> <code>{id}</code> v{s.version} · {s.status}
                {s.validation_passed != null && (
                  <span className={s.validation_passed ? "text-ok" : "text-err"}>
                    {" "}
                    · validation {s.validation_passed ? "passed" : "failed"}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h3>Try asking</h3>
        {EXAMPLES.map((e) => {
          const text = e.replace("{study}", studyId || "<study>");
          return (
            <button key={e} className="example" disabled={!studyId || busy} onClick={() => onExample(text)}>
              {text}
            </button>
          );
        })}
      </section>
      <p className="muted small">
        Mappings are derived from the SDTM IG only and stay drafts until you approve them. Nothing is written to
        Silver tables before approval.
      </p>
    </aside>
  );
}
