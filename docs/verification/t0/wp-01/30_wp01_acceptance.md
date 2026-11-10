# T0 · WP-01 验收记录

> 日期：2026-11-10 22:16（Asia/Shanghai）。
> 裁决人：`用户`（本会话逐项选择）。
> 结论：`T-WP-01-001` → `DONE`。
> 依据：[`WP-01_REPORT.md`](WP-01_REPORT.md) 与 `docs/verification/t0/wp-01/` 全部证据。

## 1. 四项裁决

| 编号 | 事项 | 用户决定 | 落点 |
|---|---|---|---|
| D-1 | `T-WP-01-001` 验收结论 | 转 `DONE` | `docs/state/project_state.json` → `tasks[].status` |
| D-2 | `.venv` 实测 502.3 MB，超矩阵估算 350–450 MB | 接受，记为已知偏差；不裁剪依赖、不改组成 | 本文件 §3；`docs/verification/g0/09_dependency_matrix.md` §4 |
| D-3 | `last_verified_commit` | 更新为 `19c337f350fead30efd52c222356ad6248a3f937` | `docs/state/project_state.json` 顶层 |
| D-4 | T0 里程碑编号 | 暂不指定，保持 `M0_GOVERNANCE_BASELINE` | 未改动 |

D-4 依据：冻结版 `07_T0_PLAN_AND_GATES.md`（v1.0）全文未定义 T0 里程碑编号（检索 `M0`／`M1`／`里程碑`／`milestone` 均无命中），用户选择不自行发明编号，待 ⑦ 经变更流程修订时再定。

## 2. 验收标准逐条对账

| # | 验收标准（摘自 `project_state.json` 原值，未改写） | 证据 | 判定 |
|---|---|---|---|
| 1 | `.venv` 由 uv 托管 CPython 3.11.16 创建；`sys.version` 含 3.11.16 且 `platform.architecture()[0]` 为 64bit | [`env_fingerprint.json`](env_fingerprint.json)、[`venv_cache_failure.log`](venv_cache_failure.log)、`WP-01_REPORT.md` §1 | 通过 |
| 2 | 矩阵内 16 个直接 pin 与 SQLite 逐项核对；uv 工具版本偏差单独记录原因，无静默升级 | [`dependency_resolution.txt`](dependency_resolution.txt)、[`version_combo.log`](version_combo.log) | 通过（uv `0.12.16` vs 矩阵 `0.13.7`，保留理由已记录，未静默升级） |
| 3 | `httpx2==2.16.0` 仅在用户 2026-11-10 批准后安装，并记录 starlette 1.10.0 的 TestClient 约束 | [`install_httpx2.log`](install_httpx2.log)、[`starlette_resolution.txt`](starlette_resolution.txt) | 通过 |
| 4 | `requirements.lock` 锁定 58 个包；干净环境从锁文件复现安装并 TestClient 200 | [`lockfile.txt`](lockfile.txt)、[`clean_room_install.log`](clean_room_install.log) | 通过 |
| 5 | TestClient 最小端点返回 200；starlette 1.10.0 与矩阵一致、不回退；8 个模块导入与 numpy `[2.0.2,2.7)` 区间通过 | [`testclient_smoke.log`](testclient_smoke.log)、[`version_combo.log`](version_combo.log) | 通过 |
| 6 | `.venv` 体积与耗时实测并对照矩阵估算；超出估算的偏差如实记录，不用估算值回填 | [`size_and_timing.md`](size_and_timing.md)、本文件 §3 | 通过 |
| 7 | `researchflow/` 仍只有 `.gitkeep`；未写业务代码、未建数据库、未写 API、未做模板；证据齐全 | `git ls-files researchflow` → 仅 `researchflow/.gitkeep`；`git status --porcelain=v1` 空 | 通过 |

## 3. 体积偏差（已知偏差 D-2）

| 项 | 实测 | 矩阵估算 | 对比 |
|---|---|---|---|
| `.venv` | `502,349,269` 字节（502.3 MB） | 350–450 MB | 超上限 `52.3 MB`（`+11.6%`） |
| 安装主路径耗时 | `59.48 s`（0.51 + 46.10 + 12.87） | 无耗时估算 | 只记录实测 |
| 干净环境复现 | `43.95 s` | — | — |
| `.uv-cache` | `473.7 MB` | 下载约 150 MB（估） | 不可直接比较：uv 解压缓存，不是网络下载字节 |

原因：完整依赖闭包、Windows 二进制 wheel、Streamlit 全套传递依赖、矩阵外新增 `httpx2`（及其 `httpcore2`、`truststore`）。
处置：用户裁决 **接受为已知偏差**；不删包凑估算、不回填估算值。本次未登记后续瘦身任务。

## 4. 未随验收改变的事项

- `current_phase` 仍 `T0`；`current_milestone` 仍 `M0_GOVERNANCE_BASELINE`。
- `G1`–`G7` 仍 `NOT_STARTED`。
- `BLK-003` 仍 `OPEN` / `MEDIUM`；13b 仍 `NOT VERIFIED`；2D 未单独执行。
- `researchflow/` 仍只有 `.gitkeep`；未建数据库、未写 API、未做模板、未写业务代码。

## 5. 复核命令与真实结果

本轮真实执行（stdout 见 [`state_sync_acceptance.log`](state_sync_acceptance.log)）：

| 命令 | 结果 | 退出码 |
|---|---|---|
| `.venv/Scripts/python.exe scripts/state_sync.py validate` | 见日志 | 0 |
| `.venv/Scripts/python.exe scripts/state_sync.py render` | 重新生成 `PROJECT_STATE.md`、`IMPLEMENTATION_STATUS.md` | 0 |
| `.venv/Scripts/python.exe scripts/state_sync.py check` | 2 个生成文件与 `project_state.json` 逐字节一致 | 0 |

生成文件 SHA256：

- `docs/PROJECT_STATE.md`：`76411b3f58673dabf7738e08b0e6b110214f49ac3d602b7eaa905f872c7652d8`
- `docs/IMPLEMENTATION_STATUS.md`：`8d33690f20a427040612a2bf9cbba7081fbf6d01403757eef511cf8dcf9f7502`
