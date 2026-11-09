# 阶段 7 · DOCX 页码读取尝试记录

> 结论：**未取得可信页码**；未修改 DOCX；未安装任何软件。
> 时间：2026-11-08 12:43–12:47（Asia/Shanghai）

## 1. 为什么尝试

策划书全文抽取已完成 754 段落 / 80 表格，但 DOCX 没有目录字段和缓存分页：

- `docProps/app.xml` 的 `Pages=1`、`Words=0`、`Characters=0` 是 `python-docx` 生成残留，不能当页数；
- 文档内 `lastRenderedPageBreak` = 0；
- 只有 30 个手工分页符，不能推出每章真实页码。

为给知识文档提供“页码”引用，尝试用本机 Microsoft Word 只读分页。

## 2. 环境

| 项 | 值 |
|---|---|
| Word | `C:\Program Files\Microsoft Office\Office16\WINWORD.EXE` |
| 脚本 | `docs/verification/stage7/docx_page_map.ps1` |
| 方式 | Word COM `Documents.Open(..., ReadOnly=$true)`；`ComputeStatistics(2)` 取页数；`Range.Information(3)` 取标题页码 |
| 文档 | 根目录 DOCX；只读打开；不保存 |

## 3. 结果

- 第一次通过 `pwsh -File` 调用失败：当前环境没有 `pwsh` 命令（只有 Windows PowerShell）。
- 第二次通过 `powershell -ExecutionPolicy Bypass -File` 调用：进程超过 180 秒未返回，Word 进程存在但无可见窗口；未输出 `WORD_STARTED`，判断为 Word 启动/自动化阶段阻塞。
- 终止 Word 进程后重试简化调用：`New-Object -ComObject Word.Application` 仍阻塞，未打开文档。
- 未修改 DOCX；未安装 LibreOffice/WPS；未改注册表/系统配置。

日志：

- `06_page_map.log`（失败调用输出）
- 无成功页数输出。

## 4. 处理

- 不估算页码，不使用 `Pages=1`。
- 所有知识文档使用 `§章节 / P#### / TABLE ##` 锚点：
  - `P####` → `02_docx_body.txt`
  - `TABLE ##` → `05_docx_tables.txt`
- 如后续需要真实页码，在有可用 Word/LibreOffice 的环境重新分页；不得把估算值写成原文页码。

## 5. 复现命令（只读）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File docs/verification/stage7/docx_page_map.ps1
```

预期：若 Word 自动化可用，输出 `06_docx_page_map.txt`；当前环境未成功。
