# M05 · NEGATIVE_TESTS — 负例判据（P3）

> 阶段：P3｜状态：**判据定义，未执行**（本阶段限权：不建环境、不跑测试、不写业务代码）
> 执行阶段：M05 落地（WP-06 之后）
> 解释器（届时必须）：`C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe`
> 记录要求：命令、解释器、退出码、日志路径、运行时间；**P3 不得写成"已通过"**。
> 进程类负例必须在 Windows 上真实执行（作业对象/回收无法用 mock 证明）。

## 0. 判定纪律

1. 每条负例必须断言**拒绝原因正确**：异常类 + `fault`/`violation` + `error_code`（若有）
   + 关键字段（`relative_path`/`attempt_id`/`disposition`）中至少两项与下表一致；
   只断言"抛异常了"或"没跑起来"判测试失败。
2. 进程类负例必须断言：`AttemptOutcome.disposition`、`exit_code`、
   `escalation_required`、以及 `executor_process_exit` 事件是否落库（真实 SQLite）。
3. 路径类负例必须断言：抛出的 `WorkspaceEscape.relative_path` 与 `reason`；
   **且目录未被创建**（`os.path.exists` 为 False）。
4. 产物类负例必须断言：清单**没有**写入任何记录（半套清单也算失败）。
5. 静态边界负例必须断言具体禁名/禁字段，不得只断言"看起来没有"。
6. 原因不符即失败；不得改期望值、放宽阈值、用"重试通过"覆盖失败记录。
7. 本表每条只计一次；同一用例重复运行不构成独立样本。
8. 正例通过不构成完成证据；本表必须真实执行并逐条留下拒绝原因。

## A. 白名单与入口（`registry.py`）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M05-01 | 未注册模板被拒 | `registry.resolve("ghost@1.0.0")` | `TemplateNotRegistered`；`error_code="TOOL_NOT_ALLOWLISTED"`；`http_status=403`；`reason="TEMPLATE_NOT_REGISTERED"`；`.template_id` 等于入参 | 05 §3.1；用户判据 3 |
| NEG-M05-02 | 版本不精确匹配被拒 | `resolve("rf@1.0")` / `"rf@latest"` / `"RF@1.0.0"` | 三条均 `TemplateNotRegistered` 或 `RegistryContractError`（`NAME_VERSION_PATTERN`）；**不得**回退到 `rf@1.0.0` | `models.NAME_VERSION_PATTERN` |
| NEG-M05-03 | 类型自报不一致被拒 | 登记 `node_type="ml.train.classifier"`，`resolve_for(id, "ml.predict")` | `TemplateNotRegistered`；`reason="NODE_TYPE_NOT_ALLOWED"`；`detail` 含两个类型 | 05 §3.1 |
| NEG-M05-04 | 任意 shell 入口被拒 | 构造 `TemplateRegistration(module="python", symbol="main")`；`module="a.b", symbol="x; rm -rf /"` | 均 `RegistryContractError`；消息含命中的禁令 token（`python` / `;`）；**不得**"清洗后接受" | 05 §8.1；errors.py trigger |
| NEG-M05-05 | 脚本/可执行入口被拒 | `module="a.b.cmd"`、`symbol="run.exe"`、`module="C:/x/y"` | 均 `RegistryContractError`；命中 `.cmd`/`.exe`/`:`/`/` | 同上 |
| NEG-M05-06 | 重复登记被拒 | 两条相同 `template_id` 的登记 | `RegistryContractError`；消息含"重复登记"；**不得**后者覆盖前者 | REGISTRY_LIFECYCLE |
| NEG-M05-07 | 运行期注册入口不存在 | `hasattr(TemplateRegistry, "register")` 等 7 个禁名 | 全为 `False`；`assert_registry_contract(reg)` 返回 `[]` | 同上 |
| NEG-M05-08 | 网络模板被拒 | `ResourceCaps(..., network_allowed=True)` | `RegistryContractError`；消息含"T0 断网" | AGENTS §5；05 §2.1 |
| NEG-M05-09 | 副作用模板不得 DC 候选 | `dc_candidate=True, side_effect_class="SIDE_EFFECT"` | `RegistryContractError`；消息含"不得登记为 dc_candidate" | AGENTS §4.14 |
| NEG-M05-10 | 产物名非法 | `outputs=("a/b",)` / `("../x",)` / `("con",)` | `RegistryContractError`；消息含具体非法原因 | 05 §3.1；workspace 同名规则 |
| NEG-M05-11 | 参数 Schema 未知键 | `schema.validate({"target": "y", "evil": 1})` | `ParamViolation(field_path="parameters.evil", keyword="unknown-key")` | 05 §2.1；OQ-CT-08 |
| NEG-M05-12 | 参数类型不做强转 | `seed="42"`（string）、`test_size=True` | 两条均 `keyword="type"`；**不得**把 `"42"` 转成 `42`、不得把 `True` 当 int | `ParamSchema` |
| NEG-M05-13 | 参数越界 | `test_size=1.5`（max 1.0）、`seed=-1`（min 0） | `keyword="maximum"` / `"minimum"`；`field_path` 精确到 `parameters.test_size` | 05 §2.1 |

