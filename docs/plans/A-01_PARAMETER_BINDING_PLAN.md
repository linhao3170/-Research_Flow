# A-01 参数完整性绑定：方案与文件级 diff 计划

> 日期：2026-11-14（Asia/Shanghai）
> 依据：`reports/t0_review_20261114/REVIEW.md` A-01、`docs/goals/GOAL_01_CORE_BACKEND.md:140` 的参数完整性要求、`docs/design/05_CONTRACTS_AND_STATES.md` §3.1/§4.1。
> 性质：修复方案与准确修改面。不修改 `contracts/**`、`docs/design/**`、`docs/ADR/**`、数据库 Schema、状态迁移表。
>
> **批准状态**：本轮 Goal 指令明确要求按 A-01 → A-02 → A-03 执行；本方案在复核报告已列出的最小修改面内落地。跨模块范围仅限 `researchflow/verification/{context,l1,l3}.py` 与对应测试，未扩大到 Collector、Gate、Executor、API 或 Schema。

## 1. 缺陷与冻结依据

- 复现：`reports/t0_review_20261114/l3_parameter_probe.py`。L3 从执行目录 `job.json.parameters` 取参数，未核对当前有效 NodeSpec 的 `parameters_hash` 与当前 attempt 的 E2 `executor_launch.parameters_hash`；L1 的产物哈希校验不覆盖 `job.json`。父进程内存中把 seed 42 改成 43 后，L1/L2/L3 仍 PASS，coverage=1.0。
- 现有事实源：
  - NodeSpec 声明：`graph_versions.graph_json.nodes[].parameters_hash`（`researchflow/dag/builder.py` 用 `hash_payload(parameters)` 生成）。
  - 执行事实：`attempts/<node>/attempt_NN/job.json`，其中 `parameters` 与 `parameters_hash`（Executor 写入）并存；`result.json.parameters_hash` 由 Executor 回写。
  - 证据事实：E2 `executor_launch.payload.parameters_hash`（Collector 从 `AttemptObservation` 记录）。
- 冻结依据：05 §3.1 要求 `parameters_hash` “与解析后的参数一致”；05 §4.1 要求证据 payload 与实际内容一致；07 WP-10 要求 L3 从原始数据真实重训。冻结件未规定 L1/L3 运行时必须交叉核对这四个事实源，因此本修复是**落实既有参数一致性要求的最小实现**，不是新增契约字段。
- 错误码：现有冻结 API 错误码表（06 §4.4）不含参数绑定码，也不要求新增公共错误码。本修复只在 `VerificationReport.gaps` / `L3Result.issues` 内使用新的 `L1_PARAMETERS_*`、`L3_PARAMETERS_*` 原因码，不进入 13 个冻结 API 错误码，不改变 HTTP 契约。

## 2. 唯一有效参数定义

对节点 N 的当前 attempt A（`nodes.attempt_seq`）：

```text
N 的有效参数 = graph_versions.graph_json.nodes[N].parameters_hash
```

必须同时满足以下等式（缺一即 fail-closed）：

```text
hash_payload(job.parameters) == job.parameters_hash
job.parameters_hash        == E2(executor_launch, N, A).parameters_hash
E2(...).parameters_hash    == result.json.parameters_hash        （result.json 存在时）
E2(...).parameters_hash    == graph.nodes[N].parameters_hash
```

`result.json` 缺失时由既有 `L1_ATTEMPT_RESULT_MISSING` 负责；不把缺失当参数匹配。

恢复重跑：冻结计划 `steps[].parameters_hash` 来自建计划时的同一 `graph_json.nodes[].parameters_hash`，`RecoveryService.rerun()` 用 `steps[].parameters` 执行；因此新的 attempt 仍满足上述等式。A-01 的回归测试必须覆盖 `test_wp_recovery.py::test_full_recovery_rerun_and_offline_bundle` 的 attempt_02 路径。

## 3. 代码修改面（准确 diff）

### 3.1 `researchflow/verification/context.py`（新增只读绑定检查，不改现有语义）

新增：

