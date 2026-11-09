# 07 T0 依赖图与质量门禁（v1.0）

> 冻结日期：2026-11-10｜状态：**G0 冻结**｜被取代版本：**v0.2（候选）**｜G0 门禁 PASS 由用户宣布，本文不代替门禁判定。
> 状态：**G0 文档 ⑦ v1.0（G0 冻结）**；已写入 `WP-01` 依赖矩阵锁定基线与解释器硬约束；**不是 G0 门禁 PASS，不是 T0 开发批准**。
> 日期：2026-11-10（Asia/Shanghai）；候选期内容更新于 2026-11-09。
> 基线：术语按 [01](../G0/01_BASELINE_AND_TERMS.md) v1.0；需求按 [02](../PRD/02_REQUIREMENT_TRACEABILITY.md) v1.0；故事按 [03](../PRD/03_PRD_T0.md) v1.0；架构按 [04](04_ARCHITECTURE.md) v1.0；契约/状态按 [05](05_CONTRACTS_AND_STATES.md) v1.0；数据/API 按 [06](06_DATA_AND_API.md) v1.0；机器可读契约按 [`contracts/`](../../contracts/)（G0 文档 ⑨ v1.0）。
> 工作量说明：本文的“工程量级”是 `【工程建议】` 的估算，**不是实测工期**，不得写入对外材料当作承诺。

## 1. 唯一 T0 依赖图

### 1.1 主线

【用户决议 C1】附录 J 为 T0 工作包基线；`WP-R` 放在 `WP-13` 之后、`WP-14` 之前。

```text
WP-01 仓库/环境锁定
  → WP-02 核心契约落地（schema → Pydantic/API）
  → WP-03 SQLite + StateMachine + audit_log
  → WP-04 DAG Builder（静态）
  → WP-05 内置数据与 ML 模板
  → WP-06 Executor
  → WP-07 Collector
  → WP-08 Gate
  → WP-09 Verifier L1/L2
  → WP-10 Verifier L3
  → WP-11 Ed25519/JCS/Merkle + 信任锚
  → WP-12 Evidence Bundle + verify_bundle
  → WP-13 最小工作台
  → WP-R  FR-010 最小切片（B1）
  → WP-14 端到端验收
```

### 1.2 允许的并行

| 并行组 | 条件 |
|---|---|
| `WP-04` 与 `WP-05` | `WP-02` 完成后可并行 |
| `WP-09` 与 `WP-11` | `WP-07` 完成后可并行（L1/L2 不依赖签名） |
| `WP-12` 与 `WP-13` | `WP-11` 完成后可并行 |
| `WP-R` 与 `WP-13` | 用户要求 `WP-R` 在 `WP-13` 后；可与其收尾重叠，但不得早于 `WP-09` |

### 1.3 关键路径

`WP-01 → WP-02 → WP-03 → WP-06 → WP-07 → WP-08 → WP-10 → WP-11 → WP-12 → WP-14`。`WP-04/05/09/13` 可部分并行，但 `WP-14` 必须等全部完成（含 `WP-R`）。

## 2. 工作包

### 2.1 WP-01 仓库/环境锁定

| 项 | 内容 |
|---|---|
| 目标 | Python 3.11.16（64 位）锁定、依赖锁定、目录骨架、启动脚本；依赖解析以锁定矩阵为准 |
| 入口 | ① 用户批准 T0 启动；② G0 文档 ⑦ v1.0 与 ⑨ v1.0 已冻结；③ **依赖矩阵 [`09_dependency_matrix.md`](../verification/g0/09_dependency_matrix.md) 已按 2026-11-10 裁决锁定为 WP-01 基线**（17 个第三方包：fastapi、pydantic、networkx、pandas、scikit-learn、cryptography、streamlit、pytest、uv、numpy、scipy、pydantic-core、starlette、cffi、pyarrow、pillow、protobuf；另 SQLite 随解释器；均为 cp311 win_amd64 或纯 Python wheel）；④ 解释器硬约束已确认（见下） |
| 交付 | 依赖锁文件（`uv.lock` 或等效）、启动脚本、`.gitignore` 复核、环境指纹脚本、TestClient 冒烟日志 |
| 出口 | 干净环境可安装并启动；版本记录可追溯；解释器指纹为 `3.11.16` + `64bit`；安装解析与矩阵逐项一致（偏差必须有记录）；FastAPI `TestClient` 冒烟通过 |
| 依赖 | 无（受 G0 冻结与依赖矩阵约束） |
| FR/NFR | 支撑 `NFR-01`、`NFR-06` |
| 证据 | `docs/verification/t0/wp-01/{env_fingerprint.json,lockfile.txt,dependency_resolution.txt,testclient_smoke.log,starlette_resolution.txt,startup.log}` |
| 工程量级 | 2–3 人日（`【工程建议】`） |
| 风险 | 依赖版本漂移；禁止运行期安装；解释器架构错配导致“找不到匹配的发行版” |