## B. 工作目录与越界写入（`workspace.py`）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M05-14 | `..` 逃逸被拒 | `resolve_inside(root, "../../etc/passwd")` | `WorkspaceEscape`；`relative_path` 原样；`reason` 含 `..`；目标未被创建 | I-03；本文 §5.2 |
| NEG-M05-15 | 绝对路径被拒 | `"C:\\Windows\\x"`、`"/etc/x"`、`"\\\\server\\share\\x"` | 三条均 `WorkspaceEscape`；`reason` 含"绝对路径/UNC" | 同上 |
| NEG-M05-16 | ADS / 盘符相对被拒 | `"a.txt:evil"`、`"C:foo"` | 均 `WorkspaceEscape`；`reason` 含"冒号" | 同上 |
| NEG-M05-17 | 符号链接/联接逃逸被拒 | 在根内建 junction 指向根外，再 `resolve_inside(root, "link/passwd")` | `WorkspaceEscape`；`reason` 含"链接逃逸"；**不得**只看字符串前缀就放行 | 同上 |
| NEG-M05-18 | 保留设备名被拒 | `node_id="con"` / `"aux"` / `"lpt1"` | `WorkspaceEscape`；`reason` 含"保留设备名"；目录未创建 | Windows 命名规则 |
| NEG-M05-19 | 结尾句点/空格被拒 | `node_id="model."`、`"model "` | `WorkspaceEscape`；`reason` 含"结尾句点/空格" | 同上 |
| NEG-M05-20 | 根不在 allowlist 被拒 | `WorkspacePolicy(root=<allowlist 外>, ...)` | `WorkspaceRootRejected`；`error_code="TOOL_NOT_ALLOWLISTED"`；消息不回显绝对路径 | OQ-P3-06 |
| NEG-M05-21 | 根是链接被拒 | `root` 本身是 junction | `WorkspaceRootRejected`；`reason` 含"符号链接/联接" | 本文 §5.1 |
| NEG-M05-22 | attempt 目录已存在 | 同一 `attempt_id` 再 `create()` | `WorkspaceCollision`；`fault=WORKSPACE_COLLISION`；`error_code=STATE_TRANSITION_DENIED`；**不得** `exist_ok=True` 覆盖 | 06 §4.5 |
| NEG-M05-23 | 清理不得碰产物 | `plan_cleanup(policy=ORPHAN_NO_EVIDENCE, evidence_seen=True, ...)` | `allowed=False`；`reason` 含"已有证据"；`targets` 不含 `artifacts/`/`logs/`/`inputs/` | 06 §1.2；M03 limits |
| NEG-M05-24 | 配额超限 | `QuotaGuard(quota_mb=10, reserved_mb=2).check(used_mb=9)` | `WorkspaceQuotaExceeded`；`error_code="RESOURCE_BUDGET_EXCEEDED"`；`limit_kind="disk"`；**不得**删文件腾空间 | M03 limits |

