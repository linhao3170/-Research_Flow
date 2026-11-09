# 阶段 6 · Context7 远程 MCP 端点只读探测

> 探测时间：2026-11-08 12:08–12:12（Asia/Shanghai）
> 端点：`https://mcp.context7.com/mcp`
> 方式：本机 Python 3.11.16 标准库 + 内置 Node 24 交叉验证；**未使用任何 API Key**
> 结论：端点可达，匿名 `initialize` / `tools/list` / `tools/call` 均返回真实结果；接入方案不需要 API Key 即可运行。
> 后续：2026-11-08 12:33 已写入 profile 并热重载；DSH 工具调用结果见 [`08_apply_result.md`](08_apply_result.md)。

## 1. 探测方法

| 项 | 值 |
|---|---|
| 脚本 | `docs/verification/stage6/context7_probe.py`（仅标准库，无依赖） |
| 解释器 | `C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe` |
| 命令 | `& $py docs/verification/stage6/context7_probe.py` |
| 输出日志 | `docs/verification/stage6/01_context7_probe.log` |
| 发送内容 | `initialize`、`tools/list`、`tools/call(resolve-library-id, libraryName=FastAPI)` |
| 未发送 | 项目代码、文件路径、仓库名、凭据、Cookie、API Key、个人数据 |
| 凭据头 | 无（脚本明确打印 `credential_header_present=false`） |

补充探测：对端点发 `HEAD` 得到 HTTP 405，响应头 `access-control-allow-headers` 列出
`X-Context7-API-Key`、`Context7-API-Key`、`X-API-Key`、`Authorization`。这只说明服务端接受这些头名，不证明本机已配置任何密钥。

## 2. 实际结果（来自日志）

| 阶段 | 结果 |
|---|---|
| `initialize` | HTTP 200；协议 `2025-06-18`；server `Context7`，版本 `4.5.0` |
| capabilities | `prompts`、`resources`、`tools` |
| instructions | 703 字符；描述“获取最新库文档”的用途与边界 |
| `tools/list` | HTTP 200；2 个工具 |
| `tools/call` | HTTP 200；`isError=false`；1 个文本块；1716 字符；首行 `Available Libraries:` |
| 探测结论 | `PROBE_RESULT=PASS`，exit 0 |

日志原文：

```text
probe_time_utc=2026-11-08T04:12:24+00:00
endpoint=https://mcp.context7.com/mcp
credential_header_present=false
initialize_http_status=200
negotiated_protocol=2025-06-18
server_name=Context7
server_version=4.5.0
capabilities=prompts,resources,tools
instructions_chars=703
tools_list_http_status=200
tool_count=2
tool=resolve-library-id readOnlyHint=True required=query,libraryName
tool=query-docs readOnlyHint=True required=libraryId,query
tool_call_http_status=200
tool_call_is_error=False
tool_call_content_blocks=1
tool_call_text_chars=1716
tool_call_first_line=Available Libraries:
PROBE_RESULT=PASS
```

## 3. 工具清单

| 工具 | 必填参数 | 用途 | `readOnlyHint` |
|---|---|---|---|
| `resolve-library-id` | `query`、`libraryName` | 把包/产品名解析为 Context7 库 ID | `true` |
| `query-docs` | `libraryId`、`query` | 按库 ID 检索最新文档与代码示例 | `true` |

实际返回示例：`FastAPI` 解析出 `/websites/fastapi_tiangolo`（4326 个代码片段，High 声誉）等候选。该结果只用于证明端点真实可用，不作为 ResearchFlow 技术选型依据。

## 4. 认证与配额

| 项 | 事实 | 来源 |
|---|---|---|
| 匿名访问 | 可用；`initialize`、`tools/list`、`tools/call` 均返回 200 | 本机实测日志 |
| 匿名限制 | “Without API key: Low rate limits and no custom configuration” | Context7 官方 API 指南（外部资料） |
| 带 Key 限制 | 按套餐提高；免费账户每月 1,000 次调用，用尽后停止至下月 | Context7 Plans & Pricing（外部资料） |
| 本机 API Key 状态 | **未配置**；未读取 `.credentials.yaml`，未在文件中写入任何 Key | 本阶段约束与配置快照 |
| 本方案是否需要 Key | **不需要**；先按匿名额度运行，额度不足时再单独评估 | 本阶段判断 |

外部资料（访问日期 2026-11-08，默认不是项目证据）：

- [Context7 API Guide](https://github.com/upstash/context7/blob/23843e9c/docs/api-guide.mdx)
- [Context7 Plans & Pricing](https://github.com/upstash/context7/blob/bfe89ea8/docs/plans-pricing.mdx)
- [Context7 官网定价页](https://context7.com/plans)

## 5. 未验证 / 待核实

1. **已在 DSH 中实际加载并调用**——2026-11-08 12:33 写入后热重载，两个工具出现；`resolve-library-id` 与 `query-docs` 均成功，详见 `08_apply_result.md`。本文件仅记录写入前的端点探测。
2. **未测匿名额度的具体数值**——官方只说“低限额”，未给出确切上限；实际使用后以 `429` 与 `RateLimit-*` 响应头为准。
3. **`query-docs` 已在接入后验证**——用 `/pydantic/pydantic/v2.11.0` 返回 v2.11.0 文档；但未做长文档/多并发压力测试。
4. **未测企业代理/TLS 中间盒**——当前直连成功；换网络需复测。
5. **未测长时间断线重连**——客户端默认 500 ms–30 s、10 次；未做故障注入。

## 6. 相关文件

- [`context7_probe.py`](context7_probe.py)
- [`01_context7_probe.log`](01_context7_probe.log)
- [`00_mcp_capability.md`](00_mcp_capability.md)
- [`02_config_diff_proposal.md`](02_config_diff_proposal.md)
