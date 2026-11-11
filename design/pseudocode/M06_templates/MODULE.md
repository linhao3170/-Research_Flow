# M06 · Templates（P4）

> 阶段：P4「模板与证据链」｜日期：2026-11-11｜状态：**伪代码/设计件，不是实现**
> 覆盖：三模型分类模板、参数契约、指标/产物/required_checks、SplitService 与六字段 manifest、
> 模型工厂与超参白名单、Wine 冒烟与 Breast Cancer 主干差异、离线数据集登记与绑定
> 不覆盖：Gate 判定（P5）、签名（P6）、L3 重跑（P5）、API（P10）、调度（P7）
> 前置：P3 已验收（Executor 协议与工作区已定）；M01 契约与错误码已冻结
> 阶段约束（S0）：只写 `design/pseudocode/**`；不建环境、不跑测试、不改看板、不写业务代码

## 1. 目标

让“真实执行”产生**可复算、可定位**的模板事实，并把数据划分钉成 L3 能重算的六字段清单：

1. **模板白名单**：只支持 `logistic_regression` / `random_forest` / `svm` 三个模型；
   参数只能是模板声明的键；模型/超参不在白名单一律拒绝（`models.py`）；
2. **可复现划分**：`SplitService` 生成 `dataset_hash`、`split`、`seed`、`row_id_hash`、
   `fold_assignment_hash`、`semantics` 六字段，`manifest_hash` 覆盖六字段（`splits.py`）；
3. **离线数据**：Wine / Breast Cancer 只从登记表 + 锁文件 + 本地文件读取；
   未登记、哈希不符、路径逃逸、许可不符一律拒绝（`datasets_registry.py`）；
4. **不裁决**：模板只产出指标、预测、划分、运行摘要、泄漏诊断；
   没有 `status`/`passed`/`verdict` 字段，不写证据/状态，不自报产物哈希；
5. **冒烟可跑**：Wine 三模型 + 收紧超参 + 120s 墙钟；与主干共享同一模板与同一组产物。

## 2. 文件

| 文件 | 内容 | 行数 | 状态 |
|---|---|---:|---|
| `executor/templates/classification_benchmark.py` | 模板契约、参数、指标、产物、required_checks、prepare/run 流程 | 523 | 完成（伪代码） |
| `executor/templates/splits.py` | SplitService、六字段、manifest_hash、train-only 语义、校验 | 752 | 完成（伪代码） |
| `executor/templates/models.py` | 三模型白名单、超参范围、拒绝点、工厂形状、静态边界 | 554 | 完成（伪代码） |
| `executor/templates/smoke_wine.py` | Wine 冒烟档案、预算上限、与主干差异表 | 232 | 完成（伪代码） |
| `data/datasets_registry.py` | 数据集登记、锁文件、三道比对、DatasetBinder | 510 | 完成（伪代码） |

行数为物理行数（含空行）。

均 ≤800 行，按 PHASE_RULES §5 第 1 档，无需函数索引。

## 3. 模板契约（`classification_benchmark.py`）

### 3.1 参数

| 参数 | 类型 | 必填 | 范围/枚举 | 说明 |
|---|---|---|---|---|
| `target` | string | 是 | 1–64 字符 | 目标列；必须存在于绑定 CSV 表头 |
| `seed` | integer | 是 | 0–2^31-1 | 划分与模型随机性；进入 manifest |
| `test_size` | number | 是 | [0.1, 0.5] | 模板比 TaskSpec 的 (0,1) 更紧，保证测试行足够 |
| `models` | array[string] | 是 | 1–3 个，白名单、无重复 | 三模型可任选子集 |
| `scale_features` | boolean | 否 | 默认 true | 选中 LR/SVM 时必须 true |
| `model.param` | 按模型 | 否 | 见 `models.MODEL_SPECS` | 扁平键，如 `svm.C`；未知键拒绝 |

模型超参上限（模板默认值，不是“最优值”）：

| 模型 | 超参（默认 / 范围） |
|---|---|
| `logistic_regression` | `C`=1.0 [1e-6,1e6]；`max_iter`=1000 [100,10000]；`class_weight`=none/balanced |
| `random_forest` | `n_estimators`=200 [10,500]；`max_depth`=16 [1,64]；`min_samples_leaf`=1 [1,50]；`max_features`=sqrt/log2；`class_weight`=none/balanced |
| `svm` | `C`=1.0 [1e-6,1e6]；`kernel`=linear/rbf；`gamma`=scale/auto；`class_weight`=none/balanced |

