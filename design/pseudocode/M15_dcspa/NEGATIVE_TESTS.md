# M15 · NEGATIVE_TESTS — DC/SPA/PRR 负例（P9）

> 阶段：P9｜状态：**判据定义，未执行**（S0：不建环境、不跑测试、不写业务代码）
> 执行阶段：M15 落地（T2/FR-015）、G4 恢复验收；T0/T1 不启用 DC/SPA，只验证“禁用路径”
> 解释器（届时必须）：`C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe`
> 记录要求：命令、解释器、退出码、日志路径、运行时间；**P9 不得写成“已通过”**。
> 真实输入：真实 k 次独立进程/目录探针、真实 JCS 哈希、真实文件系统复算；
> 不得用 mock 证明“哈希不一致会被拒”。

## 0. 判定纪律

1. 每条负例必须断言**拒绝原因正确**：`error_code` + `reason`（或 `DcValidity.status` /
   `SpaDecision.action` + `reason` / `PrrReport` 字段），只断言“抛异常”判失败。
2. 结构型负例必须断言**构造失败**（`DcIdentity(...)`、`ConditionResult(...)`、
   `SpaDecision(...)`、`PrrReport(...)` 抛错），证明不是运行期碰巧拒绝。
3. 一票否决负例必须构造“其它条件全 PASS、只有随机性命中”的输入，断言 `eligible=False`
   且 `vetoed=True`；不能只测“随机节点也没有产物”。
4. 默认分支负例必须断言 `action is REEXECUTE` 且 `record is None`；
   SKIP 负例必须断言“无记录/无签名时构造失败”。
5. PRR 负例必须断言**分母与逐节点行**：`prr_point_estimate is None`、`unresolved` 计数、
   `rows` 长度；不得只断言“报告非空”。
6. 正例通过不构成完成证据；`GUARD-M15-01/02/03` 必须真实跑并留两次哈希/两条独立进程记录。
7. 时间负例必须覆盖 `Z` 与 `+00:00` 两种写法（`NEG-M15-22`）。

## 0.1 符号对照（初稿名 → 当前实现名）

> 负例 ID 与场景保留；下表只把「预期拒绝原因」映射到当前代码里的真实符号，
> 保证断言的是**原因**而不是「抛了异常」。逐条文本重写列入 `OQ-P9-20`。

| 负例写法 | 当前符号 | 落点 |
|---|---|---|
| `reason=STOCHASTIC_NODE` | `DcReason.RANDOM_NODE` + `ConditionStatus.VETO` | `dc_eligibility._randomness_result` |
| `reason=SIDE_EFFECT_CLASS` | `DcReason.SIDE_EFFECT_NODE`（`Condition.NODE_PURITY` → `FAIL`） | `dc_eligibility._purity_result` |
| `reason=K_TOO_SMALL` | `DcReason.K_RUNS_INSUFFICIENT`（`ConditionStatus.MISSING_EVIDENCE`） | `dc_eligibility.compare_runs` 第 1 步 |
| `reason=RUNS_SHARE_PROCESS` | `DcReason.PROCESS_REUSED` | `compare_runs` 第 3 步 |
| `reason=RUNS_SHARE_DIRECTORY` | `DcReason.DIRECTORY_REUSED` | `compare_runs` 第 4 步 |
| `reason=RUN_FINGERPRINT_REUSED` | `DcReason.RUN_FINGERPRINT_REUSED`（同名） | `compare_runs` 第 5 步 |
| `reason=ARTIFACT_HASH_DIVERGENCE` | `DcReason.OUTPUT_DIVERGED` | `compare_runs` 第 7 步 |
| `reason=METRIC_DIVERGENCE` | `DcReason.METRIC_DIVERGED` | `compare_runs` 第 8 步 |
| `reason=INPUT_HASH_MISMATCH` | `DcReason.INPUT_NOT_FIXED` | `compare_runs` 第 6 步 |
| `reason=ENV_MISMATCH` | `DcReason.ENV_CHANGED` / `ENV_INCOMPLETE` | `_env_result` |
| `reason=NO_DC` | `ReexecuteReason.NO_DC`（同名） | `spa_judge._dc_outcome` |
| `reason=PREDECESSOR_HASH_CHANGED` | 同名（`ReexecuteReason.PREDECESSOR_HASH_CHANGED`） | `spa_judge._predecessor_outcome` |
| `PrrRefused(reason="PRUNING_RECORD_MISSING")` | 同名 | `prr_ledger.PrrLedger._require_episode` |
| `PrrRefused(reason="RERUN_WITHOUT_START")` | 同名 | `prr_ledger.record_rerun_completed` |

