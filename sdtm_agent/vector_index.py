"""Builds and syncs the Vector Search index over the SDTM IG corpus.

Run from notebooks/00_setup.py (initial setup) and from the scheduled
`refresh_sdtm_index` job (feedback loop: newly approved mapping specs become
retrievable examples).
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

from sdtm_agent.config import AgentConfig
from sdtm_agent.ig_corpus import approved_spec_chunks, document_chunks, knowledge_chunks

log = logging.getLogger(__name__)

CHUNK_COLUMNS = ["id", "domain", "chunk_type", "variable", "title", "content", "source"]


def read_ig_documents(volume_path: str) -> list[dict]:
    """Chunk licensed SDTM IG documents (PDF, TXT, MD, HTML) found under a UC volume path."""
    if not volume_path or not os.path.isdir(volume_path):
        return []
    chunks = []
    for root, _, files in os.walk(volume_path):
        for name in sorted(files):
            path = os.path.join(root, name)
            ext = name.lower().rsplit(".", 1)[-1]
            if ext == "pdf":
                from pypdf import PdfReader

                text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
            elif ext in ("txt", "md"):
                with open(path, encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            elif ext in ("html", "htm"):
                with open(path, encoding="utf-8", errors="ignore") as f:
                    text = re.sub(r"<[^>]+>", " ", f.read())
            else:
                continue
            doc_chunks = document_chunks(text, source=name)
            log.info("%s: %d chunks", name, len(doc_chunks))
            chunks.extend(doc_chunks)
    return chunks


def build_corpus_table(spark: Any, config: AgentConfig, ig_volume_path: str | None = None) -> int:
    """(Re)write the chunk table that the Delta Sync index reads from."""
    chunks = knowledge_chunks() + read_ig_documents(ig_volume_path or "")
    if spark.catalog.tableExists(config.mapping_specs_table):
        approved = spark.sql(
            f"SELECT spec_json FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY spec_id ORDER BY version DESC) rn "
            f"FROM {config.mapping_specs_table}) WHERE rn = 1 AND status = 'approved'"
        ).collect()
        chunks += approved_spec_chunks([{"spec_json": r.spec_json} for r in approved])

    table = f"{config.metadata_schema}.sdtm_ig_chunks"
    spark.sql(
        f"CREATE TABLE IF NOT EXISTS {table} (id STRING, domain STRING, chunk_type STRING, variable STRING, "
        f"title STRING, content STRING, source STRING) USING DELTA TBLPROPERTIES (delta.enableChangeDataFeed = true)"
    )
    rows = [tuple(c.get(k) for k in CHUNK_COLUMNS) for c in {c["id"]: c for c in chunks}.values()]
    df = spark.createDataFrame(rows, schema=", ".join(f"{c} STRING" for c in CHUNK_COLUMNS))
    df.createOrReplaceTempView("new_chunks")
    # MERGE keeps unchanged rows untouched so the index only re-embeds what changed.
    spark.sql(
        f"""MERGE INTO {table} t USING new_chunks s ON t.id = s.id
        WHEN NOT MATCHED THEN INSERT *
        WHEN NOT MATCHED BY SOURCE THEN DELETE"""
    )
    return len(rows)


def ensure_index(config: AgentConfig, endpoint_name: str, embedding_endpoint: str = "databricks-gte-large-en") -> None:
    """Create the Vector Search endpoint and Delta Sync index if needed, then trigger a sync."""
    from databricks.vector_search.client import VectorSearchClient

    vsc = VectorSearchClient(disable_notice=True)
    if endpoint_name not in [e["name"] for e in vsc.list_endpoints().get("endpoints", [])]:
        log.info("Creating vector search endpoint %s", endpoint_name)
        vsc.create_endpoint_and_wait(name=endpoint_name, endpoint_type="STANDARD")

    source_table = f"{config.metadata_schema}.sdtm_ig_chunks"
    try:
        index = vsc.get_index(endpoint_name=endpoint_name, index_name=config.vector_search_index)
    except Exception:
        log.info("Creating index %s", config.vector_search_index)
        index = vsc.create_delta_sync_index(
            endpoint_name=endpoint_name,
            index_name=config.vector_search_index,
            source_table_name=source_table,
            pipeline_type="TRIGGERED",
            primary_key="id",
            embedding_source_column="content",
            embedding_model_endpoint_name=embedding_endpoint,
        )
    for _ in range(60):  # a new index must be online before it can be synced
        status = index.describe().get("status", {})
        if status.get("ready"):
            break
        time.sleep(30)
    index.sync()
