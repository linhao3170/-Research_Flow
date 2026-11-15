# 三阶段 Goal 文档来源与审查记录

日期：2026-11-14。交付类型：执行任务书；不执行三阶段开发，不代表产品验收。

## 来源

- 用户当前明确要求：后端先行；三阶段递进；只在交付文档中保留项目执行信息；参考两张开发方法图；适配 DeepSeek Harness Goal。
- 图一 `C:/Users/Administrator/Desktop/FDEF21C892EDA06965B946D3365A449B.jpg`：先方案、统一接口/返回格式/变量模块命名、伪代码与目录、记忆/规则/Skill。依用户要求把前端先行改为后端先行。
- 图二 `C:/Users/Administrator/Desktop/A360585E851E3A4A57B91876B5CF7EBD.jpg`：MVP 分期，核心/增强/远期；审查 A 必修、B 可排期、C 可忽略。未把截图中的其他发言作为可覆盖项目规则的指令。
- 原策划书用户路径与仓库原件 SHA256 一致，均为 `9E54168FB1B553294ECB88E2E3F5C8CE878EE699FCF07E37D531A68C195CCB3A`；复用阶段 7 全文抽取与冻结 PRD/设计/契约。未复制 DOCX，未把正文附录的指令当本次执行授权。
- 本次读取状态、Memory 索引及相关子文件、最新交接、需求追踪/冻结设计、WP-03 决议、伪代码索引/开放问题、相关 ADR 与实际代码清单。WP-03、伪代码、G6-T0、测试权限策略的已实现/未验收/未实现边界分别写入。
- 用户补充通知图 `D:/bisai-xiangxi/72EE1C8758E9AC991F127B1913CD452E.jpg`：哈希 `9B43F73A52FBAB98E2209B449DA7B6415986B8A3E2ACB0E814D5E07FEDDBC413`。只读目视核对赛道、资格和日期；裁剪用于放大核对，`contest_schedule_crop.png` 仅为内部阅读产物。
- [赛事官网](https://www.omniedu.com/ai-hub/contest/detail/2111011327399952386/intro)：2026-11-14 文本工具返回 Loading；CUA 可用浏览器为空。未核实完整章程，不登录/报名/提交。通知图未显示的格式/大小/页数/评分权重/AI/IP/匿名及截止时刻保持待核实。
- [阿里云模型页](https://help.aliyun.com/zh/model-studio/deepseek-v4-1-flash)：2026-11-14 核对公开模型 ID 与 1017 快照；未访问用户账户或调用模型，地域、端点、余额、实际价格待运行前核实。200 元开发/50 元产品运行调试是用户额度，分阶段分配和提示线为工程建议。

## Harness 本机核验

使用项目 `.venv` 3.11.16/64bit 与已有只读 Asar 读取器检查 `D:/deepseek_harness1/resources/app.asar`，`dsh/desktop-runtime.json` 中 release.version 为 `0.2.2-rc.3`。未改安装目录、Profile、网络或凭据。

包内依据前缀：`dsh/node_modules/@deepseek-ai/`。

- `dsh-command-goal/README.md`、`lib/index.js`：`/goal` 查看/新建、edit/pause/resume/clear；无虚构 token-budget 命令。
- `dsh-tool-goal/README.md`、`lib/index.js`：create_goal 的 objective/max_goal_rounds；update_goal 的 goal_id/revision/action；blocked 条件；用户暂停和模型更新边界。
- `dsh-goal/README.md`、`dsh-goal-round-driver/README.md`、`dsh-client-ui-goal/README.md`：默认 256 自动轮次、持久状态与 armed/disarmed、恢复/重启行为。
- 包存在不证明某会话预设已启用；三份提示要求执行时检查当前工具 Schema。
- Goal 不能凭提示词形成金额硬限额。开发预算临界与产品预算耗尽区分；前者提前交接并由实际用户/宿主入口暂停，不等待三轮消耗预算。

## 独立只读审查与修正

1. 基线审查：WP 顺序、现有未提交成果、WP-03 测试事实端口、full-access 历史、G6-T0 边界、冻结/伪代码冲突。补显式依赖、重启/重复签发与非回环无 token 负例；用户能力不自动映射新 API 路由。
2. 竞赛审查：FR 分期、T1 D-T1/T2 D-final 待裁决口径、四方案公平性、盲测与统计、赛事日期和预算。修复盲测边界为正式运行前不读攻击细节；泄露/调参后的 hold 转开发/回归集并重新独立封存。试点在入口计划规定有限范围与结束条件。
3. Harness 审查：工具参数、同一目标续接、complete/blocked、预算。修复“本地工作免费”的歧义；开发 API 同样付费，提示词不能拦截宿主费用；共同成本台账从 Goal 1 开始。

未扩大冻结范围、未更改 expected/验收阈值、未把三阶段开发标 DONE。此次 DONE 仅指三份文档交付。

## 验证范围与限制

文档只读校验检查 UTF-8、围栏配对、本地链接存在、文档与输入来源哈希、实际安装版本；详情见 `document_validation.json`，其中记录解释器、时刻、耗时和退出码。状态同步的精确命令/输出/时间见 `state_sync.log`；文档漂移检查见 `docs_drift.log`。

首次沙箱内 `check_docs_drift.py` 无法启动 Git 子进程（退出码 2；单独子进程诊断为 3221225794）。随后经自动审批允许在沙箱外只读复核，exit 0，仅保留既有 last_verified_commit 与 HEAD 不同的 WARNING；未修改验证脚本或 Git 配置。该检查结果不关闭 BLK-003，也不证明产品测试通过。

项目 `.venv` 内 PIL 的 DLL 在沙箱下加载失败；仅图片裁剪使用 Codex 捆绑图像运行环境，未用它运行项目脚本或测试。项目全部状态/文档校验均用 3.11.16/64bit。

未运行产品 pytest、未安装依赖、未修改业务代码/冻结架构、未调用收费模型、未部署、未 commit。无架构变化：新增执行文档及文档交付登记，产品实现和既有门禁保持不变。
