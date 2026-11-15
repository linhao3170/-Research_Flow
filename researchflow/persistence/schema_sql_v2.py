"""Forward-only schema migration 0002 (T0 WP-04 … WP-12 storage).

``06_DATA_AND_API.md`` §1.3 defines ``graph_versions``, ``reports``,
``certificates`` and ``ingestion_log``.  WP-03 deliberately shipped only the
seven tables it needed, so this migration adds the remaining frozen tables
without touching the 0001 statements or their checksum (an existing database
must keep migrating cleanly).

Recorded deviations from the 06 §1.3 DDL (see
``docs/verification/t0/wp-04/00_decisions.md``):

* ``graph_versions.graph_json`` snapshots the validated ``NodeSpec`` list so
  the DAG view can be rebuilt without inventing columns on ``nodes``.
* ``reports`` stores the coverage triple, structured gaps and the exact signed
  report document.  The frozen ``VerificationReport`` contract requires
  ``required_check_coverage`` and ``GET /report`` must return gaps, but
  06 §1.3 lists no column for either.
* ``certificates`` follows 06 §1.3 column-for-column.

No contract field is added or renamed; only storage for fields the frozen
contracts already require.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "GRAPH_VERSION_TABLE_VERSION",
    "MIGRATION_V2_STATEMENTS",
    "REPORT_FINAL_STATES",
    "STATUS_VALUES",
]

GRAPH_VERSION_TABLE_VERSION: Final[str] = "0002_t0_evidence_loop"

REPORT_FINAL_STATES: Final[tuple[str, ...]] = ("VERIFIED", "PARTIAL", "FAILED", "BLOCKED")
STATUS_VALUES: Final[tuple[str, ...]] = ("PASS", "FAIL", "SKIP", "NOT_RUN")


def _in(values: tuple[str, ...]) -> str:
    return "(" + ",".join("'" + value + "'" for value in values) + ")"


MIGRATION_V2_STATEMENTS: Final[tuple[str, ...]] = (
    # ---------------------------------------------------------- graph_versions
    """
CREATE TABLE IF NOT EXISTS graph_versions (
  task_id           TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
  graph_version     INTEGER NOT NULL CHECK (graph_version >= 1),
  graph_hash        TEXT NOT NULL CHECK (length(graph_hash) = 64),
  topology_order    TEXT NOT NULL CHECK (json_valid(topology_order)),
  graph_json        TEXT NOT NULL CHECK (json_valid(graph_json)),
  created_at        TEXT NOT NULL,
  PRIMARY KEY (task_id, graph_version)
);
""".strip(),
    """
CREATE TRIGGER IF NOT EXISTS trg_graph_versions_no_update
BEFORE UPDATE ON graph_versions
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: graph_versions'); END;
""".strip(),
    """
CREATE TRIGGER IF NOT EXISTS trg_graph_versions_no_delete
BEFORE DELETE ON graph_versions
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: graph_versions'); END;
""".strip(),
    # ---------------------------------------------------------------- reports
    f"""
CREATE TABLE IF NOT EXISTS reports (
  report_id          TEXT PRIMARY KEY,
  schema_version     TEXT NOT NULL,
  task_id            TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
  final_state        TEXT NOT NULL CHECK (final_state IN {_in(REPORT_FINAL_STATES)}),
  l1_status          TEXT NOT NULL CHECK (l1_status IN {_in(STATUS_VALUES)}),
  l2_status          TEXT NOT NULL CHECK (l2_status IN {_in(STATUS_VALUES)}),
  l3_status          TEXT NOT NULL CHECK (l3_status IN {_in(STATUS_VALUES)}),
  coverage_required  INTEGER NOT NULL CHECK (coverage_required >= 0),
  coverage_passed    INTEGER NOT NULL CHECK (coverage_passed >= 0),
  coverage_missing   INTEGER NOT NULL CHECK (coverage_missing >= 0),
  gaps_json          TEXT NOT NULL CHECK (json_valid(gaps_json)),
  ruleset_hash       TEXT NOT NULL CHECK (length(ruleset_hash) = 64),
  evidence_root      TEXT NOT NULL CHECK (length(evidence_root) = 64),
  l3_coverage        REAL NOT NULL CHECK (l3_coverage >= 0.0 AND l3_coverage <= 1.0),
  issued_at          TEXT NOT NULL,
  key_id             TEXT NOT NULL,
  signature          TEXT NOT NULL,
  report_json        TEXT NOT NULL CHECK (json_valid(report_json)),
  UNIQUE (task_id, report_id),
  CHECK (coverage_passed <= coverage_required),
  CHECK (coverage_missing = coverage_required - coverage_passed),
  CHECK (final_state <> 'VERIFIED' OR coverage_missing = 0)
);
""".strip(),
    """