## A. DC 资格（六类条件）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M15-01 | **副作用节点签 DC** | `side_effect_class="SIDE_EFFECT"`，其余事实全 PASS | `eligible=False`；`NODE_PURITY.status=FAIL`；`reason=SIDE_EFFECT_CLASS`；`issue_dc` 抛 `DcRefused(error_code="RECOVERY_NOT_SAFE", reason="DC_NOT_ELIGIBLE")` | §8.2 R02；AGENTS §4.14 |
| NEG-M15-02 | **随机性节点签 DC（一票否决）** | `declared_stochastic=True`，k=3 且 bit-exact | `eligible=False`；`vetoed=True`；`RANDOMNESS.status=VETO`；`reason=STOCHASTIC_NODE`；即使其它五项 PASS 也不得签发 | §8.2 R06；验收判据 2 |
| NEG-M15-03 | 外部随机源漏判 | `uses_random_external_source=True` | `status=VETO`；`reason=RANDOM_EXTERNAL_SOURCE` | §8.2 R06 |
| NEG-M15-04 | 纯度能力漏判 | 依次置 `writes_database/performs_network_io/mutates_global_state/uses_wall_clock=True` | 四项分别 FAIL，reason 对应 `WRITES_DATABASE/PERFORMS_NETWORK_IO/MUTATES_GLOBAL_STATE/USES_WALL_CLOCK` | §8.2 R02 |
| NEG-M15-05 | **k 不足** | 只有 2 条 `RunProbe`，`required=3` | `K_RUN_BIT_EXACT.status=MISSING_EVIDENCE`；`reason=K_TOO_SMALL`；`observed_k=2` | §8.2 R05 |
| NEG-M15-06 | 同一进程跑 3 次 | 3 条探针 `process_id` 相同，其余一致 | `bit_exact=False`；`reason=RUNS_SHARE_PROCESS` | §8.2 R05 |
| NEG-M15-07 | 同一目录跑 3 次 | 3 条探针 `working_directory` 仅大小写/分隔符不同 | `reason=RUNS_SHARE_DIRECTORY`（规范化后相同） | §8.2 R05 |
| NEG-M15-08 | 运行身份复用 | 3 条探针 `run_fingerprint` 相同 | `reason=RUN_FINGERPRINT_REUSED` | §8.2 R05 |
| NEG-M15-09 | 产物哈希不一致 | 第 2 次运行的 `metrics.json` 哈希差 1 位 | `bit_exact=False`；`reason=ARTIFACT_HASH_DIVERGENCE`；`diverging_artifacts=("metrics.json",)` | §8.2 R05 |
| NEG-M15-10 | 指标哈希不一致 | 产物一致，`metric_hash` 不同 | `reason=METRIC_DIVERGENCE` | §8.2 R05 |
| NEG-M15-11 | 输入在 k 次间变化 | 第 3 次 `input_hashes["dataset"]` 不同 | `INPUT_FIXED.status=FAIL`；`reason=INPUT_HASH_MISMATCH` | §8.2 R03 |
| NEG-M15-12 | 环境漂移 | `EnvComparisonView(equal=False, reason="VALUE_DIFF", differing=("threads",))` | `ENV_FINGERPRINT.status=FAIL`；`reason=ENV_MISMATCH`；detail 含 `threads` | §8.2 R04 |
| NEG-M15-13 | 环境缺项 | `EnvComparisonView.equal=False, reason="MISSING_COMPONENT", missing=("seed_policy",)` | `status=MISSING_EVIDENCE`；`reason=ENV_EVIDENCE_MISSING`；**缺项不得当未知跳过** | §8.2 R04；M03 契约 |
| NEG-M15-14 | 规则版本变化 | `binding.ruleset_hash != current_ruleset_hash` | `VALIDITY_RULESET.status=FAIL`；`reason=RULESET_MISMATCH` | §8.2 R07 |
| NEG-M15-15 | 提议的 DC 已过期 | `proposed_expires_at <= now` | `reason=EXPIRED_PROPOSAL` | §8.2 R07 |
| NEG-M15-16 | TTL 超上限 | `expires_at - now = 31 天` | `reason=TTL_TOO_LONG` | OQ-P9-05 |
| NEG-M15-17 | **缺证据的 PASS** | 直接构造 `ConditionResult(status=PASS, evidence_refs=())` | 构造抛 `DcEligibilityError(reason="PASS_WITHOUT_EVIDENCE")` | 结构约束 |
| NEG-M15-18 | 非否决项返回 VETO | `ConditionResult(condition=NODE_PURITY, status=VETO, reason=...)` | 构造抛 `VETO_OUTSIDE_VETO_SET` | 一票否决只属于 RANDOMNESS |
| NEG-M15-19 | 六项不全 | `EligibilityVerdict(results=五项, ...)` | 构造抛 `CONDITION_SET_INCOMPLETE` | 结构约束 |
| NEG-M15-20 | **有 FAIL 却声称合格** | 构造六条结果：五条 PASS + `REPEATED_RUNS=FAIL` | `verdict.eligible is False`（`eligible` 是派生属性，`dataclasses.fields(EligibilityVerdict)` 里**没有**该字段，无法置真）；`vetoes == ()` | §8.2；结构约束 |