`random_state` / `n_jobs` / `warm_start` 等由工厂固定写入，用户传值一律拒绝
（`RESERVED_MODEL_PARAM`）；RF 的 `n_jobs` 固定 1，模板不自己开并行。

### 3.2 指标（只在测试折算）

`accuracy`、`precision_macro`、`recall_macro`、`f1_macro`、`roc_auc_ovr`。
`roc_auc_ovr` 用 `decision_function`（SVM `probability=False`），避免内部 CV 引入第二层随机性；
二分类把 1D 分数转成 `[-s, s]` 两列，多分类直接用 `(n_samples, n_classes)`。
每个模型记录 `n_test`；`metrics.json` 不含 PASS/FAIL，也不含“最佳模型”裁决。

### 3.3 产物（5 个，无模型二进制）

| 产物 | 内容 | 为什么需要 |
|---|---|---|
| `split_manifest.json` | 六字段 + `manifest_hash` | L3 重算划分 |
| `metrics.json` | 每模型 × 指标 + `n_test` + 定义 | Gate/L2 重算与比较 |
| `predictions.csv` | 测试折 `row_id,fold,y_true,pred_*,score_*` | L2 从原始预测重算指标 |
| `run_summary.json` | 解析后参数、库版本、行数、耗时 | 复现与环境归因 |
| `leakage_report.json` | 行重叠、重复行、target 混入特征、ID 类特征、scaler 作用域 | L2 泄漏五规则的输入 |

不产出 `.pkl/.joblib`：L3 是重训，不是加载模型；pickle 反序列化会引入任意代码执行风险。
【OQ-P4-10】若 WP-05 坚持要模型产物，必须同时定义“验证路径永不反序列化”。

### 3.4 required_checks（声明，不是自检结果）

| check_id | 执行类 | 最低等级 | 说明 |
|---|---|---:|---|
| `dataset_hash_match` | 是 | E2 | 绑定数据字节哈希 = 登记哈希 |
| `split_manifest_valid` | 是 | E2 | 六字段齐全、manifest_hash 重算一致 |
| `predictions_cover_test_rows` | 是 | E2 | 覆盖全部测试行且无多余行 |
| `metrics_recomputable` | 是 | E2 | 由 predictions + 标签可重算指标 |
| `no_train_test_overlap` | 是 | E2 | train/test 行无交集 |
| `leakage_report_present` | 是 | E2 | 泄漏诊断产物存在且字段完整 |
| `model_params_whitelisted` | 否 | E1 | 模型/超参来自白名单 |
| `seed_recorded` | 否 | E1 | seed 进入 manifest 与 run_summary |

执行类必检至少 E2；E0/E1 只能辅助。P5 的 Gate 必须调用
`collector.assert_can_satisfy_execution_check()`，不得用 Agent 声明顶替。

## 4. Split Manifest（`splits.py`）

### 4.1 六字段

逻辑字段名（与策划书 §9.3 逐字对应，`splits.LOGICAL_MANIFEST_FIELDS`）：
`dataset_hash`、`split_algorithm/version`、`seed`、`row_id_hash`、`fold_assignment_hash`、
`group/time_semantics`。物理 payload（`splits.SPLIT_MANIFEST_FIELDS`）如下：

| # | 字段 | 内容 | 被 manifest_hash 覆盖 |
|---:|---|---|---|
| 1 | `dataset_hash` | 原始数据文件**字节**的 SHA-256（二进制读） | 是 |
| 2 | `split` | `{algorithm, version, params:{test_size,stratify_on}}` | 是 |
| 3 | `seed` | 划分随机种子 | 是 |
| 4 | `row_id_hash` | `sha256(JCS(row_ids))`，数组保持数据行顺序 | 是 |
| 5 | `fold_assignment_hash` | `sha256(JCS([[row_id, fold], ...]))`，按数据行顺序 | 是 |
| 6 | `semantics` | `{group_key,time_key,ordering,group_aware,time_aware,notes}` | 是 |

`manifest_hash = sha256(JCS(六字段))`；`schema_version` 与 `manifest_hash` 是信封字段，
不进入前像。`MANIFEST_HASH_EXCLUDED = ("schema_version","manifest_hash")` 写死在代码里。

