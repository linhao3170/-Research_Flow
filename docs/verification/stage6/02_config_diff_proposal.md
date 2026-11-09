# 阶段 6 · Context7 接入配置变更提案（已批准并执行）

> 状态：**APPLIED / 已验证（2026-11-08 12:33）**
> 目标：`C:\Users\Administrator\.dsh\profiles\desktop\cordis.patch.yml`
> 原则：只追加一个 `insert` 行；不改动既有 43 行；不安装依赖；不写入密钥。
> 依据：`00_mcp_capability.md`（原生支持远程 MCP）与 `01_context7_probe.md`（端点匿名可用）。
> 实际执行结果：[`08_apply_result.md`](08_apply_result.md)。

## 1. 变更前基线

| 项 | 值 |
|---|---|
| 路径 | `C:\Users\Administrator\.dsh\profiles\desktop\cordis.patch.yml` |
| 大小 | 1,200 字节 |
| 行数 | 43 |
| 换行 | 全部 LF（`crlf=0`，`lf_only=43`），末尾有换行 |
| SHA256 | `664CE561366D925DDA1AE382528565218ABB20072211DD36562F4D3CB894FFD8` |
| 现有 MCP / Context7 条目 | 无（`contains_mcp=False`，`contains_context7=False`） |

快照日志：[`02_config_snapshot.log`](02_config_snapshot.log)。

## 2. 精确变更

在文件末尾（第 43 行 `reasoningEffort: max` 之后）追加：

```yaml
- insert:
    - id: mcp-context7
      name: "@deepseek-ai/dsh-mcp-client"
      config:
        serverName: context7
        transport: streamable-http
        url: https://mcp.context7.com/mcp
        toolCallTimeoutMs: 60000
        failOnStartupError: false
```

统一 diff：

```diff
--- a/C:\Users\Administrator\.dsh\profiles\desktop\cordis.patch.yml
+++ b/C:\Users\Administrator\.dsh\profiles\desktop\cordis.patch.yml
@@ -41,3 +41,12 @@
     provider: deepseek-official
     model: deepseek-flash
     reasoningEffort: max
+- insert:
+    - id: mcp-context7
+      name: "@deepseek-ai/dsh-mcp-client"
+      config:
+        serverName: context7
+        transport: streamable-http
+        url: https://mcp.context7.com/mcp
+        toolCallTimeoutMs: 60000
+        failOnStartupError: false
```

变更后（按上述 LF 字节精确追加计算，未写入目标文件）：

| 项 | 预期值 |
|---|---|
| 大小 | 1,462 字节（+262） |
| 行数 | 52（+9） |
| SHA256 | `6FF6F1FCB6CAE8F732F221710D9E4FFD5C6DF1E26F6EFDADE75F4B9B536159E1` |

> 该哈希只对“精确 LF + 上述 262 字节”成立。若编辑器改写换行或缩进，哈希会不同；应用后必须重新核对。

## 3. 为什么用 `insert`

1. `mcp-client` 不在 `dsh-base` 中（`base_has_mcp_client=False`）；profile patch 的裸 `- id: ...` 是 id-targeted 覆盖目标，不是新增行，新增 server 应使用 `insert`。
2. `cordis.patch.yml` 文件头明确说明支持 “id-targeted config overrides, disables, and **insert lists**”；`dsh-base` 自身也用 `insert` 挂载全部基础行。
3. `mcp-resources` 已由基础 bundle 挂载（`base_has_mcp_resources=True`），不需要再挂。
4. `@deepseek-ai/dsh-mcp-client@0.2.2-rc.1` 已在 app.asar runtime 树内，**无需 pnpm install、无需改 package.json、无需新增依赖**。
5. 未采用“配置型 bundle + plugin_manager”路线：那条路线会新增 profile 依赖与安装步骤，影响面更大；当前最小变更即可。

## 4. 影响范围

