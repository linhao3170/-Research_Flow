"""M03 · config/env_fingerprint.py — 环境指纹组成、合成与比较（P1 伪代码）。

阶段：P1｜状态：组成项、合成顺序、比较语义；不实现采集与哈希。

来源：策划书 §8.4（OS/架构/CPU、Python、依赖锁、关键库、线程变量、locale/timezone、
种子策略 → 环境变化即失效）、05 §6（证书 env_fingerprint 必须与 E2 记录一致）、
WP-01 证据 `docs/verification/t0/wp-01/env_fingerprint.json`、NFR-06/NFR-07。

**本模块最关键的一条**：
  任一侧缺少任一必需组成项时，`compare_env_fingerprint()` **必须返回 MISMATCH**
  （reason=MISSING_COMPONENT, equal=False），由 `same_env()` 返回 False、
  `assert_same_env()` 抛 ENV_FINGERPRINT_MISMATCH。
  **禁止**把缺项当成“未知所以跳过”，也禁止只在文档里写、代码里返回 True。

设计取舍（P1 约定，非 G0 冻结）：
  - 不把项目根目录、venv 路径、Python 可执行文件绝对路径计入指纹：
    同一台机器换目录做 L3 时，环境并未变化，计入路径会造成误判“不同环境”。
  - 计入 OS release/version：系统补丁变化视为环境变化（保守，宁严勿松）。
  - `PYTHONHASHSEED` 未设或为 random 时记为 "randomized"；比较结果为 MISMATCH，
    因为此时字符串哈希顺序不可复现（L3/DC 结论不成立）。
  - 新增组成项必须同时升 `COMPOSITION_VERSION`，否则新旧指纹可能碰撞。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping

__all__ = [
    "COMPONENTS",
    "COMPONENT_ORDER",
    "COMPOSITION_VERSION",
    "KEY_LIBS",
    "MISSING_COMPONENT_POLICY",
    "REQUIRED_COMPONENTS",
    "THREAD_ENV_VARS",
    "CompareResult",
    "ComponentSpec",
    "EnvComparison",
    "EnvFingerprint",
    "MismatchReason",
    "assert_same_env",
    "compare_env_fingerprint",
    "compute_env_fingerprint",
    "dc_reuse_allowed",
    "same_env",
]

COMPOSITION_VERSION: Final[str] = "p1-1"

KEY_LIBS: Final[tuple[str, ...]] = (
    "numpy",
    "scipy",
    "pandas",
    "scikit-learn",
    "pydantic",
    "fastapi",
    "starlette",
    "networkx",
    "cryptography",
)

THREAD_ENV_VARS: Final[tuple[str, ...]] = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    key: str
    collected_from: str
    example: str
    why: str
    volatility: str


# 顺序即合成顺序：固定、不可由调用方重排。
COMPONENT_ORDER: Final[tuple[str, ...]] = (
    "os",
    "arch",
    "cpu",
    "python",
    "deps_lock",
    "key_libs",
    "threads",
    "locale_tz",
    "seed_policy",
)

COMPONENTS: Final[Mapping[str, ComponentSpec]] = MappingProxyType(
    {
        "os": ComponentSpec(
            key="os",
            collected_from="platform.system() / platform.release() / platform.version()",
            example="Windows|11|10.0.26100",
            why="系统版本变化可能改变调度、文件系统与数值库行为",
            volatility="低（补丁级变化即视为环境变化）",
        ),
        "arch": ComponentSpec(
            key="arch",
            collected_from="platform.machine() + platform.architecture()[0]",
            example="AMD64|64bit",
            why="32/64 位与指令集差异直接改变数值结果",
            volatility="极低",
        ),
        "cpu": ComponentSpec(
            key="cpu",
            collected_from="platform.processor() 或 platform.machine() + os.cpu_count()",
            example="Intel64 Family 6 Model 154|16",
            why="CPU 型号/核数影响浮点归约顺序与线程调度",
            volatility="低（换机/改核数即变化）",
        ),
        "python": ComponentSpec(
            key="python",
            collected_from="sys.version + platform.python_implementation() + platform.python_compiler()",
            example="3.11.16 (main, ...) [MSC v.1944 64 bit (AMD64)]|CPython|MSC v.1944",
            why="解释器版本与编译器决定字节码与浮点行为；**不含可执行文件路径**",
            volatility="低",
        ),
        "deps_lock": ComponentSpec(
            key="deps_lock",
            collected_from="requirements.lock 的 sha256（二进制读取）+ 包数",
            example="<64-hex>|58",
            why="依赖漂移是 L3 不可复现的首要原因",
            volatility="低（改锁文件即变化）",
        ),
        "key_libs": ComponentSpec(
            key="key_libs",
            collected_from=f"importlib.metadata.version(name)，固定集合 {KEY_LIBS}",
            example="numpy==2.0.2|pandas==2.2.3|…",
            why="锁文件哈希之外再钉关键数值库，防“锁文件没改但环境被手装覆盖”",
            volatility="低",
        ),
        "threads": ComponentSpec(
            key="threads",
            collected_from=f"环境变量 {THREAD_ENV_VARS} 的字面值；未设为 \"<unset>\"",
            example="OMP_NUM_THREADS=1|OPENBLAS_NUM_THREADS=<unset>|…",
            why="线程数改变 BLAS 归约顺序，可在 bit-exact 上产生差异",
            volatility="低（但常被临时 export 改掉）",
        ),
        "locale_tz": ComponentSpec(
            key="locale_tz",
            collected_from="locale.getpreferredencoding(False) + LANG/LC_ALL + TZ",
            example="UTF-8|LANG=<unset>|LC_ALL=<unset>|TZ=<unset>",
            why="排序、大小写与时间格式化会随 locale/TZ 漂移（时间本身仍强制 UTC）",
            volatility="低",
        ),
        "seed_policy": ComponentSpec(
            key="seed_policy",
            collected_from="configs/experiment.yaml: seed_policy + PYTHONHASHSEED",
            example="explicit_per_task|PYTHONHASHSEED=0",
            why="种子策略与哈希随机化决定“同输入是否真能重放”",
            volatility="低；但未设 PYTHONHASHSEED 时记为 randomized",
        ),
    }
)

REQUIRED_COMPONENTS: Final[frozenset[str]] = frozenset(COMPONENT_ORDER)

# 机器可读的硬规则：缺项不是“未知”，是不一致。
# compare_env_fingerprint() 必须返回 CompareResult.MISMATCH + MismatchReason.MISSING_COMPONENT；
# 任何把缺项当 MATCH / 跳过 / None 的实现都与本常量冲突，负例 NEG-M03-11 锁定。
MISSING_COMPONENT_POLICY: Final[str] = "MISMATCH"


class MismatchReason(StrEnum):
    MISSING_COMPONENT = "MISSING_COMPONENT"
    VALUE_DIFF = "VALUE_DIFF"
    NON_DETERMINISTIC_HASH_SEED = "NON_DETERMINISTIC_HASH_SEED"
    DIGEST_DIFF = "DIGEST_DIFF"
    UNKNOWN = "UNKNOWN"


class CompareResult(StrEnum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"


@dataclass(frozen=True, slots=True)
class EnvFingerprint:
    """一次采集的结果；components 必须恰好包含 COMPONENT_ORDER 的键。"""

    composition_version: str
    components: Mapping[str, str]
    digest: str                  # sha256(canonical_bytes({...}))，64 位小写十六进制
    captured_at: str             # UTC RFC3339（本项目写法：微秒 + Z）


@dataclass(frozen=True, slots=True)
class EnvComparison:
    status: CompareResult
    reason: MismatchReason | None
    equal: bool
    missing: tuple[str, ...]
    differing: tuple[str, ...]
    note: str


def compute_env_fingerprint(*, seed_policy: str) -> EnvFingerprint:
    """采集九项 → 固定顺序合成 → JCS → sha256。

    规则：
      1. 按 COMPONENT_ORDER 组装 {"composition_version": ..., "components": {...}}；
         键顺序由 JCS 决定，**不依赖** dict 插入顺序。
      2. `digest = sha256(canonical_bytes(payload)).hexdigest()`（小写十六进制）。
      3. 任一组成项采集失败/为空 → 抛 ENV_FINGERPRINT_INCOMPLETE；
         **不得**跳过该项后继续（少一项的指纹不得传给证书）。
      4. `seed_policy` 必填且来自 experiment.yaml；不得在此处给默认值。
      5. 本函数不得读取私钥、token、数据集内容。
    """
    raise NotImplementedError("P1 伪代码：采集属 M03 落地阶段")


def compare_env_fingerprint(left: EnvFingerprint, right: EnvFingerprint) -> EnvComparison:
    """比较两个指纹。**缺项必须判不一致**——这是本函数的契约，不是建议。

    判定顺序：
      1. 任一侧 components 的键集合 ≠ REQUIRED_COMPONENTS，或任一值为空串
         → status=MISMATCH, reason=MISSING_COMPONENT, equal=False,
           missing=(缺失键…), note 指出“缺项按不一致处理，不得跳过”。
      2. 任一侧 seed_policy 中 PYTHONHASHSEED 为 randomized
         → MISMATCH, reason=NON_DETERMINISTIC_HASH_SEED, equal=False。
      3. 任一组成项值不同 → MISMATCH, reason=VALUE_DIFF, differing=(…), equal=False。
      4. 组成项全同但 digest 不同 → MISMATCH, reason=DIGEST_DIFF（合成版本漂移/碰撞防御）。
      5. digest 相同但组成项不同 → MISMATCH（同上，防御性）。
      6. 其余 → MATCH, equal=True, reason=None。
    任何分支都不得返回“未知/None 当相等”。
    """
    raise NotImplementedError("P1 伪代码：比较属 M03 落地阶段")


def same_env(left: EnvFingerprint, right: EnvFingerprint) -> bool:
    """`compare_env_fingerprint(...).equal` 的唯一入口；不得自行实现第二套比较。"""
    raise NotImplementedError("P1 伪代码：same_env 委托 compare_env_fingerprint")


def assert_same_env(left: EnvFingerprint, right: EnvFingerprint) -> None:
    """不一致时抛 ENV_FINGERPRINT_MISMATCH（409），并带上 missing/differing。

    证书签发、E2 绑定校验、L3 重跑前都必须走这里；不得只比较 digest 字符串
    （digest 相同但组成项缺失的情况虽然少见，仍必须按不一致处理）。
    """
    raise NotImplementedError("P1 伪代码：签发入口的断言属 M03/Verifier 落地阶段")


def dc_reuse_allowed(
    comparison: EnvComparison,
    *,
    ruleset_equal: bool,
    inputs_equal: bool,
) -> bool:
    """T2 占位：环境不一致时 DC 复用必须失效。

    规则：仅当 comparison.equal 为 True、ruleset_equal 与 inputs_equal 均为 True 时返回 True；
    否则 False。本函数**不定义** DC 契约字段（OQ-CT-07 同批），只表达“环境变化即失效”。
    """
    raise NotImplementedError("P1 伪代码：DC 资格判定属 T2")