## C. 进程、超时与残留（`process_control.py`）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M05-25 | 无隔离不启动 | 桩：`JobObjectHandle.create` 抛 `OSError` | `ProcessIsolationUnavailable`；`fault=PROCESS_ISOLATION_UNAVAILABLE`；**未创建子进程**（无新 pid） | 本文 §6.1 |
| NEG-M05-26 | 分配失败不启动 | 桩：`assign` 抛 `OSError` | 同上；进程已被创建时必须**先杀再抛**（断言无残留） | 同上 |
| NEG-M05-27 | 超时后整树回收 | 子进程派生 1 个孙进程并睡 60s；`wall_time_sec=1` | `ExitStatus.exit_code is None`；`timed_out=True`；`ReclaimReport.ok=True`；`method=GRACEFUL_THEN_JOB`；孙进程 pid 不在活动进程表 | 策划书 §6.1；用户判据 2 |
| NEG-M05-28 | 回收失败不得报成功 | 桩：`terminate()` 返回 False 且 `active_process_count()` 恒为 1 | `ReclaimReport.ok=False`；`fault=RESIDUAL_PROCESSES`；`residual_pids` 非空；`escalation_required=True`；`AttemptOutcome.disposition=RECLAIM_FAILED`；`exit_code is None` | 本文 §6.2 |
| NEG-M05-29 | 残留进程存在时退出码 0 不可构造 | `ExitStatus(exit_code=0, tree_reclaimed=False, residual_pids=(1,))`；`ExitStatus(exit_code=0, timed_out=True, ...)`；`AttemptOutcome(disposition=RECLAIM_FAILED, exit_code=0, ...)` | 三条均抛 `ValueError`；消息分别含"未回收"/"超时不得带"/"不得带 exit_code" | 本文 §6.2 三道封死 |
| NEG-M05-30 | 残留未消失不得派发新 attempt | 残留 1 个 pid；Orchestrator 请求同节点新 attempt | 拒绝（`block_until_reclaimed`）；`attempt_seq` 不增；新一轮 `run_attempt` 不启动 | 本文 §6.2 ⑤ |
| NEG-M05-31 | 回收失败必须留痕 | 同 NEG-M05-28 | 存在 1 条 CRITICAL 结构化日志，含 `fault`、`residual_process_count`；存在 1 条 `executor_process_exit` 事件，`reclaim_ok=false`、`escalation_required=true`；**不得**只有日志没有事件 | 用户要求"留痕并升级" |
| NEG-M05-32 | 不许 shell 拼接 | 静态扫描：`shell=True`、`os.system`、`subprocess.call(`、`Popen(` 无作业参数 | 全部不出现；`build_argv` 形态固定为 `(python, "-m", module, "--params", name)`；含 shell 元字符的模块名被拒 | 05 §8.1；本文 §6.1 |
| NEG-M05-33 | 参数值不进命令行 | `params` 含 `"x; rm -rf /"` | `argv` 中不出现该值（只出现 `params.json`）；进程实际读文件；若出现即 FAIL | 同上 |
| NEG-M05-34 | 采样失败不得当 0 | 桩：`sample()` 返回 `failed=True` | `AttemptOutcome.sample_failures += 1`；上限判定**不使用**该 0 值；`disposition` 不因采样失败变成 `EXITED` 成功口径 | 本文 §8 |

