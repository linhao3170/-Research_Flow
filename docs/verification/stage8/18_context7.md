# 18 Context7 MCP 最小真实调用

- 时间：2026-11-08 13:15（Asia/Shanghai）
- MCP server：`context7`（`https://mcp.context7.com/mcp`，匿名额度；未配置 API Key）
- 调用 1：`mcp__context7__resolve-library-id`
  - 参数：`libraryName=Pydantic`，`query=pydantic v2 BaseModel required string field`
  - 结果：返回 `/pydantic/pydantic`（Source Reputation: High，Benchmark 75.28；版本列表含 v2.11.0 等）
- 调用 2：`mcp__context7__query-docs`
  - 参数：`libraryId=/pydantic/pydantic`，`query=How to define a BaseModel with a required string field in Pydantic v2`，`language=Python`
  - 结果：返回 Pydantic V2 必填/可选字段说明与 `BaseModel` 示例，来源为 GitHub `pydantic/pydantic` 文档；内容与查询匹配。
- 网络：仅访问 Context7 MCP 端点与模型后端；未发送项目代码、路径、文件内容、数据集或秘密。
- 凭据：未读取、未回显任何 API Key 或 Token。
- 结论：Context7 MCP 已接入且可真实调用；本次只用于公开库文档查询，不作为 ResearchFlow 证据或验收结论。
