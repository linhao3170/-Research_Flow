# T0 · WP-01 仓库与环境锁定报告

> 日期：2026-11-10（Asia/Shanghai）。
> 范围：只做 Python 解释器、虚拟环境、依赖安装与锁文件；**未写任何 ResearchFlow 业务代码**。
> 状态：`DONE`（用户 2026-11-10 验收通过，记录见 [`30_wp01_acceptance.md`](30_wp01_acceptance.md)）。
> 矩阵：[`docs/verification/g0/09_dependency_matrix.md`](../../g0/09_dependency_matrix.md)（v1.0，2026-11-10 锁定）。
> 计划：[`docs/design/07_T0_PLAN_AND_GATES.md`](../../../design/07_T0_PLAN_AND_GATES.md) §2.1。

## 1. 解释器与虚拟环境

| 项 | 实测 |
|---|---|
| 创建命令 | `uv venv --python 3.11.16 .venv` |
| uv 版本 | `0.12.16`（矩阵列 0.13.7；见 §4 偏差） |
| 首次尝试 | 失败：`Failed to initialize cache at C:\Users\Administrator\AppData\Local\uv\cache`（默认缓存在工作区沙箱外，被拒绝）；首次工具捕获 exit 1，复现实测 uv exit 2 |
| 重试方式 | 设 `UV_CACHE_DIR=D:\ResearchFlow-project\.uv-cache` 后重试 |
| 重试结果 | exit 0；0.51 s；`Using CPython 3.11.16` |
| 指纹 | **`3.11.16` + `64bit`**（`sys.version` 与 `platform.architecture()[0]`） |
| `.venv` 解释器 | `D:\ResearchFlow-project\.venv\Scripts\python.exe` |
| SQLite | `3.53.1`（随解释器） |

首次失败是缓存路径问题，不是版本或架构解析问题；未改用 PATH 的 3.12 或 `py -3.11`（32 位）。

## 2. 依赖安装与解析

| 项 | 结果 |
|---|---|
| 直接 pin | 16 个矩阵内包 + `httpx2==2.16.0`（矩阵外，用户批准） |
| dry-run | 55 个包；exit 0；无解析冲突 |
| 正式安装 | 55 个包；exit 0；46.10 s |
| 依赖一致性 | `uv pip check` → `All installed packages are compatible`，exit 0 |
| 锁文件 | [`requirements.lock`](../../../../requirements.lock)：58 个精确 pin；SHA256 见 `lockfile.txt` |
| 直接依赖清单 | [`requirements.in`](../../../../requirements.in)：16 + `httpx2` |
| 干净环境复现 | `.venv-repro` 从 `requirements.lock` 安装 → TestClient 200；43.95 s；已删除 |

锁文件由真实安装后的 `uv pip freeze` 生成，不是按矩阵手抄；`requirements.in` 保留矩阵直接 pin 与新增批准记录。

## 3. 版本核对（逐项）

完整表见 [`dependency_resolution.txt`](dependency_resolution.txt)。

| 包名 | 矩阵版本 | 实际版本 | 是否一致 |
|---|---|---|---|
| fastapi | 0.162.2 | 0.162.2 | 一致 |
| pydantic | 2.14.3 | 2.14.3 | 一致 |
| networkx | 3.6.1 | 3.6.1 | 一致 |
| pandas | 3.1.1 | 3.1.1 | 一致 |
| scikit-learn | 1.9.1 | 1.9.1 | 一致 |
| cryptography | 50.0.2 | 50.0.2 | 一致 |
| streamlit | 1.67.0 | 1.67.0 | 一致 |
| pytest | 9.2.0 | 9.2.0 | 一致 |
| numpy | 2.4.6 | 2.4.6 | 一致 |
| scipy | 1.17.1 | 1.17.1 | 一致 |
| pydantic-core | 2.50.4 | 2.50.4 | 一致 |
| starlette | 1.10.0 | 1.10.0 | 一致 |
| cffi | 2.1.1 | 2.1.1 | 一致 |
| pyarrow | 26.0.1 | 26.0.1 | 一致 |
| pillow | 13.0.0 | 13.0.0 | 一致 |
| protobuf | 7.36.2 | 7.36.2 | 一致 |
| uv（工具） | 0.13.7 | 0.12.16 | **不一致（见 §4）** |
| SQLite | 3.53.1（随解释器） | 3.53.1 | 一致 |

