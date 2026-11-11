"""M02 · persistence/migrations.py — schema_migrations、升级骨架与失败回滚（P2 伪代码）。

阶段：P2｜状态：版本表、迁移清单、升级流程与回滚语义；**不执行迁移、不建库**。
规范来源：`docs/design/06_DATA_AND_API.md` §5（只向前、迁移记录、备份、只追加表）、
`docs/design/06_DATA_AND_API.md` §2（事务边界）、`schema_sql.py`。

设计要点：
  1. **只向前**：没有 `down()`；降级只能用迁移前备份恢复（06 §5）。
  2. **全有或全无**：一次 `upgrade()` 在一个 `BEGIN EXCLUSIVE` 事务里应用所有 pending
     迁移；任一语句失败 → 整体 `ROLLBACK`，DB 版本停在迁移前。
  3. **迁移行与被迁移 schema 同事务**：`schema_migrations` 插入和 DDL 一起提交；
     不会出现“DDL 已生效但版本没记”或“版本记了但 DDL 没生效”。
  4. **校验和**：已应用迁移的 SQL 规范化 SHA-256 与代码中的 `Migration.checksum` 不一致
     时拒绝启动/升级，禁止“改历史迁移”。
  5. **备份**：DDL 前必须成功创建备份；备份失败不得开始迁移。

错误码边界：本文件的异常是启动/CLI 异常（退出码 2），**不是 API 错误码**，
因此不写入 `contracts.errors.REGISTRY`；M02 不新增 E.3 错误码。
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from dataclasses import dataclass
from typing import Callable, Final, Protocol, Sequence

from . import schema_sql

__all__ = [
    "BOOTSTRAP_STATEMENTS",
    "MIGRATIONS",
    "SCHEMA_VERSION",
    "AppliedMigration",
    "BackupPort",
    "Migration",
    "MigrationBackupFailed",
    "MigrationChecksumMismatch",
    "MigrationError",
    "MigrationFailed",
    "MigrationLockTimeout",
    "MigrationPlan",
    "MigrationReport",
    "MigrationRunner",
    "SchemaMigrationState",
    "SchemaVersionUnsupported",
    "assert_migration_contract",
    "assert_schema_current",
]

SCHEMA_VERSION: Final[int] = schema_sql.SCHEMA_VERSION


# ---------------------------------------------------------------------------
# 0. 异常（启动/CLI 语义，不是 API 错误码）
# ---------------------------------------------------------------------------
class MigrationError(RuntimeError):
    """迁移失败的基类；启动层以退出码 2 拒绝启动，不监听端口。"""

    code = "MIGRATION_FAILED"
    exit_code = 2


class MigrationChecksumMismatch(MigrationError):
    code = "MIGRATION_CHECKSUM_MISMATCH"


class SchemaVersionUnsupported(MigrationError):
    code = "SCHEMA_VERSION_UNSUPPORTED"


class MigrationBackupFailed(MigrationError):
    code = "MIGRATION_BACKUP_FAILED"


class MigrationLockTimeout(MigrationError):
    code = "MIGRATION_LOCK_TIMEOUT"


class MigrationFailed(MigrationError):
    code = "MIGRATION_FAILED"

    def __init__(self, version: int, cause: BaseException) -> None:
        self.version = version
        self.cause = cause
        super().__init__(f"迁移 v{version} 失败；已回滚到迁移前版本：{cause}")


# ---------------------------------------------------------------------------
# 1. 迁移定义与校验和
# ---------------------------------------------------------------------------
def _normalized(statements: Sequence[str]) -> str:
    """迁移 SQL 的规范化文本：去首尾空白、LF 连接、末尾 LF。

    不得用文件 mtime、字节数或“版本号”替代 SQL 文本；改一个空格也应改变校验和。
    """
    return "\n".join(statement.strip() for statement in statements) + "\n"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]
    source: str

    @property
    def checksum(self) -> str:
        return _sha256(_normalized(self.statements))


MIGRATIONS: Final[tuple[Migration, ...]] = (
    Migration(
        version=1,
        name="initial_schema",
        statements=(
            *schema_sql.MIGRATION_STATEMENTS,
            *schema_sql.TRIGGER_STATEMENTS,
        ),
        source="06 §1.3/§2/§3/§5；schema_sql.py",
    ),
)

BOOTSTRAP_STATEMENTS: Final[tuple[str, ...]] = schema_sql.BOOTSTRAP_STATEMENTS


# ---------------------------------------------------------------------------
# 2. 备份端口（实现由 WP-03 提供；M02 只定义契约）
# ---------------------------------------------------------------------------
class BackupPort(Protocol):
    """迁移前备份/失败恢复；实现必须使用 SQLite backup API，不得只复制主文件。"""

    def create_backup(self, *, label: str) -> str:
        """返回备份标识/路径；失败抛异常，调用方不得继续迁移。"""
        ...

    def restore(self, backup_path: str) -> None:
        """用备份恢复数据库；仅在回滚后完整性检查仍失败时调用。"""
        ...


# ---------------------------------------------------------------------------
# 3. 读取状态
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class AppliedMigration:
    version: int
    name: str
    checksum: str
    applied_at: str
    applied_by: str
    execution_ms: int | None


@dataclass(frozen=True, slots=True)
class SchemaMigrationState:
    current_version: int
    applied: tuple[AppliedMigration, ...]
    pending: tuple[Migration, ...]
    checksums_ok: bool
    target_version: int


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    from_version: int
    to_version: int
    pending: tuple[Migration, ...]
    requires_backup: bool
    is_downgrade: bool


@dataclass(frozen=True, slots=True)
class MigrationReport:
    from_version: int
    to_version: int
    applied_versions: tuple[int, ...]
    backup_path: str | None
    dry_run: bool
    duration_ms: int
    integrity_ok: bool
    foreign_keys_ok: bool


# ---------------------------------------------------------------------------
# 4. 升级器
# ---------------------------------------------------------------------------
class MigrationRunner:
    """迁移执行器；一个实例只服务一个连接/一个进程。"""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        backup: BackupPort,
        clock_ms: Callable[[], int] = lambda: int(time.time() * 1000),
        applied_by: str = "migration_runner",
    ) -> None:
        self._conn = conn
        self._backup = backup
        self._clock_ms = clock_ms
        self._applied_by = applied_by

    # -- 读 ---------------------------------------------------------------
    def bootstrap(self) -> None:
        """建 `schema_migrations`；已存在则无操作。"""
        for statement in BOOTSTRAP_STATEMENTS:
            self._conn.execute(statement)

    def applied(self) -> tuple[AppliedMigration, ...]:
        raise NotImplementedError("P2 伪代码：MigrationRunner.applied")

    def current_version(self) -> int:
        applied = self.applied()
        return max((m.version for m in applied), default=0)

    def plan(self, *, target: int = SCHEMA_VERSION) -> MigrationPlan:
        """计算 pending；不执行 DDL。

        - applied 必须是 `MIGRATIONS` 的前缀，版本连续且校验和一致；
        - `target < current` 是降级，拒绝（只向前）；
        - `target > SCHEMA_VERSION` 是未知版本，拒绝。
        """
        if target < 1 or target > SCHEMA_VERSION:
            raise SchemaVersionUnsupported(
                f"目标 schema 版本 {target} 不在 1..{SCHEMA_VERSION} 内"
            )
        applied = self.applied()
        known = {m.version: m for m in MIGRATIONS}
        versions = [m.version for m in applied]
        expected_prefix = list(range(1, len(versions) + 1))
        if versions != expected_prefix:
            raise SchemaVersionUnsupported(
                f"已应用迁移不是连续前缀：{versions!r}"
            )
        for row in applied:
            migration = known.get(row.version)
            if migration is None:
                raise SchemaVersionUnsupported(
                    f"数据库已有未知迁移 v{row.version}；代码版本过旧，拒绝降级"
                )
            if row.name != migration.name:
                raise MigrationChecksumMismatch(
                    f"v{row.version} 名称不一致：DB={row.name!r} code={migration.name!r}"
                )
            if row.checksum != migration.checksum:
                raise MigrationChecksumMismatch(
                    f"v{row.version} 校验和不一致；历史迁移不得改写"
                )
        current = max(versions, default=0)
        if target < current:
            raise SchemaVersionUnsupported(
                f"拒绝降级：DB v{current} → target v{target}；只向前，回滚用备份"
            )
        pending = tuple(m for m in MIGRATIONS if m.version > current and m.version <= target)
        return MigrationPlan(
            from_version=current,
            to_version=target,
            pending=pending,
            requires_backup=bool(pending),
            is_downgrade=False,
        )

    def state(self, *, target: int = SCHEMA_VERSION) -> SchemaMigrationState:
        applied = self.applied()
        current = max((m.version for m in applied), default=0)
        checksums_ok = True
        try:
            plan = self.plan(target=target)
            pending = plan.pending
        except MigrationChecksumMismatch:
            checksums_ok = False
            pending = ()
        return SchemaMigrationState(
            current_version=current,
            applied=applied,
            pending=pending,
            checksums_ok=checksums_ok,
            target_version=target,
        )

    # -- 写 ---------------------------------------------------------------
    def upgrade(
        self,
        *,
        target: int = SCHEMA_VERSION,
        dry_run: bool = False,
    ) -> MigrationReport:
        """应用 pending 迁移；全有或全无。

        步骤（伪代码，实现时严格按此顺序）：
          1. `plan(target)`；校验已应用迁移的名称/校验和/连续性；
          2. 若无 pending → 只做完整性检查并返回；
          3. `backup.create_backup(label=...)`；失败 → `MigrationBackupFailed`，不执行 DDL；
          4. `BEGIN EXCLUSIVE`（写锁；拿不到 → `MigrationLockTimeout`）；
          5. 逐条执行 pending 的 statements；每条执行后断言 `in_transaction` 仍为 True；
          6. 插入 `schema_migrations` 行（与 DDL 同事务）；
          7. `PRAGMA user_version = target`（辅助标记；以 schema_migrations 为准）；
          8. `dry_run` → `ROLLBACK`；否则 `COMMIT`；
          9. `PRAGMA integrity_check` / `foreign_key_check`；失败 → 恢复备份并抛错。
        """
        started = self._clock_ms()
        self.bootstrap()
        plan = self.plan(target=target)
        if not plan.pending:
            integrity_ok, foreign_keys_ok = self._post_checks()
            return MigrationReport(
                from_version=plan.from_version,
                to_version=plan.from_version,
                applied_versions=(),
                backup_path=None,
                dry_run=dry_run,
                duration_ms=self._clock_ms() - started,
                integrity_ok=integrity_ok,
                foreign_keys_ok=foreign_keys_ok,
            )

        backup_path: str | None = None
        if not dry_run:
            try:
                backup_path = self._backup.create_backup(
                    label=f"before_v{plan.from_version}_to_v{plan.to_version}"
                )
            except Exception as exc:  # noqa: BLE001 - 备份失败必须中止
                raise MigrationBackupFailed(
                    f"迁移前备份失败，未执行任何 DDL：{exc}"
                ) from exc

        applied_versions: list[int] = []
        try:
            self._conn.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as exc:
            raise MigrationLockTimeout("无法取得迁移写锁；另一个迁移可能正在运行") from exc

        try:
            for migration in plan.pending:
                for statement in migration.statements:
                    self._conn.execute(statement)
                    if not self._conn.in_transaction:
                        # executescript/某些 PRAGMA 会隐式提交；出现即视为实现缺陷。
                        raise MigrationFailed(
                            migration.version,
                            RuntimeError("迁移语句隐式提交，破坏全有或全无语义"),
                        )
                self._insert_applied(migration)
                applied_versions.append(migration.version)
            self._conn.execute(f"PRAGMA user_version = {int(target)}")
            if dry_run:
                self._conn.rollback()
            else:
                self._conn.commit()
        except MigrationFailed:
            self._conn.rollback()
            raise
        except Exception as exc:  # noqa: BLE001 - 统一回滚并保留原因
            self._conn.rollback()
            # 回滚后仍可能因磁盘/损坏而不一致；只有检查失败才动备份。
            integrity_ok, foreign_keys_ok = self._post_checks()
            if backup_path is not None and not (integrity_ok and foreign_keys_ok):
                self._backup.restore(backup_path)
            raise MigrationFailed(
                plan.pending[len(applied_versions)].version
                if len(applied_versions) < len(plan.pending)
                else plan.to_version,
                exc,
            ) from exc

        integrity_ok, foreign_keys_ok = self._post_checks()
        if not (integrity_ok and foreign_keys_ok):
            if backup_path is not None:
                self._backup.restore(backup_path)
            raise MigrationFailed(
                plan.to_version,
                RuntimeError(
                    f"迁移后完整性检查失败：integrity_ok={integrity_ok}, "
                    f"foreign_keys_ok={foreign_keys_ok}"
                ),
            )
        return MigrationReport(
            from_version=plan.from_version,
            to_version=plan.to_version,
            applied_versions=tuple(applied_versions),
            backup_path=backup_path,
            dry_run=dry_run,
            duration_ms=self._clock_ms() - started,
            integrity_ok=integrity_ok,
            foreign_keys_ok=foreign_keys_ok,
        )

    def _insert_applied(self, migration: Migration) -> None:
        raise NotImplementedError("P2 伪代码：MigrationRunner._insert_applied")

    def _post_checks(self) -> tuple[bool, bool]:
        """`PRAGMA integrity_check` == 'ok' 且 `PRAGMA foreign_key_check` 无行。"""
        raise NotImplementedError("P2 伪代码：MigrationRunner._post_checks")


# ---------------------------------------------------------------------------
# 5. 启动守卫
# ---------------------------------------------------------------------------
def assert_schema_current(conn: sqlite3.Connection, *, runner: MigrationRunner) -> None:
    """BootRecovery 调用：DB 必须正好在当前 schema 版本，且无 pending。

    失败抛 `SchemaVersionUnsupported` / `MigrationChecksumMismatch`；
    BootRecovery 必须把 `schedule_allowed` 置 False，不得“先调度再补迁移”。
    """
    plan = runner.plan(target=SCHEMA_VERSION)
    if plan.pending:
        raise SchemaVersionUnsupported(
            f"存在未应用迁移：{[m.version for m in plan.pending]}"
        )
    if plan.from_version != SCHEMA_VERSION:
        raise SchemaVersionUnsupported(
            f"DB schema v{plan.from_version} != 期望 v{SCHEMA_VERSION}"
        )


# ---------------------------------------------------------------------------
# 6. 回滚语义（写进文档，不靠注释口口相传）
# ---------------------------------------------------------------------------
ROLLBACK_SEMANTICS: Final[tuple[str, ...]] = (
    "只向前：没有 down 迁移；降级用迁移前备份恢复，不做破坏性降级（06 §5）。",
    "一次 upgrade 的全部 pending 迁移在同一事务内；任一失败 → 全部回滚，版本停在迁移前。",
    "schema_migrations 行与 DDL 同事务插入；不存在“DDL 生效但版本未记”的脏状态。",
    "进程崩溃：SQLite 在下次打开时回滚未提交事务；已提交迁移要么完整存在，要么完全不存在。",
    "回滚后用 integrity_check/foreign_key_check 复核；仍失败才 restore 备份。",
    "已应用迁移的 checksum 不得改变；改历史迁移会被拒绝（MigrationChecksumMismatch）。",
    "迁移不得删除历史证据/审计；需要改结构时新增列或新表（06 §5）。",
)


# ---------------------------------------------------------------------------
# 7. 自检（实现阶段调用；P2 只定义）
# ---------------------------------------------------------------------------
def assert_migration_contract() -> list[str]:
    problems: list[str] = []
    versions = [m.version for m in MIGRATIONS]
    if versions != list(range(1, len(versions) + 1)):
        problems.append(f"迁移版本必须从 1 连续：{versions!r}")
    if SCHEMA_VERSION != max(versions, default=0):
        problems.append("SCHEMA_VERSION 必须等于最大迁移版本")
    names = [m.name for m in MIGRATIONS]
    if len(set(names)) != len(names):
        problems.append("迁移名称必须唯一")
    if not BOOTSTRAP_STATEMENTS:
        problems.append("BOOTSTRAP_STATEMENTS 不能为空")
    if any("schema_migrations" not in s for s in BOOTSTRAP_STATEMENTS):
        problems.append("引导语句只能创建 schema_migrations")
    if any("DROP " in s.upper() for m in MIGRATIONS for s in m.statements):
        problems.append("迁移不得包含 DROP")
    return problems