"""Forward-only schema migration 0003: extend the audit action vocabulary.

``0001_initial`` froze ``audit_log.action`` to a ``CHECK`` list sized for WP-03.
The T0 loop needs to audit evidence appends (``06_DATA_AND_API.md`` §2 lists
``audit_log`` in the evidence-append transaction), verification runs, report and
certificate issuance, and bundle exports.  SQLite cannot alter a ``CHECK``
constraint, so the standard rebuild procedure is used:

1. create ``audit_log__v3`` with the extended ``CHECK``;
2. copy every existing row unchanged (append-only history is preserved);
3. drop the old table (its append-only triggers drop with it);
4. rename the new table to ``audit_log``;
5. recreate the indexes and the append-only triggers from ``0001``.

No column is added, removed, renamed or retyped.  Migration ``0001`` and its
checksum stay untouched.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "AUDIT_ACTION_TABLE_VERSION",
    "AUDIT_ACTIONS_V3",
    "MIGRATION_V3_STATEMENTS",
]

AUDIT_ACTION_TABLE_VERSION: Final[str] = "0003_audit_actions"

# ``0001`` actions plus the T0 loop actions.  Keep old values untouched.
AUDIT_ACTIONS_V3: Final[tuple[str, ...]] = (
    "STATE_TRANSITION",
    "TASK_CREATED",
    "NODE_PLANNED",
    "NODE_INVALIDATED",
    "RECOVERY_PLAN_FROZEN",
    "RECOVERY_PLAN_REUSE",
    "TOOL_REQUEST",
    "SIGN",
    "ENV_FINGERPRINT_CHECK",
    "STARTUP_GUARD",
    "AUDIT_WRITE_FAILED",
    "EVIDENCE_APPENDED",
    "VERIFY_RUN",
    "REPORT_ISSUED",
    "CERTIFICATE_ISSUED",
    "BUNDLE_EXPORTED",
)


def _in(values: tuple[str, ...]) -> str:
    return "(" + ",".join("'" + value + "'" for value in values) + ")"


MIGRATION_V3_STATEMENTS: Final[tuple[str, ...]] = (
    # Dependent triggers reference audit_log; SQLite refuses to drop the table
    # while they exist.  All four state/field guard triggers are dropped so they
    # can be recreated in the exact 0001 order (SQLite fires triggers LIFO, and
    # the WP-03 negative tests rely on that order).
    "DROP TRIGGER IF EXISTS trg_tasks_state_requires_audit;",
    "DROP TRIGGER IF EXISTS trg_nodes_state_requires_audit;",
    "DROP TRIGGER IF EXISTS trg_tasks_graph_version_requires_state_change;",
    "DROP TRIGGER IF EXISTS trg_nodes_nonstate_requires_state_change;",
    f"""
CREATE TABLE audit_log__v3 (
  audit_id          TEXT PRIMARY KEY,
  task_id           TEXT,
  node_id           TEXT,
  actor             TEXT NOT NULL CHECK (length(actor) > 0 AND instr(actor, ':') > 0),
  action            TEXT NOT NULL CHECK (action IN {_in(AUDIT_ACTIONS_V3)}),
  previous_state    TEXT,
  next_state        TEXT,
  reason_code       TEXT,
  rule_version      TEXT,
  correlation_id    TEXT,
  plan_id           TEXT,
  plan_hash         TEXT,
  result            TEXT NOT NULL CHECK (result IN ('OK','DENIED')),
  error_code        TEXT,
  created_at        TEXT NOT NULL,
  CHECK (action <> 'STATE_TRANSITION'
      OR (previous_state IS NOT NULL AND next_state IS NOT NULL)),
  CHECK ((plan_id IS NULL AND plan_hash IS NULL)
      OR (plan_id IS NOT NULL AND plan_hash IS NOT NULL))
);
""".strip(),
    """
INSERT INTO audit_log__v3(audit_id, task_id, node_id, actor, action, previous_state,
  next_state, reason_code, rule_version, correlation_id, plan_id, plan_hash,
  result, error_code, created_at)
SELECT audit_id, task_id, node_id, actor, action, previous_state, next_state,
  reason_code, rule_version, correlation_id, plan_id, plan_hash,
  result, error_code, created_at
FROM audit_log;
""".strip(),
    "DROP TABLE audit_log;",
    "ALTER TABLE audit_log__v3 RENAME TO audit_log;",
    "CREATE INDEX IF NOT EXISTS idx_audit_task_time ON audit_log(task_id, created_at);",
    "CREATE INDEX IF NOT EXISTS idx_audit_plan ON audit_log(plan_hash);",
    "CREATE INDEX IF NOT EXISTS idx_audit_result "
    "ON audit_log(task_id, result, created_at);",
    """
CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_update
BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: audit_log'); END;
""".strip(),
    """
CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_delete
BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: audit_log'); END;
""".strip(),
    # Recreate the state triggers dropped above (identical to 0001).
    """
CREATE TRIGGER IF NOT EXISTS trg_tasks_state_requires_audit
BEFORE UPDATE OF state, graph_version ON tasks
FOR EACH ROW
WHEN NOT EXISTS (
  SELECT 1 FROM audit_log
  WHERE task_id = NEW.task_id
    AND action = 'STATE_TRANSITION'
    AND result = 'OK'
    AND previous_state = OLD.state
    AND next_state = NEW.state
    AND created_at = NEW.updated_at
)
BEGIN SELECT RAISE(ABORT, 'STATE_WRITE_WITHOUT_AUDIT: tasks'); END;
""".strip(),
    """
CREATE TRIGGER IF NOT EXISTS trg_nodes_state_requires_audit
BEFORE UPDATE OF state, attempt_seq, plan_id, plan_hash ON nodes
FOR EACH ROW
WHEN NOT EXISTS (
  SELECT 1 FROM audit_log
  WHERE task_id = NEW.task_id
    AND node_id = NEW.node_id
    AND action = 'STATE_TRANSITION'
    AND result = 'OK'
    AND previous_state = OLD.state
    AND next_state = NEW.state
    AND created_at = NEW.updated_at
)
BEGIN SELECT RAISE(ABORT, 'STATE_WRITE_WITHOUT_AUDIT: nodes'); END;
""".strip(),
    # Recreated in 0001 order after the state triggers above.
    """
CREATE TRIGGER IF NOT EXISTS trg_tasks_graph_version_requires_state_change
BEFORE UPDATE OF graph_version ON tasks
WHEN OLD.state = NEW.state AND OLD.graph_version IS NOT NEW.graph_version
BEGIN SELECT RAISE(ABORT, 'GRAPH_VERSION_CHANGE_WITHOUT_STATE_TRANSITION'); END;
""".strip(),
    """
CREATE TRIGGER IF NOT EXISTS trg_nodes_nonstate_requires_state_change
BEFORE UPDATE OF attempt_seq, plan_id, plan_hash ON nodes
WHEN OLD.state = NEW.state
 AND (OLD.attempt_seq IS NOT NEW.attempt_seq
      OR OLD.plan_id IS NOT NEW.plan_id
      OR OLD.plan_hash IS NOT NEW.plan_hash)
BEGIN SELECT RAISE(ABORT, 'NODE_FIELD_CHANGE_WITHOUT_STATE_TRANSITION'); END;
""".strip(),
)