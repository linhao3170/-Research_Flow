# M03 · NEGATIVE_TESTS — 负例判据（P1）

> 阶段：P1｜状态：**判据定义，未执行**（本阶段限权：不建环境、不跑测试）
> 执行阶段：M03 落地（配置加载器与观测层实现之后）
> 解释器（届时必须）：`C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe`
> 记录要求：命令、解释器、退出码、日志路径、运行时间；**P1 不得写成“已通过”**。

## 0. 判定纪律

1. 每条负例必须断言**拒绝原因**：错误码 + `field_path` / 异常类 / `reason` 中至少两项与下表一致。
2. “进程没启动”不够：必须同时断言退出码 2、端口未监听、审计/日志里出现对应 `error_code`。
3. 原因不符即失败；不得改配置样本或放宽阈值来“通过”。
4. 正例通过不构成完成证据；本表 18 条必须真实执行。

## A. 配置拒绝启动（8 条）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M03-01 | 缺键不取默认 | `gates.yaml` 删除 `ruleset_hash` | `CONFIG_MISSING_KEY`，`field_path == "ruleset_hash"`，退出码 2，端口未监听 | M03 硬规则 1 |
| NEG-M03-02 | 缺文件不取默认 | 删除 `configs/security.yaml` | `CONFIG_MISSING_KEY`，`filename == "security.yaml"`；不得用内置默认安全配置继续启动 | 同上 |
| NEG-M03-03 | 未知键拒绝 | `agents.yaml` 增加 `roles: []` | `CONFIG_UNKNOWN_KEY`，`field_path == "roles"`（T1 字段不得提前混入 T0） | schemas.py；FR-012 属 T1 |
| NEG-M03-04 | 不做类型强转 | `limits.yaml: max_workers: "2"`（字符串） | `CONFIG_TYPE_INVALID`，`field_path == "max_workers"`；**不得**当成 2 接受 | schemas.py 规则 3 |
| NEG-M03-05 | `null` 不是缺键 | `limits.yaml: max_memory_mb_per_worker: null` | `CONFIG_TYPE_INVALID`（不是 `CONFIG_MISSING_KEY`），`field_path` 精确到该键 | schemas.py 规则 4 |
| NEG-M03-06 | 硬上限 | `limits.yaml: max_workers: 3` | `CONFIG_VALUE_OUT_OF_RANGE`，`field_path == "max_workers"`；不得运行期再拦 | 05 §2.1；NFR-06 |
| NEG-M03-07 | 两处并发不一致 | `limits.max_workers=2`、`scheduler.max_workers=1` | `CONFIG_VALUE_OUT_OF_RANGE`，信息同时给出两个 `field_path` | limits.py |
| NEG-M03-08 | YAML 重复键 | 同一 `gates.yaml` 内写两个 `ruleset_hash` | `CONFIG_TYPE_INVALID`，`field_path == "ruleset_hash"`；不得“后者覆盖前者” | YAML_POLICY |

## B. Feature flag 越权（2 条）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M03-09 | T0 不得开 DC/SPA | `feature_flags: dc_spa=true`（其余按 T0） | `FEATURE_FLAG_NOT_PERMITTED`，信息含 `dc_spa` 与期望 `false`；退出码 2 | AGENTS §5；T2 范围 |
| NEG-M03-10 | 非法组合先于单值 | `role_off=true` + `agents=false` | `FEATURE_FLAG_NOT_PERMITTED`，信息含 `role_off` 依赖 `agents`；不得先报 T0 强制值而掩盖组合错误 | feature_flags 规则 3 |

## C. 环境指纹（4 条）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M03-11 | **缺一项必须不一致** | 右侧指纹 components 删除 `threads`（其余 8 项相同） | `compare_env_fingerprint` 返回 `status=MISMATCH`、`reason=MISSING_COMPONENT`、`equal=False`、`missing=("threads",)`；`same_env` False；`assert_same_env` 抛 `ENV_FINGERPRINT_MISMATCH` | env_fingerprint 核心契约 |
| NEG-M03-12 | 任一项不同即不一致 | 仅 `key_libs` 中 `numpy` 版本不同 | `MISMATCH`、`reason=VALUE_DIFF`、`differing == ("key_libs",)`、`equal=False`；`dc_reuse_allowed(..., ruleset_equal=True, inputs_equal=True)` 返回 `False` | 策划书 §8.4；05 §6 |
| NEG-M03-13 | 哈希种子随机化 | 两侧一致但 `PYTHONHASHSEED` 未设（值为 `"randomized"`） | `MISMATCH`、`reason=NON_DETERMINISTIC_HASH_SEED`；不得判 MATCH | env_fingerprint 设计取舍 |
| NEG-M03-14 | 摘要同但组成不同 | 手工构造 components 不同、digest 相同的两侧 | `MISMATCH`、`reason=DIGEST_DIFF`；不得因 digest 相等而放行 | env_fingerprint 判定 4/5 |

## D. 日志脱敏（2 条）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M03-15 | 私钥/token 不得落日志 | event 含 `private_key="-----BEGIN PRIVATE KEY-----…"`、`access_token="sk-…"` | 两个键均被**整键丢弃**；序列化输出中不含 PEM/`sk-` 原文；`redactions >= 2`；`assert_log_safe` 通过 | logging 硬规则 1 |
| NEG-M03-16 | 原始数据不得落日志 | event 含 `payload={...}`、`message` 内嵌 PEM 块 | `payload` 键被丢弃；`message` 中 PEM 被替换为 `<redacted>` 且 `redaction_applied=True`；输出不含原始内容 | logging 硬规则 2 |

## E. 审计写入边界（2 条）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M03-17 | 非 StateMachine 不得写 audit_log | 以 `collector` 身份请求写 `STATE_TRANSITION_APPLIED` | 拒绝（权限错误），`audit_log` 行数不变；错误信息含 `writer` 与 `state_machine` | 06 §3 |
| NEG-M03-18 | 启动拒绝不走 DB | 构造 `bind_hosts=["0.0.0.0"]` 且 `auth_token_env=""` | 拒绝启动（非回环必须有 token），`error_code` 为配置/启动类码，`sink == STARTUP_STDERR`；不得写 `audit_log` | 06 §4.6；audit_events 规则 1 |

## F. 误拒守卫（3 条：防止收紧过头）

| ID | 守卫目标 | 输入 / 操作 | 期望 | 依据 |
|---|---|---|---|---|
| GUARD-M03-01 | 回环可无 token | `bind_hosts=["127.0.0.1"]`、`auth_token_env=""` | 允许启动；不得把空串当缺键 | 06 §4.6 |
| GUARD-M03-02 | 固定哈希种子应判一致 | `PYTHONHASHSEED="0"`，其余组成项相同 | `MATCH`、`equal=True`；不得因“设了种子”反而判不一致 | env_fingerprint |
| GUARD-M03-03 | 有 token 的非回环允许 | `bind_hosts=["0.0.0.0"]`、`auth_token_env` 非空且环境变量存在 | 允许启动（T0 仍建议回环）；不得无条件拒绝 | 06 §4.6 |

## G. 执行记录模板（落地阶段填写，P1 留空）

| ID | 命令 | 退出码 | 断言到的原因 | 端口状态 | 日志路径 | 结论 |
|---|---|---|---|---|---|---|
| NEG-M03-01 | （待执行） | — | — | — | — | 未执行 |