# 20 Git 可审查与可回滚

> 2026-11-10 补测更新：G0 基线 `91bde66` 已建立，本文件新增 §3 受控回滚实测；第 20 项最终判定改为 **PASS（基线建立后补测）**。
> §1 保留 2026-11-08 初验的原始记录，不改写为「当时已通过」。

## 1. 初验实测事实（2026-11-08）

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
| 可回滚 | **PASS（2026-11-10 补测）** | 基线 `91bde66` 上完成探针写入、diff 核对、`git checkout --` 恢复；见 §3 |
| 是否创建基线 commit | 已创建 | `chore(g0): 建立 G0 规格基线`，HEAD `91bde66` |

## 2. 初验建议（历史）

1. 用户确认 Git `user.name` / `user.email`。
2. 用户批准后创建基线 commit（必须排除 DOCX，见 `SOURCE_REGISTER` 的 Git 跟踪规则）。
3. 在基线 commit 上再做一次受控回滚测试，才能把“可回滚”改为 PASS。

> 不得把“工作区可查看”写成“回滚已实测”。

## 3. 补测实测（2026-11-10）

| 项 | 结果 |
|---|---|
| 基线 | `91bde66365f24726003212c4b4f218da23148c1d` |
| 探针文件 | `docs/CHANGELOG_DEV.md` |
| 探针行 | `PROBE-G0-ROLLBACK-20261110` |
| 写入前 blob / `HEAD` blob | `051d7616947cfcad59ae6d0f2b1d9b1aaf1e75a4` / 同一值 |
| 写入后 `git status` | `M docs/CHANGELOG_DEV.md` |
| `git diff` | 可见 `+PROBE-G0-ROLLBACK-20261110` |
| `git checkout -- docs/CHANGELOG_DEV.md` | exit 0 |
| 恢复后 blob | `051d7616947cfcad59ae6d0f2b1d9b1aaf1e75a4`（等于 `HEAD`） |
| 恢复后 SHA256 | `070CF8F2B8D9B205FCB39322B56ADB098C98D6531DA8640C2D2CEDB979CCAB81`（等于写入前） |
| 探针残留 | 无 |
| 文件级 `git status` | 空 |

完整命令、退出码与前后哈希见 [`docs/verification/g0/18_git_rollback.log`](../g0/18_git_rollback.log)。

**判定：第 20 项 PASS（基线建立后补测）。**
