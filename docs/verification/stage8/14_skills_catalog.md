# 14 九个项目级 Skill 的发现证据

当前会话的 model-facing catalog（系统提示 `available_skills`）包含以下 9 个项目级 Skill：

1. `researchflow-contracts-api`
2. `researchflow-dag-state-machine`
3. `researchflow-evidence-security`
4. `researchflow-memory-handoff`
5. `researchflow-onboarding`
6. `researchflow-prompt-workflow`
7. `researchflow-python-backend`
8. `researchflow-spec-driven-development`
9. `researchflow-testing-benchmark`

文件系统核对：

- `.agents/skills/` 目录数：9
- `SKILL.md` 数：9
- 名称与 catalog 一致
- 未在 `.dsh/skills`、`~/.dsh/skills`、`~/.agents/skills` 创建同名 Skill

证据：`14_skills_catalog.log`、当前会话系统提示的 `available_skills` 列表、`docs/SKILL_CATALOG.md` §3。

> “已发现”只表示出现在 catalog；不等同于“已加载”或“已执行验证”。本阶段加载情况见 `15_skills_on_demand.md`，无副作用调用见 `16_skill_no_side_effect.log`。
