# 依赖版本锁定矩阵（WP-01 基线，v1.0）

> 冻结日期：2026-11-10｜状态：**WP-01 锁定基线**｜被取代版本：**无（2026-11-09 调研稿首次锁定为 v1.0）**。
> 性质：**已由用户 2026-11-10 裁决锁定为 `WP-01` 依赖基线**；锁定不等于已安装——**未创建 `.venv`、未安装、未生成 lock 文件**，安装结果须按本矩阵逐项核对。
> 日期：2026-11-09（Asia/Shanghai）调研；2026-11-10 锁定。
> 目标环境：Windows 11 / 16GB / CPU-only / **CPython 3.11.16（64 位，uv 托管）**。
> 数据来源：PyPI JSON API（`https://pypi.org/pypi/<pkg>/json` 与 `/<pkg>/<ver>/json`），读取 `requires_python`、wheel 文件名与 `requires_dist`；脚本 [`research_versions.py`](research_versions.py)，原始日志 [`08_dependency_matrix.log`](08_dependency_matrix.log)。
> 局限：只验证“元数据与 wheel 存在”，**未安装、未导入、未跑契约冒烟**；版本配对是否真能工作，须在 WP-01 安装后实测。锁定后任何版本偏差都必须记录理由，不得静默升级。

## 1. 结论先行

- 全部 10 个指定包 + 7 个关键传递依赖（合计 **17 个第三方包**；另 SQLite 随解释器）都有 **cp311/win_amd64 或 `py3-none-any` wheel**，**无需在本机编译**（无一标红）。
- 本矩阵自 2026-11-10 起是 **`WP-01` 锁定基线**，已写入 ⑦ `WP-01` 的入口条件；安装解析结果必须逐项一致，偏差须记录理由。
- numpy 只能走 **2.x**：本组依赖的下界是 `>=2.0.2`（pandas 3.1.1），上界是 `<2.7`（scipy 1.17.1）；不存在 numpy 1.x 路径。
- **Python 3.11 已进入 security-only 阶段**（PEP 664，安全支持到 2027-10），上游已开始丢 3.11：networkx 3.7 要 `>=3.12`、numpy 2.5 要 `>=3.12`、scipy 1.18 要 `>=3.12`。本矩阵选的是**各包最后一条支持 3.11 的线**，必须锁定，不能“装最新”。

## 2. 候选矩阵

| 包 | 选定版本 | `requires_python` | wheel（win 平台） | 类型 | wheel 大小 | 选择理由 |
|---|---|---|---|---|---|---|
| **fastapi** | 0.162.2 | `>=3.10` | `fastapi-0.162.2-py3-none-any.whl` | 纯 Python | 0.14 MB | 最新稳定；要求 `pydantic>=2.9`，与下方 pydantic 2.14.3 兼容 |
| **pydantic** | 2.14.3 | `>=3.10` | `pydantic-2.14.3-py3-none-any.whl` | 纯 Python | 0.47 MB | 最新 2.x；精确 pin `pydantic-core==2.50.4` |
| **networkx** | 3.6.1 | `!=3.14.1,>=3.11` | `networkx-3.6.1-py3-none-any.whl` | 纯 Python | 1.97 MB | **3.7 要求 `>=3.12`**，3.6.1 是最后支持 3.11 的版本 |
| **pandas** | 3.1.1 | `>=3.11` | `pandas-3.1.1-cp311-cp311-win_amd64.whl` | 二进制 | 10.47 MB | 最新且提供 cp311 wheel；要求 `numpy>=2.0.2` |
| **scikit-learn** | 1.9.1 | `>=3.11` | `scikit_learn-1.9.1-cp311-cp311-win_amd64.whl` | 二进制 | 7.94 MB | 最新且提供 cp311 wheel |
| **cryptography** | 50.0.2 | `!=3.9.0,!=3.9.1,>=3.9` | `cryptography-50.0.2-cp311-abi3-win_amd64.whl` | 二进制（abi3） | 3.65 MB | 最新；`abi3` wheel 向前兼容 3.11+ |
| **streamlit** | 1.67.0 | `>=3.11` | `streamlit-1.67.0-py3-none-any.whl` | 纯 Python | 10.72 MB | 最新；依赖区间是体积与冲突的主要来源（见 §3） |
| **pytest** | 9.2.0 | `>=3.10` | `pytest-9.2.0-py3-none-any.whl` | 纯 Python | 0.39 MB | 最新稳定 |
| **uv** | 0.13.7 | `>=3.8` | `uv-0.13.7-py3-none-win_amd64.whl` | 单文件二进制 | 14.62 MB | 仅作安装/环境工具；**本机已有 0.12.16**，是否升级由 WP-01 决定 |
| **SQLite** | 3.53.1（随解释器） | —（stdlib） | 无 wheel（`sqlite3` 内置） | 标准库 | — | 本机 3.11.16 实测 `sqlite3.sqlite_version = 3.53.1`；WAL、外键均支持 |