**WP-01 解释器硬约束（用户 2026-11-10 裁决，逐条执行）**

1. 建 venv 只能使用 uv 托管的 3.11.16：

   ```powershell
   uv venv --python 3.11.16 .venv
   ```

   不得使用 PATH 上的 `python`（3.12），不得使用 `py -3.11`（指向 32 位 3.11.0）。

2. 建完立即验证解释器指纹：

   ```powershell
   & .\.venv\Scripts\python.exe -c "import sys,platform;print(sys.version, platform.architecture()[0])"
   ```

   输出必须同时出现 `3.11.16` 与 `64bit`；任一不满足即停止，不得继续安装。

3. 安装出现“找不到匹配的发行版”（`No matching distribution found`）时，**第一反应是解释器版本/架构错误，不是网络问题**；先重跑第 2 步确认指纹，再排查索引或网络。

4. `starlette` 安装后必须跑一次 FastAPI `TestClient` 冒烟：

   ```powershell
   & .\.venv\Scripts\python.exe -c "from fastapi import FastAPI; from fastapi.testclient import TestClient; app=FastAPI(); app.get('/health')(lambda: {'ok': True}); r=TestClient(app).get('/health'); print('TESTCLIENT_OK', r.status_code, r.json()); assert r.status_code==200 and r.json()=={'ok': True}"
   ```

   失败则回退 `starlette` 到 `fastapi` 声明的兼容下界（fastapi 0.162.2 声明 `starlette>=0.46.0`，即 0.46.0 线），并把实测 `fastapi`/`starlette` 组合、失败日志与回退理由写入 `wp-01/` 证据；不得凭猜测定版。

5. 依赖解析必须与 [`09_dependency_matrix.md`](../verification/g0/09_dependency_matrix.md) 的锁定基线逐项一致；任何偏差（版本、wheel 类型、来源）必须在 `wp-01/` 证据中记录原因，不得静默升级或改用其它解释器。

### 2.2 WP-02 核心契约落地

| 项 | 内容 |
|---|---|
| 目标 | 把 G0 ⑨ 的 `contracts/*.schema.json` 落成 Pydantic v2 模型，接入 API/StateMachine/DB，并保持 schema ↔ 模型一致 |
| 入口 | G0 通过（⑨ 随 G0 冻结）；`contracts/` 与 `scripts/validate_contracts.py` 已存在且真实 exit 0 |
| 交付 | Pydantic v2 模型、schema↔模型差异检查、API 请求/响应绑定、422 字段路径映射 |
| 出口 | schema 正例/反例在模型层同样通过/拒绝；`validate_contracts.py` 仍 exit 0；字段/枚举/必填与 schema 完全一致；未知字段拒绝 |
| 依赖 | `WP-01`；**G0 文档 ⑨** |
| FR/NFR | `FR-001`、`FR-005`、`FR-008`；`NFR-02` |
| 证据 | `docs/verification/t0/wp-02/{model_parity.json,schema_validation.log,api_422.log}` |
| 工程量级 | 3–4 人日（`【工程建议】`；Schema 与正反例已在 G0 完成，本包不重复造） |
| 风险 | schema 与 Pydantic 双份定义漂移；`HarnessEvent`/`DomainPack` 未冻结，不得阻塞 T0 |

### 2.3 WP-03 SQLite + StateMachine + audit_log