### 4.2 划分语义

- T0 两个数据集都 `group_key=None`、`time_key=None`、`ordering="row_index"`；
  **必须显式写 `none`**，不得省略语义字段。
- group 只允许 GroupShuffleSplit 类语义：同一 group 不得跨 train/test；
- time 只允许按时间排序取尾部，禁止 shuffle；
- group + time 同时启用 → `GROUP_TIME_UNSUPPORTED`，不猜；
- 分层：每个类别必须同时出现在 train/test；test 行数偏离期望超过
  `max(1, 10%)` → `TEST_SIZE_DEVIATION`。

### 4.3 L3 校验顺序（`SplitService.verify`）

1. `schema_version` / 六字段集合；
2. `dataset_hash` 与传入数据视图比对；
3. `split.algorithm/version/test_size` 与期望一致；
4. `row_id_hash` 重算；
5. 用同 seed 重跑划分，重算 `fold_assignment_hash`；
6. 重算 `manifest_hash`。

任何一步失败返回 `ok=False` + 可断言 `reason`；`assert_valid()` 抛
`SplitVerificationError(BUNDLE_TAMPERED)`。L3 不得“看起来差不多”就通过。

### 4.4 train-only 语义

`FOLD_TRAIN=0`、`FOLD_TEST=1`。模板必须：
- 只在 `train_indices` 上 `fit`（含 scaler/encoder）；
- 只在 `test_indices` 上 `predict`/算指标；
- 不读原运行的 metrics/predictions/模型文件。

## 5. 数据集登记（`data/datasets_registry.py`）

### 5.1 静态登记（无真实哈希）

| dataset_id | 来源 | 许可 | 版本标签 | 形状 | 用途 |
|---|---|---|---:|---:|---|
| `wine` | UCI 109，scikit-learn 1.9.1 自带 CSV 导出 | CC-BY-4.0 | `uci-wine-1` | 178×13，3 类 | 冒烟 |
| `breast_cancer` | UCI 17，scikit-learn 1.9.1 自带 CSV 导出 | CC-BY-4.0 | `uci-bcw-diagnostic-1` | 569×30，2 类 | 主干 |

真实 `sha256` 与 `size_bytes` 来自 WP-05 的 `datasets.lock.json`；本阶段不写真实哈希
（PHASE_RULES §5）。UCI 修订号【待核实】，以归档文件 SHA-256 为版本事实源。

### 5.2 三道比对

1. `local://datasets/<id>` 必须解析到已登记 id；网络/绝对路径/`..`/查询串一律拒绝；
2. `dataset_ref.sha256` 必须等于锁文件哈希；
3. 锁文件哈希必须等于文件字节哈希（读取时重算）。

另检 `dataset_ref.license` 与登记许可一致；`DatasetBinder` 复制后再算一次哈希，
目标已存在则拒绝覆盖。

### 5.3 绑定到 attempt

`DatasetBinder.bind()` 是 M05 `run_attempt` 的集成点（P4 只定义，不改 P3）：
在写 `inputs/params.json` 后、提交 `executor_launch` 前，把数据复制为
`inputs/dataset.csv` 并写 `inputs/dataset_binding.json`；模板只读这两个文件，
不读注册表根、不读绝对路径、不联网。【OQ-P4-07】

## 6. Wine 冒烟 vs Breast Cancer 主干

| 维度 | Wine 冒烟 | BCW 主干 |
|---|---|---|
| 数据集 | 178×13，3 类 | 569×30，2 类 |
| 模型 | 三模型全选 | 三模型全选 |
| 超参 | `SMOKE_CAPS` 收紧（RF≤100 棵、LR/SVM C 收紧） | 模板默认值 |
| wall_time_sec | 120 | 600 |
| memory_mb | 1024 | 2048 |
| test_size | 0.2 | 0.2 |
| 额外必检 | `smoke_within_wall_time` | 无；按 L3 覆盖判定 |
| 用途 | 30 秒级链路自检；不得作为验收成绩 | 演示；L3 覆盖后才谈 VERIFIED |

“2 分钟内”不是模板自报：超参上限在 `prepare()` 前拒绝；`limits.wall_time_sec=120`
由执行器强制；实际 elapsed 由 E2 的 `executor_process_exit` 观测，Gate 的
`smoke_within_wall_time` 判定。P4 不预填“已通过”。

