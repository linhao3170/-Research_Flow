# 21 凭据与 Session 安全审计

## 1. 敏感位置与访问情况

| 位置 | 本阶段是否读取内容 | 说明 |
|---|---|---|
| `C:\Users\Administrator\.dsh\.credentials.yaml` | **否** | 仅在 `.dsh` 目录列表中看到文件名；未打开、未复制、未回显 |
| `C:\Users\Administrator\.dsh\sessions\` | **否** | 未列出会话内容、未读取、未导出、未写入项目 |
| `C:\Users\Administrator\.dsh\storages\` | **否** | 未读取 |
| `C:\Users\Administrator\.dsh\profiles\desktop\cordis.patch.yml` | 只读 2C 三块 | 仅读取 `session-log-deepseek`、`session-telemetry-otel`、`web-fetch-http` 及其相邻配置；未修改；文件哈希 `6FF6F1FC…59E1` 与阶段 6 一致 |
| 阶段 6 备份 `cordis.patch.yml.bak-20261108-stage6` | 只读哈希/大小 | 1,200 字节；SHA256 `664CE561…FFD8`；未删除、未修改 |
| `C:\Users\Administrator\.dsh\profiles\node_modules` 的 431 个目录联接 | 只读计数/目标检查 | 未修改、未删除；0 个断链 |
| 旧 CLI `@deepseek-ai/dsh` 0.1.0-rc.8 | 只读 `package.json` 版本/文件计数 | 未修改 |

## 2. 项目内写入审计

本阶段项目内新增/修改仅限：

- `docs/verification/stage8/` 证据文件；
- 计划内的 `docs/state/project_state.json`、生成状态文件、`CHANGELOG_DEV.md`、`SESSION_HANDOFF.md`、记忆/来源/冲突文档；
- 无业务代码、无 `.venv`、无依赖安装、无 `.env`、无密钥文件。

## 3. 秘密扫描

- 对 `docs/verification/stage8/` 的 43 个文件执行 6 类密钥模式扫描：**0 命中**。
- 对全项目 169 个文本文件（`*.md` / `*.json` / `*.log` / `*.txt` / `*.py`，排除 `.git`）执行同一扫描：**0 命中**。
- 证据：`21_secret_scan.log`。
- 报告中未出现 Key、Token、密码、私钥或 Session 标识。

## 4. 诊断目录

- `D:\ResearchFlow-project\tmpavet2qv9` 是用户指定 BLK-003 取证命令创建的空目录；权限诊断已完成（`NOT_THIS_CLASS`，`FIXED=0`），阶段 8 保留该目录，**阶段 9 开始时只删除这一个目录**，不修改 ACL、不删除其他目录。
- 该目录不含文件，不包含凭据或 Session 内容。

## 4. Session 与模型探针

- 模型探针使用 1 个 DSH 子 Agent；其会话存储位于 Harness 运行目录，不在项目内；未读取、未导出。
- 当前会话 ID 未写入任何项目文件；环境变量输出中的 `DSH_SESSION_ID` 已在证据日志中排除。

## 5. 判定

PASS：未读取凭据、未读取/导出 Session、未写入项目；431 联接与 Profile 备份未被修改。当前 `danger-full-access` 策略使“未越权”依赖 Agent 自律而非沙箱强制，该风险另见 `06_workspace_policy.md`。
