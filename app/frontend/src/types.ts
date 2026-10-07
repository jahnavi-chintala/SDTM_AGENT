export interface ToolCall {
  id: string;
  type: "function";
  function: { name: string; arguments: string };
}

/** Message as returned by the agent's ChatAgent endpoint. */
export interface AgentMessage {
  id?: string;
  role: "assistant" | "tool" | "user" | "system";
  content: string;
  tool_calls?: ToolCall[];
  tool_call_id?: string;
  name?: string;
}

export interface Turn {
  role: "user" | "assistant";
  content: string;
  steps?: AgentMessage[];
  error?: boolean;
}

export interface SpecSummary {
  domain?: string;
  version?: number;
  status?: string;
  errors?: number;
  target_table?: string;
  run_id?: number;
  run_state?: string;
  validation_passed?: boolean | null;
}

export interface Workflow {
  stage?: string;
  study_id?: string | null;
  source_table?: string | null;
  active_spec_id?: string | null;
  specs?: Record<string, SpecSummary>;
}

export interface Issue {
  severity: "error" | "warning" | "info";
  rule: string;
  variable: string | null;
  message: string;
}

export interface MappingRow {
  target: string;
  from: string;
  transform: string;
  confidence: string | null;
  rationale: string | null;
}

export interface SpecView {
  spec_id: string;
  version: number;
  status: string;
  study_id: string;
  domain: string;
  source_table: string;
  target_table: string;
  filter: string | null;
  unpivot: { tests: { source_column: string; testcd: string }[] } | null;
  notes: string | null;
  mapping_table: MappingRow[];
  issues: Issue[];
}

export interface Finding {
  rule: string;
  severity: "error" | "warning" | "info";
  variable: string | null;
  message: string;
  count: number | null;
  examples: unknown[];
}

export interface ValidationReport {
  table?: string;
  table_name?: string;
  passed: boolean;
  error_count: number;
  warning_count: number;
  record_count: number;
  findings: Finding[];
}

export interface PreviewResult {
  spec_id: string;
  version: number;
  columns: string[];
  rows: unknown[][];
  sql: string;
}

export interface RunResult {
  run_id: number;
  run_page_url?: string;
  life_cycle_state?: string;
  result_state?: string | null;
  target_table?: string;
  validation?: ValidationReport | null;
}
