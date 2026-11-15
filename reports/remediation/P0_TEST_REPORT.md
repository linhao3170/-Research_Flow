# ResearchFlow 3.1 · P0 测试报告（P0_TEST_REPORT）

> 日期：2026-11-11（Asia/Shanghai）
> 工作区：`D:\ResearchFlow-project`
> 解释器：`D:\ResearchFlow-project\.venv\Scripts\python.exe`
> Python：3.11.16（main, Sep 1 2026）[MSC v.1944 64 bit (AMD64)]
> 架构：64bit；SQLite：3.53.1；pytest：9.2.0
> 说明：本报告只记录真实执行的命令与结果；未执行的项明确写“未执行”。

## 1. 测试范围与授权

| 项 | 内容 |
|---|---|
| 授权来源 | 用户 P0 整改 E 项：一次受控 full-access 全量 pytest |
| 限制 | 只运行项目已有测试；不安装/升级依赖；不改业务代码、测试、配置、契约；不删除临时文件 |
| 结果用途 | 只用于业务回归；**不关闭 BLK-003，不用于安全项，不构成 G1/运行时能力通过** |
| 未执行 | 未运行 P9 六份并发重写伪代码的导入/行为测试；未运行 WP-03；未运行安全/权限专项 |

## 2. 环境核验

命令：

```powershell
& .venv/Scripts/python.exe -c "import sys,platform,sqlite3;print(sys.version);print('platform='+platform.architecture()[0]);print('sqlite='+sqlite3.sqlite_version);print('exe='+sys.executable)"
& .venv/Scripts/python.exe -m pytest --version
uv pip check --python .venv/Scripts/python.exe
```

结果：

```text
3.11.16 (main, Sep  1 2026, 14:15:24) [MSC v.1944 64 bit (AMD64)]
platform=64bit
sqlite=3.53.1
exe=D:\ResearchFlow-project\.venv\Scripts\python.exe
pytest 9.2.0
Checked 58 packages in 226ms
All installed packages are compatible
```

证据：`reports/remediation/logs/50_env_and_contracts.log`

## 3. A · API 幂等与 422 回归

命令：

```powershell
& .venv/Scripts/python.exe -m pytest tests/test_api_422.py tests/test_api_idempotency.py -q -p no:cacheprovider
```

结果：

```text
..................                                                       [100%]
18 passed in 0.64s
EXIT_CODE=0
DURATION_SEC=1.388
```

- 原 `tests/test_api_422.py` 13 项全部通过（含 422 顺序、dataset_ref、重复键、NaN、409、404、GET）。
- 新增 `tests/test_api_idempotency.py` 5 项 A–E 全部通过；A/D/E 含 `first.content == second.content` 与完整 JSON 相等断言。
- 未修改 422 错误处理顺序；未新增公共响应字段；未修改 GET 结构。

日志：`reports/remediation/logs/10_api_pytest_before_fullaccess.log`

## 4. E · 受控 full-access 全量 pytest