### 2.1 关键传递依赖（决定“是否真的不用编译”）

| 包 | 选定版本 | `requires_python` | wheel | 大小 | 说明 |
|---|---|---|---|---|---|
| **numpy** | 2.4.6 | `>=3.11` | `numpy-2.4.6-cp311-cp311-win_amd64.whl` | 12.02 MB | 2.5.x 起要求 `>=3.12`；2.4.6 是 3.11 线 |
| **scipy** | 1.17.1 | `>=3.11` | `scipy-1.17.1-cp311-cp311-win_amd64.whl` | 34.91 MB | 1.18 起要求 `>=3.12`；要求 `numpy<2.7` |
| **pydantic-core** | 2.50.4 | `>=3.10` | `pydantic_core-2.50.4-cp311-cp311-win_amd64.whl` | 2.15 MB | 由 pydantic **精确 pin**，不可单独升级 |
| **starlette** | 1.10.0 | `>=3.11` | `starlette-1.10.0-py3-none-any.whl` | 0.08 MB | fastapi 要求 `>=0.46.0`、streamlit 要求 `<2,>=0.46`；1.x 配对见 §3 风险 |
| **cffi** | 2.1.1 | `>=3.10` | `cffi-2.1.1-cp311-cp311-win_amd64.whl` | 0.18 MB | cryptography 要求 `>=2.0.0` |
| **pyarrow** | 26.0.1 | `>=3.11` | `pyarrow-26.0.1-cp311-cp311-win_amd64.whl` | 27.69 MB | streamlit 要求 `<27,>=12`；体积最大项之一 |
| **pillow** | 13.0.0 | `>=3.11` | `pillow-13.0.0-cp311-cp311-win_amd64.whl` | 6.94 MB | streamlit 要求 `<14,>=9.2` |
| **protobuf** | 7.36.2 | `>=3.10` | `protobuf-7.36.2-cp310-abi3-win_amd64.whl` | 0.44 MB | streamlit 要求 `<8,>=5.26.1` |

其余纯 Python 小包（uvicorn、anyio、altair、pydeck、requests、click、packaging、pygments、pluggy、iniconfig、colorama、joblib、threadpoolctl、narwhals、python-dateutil、tzdata、annotated-types、annotated-doc、typing-extensions、typing-inspection、opentelemetry-api、pycparser、itsdangerous、python-multipart、watchdog/websockets）均为 `py3-none-any` 或小型二进制 wheel，未见编译需求。

## 3. 已知传递依赖冲突与配对

| 冲突点 | 事实 | 处置 |
|---|---|---|
| **numpy 1.x / 2.x 分界** | pandas 3.1.1 要求 `numpy>=2.0.2`；scipy 1.17.1 要求 `numpy<2.7,>=1.26.4`；scikit-learn 要求 `>=1.24.1`；streamlit 要求 `<3,>=1.25`。交集 `[2.0.2, 2.7)` | 固定 **numpy 2.4.6**；不存在兼容 numpy 1.x 的组合，T0 不要引入要求 `numpy<2` 的插件 |
| **pydantic ↔ fastapi** | fastapi 0.162.2 要求 `pydantic>=2.9.0`（无上界）；pydantic 2.14.3 要求 `pydantic-core==2.50.4` | 固定 pydantic 2.14.3 + pydantic-core 2.50.4；**不要手工升 pydantic-core**，它由 pydantic 精确 pin |
| **starlette 1.x 配对** | fastapi 只声明 `starlette>=0.46.0`（无上界），streamlit 声明 `<2,>=0.46`；解析器会选 1.10.0 | 这是本矩阵**唯一无法用元数据排除**的风险：FastAPI 0.162.2 是否已在 Starlette 1.x 上验证，元数据不能证明。WP-01 安装后必须跑一次 `TestClient` 契约冒烟；若失败，回退到 0.4x 线并记录实测版本，不得凭猜测定版 |
| **scipy ↔ numpy** | scipy 1.17.1 要求 `numpy<2.7`，与 numpy 2.4.6 兼容 | 固定 scipy 1.17.1 |
| **streamlit 的宽区间** | `pandas<4`、`pyarrow<27`、`pillow<14`、`protobuf<8`、`numpy<3` | 均在上述选定版本内；升级任何一个大包前先看 streamlit 区间 |
| **cryptography/cffi** | cryptography 50 要求 `cffi>=2.0.0` | cffi 2.1.1 满足 |
| **SQLite** | 标准库自带，不参与 pip 解析 | 不锁版本号，但在 `WP-01` 记录 `sqlite3.sqlite_version` |

