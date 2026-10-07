"""Transform job: materializes an approved mapping spec as a Silver SDTM table and validates it.

Triggered by the agent's execute_transform tool (Jobs API run_now). Arguments come
from the job parameters defined in databricks.yml.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

try:
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
except NameError:  # __file__ is not always defined on Databricks
    _ROOT = os.path.dirname(os.getcwd())
sys.path.insert(0, _ROOT)

from pyspark.sql import SparkSession  # noqa: E402

from sdtm_agent.config import load_config  # noqa: E402
from sdtm_agent.spec_store import SpecStore  # noqa: E402
from sdtm_agent.sql import SparkRunner  # noqa: E402
from sdtm_agent.transform import run_pyspark  # noqa: E402
from sdtm_agent.validation import validate_dataset  # noqa: E402


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec-id", required=True)
    parser.add_argument("--spec-version", default="")
    parser.add_argument("--target-table", required=True)
    parser.add_argument("--source-table", default="")
    parser.add_argument("--requested-by", default="unknown")
    parser.add_argument("--run-id", default="manual")
    parser.add_argument("--metadata-schema", required=True)
    args = parser.parse_args(argv)

    spark = SparkSession.builder.getOrCreate()
    runner = SparkRunner(spark)
    store = SpecStore(runner, load_config({"metadata_schema": args.metadata_schema}))

    spec = store.get(args.spec_id, int(args.spec_version) if args.spec_version else None)
    if spec is None:
        raise SystemExit(f"Spec {args.spec_id} v{args.spec_version or 'latest'} not found")
    if spec.status != "approved":
        raise SystemExit(f"Spec {spec.spec_id} v{spec.version} is '{spec.status}', not approved")
    if args.source_table:
        spec.source_table = args.source_table

    print(f"Running spec {spec.spec_id} v{spec.version} ({spec.domain}) for {args.requested_by}")
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {args.target_table.rsplit('.', 1)[0]}")
    if spec.dm_table and not spark.catalog.tableExists(spec.dm_table):
        print(f"DM table {spec.dm_table} not found; --DY variables will be null. Map DM first.")
        spec.dm_table = None
    result = run_pyspark(spark, spec, args.target_table)

    dm_table = spec.dm_table if spec.domain != "DM" else None
    report = validate_dataset(runner, args.target_table, spec.domain, dm_table=dm_table)
    store.save_validation(args.run_id, spec, report)

    summary = {**result, "passed": report["passed"], "errors": report["error_count"], "warnings": report["warning_count"]}
    print(json.dumps(summary, indent=2, default=str))
    return summary


if __name__ == "__main__":
    main()
