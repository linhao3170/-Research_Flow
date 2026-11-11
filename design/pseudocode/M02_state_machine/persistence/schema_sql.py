"""M02 · persistence/schema_sql.py — SQLite 表结构、约束、索引与写入者（P2 伪代码）。

阶段：P2「持久层与状态机」｜状态：DDL 与写入者声明，**不执行建库、不连接数据库**。
规范来源：
  - `docs/design/06_DATA_AND_API.md` §1.2/§1.3/§2/§3/§5（G0 冻结 v1.0，表结构均为【工程建议】）；
  - `docs/design/05_CONTRACTS_AND_STATES.md` §9/§10/§13；
  - `docs/ADR/ADR-001`（INVALIDATED）、`ADR-004`（T0 恢复边界）、`ADR-005`（失败迁移审计）；
  - `design/pseudocode/00_BASELINE/ENCODING_RULES.md`、`M01_contracts/contracts/errors.py`。

本文件只做三件事：
  1. 把 06 §1.3 的基线 DDL 落成**可检查的列级规格**（类型 / 可空 / 约束 / 索引 / 写者）；
  2. 补 M02 必需的 CHECK 与触发器：只追加表禁止 UPDATE/DELETE；任务/节点状态更新必须带
     同事务的 `audit_log(result=OK)` 记录（防旁路写，触发器不是安全边界）；
  3. 给出“只由谁写”的矩阵与自检函数。

**本文件不新增契约字段、不建 `recovery_plans` 表、不建 reports/certificates 表。**
后两者属 Verifier；恢复计划属内容寻址文件（ADR-004），DB 只存 `nodes.plan_id`/`plan_hash`。

关于 Evidence 状态（05 §9.4）的边界，见本文件 §EVIDENCE_STATE_NOTE：
`evidence` 表是**只追加的元数据表**，06 §1.3 没有 `state` 列。M02 不擅自加列：
`RECEIVED` / `VALIDATED` 是 Collector 摄入流水线状态，`APPENDED` 以“行存在”表示，
`INVALID` / `CONFLICT` 在写入前被拒绝、不落 `evidence` 表。若 WP-07 需要持久化摄入状态，
必须先补 ADR + 迁移，不能在本阶段顺手加列。
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping

__all__ = [
    "APPEND_ONLY_TABLES",
    "AUDIT_ACTIONS",
    "AUDIT_RESULTS",
    "BOOTSTRAP_STATEMENTS",
    "COLUMN_INDEXES",
    "COLUMN_INDEX_MAP",
    "DDL_STATEMENTS",
    "EVIDENCE_KINDS",
    "EVIDENCE_LEVELS",
    "EVIDENCE_STATES",
    "FORBIDDEN_OPERATIONS",
    "INDEX_STATEMENTS",
    "INVALIDATION_CAUSES",
    "MIGRATION_STATEMENTS",
    "NODE_STATES",
    "READERS",
    "SCHEMA_VERSION",
    "TABLE_SPECS",
    "TASK_STATES",
    "TRIGGER_STATEMENTS",
    "WRITE_OWNERS",
    "ColumnSpec",
    "IndexSpec",
    "TableSpec",
    "assert_schema_contract",
    "ddl",
]

# ---------------------------------------------------------------------------
# 0. 版本与枚举字面值
# ---------------------------------------------------------------------------
SCHEMA_VERSION: Final[int] = 1                # DB schema 版本，独立于契约 schema_version="1.0"
SCHEMA_MIGRATIONS_TABLE: Final[str] = "schema_migrations"

TASK_STATES: Final[tuple[str, ...]] = (
    "CREATED", "PLANNING", "READY", "RUNNING", "VERIFYING",
    "COMPLETED", "FAILED", "BLOCKED", "CANCELLED",
)  # 9 个；05 §9.2

NODE_STATES: Final[tuple[str, ...]] = (
    "PLANNED", "READY", "RUNNING", "VERIFYING", "VERIFIED",
    "FAILED", "BLOCKED", "DIAGNOSING", "RECOVERING", "INVALIDATED",
)  # 10 个；05 §9.3 + ADR-001

EVIDENCE_STATES: Final[tuple[str, ...]] = (
    "RECEIVED", "VALIDATED", "APPENDED", "INVALID", "CONFLICT",
)  # 5 个；05 §9.4。**不落 evidence 表**，见 EVIDENCE_STATE_NOTE

EVIDENCE_LEVELS: Final[tuple[str, ...]] = ("E0", "E1", "E2", "E3")
EVIDENCE_KINDS: Final[tuple[str, ...]] = (
    "agent_claim", "tool_invocation", "harness_trace",
    "executor_launch", "executor_process_exit", "artifact_observed", "verifier_recheck",
)  # 05 §1.6 / §4.5 冻结
INVALIDATION_CAUSES: Final[tuple[str, ...]] = (
    "INPUT_CHANGE", "PREDECESSOR_CHANGE", "GRAPH_VERSION_CHANGE", "RULESET_CHANGE",
)  # 06 §1.3 CHECK；ADR-001/004
AUDIT_RESULTS: Final[tuple[str, ...]] = ("OK", "DENIED")  # 06 §1.3 CHECK

AUDIT_ACTIONS: Final[tuple[str, ...]] = (
    "STATE_TRANSITION",
    "NODE_INVALIDATED",
    "RECOVERY_PLAN_FROZEN",
    "RECOVERY_PLAN_REUSE",
    "TOOL_REQUEST",
    "SIGN",
    "ENV_FINGERPRINT_CHECK",
    "STARTUP_GUARD",
    "AUDIT_WRITE_FAILED",
)  # 与 M03 observability/audit_events.py 的 action 对齐；新增 action 走迁移

EVIDENCE_STATE_NOTE: Final[str] = (
    "05 §9.4 的 Evidence 状态机是 Collector/Verifier 的摄入流水线状态。"
    "06 §1.3 的 evidence 表没有 state 列且只追加，因此 M02 不把 RECEIVED/VALIDATED 落库；"
    "APPENDED 以行存在表示；INVALID/CONFLICT 在写入前拒绝，不落 evidence 表。"
    "StateMachine 不写 evidence 表；E0–E2 写者是 Collector，E3 写者是 Verifier（06 §3）。"
)


# ---------------------------------------------------------------------------
# 1. 列 / 表 / 索引规格
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """一列的规格；`constraints` 是原样拼进 DDL 的列级约束。"""

    name: str
    sql_type: str
    nullable: bool
    constraints: str
    writer: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class IndexSpec:
    name: str
    table: str
    columns: tuple[str, ...]
    unique: bool
    purpose: str

    def sql(self) -> str:
        uniq = "UNIQUE " if self.unique else ""
        cols = ", ".join(self.columns)
        return f"CREATE {uniq}INDEX IF NOT EXISTS {self.name} ON {self.table} ({cols});"


@dataclass(frozen=True, slots=True)
class TableSpec:
    name: str
    writer: str
    append_only: bool
    columns: tuple[ColumnSpec, ...]
    table_constraints: tuple[str, ...]
    source: str


def _in(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def _hash_check(column: str) -> str:
    return (
        f"CHECK (length({column}) = 64 AND {column} NOT GLOB '*[^0-9a-f]*')"
    )


def _utc_check(column: str) -> str:
    # 06 §1.1：UTC RFC3339 文本；P2 写入统一微秒 + Z（固定 27 字符，字典序=时间序）。
    return (
        f"CHECK (length({column}) = 27 "
        f"AND {column} GLOB '????-??-??T??:??:??.??????Z')"
    )


def _task_id_check(column: str) -> str:
    return (
        f"CHECK (length({column}) = 41 "
        f"AND {column} GLOB 'task_????????-????-????-????-????????????' "
        f"AND {column} NOT GLOB '*[^0-9a-f-]*')"
    )


def _evidence_id_check(column: str) -> str:
    return (
        f"CHECK (length({column}) = 39 "
        f"AND {column} GLOB 'ev_????????-????-????-????-????????????' "
        f"AND {column} NOT GLOB '*[^0-9a-f-]*')"
    )


def _node_id_check(column: str) -> str:
    return (
        f"CHECK (length({column}) BETWEEN 1 AND 128 "
        f"AND {column} GLOB '[A-Za-z0-9]*' "
        f"AND {column} NOT GLOB '*[^A-Za-z0-9_.-]*')"
    )


def _attempt_id_check(column: str) -> str:
    return f"CHECK ({column} GLOB 'attempt_[0-9][0-9]*')"


# -- tasks ------------------------------------------------------------------
TASKS = TableSpec(
    name="tasks",
    writer="StateMachine.transition（UPDATE）；任务创建服务只 INSERT 初始 CREATED",
    append_only=False,
    source="06 §1.3；06 §2；06 §3",
    columns=(
        ColumnSpec("task_id", "TEXT", False, "PRIMARY KEY " + _task_id_check("task_id"),
                   "任务创建服务（INSERT）；StateMachine（只读）"),
        ColumnSpec("schema_version", "TEXT", False,
                   "CHECK (schema_version = '1.0')",
                   "任务创建服务", "契约版本列；06 §5"),
        ColumnSpec("domain_pack", "TEXT", False,
                   "CHECK (length(domain_pack) > 0 "
                   "AND domain_pack NOT GLOB '*[^A-Za-z0-9_.@+-]*')",
                   "任务创建服务", "完整 name@MAJOR.MINOR.PATCH 由模型层校验"),
        ColumnSpec("goal", "TEXT", False, "CHECK (length(trim(goal)) > 0)",
                   "任务创建服务", "不参与判定"),
        ColumnSpec("task_spec_hash", "TEXT", False, _hash_check("task_spec_hash"),
                   "任务创建服务", "TaskSpec 的 JCS SHA-256；创建后不可改"),
        ColumnSpec("state", "TEXT", False, f"CHECK (state IN {_in(TASK_STATES)})",
                   "StateMachine", "唯一状态写者；触发器要求同事务 OK 审计"),
        ColumnSpec("graph_version", "INTEGER", True,
                   "CHECK (graph_version IS NULL OR graph_version >= 1)",
                   "StateMachine（PLANNING→READY 时写入）", "06 §1.3；WP-04 产出"),
        ColumnSpec("created_at", "TEXT", False, _utc_check("created_at"),
                   "任务创建服务"),
        ColumnSpec("updated_at", "TEXT", False,
                   _utc_check("updated_at") + " " +
                   "CHECK (updated_at >= created_at)",
                   "StateMachine", "与 audit.created_at 使用同一 now"),
    ),
    table_constraints=(),
)

# -- nodes ------------------------------------------------------------------
NODES = TableSpec(
    name="nodes",
    writer="StateMachine.transition（UPDATE）；DAG 注册只 INSERT 初始 PLANNED",
    append_only=False,
    source="06 §1.3；05 §9.3；ADR-001/004",
    columns=(
        ColumnSpec("task_id", "TEXT", False,
                   "REFERENCES tasks(task_id) ON DELETE RESTRICT",
                   "DAG 注册（INSERT）；StateMachine（只读）"),
        ColumnSpec("node_id", "TEXT", False, _node_id_check("node_id"),
                   "DAG 注册（INSERT）；StateMachine（只读）",
                   "无 node_ 前缀要求；任务内唯一"),
        ColumnSpec("schema_version", "TEXT", False,
                   "CHECK (schema_version = '1.0')",
                   "DAG 注册"),
        ColumnSpec("node_type", "TEXT", False,
                   "CHECK (node_type GLOB '*.*' AND node_type GLOB '[a-z]*' "
                   "AND node_type NOT GLOB '*[^a-z0-9_.]*')",
                   "DAG 注册", "点分小写；完整正则由模型层校验"),
        ColumnSpec("template_id", "TEXT", False,
                   "CHECK (length(template_id) > 0)",
                   "DAG 注册"),
        ColumnSpec("state", "TEXT", False, f"CHECK (state IN {_in(NODE_STATES)})",
                   "StateMachine", "唯一状态写者；触发器要求同事务 OK 审计"),
        ColumnSpec("attempt_seq", "INTEGER", False,
                   "DEFAULT 0 CHECK (attempt_seq >= 0)",
                   "StateMachine", "READY→RUNNING 时 +1；重试不得复用旧 attempt_id"),
        ColumnSpec("plan_id", "TEXT", True,
                   "CHECK (plan_id IS NULL OR (length(plan_id) > 0 "
                   "AND instr(plan_id, '/') = 0 AND instr(plan_id, '\\') = 0))",
                   "StateMachine（仅 INVALIDATED→READY）", "plan_id 形态未冻结；不得含路径分隔符"),
        ColumnSpec("plan_hash", "TEXT", True,
                   "CHECK (plan_hash IS NULL OR " +
                   "(length(plan_hash) = 64 AND plan_hash NOT GLOB '*[^0-9a-f]*'))",
                   "StateMachine（仅 INVALIDATED→READY）", "内容寻址文件名；不得由调用方直接写"),
        ColumnSpec("updated_at", "TEXT", False, _utc_check("updated_at"),
                   "StateMachine"),
    ),
    table_constraints=(
        "PRIMARY KEY (task_id, node_id)",
        "CHECK ((plan_id IS NULL AND plan_hash IS NULL) "
        "OR (plan_id IS NOT NULL AND plan_hash IS NOT NULL))",
    ),
)

# -- evidence（元数据） -------------------------------------------------------
EVIDENCE = TableSpec(
    name="evidence",
    writer="Collector（E0–E2，追加）；Verifier（E3，追加）；任何组件不得 UPDATE/DELETE",
    append_only=True,
    source="06 §1.3；05 §4/§9.4；06 §3",
    columns=(
        ColumnSpec("evidence_id", "TEXT", False,
                   "PRIMARY KEY " + _evidence_id_check("evidence_id"),
                   "Collector / Verifier（INSERT）", "全局唯一；只追加"),
        ColumnSpec("task_id", "TEXT", False,
                   "REFERENCES tasks(task_id) ON DELETE RESTRICT",
                   "Collector / Verifier"),
        ColumnSpec("node_id", "TEXT", False, _node_id_check("node_id"),
                   "Collector / Verifier"),
        ColumnSpec("attempt_id", "TEXT", False, _attempt_id_check("attempt_id"),
                   "Collector / Verifier"),
        ColumnSpec("event_seq", "INTEGER", False,
                   "CHECK (event_seq >= 1)",
                   "Collector", "任务内单调递增且唯一；由 Collector 单写队列分配"),
        ColumnSpec("level", "TEXT", False, f"CHECK (level IN {_in(EVIDENCE_LEVELS)})",
                   "Collector（E0–E2）/ Verifier（E3）"),
        ColumnSpec("kind", "TEXT", False, f"CHECK (kind IN {_in(EVIDENCE_KINDS)})",
                   "Collector / Verifier"),
        ColumnSpec("producer", "TEXT", False,
                   "CHECK ((level IN ('E0','E1','E2') AND producer = 'collector') "
                   "OR (level = 'E3' AND producer = 'verifier'))",
                   "Collector / Verifier", "等级-写入者映射；05 §4.5"),
        ColumnSpec("timestamp", "TEXT", False, _utc_check("timestamp"),
                   "Collector / Verifier", "顺序判定用 event_seq，不用 timestamp"),
        ColumnSpec("payload_hash", "TEXT", False, _hash_check("payload_hash"),
                   "Collector / Verifier", "payload 不入库；只存哈希"),
        ColumnSpec("artifact_refs", "TEXT", True,
                   "CHECK (artifact_refs IS NULL "
                   "OR (json_valid(artifact_refs) AND json_type(artifact_refs) = 'array'))",
                   "Collector / Verifier", "JSON 数组文本；不存产物正文"),
        ColumnSpec("prev_hash", "TEXT", False, _hash_check("prev_hash"),
                   "Collector", "首条值 OQ-CT-10 未决；只校验形态"),
        ColumnSpec("chain_hash", "TEXT", False, _hash_check("chain_hash"),
                   "Collector", "前像未冻结（05 §13）；本文件不定义"),
    ),
    table_constraints=(
        "UNIQUE (task_id, event_seq)",
        "FOREIGN KEY (task_id, node_id) REFERENCES nodes(task_id, node_id) "
        "ON DELETE RESTRICT",
    ),
)

# -- evidence_invalidations -------------------------------------------------
EVIDENCE_INVALIDATIONS = TableSpec(
    name="evidence_invalidations",
    writer="StateMachine（仅 VERIFIED→INVALIDATED 的同事务追加）；不得 UPDATE/DELETE",
    append_only=True,
    source="06 §1.3；05 §9.3；ADR-001/004；决议 4",
    columns=(
        ColumnSpec("invalidation_id", "TEXT", False, "PRIMARY KEY",
                   "StateMachine", "形态未冻结；M02 用不透明 UUID，不新造前缀"),
        ColumnSpec("task_id", "TEXT", False,
                   "REFERENCES tasks(task_id) ON DELETE RESTRICT",
                   "StateMachine"),
        ColumnSpec("node_id", "TEXT", False, _node_id_check("node_id"),
                   "StateMachine"),
        ColumnSpec("evidence_id", "TEXT", False,
                   "REFERENCES evidence(evidence_id) ON DELETE RESTRICT",
                   "StateMachine", "必须引用真实 stale 证据；不得删除/改写证据"),
        ColumnSpec("reason_code", "TEXT", False, "CHECK (length(reason_code) > 0)",
                   "StateMachine"),
        ColumnSpec("cause_type", "TEXT", False,
                   f"CHECK (cause_type IN {_in(INVALIDATION_CAUSES)})",
                   "StateMachine"),
        ColumnSpec("cause_ref", "TEXT", True,
                   "CHECK (cause_ref IS NULL OR length(cause_ref) > 0)",
                   "StateMachine", "变更来源引用；不写计划正文"),
        ColumnSpec("plan_id", "TEXT", True,
                   "CHECK (plan_id IS NULL OR length(plan_id) > 0)",
                   "StateMachine"),
        ColumnSpec("plan_hash", "TEXT", True,
                   "CHECK (plan_hash IS NULL OR " +
                   "(length(plan_hash) = 64 AND plan_hash NOT GLOB '*[^0-9a-f]*'))",
                   "StateMachine"),
        ColumnSpec("created_at", "TEXT", False, _utc_check("created_at"),
                   "StateMachine"),
    ),
    table_constraints=(
        "CHECK ((plan_id IS NULL AND plan_hash IS NULL) "
        "OR (plan_id IS NOT NULL AND plan_hash IS NOT NULL))",
    ),
)

# -- audit_log ---------------------------------------------------------------
AUDIT_LOG = TableSpec(
    name="audit_log",
    writer="StateMachine（唯一写者；成功同事务、失败独立事务；只追加）",
    append_only=True,
    source="06 §1.3/§2/§3；05 §9.7；ADR-005；决议 7",
    columns=(
        ColumnSpec("audit_id", "TEXT", False, "PRIMARY KEY",
                   "StateMachine", "形态未冻结；M02 用不透明 UUID"),
        ColumnSpec("task_id", "TEXT", True,
                   "CHECK (task_id IS NULL OR length(task_id) > 0)",
                   "StateMachine", "不设 FK：失败审计可能先于/独立于任务存在"),
        ColumnSpec("node_id", "TEXT", True,
                   "CHECK (node_id IS NULL OR length(node_id) > 0)",
                   "StateMachine"),
        ColumnSpec("actor", "TEXT", False,
                   "CHECK (length(actor) > 0 AND instr(actor, ':') > 0)",
                   "StateMachine", "规范形态 role:identity，例如 wp_r:local"),
        ColumnSpec("action", "TEXT", False, f"CHECK (action IN {_in(AUDIT_ACTIONS)})",
                   "StateMachine"),
        ColumnSpec("previous_state", "TEXT", True,
                   "CHECK (previous_state IS NULL OR length(previous_state) > 0)",
                   "StateMachine"),
        ColumnSpec("next_state", "TEXT", True,
                   "CHECK (next_state IS NULL OR length(next_state) > 0)",
                   "StateMachine"),
        ColumnSpec("reason_code", "TEXT", True,
                   "CHECK (reason_code IS NULL OR length(reason_code) > 0)",
                   "StateMachine", "结构化原因码；不得用自由文本替代"),
        ColumnSpec("rule_version", "TEXT", True,
                   "CHECK (rule_version IS NULL OR length(rule_version) > 0)",
                   "StateMachine"),
        ColumnSpec("correlation_id", "TEXT", True,
                   "CHECK (correlation_id IS NULL OR length(correlation_id) > 0)",
                   "StateMachine"),
        ColumnSpec("plan_id", "TEXT", True,
                   "CHECK (plan_id IS NULL OR length(plan_id) > 0)",
                   "StateMachine", "仅计划冻结/复用相关事件"),
        ColumnSpec("plan_hash", "TEXT", True,
                   "CHECK (plan_hash IS NULL OR " +
                   "(length(plan_hash) = 64 AND plan_hash NOT GLOB '*[^0-9a-f]*'))",
                   "StateMachine"),
        ColumnSpec("result", "TEXT", False, f"CHECK (result IN {_in(AUDIT_RESULTS)})",
                   "StateMachine"),
        ColumnSpec("error_code", "TEXT", True,
                   "CHECK (error_code IS NULL OR length(error_code) > 0)",
                   "StateMachine", "DENIED 必填；OK 必须为 NULL"),
        ColumnSpec("created_at", "TEXT", False, _utc_check("created_at"),
                   "StateMachine"),
    ),
    table_constraints=(
        # 成功迁移不携带 error_code；失败必须携带（05 §9.7 / ADR-005）
        "CHECK ((result = 'OK' AND error_code IS NULL) "
        "OR (result = 'DENIED' AND error_code IS NOT NULL))",
        # 状态迁移审计的必填字段（05 §9.7；提示中的六项 + error_code 由上一约束保证）
        "CHECK (action <> 'STATE_TRANSITION' OR (previous_state IS NOT NULL "
        "AND next_state IS NOT NULL AND reason_code IS NOT NULL "
        "AND rule_version IS NOT NULL AND correlation_id IS NOT NULL))",
        # 计划字段成对
        "CHECK ((plan_id IS NULL AND plan_hash IS NULL) "
        "OR (plan_id IS NOT NULL AND plan_hash IS NOT NULL))",
    ),
)

# -- idempotency_keys --------------------------------------------------------
IDEMPOTENCY_KEYS = TableSpec(
    name="idempotency_keys",
    writer="API 任务创建路径（只 INSERT，与 tasks 同事务；不得 UPDATE）",
    append_only=False,
    source="06 §1.3/§2/§4.5；附录 E.4；OQ-DB-2 开放",
    columns=(
        ColumnSpec("idem_key", "TEXT", False,
                   "PRIMARY KEY CHECK (length(idem_key) BETWEEN 1 AND 255 "
                   "AND length(trim(idem_key)) = length(idem_key))",
                   "API 创建路径", "完整字符集校验在 idempotency.py"),
        ColumnSpec("request_hash", "TEXT", False, _hash_check("request_hash"),
                   "API 创建路径", "JCS 规范化后 SHA-256；不是 sort_keys=True 的 JSON"),
        ColumnSpec("task_id", "TEXT", False,
                   "REFERENCES tasks(task_id) ON DELETE RESTRICT",
                   "API 创建路径", "与 tasks 同事务；06 §2"),
        ColumnSpec("created_at", "TEXT", False, _utc_check("created_at"),
                   "API 创建路径"),
    ),
    table_constraints=(),
)

# -- schema_migrations -------------------------------------------------------
SCHEMA_MIGRATIONS = TableSpec(
    name=SCHEMA_MIGRATIONS_TABLE,
    writer="迁移执行器（只 INSERT；已应用迁移不得改写）",
    append_only=True,
    source="06 §5；本模块 migrations.py",
    columns=(
        ColumnSpec("version", "INTEGER", False,
                   "PRIMARY KEY CHECK (version >= 1)",
                   "迁移执行器"),
        ColumnSpec("name", "TEXT", False,
                   "UNIQUE CHECK (length(name) > 0)",
                   "迁移执行器"),
        ColumnSpec("checksum", "TEXT", False, _hash_check("checksum"),
                   "迁移执行器", "迁移 SQL 的规范化 SHA-256"),
        ColumnSpec("applied_at", "TEXT", False, _utc_check("applied_at"),
                   "迁移执行器"),
        ColumnSpec("applied_by", "TEXT", False,
                   "CHECK (length(applied_by) > 0)",
                   "迁移执行器"),
        ColumnSpec("execution_ms", "INTEGER", True,
                   "CHECK (execution_ms IS NULL OR execution_ms >= 0)",
                   "迁移执行器"),
    ),
    table_constraints=(),
)

TABLE_SPECS: Final[Mapping[str, TableSpec]] = MappingProxyType(
    {
        spec.name: spec
        for spec in (
            TASKS, NODES, EVIDENCE, EVIDENCE_INVALIDATIONS,
            AUDIT_LOG, IDEMPOTENCY_KEYS, SCHEMA_MIGRATIONS,
        )
    }
)

APPEND_ONLY_TABLES: Final[tuple[str, ...]] = (
    "evidence", "evidence_invalidations", "audit_log", "schema_migrations",
)

# 06 §3 的单写者矩阵（R 只读；W 唯一写；A 追加；— 禁止）
WRITE_OWNERS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "tasks": "StateMachine（UPDATE 状态）；任务创建服务（INSERT CREATED）",
        "nodes": "StateMachine（UPDATE 状态/attempt_seq/plan_*）；DAG 注册（INSERT PLANNED）",
        "evidence": "Collector（E0–E2，追加）；Verifier（E3，追加）",
        "evidence_invalidations": "StateMachine（VERIFIED→INVALIDATED 同事务追加）",
        "audit_log": "StateMachine（成功同事务；失败独立事务；只追加）",
        "idempotency_keys": "API 任务创建路径（INSERT，与 tasks 同事务）",
        "schema_migrations": "迁移执行器（INSERT）",
    }
)

READERS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "tasks": ("StateMachine", "DAG Builder", "Gate", "Verifier", "API", "Scheduler"),
        "nodes": ("StateMachine", "Scheduler", "Gate", "Verifier", "API", "WP-R"),
        "evidence": ("Collector", "Gate", "Verifier", "API", "WP-R"),
        "evidence_invalidations": ("Gate", "StateMachine", "Verifier", "WP-R"),
        "audit_log": ("Gate", "Verifier", "API", "WP-R", "BootRecovery"),
        "idempotency_keys": ("API",),
        "schema_migrations": ("迁移执行器", "BootRecovery"),
    }
)

FORBIDDEN_OPERATIONS: Final[tuple[str, ...]] = (
    "UPDATE/DELETE evidence / evidence_invalidations / audit_log / schema_migrations（只追加）",
    "绕过 StateMachine 直接 UPDATE tasks.state / nodes.state / nodes.attempt_seq / nodes.plan_*",
    "INSERT tasks 时 state != 'CREATED'",
    "INSERT nodes 时 state != 'PLANNED'",
    "在 tasks/nodes 中写入 T1 Recovery 状态（PROPOSED/APPROVED/EXECUTING/RECHECKED/CLOSED/ESCALATED）",
    "新增 recovery_plans 表或把计划正文写入 audit_log",
    "删除 tasks/nodes/evidence 以“修复”数据",
)

# ---------------------------------------------------------------------------
# 2. DDL 渲染（只返回字符串，不执行）
# ---------------------------------------------------------------------------
def _render_create_table(spec: TableSpec) -> str:
    lines: list[str] = []
    for col in spec.columns:
        parts = [f"  {col.name} {col.sql_type}"]
        if not col.nullable:
            parts.append("NOT NULL")
        if col.constraints:
            parts.append(col.constraints)
        lines.append(" ".join(parts))
    lines.extend(f"  {c}" for c in spec.table_constraints)
    body = ",\n".join(lines)
    return f"CREATE TABLE IF NOT EXISTS {spec.name} (\n{body}\n);"


# 迁移引导：先建 schema_migrations 本身，才能记录版本。
BOOTSTRAP_STATEMENTS: Final[tuple[str, ...]] = (
    _render_create_table(SCHEMA_MIGRATIONS),
)

# 迁移体：不含 PRAGMA（journal_mode 不能在事务内切换；连接建立时单独执行）。
# 定义放在 DDL_STATEMENTS 之后，避免前向引用。


COLUMN_INDEXES: Final[Mapping[str, tuple[IndexSpec, ...]]] = MappingProxyType(
    {
        "tasks": (
            IndexSpec("idx_tasks_state", "tasks", ("state", "updated_at"), False,
                      "就绪/取消/恢复扫描"),
        ),
        "nodes": (
            IndexSpec("idx_nodes_state", "nodes", ("task_id", "state"), False,
                      "就绪/失效查询；06 §1.3"),
            IndexSpec("idx_nodes_state_global", "nodes", ("state", "updated_at"), False,
                      "调度器跨任务扫描 READY/RUNNING"),
            IndexSpec("idx_nodes_plan", "nodes", ("task_id", "node_id", "plan_hash"), False,
                      "INVALIDATED→READY 计划追溯"),
        ),
        "evidence": (
            IndexSpec("idx_evidence_task_seq", "evidence", ("task_id", "event_seq"), True,
                      "链校验与分页；06 §1.3"),
            IndexSpec("idx_evidence_attempt", "evidence",
                      ("task_id", "node_id", "attempt_id", "event_seq"), False,
                      "重启恢复：按 attempt 找 launch/exit"),
            IndexSpec("idx_evidence_level", "evidence", ("task_id", "level"), False,
                      "Gate 覆盖矩阵"),
        ),
        "evidence_invalidations": (
            IndexSpec("idx_invalidations_node", "evidence_invalidations",
                      ("task_id", "node_id"), False, "stale 判定"),
            IndexSpec("idx_invalidations_evidence", "evidence_invalidations",
                      ("task_id", "evidence_id"), False,
                      "证据是否 stale 的点查（Gate 必检项）"),
        ),
        "audit_log": (
            IndexSpec("idx_audit_task_time", "audit_log", ("task_id", "created_at"), False,
                      "审计追溯；06 §1.3"),
            IndexSpec("idx_audit_plan", "audit_log", ("plan_hash",), False,
                      "计划冻结/守卫校验追溯；06 §1.3"),
            IndexSpec("idx_audit_result", "audit_log",
                      ("task_id", "result", "created_at"), False,
                      "DENIED 迁移审计核查；06 §1.3"),
            IndexSpec("idx_audit_correlation", "audit_log", ("correlation_id",), False,
                      "按迁移请求追溯成功/失败两条记录"),
        ),
        "idempotency_keys": (
            IndexSpec("idx_idempotency_task", "idempotency_keys", ("task_id",), False,
                      "按任务反查幂等键"),
        ),
        "schema_migrations": (),
    }
)

INDEX_STATEMENTS: Final[tuple[str, ...]] = tuple(
    idx.sql()
    for indexes in COLUMN_INDEXES.values()
    for idx in indexes
)

# 列 → 索引名（一列可属于多个索引；未列出的列没有二级索引，但可能属于主键/唯一键）。
# 这张表回答“每列的索引是什么”，不用读者从 `COLUMN_INDEXES` 反推。
def _build_column_index_map() -> Mapping[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for indexes in COLUMN_INDEXES.values():
        for idx in indexes:
            for column in idx.columns:
                result[f"{idx.table}.{column}"] = tuple(
                    candidate.name
                    for candidate in COLUMN_INDEXES[idx.table]
                    if column in candidate.columns
                )
    return MappingProxyType(result)


COLUMN_INDEX_MAP: Final[Mapping[str, tuple[str, ...]]] = _build_column_index_map()

DDL_STATEMENTS: Final[tuple[str, ...]] = (
    "PRAGMA journal_mode = WAL;",
    "PRAGMA foreign_keys = ON;",
    "PRAGMA busy_timeout = 5000;",
    "PRAGMA synchronous = FULL;",   # 审计/证据只追加，提交后必须落盘
    *(_render_create_table(spec) for spec in TABLE_SPECS.values()),
    *INDEX_STATEMENTS,
)

# 迁移体：不含 PRAGMA（journal_mode 不能在事务内切换；连接建立时单独执行）。
MIGRATION_STATEMENTS: Final[tuple[str, ...]] = tuple(
    statement for statement in DDL_STATEMENTS
    if not statement.lstrip().upper().startswith("PRAGMA")
)

# ---------------------------------------------------------------------------
# 3. 触发器：只追加表、初始状态、状态更新必须带审计
# ---------------------------------------------------------------------------
TRIGGER_STATEMENTS: Final[tuple[str, ...]] = (
    # --- 只追加表 ---------------------------------------------------------
    """
