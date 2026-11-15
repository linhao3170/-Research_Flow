# M03 · 配置与环境指纹（P1）

> 阶段：P1「契约对齐与配置基座」｜日期：2026-11-11｜状态：**伪代码/设计件，不是实现**
> 覆盖：十个 YAML 的字段契约、资源上限、六个 feature flag、环境指纹、日志脱敏、审计事件
> 不覆盖：加载器实现、限额执行器、指纹采集、logger/审计写入、启动脚本

## 1. 目标

让“配置/环境”这一层在后续 9 个阶段有唯一口径，尤其钉死三件容易走样的事：

1. **配置缺键 = 启动失败**，不是“取默认值继续跑”。`default_for()` 的返回类型是 `NoReturn`，
   代码层面就不存在“缺了就按 False/0/空列表”的通路。
2. **环境指纹缺一项 = 不一致**。`compare_env_fingerprint()` 在任一侧缺组成项时返回
   `MISMATCH / MISSING_COMPONENT / equal=False`，`same_env()` 返回 `False`，
   `assert_same_env()` 抛 `ENV_FINGERPRINT_MISMATCH`；证书不得复用、DC 判定必须失效。
3. **开关必须真的改变行为**。每个 flag 都给出“关闭后的最小可观测集合”；
   只回显配置值不算实现。

## 2. 文件

| 文件 | 内容 | 状态 |
|---|---|---|
| `config/schemas.py` | 10 个 YAML、40 个字段的字段/类型/来源/缺失处理；无默认值策略 | 完成 |
| `config/limits.py` | token / wall-clock / 并发 / 内存 / 磁盘 / 重试：上限结构、超限动作、计量点 | 完成 |
| `config/feature_flags.py` | eg / dc_spa / vas / agents / adapter / role_off：T0 强制值、关闭后最小行为集合、非法组合 | 完成 |
| `config/env_fingerprint.py` | 9 个组成项、固定合成顺序、sha256、比较语义 | 完成 |
| `observability/logging.py` | 日志字段/级别/路径归一/脱敏（私钥、原始数据、token 一律不落） | 完成 |
| `observability/audit_events.py` | 10 类审计事件：触发点、必填字段、唯一写入者、sink | 完成 |
| `MODULE.md`、`NEGATIVE_TESTS.md` | 模块说明与 18 条负例判据（P1 不执行） | 完成 |

## 3. 十个 YAML 与阶段门控

| 文件 | 阶段 | 字段数 | 说明 |
|---|---|---:|---|
| `agents.yaml` | T1（门控） | 2 | 只允许 `config_version` + `enabled=false`；角色/模型/权限/预算未定义（FR-012） |
| `gates.yaml` | T0 | 6 | `ruleset_hash`、`required_checks[].check_id/min_level`、`l3_min_coverage` |
| `scheduler.yaml` | T0 | 5 | `max_workers`(1–2)、`ready_order` 固定、内存/磁盘水位 |
| `vas.yaml` | T2（门控） | 2 | 只允许门控键；风险特征/权重/预算未定义（FR-016） |
| `recovery.yaml` | T0（部分） | 3 | `plan_store_root`、`full_state_machine_enabled=false`；T1 恢复参数未定义 |
| `security.yaml` | T0 | 6 | 回环绑定、token 引用、路径白名单、包外信任锚、私钥引用名 |
| `harness.yaml` | T2（门控） | 2 | 只允许门控键；事件映射未定义（OQ-CT-06 / FR-017） |
| `experiment.yaml` | T0（部分） | 2 | 只允许 `seed_policy="explicit_per_task"`；任务集/重复/统计协议属 T1/T2 |
| `limits.yaml` | T0 | 10 | token/时长/并发/内存/磁盘/重试上限，全部显式 |
| `domainpacks.yaml` | T0 | 2 | 已审核域包标识白名单（至少 `tabular_ml@1.0.0`） |

合计 40 个字段，全部 `required=True`、`missing_action=ABORT_STARTUP`、`default_source="无"`。

## 4. 硬规则

### 4.1 配置

- 缺文件、缺键、未知键、类型不符、`null` 值、越界 → 一律拒绝启动（退出码 2，不监听端口）。
- 键存在但值为 `null` 属 `CONFIG_TYPE_INVALID`，**不是**缺键；不得混用两个码。
- 不做类型强转（`"2"` ≠ `2`，`"false"` ≠ `False`）。
- YAML 层拒绝重复键、多文档、merge key（`<<`）；PyYAML 默认“后者覆盖前者”必须关掉。
- 两处 `max_workers`（`limits.yaml` / `scheduler.yaml`）必须一致，且 ≤2。
- 非回环绑定且无 token → 拒绝启动（06 §4.6）；失败信息只说明原因，不回显配置值。

### 4.2 Feature flags（T0）

- 只允许 `eg=true`；`dc_spa` / `vas` / `agents` / `adapter` / `role_off` 必须 `false`。
- 组合优先：`role_off=true` 要求 `agents=true`；`dc_spa=true` 要求 `eg=true`。
- 与强制值不一致 → `FEATURE_FLAG_NOT_PERMITTED`，**不得静默降级**为强制值。

