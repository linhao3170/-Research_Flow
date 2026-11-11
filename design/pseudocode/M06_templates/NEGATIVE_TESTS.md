# M06 · NEGATIVE_TESTS — 负例判据（P4）

> 阶段：P4｜状态：**判据定义，未执行**（S0：不建环境、不跑测试、不写业务代码）
> 执行阶段：M06 落地（WP-05）
> 解释器（届时必须）：`C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe`
> 记录要求：命令、解释器、退出码、日志路径、运行时间；**P4 不得写成“已通过”**。
> 数据真实哈希、锁文件与 CSV 属 WP-05；本表只定义“拒绝原因必须是什么”。

## 0. 判定纪律

1. 每条负例必须断言**拒绝原因正确**：异常类 + `reason` + `error_code` + `field_path`
   中至少三项与下表一致；只断言“抛异常了”判失败。
2. 数据集/划分类负例必须断言：**错误发生在拟合之前**（无 artifact、无 fit 调用）。
3. 参数类负例必须断言：**没有类型强转**（`"42"` 不得变成 `42`，`true` 不得当 `1`）。
4. 静态边界负例必须断言具体禁名/禁字段，不得只断言“看起来没有”。
5. 原因不符即失败；不得改期望值、放宽范围、用“重试通过”覆盖失败记录。
6. 正例通过不构成完成证据；本表必须真实执行并逐条留下拒绝原因。
7. 本表每条只计一次；同一用例重复运行不构成独立样本。

## A. 数据集登记与绑定（`data/datasets_registry.py`）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M06-01 | 未登记数据集被拒 | `require_dataset_ref("local://datasets/iris", <hash>, "CC-BY-4.0")` | `DatasetRegistryError`；`reason=DATASET_NOT_REGISTERED`；`error_code=SCHEMA_INVALID`；`field_path=dataset_ref.uri`；`http_status=422` | 用户判据 4；本文 §5.2 |
| NEG-M06-02 | 网络 URI 被拒 | `uri="https://archive.ics.uci.edu/..."` / `"local://datasets/http://x"` | `DATASET_URI_NOT_LOCAL` / `DATASET_URI_INVALID`；不得尝试下载 | T0 断网；`NFR-01` |
| NEG-M06-03 | 路径穿越被拒 | `local://datasets/../wine`、`local://datasets/wine/../../x` | `DATASET_URI_INVALID`；`field_path=dataset_ref.uri` | 本文 §5.2 |
| NEG-M06-04 | 任务引用哈希不符 | 锁哈希 `A`，TaskSpec 写 `B` | `DATASET_HASH_MISMATCH`；`field_path=dataset_ref.sha256`；不读取文件 | 三道比对 ② |
| NEG-M06-05 | 文件字节被换 | 锁 `A`，磁盘文件写入不同字节后 `read_verified()` | `DATASET_HASH_MISMATCH`；`field_path=dataset_ref.sha256`；不返回近似内容 | 三道比对 ③ |
| NEG-M06-06 | 许可不符 | TaskSpec `license="MIT"`，登记 `CC-BY-4.0` | `DATASET_LICENSE_MISMATCH`；`field_path=dataset_ref.license` | 本文 §5.2；NFR-08 |
| NEG-M06-07 | 锁文件缺数据集 | 锁只含 `wine`，登记有 `wine`/`breast_cancer` | `LOCK_DATASET_SET_MISMATCH`；detail 含缺失项 `breast_cancer` | 本文 §5.1 |
| NEG-M06-08 | 锁文件多数据集 | 锁多出 `iris` | `LOCK_DATASET_SET_MISMATCH`；detail 含多余项 | 同上 |
| NEG-M06-09 | 锁文件改路径 | `wine` 的 `offline_relative_path` 改成 `../secret.csv` | `LOCK_PATH_MISMATCH`；不得跟随新路径 | 同上 |
| NEG-M06-10 | 数据根是链接 | root 指向 junction | `DATASET_ROOT_LINKED`；`field_path=root` | 路径边界 |
| NEG-M06-11 | 文件大小不符 | 锁 `size_bytes=999`，文件 100 | `DATASET_SIZE_MISMATCH`；`field_path=size_bytes` | 三道比对 ③ |
| NEG-M06-12 | 静态登记路径逃逸 | 构造 `DatasetSpec(offline_relative_path="../x.csv")` | `ValueError`；消息含“无逃逸的相对 POSIX 路径” | 本文 §5.1 |
| NEG-M06-13 | 绑定目标已存在 | `inputs/dataset.csv` 已存在再 `bind()` | `DATASET_BINDING_EXISTS`；**不得覆盖**；旧文件哈希不变 | 本文 §5.3 |
| NEG-M06-14 | 复制后哈希不符 | 桩：写入后读回字节被改 | `DATASET_COPY_HASH_MISMATCH`；删除临时文件；目标不落盘 | 本文 §5.3 |
| NEG-M06-15 | inputs 目录缺失 | `bind(Path("nope"), ...)` | `INPUTS_DIR_MISSING`；不创建目录、不写文件 | 同上 |
| NEG-M06-16 | 模块出现下载入口 | 静态：模块暴露 `requests`/`urllib`/`download` | `assert_dataset_boundary()` 返回非空，含具体禁名 | T0 断网 |

