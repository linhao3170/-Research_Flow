# T0 端到端验收报告（WP-14）

> 日期：2026-11-14（Asia/Shanghai）
> 解释器：`D:\ResearchFlow-project\.venv\Scripts\python.exe`（CPython 3.11.16，64bit）
> 主机：Windows 11（10.0.22631），CPU-only，物理内存 16,117 MB
> 会话权限：`danger-full-access`（审批不再询问）；`BLK-003` 仍 `OPEN`，本报告**不**声称 workspace-write 通过。
> 原始记录：[run_1/](run_1/)、[run_2/](run_2/)、[run_3/](run_3/)、[runs_summary.json](runs_summary.json)、[concurrency.json](concurrency.json)
> 修订（2026-11-14 晚）：独立审查发现执行器只采样了 venv `python.exe` 启动器（约 3.4 MB），真实解释器是其子进程；已改为进程树采样并补真实分配校准测试，随后**重新生成** run_1..run_3。旧证据保留在 [superseded_2026-11-14_pre_memfix/](superseded_2026-11-14_pre_memfix/)，不再作为证据。

## 1. 目标与执行方式

在断网意图、无模型（T0 无任何 LLM/模型客户端）、单机条件下，通过内置表格 ML 模板完成真实实验，经 Collector、Gate、独立 Verifier L1/L2/L3 形成证据，签发 `CompletionCertificate`，导出 Evidence Bundle，并由包外信任锚和隔离目录中的独立工具验签。

每轮运行的真实路径：

1. 启动 API（仅 `127.0.0.1`，无 token，代理变量指向黑洞）；
2. `POST /api/v1/tasks`（带 `Idempotency-Key`）；
3. 内部编排执行 DAG：`split_dataset` → `train_logistic_regression` / `train_random_forest`（`max_workers=2`，真实并行）；
4. `POST /verify` → L1/L2/L3 → Gate → 签名报告 + 凭证；
5. 修改该运行独占的数据副本（seed 20261114 → 7），声明 `INPUT_CHANGE`：`VERIFIED → INVALIDATED`，生成内容寻址的确定性计划并冻结；
6. 三条件守卫通过后保守重跑（新 attempt），再次 `POST /verify` → 新报告/凭证；
7. 任务 `COMPLETED`，导出 Bundle；
8. 把 `verify_bundle.py`、Bundle、外部信任锚复制到 `isolated-verifier/`，以 `-E` 独立进程离线验签。

命令：

```powershell
& .\.venv\Scripts\python.exe scripts/e2e_run.py --runs 3 --out docs/verification/t0/e2e
& .\.venv\Scripts\python.exe scripts/measure_concurrency.py
```

## 2. 三次运行结果

| 运行 | 耗时 | 任务状态 | 报告状态 | 必检覆盖 | L3 覆盖 | 证据条数 | 失效证据 | Bundle 文件数 | 离线验签 |
|---|---:|---|---|---:|---:|---:|---:|---:|---|
| run_1 | 28.32 s | COMPLETED | VERIFIED | 8/8，缺 0 | 1.0 | 32 | 16 | 63 | exit 0，VERIFIED |
| run_2 | 27.39 s | COMPLETED | VERIFIED | 8/8，缺 0 | 1.0 | 32 | 16 | 63 | exit 0，VERIFIED |
| run_3 | 27.12 s | COMPLETED | VERIFIED | 8/8，缺 0 | 1.0 | 32 | 16 | 63 | exit 0，VERIFIED |

一致性判定 `runs_summary.json.consistent = true`：任务/报告终态、必检覆盖、L3 覆盖、证据总数、失效数、重跑 attempt、Bundle 文件数、离线验签退出码与状态全部一致。各运行的 `task_id`、`report_id`、`cert_id`、`plan_hash`、`merkle_root` 不同（含任务/时间和内容差异），这是预期而非不一致。

每个 `run_N/` 目录：

- `data/`：本运行独占的数据副本（v1 → v2）与数据集登记；
- `runtime/`：SQLite、attempt 目录、evidence payload、恢复计划、签名密钥（私钥不进入 Bundle）；
- `logs/http.jsonl`：11 次真实 HTTP 调用（请求/响应/状态码）；
- `logs/execution.json`、`verify_1.json`、`invalidation.json`、`rerun.json`、`verify_2.json`；
- `logs/graph*.json`、`evidence*.json`、`report.json`、`certificate.json`；
- `logs/verify_bundle.stdout.log` / `.stderr.log` / `verify_bundle.json`；
- `bundle/`（63 个文件）、`trust_store.json`（包外）、`isolated-verifier/`。

## 3. 证据可信要点（真实负例见各 WP 日志）

