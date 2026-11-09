# 20 Git 可审查与可回滚

## 实测事实

- 分支：`main`。
- commit 数：`0`（`git rev-list --count --all` = 0）。
- 已跟踪文件：`0`（`git ls-files` 为空）。
- `git log -5 --oneline`：exit 128，`fatal: your current branch 'main' does not have any commits yet`。
- `git status --porcelain=v1`：11 行，全部为未跟踪路径（`.agents/`、`AGENTS.md`、`docs/`、DOCX 等）。
- `git diff --cached --stat`：空。
- 未执行 `git add` / `git commit`；`last_verified_commit` 仍为 `null`。

## 判定

| 子项 | 结果 | 说明 |
|---|---|---|
| 当前工作区可审查 | PASS | `git status` 能列出全部未跟踪文件；但无基线 diff |
| 可回滚 | **NOT VERIFIED** | 没有初始 commit，无法实测 `git checkout` / `git restore` 回滚 |
| 是否创建基线 commit | 未创建 | 需用户批准并确认 Git 身份（`BLK-001`） |

## 建议

1. 用户确认 Git `user.name` / `user.email`。
2. 用户批准后创建基线 commit（必须排除 DOCX，见 `SOURCE_REGISTER` 的 Git 跟踪规则）。
3. 在基线 commit 上再做一次受控回滚测试，才能把“可回滚”改为 PASS。

> 不得把“工作区可查看”写成“回滚已实测”。
