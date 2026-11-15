"""WP-03 minimal SQLite schema.

Seven tables are created: ``tasks``, ``nodes``, ``evidence``,
``evidence_invalidations``, ``audit_log``, ``idempotency_keys`` and
``schema_migrations``.  Column definitions follow ``06_DATA_AND_API.md`` §1.3
with two approved WP-03 additions:

* ``tasks.task_spec_json`` — preserves the existing GET ``spec`` payload;
* ``idempotency_keys.task_id`` is ``NOT NULL`` with a foreign key to tasks
  (user-approved §12-7 tightening).

Triggers are defence-in-depth, not a security boundary.  They catch direct SQL
state writes that bypass ``StateMachine``.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "AUDIT_ACTIONS",
    "AUDIT_RESULTS",
    "DDL_STATEMENTS",
    "EVIDENCE_KINDS",
    "EVIDENCE_LEVELS",
    "INITIAL_SCHEMA_VERSION",
    "INVALIDATION_CAUSES",
    "NODE_STATES",
    "SCHEMA_MIGRATIONS_DDL",
    "TASK_STATES",
    "assert_schema_contract",
    "ddl_text",
]

INITIAL_SCHEMA_VERSION: Final[str] = "0001_initial"

TASK_STATES: Final[tuple[str, ...]] = (
    "CREATED",
    "PLANNING",
    "READY",
    "RUNNING",
    "VERIFYING",
    "COMPLETED",
    "FAILED",
    "BLOCKED",
    "CANCELLED",
)

NODE_STATES: Final[tuple[str, ...]] = (
    "PLANNED",
    "READY",
    "RUNNING",
    "VERIFYING",
    "VERIFIED",
    "INVALIDATED",
    "FAILED",
    "BLOCKED",
    "DIAGNOSING",
    "RECOVERING",
)

EVIDENCE_LEVELS: Final[tuple[str, ...]] = ("E0", "E1", "E2", "E3")

EVIDENCE_KINDS: Final[tuple[str, ...]] = (
    "agent_claim",
    "tool_invocation",
    "harness_trace",
    "executor_launch",
    "executor_process_exit",
    "artifact_observed",
    "verifier_recheck",
)

INVALIDATION_CAUSES: Final[tuple[str, ...]] = (
    "INPUT_CHANGE",
    "PREDECESSOR_CHANGE",
    "GRAPH_VERSION_CHANGE",
    "RULESET_CHANGE",
)

AUDIT_RESULTS: Final[tuple[str, ...]] = ("OK", "DENIED")

AUDIT_ACTIONS: Final[tuple[str, ...]] = (
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
)

SCHEMA_MIGRATIONS_DDL: Final[str] = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version           TEXT PRIMARY KEY,
  applied_at        TEXT NOT NULL,
  checksum          TEXT NOT NULL
);
""".strip()


def _in(values: tuple[str, ...]) -> str:
    return "(" + ",".join("'" + value + "'" for value in values) + ")"


