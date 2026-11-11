# M05 · Executor（P3）

> 阶段：P3「DAG 与执行器」｜日期：2026-11-11｜状态：**伪代码/设计件，不是实现**
> 覆盖：模板注册表、每 attempt 独立工作目录、子进程与整棵进程树回收、`run_attempt` 主流程、模板协议
> 不覆盖：模板本体（P4）、E0–E3 写入（WP-07）、Gate 判定（P5）、调度与并发（P7）、API（P10）
> 前置：P2 已验收、DEC-01/02/03 已裁决；M04 提供节点参数与 `artifact://<name>` 引用
> 阶段约束（S0）：不改 M02/M01/05/06/ADR；不建环境、不跑测试、不实现任何模板

## 1. 目标

把"任务能被真正执行，且执行方不裁决成败"落成五件可检查的东西：

1. **白名单**：模板只能来自冻结注册表，只按 `module + symbol` 形式登记；
   未注册、类型不符、任意 shell/python 入口一律拒绝（`registry.py`）；
2. **隔离**：每次 attempt 一个独立目录，所有路径经 `resolve_inside()`；
   软链/`..`/盘符/UNC/ADS 全部拒绝（`workspace.py`）；
3. **可控**：子进程挂在 Windows 作业对象上，超时**回收整棵树**；
   回收失败**也**要回收、要留痕、要升级（`process_control.py`）；
4. **不裁决**：`run_attempt()` 只产出"执行事实"（退出码、超时、产物哈希、采集缺口），
   不写状态、不写证据、不写审计、不返回 PASS/FAIL（`worker.py`）；
5. **协议边界**：模板只声明产物路径，不提供哈希、不返回裁决、不联网、不起子进程
   （`template_protocol.py`）。

## 2. 文件

| 文件 | 内容 | 状态 |
|---|---|---|
| `executor/registry.py` | 模板注册表、ParamSchema、ResourceCaps、静态入口校验 | 完成 |
| `executor/workspace.py` | 目录命名、越界检查、清理策略、配额 | 完成 |
| `executor/process_control.py` | 作业对象、启动顺序、超时、整树回收、留痕升级 | 完成 |
| `executor/worker.py` | `run_attempt()` 十步、产物清单、事件草稿 | 完成 |
| `executor/template_protocol.py` | prepare/run/emit_artifacts 三方法、禁止项、交接表 | 完成 |
| `MODULE.md`、`NEGATIVE_TESTS.md` | 模块说明与 53 条负例判据（P3 不执行） | 完成 |

行数：`registry.py` 566、`workspace.py` 560、`process_control.py` 527、`worker.py` 559、
`template_protocol.py` 397 —— 均 ≤ 800，按 PHASE_RULES §5 第 1 档，无需函数索引。

## 3. 边界（Executor 只执行）

| 东西 | 谁写 | 本模块 |
|---|---|---|
| `tasks.state` / `nodes.state` | StateMachine | ❌ 无仓储依赖、无 `transition` 调用 |
| `evidence`（E0–E3） | Collector / Verifier | ❌ 只提交 `EventDraft`，`event_seq`/`chain_hash` 由 Collector 分配 |
| `audit_log` | StateMachine | ❌ 不写 |
| 产物字节 | 模板（写 `artifacts/`） | 只读、复算哈希 |
| 产物清单（路径/哈希/大小/attempt） | **Executor** | ✅ `ArtifactManifest` |
| PASS / FAIL / VERIFIED | Gate / Verifier | ❌ `AttemptOutcome.VERDICT` 恒为 `None`，类里无裁决字段 |
| 重试与退避 | Scheduler/Orchestrator | ❌ 只报告一次 attempt 的事实 |

硬化手段（不靠自觉）：

- `AttemptRequest` 里没有仓储、没有 machine、没有 verifier；
- `EventDraft` 没有 `event_seq`/`prev_hash`/`chain_hash`/`level`；
- `AttemptOutcome` 的字段集合由 `assert_executor_boundary()` 检查，禁名含 `verdict`/`passed`/`success`/`status`；
- `run_attempt()` 的依赖只有 collector / workspace / processes / clock。

## 4. 模板注册表（`registry.py`）

| 项 | 规则 |
|---|---|
| ID 形态 | `name@MAJOR.MINOR.PATCH`，**精确匹配**；正则唯一来源 `models.NAME_VERSION_PATTERN`（本文件不复制） |
| 未注册 | `TemplateNotRegistered`，`error_code=TOOL_NOT_ALLOWLISTED`，`http_status=403`，`reason=TEMPLATE_NOT_REGISTERED` |
| 类型不符 | 同一异常，`reason=NODE_TYPE_NOT_ALLOWED`（调用方自报 `node_type` 不被接受） |
| 入口 | 只接受 `module`（≥2 段全小写）+ `symbol`（标识符）；命中 30 个禁令 token（`python`/`cmd`/`-c`/`&&`/`/`/`\`/`: `/.exe`/URL…）即 `RegistryContractError` |
| 参数 | `ParamSchema` 严格：未知键拒绝、bool≠int、不做强转、无 `additionalProperties: true` |
| 资源 | `ResourceCaps` 六个正数 + `network_allowed=False`（为 True 直接构造失败） |
| DC | 只登记 `dc_candidate`；`SIDE_EFFECT` 不得是候选；T0 `dc_spa=false` 不使用 |
| 生命周期 | 启动时构造、不可变；**没有** `register/add/reload/update/remove` |

