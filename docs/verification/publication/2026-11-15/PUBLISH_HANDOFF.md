# T0 首次 GitHub 提交交接

## 用户授权与分工

用户于 2026-11-15 明确要求提交已验收 T0，并随后明确由 **DeepSeek Harness 执行 commit 和 push**；Codex 负责核心审核、方案判断与部分难点开发。本次 Codex 未暂存、未 commit、未修改 remote、未 push。后续常规提交不交由 Codex 代执行，除非用户另行要求。

准确目标：`https://github.com/linhao3170/-Research_Flow`，Git URL：`https://github.com/linhao3170/-Research_Flow.git`。仓库名有前导连字符，不能擅自改成 `Research_Flow`。用户提供了创建后的链接；本轮尚未验证远端可见性、是否为空及访问权限。按私有仓库的预期核对；如果实际公开，先报告差异，不静默扩大公开范围。

该授权取代此前“暂不 commit”的操作限制，不改变 T0 已披露风险，不授权 T1 自动开工、重写历史、force push 或改全局 Git 身份。

## 已核实基线

- 分支 `main`，HEAD `309083e715cb59a1f0c181d95df44e1946ffbaa5`；7 个历史提交。
- 本仓库 Git 身份 `ResearchFlow Dev <dev@researchflow.local>`，沿用既有仓库配置，不改全局配置。
- T0 验收与 A-01/A-02/A-03 收口资料在 `docs/verification/t0/T0_ACCEPTANCE.md`、`review_2026-11-15.md` 及各专题目录。历史全量日志为 **351 passed in 395.66s**；本轮没有重跑产品全量测试。
- 当前 `last_verified_commit` 仍为历史值，不能仅为了消除 WARNING 而替换成 HEAD。
- 15 元已记入 `docs/verification/budget/BUDGET_LEDGER.md`：用户确认本次收口开发 API 消耗；更正同批未知记录，不重复累计。更早批次消耗及总余额未知，不能推算余额 185 元；产品 API 沿用 T0 为 0 的证据。

## 提交范围与排除项

允许提交当前验收成果：业务代码、测试、独立验签器、锁定依赖、合成样例、契约、已批准 ADR、项目规则/Skills、状态/记忆/交接、Goal 文档、修复及验收证据。

证据保留 Bundle、包外公开 trust store、报告、日志、截图以及有说明的历史证据。排除运行私钥、凭据、虚拟环境、根运行目录、临时测试目录、e2e 本地 SQLite/WAL/SHM 和原 DOCX。已增量补充 `.gitignore`，原文件未删除。

P7/P8 设计可按已验收记录提交。P9（M15/M16）、P10（M19）仍 **BLOCKED**，只作为既有未验收设计草稿保留，不导入生产、不执行、不改状态、不宣称完成。状态校验要求已登记模块目录存在，完全排除这些目录会让新克隆的状态检查失败；保留现状不代表批准其实施。提交说明必须明示此边界，不为发布放宽校验器。

当前工作区存在此前积累的多个模块变更，不使用无清单的 `git add .`，也不 reset、clean 或删除未提交文件。先审查准确路径列表，再按清单暂存。

## 本次安全与范围预检

`working_audit.json` 是工作区候选快照，含路径、大小和 SHA256；不是最终 staged 审查。检查跳过敏感命名文件内容，对文本检查典型 GitHub/API/AWS 凭据格式、私钥块和私钥 JSON 值；不会打印匹配值。当前匹配列表为空，无超过 50 MiB 的候选文件。该检查加上人工范围审核不能证明绝无秘密；新增改动、暂存内容和历史仍须复核。

已只读抽查 7 个提交的敏感文件名和典型密钥格式；PEM 头命中为负例文档中的说明文字，没有读取真实私钥。旧 stage7 扫描脚本会覆盖历史日志且范围不足，不直接复用。

本轮浏览器连接和部分沙箱外命令因自动审批服务 404（`codex-auto-review` 不被代理支持）未执行。后续候选扫描通过直接 Git 导出路径和受限环境的文件读取完成，没有修改审批或系统配置。Harness 应使用自身当前有效工具与权限，不复用本轮或历史 full-access 授权，不关闭 BLK-003。

## Harness 执行顺序

