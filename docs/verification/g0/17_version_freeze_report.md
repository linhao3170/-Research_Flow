# G0 规格基线升版与冻结报告（v1.0）

> 日期：2026-11-10（Asia/Shanghai）。
> 性质：本轮升版、校验、Git 身份与 DOCX 忽略处置的**真实结果记录**；**不是 G0 门禁 PASS**。G0 是否 PASS 由用户宣布。
> 范围：①–⑧ 八份 G0 文档、⑨ `contracts/`、依赖矩阵、`ADR-007`、`project_state.json`、首次 G0 基线提交。

## 1. 本轮指令落地

| 指令 | 落地 | 结果 |
|---|---|---|
| Git 身份仅本仓库 | `git config --local user.name/user.email` | 完成，见 §2 |
| DOCX 选 B（精确文件名） | `.gitignore` 精确规则 + `git check-ignore -v` | 完成，见 §3 |
| 三组枚举按现值冻结 | 05 §1.6、⑧ §5.1/§6.1、schema 注记 | 完成，见 §4 |
| 依赖矩阵为 WP-01 基线 | ⑦ `WP-01` 入口条件 + 矩阵冻结标记 | 完成，见 §5 |
| ADR-007 延后 | 保持 `PROPOSED`，`WP-13` 前裁决 | 完成，见 §6 |
| ①–⑧/⑨ 升 v1.0 | 各文档头 + 版本记录 | 完成，见 §7 |
| 重跑校验 | 6 类命令、真实退出码 | 完成，见 §8 |

## 2. Git 身份（仅仓库级）

命令与结果：

```text
git config --local user.name  "ResearchFlow Dev"
git config --local user.email "dev@researchflow.local"

git config --local --get user.name   → ResearchFlow Dev
git config --local --get user.email  → dev@researchflow.local
git config --global --get user.name  → （空）
git config --global --get user.email → （空）
git config --local --show-origin --get-regexp '^user\.'
  file:.git/config  user.name  ResearchFlow Dev
  file:.git/config  user.email dev@researchflow.local
```

未使用 `--global`，未修改 `C:\Users\Administrator\.gitconfig`。`BLK-001` 据此置 `RESOLVED`。

## 3. DOCX 精确忽略（选 B）

`.gitignore` 新增规则（不扩展到 `*.docx`）：

```text
/ResearchFlow_3.1_项目策划书_v4.3.1_完整开发版.docx
```

验证：

```text
git check-ignore -v -- "ResearchFlow_3.1_项目策划书_v4.3.1_完整开发版.docx"
  .gitignore:61:/ResearchFlow_3.1_项目策划书_v4.3.1_完整开发版.docx
  → exit 0（被精确规则忽略）

git check-ignore -v --no-index -- "docs/notes/another.docx"  → exit 1（未被忽略）
git check-ignore -v --no-index -- "docs/verification/sample_export.docx" → exit 1（未被忽略）
```

DOCX 原文件未修改、未改名、未移动；`git status` 不再显示该文件。仓库内当前只有这一份 `.docx`，因此“其他 docx 不受影响”用不存在路径的 `--no-index` 规则匹配验证。

## 4. 三组枚举冻结（v1.0 现值）

| 枚举 | 数量 | 冻结值 | 变更规则 |
|---|---|---|---|
| `EvidenceRecord.kind` | 7 | `agent_claim`、`tool_invocation`、`harness_trace`、`executor_launch`、`executor_process_exit`、`artifact_observed`、`verifier_recheck` | 新增成员 `MINOR`；删除/改语义 `MAJOR` |
| `l1_status` / `l2_status` / `l3_status` | 4 | `PASS`、`FAIL`、`SKIP`、`NOT_RUN` | 新增成员 `MINOR`；删除/改语义 `MAJOR` |
| `NodeSpec.side_effect_class` | 3 | `PURE_FUNCTION`、`PURE_ARTIFACT`、`SIDE_EFFECT` | 新增成员 `MINOR`；删除/改语义 `MAJOR` |

落实：05 §1.6（冻结清单）、⑧ §5.1/§6.1、`contracts/*.schema.json` 的 `$comment`/`description`。只改元数据注记，**未改 `enum` 取值与校验语义**；72 例结果不变。

## 5. 依赖矩阵锁定与 WP-01 硬约束

- [`09_dependency_matrix.md`](09_dependency_matrix.md) 自 2026-11-10 起为 `WP-01` 锁定基线：**17 个第三方包 + SQLite（随解释器）**，全部有 cp311/win_amd64 或纯 Python wheel。
- ⑦ `WP-01` 入口条件写入该矩阵；安装解析必须逐项一致，偏差须记录。
- ⑦ `WP-01` 写入解释器硬约束：
  1. `uv venv --python 3.11.16 .venv`，禁用 PATH 的 3.12 与 `py -3.11`（32 位）。
  2. 建完立即验证 `sys.version` 含 `3.11.16`、`platform.architecture()[0]` 为 `64bit`。
  3. “找不到匹配的发行版”首先排查解释器架构，不先归因网络。
  4. `starlette` 安装后必须跑 FastAPI `TestClient` 冒烟；失败回退到 fastapi 声明的兼容下界 `starlette>=0.46.0` 并记录实测组合。