## B. 模型与超参（`executor/templates/models.py`）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M06-17 | 白名单外模型 | `models=["xgboost"]` | `MODEL_NOT_ALLOWED`；`field_path=parameters.models[0]`；`error_code=SCHEMA_INVALID` | 本文 §3.1 |
| NEG-M06-18 | 模型重复 | `models=["svm","svm"]` | `MODEL_DUPLICATED`；`field_path=parameters.models[1]` | 同上 |
| NEG-M06-19 | models 不是数组 | `models="svm"` | `MODELS_NOT_ARRAY`；`keyword=type` | 同上 |
| NEG-M06-20 | models 为空 | `models=[]` | `MODELS_EMPTY`；`keyword=minItems` | 同上 |
| NEG-M06-21 | 保留超参被拒 | `random_forest.n_jobs=4` / `random_forest.random_state=1` | `RESERVED_MODEL_PARAM`；`field_path=parameters.random_forest.n_jobs`；不得静默忽略 | 本文 §3.1 |
| NEG-M06-22 | 未知超参被拒 | `random_forest.foo=1` | `UNKNOWN_MODEL_PARAM`；`keyword=unknown-key` | 同上 |
| NEG-M06-23 | 不做类型强转 | `seed="42"`；`random_forest.n_estimators="100"` | `SEED_INVALID` / `MODEL_PARAM_TYPE`；**不得**转成整数 | 本文 §3.1 |
| NEG-M06-24 | 超参越界 | `svm.C=0`；`random_forest.n_estimators=10000` | `MODEL_PARAM_RANGE`；`keyword=minimum`/`maximum`；`field_path` 精确到参数 | 同上 |
| NEG-M06-25 | bool 冒充整数 | `random_forest.max_depth=true` | `MODEL_PARAM_TYPE`；`True` 不得当 `1` | 同上 |
| NEG-M06-26 | 给未选中模型传参 | `models=["svm"]` + `random_forest.n_estimators=100` | `MODEL_PARAM_FOR_UNSELECTED_MODEL`；`field_path=parameters.random_forest.n_estimators` | 同上 |
| NEG-M06-27 | 需要缩放却关闭 | `models=["logistic_regression"]`，`scale_features=false` | `FEATURE_SCALING_REQUIRED`；`field_path=parameters.scale_features` | 本文 §4.4 |
| NEG-M06-28 | test_size 越界 | `test_size=0.9` / `0.01` | `TEST_SIZE_INVALID`；模板范围 [0.1,0.5] | 本文 §3.1 |
| NEG-M06-29 | target 缺失/空 | 缺 `target`；`target=""` | `PARAM_REQUIRED` / `TARGET_INVALID`；`field_path=parameters.target` | 同上 |
| NEG-M06-30 | 任意代码入口 | 模板类暴露 `eval`/`exec`/`subprocess`；或 `module="a.b:c"` | `assert_model_boundary()` 非空；登记拒绝 `TOOL_NOT_ALLOWLISTED`(403) | 本文 §7；M05 registry |
| NEG-M06-31 | 动态 estimator 路径 | `estimator_symbol="os.system"` / `"module:Class"` | `assert_model_boundary()` 非空；只允许 `sklearn.*` | 同上 |
| NEG-M06-32 | 模型二进制产物 | 往 `ARTIFACT_SPECS` 加 `.pkl` 或 `sha256` 槽位 | 静态检查非空；不得进入产物清单 | 本文 §3.3；OQ-P4-10 |