## B. DC 签发 / 过期 / 撤销

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M15-21 | **不合格仍签发** | `verdict.eligible=False` 传给 `issue_dc` | 抛 `DcRefused`；`error_code="RECOVERY_NOT_SAFE"`；`reason="DC_NOT_ELIGIBLE"`；`registry.size == 0`（未落库） | §8.2；D.5 |
| NEG-M15-22 | 签发前复核发现不一致 | `verdict` 被伪造成 eligible=True，探针产物实际不同 | `issue_dc` 抛 `reason="DC_RUNS_NOT_BIT_EXACT"`；detail 含第二次比对原因 | §8.2 R05 |
| NEG-M15-23 | `eligible=false` 的 DC 身份 | 构造 `DcIdentity(eligible=False, ...)` | 抛 `DcRefused(reason="DC_ELIGIBLE_FALSE")` | D.5 字段语义 |
| NEG-M15-24 | 签名未回验 | `DcSignature(verified_roundtrip=False)` | 抛 `DcSignatureInvalid(reason="DC_SIGNATURE_NOT_VERIFIED", error_code="SIGNATURE_INVALID")` | §7.5；OQ-P6-02 |
| NEG-M15-25 | 域前缀错误 | `DcSignature(domain_prefix=b"RF-SPA-V1\x00")` | `reason="DC_DOMAIN_PREFIX_MISMATCH"` | §7.5 域分离 |
| NEG-M15-26 | `dc_id` 与内容不符 | 改记录里的 `node_type`，`dc_id` 不变 | 构造 `DcRecord` 抛 `DcStoreCorrupt(reason="DC_ID_MISMATCH")` | OQ-P9-01 |
| NEG-M15-27 | 同 ID 异内容 | 先 `put(record)`，再 `put` 改过 `expires_at` 但 `dc_id` 相同的记录 | 抛 `DcStoreCorrupt(reason="DC_ID_CONTENT_CONFLICT")`；原记录仍在且字节不变 | 附录 D.6 只增不改 |
| NEG-M15-28 | 过期后仍复用 | `now >= expires_at` | `evaluate_dc` 返回 `DcStatus.EXPIRED`；`valid=False` | §8.3 条件 1 |
| NEG-M15-29 | 撤销后仍复用 | `revoke_dc(reason=K_RUN_DIVERGENCE)` 后 `evaluate_dc` | `DcStatus.REVOKED`；detail 含原因；**撤销优先于到期/绑定** | §8.2 R07；终态 |
| NEG-M15-30 | 撤销不存在的 DC | `revoke_dc(dc_id="0"*64)` | 抛 `DcRefused(reason="DC_NOT_FOUND")`；不产生撤销记录 | 只增不改 |
| NEG-M15-31 | 代码/输入结构/环境漂移 | 分别改 `binding.code_hash/input_schema_hash/env_digest` | 分别返回 `CODE_MISMATCH/INPUT_SCHEMA_MISMATCH/ENV_MISMATCH` | §8.3 条件 1 |
| NEG-M15-32 | 签名无效的记录 | 把 `record.signature` 换成 `verified_roundtrip=False` 的等价对象（绕过构造） | `evaluate_dc_record` 返回 `SIGNATURE_INVALID`；`valid=False` | §7.5 |
| NEG-M15-33 | `output_hashes` 未排序/重复 | `DcIdentity(output_hashes=("b"*64,"a"*64))` | 抛 `reason="DC_OUTPUT_HASHES_NOT_CANONICAL"` | OQ-P9-02 |
| NEG-M15-34 | `run_fingerprints` 重复 | 3 条探针里两条相同 | 抛 `reason="DC_RUN_FINGERPRINT_REUSED"` | §8.2 R05 |