| 项 | 内容 |
|---|---|
| 目标 | 迁移脚本、单写者状态机、成功/失败双路审计、非法迁移拒绝、`INVALIDATED` 迁移与守卫 |
| 入口 | `WP-02` 完成；06 表结构确认（含 `plan_id`/`plan_hash`、`error_code`） |
| 交付 | 迁移脚本、`StateMachine.transition()`、成功同事务审计、失败独立事务 `DENIED` 审计、守卫（含计划三条件）、旁路防护 |
| 出口 | 合法迁移成功并写 `OK` 审计；非法迁移/旁路写库被拒；**失败迁移回滚后 `DENIED` 记录仍存在**；审计二次失败降级 stderr 且被测试捕获；`INVALIDATED` 两条边按守卫执行 |
| 依赖 | `WP-02` |
| FR/NFR | `FR-003`、`FR-010`（T0 部分）；`NFR-05`、`NFR-04`（部分） |
| 证据 | `docs/verification/t0/wp-03/{transitions.jsonl,illegal.log,direct_write.log,audit_log.jsonl,denied_survives_rollback.log,audit_degraded_stderr.log,invalidated_guard.log}` |
| 工程量级 | 7–9 人日（`【工程建议】`；新增失败审计双事务与守卫测试） |
| 风险 | 双事务语义写错会“失败无审计”；`INVALIDATED` 守卫依赖 `WP-R` 的计划文件约定，需接口先对齐 |

### 2.4 WP-04 DAG Builder（静态）

| 项 | 内容 |
|---|---|
| 目标 | 建图、拓扑、环/孤立/重复边/缺失依赖校验、图版本 |
| 入口 | `WP-02` 完成 |
| 交付 | 建图器、校验器、`graph_version` 生成 |
| 出口 | 非法图全部拒绝；合法图版本固定可重放 |
| 依赖 | `WP-02` |
| FR/NFR | `FR-002` |
| 证据 | `docs/verification/t0/wp-04/{cycle.json,orphan.json,duplicate_edge.json,graph_version.json}` |
| 工程量级 | 3–4 人日 |
| 风险 | 与 T1 Scheduler 的边界混淆；本包不含调度 |

### 2.5 WP-05 内置数据与 ML 模板

| 项 | 内容 |
|---|---|
| 目标 | 离线数据集、固定模板、参数 Schema、Split Manifest |
| 入口 | `WP-02` 完成 |
| 交付 | 数据集与哈希、模板注册表项、参数 Schema、Split Manifest 生成 |
| 出口 | 冒烟任务可跑；数据哈希可复核；参数越界拒绝 |
| 依赖 | `WP-02` |
| FR/NFR | `FR-004`、`NFR-01` |
| 证据 | `docs/verification/t0/wp-05/{dataset_hashes.json,template_registry.json,split_manifest.json,smoke.log}` |
| 工程量级 | 3–5 人日 |
| 风险 | 数据许可/隐私（`NFR-08`） |

### 2.6 WP-06 Executor

| 项 | 内容 |
|---|---|
| 目标 | 白名单执行、独立目录、子进程、超时、退出码、资源采集、进程树回收 |
| 入口 | `WP-03`、`WP-05` 完成 |
| 交付 | 执行器、工作目录管理、资源限制、执行事件 |
| 出口 | 未注册模板拒绝；目录隔离；超时回收；产物哈希与资源峰值记录 |
| 依赖 | `WP-03`、`WP-05` |
| FR/NFR | `FR-004`；`NFR-06` |
| 证据 | `docs/verification/t0/wp-06/{unregistered.log,isolation.json,timeout_tree.log,artifact_hashes.json}` |
| 工程量级 | 6–8 人日 |
| 风险 | 进程树回收在 Windows 上的可靠性；受控子进程不等于沙箱 |

### 2.7 WP-07 Collector

