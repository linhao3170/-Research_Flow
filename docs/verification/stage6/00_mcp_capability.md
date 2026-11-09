# 阶段 6 · MCP Client 能力核实（DSH 0.2.2-rc.1）

> 核实时间：2026-11-08 12:05–12:36（Asia/Shanghai）
> 核实对象：DeepSeek Harness 桌面版 `0.2.2-rc.1`，安装目录 `D:\deepseek_harness1`
> 事实原则：以 `app.asar` 内 `0.2.2-rc.1` 的 `dsh-mcp-client` 源码与实际端点探测为准；
> profile 下 `0.1.0-rc.8` 的同名包只作为解析回退，不作为当前行为依据。
> 结论：**当前版本原生支持远程 MCP（Streamable HTTP）**；无需第三方桥接、无需安装依赖。
> 接入状态：2026-11-08 12:33 已写入 profile 并热重载生效；两个工具已真实调用，详见 `08_apply_result.md`。

## 1. 事实来源

| 证据 | 路径 | 说明 |
|---|---|---|
| 静态检查脚本 | `docs/verification/stage6/inspect_mcp_client.py` | 只读解析 asar，输出包版本、配置字段、传输实现、解析顺序 |
| 静态检查日志 | `docs/verification/stage6/00_mcp_source.log` | 2026-11-08 实跑，`INSPECT_RESULT=PASS`，exit 0 |
| 运行时描述 | `app.asar` 内 `dsh/desktop-runtime.json` | `release.version=0.2.2-rc.1`，Node 24.21.0，pnpm 11.28.5 |
| 运行时包清单 | `app.asar` 内 `dsh/package.json` | `@deepseek-ai/dsh-desktop-runtime@0.2.2-rc.1`，依赖含 `dsh-mcp-client@0.2.2-rc.1` |
| MCP Client 包 | `app.asar` 内 `dsh/node_modules/@deepseek-ai/dsh-mcp-client/` | `package.json` 版本 `0.2.2-rc.1`，MCP SDK `@modelcontextprotocol/client@2.2.0` |
| 基础 bundle | `app.asar` 内 `dsh-base/cordis.patch.yml` | 已挂载 `mcp-resources`，**未**挂载 `mcp-client`（默认无服务器） |
| 解析顺序 | `app.asar` 内 `dsh-app-boot/lib/index.js` 第 1317–1321、1763–1779 行 | 安装锚点优先，profile 目录仅第二锚点 |

## 2. 运行时与包版本

| 项 | 已核实值 |
|---|---|
| 桌面壳 | `@deepseek-ai/dsh-desktop@0.2.2-rc.1` |
| 内置 runtime | `@deepseek-ai/dsh-desktop-runtime@0.2.2-rc.1` |
| MCP Client | `@deepseek-ai/dsh-mcp-client@0.2.2-rc.1` |
| MCP SDK | `@modelcontextprotocol/client@2.2.0` |
| MCP Resources | `@deepseek-ai/dsh-mcp-resources@0.2.2-rc.1`（基础 bundle 已挂载） |
| profile 侧旧包 | `C:\Users\Administrator\.dsh\profiles\node_modules\...` 为 `0.1.0-rc.8`；仅作第二解析锚点 |

`dsh-app-boot` 的解析契约明确写明：bundle 与随包插件先由 dsh 安装目录解析，再从 profile 目录解析；`@deepseek-ai/dsh-base` 等随包 bundle 必须来自与运行中的 dsh 同一安装。因此实际行为以 app.asar 内 `0.2.2-rc.1` 为准。

## 3. 能力矩阵

