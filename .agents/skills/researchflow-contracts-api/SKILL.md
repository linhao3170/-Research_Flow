---
name: researchflow-contracts-api
description: Use when designing, reviewing, versioning, or testing ResearchFlow data contracts, JSON Schema, Pydantic models, REST APIs, error codes, or idempotency behavior.
---

# ResearchFlow Contracts and API

## 1. 适用条件 / When to use

在以下情况使用：

- 设计或评审 TaskSpec、NodeSpec、EvidenceRecord、VerificationReport、CompletionCertificate、HarnessEvent、DomainPack。
- 同步 JSON Schema 与 Pydantic v2 模型。
- 设计或修改 REST API、请求/响应、HTTP 状态码、错误码、幂等规则。
- 判断契约变更是否兼容，是否需要迁移或版本升级。
- 为契约准备合法、非法和边界样例。

不用于：在 G0 冻结前宣称契约已最终确定；用自然语言声明替代结构化证据。

## 2. 输入与前置检查

1. 当前契约状态已核实：`contracts/` 是否已有文件、版本、冻结标记。
2. 变更来源明确：用户指令、PRD、ADR、策划书章节。当前详细 Schema **尚未冻结**，不得把推测字段写成正式契约。
3. 已识别消费者：StateMachine、Executor、Collector、Gate、Verifier、API、前端、证据包工具。
4. 已确认兼容策略：新增可选字段、枚举扩展、版本号、迁移脚本、旧数据读取。
5. 已确认安全边界：Agent 不得直接写 Evidence、Report、Certificate 或私钥。

若契约尚未冻结且用户要求“直接实现”，先给出建议稿并标明“待 G0 批准”，不冒充冻结契约。

## 3. 执行步骤

1. **列出实体与关系**：七个核心实体各自的职责、生产者、消费者、生命周期。
2. **定义字段**：名称、类型、必填/可选、默认值、枚举、格式、约束、单位、版本。未知字段标“待核实”，不填猜测值。
3. **定义不变量**：跨字段约束、状态与证据的一致性、时间/顺序、哈希与签名覆盖范围。
4. **同步 Schema 与模型**：JSON Schema 与 Pydantic v2 模型逐字段对照；生成或手写都必须有差异检查。
5. **定义 API**：方法、路径、请求、响应、HTTP 状态码、业务错误码、幂等键、重试语义、分页/过滤。
6. **做兼容性分析**：新增/删除/改义/改类型/改枚举的影响；旧数据是否可读；消费者是否需要同步升级。
7. **准备样例**：每个契约至少一个合法样例、一个非法样例、一个边界样例；非法样例要有预期错误码。
8. **写测试**：Schema 校验、模型校验、API 契约、错误码、幂等、版本迁移。
9. **更新契约索引**：记录版本、状态、变更摘要、审批状态、测试证据。索引模板见 `references/contract-index.md`。
10. **冻结检查**：只有用户批准、测试通过、迁移说明齐全时，才可标记 `FROZEN`。

## 4. 不可违反的约束

- Schema 一旦冻结，不得静默改变字段含义；变更必须版本化并写迁移说明。
- JSON Schema 与 Pydantic v2 模型必须一致；不得只改一边。
- 不得把 Agent 的自然语言声明设计成可信完成证据。
- 不得让 Agent 直接写 Evidence Store、VerificationReport、CompletionCertificate 或私钥。
- 错误码必须稳定；不得用同一错误码表示不同语义。
- 不得删除旧字段而不提供迁移/弃用周期。
- 不得用 `additionalProperties: true` 掩盖未定义字段，除非有明确兼容理由并记录。
- 不得在样例中伪造真实实验数据；样例必须标注 synthetic/example。
- 不得在 G0 前把建议稿写成“已冻结”。

## 5. 输出要求

至少交付：

1. **契约说明**：实体、字段表、必填/可选、枚举、约束、不变量。
2. **Schema/Pydantic 变更**：文件清单、diff 摘要、同步检查结果。
3. **API 说明**：请求/响应、状态码、错误码、幂等规则。
4. **兼容性分析**：影响消费者、旧数据、迁移、回滚。
5. **样例与测试**：合法、非法、边界样例及预期结果。
6. **版本与状态**：`DRAFT` / `PROPOSED` / `FROZEN` / `DEPRECATED`，以及批准记录。

## 6. 验收标准

- Schema 与 Pydantic 模型字段、类型、必填性、枚举一致。
- 每个必填字段有明确语义和来源；没有“待定但写成必填”的字段。
- 非法样例能被拒绝，错误码稳定且可区分。
- API 幂等行为有测试；重复请求不会产生重复副作用。
- 版本变化有迁移说明；旧数据兼容性有结论。
- Agent 声明没有被当作完成证据。
- 未冻结契约明确标注，不被下游当成稳定接口。

## 7. 相关文件 / 参考资料

- `AGENTS.md`
- `docs/memory/architecture-decisions.md`
- `docs/state/runtime_states.md`
- `contracts/`（当前可能为空，使用前先核实）
- 策划书 v4.3.1 附录 D、附录 E、附录 F
- `references/contract-index.md`

## 8. 失败与暂停条件

- 契约状态不明确（草案/冻结/废弃）却要求改字段含义。
- 字段来源无法追溯到用户指令、PRD、ADR 或策划书章节。
- JSON Schema 与 Pydantic 模型无法同步，或生成工具缺失。
- 变更会破坏已有消费者且没有迁移方案。
- 错误码、状态码或幂等语义存在冲突。
- 需要让 Agent 获得证据/凭证/私钥写权限。

暂停时输出：冲突字段、受影响消费者、兼容性风险、需要批准的最小变更集。
