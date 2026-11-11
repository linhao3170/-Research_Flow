"""M06 · executor/templates/splits.py — SplitService 与 Split Manifest 六字段（P4 伪代码）。
阶段：P4「模板与证据链」｜追踪：FR-004（可复现划分）、FR-007（L3 校验 Split Manifest）、策划书 §9.3
依赖：M06 datasets_registry（dataset_hash 来源）、M01 encoding（JCS + SHA-256，端口注入）
不变量：六字段固定；manifest_hash 覆盖六字段；划分只由 (dataset, algorithm/version, seed, semantics) 决定；
        训练/测试索引不重叠且覆盖全行；L3 只重算不重抽样；不写 artifacts/、不写证据、不写状态
错误码：SCHEMA_INVALID（422，划分请求非法）；BUNDLE_TAMPERED（422，manifest/数据被改后校验失败）
写入者：**无**（纯计算；产物文件由模板写，worker 计算哈希）
状态：伪代码；sklearn 调用标 `# LIB:`，本文件不执行、不建环境、不跑测试

## 六字段（验收口径）

  1. `dataset_hash`          —— 原始数据文件**字节**的 SHA-256（二进制读，不做换行规范化）
  2. `split`                 —— `{algorithm, version, params}`，即 “split_algorithm/version”
  3. `seed`                  —— 划分随机种子；≥0 的 integer
  4. `row_id_hash`           —— 数据行 ID 序列的哈希；ID 方案见 §2
  5. `fold_assignment_hash`  —— 每行 → fold 的完整分配哈希；L3 重算后必须逐字节相同
  6. `semantics`             —— group/time 语义；T0 两个数据集均为 `none`，但必须显式写出

  `manifest_hash = sha256(JCS({六字段}))`。`schema_version` 与 `manifest_hash` 是信封字段，
  **不进入** 六字段前像；这样“六字段被覆盖”可以被单独断言，也不会因为信封加字段而改哈希语义。

## 为什么 fold 分配也要哈希

  只哈希数据集和种子，无法发现“划分代码被改但种子没变”或“某一行被挪到训练折”。
  `fold_assignment_hash` 把逐行分配钉死；L3 用同一 algorithm/version/seed 重算，
  任何一行不同都会得到不同哈希。哈希链/Merkle 只提高可发现性，不声称不可篡改。

## 不做什么

  - 不把 `metrics`、模型文件、环境指纹塞进 manifest；它们是别的证据。
  - 不在 L3 重新 `train_test_split` 后“看起来差不多”就通过；必须 exact 比对哈希。
  - 不支持 group+time 同时启用（T0 无此数据集）；出现即拒绝，不猜语义。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Mapping, Protocol, Sequence

__all__ = [
    "FOLD_TEST",
    "FOLD_TRAIN",
    "LOGICAL_MANIFEST_FIELDS",
    "MANIFEST_HASH_EXCLUDED",
    "SPLIT_MANIFEST_FIELDS",
    "DatasetView",
    "SplitBundle",
    "SplitContractError",
    "SplitManifest",
    "SplitSemantics",
    "SplitService",
    "SplitSpec",
    "SplitVerification",
    "SplitVerificationError",
    "SplitterPort",
    "build_row_ids",
    "compute_fold_assignment_hash",
    "compute_manifest_hash",
    "compute_row_id_hash",
]

FOLD_TRAIN: Final[int] = 0
FOLD_TEST: Final[int] = 1

# 六个**逻辑**字段，名称与策划书 §9.3 的六项逐字对应；物理 payload 见 `six_fields()`。
LOGICAL_MANIFEST_FIELDS: Final[tuple[str, ...]] = (
    "dataset_hash",
    "split_algorithm/version",
    "seed",
    "row_id_hash",
    "fold_assignment_hash",
    "group/time_semantics",
)

SPLIT_MANIFEST_FIELDS: Final[tuple[str, ...]] = (
    "dataset_hash",
    "split",
    "seed",
    "row_id_hash",
    "fold_assignment_hash",
    "semantics",
)

MANIFEST_HASH_EXCLUDED: Final[tuple[str, ...]] = ("schema_version", "manifest_hash")

ROW_ID_SCHEME: Final[str] = "dataset_id:index"
SUPPORTED_ALGORITHM: Final[str] = "stratified_holdout"
SUPPORTED_VERSION: Final[str] = "1.0"


class SplitAlgorithm(StrEnum):
    STRATIFIED_HOLDOUT = "stratified_holdout"


# ---------------------------------------------------------------------------
# 1. 错误与端口
# ---------------------------------------------------------------------------
class SplitContractError(ValueError):
    """划分请求/产物不合法。默认 422；校验历史 manifest 时可用 BUNDLE_TAMPERED。"""

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        field_path: str,
        error_code: str = "SCHEMA_INVALID",
    ) -> None:
        self.reason = reason
        self.field_path = field_path
        self.error_code = error_code
        self.http_status = 422
        super().__init__(f"{error_code}/{reason} @ {field_path}: {message}")


class SplitVerificationError(SplitContractError):
    """manifest 与数据/重算结果不一致：按证据包篡改处理（BUNDLE_TAMPERED）。"""

    def __init__(self, reason: str, message: str, *, field_path: str) -> None:
        super().__init__(reason, message, field_path=field_path, error_code="BUNDLE_TAMPERED")


class SplitterPort(Protocol):
    """划分算法端口；生产实现用 sklearn（版本必须进环境指纹/run_summary）。

    只返回索引，不返回掩码；索引必须已排序。所有随机性都来自 `seed`，
    端口实现不得再读全局 RNG 或系统时间。
    """

    def stratified_holdout(
        self,
        *,
        n_rows: int,
        labels: Sequence[object],
        test_size: float,
        seed: int,
    ) -> tuple[tuple[int, ...], tuple[int, ...]]:
        ...

    def group_holdout(
        self,
        *,
        n_rows: int,
        labels: Sequence[object],
        groups: Sequence[object],
        test_size: float,
        seed: int,
    ) -> tuple[tuple[int, ...], tuple[int, ...]]:
        ...

    def time_holdout(
        self,
        *,
        n_rows: int,
        times: Sequence[object],
        test_size: float,
    ) -> tuple[tuple[int, ...], tuple[int, ...]]:
        ...


class CanonicalizerPort(Protocol):
    """JCS 规范化端口（M01 唯一实现）。不得用 json.dumps(sort_keys=True) 替代。"""

    def canonical_bytes(self, value: object) -> bytes:
        ...


# ---------------------------------------------------------------------------
# 2. 输入视图与六字段
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class DatasetView:
    """划分所需的只读数据视图。

    `row_ids` 与 `labels` 必须等长、按原始文件数据行顺序；`row_ids` 不得重复。
    `groups`/`times` 只在 semantics 声明启用时提供；T0 两个数据集均为 None。
    """

    dataset_id: str
    dataset_hash: str
    row_ids: tuple[str, ...]
    labels: tuple[object, ...]
    groups: tuple[object, ...] | None = None
    times: tuple[object, ...] | None = None

    def __post_init__(self) -> None:
        if not self.dataset_id or not self.dataset_id.replace("_", "").isalnum():
            raise SplitContractError(
                "DATASET_ID_INVALID", "dataset_id 只允许字母/数字/下划线", field_path="dataset_id"
            )
        if len(self.dataset_hash) != 64 or any(c not in "0123456789abcdef" for c in self.dataset_hash):
            raise SplitContractError(
                "DATASET_HASH_INVALID", "dataset_hash 必须是 64 位小写十六进制", field_path="dataset_hash"
            )
        if not self.row_ids or len(self.row_ids) != len(self.labels):
            raise SplitContractError(
                "DATASET_SHAPE_INVALID", "row_ids 与 labels 必须非空且等长", field_path="row_ids"
            )
        prefix = f"{self.dataset_id}:"
        if not all(isinstance(rid, str) and rid.startswith(prefix) and rid[len(prefix):].isdigit()
                   for rid in self.row_ids):
            raise SplitContractError(
                "ROW_ID_SCHEME_INVALID",
                f"row_id 必须是 {prefix!r} + 十进制源行号（见 build_row_ids）",
                field_path="row_ids",
            )
        if len(set(self.row_ids)) != len(self.row_ids):
            raise SplitContractError(
                "ROW_ID_DUPLICATED", "row_id 不得重复", field_path="row_ids"
            )
        if self.groups is not None and len(self.groups) != len(self.row_ids):
            raise SplitContractError(
                "GROUP_SHAPE_INVALID", "groups 长度必须等于行数", field_path="semantics.group_key"
            )
        if self.times is not None and len(self.times) != len(self.row_ids):
            raise SplitContractError(
                "TIME_SHAPE_INVALID", "times 长度必须等于行数", field_path="semantics.time_key"
            )


@dataclass(frozen=True, slots=True)
class SplitSpec:
    """`split` 字段的内容：算法、版本、参数。

    `params.test_size` 进入 manifest；不在六字段之外另开顶层 `test_size`，
    避免“同一个值有两份、改一份就能骗过校验”。
    """

    algorithm: str
    version: str
    test_size: float
    stratify_on: str = "target"

    def __post_init__(self) -> None:
        if self.algorithm != SUPPORTED_ALGORITHM:
            raise SplitContractError(
                "SPLIT_ALGORITHM_UNSUPPORTED",
                f"只支持 {SUPPORTED_ALGORITHM!r}，实际 {self.algorithm!r}",
                field_path="split.algorithm",
            )
        if self.version != SUPPORTED_VERSION:
            raise SplitContractError(
                "SPLIT_VERSION_UNSUPPORTED",
                f"只支持版本 {SUPPORTED_VERSION!r}，实际 {self.version!r}",
                field_path="split.version",
            )
        if isinstance(self.test_size, bool) or not isinstance(self.test_size, (int, float)):
            raise SplitContractError(
                "TEST_SIZE_TYPE", "test_size 必须是 number", field_path="split.params.test_size"
            )
        if not (0.1 <= float(self.test_size) <= 0.5):
            raise SplitContractError(
                "TEST_SIZE_RANGE",
                f"test_size={self.test_size} 不在 [0.1, 0.5]（T0 模板收紧；TaskSpec 仍为 (0,1)）",
                field_path="split.params.test_size",
            )
        if self.stratify_on != "target":
            raise SplitContractError(
                "STRATIFY_UNSUPPORTED",
                "T0 只允许按 target 分层",
                field_path="split.params.stratify_on",
            )

    def as_payload(self) -> dict[str, object]:
        return {
            "algorithm": self.algorithm,
            "version": self.version,
            "params": {
                "test_size": float(self.test_size),
                "stratify_on": self.stratify_on,
            },
        }


@dataclass(frozen=True, slots=True)
class SplitSemantics:
    """group/time 语义。T0 必须显式写 `none`，不得省略。

    - `group_key=None` 且 `time_key=None`：普通分层 holdout；
    - 只启用 group：同一 group 不得跨 train/test（GroupShuffleSplit）；
    - 只启用 time：按 time 排序取尾部为 test，禁止 shuffle；
    - 两者同时启用：T0 拒绝（`GROUP_TIME_UNSUPPORTED`），不猜。
    """

    group_key: str | None = None
    time_key: str | None = None
    ordering: str = "row_index"
    notes: str = ""

    def __post_init__(self) -> None:
        if self.group_key is not None and self.time_key is not None:
            raise SplitContractError(
                "GROUP_TIME_UNSUPPORTED",
                "T0 不支持 group 与 time 同时启用",
                field_path="semantics",
            )
        if self.ordering not in ("row_index", "time_ascending"):
            raise SplitContractError(
                "ORDERING_UNSUPPORTED",
                f"ordering={self.ordering!r} 不支持",
                field_path="semantics.ordering",
            )
        if self.time_key is not None and self.ordering != "time_ascending":
            raise SplitContractError(
                "TIME_ORDERING_REQUIRED",
                "启用 time_key 时 ordering 必须是 time_ascending",
                field_path="semantics.ordering",
            )
        if self.time_key is None and self.ordering != "row_index":
            raise SplitContractError(
                "ROW_ORDERING_REQUIRED",
                "未启用 time_key 时 ordering 必须是 row_index",
                field_path="semantics.ordering",
            )

    @property
    def group_aware(self) -> bool:
        return self.group_key is not None

    @property
    def time_aware(self) -> bool:
        return self.time_key is not None

    def as_payload(self) -> dict[str, object]:
        return {
            "group_key": self.group_key,
            "time_key": self.time_key,
            "ordering": self.ordering,
            "group_aware": self.group_aware,
            "time_aware": self.time_aware,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class SplitManifest:
    """Split Manifest 的六字段 + 信封。

    `manifest_hash` 不由构造参数传入；由 `SplitService.build/verify` 计算后
    通过 `with_hash()` 生成，避免调用方自报哈希。
    """

    dataset_hash: str
    split: SplitSpec
    seed: int
    row_id_hash: str
    fold_assignment_hash: str
    semantics: SplitSemantics
    schema_version: str = "1.0"
    manifest_hash: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise SplitContractError(
                "SCHEMA_VERSION_UNSUPPORTED",
                "Split Manifest schema_version 只支持 1.0",
                field_path="schema_version",
            )
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise SplitContractError(
                "SEED_INVALID", "seed 必须是 ≥0 的 integer", field_path="seed"
            )
        for name in ("row_id_hash", "fold_assignment_hash"):
            value = getattr(self, name)
            if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise SplitContractError(
                    f"{name.upper()}_INVALID", f"{name} 必须是 64 位小写十六进制", field_path=name
                )

    def six_fields(self) -> dict[str, object]:
        """恰好六字段（物理 payload）；顺序固定，供 JCS/哈希与测试逐项断言。"""
        return {
            "dataset_hash": self.dataset_hash,
            "split": self.split.as_payload(),
            "seed": self.seed,
            "row_id_hash": self.row_id_hash,
            "fold_assignment_hash": self.fold_assignment_hash,
            "semantics": self.semantics.as_payload(),
        }

    def logical_view(self) -> dict[str, object]:
        """六个**逻辑**字段视图，键名与策划书 §9.3 逐字对应。

        只用于评审/断言，不参与 manifest_hash；哈希前像仍是 `six_fields()`。
        这样“六字段齐全”可以按用户词汇直接核对，而不必猜测嵌套结构。
        """
        return {
            "dataset_hash": self.dataset_hash,
            "split_algorithm/version": {
                "algorithm": self.split.algorithm,
                "version": self.split.version,
                "params": self.split.as_payload()["params"],
            },
            "seed": self.seed,
            "row_id_hash": self.row_id_hash,
            "fold_assignment_hash": self.fold_assignment_hash,
            "group/time_semantics": self.semantics.as_payload(),
        }

    def with_hash(self, canonicalizer: CanonicalizerPort) -> "SplitManifest":
        digest = compute_manifest_hash(self.six_fields(), canonicalizer)
        return SplitManifest(
            dataset_hash=self.dataset_hash,
            split=self.split,
            seed=self.seed,
            row_id_hash=self.row_id_hash,
            fold_assignment_hash=self.fold_assignment_hash,
            semantics=self.semantics,
            schema_version=self.schema_version,
            manifest_hash=digest,
        )


# ---------------------------------------------------------------------------
# 3. 哈希定义
# ---------------------------------------------------------------------------
def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_row_ids(dataset_id: str, n_rows: int) -> tuple[str, ...]:
    """生成稳定的行 ID：`<dataset_id>:<zero-based 源行号>`。

    不使用文件路径、不使用内容哈希：行 ID 必须在 CSV 重新导出后仍保持同一行对应；
    内容哈希会因列格式/换行变化而变，路径会泄露部署信息。
    """
    if not dataset_id or "/" in dataset_id or ":" in dataset_id:
        raise SplitContractError("DATASET_ID_INVALID", "dataset_id 形态非法", field_path="dataset_id")
    if isinstance(n_rows, bool) or not isinstance(n_rows, int) or n_rows < 1:
        raise SplitContractError("DATASET_ROWS_INVALID", "n_rows 必须 ≥1", field_path="n_rows")
    return tuple(f"{dataset_id}:{index}" for index in range(n_rows))


def compute_row_id_hash(
    row_ids: Sequence[str],
    canonicalizer: CanonicalizerPort,
) -> str:
    """`row_id_hash = sha256(JCS(row_ids))`，数组保持数据行顺序，不排序。

    为什么不用 sorted：数组顺序本身是“数据没有重排”的证据；排序会掩盖行序变化。
    规范化只走注入的 M01 实现；本文件不复制 JCS。
    """
    return _sha256_hex(canonicalizer.canonical_bytes(list(row_ids)))


def compute_fold_assignment_hash(
    row_ids: Sequence[str],
    folds: Sequence[int],
    canonicalizer: CanonicalizerPort,
) -> str:
    """`fold_assignment_hash = sha256(JCS([[row_id, fold], ...]))`，按数据行顺序。"""
    if len(row_ids) != len(folds):
        raise SplitContractError(
            "FOLD_SHAPE_INVALID", "row_ids 与 folds 长度不一致", field_path="fold_assignment_hash"
        )
    payload = [[row_id, int(fold)] for row_id, fold in zip(row_ids, folds)]
    return _sha256_hex(canonicalizer.canonical_bytes(payload))


def compute_manifest_hash(
    six_fields: Mapping[str, object],
    canonicalizer: CanonicalizerPort,
) -> str:
    """`manifest_hash = sha256(JCS(六字段))`；只接受恰好六字段的映射。"""
    if set(six_fields) != set(SPLIT_MANIFEST_FIELDS):
        raise SplitContractError(
            "MANIFEST_FIELDS_MISMATCH",
            f"manifest 必须恰好包含 {list(SPLIT_MANIFEST_FIELDS)}，实际 {sorted(six_fields)}",
            field_path="manifest_hash",
        )
    return _sha256_hex(canonicalizer.canonical_bytes(dict(six_fields)))


# ---------------------------------------------------------------------------
# 4. SplitService
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SplitBundle:
    """一次划分的结果：manifest + 索引。模板只能按这两个索引取数。"""

    manifest: SplitManifest
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]

    def __post_init__(self) -> None:
        if set(self.train_indices) & set(self.test_indices):
            raise SplitContractError(
                "TRAIN_TEST_OVERLAP", "train/test 索引不得重叠", field_path="fold_assignment_hash"
            )
        if not self.train_indices or not self.test_indices:
            raise SplitContractError(
                "EMPTY_SPLIT", "train/test 均不得为空", field_path="fold_assignment_hash"
            )


@dataclass(frozen=True, slots=True)
class SplitVerification:
    """校验结果。`ok=False` 时 `reason` 必须可断言，不能只返回 False。"""

    ok: bool
    checked: str
    reason: str = ""
    detail: str = ""
    expected: str = ""
    actual: str = ""


class SplitService:
    """生成与校验 Split Manifest。

    职责边界：
      - 只读数据视图；不读文件、不写文件、不碰数据库/证据；
      - 所有划分随机性来自 `seed`；不读全局 RNG；
      - `verify()` 必须重算 `fold_assignment_hash`，不是只比 manifest 自带的哈希。
    """

    def __init__(self, splitter: SplitterPort, canonicalizer: CanonicalizerPort) -> None:
        self._splitter = splitter
        self._canonicalizer = canonicalizer

    # -- 4.1 生成 ---------------------------------------------------------
    def build(
        self,
        dataset: DatasetView,
        spec: SplitSpec,
        semantics: SplitSemantics,
        seed: int,
    ) -> SplitBundle:
        """按 (dataset, spec, semantics, seed) 生成划分并计算六字段。

        步骤：
          1. 校验 dataset 形状、row_id 唯一、标签非空；
          2. 校验 semantics：T0 只允许 group/time 至多一个；数据必须提供对应列；
          3. 调 SplitterPort 得到 train/test 索引（分层；或 group/time 变体）；
          4. 断言：并集 = 全行、交集 = 空、每类在 train/test 都出现、test 比例在容差内；
          5. 生成 folds（train=0/test=1），计算 row_id_hash / fold_assignment_hash；
          6. 组装六字段并计算 manifest_hash（调用方不得自带哈希）。
        """
        if len(dataset.row_ids) != len(set(dataset.row_ids)):
            raise SplitContractError(
                "ROW_ID_DUPLICATED", "row_id 不得重复", field_path="row_ids"
            )
        if len(set(dataset.labels)) < 2:
            raise SplitContractError(
                "LABEL_SINGLE_CLASS", "标签必须至少两个类别", field_path="labels"
            )
        if semantics.group_aware and dataset.groups is None:
            raise SplitContractError(
                "GROUP_COLUMN_MISSING", "声明 group_key 但数据未提供 groups", field_path="semantics.group_key"
            )
        if semantics.time_aware and dataset.times is None:
            raise SplitContractError(
                "TIME_COLUMN_MISSING", "声明 time_key 但数据未提供 times", field_path="semantics.time_key"
            )

        n_rows = len(dataset.row_ids)
        if semantics.time_aware:
            train_idx, test_idx = self._splitter.time_holdout(
                n_rows=n_rows, times=dataset.times or (), test_size=float(spec.test_size)
            )
        elif semantics.group_aware:
            train_idx, test_idx = self._splitter.group_holdout(
                n_rows=n_rows,
                labels=dataset.labels,
                groups=dataset.groups or (),
                test_size=float(spec.test_size),
                seed=seed,
            )
        else:
            train_idx, test_idx = self._splitter.stratified_holdout(
                n_rows=n_rows,
                labels=dataset.labels,
                test_size=float(spec.test_size),
                seed=seed,
            )

        self._assert_partition(n_rows, train_idx, test_idx, dataset.labels, spec.test_size)
        if semantics.group_aware and dataset.groups is not None:
            self._assert_groups_disjoint(train_idx, test_idx, dataset.groups)
        if semantics.time_aware and dataset.times is not None:
            self._assert_time_order(train_idx, test_idx, dataset.times)

        test_set = set(test_idx)
        folds = [FOLD_TEST if i in test_set else FOLD_TRAIN for i in range(n_rows)]
        row_id_hash = compute_row_id_hash(dataset.row_ids, self._canonicalizer)
        fold_hash = compute_fold_assignment_hash(dataset.row_ids, folds, self._canonicalizer)
        manifest = SplitManifest(
            dataset_hash=dataset.dataset_hash,
            split=spec,
            seed=seed,
            row_id_hash=row_id_hash,
            fold_assignment_hash=fold_hash,
            semantics=semantics,
        ).with_hash(self._canonicalizer)
        return SplitBundle(
            manifest=manifest,
            train_indices=tuple(sorted(train_idx)),
            test_indices=tuple(sorted(test_idx)),
        )

    # -- 4.2 校验 ---------------------------------------------------------
    def verify(
        self,
        manifest: SplitManifest,
        dataset: DatasetView,
        *,
        expected_algorithm: str = SUPPORTED_ALGORITHM,
        expected_version: str = SUPPORTED_VERSION,
    ) -> SplitVerification:
        """重算六字段并逐项比对；任何不一致都 `ok=False` 且给出 reason。

        顺序固定（负例按顺序断言）：
          1. schema_version / 六字段集合；
          2. dataset_hash（与传入 dataset 的哈希）；
          3. split.algorithm/version/test_size 与期望一致；
          4. row_id_hash 重算；
          5. 用同 seed 重跑划分，重算 fold_assignment_hash；
          6. manifest_hash 重算。
        """
        if manifest.schema_version != "1.0":
            return SplitVerification(False, "schema_version", "SCHEMA_VERSION_UNSUPPORTED",
                                     actual=manifest.schema_version)
        if set(manifest.six_fields()) != set(SPLIT_MANIFEST_FIELDS):
            return SplitVerification(False, "six_fields", "MANIFEST_FIELDS_MISMATCH")
        if manifest.dataset_hash != dataset.dataset_hash:
            return SplitVerification(
                False, "dataset_hash", "DATASET_HASH_MISMATCH",
                expected=dataset.dataset_hash, actual=manifest.dataset_hash,
            )
        if manifest.split.algorithm != expected_algorithm:
            return SplitVerification(
                False, "split.algorithm", "SPLIT_ALGORITHM_UNSUPPORTED",
                expected=expected_algorithm, actual=manifest.split.algorithm,
            )
        if manifest.split.version != expected_version:
            return SplitVerification(
                False, "split.version", "SPLIT_VERSION_UNSUPPORTED",
                expected=expected_version, actual=manifest.split.version,
            )
        if compute_row_id_hash(dataset.row_ids, self._canonicalizer) != manifest.row_id_hash:
            return SplitVerification(
                False, "row_id_hash", "ROW_ID_HASH_MISMATCH",
                expected=compute_row_id_hash(dataset.row_ids, self._canonicalizer),
                actual=manifest.row_id_hash,
            )

        try:
            rebuilt = self.build(dataset, manifest.split, manifest.semantics, manifest.seed)
        except SplitContractError as exc:
            return SplitVerification(False, "recompute_assignment", exc.reason, detail=str(exc))
        if rebuilt.manifest.fold_assignment_hash != manifest.fold_assignment_hash:
            return SplitVerification(
                False, "fold_assignment_hash", "FOLD_ASSIGNMENT_HASH_MISMATCH",
                expected=rebuilt.manifest.fold_assignment_hash,
                actual=manifest.fold_assignment_hash,
            )
        if rebuilt.manifest.row_id_hash != manifest.row_id_hash:
            return SplitVerification(
                False, "row_id_hash", "ROW_ID_HASH_MISMATCH",
                expected=rebuilt.manifest.row_id_hash, actual=manifest.row_id_hash,
            )
        recomputed_manifest = compute_manifest_hash(manifest.six_fields(), self._canonicalizer)
        if recomputed_manifest != manifest.manifest_hash:
            return SplitVerification(
                False, "manifest_hash", "MANIFEST_HASH_MISMATCH",
                expected=recomputed_manifest, actual=manifest.manifest_hash,
            )
        return SplitVerification(True, "six_fields")

    def assert_valid(self, manifest: SplitManifest, dataset: DatasetView) -> None:
        """`verify()` 的抛异常版本；供 L3/模板在开始拟合前 fail-closed。"""
        result = self.verify(manifest, dataset)
        if not result.ok:
            raise SplitVerificationError(
                result.reason,
                f"{result.checked}: {result.detail or result.reason}",
                field_path=result.checked,
            )

    # -- 4.3 内部断言 -----------------------------------------------------
    @staticmethod
    def _assert_partition(
        n_rows: int,
        train_idx: Sequence[int],
        test_idx: Sequence[int],
        labels: Sequence[object],
        test_size: float,
    ) -> None:
        train = tuple(train_idx)
        test = tuple(test_idx)
        if len(set(train)) != len(train) or len(set(test)) != len(test):
            raise SplitContractError("INDEX_DUPLICATED", "索引重复", field_path="fold_assignment_hash")
        if set(train) & set(test):
            raise SplitContractError("TRAIN_TEST_OVERLAP", "train/test 重叠", field_path="fold_assignment_hash")
        if sorted(set(train) | set(test)) != list(range(n_rows)):
            raise SplitContractError(
                "PARTITION_INCOMPLETE", "索引未覆盖全部行", field_path="fold_assignment_hash"
            )
        if any(i < 0 or i >= n_rows for i in train + test):
            raise SplitContractError("INDEX_OUT_OF_RANGE", "索引越界", field_path="fold_assignment_hash")
        if not train or not test:
            raise SplitContractError("EMPTY_SPLIT", "train/test 不得为空", field_path="fold_assignment_hash")
        expected = n_rows * float(test_size)
        if abs(len(test) - expected) > max(1.0, expected * 0.1):
            raise SplitContractError(
                "TEST_SIZE_DEVIATION",
                f"test 行数 {len(test)} 偏离期望 {expected:.2f} 超过容差",
                field_path="split.params.test_size",
            )
        train_labels = {labels[i] for i in train}
        test_labels = {labels[i] for i in test}
        if set(labels) - train_labels or set(labels) - test_labels:
            raise SplitContractError(
                "STRATIFICATION_INCOMPLETE",
                "每个类别必须同时出现在 train 与 test（分层要求）",
                field_path="split.params.stratify_on",
            )

    @staticmethod
    def _assert_groups_disjoint(
        train_idx: Sequence[int],
        test_idx: Sequence[int],
        groups: Sequence[object],
    ) -> None:
        train_groups = {groups[i] for i in train_idx}
        test_groups = {groups[i] for i in test_idx}
        overlap = train_groups & test_groups
        if overlap:
            raise SplitContractError(
                "GROUP_LEAKAGE",
                f"group 同时出现在 train/test：{sorted(map(str, overlap))[:5]}",
                field_path="semantics.group_key",
            )

    @staticmethod
    def _assert_time_order(
        train_idx: Sequence[int],
        test_idx: Sequence[int],
        times: Sequence[object],
    ) -> None:
        if not train_idx or not test_idx:
            return
        max_train = max(times[i] for i in train_idx)  # type: ignore[type-var]
        min_test = min(times[i] for i in test_idx)    # type: ignore[type-var]
        if not (max_train <= min_test):
            raise SplitContractError(
                "TIME_LEAKAGE",
                "训练集时间不得晚于测试集（time holdout 必须按时间切尾）",
                field_path="semantics.time_key",
            )