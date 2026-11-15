# BLK-003 workspace-write pytest failure (observed 2026-11-12)

- 解释器：`D:\ResearchFlow-project\.venv\Scripts\python.exe`（3.11.16 / 64bit）
- 策略：workspace-write
- 命令：

```powershell
& .venv/Scripts/python.exe -m pytest tests/test_jcs.py tests/test_persistence_migrations.py -q -p no:cacheprovider --basetemp=runtime/pytest-tmp
```

- 结果：`6 passed, 6 errors`，exit 1。
- 失败阶段：全部在 pytest `tmp_path` fixture 的 setup 阶段，未进入测试断言。
- 典型错误：

```text
PermissionError: [WinError 5] 拒绝访问。:
'D:\ResearchFlow-project\runtime\pytest-tmp\test_fresh_db_creates_the_seve19'
...
OSError: could not create numbered dir with prefix ... after 20 tries
```

- 判断：与 `BLK-003` 描述一致——workspace-write 下运行期新建子目录未继承写入授权；不是测试断言失败。
- 处理：`BLK-003` 维持 `OPEN`。随后按用户已确认的 11B 口径，在 `danger-full-access` 下执行补充测试；full-access 结果只作补充证据，**不写成 workspace-write 通过**。
- 补充证据：`pytest_targeted.log`（87 passed）、`pytest_full.log`（217 passed）。