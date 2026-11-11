"""M06 · data/datasets_registry.py — 离线数据集登记、锁文件与绑定（P4 伪代码）。
阶段：P4「模板与证据链」｜追踪：FR-004（内置数据）、NFR-01（离线）、NFR-08（许可）、策划书 §14.1
依赖：M01 parsing（严格 JSON，端口注入）、M01 encoding（SHA-256 只引用算法）、tools/requirements.lock
不变量：未登记数据集一律拒绝；网络 URI/绝对路径/`..` 一律拒绝；dataset_hash 以锁文件 + 任务引用双重比对；
        文件名与大小在复制前后各校验一次；模板只读 `inputs/` 内的绑定副本
错误码：SCHEMA_INVALID（422，未登记/哈希不符/路径逃逸/许可不符）；RESOURCE_BUDGET_EXCEEDED（429，仅磁盘配额层）
写入者：**Worker/DatasetBinder** 写 `inputs/dataset.csv` 与 `inputs/dataset_binding.json`；
        模板只读；本文件不写证据、不写状态、不联网
状态：伪代码；真实 SHA-256 与文件不在本阶段生成（PHASE_RULES §5：不写真实哈希）；锁文件由 WP-05 固化

## 为什么用锁文件，而不是把哈希写死在这里

  本阶段禁止写真实哈希值；把占位哈希写进代码又会制造“看起来已登记”的假象。
  因此：静态表只登记**来源/许可/版本/路径/形状**；真实 `sha256` 与 `size_bytes`
  来自 WP-05 生成的 `datasets.lock.json`，并在每次解析/绑定时与文件字节复核。
  锁文件缺项、路径被改、哈希不符 → 拒绝，不取默认值、不回退到“同名文件”。

## 三道比对（缺一不可）

  1. `TaskSpec.dataset_ref.uri` 必须解析到已登记 `dataset_id`；
  2. `dataset_ref.sha256` 必须等于锁文件哈希（任务创建时绑定的信任锚）；
  3. 锁文件哈希必须等于离线文件字节哈希（读取时重算）。
  只满足 1/2 不满足 3 = 文件被换；只满足 1/3 不满足 2 = 任务引用了另一个版本。

## 许可与来源

  Wine 与 Breast Cancer Wisconsin (Diagnostic) 均来自 UCI Machine Learning Repository，
  UCI 数据集页面标注 CC BY 4.0。离线副本计划由 WP-05 从 scikit-learn 1.9.1 自带 CSV 导出，
  并随数据归档许可证文本与来源页快照。`source_url` 只是元数据，**没有任何下载函数**。
  【待核实】UCI 数据集修订号未单列；以归档文件的 SHA-256 作为版本事实源。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final, Mapping, Protocol, Sequence

__all__ = [
    "ALLOWED_LICENSE_IDS",
    "DATASET_SPECS",
    "DatasetBinder",
    "DatasetBinding",
    "DatasetRecord",
    "DatasetRegistry",
    "DatasetRegistryError",
    "DatasetSpec",
    "StrictJsonPort",
    "assert_dataset_boundary",
    "load_lock",
]

ALLOWED_LICENSE_IDS: Final[tuple[str, ...]] = ("CC-BY-4.0",)

# 来源页仅作元数据；T0 断网，任何下载/抓取函数都不得存在。
FORBIDDEN_DATASET_ATTRS: Final[tuple[str, ...]] = (
    "socket", "requests", "urllib", "http", "httpx", "aiohttp",
    "urlopen", "download", "fetch", "wget", "curl",
)

MAX_DATASET_BYTES: Final[int] = 64 * 1024 * 1024


class StrictJsonPort(Protocol):
    """M01 `parsing.loads_strict` 端口：重复键/NaN/Infinity/非法编码必须拒绝。"""

    def loads_strict(self, data: bytes) -> object:
        ...


# ---------------------------------------------------------------------------
# 1. 静态登记（无真实哈希）
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class DatasetSpec:
    """数据集静态元数据；`sha256` 不在此处，必须从锁文件来。"""

    dataset_id: str
    display_name: str
    source_kind: str
    source_url: str
    license_id: str
    license_url: str
    dataset_version: str
    offline_relative_path: str
    n_rows: int
    n_features: int
    n_classes: int
    target_column: str
    task_kind: str
    provenance_note: str = ""

    def __post_init__(self) -> None:
        if not self.dataset_id or not self.dataset_id.replace("_", "").isalnum():
            raise ValueError("dataset_id 只允许字母/数字/下划线")
        if self.license_id not in ALLOWED_LICENSE_IDS:
            raise ValueError(f"未批准的许可证 {self.license_id!r}")
        rel = self.offline_relative_path.replace("\\", "/")
        if rel.startswith("/") or ".." in rel.split("/") or ":" in rel:
            raise ValueError(f"离线路径必须是无逃逸的相对 POSIX 路径：{rel!r}")
        if self.n_rows < 1 or self.n_features < 1 or self.n_classes < 2:
            raise ValueError("数据集形状必须为正，类别数 ≥2")
        if not self.target_column or "/" in self.target_column:
            raise ValueError("target_column 非法")


DATASET_SPECS: Final[Mapping[str, DatasetSpec]] = MappingProxyType({
    "wine": DatasetSpec(
        dataset_id="wine",
        display_name="Wine (UCI)",
        source_kind="uci",
        source_url="https://archive.ics.uci.edu/dataset/109/wine",
        license_id="CC-BY-4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        dataset_version="uci-wine-1",
        offline_relative_path="wine/wine.csv",
        n_rows=178,
        n_features=13,
        n_classes=3,
        target_column="target",
        task_kind="smoke",
        provenance_note="UCI Wine；WP-05 从 scikit-learn 1.9.1 自带 CSV 导出；UCI 修订号[待核实]",
    ),
    "breast_cancer": DatasetSpec(
        dataset_id="breast_cancer",
        display_name="Breast Cancer Wisconsin (Diagnostic)",
        source_kind="uci",
        source_url="https://archive.ics.uci.edu/dataset/17/breast+cancer+wisconsin+diagnostic",
        license_id="CC-BY-4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        dataset_version="uci-bcw-diagnostic-1",
        offline_relative_path="breast_cancer/breast_cancer.csv",
        n_rows=569,
        n_features=30,
        n_classes=2,
        target_column="target",
        task_kind="main",
        provenance_note="UCI BCW-Diagnostic；WP-05 从 scikit-learn 1.9.1 自带 CSV 导出；UCI 修订号[待核实]",
    ),
})


# ---------------------------------------------------------------------------
# 2. 锁文件与记录
# ---------------------------------------------------------------------------
class DatasetRegistryError(ValueError):
    """数据集拒绝。对外统一 SCHEMA_INVALID(422)；内部 reason 必须可断言。"""

    error_code: Final[str] = "SCHEMA_INVALID"
    http_status: Final[int] = 422

    def __init__(self, reason: str, message: str, *, field_path: str) -> None:
        self.reason = reason
        self.field_path = field_path
        super().__init__(f"{self.error_code}/{reason} @ {field_path}: {message}")


@dataclass(frozen=True, slots=True)
class DatasetRecord:
    """静态元数据 + 锁文件事实。`offline_path` 是部署根内的绝对路径，不对外输出。"""

    spec: DatasetSpec
    sha256: str
    size_bytes: int
    offline_path: Path

    def __post_init__(self) -> None:
        if len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256):
            raise DatasetRegistryError(
                "LOCK_HASH_INVALID", "锁文件 sha256 必须是 64 位小写十六进制", field_path="datasets.sha256"
            )
        if self.size_bytes < 1 or self.size_bytes > MAX_DATASET_BYTES:
            raise DatasetRegistryError(
                "LOCK_SIZE_INVALID", "size_bytes 不在允许范围", field_path="datasets.size_bytes"
            )
        if not self.offline_path.is_absolute():
            raise DatasetRegistryError(
                "DATASET_PATH_ESCAPE", "offline_path 必须是绝对路径", field_path="offline_relative_path"
            )

    @property
    def dataset_id(self) -> str:
        return self.spec.dataset_id


@dataclass(frozen=True, slots=True)
class DatasetBinding:
    """写入 attempt `inputs/` 的绑定清单；模板只认这个清单，不认外部路径。"""

    dataset_id: str
    dataset_hash: str
    size_bytes: int
    license_id: str
    relative_path: str
    rows: int

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "dataset_id": self.dataset_id,
            "dataset_hash": self.dataset_hash,
            "size_bytes": self.size_bytes,
            "license_id": self.license_id,
            "relative_path": self.relative_path,
            "rows": self.rows,
        }


def load_lock(
    data: bytes,
    strict_json: StrictJsonPort,
) -> Mapping[str, Mapping[str, object]]:
    """解析并校验锁文件形状；未知数据集/缺项/路径改写在构造 Registry 时再拒。

    锁文件不是“信任根”：任务创建时写入的 `dataset_ref.sha256` 才是该任务的锚。
    锁文件的作用是把“登记事实”与代码解耦，并允许 WP-05 在不改代码的情况下固化版本。
    """
    obj = strict_json.loads_strict(data)
    if not isinstance(obj, dict):
        raise DatasetRegistryError("LOCK_SHAPE_INVALID", "锁文件顶层必须是对象", field_path="$")
    if obj.get("schema_version") != "1.0":
        raise DatasetRegistryError(
            "LOCK_VERSION_UNSUPPORTED", "锁文件 schema_version 只支持 1.0", field_path="schema_version"
        )
    datasets = obj.get("datasets")
    if not isinstance(datasets, dict) or not datasets:
        raise DatasetRegistryError("LOCK_INCOMPLETE", "锁文件缺少 datasets", field_path="datasets")
    out: dict[str, Mapping[str, object]] = {}
    for key, value in datasets.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise DatasetRegistryError("LOCK_SHAPE_INVALID", "datasets 项形态非法", field_path="datasets")
        out[key] = MappingProxyType(dict(value))
    return MappingProxyType(out)


# ---------------------------------------------------------------------------
# 3. 注册表
# ---------------------------------------------------------------------------
class DatasetRegistry:
    """已登记数据集的只读注册表；构造即 fail-closed。

    构造检查：
      1. 根目录绝对、存在、`realpath` 不改变（根不得是链接）；
      2. 锁项集合 == `DATASET_SPECS` 键集合（缺项/多项都拒绝）；
      3. 每项 sha256/size 形态合法，`offline_relative_path` 与静态表一致；
      4. 解析后的路径在根内、不是符号链接、文件存在、大小一致。
    读取时 `read_verified()` 再重算哈希；不缓存“已验证”事实。
    """

    def __init__(
        self,
        root: Path,
        lock: Mapping[str, Mapping[str, object]],
        *,
        allowed_licenses: Sequence[str] = ALLOWED_LICENSE_IDS,
    ) -> None:
        if not root.is_absolute():
            raise DatasetRegistryError("DATASET_ROOT_NOT_ABSOLUTE", "数据根必须是绝对路径", field_path="root")
        if not root.exists() or not root.is_dir():
            raise DatasetRegistryError("DATASET_ROOT_MISSING", "数据根不存在或不是目录", field_path="root")
        real_root = Path(os.path.realpath(root))
        if os.path.normcase(str(real_root)) != os.path.normcase(str(root)):
            raise DatasetRegistryError("DATASET_ROOT_LINKED", "数据根不得是符号链接/联接", field_path="root")

        if set(lock) != set(DATASET_SPECS):
            missing = sorted(set(DATASET_SPECS) - set(lock))
            extra = sorted(set(lock) - set(DATASET_SPECS))
            raise DatasetRegistryError(
                "LOCK_DATASET_SET_MISMATCH",
                f"锁文件数据集集合与登记表不一致；缺 {missing}，多 {extra}",
                field_path="datasets",
            )

        records: dict[str, DatasetRecord] = {}
        for dataset_id, spec in DATASET_SPECS.items():
            entry = lock[dataset_id]
            sha256 = entry.get("sha256")
            size_bytes = entry.get("size_bytes")
            rel = entry.get("offline_relative_path")
            if not isinstance(sha256, str) or len(sha256) != 64 or any(
                c not in "0123456789abcdef" for c in sha256
            ):
                raise DatasetRegistryError(
                    "LOCK_HASH_INVALID", f"{dataset_id}: sha256 形态非法", field_path=f"datasets.{dataset_id}.sha256"
                )
            if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 1:
                raise DatasetRegistryError(
                    "LOCK_SIZE_INVALID", f"{dataset_id}: size_bytes 非法", field_path=f"datasets.{dataset_id}.size_bytes"
                )
            if rel != spec.offline_relative_path:
                raise DatasetRegistryError(
                    "LOCK_PATH_MISMATCH",
                    f"{dataset_id}: 锁文件路径 {rel!r} 与登记 {spec.offline_relative_path!r} 不一致",
                    field_path=f"datasets.{dataset_id}.offline_relative_path",
                )
            if spec.license_id not in allowed_licenses:
                raise DatasetRegistryError(
                    "DATASET_LICENSE_NOT_ALLOWED",
                    f"{dataset_id}: 许可证 {spec.license_id!r} 未批准",
                    field_path=f"datasets.{dataset_id}.license_id",
                )
            path = self._resolve_inside(real_root, spec.offline_relative_path)
            if path.is_symlink() or not path.is_file():
                raise DatasetRegistryError(
                    "DATASET_FILE_MISSING", f"{dataset_id}: 离线文件不存在或为链接", field_path="offline_relative_path"
                )
            if path.stat().st_size != size_bytes:
                raise DatasetRegistryError(
                    "DATASET_SIZE_MISMATCH",
                    f"{dataset_id}: 文件大小 {path.stat().st_size} != 锁 {size_bytes}",
                    field_path="size_bytes",
                )
            records[dataset_id] = DatasetRecord(
                spec=spec, sha256=sha256, size_bytes=size_bytes, offline_path=path
            )
        self._records = MappingProxyType(records)

    @staticmethod
    def _resolve_inside(root: Path, relative: str) -> Path:
        candidate = (root / Path(relative)).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise DatasetRegistryError(
                "DATASET_PATH_ESCAPE", f"路径逃逸数据根：{relative!r}", field_path="offline_relative_path"
            ) from exc
        return candidate

    # -- 3.1 查询 ---------------------------------------------------------
    def get(self, dataset_id: str) -> DatasetRecord:
        if not isinstance(dataset_id, str) or dataset_id not in self._records:
            raise DatasetRegistryError(
                "DATASET_NOT_REGISTERED",
                f"未登记数据集 {dataset_id!r}；白名单 {sorted(self._records)}",
                field_path="dataset_ref.uri",
            )
        return self._records[dataset_id]

    def require_dataset_ref(self, uri: str, sha256: str, license_id: str) -> DatasetRecord:
        """把 `TaskSpec.dataset_ref` 解析成记录；三道比对在这里一次做完。"""
        dataset_id = self._parse_local_uri(uri)
        record = self.get(dataset_id)
        if not isinstance(sha256, str) or sha256 != record.sha256:
            raise DatasetRegistryError(
                "DATASET_HASH_MISMATCH",
                f"{dataset_id}: 任务引用哈希与登记不一致",
                field_path="dataset_ref.sha256",
            )
        if license_id != record.spec.license_id:
            raise DatasetRegistryError(
                "DATASET_LICENSE_MISMATCH",
                f"{dataset_id}: 任务引用许可证 {license_id!r} != 登记 {record.spec.license_id!r}",
                field_path="dataset_ref.license",
            )
        return record

    @staticmethod
    def _parse_local_uri(uri: str) -> str:
        if not isinstance(uri, str):
            raise DatasetRegistryError("DATASET_URI_INVALID", "uri 必须是字符串", field_path="dataset_ref.uri")
        prefix = "local://datasets/"
        if not uri.startswith(prefix):
            raise DatasetRegistryError(
                "DATASET_URI_NOT_LOCAL",
                f"只接受 {prefix}<dataset_id>；网络/绝对路径/相对路径一律拒绝",
                field_path="dataset_ref.uri",
            )
        dataset_id = uri[len(prefix):]
        if (not dataset_id or "/" in dataset_id or "\\" in dataset_id or ".." in dataset_id
                or ":" in dataset_id or "?" in dataset_id or "#" in dataset_id):
            raise DatasetRegistryError(
                "DATASET_URI_INVALID", f"dataset_id 形态非法：{dataset_id!r}", field_path="dataset_ref.uri"
            )
        return dataset_id

    # -- 3.2 读取校验 -----------------------------------------------------
    def read_verified(self, record: DatasetRecord) -> bytes:
        """二进制读并重算哈希；任何不符都拒绝，不返回近似内容。"""
        data = record.offline_path.read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if actual != record.sha256:
            raise DatasetRegistryError(
                "DATASET_HASH_MISMATCH",
                f"{record.dataset_id}: 文件字节哈希与锁文件不一致",
                field_path="dataset_ref.sha256",
            )
        if len(data) != record.size_bytes:
            raise DatasetRegistryError(
                "DATASET_SIZE_MISMATCH",
                f"{record.dataset_id}: 读取字节数 {len(data)} != 锁 {record.size_bytes}",
                field_path="size_bytes",
            )
        return data


# ---------------------------------------------------------------------------
# 4. 绑定到 attempt inputs/
# ---------------------------------------------------------------------------
class DatasetBinder:
    """把已登记数据集复制成 attempt 的只读输入。

    这是 M05 `worker.run_attempt` 的集成点（P4 只定义，不改 P3）：
      在写 `inputs/params.json` 之后、提交 `executor_launch` 之前调用 `bind()`。
      绑定失败 → `PRECHECK_FAILED`，不得启动子进程（否则模板会自己去找数据）。

    绑定文件 `inputs/dataset_binding.json` 是模板唯一的数据来源声明；
    模板不得读注册表根、不得读绝对路径、不得联网。
    """

    BINDING_NAME: Final[str] = "dataset_binding.json"
    DATA_NAME: Final[str] = "dataset.csv"

    def bind(
        self,
        inputs_dir: Path,
        record: DatasetRecord,
        registry: DatasetRegistry,
    ) -> DatasetBinding:
        """原子复制 + 双次哈希 + 写绑定清单。

        步骤：
          1. `inputs_dir` 必须是已存在目录，且 `realpath` 在 attempt 内（调用方保证）；
          2. 目标文件不得已存在（不覆盖，避免第二次绑定掩盖第一次）；
          3. 二进制读源文件 → 校验哈希/大小 → 写临时文件 → fsync → `os.replace`；
          4. 从目标文件重新读一遍、重算哈希（防止复制中途被替换/截断）；
          5. 原子写 `dataset_binding.json`（UTF-8 无 BOM，键排序）；
          6. 返回 Binding；任一步失败都删除临时文件，不留下“半个数据集”。
        """
        if not inputs_dir.is_dir():
            raise DatasetRegistryError(
                "INPUTS_DIR_MISSING", "inputs/ 目录不存在", field_path="inputs"
            )
        target = inputs_dir / self.DATA_NAME
        binding_path = inputs_dir / self.BINDING_NAME
        if target.exists() or binding_path.exists():
            raise DatasetRegistryError(
                "DATASET_BINDING_EXISTS",
                "dataset.csv / dataset_binding.json 已存在；不得覆盖",
                field_path="inputs.dataset.csv",
            )
        data = registry.read_verified(record)
        tmp_fd, tmp_name = tempfile.mkstemp(prefix=".dataset-", dir=inputs_dir)
        try:
            with os.fdopen(tmp_fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            copied = Path(tmp_name).read_bytes()
            if hashlib.sha256(copied).hexdigest() != record.sha256:
                raise DatasetRegistryError(
                    "DATASET_COPY_HASH_MISMATCH",
                    "复制后哈希与源不一致（磁盘/并发问题）",
                    field_path="inputs.dataset.csv",
                )
            os.replace(tmp_name, target)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        binding = DatasetBinding(
            dataset_id=record.dataset_id,
            dataset_hash=record.sha256,
            size_bytes=record.size_bytes,
            license_id=record.spec.license_id,
            relative_path=f"inputs/{self.DATA_NAME}",
            rows=record.spec.n_rows,
        )
        payload = json.dumps(binding.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        tmp_fd, tmp_name = tempfile.mkstemp(prefix=".binding-", dir=inputs_dir)
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, binding_path)
        except BaseException:
            # 绑定清单写失败时，已复制的 dataset.csv 也必须清掉，避免“半个数据集”。
            if target.exists():
                target.unlink()
            raise
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        return binding


# ---------------------------------------------------------------------------
# 5. 静态边界
# ---------------------------------------------------------------------------
def assert_dataset_boundary() -> list[str]:
    """检查本模块没有下载入口、没有把静态表变成任意路径读取。"""
    problems: list[str] = []
    import sys

    module = sys.modules[__name__]
    for attr in FORBIDDEN_DATASET_ATTRS:
        if hasattr(module, attr):
            problems.append(f"模块暴露禁用名 {attr!r}（T0 断网/禁止下载）")
    for key, spec in DATASET_SPECS.items():
        if not spec.source_url.startswith("https://archive.ics.uci.edu/"):
            problems.append(f"{key}: source_url 不是已登记的 UCI 页面")
        if spec.license_id not in ALLOWED_LICENSE_IDS:
            problems.append(f"{key}: 许可证未批准")
        if ".." in spec.offline_relative_path.split("/"):
            problems.append(f"{key}: 离线路径含 ..")
    return problems