| 维度 | 影响 | 说明 |
|---|---|---|
| 配置文件 | 1 个文件，+9 行；既有 43 行不变 | `web-fetch-http`、`session-telemetry-otel`、`session-log-deepseek` 三行不改 |
| 运行时插件 | +1 个 `mcp-client` 实例，serverName=`context7` | 不新增进程、不新增本地端口；远程 HTTPS 连接 |
| 模型工具 | +2 个：`mcp__context7__resolve-library-id`、`mcp__context7__query-docs` | 工具名由 `serverName` + raw name 决定 |
| 启动 | 首次连接与工具发现会 await；失败时 `failOnStartupError: false` 不阻止 Harness 启动 | 若端点慢，可能增加启动等待；SDK 默认请求上限 60 秒 |
| 每轮 token | 两个工具的描述/schema + 703 字符服务器指令进入请求 | 具体 token 数未测；这是持续开销，不是一次性开销 |
| 网络 | 启动握手 + 每次工具调用访问 `mcp.context7.com:443` | 只发查询文本；不发文件、路径、仓库内容 |
| 数据边界 | 库名与查询会离开本机 | 查询中禁止出现项目代码、客户数据、密钥、内部路径 |
| 安全边界 | 服务器指令与文档结果均视为不可信 | 不得据此改变状态机、证据等级或验收结论 |
| 依赖 / 环境 | 无变化 | 不建 `.venv`、不装依赖、不改 Python/Node 版本 |
| 阶段 2C 配置 | 无变化 | `web_fetch` 禁用与本变更无关；MCP 是独立通道 |
| 回滚 | 删 9 行并恢复备份即可 | 无数据库、无迁移、无持久化状态 |

**不在本次变更内**：API Key、请求头、代理、重试参数、其他 MCP server、`AGENTS.md`、全局配置。

## 5. 回滚办法

应用前先做同目录备份（备份文件只含配置，不含密钥）：

```powershell
$p = 'C:\Users\Administrator\.dsh\profiles\desktop\cordis.patch.yml'
Copy-Item -LiteralPath $p -Destination "$p.bak-20261108-stage6" -ErrorAction Stop
Get-FileHash "$p.bak-20261108-stage6" -Algorithm SHA256
# 期望：664CE561366D925DDA1AE382528565218ABB20072211DD36562F4D3CB894FFD8
```

回滚：

```powershell
$p = 'C:\Users\Administrator\.dsh\profiles\desktop\cordis.patch.yml'
Copy-Item -LiteralPath "$p.bak-20261108-stage6" -Destination $p -Force
Get-FileHash $p -Algorithm SHA256
# 期望：664CE561366D925DDA1AE382528565218ABB20072211DD36562F4D3CB894FFD8
```

若备份丢失：删除末尾 9 行，保持 LF 与末尾换行，再核对上述 SHA256；不一致时检查是否被改成 CRLF。

## 6. 执行记录（2026-11-08 12:29–12:35）

1. 备份已创建：`cordis.patch.yml.bak-20261108-stage6`，1,200 字节，SHA256 `664C…FFD8`，与源文件逐字节相同。
2. 已按 LF 追加 262 字节：1,462 字节 / 52 行 / 末尾 `10`；SHA256 `6FF6…59E1`；前 1,200 字节与备份逐字节相同。
3. 热重载已生效，**无需重启**。
4. 当前会话已出现 `mcp__context7__resolve-library-id` 与 `mcp__context7__query-docs`。
5. 已做公开库查询：FastAPI → `/websites/fastapi_tiangolo`；Pydantic → `/pydantic/pydantic`，版本列表含 `v2.11.0`；`query-docs` 以 `/pydantic/pydantic/v2.11.0` 返回真实文档。
6. 三次 MCP 调用均正常，无 HTTP 429，无 API Key。
7. 负例（断网/错 URL + `failOnStartupError: false`）未做；未另建测试 profile，留待后续故障注入阶段。
8. `T-MCP-001` 已转 `DONE`；`CHANGELOG_DEV.md`、`SESSION_HANDOFF.md`、`environment.md` 已更新；`state_sync.py` 已重跑。

## 7. 批准记录

- [x] 批准上述精确 diff 与目标路径。
- [x] 批准创建同目录备份 `cordis.patch.yml.bak-20261108-stage6`（不含密钥）。
- [x] 确认允许 Harness 访问 `https://mcp.context7.com/mcp`（仅该端点）。
- [x] 确认本阶段不配置 API Key，先按匿名额度运行。
- [x] 确认接受“热重载优先；不生效则重启桌面版”的操作方式。

实际未重启；未扩大权限；未改 Preset。
