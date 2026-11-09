# Git 基线只读报告（首提前）

> 性质：**只读调查，无任何写配置、无 `git add`、无 commit**。
> 日期：2026-11-09（Asia/Shanghai）。
> 目的：在用户提供 Git 身份前，把“将会发生什么”说清楚：身份状态、`.gitignore` 影响、首提文件清单、DOCX 处置。

## 1. 身份状态

| 项 | 只读结果 |
|---|---|
| Git 版本 | `git version 2.46.0.windows.1` |
| 分支 | `main` |
| 提交数 | `git rev-list --count --all` = **0** |
| `user.name` | **未配置**（`git config --global --get user.name` 无输出） |
| `user.email` | **未配置**（同上） |
| 仓库级身份 | 未配置 |
| 全局配置文件 | `C:\Users\Administrator\.gitconfig` 存在，但不含 `user.name` / `user.email` |

结论：当前无法创建带身份确认的提交（`BLK-001` 仍 `OPEN`）。**等你提供身份后**，由你决定写全局还是仓库级配置；本轮不做任何设置。

## 2. `.gitignore` 对契约与证据的影响

对以下路径逐条执行 `git check-ignore -v`：

| 路径 | 结果 |
|---|---|
| `contracts/taskspec.schema.json` | **不被忽略** |
| `contracts/examples/taskspec.negative.1.json` | **不被忽略** |
| `contracts/examples/manifest.json` | **不被忽略** |
| `docs/verification/g0/02_validate_contracts.log` | **不被忽略** |
| `docs/verification/stage7/14_link_check.log` | **不被忽略** |
| `docs/verification/stage7/SUPERSEDED_NOTICE.md` | **不被忽略** |
| `docs/state/project_state.json` | **不被忽略** |
| `scripts/validate_contracts.py` | **不被忽略** |
| `tmp/stage6_asar/dsh__package.json` | 被忽略（`.gitignore:52 /tmp/`） |

原因：`/*.log` 只匹配**仓库根目录**的 `.log`，不匹配 `docs/verification/**`；`/tmp/` 只忽略根目录 `tmp/`。因此 **`contracts/*.json` 与 `docs/verification/**` 都会被正常纳入**，不会被误伤。

`.gitattributes` 已把 `*.py` / `*.md` / `*.json` / `*.yml` / `*.yaml` 固定为 LF，`*.docx` 标为 binary；本轮新增文件已验证全部 LF、无 BOM。

## 3. 首次提交文件清单

完整清单见 [`06_first_commit_filelist.txt`](06_first_commit_filelist.txt)，一行一个路径，按 `git -c core.quotepath=false status --porcelain --untracked-files=all` 生成，**已排除 DOCX**。

| 计数 | 值 |
|---|---|
| 当前未跟踪总数（含 DOCX） | **283** |
| 排除的 DOCX | **1**（根目录策划书原件） |
| 待你确认的首提候选 | **282** |
| 其中 `docs/` | 173 |
| 其中 `contracts/` | 80（5 schema + 72 例 + manifest + README + .gitkeep） |
| 其中 `.agents/` | 18（9 个 Skill 的 `SKILL.md` 与 references） |
| 其中 `scripts/` | 4 |
| 其中 `tests/` | 2 |
| 根目录文件 | 4（`.gitignore`、`.gitattributes`、`AGENTS.md`、`README.md`） |
| `researchflow/` | 1（`.gitkeep`） |

清单特点：

- 含 `contracts/`（5 schema + 72 例 + manifest + README）、`scripts/`、`docs/`（含 `docs/verification/**` 全部历史证据与 `docs/ADR/`）、`.agents/skills/`、`tests/`、根目录文件。
- **不含** `tmp/`（被忽略）、`.venv/`（不存在）、DOCX（已从清单排除，见 §4）。
- 不含任何密钥、Session、`.env`。
- 清单自身与 [`05_git_baseline_report.md`](05_git_baseline_report.md) 都在 282 之内（自包含）。

## 4. DOCX 处置（不纳入版本控制）

现状：

- 根目录 `ResearchFlow_3.1_项目策划书_v4.3.1_完整开发版.docx`（111,209 字节，SHA256 `9E54168F…CCB3A`）**未被跟踪，也未被忽略**。
- 因此 `git add .` / `git add -A` **会把它加入暂存区**；必须显式排除。
- `git status` 会一直显示它（未跟踪），便于提醒。

三个选项（**由你决定，本轮不改**）：

| 选项 | 做法 | 后果 |
|---|---|---|
| A（默认现状） | 不改 `.gitignore`，首提用显式路径或 `git add . ':(exclude)*.docx'` | DOCX 保持未跟踪；每次批量 add 都要记得排除，存在误加风险 |
| B | 在 `.gitignore` 加**精确文件名**（含中文文件名） | `git status` 不再显示；误加风险最低；但忽略规则含中文长路径，可读性一般 |
| C | 在 `.gitignore` 加 `*.docx` | 最简单；但会连带忽略未来可能合法入库的小 docx 产物（如导出的验收报告），与 `.gitattributes` 的 `*.docx binary` 意图不完全一致 |

建议 B：只忽略这一份原件，不扩展到所有 docx；同时保留“禁止第二份副本”的规则。

## 5. 提交前还需要你确认

1. Git 身份：`user.name` / `user.email` 的具体值，以及写全局还是仓库级。
2. `git add` 范围：按 06 清单全量，还是排除某些历史证据目录。
3. 首提提交信息（中文/英文、是否带阶段号）。
4. DOCX 选 A/B/C。
5. 是否接受“首提前不建 `.venv`、不装依赖”的现状（当前 `contracts/` 与文档无需安装即可校验）。

提交后我会执行的校验（需你批准后才做）：`git rev-parse HEAD`、`git status --porcelain` 为空、`git ls-files` 计数与 06 清单一致、确认 DOCX 未被跟踪。