| 项 | 内容 |
|---|---|
| 目标 | E0/E1/E2 追加、`event_seq` 单调、哈希链、重复/乱序检测 |
| 入口 | `WP-06` 完成 |
| 交付 | 采集器、单写队列、链计算、`ingestion_log` |
| 出口 | 重复幂等；乱序/缺口检测；篡改可发现；E0/E1 不推进状态 |
| 依赖 | `WP-06` |
| FR/NFR | `FR-005`；`NFR-03` |
| 证据 | `docs/verification/t0/wp-07/{event_seq.jsonl,duplicate.jsonl,gap.log,tamper.log}` |
| 工程量级 | 5–7 人日 |
| 风险 | 并发下序号分配；链起点约定（`OQ-CT-10`） |

### 2.8 WP-08 Gate

| 项 | 内容 |
|---|---|
| 目标 | 覆盖矩阵、缺口码、规则版本、冲突拒绝、**按 `evidence_invalidations` 拒绝 stale 证据**、E2/E3 要求 |
| 入口 | `WP-07` 完成；规则集冻结；06 的 `evidence_invalidations` 可读 |
| 交付 | Gate 评估器、`GAP` 输出、规则版本绑定、stale 判定（引用失效记录的 `evidence_id`） |
| 出口 | 缺必检证据不 PASS；版本不匹配拒绝；**stale 证据不满足必检项——即使它仍在证据包/DB 中、哈希仍然有效**；失效记录缺失时按“未失效”处理不得反向使用 |
| 依赖 | `WP-07` |
| FR/NFR | `FR-006`；`NFR-02` |
| 证据 | `docs/verification/t0/wp-08/{coverage_matrix.json,gap.json,stale_reject.log,stale_in_bundle_reject.log}` |
| 工程量级 | 7–9 人日（`【工程建议】`；新增失效记录判定与“包内 stale”负例） |
| 风险 | 规则集与 Domain Pack 的耦合；不得用自由文本替代缺口码；不得把“stale”实现成“删除证据” |

### 2.9 WP-09 Verifier L1/L2

| 项 | 内容 |
|---|---|
| 目标 | 过程完整性（哈希/序列/Merkle/目录复用检测）与结果自洽（指标重算、泄漏五规则） |
| 入口 | `WP-07` 完成 |
| 交付 | L1、L2 检查器与报告片段 |
| 出口 | 旧产物/错误指标/泄漏被拒 |
| 依赖 | `WP-07` |
| FR/NFR | `FR-007` |
| 证据 | `docs/verification/t0/wp-09/{l1.json,l2.json,leakage_cases.json}` |
| 工程量级 | 6–8 人日 |
| 风险 | 泄漏规则阈值需领域确认 |

### 2.10 WP-10 Verifier L3

| 项 | 内容 |
|---|---|
| 目标 | 新目录、独立进程、原始数据重读、真实重训/推理、差异归因 |
| 入口 | `WP-09` 完成 |
| 交付 | L3 执行器、Split Manifest 校验、差异归因 |
| 出口 | 假 L3 被拒；真实重跑成功；差异可归因 |
| 依赖 | `WP-09`、`WP-06`（复用执行能力，但独立进程） |
| FR/NFR | `FR-007` |
| 证据 | `docs/verification/t0/wp-10/{l3_retrain.log,fake_l3_reject.log,diff_attribution.json}` |
| 工程量级 | 8–10 人日 |
| 风险 | 随机性节点一致性判定；环境漂移 |

### 2.11 WP-11 Ed25519/JCS/Merkle + 信任锚

| 项 | 内容 |
|---|---|
| 目标 | JCS 规范化、Ed25519 签名、Merkle 包含证明、密钥与信任锚 |
| 入口 | `WP-07` 完成 |
| 交付 | 签名/验签模块、密钥生成与存储、信任锚配置、标准测试向量 |
| 出口 | 标准向量通过；换公钥/改载荷验签失败；私钥不进包/日志 |
| 依赖 | `WP-07` |
| FR/NFR | `FR-008`；`NFR-05` |
| 证据 | `docs/verification/t0/wp-11/{rfc_vectors.log,sign_verify.log,key_fingerprint.json}` |
| 工程量级 | 5–7 人日 |
| 风险 | 规范化细节（数组顺序、重复键）；密钥存储形态（`OQ-ARCH-5`） |

### 2.12 WP-12 Evidence Bundle + verify_bundle

