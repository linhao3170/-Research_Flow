# 伪代码阶段日志（STAGE_LOG）

> 轻收尾日志，只追加，不改历史。
> 行数口径：`git show --numstat` 的插入行（含空行）；文件数与冻结基线提交 `1c9a104` 一致。

## P1 契约对齐与配置基座 · 2026-11-11

- 模块：M01_contracts、M03_config_env
- 产出文件数 / 总行数：14 / 3,229
- 验收状态：已验收（2026-11-11）
- 遗留 OQ 编号：OQ-P1-02（DEFERRED）；OQ-P1-03、OQ-P1-05（NEEDS_CONFIRMATION，原问题与裁决正文缺失，待用户补证；不得作为先例）
- 越界检查结论：契约与配置层不产生状态、证据或凭证；未发现 E0 推动状态、非 Collector 产生 E2、Verifier 复用 Executor 状态的路径（静态核对，未运行验证）。

## P2 持久层与状态机 · 2026-11-11

- 模块：M02_state_machine
- 产出文件数 / 总行数：10 / 5,991
- 验收状态：已验收（2026-11-12；设计件）
- 验收依据：用户 2026-11-12 指令按 C 执行；完整性/一致性审查通过，详见 `reports/pseudocode/P2_P8_ACCEPTANCE_REVIEW.md`；§12-2/§12-6/§12-7/§12-8 仍 OPEN，WP-03 不得以本阶段已验收启动。
- 遗留 OQ 编号：OQ-DB-2；§12-1～§12-10（均 OPEN）
- 越界检查结论：`StateMachine` 为唯一状态写入口；未发现 Agent/LLM 直写状态或证据的路径；重启恢复只重放既有事实（静态核对，未运行验证）。

## P3 DAG 与执行器 · 2026-11-11

- 模块：M04_dag、M05_executor
- 产出文件数 / 总行数：14 / 7,858
- 验收状态：已验收（2026-11-12；设计件）
- 验收依据：用户 2026-11-12 指令按 C 执行；完整性/一致性审查通过，详见 `reports/pseudocode/P2_P8_ACCEPTANCE_REVIEW.md`；开放 OQ 不因验收关闭。
- 遗留 OQ 编号：OPEN：OQ-P3-01/05/06/07/08/10；DEFERRED：OQ-P3-02/03/04/09/11/12
- 越界检查结论：Executor 只执行、不裁决成功，不写 E2；Verifier 工作目录与 Executor 分离；未发现越界路径（静态核对，未运行验证）。

## P4 模板与证据链 · 2026-11-11

- 模块：M06_templates、M07_evidence
- 产出文件数 / 总行数：14 / 6,109
- 验收状态：已验收（2026-11-12；设计件）
- 验收依据：用户 2026-11-12 指令按 C 执行；完整性/一致性审查通过，详见 `reports/pseudocode/P2_P8_ACCEPTANCE_REVIEW.md`；E3 写入路径等开放 OQ 不因验收关闭。
- 遗留 OQ 编号：OPEN：OQ-P4-01/02/04/05/06/07/09/10/12；DEFERRED：OQ-P4-03/08/11
- 越界检查结论：Collector 单写 E0–E2 并拒收 E3；模板只产出执行事实；E3 写入路径未在 P4 实现（OQ-P4-01 挂起）（静态核对，未运行验证）。

## P5 门控与三级验证 · 2026-11-11

- 模块：M08_gate、M09_verifier_l12、M10_verifier_l3
- 产出文件数 / 总行数：16 / 7,923
- 验收状态：已验收（2026-11-12；设计件）
- 验收依据：用户 2026-11-12 指令按 C 执行；完整性/一致性审查通过，详见 `reports/pseudocode/P2_P8_ACCEPTANCE_REVIEW.md`；L3 未真实重跑，开放 OQ 不因验收关闭。
- 遗留 OQ 编号：OPEN：OQ-P5-01/02/03/04/09/10/12；DEFERRED：OQ-P5-05/06/07/08/11
- 越界检查结论：Gate 不补造证据；L3 在新目录、独立进程从原始数据重跑；E3 仅由 Verifier 写入且写入路径仍挂 OQ-P4-01/OQ-P5-04，未设计绕过路径（静态核对，未运行验证）。

## P6 签名与离线凭证 · 2026-11-11

- 模块：M11_signing、M12_bundle
- 产出文件数 / 总行数：11 / 7,584
- 验收状态：已验收（2026-11-12；设计件）
- 验收依据：用户 2026-11-12 指令按 C 执行；完整性/一致性审查通过，详见 `reports/pseudocode/P2_P8_ACCEPTANCE_REVIEW.md`；非 VERIFIED 签名口径等开放 OQ 不因验收关闭。
- 遗留 OQ 编号：OPEN：OQ-P6-01/02/03/04/06/07/08/09/10/11；DEFERRED：OQ-P6-05/12
- 越界检查结论：仅 `VERIFIED` 报告允许签名；非 VERIFIED 结果不产生带签名报告；信任锚在包外；未发现非 VERIFIED 签发凭证的路径（静态核对，未运行验证）。

---

> 冻结范围：本次只登记 P1–P6（M01–M12，83 文件）。M13/M14/M17/M18 属 P7/P8，未纳入本次提交。

## P9 DC/SPA 与 VAS · 2026-11-11