命令：

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONUTF8 = '1'
& .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
```

授权/环境记录：

- 执行时使用用户 E 项批准的一次性 full-access；日志中记录 `POLICY=danger-full-access (one-shot, user-authorized P0 item E)`。
- `PYTHONDONTWRITEBYTECODE=1`；`-p no:cacheprovider`（不写 `.pytest_cache`）。
- 开始：2026-11-11T22:54:54.0640868+08:00；结束：22:55:00.7941886+08:00；耗时 6.73 s。

结果：

```text
........................................................................ [ 51%]
....................................................................     [100%]
140 passed in 5.82s
EXIT_CODE=0
```

日志：`reports/remediation/logs/21_full_pytest_fullaccess.log`

### 4.1 测试前后 Git 状态

| 时点 | 日志 | 结果 |
|---|---|---|
| 测试前 22:54:39 | `logs/20_git_before_fullaccess.txt` | HEAD `309083e`；仅 A 改动 + 原有未跟踪目录；无测试临时文件 |
| 测试后 22:55:08 | `logs/22_git_after_fullaccess.txt` | HEAD 未变；Git 状态与测试前一致；无新增/删除文件 |

### 4.2 测试创建/修改的缓存与临时目录

| 路径 | 测试前 | 测试后 | 说明 |
|---|---:|---:|---|
| `.pytest_cache` | 4 files / 12,253 B | 4 files / 12,253 B | 未变；本次禁用 cacheprovider |
| `__pycache__` | 1 file / 757 B | 1 file / 757 B | 未变；禁用字节码写入 |
| `researchflow/__pycache__` | 1 file / 237 B | 1 file / 237 B | 未变 |
| `tests/__pycache__` | 5 files / 115,985 B | 5 files / 115,985 B | 未变 |
| `tmp/unittest-temp` | 0 files | 0 files | 未变；未删除 |
| `tmpavet2qv9` | absent | absent | 未创建 |
| 项目 `tmp/` 下测试开始后新文件 | — | 无 | 已按时间戳检查 |
| 系统 `%TEMP%` 下 `rf_state_sync_*` / `pytest-of-*` 新目录 | — | 未发现 | 未删除任何已有临时文件 |

结论：本次测试未在项目内留下新的缓存/临时目录；未执行清理。

## 5. 契约验证（回归）

命令：

```powershell
& .venv/Scripts/python.exe scripts/validate_contracts.py --selftest
& .venv/Scripts/python.exe scripts/validate_contracts.py
```

结果：

```text
SELFTEST 10/10 PASS
contracts=5 cases=72 pass=72 fail=0 exit=0
```

日志：

- `reports/remediation/logs/51_validate_contracts_selftest.log`
- `reports/remediation/logs/52_validate_contracts.log`

## 6. 状态同步与阶段注册表测试

命令：

```powershell
& .venv/Scripts/python.exe scripts/state_sync.py validate
& .venv/Scripts/python.exe scripts/state_sync.py render
& .venv/Scripts/python.exe scripts/state_sync.py check
& .venv/Scripts/python.exe -m pytest tests/test_state_sync.py -q -p no:cacheprovider
```

结果（最终复核以 `P0_STATE_CONSISTENCY_REPORT.md` 为准）：

- `validate`：OK，任务 8，伪代码阶段 10（ACCEPTED 1，BLOCKED 2），门禁 PASS=1/8，exit 0。
- `render`：2 文件，exit 0；`check`：逐字节一致，exit 0。
- `tests/test_state_sync.py`：31 passed，exit 0；含 8 个新增阶段校验/渲染测试。
- 最终定向回归（API 422 + A–E + state_sync）：`49 passed`，exit 0；覆盖 B 改动后受影响的三个测试模块。

最终定向回归命令：

```powershell
& .venv/Scripts/python.exe -m pytest tests/test_api_422.py tests/test_api_idempotency.py tests/test_state_sync.py -q -p no:cacheprovider
```

日志：

- `reports/remediation/logs/41_state_sync_new_tests.log`
- `reports/remediation/logs/40_state_sync_existing_tests.log`
- `reports/remediation/logs/70_final_targeted_tests.log`

## 7. 文档漂移检查

命令：

```powershell
& .venv/Scripts/python.exe scripts/check_docs_drift.py
```

结果：

```text
docs/state/project_state.json:840: WARNING: last_verified_commit 与当前 HEAD 不一致
STATE-FREE enforced=5/9；ERROR=0；WARNING=1
EXIT_CODE=0
```

说明：WARNING 是未提交整改的预期结果；`last_verified_commit` 未擅自推进。

日志：`reports/remediation/logs/60_check_docs_drift.log`

## 8. 未测 / 不能宣称

1. **BLK-003 未关闭**：full-access 通过不能证明 workspace-write 下 ACL 阻塞消失。
2. **P9 未测**：六份并发重写 `.py` 只做了 AST 解析（6/6 OK），未导入、未运行 pytest、未验收；不得据此宣称 P9 完成。
3. **WP-03 未测**：未实现 StateMachine/SQLite/audit，不能宣称运行时状态迁移已实现。
4. **G1–G7 未测**：仍 `NOT_STARTED`，不能宣称任何门禁通过。
5. **多进程幂等未测**：A–E 只覆盖单进程 TestClient；锁不宣称多 worker 安全。
6. **P10/M19 未测**：只登记 5 个未跟踪 `.py`，未获开发授权。
7. **安全/权限专项未测**：本轮未执行 ACL、签名、信任锚、L3 独立重跑等专项。

## 9. 测试时序限制（必须保留）

- 受权的 full-access 全量 pytest 在 B/C/I 改动之前执行（`140 passed`）；用户只批准**一次**全量运行，因此 B 完成后**没有**再跑第二次全量 148 项。
- B 完成后执行了三个受影响测试模块的定向回归（`49 passed`）；未覆盖的其余测试仍沿用 full-access 的 140 项结果，不能声称“B 后全量 148 项已跑”。
- 如果用户要求“B 后全量重跑”，需要单独批准第二次 full-access 运行；本轮未擅自执行。