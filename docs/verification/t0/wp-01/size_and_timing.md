# WP-01 体积与耗时实测

> 实测时间：2026-11-10（Asia/Shanghai）；解释器：`D:\ResearchFlow-project\.venv\Scripts\python.exe`（CPython 3.11.16，64 位）。
> 对照：[`docs/verification/g0/09_dependency_matrix.md`](../../g0/09_dependency_matrix.md) §4「体积与内存可行性」。

## 1. 体积

| 项 | 实测 | 矩阵估算 | 对比 |
|---|---|---|---|
| `.venv` 安装体积 | **502,349,269 字节（502.3 MB；479.1 MiB）** | 约 350–450 MB | 比上限 450 MB 多 52.3 MB（+11.6%）；比下限 350 MB 多 152.3 MB（+43.5%） |
| `.venv` 文件数 | 12,655 | 未估 | — |
| `requirements.lock` 锁定包 | 58 | 矩阵列 17 个第三方包 + SQLite；其余为传递依赖 | 58 为完整闭包，含矩阵外批准的 `httpx2` 及其 2 个传递依赖 |
| `.uv-cache` 本地缓存 | 473,658,225 字节（473.7 MB；451.7 MiB） | 估算下载约 150 MB | **不可直接比较**：这是 uv 解压后的本地缓存，不是网络下载字节；uv 0.12.16 未输出网络字节统计 |

结论：安装体积**超出矩阵估算上限**，不是“大致相同”。原因：矩阵为按 wheel 大小与经验倍率估算；实际闭包含 Streamlit 全套前端/可视化传递依赖、Windows 二进制 wheel，以及新增的 `httpx2` 测试依赖。该偏差不改变版本矩阵，已记录，未用估算值回填实测值。

## 2. 耗时

| 步骤 | 实测耗时 | 说明 |
|---|---|---|
| `uv venv --python 3.11.16 .venv` | 0.51 s | 使用 uv 托管 3.11.16；失败重试 1 次（默认缓存目录在沙箱外，改用项目内缓存） |
| 矩阵内 16 个直接 pin 安装 | 46.10 s | 解析 55 个包；`uv pip install` exit 0 |
| `httpx2==2.16.0` 安装 | 12.87 s | 解析 7 个包，实际新增 3 个；用户批准后执行 |
| 干净环境从 `requirements.lock` 复现 | 43.95 s | `.venv-repro` 创建 + 58 包安装 + TestClient 200；已删除 |
| 环境安装主路径合计 | **59.48 s** | venv 0.51 s + 矩阵安装 46.10 s + httpx2 12.87 s |

矩阵没有给出耗时估算，因此只记录实测，不编造“符合估算”的结论。

## 3. 复现命令

```powershell
$env:UV_CACHE_DIR = 'D:\ResearchFlow-project\.uv-cache'
uv venv --python 3.11.16 .venv
uv pip install --python .\.venv\Scripts\python.exe -r requirements.lock
uv pip check --python .\.venv\Scripts\python.exe
```

证据：`install.log`、`install_httpx2.log`、`clean_room_install.log`、`env_fingerprint.json`。