CREATE TRIGGER IF NOT EXISTS trg_evidence_no_update
BEFORE UPDATE ON evidence
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: evidence'); END;
""",
    """
CREATE TRIGGER IF NOT EXISTS trg_evidence_no_delete
BEFORE DELETE ON evidence
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: evidence'); END;
""",
    """
CREATE TRIGGER IF NOT EXISTS trg_invalidations_no_update
BEFORE UPDATE ON evidence_invalidations
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: evidence_invalidations'); END;
""",
    """
CREATE TRIGGER IF NOT EXISTS trg_invalidations_no_delete
BEFORE DELETE ON evidence_invalidations
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: evidence_invalidations'); END;
""",
    """
CREATE TRIGGER IF NOT EXISTS trg_audit_no_update
BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: audit_log'); END;
""",
    """
CREATE TRIGGER IF NOT EXISTS trg_audit_no_delete
BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: audit_log'); END;
""",
    """
CREATE TRIGGER IF NOT EXISTS trg_migrations_no_update
BEFORE UPDATE ON schema_migrations
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: schema_migrations'); END;
""",
    """
CREATE TRIGGER IF NOT EXISTS trg_migrations_no_delete
BEFORE DELETE ON schema_migrations
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: schema_migrations'); END;
""",
    """
CREATE TRIGGER IF NOT EXISTS trg_idempotency_no_update
BEFORE UPDATE ON idempotency_keys
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_TABLE: idempotency_keys'); END;
""",
    # --- 创建只能进入初始状态 --------------------------------------------
    """