```python
@dataclass(frozen=True, slots=True)
class ParameterBinding:
    node_id: str
    attempt_id: str
    nodespec_parameters_hash: str | None
    job_declared_parameters_hash: str | None
    job_recomputed_parameters_hash: str | None
    result_parameters_hash: str | None
    e2_launch_parameters_hash: str | None
    problems: tuple[dict[str, str], ...]   # {"code", "detail"}，code 为 PARAMETERS_HASH_MISMATCH / PARAMETERS_BINDING_MISSING

    @property
    def ok(self) -> bool: ...
    def parameters(self) -> dict[str, Any] | None: ...   # 仅在 ok 时返回 job.parameters
```

新增 `VerificationContext.parameter_binding(node_id, attempt_seq) -> ParameterBinding`：

1. 从 `graph.nodes` 取 `parameters_hash`（找不到记 `PARAMETERS_BINDING_MISSING`，detail 指明 `nodespec`）。
2. 读 `attempt_dir/node job.json`；缺失/不可解析/无 `parameters`/无 `parameters_hash` 记 `PARAMETERS_BINDING_MISSING`（detail 指明 `job`/字段）。
3. 用 `researchflow.contracts.encoding.hash_payload(logical job["parameters"])` 重算；与 `job["parameters_hash"]` 比较，不等记 `PARAMETERS_HASH_MISMATCH`（detail 写 `job`）。
4. 读 `result.json.parameters_hash`（存在时）；缺失不单独记（由 L1 结果检查负责），存在但不等记 mismatch（detail 写 `result`）。
5. 取当前 attempt 的 E2 `executor_launch` payload（`ctx.evidence` 中 `node_id`/`attempt_id`/`level=E2`/`kind=executor_launch`，取最后一条）；无记录或无 `parameters_hash` 记 `PARAMETERS_BINDING_MISSING`（detail 写 `e2_launch`）；不等记 mismatch（detail 写 `e2_launch`）。
6. 不读执行器进程内存、不使用测试替身、不调用网络；只读 SQLite 已加载行与 attempt 目录文件。

不修改 `load_context()` 的数据库查询、`attempt_dir()`、`payload()`、`effective_dataset_sha256()`、`metric_nodes()`。

### 3.2 `researchflow/verification/l1.py`

新增原因码：

```python
L1_PARAMETERS_BINDING_MISMATCH = "L1_PARAMETERS_BINDING_MISMATCH"
L1_PARAMETERS_BINDING_INCOMPLETE = "L1_PARAMETERS_BINDING_INCOMPLETE"
```

在既有的逐节点循环（当前 attempt 的 `result.json` 校验）内、结果检查之前插入：

```python
binding = ctx.parameter_binding(node_id, node.attempt_seq)
checks += 1
for problem in binding.problems:
    code = L1_PARAMETERS_BINDING_INCOMPLETE if problem["code"] == "PARAMETERS_BINDING_MISSING" else L1_PARAMETERS_BINDING_MISMATCH
    issues.append(L1Issue(code, node_id, problem["detail"]))
```

不改变既有 `L1_CHAIN_*`、`L1_ARTIFACT_*`、`L1_ATTEMPT_*` 的判定与顺序；正常执行必须仍 PASS。

### 3.3 `researchflow/verification/l3.py`

新增原因码：

```python
L3_PARAMETERS_BINDING_MISMATCH = "L3_PARAMETERS_BINDING_MISMATCH"
L3_PARAMETERS_BINDING_INCOMPLETE = "L3_PARAMETERS_BINDING_INCOMPLETE"
```

`run(ctx)` 在创建 `run_root` 和任何子进程之前做 preflight：

1. `split_dataset` 节点 + 每个 `metric_nodes()` 节点调用 `ctx.parameter_binding(node_id, node.attempt_seq)`。
2. 任一 binding 不通过：立即返回
   `L3Result(status="FAIL", coverage=0.0, nodes=(), issues=(L3Issue(code, node_id, detail), ...), verification_root="", processes=())`；
   **不创建验证目录、不启动 split/train 子进程**。`verification_root=""` 表示本次没有发生复跑。
3. 全部通过后，`_split_parameters()` 与 `_node_parameters()` 仍从 `job.json` 返回 `parameters`，但改为通过 `binding.parameters()` 读取；删除 `_split_parameters()` 在 E2 launch 缺失时回退到 `task_spec.parameters` 的分支（该回退会在本轮显式拒绝 `PARAMETERS_BINDING_MISSING`）。
4. 保留既有 `validate_isolation()`、split_hash、预测、指标比较与 E3 记录逻辑不变。