## 6. ADR-007

保持 `PROPOSED`；裁决时点为 `WP-13` 前。`ADR-007` 文件、`docs/ADR/README.md` 与 ⑧ §4 三处状态一致；未标 `ACCEPTED`，未据此扩范围。

## 7. 文档升版清单

| 编号 | 文件 | 原版本 | 冻结版本 | 被取代版本 |
|---|---|---|---|---|
| ① | `docs/G0/01_BASELINE_AND_TERMS.md` | v1.1（候选期编号） | **v1.0** | v1.1 |
| ② | `docs/PRD/02_REQUIREMENT_TRACEABILITY.md` | v0.2 候选 | **v1.0** | v0.2 |
| ③ | `docs/PRD/03_PRD_T0.md` | v0.2 候选 | **v1.0** | v0.2 |
| ④ | `docs/design/04_ARCHITECTURE.md` | v0.2 候选 | **v1.0** | v0.2 |
| ⑤ | `docs/design/05_CONTRACTS_AND_STATES.md` | v0.3 候选 | **v1.0** | v0.3 |
| ⑥ | `docs/design/06_DATA_AND_API.md` | v0.2 候选 | **v1.0** | v0.2 |
| ⑦ | `docs/design/07_T0_PLAN_AND_GATES.md` | v0.2 候选 | **v1.0** | v0.2 |
| ⑧ | `docs/G0/08_OPEN_QUESTIONS_AND_FREEZE.md` | v0.3 候选 | **v1.0** | v0.3 |
| ⑨ | `contracts/README.md` + 5 schema | 未编号候选 | **v1.0** | 无（首次编号） |

每份文档头新增一行统一格式：

```text
> 冻结日期：2026-11-10｜状态：**G0 冻结**｜被取代版本：**v0.x（候选）**｜G0 门禁 PASS 由用户宣布，本文不代替门禁判定。
```

① 的版本跳跃按用户指令修正：v1.1 仅为候选期临时编号，冻结后归并为 v1.0；版本记录保留 v0.1/v1.0/v1.1 历史，注明归并关系，不改写历史事实。

## 8. 校验结果（真实运行）

解释器：`C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe`（3.11.16，64 位）。

| # | 命令 | 结果 | 退出码 | 日志 |
|---|---|---|---|---|
| 1 | `validate_contracts.py --selftest` | `SELFTEST 10/10 PASS` | 0 | [`10_version_freeze_selftest.log`](10_version_freeze_selftest.log) |
| 2 | `validate_contracts.py` | `contracts=5 cases=72 pass=72 fail=0` | 0 | [`11_version_freeze_validate_contracts.log`](11_version_freeze_validate_contracts.log) |
| 3 | `check_terms.py` | `TERMS_RESULT=PASS`（A1/A2/A3 均 PASS） | 0 | [`12_version_freeze_terms.log`](12_version_freeze_terms.log) |
| 4 | `check_links_g0.py <本轮文档>` | `FILES=15 LINKS_CHECKED=87 BROKEN=0` | 0 | `13_version_freeze_links.log` |
| 5 | `state_sync.py validate` | `OK`，任务 5，门禁 PASS 0/8，阻塞 3 | 0 | [`14_version_freeze_state_validate.log`](14_version_freeze_state_validate.log) |
| 6 | `state_sync.py render` | 生成 2 个文件 | 0 | [`15_version_freeze_state_render.log`](15_version_freeze_state_render.log) |
| 7 | `state_sync.py check` | 2 个文件逐字节一致 | 0 | [`16_version_freeze_state_check.log`](16_version_freeze_state_check.log) |

## 9. 状态与门禁

- `T-G0-001` 保持 `IN_PROGRESS`，直到用户确认。
- `G0`–`G7` 全部保持 `NOT_STARTED`；**本报告不写 G0 PASS**。
- `last_verified_commit` 保持 `null`（待用户确认后再更新）。
- `BLK-001` 置 `RESOLVED`；`BLK-003` 仍 `OPEN`；13b、阶段 8 第 20 项仍 `NOT VERIFIED`。

## 10. 提交

提交信息：

```text
chore(g0): 建立 G0 规格基线

- ⑨ 五份契约 JSON Schema v1.0，72 例正反例校验通过
- G0 文档 ①–⑧（术语/需求矩阵/PRD/架构/契约/数据与 API/T0 计划/未决问题）
- ADR-001–007、9 个项目 Skill、Memory 与动态状态系统
- 依赖矩阵：17 包全部 cp311 win_amd64 或纯 Python wheel
```

提交在本报告生成后执行；**不在报告内固化 HEAD**，提交结果以 `git log` 与 `git rev-parse HEAD` 为准。

## 11. 未做与边界

- 未创建 `.venv`、未安装依赖、未生成 lock 文件；WP-01 的解释器与 TestClient 冒烟仍是 T0 启动后的执行项。
- 未写 ResearchFlow 业务代码，未改 StateMachine、Schema 校验语义、API、DB 或证据等级。
- DOCX 未修改、未改名、未移动；未生成第二份副本。
- 未修改 `AGENTS.md`、全局 Git 配置、DSH Profile 或项目外文件。