| 项 | 内容 |
|---|---|
| 目标 | 导出完整证据包；独立离线验签工具 |
| 入口 | `WP-10`、`WP-11` 完成 |
| 交付 | 导出器、`verify_bundle.py`、包内清单与 README |
| 出口 | 真包在独立环境通过（G6-T0）；缺件/篡改被拒 |
| 依赖 | `WP-10`、`WP-11` |
| FR/NFR | `FR-009`；`NFR-07` |
| 证据 | `docs/verification/t0/wp-12/{bundle/,verify_true.log,verify_negative.log}` |
| 工程量级 | 5–7 人日 |
| 风险 | 离线工具误依赖 DB/模型；信任锚被包内公钥替代 |

### 2.13 WP-13 最小工作台

| 项 | 内容 |
|---|---|
| 目标 | 任务、DAG、证据、报告四视图 |
| 入口 | `WP-08`、`WP-12` 完成 |
| 交付 | 四视图页面、只读证据与报告 |
| 出口 | 用户可走查；页面不写状态/证据 |
| 依赖 | `WP-08`、`WP-12` |
| FR/NFR | 支撑 `FR-001`–`FR-009` 的可见性 |
| 证据 | `docs/verification/t0/wp-13/{screenshots/,walkthrough.md}` |
| 工程量级 | 4–6 人日 |
| 风险 | 范围扩张到六页工作台；`OQ-ARCH-3` |

### 2.14 WP-R FR-010 最小切片

| 项 | 内容 |
|---|---|
| 目标 | 失效传播、**确定性可重放**的计划生成与内容寻址冻结、受影响后代保守重跑、stale 拒绝；**不引入 Recovery 状态机** |
| 入口 | `WP-13` 完成；`OQ-CT-11/13` 已由决议 5/6 关闭；06 的计划存储根目录确认 |
| 交付 | 失效传播、计划生成器（纯函数）、内容寻址写入（临时文件 + fsync + rename）、`audit_log` 冻结记录、`INVALIDATED → READY` 守卫、重跑编排 |
| 出口 | 上游变化 → 受影响后代 `INVALIDATED`；**同输入两次生成同一 `plan_hash`**；计划文件不可改写；守卫三条件（文件缺失 / hash 不符 / 先重跑后冻结）各有一条 `DENIED` 负例；受影响后代全部重跑；包内 stale 证据不满足必检项；T0 代码与 DB 中不出现 `PROPOSED`/`APPROVED` |
| 依赖 | `WP-13` |
| FR/NFR | `FR-010`（T0 最小） |
| 证据 | `docs/verification/t0/wp-r/{invalidated.jsonl,plan_hash_repeat.json,plan_store.json,plan_missing_denied.log,plan_hash_mismatch_denied.log,plan_not_frozen_denied.log,rerun.jsonl,stale_reject.log}` |
| 工程量级 | 6–8 人日（`【工程建议】`；新增确定性复算与三条守卫负例） |
| 风险 | 失效范围过宽/过窄；计划正文含时间戳/随机序导致 `plan_hash` 不稳定；与 T1 完整 Recovery 的边界 |

计划确定性约束（决议 6）：计划正文只含受影响节点、原因、输入/图版本、规则版本等可复算字段；**生成时间不得进入计划正文或 `plan_hash`**，`frozen_at` 只写 `audit_log`。节点顺序按确定性拓扑序排序，不得依赖字典/集合迭代顺序。

### 2.15 WP-14 端到端验收

| 项 | 内容 |
|---|---|
| 目标 | 断网、无模型、单机跑通主场景与失效场景；导出并离线验签 |
| 入口 | `WP-01`–`WP-13`、`WP-R` 全部完成 |
| 交付 | 端到端报告、证据包、验签日志 |
| 出口 | G1、G2、G3、G6-T0 条件满足；三次重复一致 |
| 依赖 | 全部 |
| FR/NFR | `FR-001`–`FR-010`；`NFR-01`–`NFR-08`（T0 部分） |
| 证据 | `docs/verification/t0/e2e/{run_1,run_2,run_3}/`、`e2e_report.md` |
| 工程量级 | 3–5 人日 |
| 风险 | 环境残留；离线性未真正断开 |

