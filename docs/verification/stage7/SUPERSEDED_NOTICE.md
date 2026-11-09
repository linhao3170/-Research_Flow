# SUPERSEDED NOTICE — `14_link_check.log`

> 性质：**追加式事实登记**，不是新的“正确值”，不修改阶段 7 报告与 `16_final_inventory.log` 中的原始记录。
> 日期：2026-11-09（Asia/Shanghai）。
> 关联：`docs/verification/stage7/STAGE7_REPORT.md`（记 232 links）、`docs/verification/stage7/16_final_inventory.log`（记原文件 106 字节 / SHA256 `B9FDD0AB…`）。

## 1. 事实

| 项 | 原始记录（阶段 7） | 当前文件（2026-11-09 被覆盖后） |
|---|---|---|
| 文件 | `docs/verification/stage7/14_link_check.log` | 同左 |
| 相对链接数 | 232 | 239 |
| 断链 | 0 | 0 |
| 结果 | `RESULT=PASS` | `RESULT=PASS` |
| 字节数 | 106 | 106 |
| SHA256 | `B9FDD0ABE3BEAF0BECCA092C0B2E861D0A756EE9EA25D91970606F4ACCE54768` | `A3ECADA1042A2780F7AC8E4BC3470B6F9CEB165D4B5304061CC43F534EF60965` |

两份记录**同时有效**：232 是阶段 7 收尾时的真实结果；239 是 2026-11-09 重跑时的真实结果。二者差异来自两次运行之间被检查文件集合的链接变化，不代表任何一次运行失败。

## 2. 覆盖原因

2026-11-09 执行 G0 文档链接检查时，直接运行了 `docs/verification/stage7/check_links.py`，**未先确认该脚本的 `OUT` 常量**。该脚本按设计把结果写回自身目录下的 `14_link_check.log`，因此覆盖了阶段 7 的证据日志。

这是操作失误，不是脚本缺陷：脚本“写回固定路径”的行为在阶段 7 是刻意设计，但在证据已归档后再次运行就会覆盖历史。

## 3. 为什么无法恢复

- 仓库当时 `git rev-list --count --all` = 0，无任何提交，无法从版本库取回原字节。
- 项目内无该日志的备份副本。
- 已按脚本输出格式尝试重建 232 版本（106 字节），SHA256 与 `16_final_inventory.log` 记录不符，说明归档时的文件内容与该脚本当前输出格式并不完全一致；因此**没有**把重建结果写回，避免制造第二份不可信“原件”。

## 4. 后续处置（已生效）

1. **不再运行** `docs/verification/stage7/check_links.py`；该脚本保留原样，作为阶段 7 证据的一部分。
2. 新增只读检查脚本 [`docs/verification/g0/check_links_g0.py`](../g0/check_links_g0.py)：不写任何文件，结果只输出到 stdout，由调用方显式重定向。
3. 规则写入 ⑧ 风险表与 G0 冻结前检查清单：**证据日志只追加；脚本输出路径必须显式参数化，禁止默认覆盖既有日志**。
4. 阶段 7 报告中的“232 个相对链接”**保持不动**；本通知只解释现状，不改写历史结论。

## 5. 影响评估

- 不影响阶段 7 的结论（当时 0 断链、PASS）；也不影响当前 G0 文档的链接状态（本次改动的 5 份文档另行只读检查：43 links / 0 broken）。
- 影响的是“证据日志可否被证明未被改动”这一属性：在建立 Git 基线之前，任何写回固定路径的脚本都可能再次造成同类问题。
- 该风险已在 `docs/G0/08_OPEN_QUESTIONS_AND_FREEZE.md` §3 风险表登记。

---

**标记：本文件只追加，不替代任何原始证据。** 不改 `STAGE7_REPORT.md`，不改 `16_final_inventory.log`，不改 `14_link_check.log` 的现状。