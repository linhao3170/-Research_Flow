---
name: researchflow-evidence-security
description: Use when handling evidence levels, Collector, Gate, Verifier, L1/L2/L3, signatures, Evidence Bundle, permissions, secrets, or trust boundaries.
---

# ResearchFlow Evidence and Security

## 1. 适用条件 / When to use

在以下情况使用：

- 设计或审查 E0–E3 证据、Collector、Gate、Verifier、Evidence Bundle。
- 判断某条证据能否推动状态、能否满足必检项。
- 设计 L1/L2/L3 验证、签名、哈希链、离线验签、权限边界。
- 处理证据纠错、事件顺序、证据包导出、敏感数据最小化。
- 需要写伪造、缺失、篡改、越权写入的负例测试。

不用于：用 Agent 声明替代执行观测；把哈希链说成绝对不可篡改。

## 2. 输入与前置检查

1. 已确认证据等级定义：E0 Agent/LLM 声明；E1 工具调用/Harness 轨迹；E2 受控 Executor 真实观测；E3 独立 Verifier 验证证据。
2. 已确认生产者、写入者、消费者和信任边界。
3. 已确认必检项 `RequiredChecks`、规则版本、Gate 顺序。
4. 已确认 Verifier 与 Executor 在进程和工作目录上分离。
5. 已确认签名算法、规范化方法、密钥管理、外部信任锚。
6. 已确认数据分级与脱敏要求；敏感资料不得进入日志或证据包。

若证据等级、信任锚或规则版本未定义，先补规格，不实现“先相信再验证”的流程。

## 3. 执行步骤

1. **画信任边界**：Agent、Harness、Tool Gateway、Executor、Collector、Gate、Verifier、Evidence Store、外部验签者。
2. **定义证据记录**：`evidence_id`、等级、生产者、时间、`event_seq`、关联任务/节点/attempt、哈希、来源、原始观测。
3. **实现单写者**：Collector 追加 E0/E1/E2；`event_seq` 单调分配；纠错追加新事件，不原位覆盖。
4. **实现 Gate**：只读结构化证据和规则；逐项生成 coverage row；缺必检证据、哈希不符、规则版本不符、冲突未解释时不得 PASS。
5. **实现 Verifier**：独立进程/工作目录；L1/L2/L3 分层；L3 在新目录、独立进程从原始数据真实重训/推理。
6. **签发凭证**：只有报告 VERIFIED、必检证据完整、签名/信任锚有效、规定 L3 覆盖满足，才签发 CompletionCertificate。
7. **实现离线验签**：`verify_bundle.py` 独立于数据库和模型；使用外部可信指纹/信任锚；校验签名、哈希链、规则版本、证据根。
8. **实现密码学**：Ed25519、JCS、Merkle 按标准实现；不自创算法、编码或签名流程。
9. **限制权限**：Agent 无数据库写权限、证据写权限、私钥；Verifier 不复用 Executor 进程内状态。
10. **最小化数据**：公开/合成数据优先；敏感资料先脱敏；只保留必要字段和保留期。
11. **写负例测试**：伪造 E0/E1 推动 VERIFIED、缺失必检、篡改哈希、越权写入、复用 Executor 状态、错误信任锚。
12. **记录边界声明**：哈希链只称“可发现篡改”；k 次 bit-exact 只称限定条件下的经验资格。

## 4. 不可违反的约束

- E0/E1 不得单独满足执行类必检项；Harness 轨迹默认 E1，不能冒充 E2。
- E2 必须来自真实受控执行观测；不得用日志摘要或模型自述替代。
- Collector 是 E0/E1/E2 的受控记录者；单写者、追加式、`event_seq` 单调。
- Gate 只读取结构化证据和规则；缺少必检证据不得 PASS。
- Verifier 必须与 Executor 在进程和工作目录上分离。
- L3 必须在新目录、独立进程中真实重训/推理；不得用缓存、摘要或模型自述替代。
- 只有 VERIFIED 才能签发 CompletionCertificate。
- `verify_bundle.py` 必须独立于数据库和模型；离线验签使用外部可信指纹。
- 不得自创密码算法；不得把哈希链表述为绝对不可篡改。
- 不向 Agent 暴露数据库写权限、证据写权限和私钥。
- 不得省略数据最小化与脱敏；不得把敏感资料写入证据包。

## 5. 输出要求

至少交付：

1. **信任边界图**：参与方、权限、数据流。
2. **权限矩阵**：Agent/Executor/Collector/Gate/Verifier/验签者的读、写、签、验权限。
3. **证据流**：E0–E3 产生、记录、消费、验证路径。
4. **Gate 规则**：必检项、覆盖矩阵、PASS/GAP 条件。
5. **威胁分析**：伪造、篡改、重放、越权、信任锚替换、数据泄漏。
6. **负例测试**：每类攻击至少一个可执行测试及预期拒绝结果。
7. **边界声明**：哈希链、k 次 bit-exact、外部信任锚的适用边界。

## 6. 验收标准

- E0/E1 不能推动 VERIFIED；有测试证明。
- 缺失必检证据时 Gate 不 PASS；有测试。
- 篡改证据或哈希链可被发现；有测试和真实 diff。
- 伪造、越权写入、复用 Executor 状态被拒绝。
- L3 在新目录、独立进程真实执行；有过程证据。
- 只有 VERIFIED + 完整证据 + 有效签名才签发证书。
- 离线验签不依赖数据库、模型或证据包自带公钥。
- 没有秘密泄漏；敏感数据已脱敏或未收集。

## 7. 相关文件 / 参考资料

- `AGENTS.md`
- `docs/memory/architecture-decisions.md`
- `docs/state/runtime_states.md`
- 策划书 v4.3.1 第 3、5、17 章及附录 D、F
- `references/evidence-trust-boundaries.md`

## 8. 失败与暂停条件

- 证据等级、生产者或写入者定义冲突。
- 需要 Agent 获得证据/凭证/私钥写权限。
- Gate 规则或必检项未定义，无法判定 PASS/GAP。
- Verifier 无法与 Executor 分离（同进程/同目录/共享可变状态）。
- L3 只能复用缓存或摘要，无法真实重跑。
- 签名/信任锚/密钥管理方案未批准，或要求自创算法。
- 发现已签发证书缺少 VERIFIED 报告或完整证据。

暂停时报告：受影响证据/证书、信任边界缺口、已存在的风险、需要用户批准的修复方案。