### 4.3 环境指纹

- 9 项：OS、架构、CPU、Python、依赖锁、关键库、线程变量、locale/TZ、种子策略。
- 固定顺序 → JCS → SHA-256 小写十六进制；新增组成项必须升 `COMPOSITION_VERSION`。
- **缺项 = 不一致**；`PYTHONHASHSEED` 未设/random = 不一致；digest 同但组成项不同 = 不一致。
- 不计入项目根/venv/可执行文件绝对路径（同机换目录做 L3 不应误判为换环境）。
- 证书 `env_fingerprint` 必须等于 E2 记录；不一致不得签发、不得复用（05 §6）。

### 4.4 日志与审计

- 日志：16 个字段（6 必填）、5 个级别；白名单之外的键一律丢弃。
- 私钥/token/原始数据/请求响应正文：**任何级别**都不得落日志；命中即丢字段并计数。
- 绝对路径必须归一（`<project>` / `<home>` / `<external>`）。
- 审计：`audit_log` 唯一写者 = StateMachine；启动拒绝写结构化 stderr，不是 DB。
- 审计只追加；计划正文、token、私钥、工具参数原文不得写入。

## 5. 对外接口（供后续阶段引用）

| 接口 | 语义 |
|---|---|
| `schemas.CONFIG_FILES` / `default_for()` | 10 个文件的字段契约；取默认值必然失败 |
| `limits.LIMITS` / `ENFORCEMENT_PRECEDENCE` | 六类上限与同时超限时的判定顺序 |
| `feature_flags.T0_FORCED` / `validate_flags()` | T0 强制取值与组合校验 |
| `env_fingerprint.COMPONENT_ORDER` / `compare_env_fingerprint()` | 指纹合成顺序与比较（缺项=不一致） |
| `logging.LOG_FIELDS` / `redact_event()` | 日志字段与脱敏 |
| `audit_events.AUDIT_EVENTS` | 10 类审计事件与写入者 |

## 6. 验收（P1）

- 10 个 YAML 均有字段表，每字段有类型、来源、缺失处理；**无任何隐式默认**。
- `limits.py` 覆盖 token/wall-clock/并发/内存/磁盘/重试六类，每类有超限动作与留痕位置。
- 六个 flag 齐全，每个都有“关闭后最小行为集合”，不只写配置键。
- `env_fingerprint` 的缺项路径明确落在 `compare_env_fingerprint()`（返回 MISMATCH）。
- `NEGATIVE_TESTS.md` ≥8 条（本文件 18 条），每条断言拒绝原因。

## 7. 未决与风险

- 配置字段名是 **P1 提议**，不是 G0 契约；落地前需在对应 WP 评审并记 CHANGELOG。
- `PYTHONHASHSEED` 未设即判不一致，可能导致 T0 必须显式设置该变量才能签发证书；
  这是有意收紧，已由 P1 验收裁决确认，见 §8 `OQ-P1-08`。
- `auth_token_env` 允许空串的设计只适用于回环绑定；T1 引入认证后需重审。
- `CERTIFICATE_NOT_AVAILABLE` 未在附录 E.3 中，06 §4.3 与 §4.4 冲突；已由 P1 验收裁决关闭
  （不新增码，见 M01 `MODULE.md` §8 `OQ-P1-04`），M03 不重复记录。

## 8. DECISIONS（P1 验收裁决 · 2026-11-11）

> 本节只记录裁决与落地位置，不改上游冻结件；原 OQ 编号保留以便追溯（PHASE_RULES §8）。
> 未列入本节的两条（`OQ-P1-03`、`OQ-P1-05`）原问题与裁决正文均未落文件；2026-11-11 标 `NEEDS_CONFIRMATION`，不得作为先例，等待用户补证或确认无法恢复。

### `OQ-P1-06` 40 个配置键待 ADR-008 冻结

- **裁决**：40 个配置键标为 **“待 ADR-008 冻结”**；`FROZEN` / `PLAN` / `DERIVED` 分类保留。
- **约束**：ADR-008 之前，键名与取值**不是稳定接口**；任何改名必须同步 `config/schemas.py`、`MODULE.md` 与 `NEGATIVE_TESTS.md`。
- **落地**：`config/schemas.py` 的 `ValueSource` 分类与 40 个 `FieldSpec` 保持不变；本节为其冻结状态标记，不新增字段、不改键名。

### `OQ-P1-08` `PYTHONHASHSEED` 收紧口径

- **裁决**：**接受**“未设置或 `randomized` 一律 MISMATCH”；保留现状。
- **约束**：T0 要签发证书或做 L3，必须显式设置 `PYTHONHASHSEED`（建议 `0`）；不得在 `compare_env_fingerprint()` 里放宽为“跳过”。
- **落地**：`config/env_fingerprint.py` 的 `seed_policy` 组成项与判定 2；`NEGATIVE_TESTS.md` 的 `NEG-M03-13`（期望 `MISMATCH / NON_DETERMINISTIC_HASH_SEED`）。