## 3. 测试策略

### 3.1 分层

【策划书】§6.7 / TABLE 30：

| 层 | 对象 | T0 要求 |
|---|---|---|
| 单元 | 状态机、指纹、Gate、失效传播 | 非法迁移全部拒绝；核心分支覆盖 |
| 契约 | 消息/API/Domain Pack | T0 只做 API 与契约；消息协议属 T1 |
| 权限 | 写状态/证据/私钥/越界路径 | 越权全部拒绝并审计 |
| 集成 | Executor→Collector→Gate→Verifier→Certificate | 完整闭环成功 |
| 对抗 | F-1 至 F-7 变体 | 每类有预期状态与原始证据 |
| 离线 | 断网、无模型、单机 | 完成并导出可验签证据包 |

### 3.2 T0 测试矩阵（摘要）

| 测试 ID | 覆盖 | 类型 | 证据 |
|---|---|---|---|
| `T0-UT-SM-*` | `FR-003`、`INVALIDATED` | 单元 | `tests/t0/test_fr_003*` |
| `T0-UT-DAG-*` | `FR-002` | 单元 | `tests/t0/test_fr_002*` |
| `T0-CT-API-*` | `FR-001`、`FR-009` | 契约 | `tests/t0/test_fr_001*` |
| `T0-CT-SCHEMA-*` | 05 全部契约；复用 `contracts/examples/` 正反例做模型层对照 | 契约 | `tests/t0/test_contracts*` |
| `T0-CT-API-404-*` | 决议 8：`POST /recover` 未注册，访问 404 且无状态变化 | 契约 | `tests/t0/test_fr_001_no_recover*` |
| `T0-UT-REC-*` | 决议 6：计划 `plan_hash` 确定性复算 + 守卫三条件负例 | 单元 | `tests/t0/test_fr_010_minimal*` |
| `T0-UT-SM-DENIED-*` | 决议 7：`DENIED` 审计在回滚后仍存在；二次失败降级 stderr | 单元/集成 | `tests/t0/test_fr_003_denied*` |
| `T0-SEC-BIND-*` | 决议 8：非回环且无 token 拒绝启动；端口未监听 | 权限/负例 | `tests/t0/test_security_bind*` |
| `T0-PM-*` | 单写者/越权 | 权限 | `tests/t0/test_permissions*` |
| `T0-IT-E2E-*` | 主闭环 | 集成 | `tests/t0/test_e2e*` |
| `T0-ADV-*` | 假 L3/E0 推进/篡改 | 对抗 | `tests/t0/test_adversarial*` |
| `T0-OFF-*` | 断网/无模型 | 离线 | `tests/t0/test_nfr_01*` |
| **`T0-G6T0-*`** | **G6-T0** | 独立环境 | `tests/t0/test_g6_t0*` + `docs/verification/t0/g6-t0/` |

### 3.3 G6-T0 必须落到测试矩阵

【用户指令】G6-T0 单列，不得用“证据包可用后”推后：

| 检查项 | 通过条件 | 证据 |
|---|---|---|
| 环境隔离 | 另一目录/另一设备/另一 Windows 用户 | `g6-t0/env_isolation.log` |
| 外部可信指纹 | 信任锚来自包外，非包内公钥 | `g6-t0/trust_store.json` |
| 真包通过 | `verify_bundle.py` 返回成功 | `g6-t0/true_bundle.verify.log` |
| 五类负例 | **归 G6 完整版（T1）**，不在 T0 | — |

## 4. G0–G7 质量门禁

【策划书】§15.3 / TABLE 57；【用户决议】G6 拆分、G4 归 T1。

### 4.1 G0 规格冻结

| 项 | 内容 |
|---|---|
| 输入 | ①–⑧ 文档包 + **⑨ `contracts/*.schema.json` 与 `scripts/validate_contracts.py`**；A–D 决议与 2026-11-09 的 10 项决议 |
| 通过条件 | 数据模型、状态机、API、错误码、证据等级、规则版本确定；**五个可冻结契约有机器可读 schema，校验器真实 exit 0（正例通过、反例按声明原因被拒）**；用户书面批准 |
| 证据 | 9 份文档 + `contracts/` + `docs/verification/g0/01_selftest.log`、`02_validate_contracts.log` + 批准记录 |
| 负责人/复核 | 用户批准；Agent 只准备材料，不得自行把 G0 标 `PASS` |
| 失败处理 | 暂停并行开发，先统一契约；schema 与散文冲突时以 schema 为准并立即报告 |