## C. Split Manifest（`executor/templates/splits.py`）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M06-33 | 六字段缺失 | 从 manifest 删 `semantics` 后重算 | `MANIFEST_FIELDS_MISMATCH`；六字段必须恰好 6 个 | 本文 §4.1 |
| NEG-M06-34 | dataset_hash 被改 | 改 manifest.dataset_hash 后 `verify()` | `DATASET_HASH_MISMATCH`；`checked=dataset_hash` | 本文 §4.3 |
| NEG-M06-35 | fold 分配被改 | 把一行 train 改 test 后 `verify()` | `FOLD_ASSIGNMENT_HASH_MISMATCH`；期望/实际哈希都给出 | 同上 |
| NEG-M06-36 | manifest_hash 被改 | 改 `manifest_hash` 一位 | `MANIFEST_HASH_MISMATCH`；`expected` 为重算值 | 同上 |
| NEG-M06-37 | seed 被改 | `seed+1` 后 `verify()` | `FOLD_ASSIGNMENT_HASH_MISMATCH`（重跑划分不同） | 同上 |
| NEG-M06-38 | row_id_hash 被改 | 改一行 row_id 后 `verify()` | `ROW_ID_HASH_MISMATCH` | 同上 |
| NEG-M06-39 | train/test 重叠 | 桩 splitter 返回同一索引 | `TRAIN_TEST_OVERLAP`；在拟合前拒绝 | 本文 §4.2 |
| NEG-M06-40 | group 泄漏 | 同一 group 同时出现在 train/test | `GROUP_LEAKAGE`；`field_path=semantics.group_key` | 同上 |
| NEG-M06-41 | time 泄漏 | 训练集时间晚于测试集 | `TIME_LEAKAGE`；`field_path=semantics.time_key` | 同上 |
| NEG-M06-42 | group+time 同时启用 | `group_key="g", time_key="t"` | `GROUP_TIME_UNSUPPORTED`；T0 不猜语义 | 同上 |
| NEG-M06-43 | 分层不完整 | 某类只出现在 train | `STRATIFICATION_INCOMPLETE`；`field_path=split.params.stratify_on` | 同上 |
| NEG-M06-44 | test 行数偏离 | 178 行、test_size=0.5 但 splitter 返回 10 行 | `TEST_SIZE_DEVIATION` | 同上 |
| NEG-M06-45 | 算法/版本不支持 | `algorithm="kfold"` / `version="2.0"` | `SPLIT_ALGORITHM_UNSUPPORTED` / `SPLIT_VERSION_UNSUPPORTED` | 本文 §4.1 |
| NEG-M06-46 | dataset_id 非法 | `DatasetView(dataset_id="wine/../x", ...)` | `DATASET_ID_INVALID` | `DatasetView` |
| NEG-M06-47 | row_id 重复 | 两个相同 `row_id` | `ROW_ID_DUPLICATED`；拟合前拒绝 | 同上 |