CREATE TRIGGER IF NOT EXISTS trg_tasks_insert_created
BEFORE INSERT ON tasks
WHEN NEW.state <> 'CREATED'
BEGIN SELECT RAISE(ABORT, 'TASK_MUST_BE_INSERTED_CREATED'); END;
""",
    """
CREATE TRIGGER IF NOT EXISTS trg_nodes_insert_planned
BEFORE INSERT ON nodes
WHEN NEW.state <> 'PLANNED'
BEGIN SELECT RAISE(ABORT, 'NODE_MUST_BE_INSERTED_PLANNED'); END;
""",
    # --- 任务/节点状态更新必须带同事务 OK 审计 ---------------------------
    # 审记行必须先插入（同一事务内可见），且 created_at 必须等于 updated_at。
    # 触发器不是安全边界，但能抓住“直接 UPDATE 状态”的旁路写。
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
""",
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
""",
    # --- 非状态字段不得脱离状态迁移单独变化 ------------------------------
    """
CREATE TRIGGER IF NOT EXISTS trg_tasks_graph_version_requires_state_change
BEFORE UPDATE OF graph_version ON tasks
WHEN OLD.state = NEW.state AND OLD.graph_version IS NOT NEW.graph_version
BEGIN SELECT RAISE(ABORT, 'GRAPH_VERSION_CHANGE_WITHOUT_STATE_TRANSITION'); END;
""",
    """
