# 15 Skills 按需加载

- 会话 catalog 只包含 Skill 名称与 description，不包含正文；正文仅在调用 `skill` 工具时返回。
- 本阶段实际加载的 ResearchFlow Skill（6/9）：
  1. `researchflow-onboarding`
  2. `researchflow-memory-handoff`
  3. `researchflow-testing-benchmark`
  4. `researchflow-evidence-security`
  5. `researchflow-contracts-api`
  6. `researchflow-dag-state-machine`
- 本阶段未加载（3/9）：`researchflow-prompt-workflow`、`researchflow-python-backend`、`researchflow-spec-driven-development`。
- 三次新增加载（evidence-security、contracts-api、dag-state-machine）前后，项目 167 个文件的内容聚合 SHA256 完全一致（`22d26124…c972`），证明加载本身无文件副作用；见 `16_skill_no_side_effect.log`。
- 未在 `AGENTS.md` 或每轮系统提示中注入九个 Skill 全文；catalog 仅有摘要。

判定：PASS（按需加载，未每轮注入全部正文）。