1. 读取 AGENTS、状态、Memory 索引、最新 SESSION_HANDOFF、本交接及 MEMORY_CLOSEOUT；确认没有另一会话正在写相同文件。
2. 核对身份、分支、工作区差异、远端仓库地址/私有状态/分支。远端为空则正常首次推送；若已有历史先 fetch 并比较，不 force push，不覆盖其他仓库。没有 origin 时可添加准确 URL；若已存在不同 origin，保留它并使用新的明确 remote 名称，不静默改址。
3. 重新生成候选清单，复核 `.gitignore` 和提交范围。已有 `candidate_paths.txt`/`candidates.nul` 只属旧扫描辅助，不能直接作为最新暂存授权。按核对后的清单暂存，检查 `git diff --cached --stat`、`--name-only` 和准确 staged 内容；复核历史与新增内容的秘密风险，不输出秘密。
4. 需要时运行 `audit_snapshot.py staged` 审查整个索引，并记录真实结果；该模式会读取索引而非工作区。工具不适用时用等价无秘密输出检查，不假称执行成功。
5. 确认验收证据与待提交代码一致；无业务变化时复用已验收的351项历史证据，不改写成本次通过。运行契约、状态同步、文档检查及确有必要的定向验证；修改可信链时追加相应复验。使用项目 3.11.16/64 位解释器，不用默认 Python。
6. 更新本次提交交接与预算事实，按 MEMORY_CLOSEOUT 完成文件同步后再提交。建议说明：`feat(t0): 完成可信闭环与 A-01/A-02/A-03 收口`；注明未验收草稿只保存现状。
7. 执行真实 commit 和普通 push 到准确远端。核对本地 commit 与远端 main 一致、仓库页面可访问；仅在远端事实确认后写“已推送”。推送失败保留本地 commit 并报告具体原因，不重写历史。
8. 用新建临时目录检验提交快照或干净 clone 的必要入口，特别是状态目录、依赖说明、Bundle 与离线验签；不要求提交运行数据库或私钥。历史日志中机器本地路径仅为历史来源，不伪称新 clone 包含运行现场。
9. 自动收尾更新状态、日志、交接和稳定记忆。若提交后产生文档收尾变更，可作单独普通文档提交并推送，不 amend 前一提交；`last_verified_commit` 只指向确有对应验证的实际提交，无证据则保留并解释。

最终交付：仓库 URL/可见性、真实 commit hash、push 结果、具体提交范围、排除内容、检查命令/证据、未解决限制、累计预算口径。不得把工作区扫描通过当作 staged 或远端提交已通过；不自动进入 Goal 2。

## Harness 执行记录（2026-11-15，提交前）

- 远端：新增 `origin` = `https://github.com/linhao3170/-Research_Flow.git`（fetch/push 同址，前导连字符保留，未改成 `Research_Flow`）。`git ls-remote --heads origin` exit 0、0 个 ref，远端无既有分支。
- 可见性差异：`GET https://api.github.com/repos/linhao3170/-Research_Flow` 返回 200，`private=false`、`size=0`、`default_branch=main`、`pushed_at=2026-11-15T03:06:41Z`。仓库实际是**公开空仓库**，与本节上文“按私有仓库的预期核对”不一致。已按用户明确给出的目标 URL 继续，未修改仓库可见性；该差异在交付与收尾文档中明确报告。
- 身份：仓库级 `user.name=ResearchFlow Dev`、`user.email=dev@researchflow.local`；全局 `user.name` / `user.email` 仍为空；未写入全局配置。
- 候选与暂存：重新生成候选清单（`working_audit.json`，0 findings），按 `candidates.nul` 逐路径暂存，未使用无清单 `git add .`，未 reset、clean 或删除未提交文件。最终索引扫描结果见 `staged_audit.json`；候选清单文本本身只是扫描辅助，已按 `.gitignore` 排除。
- 换行与证据完整性：`.gitattributes` 增加 `/docs/verification/t0/e2e/** -text` 与 `/docs/verification/t0/g6-t0/** -text`。原因：e2e Bundle 内 `manifest.json` 的 SHA-256 基于生成时的原始字节；提交前实测 run_1 Bundle 的 65 个文件中有 34 个工作区 CRLF 与索引 LF 不一致，若按文本归一化，新克隆中的离线验签会因字节不同失败。修正后核对 e2e/g6-t0 共 1427 个文件，工作区与索引逐字节一致（差异 0）。
- 秘密风险：最终索引扫描 0 findings；7 个历史提交对私钥块、GitHub/AWS/阿里云令牌、`sk-` 格式与 PuTTY 密钥扫描均 0 命中；历史无敏感文件名。该检查不能证明绝无秘密，限制同前。命中过两处变量名/标准向量，人工确认为代码变量与 RFC 8032 公开测试向量，非凭据。
- P9/P10：`design/pseudocode/M15_dcspa`、`M16_vas`、`M19_api` 仅作为状态文件要求的既有草稿保留，状态仍 `BLOCKED`；未执行、未导入生产、未改其状态，也不构成验收或开发批准。
- 本次真实运行（解释器 `D:\ResearchFlow-project\.venv\Scripts\python.exe`，3.11.16/64bit）：`validate_contracts.py --selftest` 10/10、`validate_contracts.py` 72/72、`state_sync.py validate/render/check` 均 exit 0、`check_docs_drift.py` ERROR=0/WARNING=1（`last_verified_commit` 与 HEAD 差异，已知）；日志 `01_*.log`–`06_*.log`。历史全量 351 passed（395.66 s）本次未重跑，不写成本轮通过，也不据此改写 `last_verified_commit`。
- 预算口径：15.00 元为同一批用户确认的开发消耗，只计一次；本轮提交/推送不新增用户确认消耗，不推算累计余额与 185 元。
- 推送与干净快照验证结果：见下文“推送与验证”记录。