## 5. 工作目录（`workspace.py`）

### 5.1 命名

```
<root>/tasks/<task_id>/nodes/<node_id>/attempts/<attempt_id>/
    inputs/    只读输入（worker 写 params.json/attempt.json）
    artifacts/ 模板产物（worker 收、算哈希）
    logs/      stdout.txt / stderr.txt / sample.jsonl
    tmp/       模板临时文件（唯一允许清理的目录）
```

`<root>` 由部署注入且必须落在 `security.yaml:path_allowlist` 内；
`WorkspacePolicy` 构造时校验：绝对路径、无 `..`、`realpath` 不改变（根不得是链接）、在 allowlist 内。

### 5.2 越界检查（`resolve_inside`）

语法闸：非绝对、非 UNC、无盘符、无 `://`、无 `:`（ADS）、组件级 `check_component`
（`.`/`..`/分隔符/控制字符/保留设备名/结尾句点空格/>128）。
语义闸：`realpath(root)` 与 `realpath(join)` 的 `commonpath`（`normcase`）必须等于根；
不同盘符 → `ValueError` 转"逃逸"。命中 → `WorkspaceEscape`（`SCHEMA_INVALID` 422）。

### 5.3 清理与配额

- T0 默认 `KEEP_ALL`；`TMP_ONLY` 只清 `tmp/`；
  `ORPHAN_NO_EVIDENCE` 需同时满足"无证据 + 超保留期 + 有审计"，否则不删；
- 任何策略都不得把 `artifacts/`、`logs/`、`inputs/` 放进清理目标（自检函数会断言）；
- 配额：`used + reserved > quota` → `RESOURCE_BUDGET_EXCEEDED`（429，`limit_kind="disk"`）；
  **不删证据/产物腾空间**。

## 6. 超时与"失败也回收"（`process_control.py`）

### 6.1 启动顺序（不可交换）

```
build_argv(python_exe, module)            # 只有 (python, -m <module>.<entry>, --params params.json)
  → JobObjectHandle.create(memory_mb)     # KILL_ON_JOB_CLOSE + PROCESS_MEMORY
  → CreateProcess(CREATE_SUSPENDED | CREATE_NEW_PROCESS_GROUP)
  → job.assign(pid)                        # 分配失败 → 不启动（ProcessIsolationUnavailable）
  → ResumeThread                           # 只有分配成功才恢复执行
```

先跑后分配会漏掉"分配前已 fork 的孙子进程"，超时就杀不干净。

### 6.2 超时分支的完整回收路径（验收判据 2）

```
wait(timeout=wall_time_sec) → None
  │
  ├─ terminate_tree(reason="WALL_CLOCK")
  │    ① REQUEST_EXIT   GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT, pgid)
  │    ② GRACE_WAIT     等 grace_sec（默认 5s）
  │    ③ TERMINATE_JOB  TerminateJobObject（返回 False 也继续 ④⑤）
  │    ④ VERIFY_EMPTY   job.active_process_count() == 0 ?
  │         ├─ 是 → ⑤ CLOSE_JOB → ReclaimReport(ok=True, method=GRACEFUL_THEN_JOB)
  │         └─ 否 → ⑤ CLOSE_JOB → ReclaimReport(ok=False,
  │                                   fault=RESIDUAL_PROCESSES,
  │                                   residual_pids=[...],
  │                                   escalation_required=True)
  │
  ├─ ExitStatus(exit_code=None, timed_out=True,
  │             tree_reclaimed=report.ok, residual_pids=report.residual_pids)
  │     结构不变量：timed_out=True ⇒ exit_code is None
  │                tree_reclaimed=False ⇒ residual_pids 非空
  │                exit_code==0 ⇒ 已回收且无残留
  │
  ├─ disposition = report.ok ? TIMED_OUT : RECLAIM_FAILED
  │
  ├─ collector.record(executor_process_exit,
  │       exit_kind=TIMEOUT, exit_code=null,
  │       reclaim_ok=report.ok, residual_process_count=N,
  │       escalation_required=report.escalation_required)
  │
  ├─ 写 CRITICAL 结构化日志（component=executor, fault, residual_process_count）
  │       —— 这就是"留痕"；Executor 不写 audit_log（那是 StateMachine 的写者）
  │
  └─ 返回 AttemptOutcome（exit_code=None）
        → Orchestrator 请求 RUNNING→FAILED（失败必须有证据：exit 事件已落）
        → 残留进程确认消失前，禁止同节点派发新 attempt（block_until_reclaimed）
```

**"不得返回成功"的三道封死**：