## C. SPA 五项

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M15-35 | **无 DC 却剪枝** | `dc_record=None`、`dc_validity=None`，其余四条全 PASS | `SpaDecision.action is SpaAction.REEXECUTE`；`ReexecuteReason.NO_DC in causes`；`record is None`；`outcomes[0].outcome is REEXECUTE` | §8.3 条件 1；I-05 |
| NEG-M15-36 | DC 过期/撤销仍剪枝 | DC 记录存在但 `evaluate_dc_record` 返回 EXPIRED/REVOKED | `reason=DC_INVALID`；detail 含状态；不 SKIP | §8.3 条件 1 |
| NEG-M15-37 | **前驱哈希变化** | `predecessor_hashes_at_recovery` 里 `train=a`，`predecessor_hashes_now` 里 `train=b` | `reason=PREDECESSOR_HASH_CHANGED`；detail 含前驱名 `train`；`action=REEXECUTE` | §8.3 条件 2 |
| NEG-M15-38 | 前驱证据缺失 | `current_hashes()` 返回 `None` | `reason=PREDECESSOR_EVIDENCE_MISSING`；`evidence_missing=True` | §8.3 条件 2 |
| NEG-M15-39 | 前驱集合不符 | `predecessor_ids=("a","b")`，端口只返回 `a` | `reason=PREDECESSOR_HASH_CHANGED`；detail 含集合差异 | §8.3 条件 2 |
| NEG-M15-40 | **磁盘复验失败** | `ArtifactInspection(actual_hash != expected_hash)` | `reason=DISK_REHASH_MISMATCH`；detail 含产物名 | §8.3 条件 3 |
| NEG-M15-41 | 软链接越界 | `real_path="D:\\old\\metrics.json"`，`allowed_root="D:\\ws"` | `matches()=False`；`reason=DISK_REHASH_MISMATCH` | §8.3 条件 3 |
| NEG-M15-42 | 指向旧目录 | `points_to_old_directory=True` | 同上；即使哈希一致也不得通过 | §8.3 条件 3 |
| NEG-M15-43 | 磁盘复算缺项 | 只返回 1 个 inspection，请求有 2 个产物 | `reason=DISK_EVIDENCE_MISSING`；`evidence_missing=True` | §8.3 条件 3 |
| NEG-M15-44 | Gate 复检不过 / 旧证据过期或撤销 | `GateRecheck(passed=False, conflicts=2)`；或 `passed=True, evidence_expired=True` | 前者 `reason=GATE_NOT_PASSING`；后者构造即抛 `GATE_PASS_WITH_CONFLICTS`；detail 含冲突/过期/撤销 | §8.3 条件 4 |
| NEG-M15-45 | Gate 规则版本不符 | `recheck.ruleset_hash != request.ruleset_hash` | `reason=GATE_NOT_PASSING`；detail 指规则版本 | §8.3 条件 4 |
| NEG-M15-46 | Gate 证据缺失 | `gate_port.recheck()` 返回 `None` | `reason=GATE_EVIDENCE_MISSING`；`evidence_missing=True` | §8.3 条件 4 |
| NEG-M15-47 | **副作用节点 SPA** | `SideEffectFacts(side_effect_class="SIDE_EFFECT")` | `reason=SIDE_EFFECT_PRESENT`；`action=REEXECUTE` | §8.3 条件 5 |
| NEG-M15-48 | 任务要求本次执行 | `task_requires_actual_execution=True` | `reason=TASK_REQUIRES_EXECUTION` | §8.3 条件 5 |
| NEG-M15-49 | 副作用证据缺失 | `side_effect_port.facts()` 返回 `None` | `reason=SIDE_EFFECT_EVIDENCE_MISSING` | §8.3 条件 5 |
| NEG-M15-50 | **无证据的 PASS** | 构造 `ConditionOutcome(passed=True, evidence=None)` | 构造抛 `SpaJudgeError(reason="PASS_WITHOUT_EVIDENCE")` | 结构约束 |
| NEG-M15-51 | Agent 自述当证据 | `EvidenceRef(produced_by="agent")` | 抛 `EVIDENCE_PRODUCER_FORBIDDEN` | E0/E1 边界；§8.3 |
| NEG-M15-52 | **无签名 SKIP** | 五项全 PASS，`signer=None` | `action=REEXECUTE`；`reason=SPA_SIGNING_FAILED`；`record is None` | 验收判据 1；§7.5 |
| NEG-M15-53 | 签名失败仍 SKIP | `signer.sign_spa()` 抛 `SpaRefused` | `action=REEXECUTE`；`reason=SPA_SIGNING_FAILED`；**绝不返回 SKIP** | §7.5 |
| NEG-M15-54 | 无记录的 SKIP | 构造 `SpaDecision(action=SKIP, record=None, 五项 PASS)` | 构造抛 `SKIP_WITHOUT_RECORD` | 验收判据 1 |
| NEG-M15-55 | REEXECUTE 无原因 | 构造 `SpaDecision(action=REEXECUTE, reason=None)` | 构造抛 `REEXECUTE_WITHOUT_REASON` | 结构约束 |
| NEG-M15-56 | 未回验 SPA 签名 | `SpaSignature(verified_roundtrip=False)` | 抛 `SpaRefused(reason="SPA_SIGNATURE_NOT_VERIFIED", error_code="SIGNATURE_INVALID")` | §7.5 |
| NEG-M15-57 | SPA `spa_id` 与内容不符 | 改 `artifact_hash`，`spa_id` 不变 | 构造 `SpaRecord` 抛 `SpaRefused(reason="SPA_ID_MISMATCH")` | OQ-P9-01 |
| NEG-M15-58 | 前驱哈希未排序 | `SpaIdentity(predecessor_hashes=(b, a))` | 抛 `PREDECESSOR_HASHES_NOT_CANONICAL` | OQ-P9-07；M11 unique |

