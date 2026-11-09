# 24 Docker、本地大模型、CUDA 与大型依赖

## 1. 项目内

| 项 | 结果 |
|---|---|
| `.venv` | 不存在 |
| `node_modules` | 不存在 |
| `pyproject.toml` / `package.json` / `requirements.txt` | 不存在 |
| `Dockerfile` / `docker-compose.yml` | 不存在 |
| 模型文件（`.gguf` / `.safetensors` / `.onnx` / `.pth` / `.pt`） | 0 |
| `researchflow/`、`contracts/` | 仅 `.gitkeep` |
| 项目 Python 包 | 仅 `pip 26.2.1`、`setuptools 84.0.0` |
| 本阶段安装 | 0（未创建 `.venv`、未装依赖） |

## 2. 系统级既有环境（非本阶段安装）

| 项 | 事实 |
|---|---|
| Docker Desktop | `C:\Program Files\Docker\Docker\resources\bin\docker.exe` 存在；服务 `com.docker.service` 为 `Stopped`；项目未使用、无 Docker 文件 |
| `nvidia-smi` | `C:\Windows\system32\nvidia-smi.exe` 存在（驱动工具）；未用于项目 |
| CUDA Toolkit | `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA` 不存在；`nvcc` 未找到 |
| `ollama` | 未找到 |

## 3. 判定

**PASS（项目范围）**：本项目未安装/未使用 Docker、本地大模型、CUDA 工具链或不必要的大型依赖；项目依赖面仅为 Python 标准库。

**例外说明**：整机既有 Docker Desktop 与 NVIDIA 驱动工具，不是本阶段安装，也不在本项目使用。若按“整机从未安装 Docker”的字面口径，该项应为 FAIL；本报告采用“项目范围”口径并明确记录该例外。未卸载任何用户软件。