1. `ExitStatus.__post_init__`：超时不许带 `exit_code`；未回收不许无 `residual_pids`；
   `exit_code==0` 不许有残留；
2. `AttemptOutcome.__post_init__`：`TIMED_OUT`/`RECLAIM_FAILED` 不许带 `exit_code`；
   `RECLAIM_FAILED` 必须 `escalation_required=True`；
3. `assert_process_control_contract()`：把"只 terminate 父进程"、"timeout=None"、
   "shell=True"等禁名做成静态检查项。

## 7. 产物清单（验收要求四项）

| 字段 | 来源 | 说明 |
|---|---|---|
| `relative_path` | 模板声明的 `ArtifactDeclaration.relative_path` | `artifacts/` 下的 POSIX 相对名；越界即拒绝 |
| `sha256` | **Executor** 二进制读计算 | 64 位小写十六进制；模板自报的哈希被忽略 |
| `size_bytes` | `os.lstat().st_size` | 与哈希同一次读取的字节数 |
| `attempt_id` | 本次 attempt | 清单内所有记录必须同源 |

`ArtifactManifest.digest()` = `sha256(JCS(payload))`（按 `relative_path` 排序），
写进 `artifact_observed` 事件与 `产物清单`。

## 8. `run_attempt()` 十步与"不裁决"

十步见 `worker.py` 模块 docstring。两处关键取舍：

1. **记不了 launch 就不启动**：Collector 是 E2 唯一写者；先跑后记会造出
   "跑过但没有 launch 证据"的 attempt（既不能进 VERIFYING，也不能被 Gate 采信）。
   写失败 → `COLLECTOR_UNAVAILABLE`，不启动。
2. **`EXITED` 不是"成功"**：`exit_code=0` 只说明模板进程正常退出；
   是否通过要等 Gate（P5）与 Verifier（WP-08/WP-11）。`AttemptOutcome` 因此没有 `status`。

事件只用三个已冻结 kind：`executor_launch`、`executor_process_exit`、`artifact_observed`
（05 §4.5 的 7 值子集；不得新增）。

## 9. 验收对照

| 判据 | 落点 | 状态 |
|---|---|---|
| 2. worker 超时分支能画出进程树回收完整路径 | 本文 §6.2（五阶段 + 两个 ReclaimReport 分支 + 事件 + 升级） | 路径已画出，未执行 |
| 3. registry 拒绝未注册模板有明确错误码 | `registry.TemplateNotRegistered`（`TOOL_NOT_ALLOWLISTED`/403） | 判据已定义，未执行 |
| 4. NEGATIVE_TESTS 覆盖越界路径/残留进程/Executor 写状态 | `NEGATIVE_TESTS.md` §A.3/§A.4/§A.6 | 判据已定义，未执行 |
| 6. 未改 M02 schema；evidence 无 state 列 | 本阶段零改 M02；`workspace`/`worker` 不触碰 evidence | 已核对 |

## 10. OPEN QUESTIONS（新增，待用户裁决）

| 编号 | 问题 | 影响 | P3 的临时处理 |
|---|---|---|---|
| `OQ-P3-06` | 工作根没有独立配置键（`security.yaml` 只有 `path_allowlist`） | 部署时根目录来源不明 | 由部署注入 + 强制在 allowlist 内；不改 M03 schema |
| `OQ-P3-07` | "声明了产物但没写"没有独立子码 | 与哈希失败共用 fault | 暂用 `ARTIFACT_HASH_FAILED`；落地前补内部子码 |
| `OQ-P3-09` | 采样间隔 / `grace_sec` 没有配置键 | 各实现各写一套常量 | `SAMPLE_INTERVAL_SEC=0.5`、`DEFAULT_GRACE_SEC=5`，标注"非契约" |
| `OQ-P3-10` | 进程回收失败的"升级"落点：Executor 不能写 `audit_log` | 升级可能只停在日志 | 结构化 CRITICAL 日志 + `executor_process_exit` 事件 + `escalation_required`；审计由 StateMachine 在 `RUNNING→FAILED` 时写 |
| `OQ-P3-11` | Windows 8.3 短名/硬链接不在 `realpath` 检查范围 | 理论上仍可绕根 | 根由部署注入且在 allowlist 内；残余风险写进 `resolve_inside` docstring，不声称已解决 |
| `OQ-P3-12` | 模板注册表内容属 P4，P3 注册表为空 | 端到端无法联调 | 负例按"空注册表 → 任何 resolve 都 403"执行；正例待 P4 登记后补 |

## 11. 本阶段不做

- 不实现任何模板（P4/WP-05）、不生成 Split Manifest。
- 不写 E0–E3、不做哈希链、不写 `ingestion_log`（WP-07）。
- 不做 Gate/L1/L2/L3（P5）、不签发报告/凭证（WP-11）。
- 不做调度、并发、水位、重试退避（P7）。
- 不做 API、任务创建、幂等中间件（P10）。
- 不建 `.venv`、不装依赖、不跑测试、不改看板。