| 要点 | 本次真实证据 |
|---|---|
| E2 来自受控执行观测 | `executor_launch` / `executor_process_exit` / `artifact_observed`，payload 含退出码、超时、内存峰值、产物哈希；执行器不返回完成裁决 |
| E0/E1 不单独满足执行必检 | `docs/verification/t0/wp-08/pytest.log` 中 E0 claim 用例断言 `GAP_E2_MISSING` |
| 同事件不产生两条 | WP-07 重复投递后行数不变、`delivery_seq` 递增；同键异内容 `CHAIN_CONTENT_CONFLICT` + DENIED 审计 |
| stale 不删除且不放行 | run_1..3 均为 16 条旧证据失效、仍保留在库与 Bundle；重跑后 8/8 由新 attempt 证据满足；`test_wp_recovery` 的“包内 stale”用例断言 `REQUIRED_EVIDENCE_MISSING` |
| L3 独立 | 新目录（`runtime/verification/l3-*`）、独立子进程、读取原始数据重跑 split+train；预测逐行一致、指标容差内；隔离守卫拒绝执行器目录/本进程/执行器产物 |
| 证书条件 | 仅在报告 `VERIFIED`、必检缺口 0、L3 覆盖 1.0、链有效、E2 环境指纹存在时签发；失败运行无 `certificate.json`（WP-12 负例） |
| 离线验签 | 只信任包外 `trust_store.json`；重算清单哈希、证据链、Merkle 根、报告/证书签名，并从包内 graph/ruleset/records/invalidations 重新执行 Gate 判定；使用 `-E` 且不 import 产品包 |

## 4. 并发与资源实测

`concurrency.json`：两个训练节点在 `limits.max_workers=2` 下真实并行，attempt 时间区间重叠 **2.323 s**，观测并发 **2**。

内存观测口径（审查后修正）：uv 虚拟环境的 `python.exe` 是启动器，真实解释器是其子进程。执行器现在用 `ProcessTreeSampler` 枚举启动器及全部后代，取树内最大工作集并记录实际采样的 `worker_pids`。本次测量两个训练 worker 的峰值工作集分别为 **165.004 MB** 与 **166.586 MB**，合计 **331.59 MB**；`tests/t0/test_wp06_executor.py` 的校准用例用一个真实分配 200 MB 的子进程断言采样值落在 150–400 MB，证明读数不是常数伪值。`max_memory_mb` 现在由真实读数驱动（同一测试以 8 MB 限额终止真实 worker）。

主机物理内存 **16,117 MB**，测量时可用 5,413.9 MB（负载 66%）。T0 未实现/未宣称 GPU、分布式、多租户或动态调度。

## 5. 离线与无模型

- T0 产品代码不包含任何 LLM/云模型客户端；`researchflow/` 无 `openai`、`dashscope`、`anthropic`、`requests` 等网络客户端导入（可扫描复核）。
- 三次运行中，API 与 worker 的环境把 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY` 指向黑洞端口，`NO_PROXY` 仅放行回环；所有 HTTP 调用目标均为 `127.0.0.1`（`http.jsonl` 可逐条核对）。
- 数据仅来自仓库内置合成数据（CC0-1.0），不下载。
- **限制**：未执行操作系统级网卡断开；因此证据是“代码与运行环境均无外呼”的强证据，而非物理断网证明。

## 6. 门禁证据映射

| 门禁 | 条件 | 证据 | 判定 |
|---|---|---|---|
| G1 纵向闭环 | 无模型、离线、单任务从提交到凭证全链跑通 | 三次运行 + 本报告 | 满足（会话实施复核） |
| G2 证据可信 | E0 不推动状态；E2 由 Collector 观察；越权写被拒；stale 不满足必检且不删除 | WP-07/08/R 负例 + 三次运行 | 满足 |
| G3 L3 独立重执行 | 新目录、独立进程、真实重跑；假 L3 拒绝 | WP-10 + 三次运行 | 满足 |
| G6-T0 | 独立环境（另一目录）验签真包通过 | `docs/verification/t0/g6-t0/` | 满足（目录级隔离；另一设备/用户未用，已披露） |
| 完整 G6 | 五类负例矩阵 | — | **T1，NOT_STARTED，未提前通过** |

## 7. 未达成 / 已披露限制

1. 工作台截图未提供：容器内无浏览器自动化；以 Streamlit `AppTest` 运行真实 API 数据 + 源码只读检查替代，详见 [wp-13/pytest.log](../wp-13/pytest.log) 与 [00_implementation_decisions.md](../00_implementation_decisions.md) D-24。
2. `BLK-003` 未关闭：全部测试在 `danger-full-access` 下运行，未取得 workspace-write 全绿。
3. L3 隔离为“新目录 + 独立进程 + 原始数据重训”，未使用另一台设备；跨机器可复现性未测。
4. 断网未做物理断开（见 §5）。
5. `OQ-CT-10`（创世哈希取值）、`OQ-CT-12`、`OQ-API-3/5`、`OQ-DB-2` 仍开放；T0 采用本文已披露口径。
6. G4/G5/G7 属 T1/T2，未启动；不把 WP-R 当作 G4 通过。

## 8. 复现说明

1. 使用 §0 的解释器，从仓库根运行 §1 两条命令；脚本拒绝覆盖已存在的 `run_N/`。
2. 若需重新采集证据，请先人工把旧目录移出（不要删除历史），再运行。
3. 验签只用包外信任锚：`python -E isolated-verifier/verify_bundle.py --bundle isolated-verifier/bundle --trust-store isolated-verifier/trust_store.json`；预期 exit 0 且 `status=VERIFIED`。