### 4.2 G1 纵向闭环

| 项 | 内容 |
|---|---|
| 输入 | T0 全部工作包 |
| 通过条件 | 无模型、离线、单任务从提交到凭证全链跑通 |
| 证据 | `docs/verification/t0/e2e/` 三次运行 |
| 负责人/复核 | 实现者执行；复核者按证据抽查 |
| 失败处理 | 停止前端美化与新增功能，修复执行/证据/验证 |

### 4.3 G2 证据可信

| 项 | 内容 |
|---|---|
| 输入 | Collector、Gate、权限测试 |
| 通过条件 | E0 不推动状态；E2 由 Collector 观察；越权写被拒；**stale 证据（含仍留在证据包/DB 中的）不满足必检项，且证据未被删除**；失效记录与 `DENIED` 审计可追溯 |
| 证据 | `wp-07`、`wp-08`、`wp-r` 证据；权限日志；`wp-08/stale_in_bundle_reject.log`；`wp-03/denied_survives_rollback.log` |
| 失败处理 | 不得对外展示 `VERIFIED` |

### 4.4 G3 L3 独立重执行

| 项 | 内容 |
|---|---|
| 输入 | Verifier L3 |
| 通过条件 | 新目录、独立进程、真实重跑；假复现负例拒绝 |
| 证据 | `wp-10/l3_retrain.log`、`fake_l3_reject.log` |
| 失败处理 | 缩小可 `VERIFIED` 模板范围 |

### 4.5 G4 动态调度/恢复（T1）

| 项 | 内容 |
|---|---|
| 输入 | Scheduler/Governor、完整 Recovery |
| 通过条件 | 资源变化改变调度；失败能执行完整恢复计划 |
| 证据 | T1 证据 |
| 失败处理 | 只交付固定调度基线，不宣称动态优化 |

**G4 不因 T0 的 `WP-R` 而提前通过。**

### 4.6 G5 实验数据可信（T1 起）

| 项 | 内容 |
|---|---|
| 输入 | RF-Bench、预注册、四方案/消融 |
| 通过条件 | 预注册、冻结哈希、四方案、原始 JSON、统计脚本齐全 |
| 证据 | T1 证据 |
| 失败处理 | 缺数据保持未测 |

### 4.7 G6 外部复核（拆两段）

**G6-T0（T0 出口）**

| 项 | 内容 |
|---|---|
| 输入 | Evidence Bundle、`verify_bundle.py`、外部信任锚 |
| 通过条件 | 独立环境（另一目录/设备/Windows 用户）验签真包通过 |
| 证据 | `docs/verification/t0/g6-t0/` |
| 失败处理 | T0 出口不成立；G1 不得标 PASS |

**G6 完整版（T1）**

| 项 | 内容 |
|---|---|
| 输入 | 五类负例矩阵（改 payload、换公钥、删 split、改状态、破签名） |
| 通过条件 | 真包通过 + 五类负例全部拒绝 |
| 证据 | `docs/verification/t1/g6/` |
| 失败处理 | 不得宣称第三方可复核 |

### 4.8 G7 Harness 适配（T2）

| 项 | 内容 |
|---|---|
| 输入 | 固定版本插件、事件映射、状态回传 |
| 通过条件 | 契约测试通过；版本不匹配拒绝 |
| 证据 | T2 证据 |
| 失败处理 | 标注实验性/计划，不写已接入 |

## 5. Definition of Done（T0）

【策划书】§15.7 / P0408–P0412：

1. 每模块有 Schema、错误码、日志、单测、集成测试和使用说明。
2. 核心状态迁移、Gate、签名验签与失效判定有正例和负例。
3. 每个机制有开关/对照/消融或明确边界证明；T0 至少证明“无模型/离线/独立验签”。
4. 所有对外数字可追到原始数据；示意图明确标示。
5. 离线启动、断网运行、无模型回退和离线验签在独立环境复测。

