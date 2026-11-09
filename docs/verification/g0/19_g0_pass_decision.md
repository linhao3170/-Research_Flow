# G0 门禁 PASS 决议记录

> 日期：2026-11-10（Asia/Shanghai）。
> 性质：记录用户对 G0 门禁的 PASS 宣布及支撑证据；**决议由用户作出，本记录不代替用户判断**。
> 基线：`91bde66365f24726003212c4b4f218da23148c1d`（`chore(g0): 建立 G0 规格基线`）。

## 1. 决议

| 项 | 内容 |
|---|---|
| 门禁 | G0「规格冻结」 |
| 结论 | **PASS** |
| 裁决人 | 用户 |
| 裁决日期 | 2026-11-10 |
| 生效范围 | G0 规格基线（①–⑧ + ⑨）；不改变 G1–G7 |
| 状态记录 | `docs/state/project_state.json` → `stage_gates.G0.status = PASS`、`decided_by = 用户`、`decided_at = 2026-11-10` |
| 任务记录 | `T-G0-001` → `DONE` |

用户宣布的依据（原文摘要）：

1. ①–⑧ 与 ⑨ 全部 v1.0 冻结；
2. 五份 schema 正反例 72/72 通过；
3. 阻塞级未决问题（OQ）= 0；
4. Git 基线 `91bde66` 已建立；
5. DOCX 未入库、哈希未变；
6. G0–G7 未被擅改。

## 2. 复核证据（2026-11-10 真实运行）

解释器：`C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe`（3.11.16，64 位）。

| # | 检查 | 命令 | 结果 | 退出码 | 日志 |
|---|---|---|---|---|---|
| 1 | 契约校验器自检 | `& $py -X utf8 scripts/validate_contracts.py --selftest` | `SELFTEST 10/10 PASS` | 0 | `20_g0_pass_recheck.log` |
| 2 | 五份 schema 正反例 | `& $py -X utf8 scripts/validate_contracts.py` | `SUMMARY contracts=5 cases=72 pass=72 fail=0 exit=0` | 0 | `20_g0_pass_recheck.log` |
| 3 | ①–⑧ 冻结标记 | 逐文件匹配「状态：**G0 冻结**」 | 8/8 | 0 | `20_g0_pass_recheck.log` |
| 4 | ⑨ schema 数量 | `contracts/*.schema.json` 计数 | 5 | 0 | `20_g0_pass_recheck.log` |
| 5 | 阻塞级 OQ | ⑧ `仍需用户确认` 行 | 0 | 0 | `08_OPEN_QUESTIONS_AND_FREEZE.md` |
| 6 | DOCX 未入库且未变 | `Get-FileHash`；`.gitignore` 精确规则 | 111,209 字节；SHA256 `9E54168FB1B553294ECB88E2E3F5C8CE878EE699FCF07E37D531A68C195CCB3A` | 0 | `20_g0_pass_recheck.log` |
| 7 | Git 基线 | `git rev-parse HEAD` | `91bde66365f24726003212c4b4f218da23148c1d` | 0 | `20_g0_pass_recheck.log` |

## 3. Git 回滚补测（关闭阶段 8 第 20 项）

在已跟踪文件 `docs/CHANGELOG_DEV.md` 末尾追加一行 `PROBE-G0-ROLLBACK-20261110`，确认 `git status` 显示修改、`git diff` 可见该行；随后执行 `git checkout -- docs/CHANGELOG_DEV.md` 恢复。

| 检查 | 结果 |
|---|---|
| 探针写入前 blob | `051d7616947cfcad59ae6d0f2b1d9b1aaf1e75a4` |
| `HEAD:docs/CHANGELOG_DEV.md` blob | `051d7616947cfcad59ae6d0f2b1d9b1aaf1e75a4` |
| 探针写入后 blob | `a4ae4393b7ef90b2ea000c16d42bb007e4d2956c` |
| `git checkout --` 退出码 | 0 |
| 恢复后 blob | `051d7616947cfcad59ae6d0f2b1d9b1aaf1e75a4`（与 HEAD 一致） |
| 恢复后 SHA256 | `070CF8F2B8D9B205FCB39322B56ADB098C98D6531DA8640C2D2CEDB979CCAB81`（与写入前一致） |
| 探针残留 | 无（`PROBE` 搜索为 False） |
| 文件级 `git status` | 空 |

完整命令、哈希与退出码见 [`18_git_rollback.log`](18_git_rollback.log)。阶段 8 第 20 项据此由 `NOT VERIFIED` 改为 `PASS`，标注「基线建立后补测」。

## 4. 工作区状态说明

会话开始时 `git status` 显示 `AGENTS.md` 有未提交修改（新增两条「正例/负例证据」规则），与用户宣布的「工作区干净」不一致。已向用户报告并获批准：该修改纳入本次 `chore(g0)` 提交，提交后工作区恢复干净。此事实不影响 G0 门禁判定，但按实测记录在此，未改写为「当时已干净」。

## 5. 边界

- `G1`–`G7` 保持 `NOT_STARTED`，未连带改动。
- 本决议不构成 T0 业务代码开发批准；T0 只进入 `WP-01` 环境与依赖锁定。
- 未创建 `.venv`、未安装依赖、未生成 lock（均属 `WP-01`）。
- 未修改冻结的 ①–⑧ 与 ⑨ 内容；只新增本决议记录与回滚/复核日志。