## 7. 安全边界

| 禁止 | 落点 | 拒绝方式 |
|---|---|---|
| 任意代码执行入口 | 模板只经 `module+symbol` 登记；无 `eval/exec/compile/importlib` | `TOOL_NOT_ALLOWLISTED`(403) / 静态检查 |
| 运行期下载数据 | 无 `requests/urllib/socket/http`；数据集只读本地锁文件 | `TOOL_NOT_ALLOWLISTED` / `assert_dataset_boundary()` |
| 未知模型/超参 | `models.MODEL_SPECS` 白名单；不做类型强转 | `SCHEMA_INVALID`(422) + `field_path` |
| 未登记数据集 | 注册表 + 锁文件 + 任务引用三道比对 | `SCHEMA_INVALID` + `DATASET_NOT_REGISTERED` |
| 模板自报裁决/哈希 | `RunReport` 无 verdict 槽位；`ArtifactSpec` 无 sha256/size | 结构上不可达 + 静态检查 |
| 全量数据 fit scaler | 模板流程钉死 train-only；split 索引是唯一入口 | L2/Gate 负例 + 代码审查 |

## 8. 验收对照

| 判据 | 落点 | 状态 |
|---|---|---|
| Splits 六字段齐全且被 manifest 哈希覆盖 | 本文 §4.1；`splits.SPLIT_MANIFEST_FIELDS` / `compute_manifest_hash` | 已定义，未执行 |
| 未登记数据集拒绝 | `datasets_registry.DatasetRegistry.get/require_dataset_ref` | 判据已定义，未执行 |
| 非法超参拒绝点明确 | `models.resolve_params` / `param_field_specs` | 判据已定义，未执行 |
| Wine 冒烟 2 分钟内有结构性上限 | `smoke_wine.assert_smoke_budget` / `SMOKE_CAPS` | 上限已定义，未实测 |
| 模板无任意代码入口/下载 | `assert_template_boundary` / `assert_dataset_boundary` | 静态判据已定义，未执行 |

## 9. DECISIONS（P4 设计决定）

1. 一个模板支持三模型，`models` 选子集；不为每个模型复制模板，避免三份 split/metrics 逻辑漂移。
2. 不产出模型二进制；L3 重训，验证路径不反序列化（OQ-P4-10 保留）。
3. `test_size` 收紧到 [0.1,0.5]，保证分层与测试行数；TaskSpec 的 (0,1) 不变。
4. `artifact_refs` 缺失在链前像中规范化为 `[]`（OQ-P4-12 记录，P4 约定）。
5. 数据集真实哈希只从锁文件来，代码不写死；三道比对缺一不可。
6. `required_checks` 由模板声明、Builder 写入 NodeSpec；M05 登记项无此字段（OQ-P4-08）。

## 10. OPEN QUESTIONS（新增，待用户裁决）

| 编号 | 问题 | P4 临时处理 |
|---|---|---|
| `OQ-P4-03` | 未登记数据集没有专用错误码 | 用 `SCHEMA_INVALID` + `detail.reason="DATASET_NOT_REGISTERED"`，field_path=`dataset_ref.uri` |
| `OQ-P4-07` | DatasetBinder 需插入 M05 `run_attempt` 的 step 4/5 之间 | P4 只定义接口；WP-06 集成前不得启动模板 |
| `OQ-P4-08` | M05 `TemplateRegistration` 没有 `required_checks` 字段 | 作为模板元数据导出，WP-05 写入 NodeSpec |
| `OQ-P4-10` | 是否必须产出模型文件 | P4 选择不产出；若强制，必须定义“永不反序列化” |
| `OQ-P4-11` | 乱序缓冲/等待常量没有配置键 | `max_reorder=64`、`max_wait_sec=5`，标注非契约 |
| `OQ-P4-12` | `artifact_refs` NULL 与 `[]` 的前像规范 | P4 统一 `[]`；需在 encoding/chain 文档同步 |

## 11. 本阶段不做

- 不实现 sklearn 拟合、CSV 读写、真实计时（WP-05）。
- 不生成真实 SHA-256、不建 `datasets.lock.json`、不复制数据（WP-05）。
- 不做 Gate 判定（P5）、不做 L3 重跑（P5）、不签名（P6）。
- 不建 `.venv`、不装依赖、不跑测试、不改看板。