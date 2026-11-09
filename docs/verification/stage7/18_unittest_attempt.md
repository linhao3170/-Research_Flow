# 阶段 7 · state_sync 回归测试尝试记录（环境阻塞）

> 结论：**23 项测试被发现，但 43 个 error 全部来自临时目录 ACL 拒绝；没有断言失败。**
> 不把本次运行计为“测试通过”；`state_sync.py validate / render / check` 已单独通过。
> 未修改测试代码、expected result、负例或阈值。

## 1. 命令

```powershell
$py = 'C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe'

# 第一次：系统 Temp
& $py -m unittest discover -s tests -v

# 第二次：把 TEMP/TMP/TMPDIR 指向工作区
$env:TEMP = 'D:\ResearchFlow-project\tmp\unittest-temp'
$env:TMP = $env:TEMP
$env:TMPDIR = $env:TEMP
& $py -m unittest discover -s tests -v
```

两次都是：

```text
Ran 23 tests in ~0.3s
FAILED (errors=43)
```

## 2. 失败形态

- 43 个 error 的 traceback 均包含：
  - `PermissionError: [WinError 5] 拒绝访问`
  - 路径形如 `...\rf_state_sync_<随机>\docs` 或 `...\rf_state_sync_<随机>`
- 失败发生在 `tempfile.TemporaryDirectory()` 创建后的 `Path.mkdir(parents=True)` / `cleanup()`，不是测试断言。
- 第一次使用系统 Temp：`C:\Users\ADMINI~1\AppData\Local\Temp\dsh-gVTluq\rf_state_sync_*`。
- 第二次使用工作区 Temp：`D:\ResearchFlow-project\tmp\unittest-temp\rf_state_sync_*`；仍在子目录创建/清理阶段被拒绝。
- 未修改 `tests/test_state_sync.py`；未修改 `scripts/state_sync.py`。

## 3. 判断

这是 **DSH 文件沙箱 / Windows ACL 对临时目录的写权限限制**，不是 `state_sync.py` 的逻辑回归：

- `state_sync.py validate`：exit 0，任务=3，门禁 PASS=0/8，阻塞=2。
- `state_sync.py render`：exit 0，生成 2 个文件。
- `state_sync.py check`：exit 0，两个生成文件逐字节一致。
- 23 项测试均被 unittest 发现；错误集中在临时目录创建/清理，测试逻辑尚未执行到断言。
- 阶段 4/5 曾在更宽松环境下真实通过 23 项测试（历史日志 `docs/verification/stage4/02_unittest.log`、`stage5/05_validation.log`），但**不能把历史结果当成本次通过**。

## 4. 处理

- 原始输出保留在 [`18_unittest.log`](18_unittest.log)。
- 本文件只解释失败原因，不修改测试、不降低标准。
- 如需本次通过，需在不受该 ACL 限制的终端/沙箱模式运行，或为测试临时目录提供可写 ACL；这需要用户/环境批准，本阶段未做。
- 阶段 7 的验收不以“23 项测试本次通过”为条件；以 `validate/render/check`、只读抽取、来源登记与冲突报告为准。

## 5. 相关

- [`10_state_sync_validate.log`](10_state_sync_validate.log)
- [`11_state_sync_render.log`](11_state_sync_render.log)
- [`12_state_sync_check.log`](12_state_sync_check.log)
- [`../stage4/02_unittest.log`](../stage4/02_unittest.log)
- [`../stage5/05_validation.log`](../stage5/05_validation.log)