## D. 模板、产物与冒烟（`classification_benchmark.py` / `smoke_wine.py`）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M06-48 | 模板自报裁决 | `RunReport` 加 `passed=True` / `status="PASS"` | `TypeError`（无该字段）或 `assert_template_boundary()` 非空；不得登记 | 本文 §7 |
| NEG-M06-49 | 模板自报哈希 | `ArtifactSpec` 加 `sha256="0"*64` | `TypeError`；产物声明无哈希/大小槽位 | 同上 |
| NEG-M06-50 | required_check 形态非法 | `check_id="Bad-Check"` | `assert_template_boundary()` 非空；不符合 `^[a-z][a-z0-9_]*$` | 本文 §3.4 |
| NEG-M06-51 | 产物路径逃逸 | `ArtifactSpec(relative_path="../x.json")` | `SCHEMA_INVALID`；`field_path=relative_path`；不得写 `artifacts/` 外 | M05 `_require_relative` |
| NEG-M06-52 | 绑定路径被改 | `DatasetBindingView(relative_path="inputs/../../x.csv")` | `DATASET_BINDING_PATH_INVALID`；模板只读 `inputs/dataset.csv` | 本文 §5.3 |
| NEG-M06-53 | 绑定数据集不在允许集 | `dataset_id="iris"` | `DATASET_NOT_ALLOWED`；`field_path=inputs.dataset_binding.dataset_id` | 同上 |
| NEG-M06-54 | 冒烟超预算 | `random_forest.n_estimators=500` | `SMOKE_BUDGET_EXCEEDED`；`field_path=parameters.random_forest.n_estimators`；不得启动 | 本文 §6 |
| NEG-M06-55 | 冒烟少选模型 | `models=["svm"]` | `SMOKE_MODELS_INCOMPLETE`；冒烟必须三模型全选 | 同上 |
| NEG-M06-56 | 冒烟改评估口径 | `test_size=0.3` | `SMOKE_TEST_SIZE_DRIFT`；冒烟固定 0.2 | 同上 |
| NEG-M06-57 | 冒烟墙钟超 120 | 改 `SMOKE_WALL_TIME_SEC=600` | `assert_smoke_profile()` 非空 | 同上 |
| NEG-M06-58 | 模板读环境凭据/联网 | 模板出现 `os.environ["TOKEN"]`、`requests`、`socket` | 静态检查非空；登记拒绝 `TOOL_NOT_ALLOWLISTED` | 本文 §7 |

## E. 误拒守卫（防止“过度收紧”）

| ID | 守卫目标 | 输入 / 操作 | 期望 | 依据 |
|---|---|---|---|---|
| GUARD-M06-01 | 合法 Wine 参数通过 | 三模型 + 默认超参 + `test_size=0.2` | `parse_params` 返回三模型；`assert_smoke_budget` 不抛 | 本文 §3.1 |
| GUARD-M06-02 | 合法 BCW 参数通过 | 三模型 + 默认值 | `parse_params` 成功；`requires_scaling=True` | 同上 |
| GUARD-M06-03 | 六字段哈希稳定 | 同输入两次 `with_hash` | 两次 `manifest_hash` 相同；六字段顺序不影响 JCS | 本文 §4.1 |
| GUARD-M06-04 | 边界值不误拒 | `test_size=0.1`、`0.5`；`n_estimators=10`、`500` | 不抛；等于边界合法 | 同上 |
| GUARD-M06-05 | 冒烟档案可构造 | `SMOKE_TASK_DRAFT` | `wall_time_sec=120`、`max_workers=1`、三模型全选 | 本文 §6 |

## F. 执行记录模板（落地阶段填写，P4 留空）

| ID | 命令 | 退出码 | 断言到的原因 | 日志路径 | 结论 |
|---|---|---|---|---|---|
| NEG-M06-01 | （待执行） | — | — | — | 未执行 |
| NEG-M06-17 | （待执行） | — | — | — | 未执行 |
| NEG-M06-35 | （待执行） | — | — | — | 未执行 |
| NEG-M06-54 | （待执行） | — | — | — | 未执行 |