DDL_STATEMENTS: Final[tuple[str, ...]] = (
    # ---------------------------------------------------------------- tasks
    f"""
CREATE TABLE IF NOT EXISTS tasks (
  task_id           TEXT PRIMARY KEY,
  schema_version    TEXT NOT NULL,
  domain_pack       TEXT NOT NULL,
  goal              TEXT NOT NULL,
  task_spec_hash    TEXT NOT NULL,
  task_spec_json    TEXT NOT NULL,
  state             TEXT NOT NULL CHECK (state IN {_in(TASK_STATES)}),
  graph_version     INTEGER,
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL,
  CHECK (graph_version IS NULL OR graph_version >= 1)
);
""".strip(),
    # ---------------------------------------------------------------- nodes
    f"""
CREATE TABLE IF NOT EXISTS nodes (
  task_id           TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
  node_id           TEXT NOT NULL,
  schema_version    TEXT NOT NULL,
  node_type         TEXT NOT NULL,
  template_id       TEXT NOT NULL,
  state             TEXT NOT NULL CHECK (state IN {_in(NODE_STATES)}),
  attempt_seq       INTEGER NOT NULL DEFAULT 0 CHECK (attempt_seq >= 0),
  plan_id           TEXT,
  plan_hash         TEXT,
  updated_at        TEXT NOT NULL,
  PRIMARY KEY (task_id, node_id),
  CHECK ((plan_id IS NULL AND plan_hash IS NULL)
      OR (plan_id IS NOT NULL AND plan_hash IS NOT NULL))
);
""".strip(),
    # ------------------------------------------------------------- evidence
    f"""
CREATE TABLE IF NOT EXISTS evidence (
  evidence_id       TEXT PRIMARY KEY,
  task_id           TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
  node_id           TEXT NOT NULL,
  attempt_id        TEXT NOT NULL,
  event_seq         INTEGER NOT NULL CHECK (event_seq >= 1),
  level             TEXT NOT NULL CHECK (level IN {_in(EVIDENCE_LEVELS)}),
  kind              TEXT NOT NULL CHECK (kind IN {_in(EVIDENCE_KINDS)}),
  producer          TEXT NOT NULL,
  timestamp         TEXT NOT NULL,
  payload_hash      TEXT NOT NULL,
  artifact_refs     TEXT,
  prev_hash         TEXT NOT NULL,
  chain_hash        TEXT NOT NULL,
  UNIQUE (task_id, event_seq),
  FOREIGN KEY (task_id, node_id) REFERENCES nodes(task_id, node_id)
    ON DELETE RESTRICT,
  CHECK (
    (level IN ('E0','E1','E2') AND producer = 'collector')
    OR (level = 'E3' AND producer = 'verifier')
  ),
  CHECK (artifact_refs IS NULL
      OR (json_valid(artifact_refs) AND json_type(artifact_refs) = 'array'))
);
""".strip(),
    # -------------------------------------------------- evidence_invalidations
    f"""
CREATE TABLE IF NOT EXISTS evidence_invalidations (
  invalidation_id   TEXT PRIMARY KEY,
  task_id           TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
  node_id           TEXT NOT NULL,
  evidence_id       TEXT NOT NULL REFERENCES evidence(evidence_id)
                      ON DELETE RESTRICT,
  reason_code       TEXT NOT NULL CHECK (length(reason_code) > 0),
  cause_type        TEXT NOT NULL CHECK (cause_type IN {_in(INVALIDATION_CAUSES)}),
  cause_ref         TEXT,
  plan_id           TEXT,
  plan_hash         TEXT,
  created_at        TEXT NOT NULL,
  CHECK ((plan_id IS NULL AND plan_hash IS NULL)
      OR (plan_id IS NOT NULL AND plan_hash IS NOT NULL))
);
""".strip(),
    # ------------------------------------------------------------- audit_log
    f"""
CREATE TABLE IF NOT EXISTS audit_log (
  audit_id          TEXT PRIMARY KEY,
  task_id           TEXT,
  node_id           TEXT,
  actor             TEXT NOT NULL CHECK (length(actor) > 0 AND instr(actor, ':') > 0),
  action            TEXT NOT NULL CHECK (action IN {_in(AUDIT_ACTIONS)}),
  previous_state    TEXT,
  next_state        TEXT,
  reason_code       TEXT,
  rule_version      TEXT,
  correlation_id    TEXT,
  plan_id           TEXT,
  plan_hash         TEXT,
  result            TEXT NOT NULL CHECK (result IN {_in(AUDIT_RESULTS)}),
  error_code        TEXT,
  created_at        TEXT NOT NULL,
  CHECK (action <> 'STATE_TRANSITION'
      OR (previous_state IS NOT NULL AND next_state IS NOT NULL)),
  CHECK ((plan_id IS NULL AND plan_hash IS NULL)
      OR (plan_id IS NOT NULL AND plan_hash IS NOT NULL))
);
""".strip(),
    # ------------------------------------------------------ idempotency_keys
    """
CREATE TABLE IF NOT EXISTS idempotency_keys (
  idem_key          TEXT PRIMARY KEY,
  request_hash      TEXT NOT NULL,
  task_id           TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
  created_at        TEXT NOT NULL
);
""".strip(),
    # ---------------------------------------------------------------- indexes
    "CREATE INDEX IF NOT EXISTS idx_nodes_state ON nodes(task_id, state);",
    "CREATE INDEX IF NOT EXISTS idx_evidence_task_seq ON evidence(task_id, event_seq);",
    "CREATE INDEX IF NOT EXISTS idx_audit_task_time ON audit_log(task_id, created_at);",
    "CREATE INDEX IF NOT EXISTS idx_invalidations_node "
    "ON evidence_invalidations(task_id, node_id);",
    "CREATE INDEX IF NOT EXISTS idx_invalidations_evidence "
    "ON evidence_invalidations(task_id, evidence_id);",
    "CREATE INDEX IF NOT EXISTS idx_audit_plan ON audit_log(plan_hash);",
    "CREATE INDEX IF NOT EXISTS idx_audit_result "
    "ON audit_log(task_id, result, created_at);",
    # ------------------------------------------------------- append-only
    """
CREATE TRIGGER IF NOT EXISTS trg_evidence_no_update
BEFORE UPDATE ON evidence
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: evidence'); END;
""".strip(),
    """
CREATE TRIGGER IF NOT EXISTS trg_evidence_no_delete
BEFORE DELETE ON evidence
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: evidence'); END;
""".strip(),
    """
CREATE TRIGGER IF NOT EXISTS trg_evidence_invalidations_no_update
BEFORE UPDATE ON evidence_invalidations
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: evidence_invalidations'); END;
""".strip(),
    """
CREATE TRIGGER IF NOT EXISTS trg_evidence_invalidations_no_delete
BEFORE DELETE ON evidence_invalidations
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: evidence_invalidations'); END;
""".strip(),
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
    """
CREATE TRIGGER IF NOT EXISTS trg_schema_migrations_no_update
BEFORE UPDATE ON schema_migrations
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: schema_migrations'); END;
""".strip(),
    """
CREATE TRIGGER IF NOT EXISTS trg_schema_migrations_no_delete
BEFORE DELETE ON schema_migrations
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: schema_migrations'); END;
""".strip(),
    """
CREATE TRIGGER IF NOT EXISTS trg_idempotency_keys_no_update
BEFORE UPDATE ON idempotency_keys
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: idempotency_keys'); END;
""".strip(),
    """
CREATE TRIGGER IF NOT EXISTS trg_idempotency_keys_no_delete
BEFORE DELETE ON idempotency_keys
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: idempotency_keys'); END;
""".strip(),
    # ------------------------------------------------- create initial state
    """
CREATE TRIGGER IF NOT EXISTS trg_tasks_insert_created
BEFORE INSERT ON tasks
WHEN NEW.state <> 'CREATED'
BEGIN SELECT RAISE(ABORT, 'TASK_MUST_BE_INSERTED_CREATED'); END;
""".strip(),
    """
CREATE TRIGGER IF NOT EXISTS trg_nodes_insert_planned
BEFORE INSERT ON nodes
WHEN NEW.state <> 'PLANNED'
BEGIN SELECT RAISE(ABORT, 'NODE_MUST_BE_INSERTED_PLANNED'); END;
""".strip(),
    # ------------------------------------- state updates require OK audit
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
    # --------------------------------- non-state changes require transition
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
    # ------------------------------------------- immutable / no delete
    """
CREATE TRIGGER IF NOT EXISTS trg_tasks_immutable_fields
BEFORE UPDATE OF task_id, schema_version, domain_pack, goal,
                 task_spec_hash, task_spec_json, created_at ON tasks
BEGIN SELECT RAISE(ABORT, 'TASK_IMMUTABLE_FIELD'); END;
""".strip(),
    """
CREATE TRIGGER IF NOT EXISTS trg_nodes_immutable_fields
BEFORE UPDATE OF task_id, node_id, schema_version, node_type, template_id ON nodes
BEGIN SELECT RAISE(ABORT, 'NODE_IMMUTABLE_FIELD'); END;
""".strip(),
    """
CREATE TRIGGER IF NOT EXISTS trg_tasks_no_delete
BEFORE DELETE ON tasks
BEGIN SELECT RAISE(ABORT, 'TASK_DELETE_FORBIDDEN'); END;
""".strip(),
    """
CREATE TRIGGER IF NOT EXISTS trg_nodes_no_delete
BEFORE DELETE ON nodes
BEGIN SELECT RAISE(ABORT, 'NODE_DELETE_FORBIDDEN'); END;
""".strip(),
)