## 4. 体积与内存可行性

| 项 | 估算 | 依据 |
|---|---|---|
| 已列 17 个 wheel 下载体积 | **约 134.8 MB** | 逐包 wheel 大小求和（见 §2） |
| 其余纯 Python 小包 | 约 10–20 MB（估） | 以 pydeck/altair/uvicorn 为主；未逐包核 |
| **下载合计** | **约 150 MB（估）** | 上述两项 |
| 解压安装体积 | **约 350–450 MB（估）** | 二进制扩展通常为 wheel 的 2–2.5×；纯 Python 约 1.2–1.5× |
| 16GB 内存可行性 | **可行** | T0 是内置表格 ML，单任务数据量小；2 个执行 worker + Streamlit + SQLite 的常驻峰值预计 < 3 GB。scikit-learn 的并行度受 `max_workers=2` 限制，不会按 16 核全开 |

以上均为**估算，不是实测**；`WP-01` 安装后必须记录真实下载量、`site-packages` 体积与空载/峰值内存。

**WP-01 实测（2026-11-10）**：

| 项 | 实测 | 与估算对比 |
|---|---|---|
| `.venv` 体积 | 502,349,269 字节（502.3 MB） | 超估算上限 450 MB 达 52.3 MB（+11.6%） |
| 安装主路径耗时 | 59.48 s（0.51 + 46.10 + 12.87） | 矩阵无耗时估算 |
| 干净环境复现 | 43.95 s | — |
| `.uv-cache` | 473.7 MB | 解压缓存，不是网络下载字节，不可直接比较 |

用户 2026-11-10 裁决：**接受为已知偏差**，不裁剪依赖组成；记录见 [`30_wp01_acceptance.md`](../t0/wp-01/30_wp01_acceptance.md)。

## 5. 风险与建议

| # | 风险 | 影响 | 建议 |
|---|---|---|---|
| 1 | Python 3.11 进入 security-only，上游陆续丢 3.11 | 以后无法“升级到最新”，只能维护 3.11 线 | 现在锁定本矩阵；升级 Python 需单独 ADR，不在 T0 内做 |
| 2 | starlette 1.x 与 fastapi 0.162.2 的实测兼容性未知 | Web 层启动或 `TestClient` 失败 | WP-01 安装后先跑契约冒烟；失败则回退并记录实测组合 |
| 3 | pydantic-core 被精确 pin | 手工升级 pydantic 会导致 core 版本不匹配、导入报错 | 只用 pydantic 的解析结果，不单独升级 core |
| 4 | scipy 34.9 MB + pyarrow 27.7 MB + uv 14.6 MB 体积较大 | 首次安装慢、磁盘占用 | 可接受；uv 可作为工具而非依赖，不进入运行环境 |
| 5 | networkx/numpy/scipy 的“最后 3.11 线”会随时间老化 | 安全补丁可能不再回移到 3.11 | 记录版本冻结理由；T1 再评估 Python 升级 |

## 6. 未做与边界

- 未创建 `.venv`、未 `pip install` / `uv sync`、未生成 `requirements.txt` / `uv.lock` / `pylock.toml`。
- 未导入任何包，未跑 FastAPI/Streamlit 冒烟。
- 只访问 PyPI 元数据与 wheel 文件名/大小，未下载 wheel 包体。
- 版本号以 2026-11-09 的 PyPI 元数据为准；后续复核必须重跑 `research_versions.py` 并对比日志。