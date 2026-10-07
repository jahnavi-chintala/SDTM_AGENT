interface Props {
  columns: string[];
  rows: unknown[][];
  maxRows?: number;
  highlight?: (row: unknown[]) => string | undefined;
}

function cell(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function DataTable({ columns, rows, maxRows = 200, highlight }: Props) {
  const shown = rows.slice(0, maxRows);
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((row, i) => (
            <tr key={i} className={highlight?.(row)}>
              {row.map((v, j) => (
                <td key={j} className={v === null || v === undefined ? "null" : undefined}>
                  {v === null || v === undefined ? "null" : cell(v)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > maxRows && <div className="muted small">Showing {maxRows} of {rows.length} rows</div>}
    </div>
  );
}

/** Columns + rows from a list of objects, keeping the given column order. */
export function fromRecords<T extends object>(records: T[], columns: (keyof T & string)[]): [string[], unknown[][]] {
  return [columns, records.map((r) => columns.map((c) => r[c]))];
}