- 模块：M15_dcspa、M16_vas
- 产出文件数 / 总行数：11 / 7,122（含 2026-11-11 复核横幅 +4 行；六个 `.py` 行数未变）
- 验收状态：待验收（IN_REVIEW）
- 遗留 OQ 编号：OPEN：OQ-P9-01/02/03/06/07/08/10/12/15；DEFERRED：OQ-P9-04/05/09/11/14；DECIDED：OQ-P9-13
- 越界检查结论：DC 只签“经验性资格”，随机性/副作用节点一票否决；SPA 默认 REEXECUTE，五项缺证据不跳过；
  PRR 逐节点、单任务、无合并；VAS 强制集合先占预算，四策略同预算。M11 对未冻结 DC/SPA 载荷的拒绝
  使 P9 无合规签名器，已登记为 OQ-P9-03，未把签名写成已实现（静态核对，未运行验证）。

> 2026-11-11 事故与恢复：22:13–22:21 有并发进程把 M15 的 4 个模块与 M16 的 `knapsack.py`/`risk_features.py` 重写后删除，并开始写 `M19_api`。并发停止后按同一验收口径重写并落盘：
> 四个 M15 模块为 `dc_eligibility.py` 1,173 行、`dc_issuer.py` 1,035 行、`spa_judge.py` 1,227 行、`prr_ledger.py` 830 行；VAS 为 `knapsack.py` 747 行、`risk_features.py` 614 行。
> 行数按实测重记（原报 7,427 与磁盘从未一致）；负例符号对照见两份 `NEGATIVE_TESTS.md` §0.1；未运行 pytest、未导入被测模块、未 commit。

## P9 复核修正 · 2026-11-11

> 本节取代上方 P9 条目的“待验收（IN_REVIEW）”口径；当前状态以 `docs/state/project_state.json` 的 `pseudocode_stages.P9` 为准。

- 事实：2026-11-11 22:53:54–55，6 个 `.py` 由并发进程重写并落盘；这不是原始正文恢复，原始正文仍不可追溯。
- 实测：P9 共 11 文件 / 7,122 行（M15 6 / 4,772；M16 5 / 2,350；含复核横幅 +4 行）；`INDEX.md` 曾写 7,030，已按实测修正。
- 六个文件：`dc_eligibility.py`、`dc_issuer.py`、`spa_judge.py`、`prr_ledger.py`、`risk_features.py`、`knapsack.py`；逐项 SHA256、时间与行数见 `reports/remediation/P0_OPEN_ISSUES.md`。
- 状态：`BLOCKED`。并发重写产物的来源/版本/接口一致性未确认，且未运行 pytest、未导入被测模块、未验收；不得标 `ACCEPTED`。
- 关联 OQ：`OQ-P9-16`（并发写入）仍 OPEN；`OQ-P9-17` 的“已重写落盘”不等于阶段验收。

## P7 调度与定向恢复 · 2026-11-11（补登）

- 模块：M13_scheduler、M14_recovery
- 产出文件数 / 总行数：11 / 6,576
- 验收状态：已验收（2026-11-12；设计件；P7 属 T1 方向）
- 验收依据：用户 2026-11-12 指令按 C 执行；完整性/一致性审查通过，详见 `reports/pseudocode/P2_P8_ACCEPTANCE_REVIEW.md`；验收不表示调度/恢复运行时已实现。
- 遗留 OQ 编号：OQ-P7-01～OQ-P7-12（均 OPEN 或 DEFERRED，详见 `OPEN_QUESTIONS.md`）。
- 越界检查结论：Scheduler 只选择 READY，不写 Task/Node 状态；Recovery 只生成/冻结计划，`INVALIDATED→READY` 仍由 StateMachine 守卫（静态核对，未运行验证）。
- 说明：本条目为 2026-11-11 P0 整改补登，不表示用户已验收 P7。

## P8 六角色与知识库 · 2026-11-11（补登）

- 模块：M17_agents、M18_knowledge
- 产出文件数 / 总行数：15 / 9,361
- 验收状态：已验收（2026-11-12；设计件；P8 属 T1）
- 验收依据：用户 2026-11-12 指令按 C 执行；完整性/一致性审查通过，详见 `reports/pseudocode/P2_P8_ACCEPTANCE_REVIEW.md`；验收不表示 Agent/知识库运行时已实现。
- 遗留 OQ 编号：OQ-P8-01～OQ-P8-13（其中 OQ-P8-13 为 DECIDED，其余 OPEN/DEFERRED）。
- 越界检查结论：Agent 只提交工具/证据请求，不直接写状态、证据、报告或凭证；知识库 T1 才装配（静态核对，未运行验证）。
- 说明：本条目为 2026-11-11 P0 整改补登，不表示用户已验收 P8。

## P10 接入、实验与交付（M19）· 2026-11-11（仅登记）

- 模块：M19_api
- 现有文件数 / 行数：5 / 2,138；无 `MODULE.md`、`NEGATIVE_TESTS.md`、阶段日志和 OQ。
- 验收状态：`BLOCKED`；仅确认文件存在，不代表获得正式开发授权。
- 约束：不删除 M19，不扩大 P10 开发范围，不标 `ACCEPTED`；等待用户确认是否授权及是否补齐文档。
- 说明：新增文件时间为 2026-11-11 22:22–22:25；Git 状态为未跟踪目录，本轮未 commit、未清理。