## D. 产物、事件与"执行器不写状态"（`worker.py` / `template_protocol.py`）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M05-35 | 未声明产物被拒 | 模板写 `artifacts/extra.bin` 但 `emit_artifacts` 不声明 | `disposition=ARTIFACT_ERROR`；`fault=ARTIFACT_UNDECLARED`；清单为空（半套清单也算失败） | 本文 §7 |
| NEG-M05-36 | 声明了却没写 | 声明 `model.pkl` 但文件不存在 | `disposition=ARTIFACT_ERROR`；`fault=ARTIFACT_HASH_FAILED`（子码见 OQ-P3-07）；清单为空 | 同上 |
| NEG-M05-37 | 产物路径越界 | `ArtifactDeclaration(relative_path="../x")` / `"C:/x"` / `"inputs/x"` | `TemplateContractError`；`violation` 分别为 `WRITE_OUTSIDE`/`ABSOLUTE_PATH`/`WRITE_OUTSIDE`；`error_code="SCHEMA_INVALID"` | `template_protocol._require_relative` |
| NEG-M05-38 | 产物是符号链接 | `artifacts/model.pkl` 指向根外 | `ARTIFACT_OUTSIDE`；清单为空；**不得**跟随链接读内容 | 本文 §7 |
| NEG-M05-39 | 产物超数量/超大小 | 20 个产物（上限 10）；单文件 200MiB（上限 100MiB） | 分别 `ARTIFACT_TOO_MANY` / `ARTIFACT_TOO_LARGE`；`exit_code` 可能为 0，但 `disposition=ARTIFACT_ERROR` | M03 limits |
| NEG-M05-40 | 模板自报哈希被忽略 | 模板在 `RunReport`/`ArtifactDeclaration` 里塞 `sha256="0"*64` | 该字段**不存在**（`ArtifactDeclaration` 无哈希槽位）；若通过 `**extra` 传入 → `TypeError`；最终清单里的哈希等于真实文件哈希，不等于 `"0"*64` | 本文 §7 |
| NEG-M05-41 | 模板自报裁决被拒 | 模板类暴露 `passed=True` 或 `status="PASS"` | `assert_template_contract()` 返回非空，含 `不得暴露 passed`；`error_code="TOOL_NOT_ALLOWLISTED"`；**不得**登记该模板 | AGENTS §4.4 |
| NEG-M05-42 | 模板联网/起子进程 | 模板模块暴露 `socket`/`subprocess`/`requests`；或 `TEMPLATE_FORBIDDEN` 命中 | `assert_template_contract()` 返回非空，含 `FORBIDDEN_TEMPLATE_ATTRS` 命中项 | 05 §8.1；T0 断网 |
| NEG-M05-43 | Collector 不可用不得启动 | 桩：`collector.record` 抛 `EVIDENCE_CHAIN_BROKEN` | `disposition=LAUNCH_FAILED`；`fault=COLLECTOR_UNAVAILABLE`；**无子进程被创建**；无 `executor_launch` 事件 | 本文 §8 |
| NEG-M05-44 | 事件草稿不含链字段 | `EventDraft` 字段集合 | 不含 `event_seq`/`prev_hash`/`chain_hash`/`level`；kind 只允许三个；`assert_executor_boundary()` 返回 `[]` | 05 §4.1/§4.5 |
| NEG-M05-45 | Executor 不写状态 | 仅扫 `M05_executor` 下全部 `.py`（不含 `.md`）：`ast.parse` 断言 AST 节点，说明文字不计入；另加运行期 `dir(worker)` | ① `Import`/`Call` 不出现 `transition`/`_apply_transition`/`_insert_planned`；② 无 SQL 执行调用（`execute`/`executemany`/`executescript`），`UPDATE nodes`/`UPDATE tasks` 只允许出现在注释、docstring、字符串常量；③ `AttemptRequest.__dataclass_fields__` 无仓储字段；`run_attempt` 形参无 `machine` | AGENTS §4.4；I-01 |
| NEG-M05-46 | Executor 不写证据/审计 | 同上：仅 `.py` + `ast`，说明文字不计入 | ① `Call` 不出现 `_append`/`_insert`；② `INSERT INTO evidence`/`audit_log` 只允许出现在注释、docstring、字符串常量（如 `BOUNDARY_RULES`），不得作为 SQL 执行调用的参数；③ 写事件的唯一通道是 `CollectorPort.record(EventDraft)`，且 `EventDraft` 仍不含链字段（NEG-M05-44） | 06 §3 |
| NEG-M05-47 | attempt_id 复用被拒 | 已有 `executor_launch` 的 `attempt_01`，再次 `run_attempt` 同 ID | `disposition=PRECHECK_FAILED`；`fault=ATTEMPT_ID_REUSED`；未创建目录、未启动进程 | 06 §4.5；本文 §5.1 |
| NEG-M05-48 | 重试必须新 attempt | `attempt_01` 成功后重试 | 新 `attempt_id=attempt_02`；目录不同；`attempt_01` 目录未被改写 | 06 §4.5 |
| NEG-M05-49 | 退出码 0 不等于通过 | 正常退出 `exit_code=0` | `disposition=EXITED`；`AttemptOutcome.VERDICT is None`；不存在 `status`/`passed` 字段；Gate 未运行前不得出现 VERIFIED | AGENTS §4.4 |

## E. 误拒守卫（防止"过度收紧"）

| ID | 守卫目标 | 输入 / 操作 | 期望 | 依据 |
|---|---|---|---|---|
| GUARD-M05-01 | 合法单目录路径通过 | `resolve_inside(root, "tasks/t/nodes/n/attempts/attempt_01/artifacts/a.bin")` | 返回根内绝对路径；**不得**因"含 attempts"或"含点号"被误拒 | 本文 §5.2 |
| GUARD-M05-02 | 闭区间上界不算超限 | `QuotaGuard(quota_mb=10).check(used_mb=10)` | 不抛异常（等于上限合法） | M03 limits |
| GUARD-M05-03 | 正常退出不受影响 | `ExitStatus(exit_code=0, tree_reclaimed=True)` | 构造成功；`disposition=EXITED` | 本文 §6.2 |
| GUARD-M05-04 | 空注册表不是崩溃 | `TemplateRegistry([], template_id_rule=rule)`；`len(reg)==0` | 构造成功；`resolve` 一律 403；自检返回 `[]` | OQ-P3-12 |

## F. 执行记录模板（落地阶段填写，P3 留空）

| ID | 命令 | 退出码 | 断言到的原因 | 日志路径 | 结论 |
|---|---|---|---|---|---|
| NEG-M05-01 | （待执行） | — | — | — | 未执行 |
| NEG-M05-27 | （待执行） | — | — | — | 未执行 |
| NEG-M05-28 | （待执行） | — | — | — | 未执行 |
| NEG-M05-45 | （待执行） | — | — | — | 未执行 |