## D. PRR 台账

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M15-59 | **无授权剪枝** | `spa_id` 为空或 `dc_id` 为空 | `PruningAuthorization` 抛 `PRUNING_AUTHORIZATION_INVALID`；台账无 episode | §8.3；I-05 |
| NEG-M15-60 | **无剪枝记录直接登记重跑** | 未 `record_pruning` 就 `record_rerun_started` | 抛 `PrrRefused(reason="PRUNING_RECORD_MISSING")`；台账 `events == ()` | §4.2 R08；验收判据 4 |
| NEG-M15-61 | **没有开始事件就登记完成** | `record_pruning` 后直接 `record_rerun_completed` | 抛 `PrrRefused(reason="RERUN_WITHOUT_START")`；证明「真的跑过」不可省略 | §4.2 R08 |
| NEG-M15-62 | 重复登记同一 episode | 同一 `(node_id, episode_id)` 两次 `record_pruning` | 抛 `reason="EPISODE_DUPLICATE"` | 不合并、不覆盖 |
| NEG-M15-63 | 覆盖已有结果 | 已 completed 后再 `record_rerun_completed` | 抛 `reason="RERUN_STATE_INVALID"`；要求走 `record_correction` | 附录 D.6 |
| NEG-M15-64 | 剪枝旧结果非 SUCCESS | `pruned_result.status="FAILED"` | 抛 `reason="PRUNED_RESULT_NOT_SUCCESS"` | §8.3 条件 1 |
| NEG-M15-65 | 重跑失败伪造成完成 | `record_rerun_completed(rerun_result.status="FAILED")` | 抛 `reason="RERUN_RESULT_NOT_SUCCESS"`；必须走 `record_rerun_failed` | §4.2 R08 |
| NEG-M15-66 | 未重跑算未变化 | 只 `record_pruning`，然后 `record_not_rerun("sampling")` | 报告 `unresolved=1`、`rerun_completed=0`、`observable_rate is None`、`prr_point_estimate is None`；**不得**报 0 | §4.2 R08；分母纪律 |
| NEG-M15-67 | 无分母报 0 | 空台账 `prr_report()` | `pruned=0`；`observable_rate is None`；`upper_bound_95 is None`；`prr_point_estimate is None` | §4.2 R08 |
| NEG-M15-68 | **跨任务合并** | 调 `PrrLedger("task_A")` 写入 `task_B` 的节点/账目；或寻找 `merge/aggregate` | 台账构造/写入拒绝；`assert_task_scoped()` 返回无合并入口；`hasattr(PrrLedger,"merge") is False` | 策划书 §4.3 |
| NEG-M15-69 | 只留汇总不留逐节点行 | 构造 `PrrReport(rows=(), pruned=1)` | 构造抛 `reason="PRR_ROWS_INCOMPLETE"` | §4.2 R08 |
| NEG-M15-70 | 覆盖率不足仍给点估计 | 构造 `PrrReport(coverage=0.5, prr_point_estimate=0.0)` | 构造抛 `reason="PRR_POINT_WITHOUT_FULL_COVERAGE"` | §4.2 R08 |
| NEG-M15-71 | 随机节点被剪枝 | `record_rerun_completed(node_is_stochastic=True)` | `changed=True`；`comparison_basis=RANDOM_NODE_CONSERVATIVE_CHANGE`；`violation="PRUNED_STOCHASTIC_NODE"`；报告 `violations=1` | §8.2 R06；保守方向 |
| NEG-M15-72 | 零错误只写 0 | 1 个剪枝、重跑未变化 | `changed=0`、`rerun_completed=1`、`upper_bound_95` 非空且 >0；摘要必须带分母 | §4.2 R08；§4.3 |
| NEG-M15-73 | 事件时间非法但状态已改 | `record_rerun_started(at="not-a-time")` | 抛 `EVENT_TIME_INVALID`；episode 仍为 `PRUNED`（未留下半套状态） | 本文件 `_require_at` |