numpy 组合：`numpy 2.4.6 / scipy 1.17.1 / pandas 3.1.1 / scikit-learn 1.9.1`；numpy 落在 `[2.0.2, 2.7)`，`NUMPY_RANGE_OK=True`（`version_combo.log`）。

## 4. 偏差与矩阵外新增

### 4.1 uv 版本偏差

- 矩阵：`0.13.7`；实际：`0.12.16`。
- 性质：uv 是安装/环境工具，不进入 `.venv` 运行时依赖；矩阵原文写明“本机已有 0.12.16，是否升级由 WP-01 决定”。
- 决定：**保留 0.12.16**。它成功完成 3.11.16 venv 创建、55 包解析、58 包安装与干净环境复现；升级全局工具不在本工作包必要范围，且会改变用户机器上的工具版本。
- 处置：记录为偏差，未静默升级，未用“大致相同”表述。

### 4.2 httpx2（矩阵外，用户批准）

- 触发：`TestClient` 首次冒烟 exit 1：`RuntimeError: The starlette.testclient module requires the httpx2 package to be installed.`（starlette 1.10.0 的 `testclient.py` 明确导入 `httpx2`）。
- 约束：`starlette 1.10.0` 元数据 `Requires-Dist: httpx2>=2.0.0; extra == 'full'`。
- 批准：2026-11-10 用户选择“批准安装 httpx2”。
- 安装：`httpx2==2.16.0`，传递依赖 `httpcore2==2.16.0`、`truststore==0.10.5`；exit 0，12.87 s。
- 范围：仅测试路径；不改变 FastAPI 运行时要求。

## 5. 冒烟验证

| # | 验证 | 命令/方式 | 结果 | 退出码 | 日志 |
|---|---|---|---|---|---|
| a | FastAPI `TestClient` 最小端点 | `TestClient(app).get('/health')` | `TESTCLIENT_OK 200 {'ok': True}` | 0 | `testclient_smoke.log` |
| b | starlette 实际版本与回退判断 | `starlette.__version__` | `1.10.0`；与矩阵一致；**不回退** | 0 | `starlette_resolution.txt` |
| c | 8 个模块导入 | `import fastapi, pydantic, networkx, pandas, sklearn, cryptography, streamlit, pytest` | 全部成功 | 0 | `install.log` / 报告 |
| d | numpy 组合与区间 | `numpy/scipy/pandas/sklearn` 版本打印 | `2.4.6 / 1.17.1 / 3.1.1 / 1.9.1`；区间 PASS | 0 | `version_combo.log` |
| e | 真实 uvicorn 启动 | 本地 `127.0.0.1:8765/health` | `STARTUP_OK`，HTTP 200 `{"ok":true}` | 0 | `startup.log` |

## 6. 体积与耗时

详见 [`size_and_timing.md`](size_and_timing.md)。

- `.venv`：**502,349,269 字节（502.3 MB）**；矩阵估算 350–450 MB；**超出上限 52.3 MB（+11.6%）**，不写成“大致符合”。
- 安装主路径耗时：venv 0.51 s + 矩阵包 46.10 s + httpx2 12.87 s = **59.48 s**；矩阵无耗时估算。
- `.uv-cache` 473.7 MB 是本地解压缓存，**不是**网络下载字节；uv 0.12.16 未输出下载字节，未拿缓存体积冒充下载量。

## 7. 边界核对

- `researchflow/` 仍只有 `.gitkeep`；未写业务代码、未建数据库、未写 API、未做模板。
- 未安装矩阵外其它包；唯一例外 `httpx2` 已获用户批准并记录。
- 未改 `AGENTS.md`、冻结的 ①–⑧/⑨、G0–G7 状态（G0 已由用户 PASS；G1–G7 仍 `NOT_STARTED`）。
- `.venv`、`.uv-cache` 均不纳入 Git；`requirements.in`、`requirements.lock` 纳入版本控制。
- 未提交前 `git status` 变动由本报告与证据文件构成；提交信息 `feat(wp-01): 锁定 T0 依赖环境`。

## 8. 证据清单

`env_fingerprint.json`、`dependency_resolution.txt`、`dependency_resolution_dryrun.log`、`install.log`、`install_httpx2.log`、`lockfile.txt`、`pip_check.log`、`pip_list.log`、`testclient_smoke.log`、`starlette_resolution.txt`、`version_combo.log`、`startup.log`、`clean_room_install.log`、`venv_cache_failure.log`、`size_and_timing.md`、`make_evidence.py`、`make_evidence.log`。