| 能力 | 结论 | 证据 |
|---|---|---|
| 连接外部 MCP 服务器 | 支持 | `README.md` 第 12、28 行；每个 server 一条插件配置 |
| 远程传输 | 支持 `streamable-http` | `lib/index.js` 第 46、793 行；`StreamableHTTPClientTransport(new URL(config.url), { requestInit: { headers } })` |
| 本地传输 | 支持 `stdio` | `lib/index.js` 第 782 行；`command` / `args` / `env` / `cwd` |
| 工具命名 | `mcp__<serverName>__<rawName>` | `lib/index.js` 第 96–100 行；冲突时整代回滚 |
| `serverName` 约束 | `[A-Za-z0-9_-]{1,32}`，同一注册作用域唯一 | `lib/index.js` 第 768、783、794、819 行 |
| 单次工具超时 | 默认 60,000 ms | `lib/index.js` 第 766、788、797 行 |
| 启动失败策略 | `failOnStartupError` 默认 `false` | `lib/index.js` 第 789、798、833 行；失败时 Harness 仍启动，仅无该 server 工具 |
| 重连 | 默认开启；500 ms 起，指数退避至 30 s，连续 10 次失败后停止 | `lib/index.js` 第 434–439、775–780 行 |
| 服务器指令 | 作为字面文本进入系统提示；UTF-8 上限 32,768 字节 | `lib/index.js` 第 441、790、799 行；`README.md` 第 189–199 行 |
| MCP 资源 | 只读、按需；由基础 bundle 的 `mcp-resources` 提供 | `dsh-base/cordis.patch.yml` 第 492–493 行；`README.md` 第 208 行 |
| MCP prompts 模板 | **不支持** | `README.md` 第 12、208 行 |
| 默认启用服务器 | **无**；不配置则没有 MCP 工具 | `README.md` 第 12 行；base patch 无 `mcp-client` 行 |
| 需要 task 扩展的工具 | 调用时拒绝，不桥接 | `README.md` 第 213 行 |
| 图片结果 | 仅在模型与附件能力满足时持久化；音频/嵌入资源转为诊断文本 | `README.md` 第 87、211 行 |

结论：远程 MCP 是原生能力，不是实验性旁路；Context7 的 `streamable-http` 端点与 `headers` 字段都在支持范围内。

## 4. 配置与加载机制

MCP server 以 Cordis 插件条目声明，一个 server 一条：

```yaml
- insert:
    - id: <loader-row-id>
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: <namespace>
        transport: streamable-http
        url: https://...
```

关键点：

1. `mcp-client` 不在基础 bundle 中，新增 server 必须用 `insert` 列表插入新行；直接写 `- id: ...` 会被当作对既有行的覆盖。
2. 包已在 app.asar 的 runtime 树内，**不需要** `pnpm install`、不需要新增 npm 依赖。
3. `mcp-resources` 已由 `dsh-base` 挂载，资源工具随 client 配置启用。
4. profile patch 支持热重载；实际是否无需重启即生效，需在批准后实测。

## 5. 安全与信任边界

- **服务器指令不可信**：Context7 的 `instructions` 会作为字面文本进入系统提示；它来自第三方，不得当作项目规则。当前 703 字符，低于 32 KiB 上限。
- **工具结果不可信**：文档内容可能包含诱导性文本；只能作为参考资料，不能推动 ResearchFlow 状态机、证据等级或验收结论。
- **stdio 环境清洗**：子进程环境会剔除匹配 `KEY|PASSWORD|SECRET|TOKEN` 的环境变量；显式 `env` 覆盖除外。
- **HTTP 头**：`headers` 会随请求发送；不得把密钥写入 profile 文件。需要密钥时应使用 Harness 正式凭据界面。
- **无本地文件权限**：MCP 工具由远程服务器执行，不直接读写本项目；但查询文本会外发，禁止包含项目代码、路径、客户数据或秘密。
- **只读声明不等于强制**：Context7 两个工具带 `readOnlyHint=true`，但这是服务器自述；真正的权限边界仍由“不发送敏感数据 + 结果不推动状态”保证。

## 6. 验证边界

| 项 | 状态 | 证据 / 说明 |
|---|---|---|
| 在本 profile 中实际加载 `mcp-client` | **已完成** | 写入后热重载；server `context7` 与两个工具出现 |
| DSH Host 进程到 Context7 的实连 | **已完成** | `resolve-library-id` / `query-docs` 真实返回 |
| `query-docs` 的内容质量 | **已完成** | `/pydantic/pydantic/v2.11.0` 返回 v2.11.0 文档 |
| 限流边界与长时间重连 | **未测** | 未做压力测试；实际使用后按 `429` / 日志观察 |
| 断网 / 错 URL 负例 | **未测** | 需独立测试 profile，不在当前 profile 做破坏性测试 |
| TLS 代理 / 企业网络 | **未测** | 当前直连成功；换网络需复测 |

## 7. 相关文件

- [`00_mcp_source.log`](00_mcp_source.log)
- [`01_context7_probe.md`](01_context7_probe.md)
- [`02_config_diff_proposal.md`](02_config_diff_proposal.md)
- [`03_decision.md`](03_decision.md)
- [`08_apply_result.md`](08_apply_result.md)
- `docs/memory/environment.md` §6.3