## E. 误拒守卫（防止“过度收紧”）

| ID | 守卫目标 | 输入 / 操作 | 期望 | 依据 |
|---|---|---|---|---|
| GUARD-M15-01 | **合格纯节点签出 DC** | `PURE_FUNCTION`、k=3 跨进程跨目录、产物/指标一致、环境/规则一致、有效期 1 天、签名端口回验成功 | `eligible=True`；`issue_dc` 返回 `DcIssuance`；`record.k_runs=3`；`created_new=True`；审计 1 条 | §8.2 |
| GUARD-M15-02 | **五项全过才 SKIP** | 有效 DC、前驱未变、磁盘一致、Gate 复检通过、无副作用、签名端口回验成功 | `action=SKIP`；`record.spa_id` 稳定；`skip_reason=VALID_DC_AND_ALL_FIVE_CHECKS_PASS` | §8.3 |
| GUARD-M15-03 | 同一输入两次同 ID | 同一 `DcIdentity` 两次 `compute_dc_id`；同一 `SpaIdentity` 两次 `compute_spa_id` | 两次哈希逐字符相同；JCS 与 `json.dumps(sort_keys=True)` 在 astral 字符上不同（跨实现检查） | OQ-P9-01；ENCODING_RULES §5 |
| GUARD-M15-04 | 合格剪枝进入 PRR 且算 unchanged | 1 个纯节点、SPA 授权完整、重跑结果逐项一致 | `changed=False`；`prr_point_estimate=0.0`（coverage=1）；`upper_bound_95≈4.99%`（n 视样本） | §4.2 R08 |
| GUARD-M15-05 | 纠错不覆盖历史 | 先记 `changed=True`，再 `record_correction(False)` | 事件数 +1；原事件仍在；`episode.changed=False`；`correction_count=1` | 附录 D.6 |
| GUARD-M15-06 | 自检全绿 | 依次调用 `assert_randomness_is_veto/assert_conservative_defaults/assert_scope_statement/assert_signature_domain/assert_dc_scope/assert_revocation_is_terminal/assert_default_reexecute/assert_evidence_is_not_boolean/assert_no_unsigned_skip/assert_no_side_effect_skip/assert_denominator_policy/assert_no_zero_without_denominator/assert_task_scoped/assert_prr_records_raw` | 全部返回 `[]` | 本阶段验收判据 |

## F. 执行记录模板（落地阶段填写，P9 留空）

| ID | 命令 | 退出码 | 断言到的原因 | 日志路径 | 结论 |
|---|---|---|---|---|---|
| NEG-M15-01 | （待执行） | — | — | — | 未执行 |
| NEG-M15-02 | （待执行） | — | — | — | 未执行 |
| NEG-M15-05 | （待执行） | — | — | — | 未执行 |
| NEG-M15-09 | （待执行） | — | — | — | 未执行 |
| NEG-M15-35 | （待执行） | — | — | — | 未执行 |
| NEG-M15-37 | （待执行） | — | — | — | 未执行 |
| NEG-M15-40 | （待执行） | — | — | — | 未执行 |
| NEG-M15-50 | （待执行） | — | — | — | 未执行 |
| NEG-M15-52 | （待执行） | — | — | — | 未执行 |
| NEG-M15-60 | （待执行） | — | — | — | 未执行 |
| NEG-M15-66 | （待执行） | — | — | — | 未执行 |
| NEG-M15-68 | （待执行） | — | — | — | 未执行 |
| GUARD-M15-01 | （待执行） | — | — | — | 未执行 |
| GUARD-M15-02 | （待执行） | — | — | — | 未执行 |