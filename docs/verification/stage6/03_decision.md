# 阶段 6 · 结论、边界与复评条件

> 日期：2026-11-08
> 范围：MCP Client 能力核实、Context7 接入、配置写入与真实调用验证。
> 状态：**PASS（能力核实 + 接入执行 + 真实调用）**；2026-11-08 12:33 写入并热重载生效。
> 本阶段不 commit、不建 `.venv`、不安装依赖。

## 1. 三态结论

| 项 | 状态 | 依据 |
|---|---|---|
| DSH 0.2.2-rc.1 是否支持 MCP Client | **PASS** | app.asar 内 `dsh-mcp-client@0.2.2-rc.1`，支持 `stdio` 与 `streamable-http` |
| 是否支持远程 MCP | **PASS** | `StreamableHTTPClientTransport` + `url`/`headers` 配置字段 |
| Context7 端点是否可用 | **PASS（匿名）** | `initialize` / `tools/list` / `tools/call` 均 200；返回真实库 ID |
| 是否需要第三方桥接 | **否** | 第一方 `mcp-client` 原生支持；未使用任何第三方 MCP 包 |
| Context7 是否已接入 Harness | **PASS** | 2026-11-08 12:33 写入；热重载后两个工具出现并调用成功 |
| 是否配置 API Key | **否** | 匿名调用成功；未读取凭据、未写入 Key |
| 是否判定 DEFERRED | **否** | 技术路径可用且已完成接入 |

## 2. 验证深度（不要合并表述）

| 层级 | 状态 | 证据 |
|---|---|---|
| 源码能力核实 | **已完成** | app.asar 内 `dsh-mcp-client@0.2.2-rc.1` 源码与配置 schema |
| Context7 端点协议 | **已实测** | 匿名 `initialize` / `tools/list` / `tools/call` 均 200 |
| DSH 实际加载 MCP 插件 | **已完成** | 热重载生效；当前会话出现 server `context7` 与两个工具 |
| DSH 内实际调用 MCP 工具 | **已完成** | `resolve-library-id` 与 `query-docs` 均返回真实结果 |
| 是否需要重启 | **不需要** | 写入后热重载，未结束进程、未启动替代服务 |

## 3. 为什么不是 DEFERRED

DEFERRED 的适用条件是“当前版本不支持远程 MCP”或“必须使用不受控第三方桥接”。本阶段两条都不成立：

1. 当前版本内置 `dsh-mcp-client@0.2.2-rc.1`，原生支持 `streamable-http`。
2. 接入只需在 profile patch 追加一个 `insert` 行，不安装包、不改基础 bundle、不扩权。
3. Context7 的匿名端点已实测返回真实结果，不需要 API Key 才能验证。

因此结论是 **PASS（能力 + 接入 + 真实调用）**，不是 DEFERRED。实际已获批准并完成写入与验证。

## 4. 已排除的方案

| 方案 | 排除原因 |
|---|---|
| 安装 `dsh-context7-mcp`、`dsh-mcp-adapter`、`dsh-plug-mcp` 等第三方包 | 不受控第三方桥接；增加供应链与权限风险；无必要 |
| 使用 `PyModel/dsh-research-plugins` 等外部 bundle | 非 DeepSeek 官方；不是本项目冻结依赖；不引入 |
| 直接调用 Context7 REST API 写自定义脚本 | 绕过 DSH 工具注册、权限与审计；形成第二套通道 |
| 修改 `dsh-base` bundle patch 或 app.asar | 改动随包安装内容；升级即丢失；不可回滚 |
| 用 `web_fetch` 抓 Context7 网页 | `web_fetch` 在阶段 2C 已禁用；且它与 MCP 是不同通道，不能互相替代 |
| 把 API Key 写入 `cordis.patch.yml` 或项目文件 | 违反凭据规则；本方案匿名即可运行 |
| 为“接入成功”放开网络/权限 | 违反阶段 6 约束；不扩大权限 |

## 5. 复评 / 转为 DEFERRED 的条件

出现以下任一情况，停止接入并重新评估，必要时转 DEFERRED：

1. Context7 取消匿名访问，且必须提供 API Key 才能完成 `initialize`；而用户不批准凭据配置。
2. 当前网络无法稳定访问 `https://mcp.context7.com/mcp`（TLS 失败、持续超时、代理不可用）。
3. 原生 `mcp-client` 在实际 profile 中无法加载（版本/服务依赖冲突），且修复需要改基础 bundle 或装依赖。
4. 实际使用中 Context7 返回内容无法与“不可信外部资料”隔离，或出现诱导性指令影响项目状态。
5. 用户决定不引入第三方文档服务。

## 6. 阶段 2C 非回归核对

| 配置 | 当前值 | 本阶段是否改动 |
|---|---|---|
| `web-fetch-http` | `disabled: true` | 否 |
| `session-telemetry-otel` | `mode: DISABLED` | 否 |
| `session-log-deepseek` | `enabled: false` | 否 |

`web_fetch` 不可用 **不等于** MCP 不可用：前者是网页抓取 provider，后者是独立的 MCP 客户端通道。本阶段没有用 `web_fetch` 探测，也没有因它失败而判定 MCP 不可用。

## 7. 已执行 / 未执行

已执行：

- 创建备份 `cordis.patch.yml.bak-20261108-stage6`，SHA256 `664C…FFD8`。
- 追加 9 行；1,462 字节 / 52 行 / SHA256 `6FF6…59E1`；前 1,200 字节与备份逐字节相同。
- 热重载生效；`mcp__context7__resolve-library-id` 与 `mcp__context7__query-docs` 出现。
- 真实查询：FastAPI `/websites/fastapi_tiangolo`；Pydantic `/pydantic/pydantic`（含 `v2.11.0`）；按 `v2.11.0` 查询成功。
- 2C 三项存在性核对：`web-fetch-http` disabled、telemetry DISABLED、session-log disabled。

未执行：

- 未配置 API Key；未读取 `.credentials.yaml`。
- 未重启 Harness；未新建替代服务；未结束进程。
- 未做断网/错 URL 负例（未另建测试 profile）。
- 未安装依赖、未创建 `.venv`、未运行 `pnpm install`。
- 未执行 `git add` / `git commit`；commit 数仍为 0。
- 未修改 `AGENTS.md`、九个 Skill、状态机、契约或业务代码。

## 8. 后续

1. 观察匿名额度；若出现 HTTP 429，报告证据，不擅自加 Key 或改配置。
2. 需要更高额度时，由用户在 Harness 正式凭据界面输入 Key，再单独审批 headers 引用方式。
3. 故障注入（断网、错 URL、`failOnStartupError` 行为）留到测试阶段，用独立 profile 做，不在当前 profile 破坏性测试。
4. 备份文件保留到阶段验收后，再由用户决定是否删除。
