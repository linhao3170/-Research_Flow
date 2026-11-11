# M01 · NEGATIVE_TESTS — 负例判据（P1）

> 阶段：P1｜状态：**判据定义，未执行**（本阶段限权：不建环境、不跑测试）
> 执行阶段：M01 落地（WP-02 之后）
> 解释器（届时必须）：`C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe`
> 记录要求：命令、解释器、退出码、日志路径、运行时间；**P1 不得写成“已通过”**。

## 0. 判定纪律

1. 每条负例必须以**拒绝原因正确**为通过条件：断言错误码 / 异常类 / `keyword` / `pointer` / `field_path`
   中至少一项与下表一致；只断言“抛异常了”或“被拒绝”判**测试失败**。
2. 原因不符即失败，不得回填期望值、不得放宽断言。
3. 同一用例重复运行不构成独立样本；表中每条只计一次。
4. 正例通过不构成完成证据：本表 15 条必须真实执行并逐条留下拒绝原因。

## A. 真负例（15 条）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M01-01 | 未冻结 ID 不得生成 | `new_id(IdKind.DC)` | `UnfrozenIdKind`，且 `.kind is IdKind.DC`；不得返回任何字符串 | 05 §1.4；OQ-CT-07 |
| NEG-M01-02 | Node 无前缀 | `new_id(IdKind.NODE)` | `UnfrozenIdKind`，`.kind is IdKind.NODE`；断言返回值不为 `"node_..."`（无返回值） | 05 §1.4「Node 无前缀要求」 |
| NEG-M01-03 | Bundle 标识不存在 | `new_id(IdKind.BUNDLE)` | `UnfrozenIdKind`；断言不存在 `bundle_` 前缀常量 | 05/06 未定义 |
| NEG-M01-04 | 不得静默大小写归一 | monkeypatch UUID 生成器返回大写文本 → `new_id(IdKind.TASK)` | 抛 `ValueError`（信息含 `TASK_ID_PATTERN`）；**不得**返回小写化后的合法 ID | ENCODING_RULES §2 |
| NEG-M01-05 | 重复键 | 原始文本含两个 `goal` 键 → `loads_strict` | `ContractJSONError`，`keyword == "duplicate-key"`，`pointer == "goal"` | 05 §1.3；附录 D.6 |
| NEG-M01-06 | NaN | 原始文本含 `NaN` → `loads_strict` | `keyword == "non-finite-number"`，`pointer == "$"` | 同上 |
| NEG-M01-07 | Infinity | `Infinity` / `-Infinity` → `loads_strict` | `keyword == "non-finite-number"`；不得转 `null`/`0` | 同上 |
| NEG-M01-08 | 非法 Unicode | `canonical_bytes({"goal": "\ud800"})` | `CanonicalizationError`，`checkpoint is Checkpoint.INVALID_UNICODE`，`pointer == "$.goal"` | ENCODING_RULES §7 |
| NEG-M01-09 | 数组不得重排 | `canonical_bytes({"a": [1, 2]})` vs `{"a": [2, 1]}` | 两者**必须不同**；相同 → 实现排了数组 → FAIL | JCS；05 §1.3 |
| NEG-M01-10 | E.3 状态码不得改写 | 查 `HARNESS_EVENT_DUPLICATE` / `HARNESS_EVENT_GAP` | 分别 `200` / `202`；写成 409/422/500 任一 → FAIL | 附录 E.3；06 §4.4 |
| NEG-M01-11 | 未注册码不得兜底 | `lookup("CERTIFICATE_NOT_AVAILABLE")` | `KeyError`，信息含该码名；不得返回通用 `ErrorCode` | 06 §4.4「不新增错误码」；errors 纪律 |
| NEG-M01-12 | 注册表规模与唯一性 | 遍历 `REGISTRY` | `len(APPENDIX_E3) == 13`、`REGISTRY_SIZE == 27`、name 无重复；多一个/少一个即 FAIL | P1 自检 |
| NEG-M01-13 | 码不得只有名字 | 遍历所有 `ErrorCode` | `raised_by` 非空且 `trigger` 非空；任一条为空 → FAIL（“谁抛/何时抛”未定义） | 用户 P1 必写项 |
| NEG-M01-14 | 缺口不得携带字段定义 | `by_code("GAP-DC-01")` / `"GAP-SPA-01"` / `"OQ-CT-06"` | 结构上无 `fields/properties/schema/required` 属性；`disposition == "本阶段不定义"`；13 条齐全 | S0 §0.6 裁决；05 §7/§8 |
| NEG-M01-15 | CANDIDATE 钩子不得调用 | `invoke("profile_data")` | `DomainPackNotFrozen`，`.code == "DOMAIN_PACK_HOOK_UNFROZEN"`，`.hook_name == "profile_data"` | OQ-CT-07；errors.py |

## B. 误拒守卫（2 条：防止“过度收紧”把合法输入拒掉）

| ID | 守卫目标 | 输入 / 操作 | 期望 | 依据 |
|---|---|---|---|---|
| GUARD-M01-01 | 创世值未裁决，不得强校验 | `accept_first_prev_hash("f" * 64)` | 返回 `True`（形态合法即可）；返回 `False` 或抛错 → 过度收紧 → FAIL | OQ-CT-10 未决 |
| GUARD-M01-02 | JCS 是 UTF-16 序，不是码点序 | 对象键 `"\U0001F600"` 与 `"\uFF01"` 规范化 | 第一个键必须是 `"\U0001F600"`（UTF-16 码元 0xD83D < 0xFF01）；用 `json.dumps(sort_keys=True)` 会先输出 `"\uFF01"` → FAIL | RFC 8785；ENCODING_RULES §5 |

## C. 与正例的边界

- 正例（5 份 schema 的 5 个 positive + 67 个 negative）仍以 `contracts/examples/manifest.json` 与
  `scripts/validate_contracts.py` 为准；**P1 不改那 72 个用例**，也不在此重复其期望值。
- 本表只补“契约文件之外、但 P1 必须钉死”的 17 条判据；与 72 例重叠的部分以 72 例为准。

## D. 执行记录模板（落地阶段填写，P1 留空）

| ID | 命令 | 退出码 | 断言到的原因 | 日志路径 | 结论 |
|---|---|---|---|---|---|
| NEG-M01-01 | （待执行） | — | — | — | 未执行 |