CREATE TRIGGER IF NOT EXISTS trg_reports_no_update
BEFORE UPDATE ON reports
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: reports'); END;
""".strip(),
    """
CREATE TRIGGER IF NOT EXISTS trg_reports_no_delete
BEFORE DELETE ON reports
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: reports'); END;
""".strip(),
    # ----------------------------------------------------------- certificates
    """
CREATE TABLE IF NOT EXISTS certificates (
  cert_id            TEXT PRIMARY KEY,
  schema_version     TEXT NOT NULL,
  report_id          TEXT NOT NULL REFERENCES reports(report_id) ON DELETE RESTRICT,
  final_state        TEXT NOT NULL CHECK (final_state = 'VERIFIED'),
  merkle_root        TEXT NOT NULL CHECK (length(merkle_root) = 64),
  tree_size          INTEGER NOT NULL CHECK (tree_size >= 1),
  ruleset_hash       TEXT NOT NULL CHECK (length(ruleset_hash) = 64),
  code_hash          TEXT NOT NULL CHECK (length(code_hash) = 64),
  env_fingerprint    TEXT NOT NULL CHECK (length(env_fingerprint) = 64),
  l3_coverage        REAL NOT NULL CHECK (l3_coverage >= 0.0 AND l3_coverage <= 1.0),
  skipped_nodes      TEXT NOT NULL CHECK (json_valid(skipped_nodes)),
  alg                TEXT NOT NULL CHECK (alg = 'Ed25519'),
  key_id             TEXT NOT NULL,
  key_fingerprint    TEXT NOT NULL CHECK (length(key_fingerprint) = 64),
  signature          TEXT NOT NULL,
  issued_at          TEXT NOT NULL,
  UNIQUE (report_id)
);
""".strip(),
    """
CREATE TRIGGER IF NOT EXISTS trg_certificates_no_update
BEFORE UPDATE ON certificates
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: certificates'); END;
""".strip(),
    """
CREATE TRIGGER IF NOT EXISTS trg_certificates_no_delete
BEFORE DELETE ON certificates
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: certificates'); END;
""".strip(),
    # ---------------------------------------------------------- ingestion_log
    """
CREATE TABLE IF NOT EXISTS ingestion_log (
  ingestion_id       TEXT PRIMARY KEY,
  evidence_id        TEXT NOT NULL,
  delivery_seq       INTEGER NOT NULL CHECK (delivery_seq >= 1),
  received_at        TEXT NOT NULL,
  UNIQUE (evidence_id, delivery_seq)
);
""".strip(),
    """
CREATE TRIGGER IF NOT EXISTS trg_ingestion_log_no_update
BEFORE UPDATE ON ingestion_log
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: ingestion_log'); END;
""".strip(),
    """
CREATE TRIGGER IF NOT EXISTS trg_ingestion_log_no_delete
BEFORE DELETE ON ingestion_log
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: ingestion_log'); END;
""".strip(),
    # ---------------------------------------------------------------- indexes
    "CREATE INDEX IF NOT EXISTS idx_reports_task ON reports(task_id);",
    "CREATE INDEX IF NOT EXISTS idx_ingestion_evidence ON ingestion_log(evidence_id);",
    "CREATE INDEX IF NOT EXISTS idx_graph_versions_task ON graph_versions(task_id);",
)