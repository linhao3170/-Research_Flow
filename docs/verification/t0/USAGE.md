# T0 启动、使用与验签说明（2026-11-14）

> 解释器：`D:\ResearchFlow-project\.venv\Scripts\python.exe`（CPython 3.11.16，64bit）。
> 所有命令在仓库根 `D:\ResearchFlow-project` 执行。T0 只支持 Windows 单机、CPU-only、回环 API。
> 运行数据默认在 `runtime/`（已 gitignore）：SQLite、attempt 目录、证据载荷、恢复计划、签名密钥。

## 1. 初始化与启动 API

```powershell
$py = 'D:\ResearchFlow-project\.venv\Scripts\python.exe'

# 初始化/迁移数据库（默认 runtime/researchflow.db）
& $py -m researchflow.cli init-db

# 仅回环启动（免 token，T0 已接受风险）
& $py -m researchflow.cli serve --host 127.0.0.1 --port 8000

# 非回环必须声明 token，否则拒绝启动：写 STARTUP_GUARD/DENIED 审计、退出码 2、不监听
$env:RESEARCHFLOW_API_TOKEN = 'placeholder'
& $py -m researchflow.cli serve --host 0.0.0.0 --port 8000
```

环境变量：

- `RESEARCHFLOW_DB_PATH`：数据库路径（默认 `runtime/researchflow.db`）；
- `RESEARCHFLOW_DATA_ROOT`：内置数据集根（默认 `researchflow/templates/data`；e2e 用隔离副本）；
- `RESEARCHFLOW_API_TOKEN`：仅作为“非回环绑定已声明认证配置存在”的启动条件，T0 端点不做鉴权。

## 2. 提交任务（公开 API）

```powershell
$body = Get-Content contracts/examples/taskspec.positive.json -Raw | ConvertFrom-Json
$body.PSObject.Properties.Remove('task_id')
$payload = $body | ConvertTo-Json -Depth 10
$created = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/tasks `
  -ContentType 'application/json' -Headers @{ 'Idempotency-Key' = 'demo-1' } -Body $payload
$created
# task_id / state=CREATED / graph_version=1
```

注意：`dataset_ref` 必须是对象 `{uri, sha256, license}` 且 sha256 与内置文件一致；
允许的模板为 `classification_benchmark@1.0.0`，模型白名单 `logistic_regression` / `random_forest` / `decision_tree`。

## 3. 执行与验证（内部编排 + 公开 API）

```powershell
# 执行（内部编排，不是公开路由）：split → 并行训练 → E2 证据
& $py -m researchflow.cli run-task --task <task_id>

# 验证（公开 API）：L1/L2/L3 → Gate → 签名报告；仅 VERIFIED 才签证书
$verifyBody = '{"mode":"full","requested_checks":["L1","L2","L3"]}'
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/tasks/<task_id>/verify" `
  -ContentType 'application/json' -Body $verifyBody
```

`run-task` 会一次完成执行→验证→节点转 VERIFIED→任务 COMPLETED。若需要“失效→重跑”场景，
使用下面的恢复命令，并在重跑后再次 `POST /verify`。

只读查询：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/tasks/<task_id>
Invoke-RestMethod http://127.0.0.1:8000/api/v1/tasks/<task_id>/graph
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/tasks/<task_id>/evidence?limit=200"
Invoke-RestMethod http://127.0.0.1:8000/api/v1/tasks/<task_id>/report
Invoke-RestMethod http://127.0.0.1:8000/api/v1/tasks/<task_id>/certificate
```

## 4. 失效、计划冻结与保守重跑（T0 无公开 /recover）

```powershell
# 输入变化：失效 split 及后代、写内容寻址计划、冻结审计
& $py -m researchflow.cli invalidate --task <task_id> --node split_dataset `
  --cause-type INPUT_CHANGE --cause-ref <new_sha256> --dataset-sha <new_sha256>

# 守卫三条件通过后重跑受影响后代（新 attempt）
& $py -m researchflow.cli rerun --task <task_id> --plan-hash <plan_hash>

# 然后再次 POST /verify，最后 run-task 的收尾状态转换由 pipeline 完成
```

`POST /api/v1/tasks/{id}/recover` 在 T0 **未注册**，访问返回 404。

## 5. 导出 Bundle 与离线验签

```powershell
# 1) 生成包外信任锚（只含公钥/指纹；私钥保留在 runtime/keys）
& $py -m researchflow.cli write-anchor --out D:\evidence\trust_store.json

# 2) 导出证据包（目录须为空/不存在）
& $py -m researchflow.cli export-bundle --task <task_id> --out D:\evidence\bundle `
  --trust-anchor D:\evidence\trust_store.json

# 3) 在隔离目录用可信版本验签（不要把 verify_bundle.py 从证据包内取）
Copy-Item verify_bundle.py D:\evidence\isolated\
Copy-Item -Recurse D:\evidence\bundle D:\evidence\isolated\bundle
Copy-Item D:\evidence\trust_store.json D:\evidence\isolated\trust_store.json
& $py -E D:\evidence\isolated\verify_bundle.py `
  --bundle D:\evidence\isolated\bundle --trust-store D:\evidence\isolated\trust_store.json
# 预期：exit 0，{"status":"VERIFIED", ...}，merkle_root 与报告一致
```

验签器只依赖 stdlib + `cryptography`，不 import 产品包、不读数据库/模型；它会重算清单哈希、
证据链、Merkle 根、报告/证书签名，并用包内 graph/ruleset/records/invalidations 重新执行 Gate 判定
（包括 E3 与当前 split 的绑定）。信任锚必须在包外；包内公钥不会被信任。

## 6. 最小工作台（只读）

```powershell
$env:RESEARCHFLOW_API_URL = 'http://127.0.0.1:8000'
$env:RESEARCHFLOW_TASK_ID  = '<task_id>'
& $py -m streamlit run researchflow/workbench/app.py
```

四视图：任务 / DAG / 证据 / 报告。只发 GET；API 不可达时显式报错，不伪造数据。T0 未提供截图。

## 7. 验收与证据入口

```powershell
& $py -m pytest tests -q -p no:cacheprovider
& $py scripts/validate_contracts.py
& $py scripts/validate_contracts.py --selftest
& $py scripts/state_sync.py validate
& $py scripts/state_sync.py render
& $py scripts/state_sync.py check
& $py scripts/check_docs_drift.py
& $py scripts/e2e_run.py --runs 3 --out docs/verification/t0/e2e
& $py scripts/measure_concurrency.py
```

- 证据索引：[WP_INDEX.md](WP_INDEX.md)
- 实施决策与偏离：[00_implementation_decisions.md](00_implementation_decisions.md)
- 独立审查：[review_2026-11-14.md](review_2026-11-14.md)
- 端到端报告：[e2e/e2e_report.md](e2e/e2e_report.md)
- 门禁证据：[g6-t0/](g6-t0/)

## 8. 限制（不宣称）

- T0 无 LLM/六角色/DC/SPA/完整 Recovery 状态机；`POST /recover` 404。
- 断网证据是“代码无外呼 + 代理黑洞 + 无模型客户端”，非 OS 级断网。
- 工作台截图缺失；`BLK-003` 未关闭，测试结果来自 `danger-full-access` 会话。
- 启动守卫不提供鉴权；非回环 + token 仍是已接受风险。
- 并发验证进程锁只覆盖单进程；跨进程并发未实现。