def ddl_text() -> str:
    """Return the schema statements used for checksum and review."""

    return "\n".join(DDL_STATEMENTS)


def assert_schema_contract() -> list[str]:
    """Return a list of contract violations for the in-code schema."""

    problems: list[str] = []
    expected_tables = {
        "tasks",
        "nodes",
        "evidence",
        "evidence_invalidations",
        "audit_log",
        "idempotency_keys",
        "schema_migrations",
    }
    full_ddl = SCHEMA_MIGRATIONS_DDL + "\n" + ddl_text()
    missing_tables = sorted(
        table
        for table in expected_tables
        if f"CREATE TABLE IF NOT EXISTS {table}" not in full_ddl
    )
    if missing_tables:
        problems.append(f"missing tables: {missing_tables}")
    if len(TASK_STATES) != 9:
        problems.append(f"TASK_STATES should have 9 values, got {len(TASK_STATES)}")
    if len(NODE_STATES) != 10:
        problems.append(f"NODE_STATES should have 10 values, got {len(NODE_STATES)}")
    forbidden_recovery = {
        "PROPOSED",
        "APPROVED",
        "EXECUTING",
        "RECHECKED",
        "CLOSED",
        "ESCALATED",
    }
    if forbidden_recovery & set(TASK_STATES + NODE_STATES):
        problems.append("T1 Recovery state leaked into T0")
    if "STATE_TRANSITION" not in AUDIT_ACTIONS:
        problems.append("AUDIT_ACTIONS must include STATE_TRANSITION")
    if "TASK_CREATED" not in AUDIT_ACTIONS or "NODE_PLANNED" not in AUDIT_ACTIONS:
        problems.append("creation audit actions missing")
    return problems