CREATE TRIGGER IF NOT EXISTS trg_nodes_nonstate_requires_state_change
BEFORE UPDATE OF attempt_seq, plan_id, plan_hash ON nodes
WHEN OLD.state = NEW.state
 AND (OLD.attempt_seq IS NOT NEW.attempt_seq
      OR OLD.plan_id IS NOT NEW.plan_id
      OR OLD.plan_hash IS NOT NEW.plan_hash)
BEGIN SELECT RAISE(ABORT, 'NODE_FIELD_CHANGE_WITHOUT_STATE_TRANSITION'); END;
""",
    # --- 禁止删除任务/节点 ------------------------------------------------
    """
CREATE TRIGGER IF NOT EXISTS trg_tasks_no_delete
BEFORE DELETE ON tasks
BEGIN SELECT RAISE(ABORT, 'TASK_DELETE_FORBIDDEN'); END;
""",
    """
CREATE TRIGGER IF NOT EXISTS trg_nodes_no_delete
BEFORE DELETE ON nodes
BEGIN SELECT RAISE(ABORT, 'NODE_DELETE_FORBIDDEN'); END;
""",
)


def ddl(*, include_triggers: bool = True) -> str:
    """返回完整 DDL 文本（供迁移/审阅使用；P2 不执行）。"""
    parts = list(DDL_STATEMENTS)
    if include_triggers:
        parts.extend(TRIGGER_STATEMENTS)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 4. 自检（实现阶段调用；P2 只定义）
# ---------------------------------------------------------------------------
def assert_schema_contract() -> list[str]:
    """返回违反项列表；空列表表示通过。

    检查的是“本文件自己声明的契约”，不是数据库实际状态。
    """
    problems: list[str] = []

    if len(TASK_STATES) != 9:
        problems.append(f"TASK_STATES 应为 9，实际 {len(TASK_STATES)}")
    if len(NODE_STATES) != 10:
        problems.append(f"NODE_STATES 应为 10，实际 {len(NODE_STATES)}")
    if len(EVIDENCE_STATES) != 5:
        problems.append(f"EVIDENCE_STATES 应为 5，实际 {len(EVIDENCE_STATES)}")
    # Task/Node 共享 READY/RUNNING/VERIFYING/FAILED/BLOCKED 是 05 §9 的既定事实，
    # 不能把“同名”当成混用；这里只校验各自的完整集合。
    expected_task = {
        "CREATED", "PLANNING", "READY", "RUNNING", "VERIFYING",
        "COMPLETED", "FAILED", "BLOCKED", "CANCELLED",
    }
    expected_node = {
        "PLANNED", "READY", "RUNNING", "VERIFYING", "VERIFIED",
        "FAILED", "BLOCKED", "DIAGNOSING", "RECOVERING", "INVALIDATED",
    }
    if set(TASK_STATES) != expected_task:
        problems.append("TASK_STATES 与 05 §9.2 的 9 个状态不一致")
    if set(NODE_STATES) != expected_node:
        problems.append("NODE_STATES 与 05 §9.3 + ADR-001 的 10 个状态不一致")

    if set(WRITE_OWNERS) != set(TABLE_SPECS):
        problems.append("WRITE_OWNERS 必须覆盖且只覆盖 TABLE_SPECS")
    for table in APPEND_ONLY_TABLES:
        spec = TABLE_SPECS.get(table)
        if spec is None or not spec.append_only:
            problems.append(f"{table} 必须在 APPEND_ONLY_TABLES 且 append_only=True")

    all_sql = ddl()
    for forbidden in ("PROPOSED", "APPROVED", "EXECUTING", "RECHECKED", "CLOSED", "ESCALATED"):
        if forbidden in all_sql:
            problems.append(f"T0 DDL 不得出现 T1 Recovery 状态 {forbidden}")
    if "recovery_plans" in all_sql:
        problems.append("不得建 recovery_plans 表（ADR-004 决议 3）")

    if "STATE_TRANSITION" not in AUDIT_ACTIONS:
        problems.append("AUDIT_ACTIONS 必须包含 STATE_TRANSITION")
    if "PLAN_HASH_MISMATCH" in all_sql:
        # 错误码不应写进 DDL；这里只是防止把应用码误当列/约束
        problems.append("错误码不应出现在 DDL 中")

    # 每张表必须有主键或显式唯一键
    for name, spec in TABLE_SPECS.items():
        has_pk = any("PRIMARY KEY" in c.constraints for c in spec.columns) or any(
            "PRIMARY KEY" in c for c in spec.table_constraints
        )
        if not has_pk:
            problems.append(f"{name} 缺少主键")

    return problems