### 3.4 测试（`tests/t0/`）

在 `tests/t0/test_wp09_verifier_l12.py` 增加：

- `test_l1_rejects_train_job_parameters_not_matching_nodespec`：把当前 attempt 的 train `job.json` 的 `seed` 改为 43 并重算 `parameters_hash`（模拟可写文件的攻击者）；断言 `L1_PARAMETERS_BINDING_MISMATCH`、`node_id=train_logistic_regression`，detail 含 NodeSpec/E2 与 job 哈希。
- `test_l1_rejects_split_job_parameters_not_matching_nodespec`：同上，对象为 `split_dataset`。
- `test_l1_rejects_stale_declared_parameters_hash`：只改 `parameters`、保留原 `parameters_hash`；断言 `L1_PARAMETERS_BINDING_MISMATCH` 且 detail 指向 `job`。
- `test_l1_rejects_missing_e2_parameters_binding`：用 `dataclasses.replace(ctx, evidence=[...])` 过滤掉 `executor_launch` 行；断言 `L1_PARAMETERS_BINDING_INCOMPLETE` 且 detail 含 `e2_launch`。该用例不修改数据库。

在 `tests/t0/test_wp10_verifier_l3.py` 增加：

- `test_l3_rejects_train_parameter_mismatch_before_spawning`：train job 篡改后调用 `L3Verifier.run`；断言 `status=FAIL`、`coverage=0.0`、`issues[0].code == L3_PARAMETERS_BINDING_MISMATCH`、`nodes == ()`、`verification_root == ""`、`processes == ()`；并断言 `root/verification` 下没有以 `l3-` 开头的新目录。
- `test_l3_rejects_split_parameter_mismatch_before_spawning`：split job 篡改；同样断言，且 `issues[0].node_id == "split_dataset"`。
- `test_l3_rejects_missing_e2_parameters_binding`：过滤 E2 launch 后用 `dataclasses.replace` 构造上下文；断言 `L3_PARAMETERS_BINDING_INCOMPLETE`、detail 含 `e2_launch`、无子进程。

回归（不新增测试文件）：`tests/t0/test_wp10_verifier_l3.py::test_l3_replays_from_raw_data_in_separate_processes`、`tests/t0/test_wp_recovery.py::test_full_recovery_rerun_and_offline_bundle` 必须继续通过，证明正常执行/恢复 attempt_02 不因绑定检查被误拒。

## 4. 明确不做

- 不新增 `contracts/**` 字段、不新增数据库列/迁移、不改变 `VerificationReport` schema。
- 不修改 Gate 的 required-check 规则或 `ruleset.v1.json`。
- 不改 `Executor`/`Collector` 写参数哈希的逻辑；不把 `job.json` 本身加入产物哈希清单（那会把执行事实与声明参数混为一谈，且改变既有 `artifact_observed` 语义）。
- 不改变 `VerificationService` 的 `L1 FAIL → L3 SKIP` 顺序；L1 的绑定失败会先使 L3 不运行，直接调用 L3 时由 preflight 拒绝。
- 不新增状态迁移、不改变 `INVALIDATED → READY` 守卫、不关闭 A-02/A-03。
- 不在本轮修改 `l2.py`。

## 5. 验证与证据

1. 修改前基线：`tests/t0/test_wp09_verifier_l12.py tests/t0/test_wp10_verifier_l3.py` 19 passed（2026-11-14，danger-full-access，`runtime/pytest-tmp-a01b`）。
2. 修改后先跑同一组 + 新增用例；再跑 `tests/t0/test_wp_recovery.py -q`。
3. 通过后跑 `tests/t0` 与全量 `tests` 回归；记录命令、解释器、exit code、耗时与日志路径。
4. 证据目录：`docs/verification/t0/a-01/`（`pytest_before.log`、`pytest_after.log`、`pytest_recovery.log`、`full_suite.log`、`summary.md`）。
5. 实施决策追加到 `docs/verification/t0/00_implementation_decisions.md`（D-30 参数绑定来源与错误码；D-31 L3 preflight 与无副作用拒绝）。

## 6. 回滚

仅回退 `context.py` / `l1.py` / `l3.py` 的新增段落与新增测试；不涉及数据库迁移、证据、报告或证书。回滚后既有三份当前 e2e 证据仍与其历史代码版本对应，不删除。