**本项目附加（G0 决议 2/7/8）**：

6. 五个可冻结契约有机器可读 schema，`scripts/validate_contracts.py` 真实 exit 0；Pydantic 模型与 schema 字段/枚举/必填一致（`WP-02`）。
7. 失败迁移的 `DENIED` 审计在回滚后仍存在；审计二次失败必须降级为结构化 stderr 并计入测试缺口，不得静默。
8. 非回环绑定且无 token 时拒绝启动；`POST /recover` 在 T0 返回 404。

## 6. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 依赖未锁定 | 环境漂移，L3 不可复现 | `WP-01` 按锁定矩阵安装 + 环境指纹；偏差必须记录 |
| 失败迁移审计写错（双事务） | “失败无审计”，状态不可信 | 决议 7 口径；`WP-03` 用真实 SQLite 证明 `DENIED` 存活；二次失败降级 stderr 并计缺口 |
| 计划 `plan_hash` 不稳定 | 守卫误拒或形同虚设 | 计划正文排除时间戳/随机序；`WP-R` 两次生成比对 |
| 非回环绑定无 token | 本机端口被外部访问 | 启动守卫 + `T0-SEC-BIND-*` 负例；登记为已接受风险，不声称已加固 |
| 契约双份定义漂移（schema vs Pydantic） | 校验行为与冻结契约不一致 | `WP-02` 差异检查；模型层复用 `contracts/examples/` 正反例 |
| 假 L3 | G3 失败 | 独立进程 + 新目录 + 禁止读原结果 |
| 信任锚被绕过 | G6-T0 失败 | 包外信任锚 + 负例 |
| 失效范围过宽 | 过度重跑 | 先算受影响子图再冻结计划 |
| 范围蔓延 | T0 失控 | A1/D1 边界 + 变更需书面裁决 |

## 7. 依据锚点

| 主题 | 锚点 |
|---|---|
| T0/T1/T2 | §15.2 / TABLE 56 |
| G0–G7 | §15.3 / TABLE 57 |
| 开发顺序 | §15.5 / P0386–P0395 |
| T0 清单 | 附录 J / TABLE 78 |
| 测试分层 | §6.7 / TABLE 30 |
| Definition of Done | §15.7 / P0408–P0412 |
| 契约机器可读定义 | [`contracts/`](../../contracts/)（G0 文档 ⑨） |
| 失败迁移审计 / 恢复守卫 / 启动守卫 | 用户决议 7/5/8；05 §9.3、§9.7；06 §2、§4.6 |

## 8. 版本记录

| 版本 | 日期 | 变更 | 状态 |
|---|---|---|---|
| v0.1 | 2026-11-09 | 依赖图、工作包、测试分层、G0–G7、DoD、风险 | 候选，已被 v0.2 取代 |
| v0.2 | 2026-11-09 | `WP-02` 改为“schema→Pydantic 落地”（⑨ 已在 G0 完成）；`WP-03` 增失败双事务审计与 `INVALIDATED` 守卫；`WP-08` 增失效记录驱动的 stale 判定；`WP-R` 增确定性计划与三条守卫负例；测试矩阵新增 4 类；G0 通过条件纳入 ⑨ 与真实退出码；DoD 附加 3 条；风险表更新 | 候选，已被 v1.0 冻结取代 |
| v1.0 | 2026-11-10 | **G0 冻结定版**：`WP-01` 入口写入依赖矩阵锁定基线（17 个第三方包 + SQLite）与四条解释器硬约束（uv 3.11.16、指纹校验、架构优先排查、TestClient 冒烟与回退）；补冻结日期、状态与被取代版本。**工作包顺序、测试矩阵、门禁条件未改** | **G0 冻结** |

---

**标记：本文件是 G0 文档 ⑦ v1.0（G0 冻结），不是 G0 门禁 PASS。** 文档已按用户 2026-11-10 指令冻结；G0 是否 PASS 由用户宣布；未建 `.venv`、未安装依赖、未写业务代码。