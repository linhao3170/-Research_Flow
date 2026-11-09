# 会话交接模板

> 使用方式：复制到 `docs/SESSION_HANDOFF.md` 的“交接记录”顶部；只写已确认事实。
> 不自动 commit；不删除旧记录。

## 1. 模板

```markdown
### YYYY-MM-DD · 阶段 X · <主题>

- 本次完成：
  - <可核对的结果>
- 未完成：
  - <明确未做/未测>
- 修改文件：
  - <路径>
- 实际测试命令与结果：

  ```powershell
  $py = 'C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe'
  & $py <命令>
  # exit code；测试数；日志路径
  ```

- 当前分支与 commit：
  - 分支：<...>
  - commit 数：<...>
  - last_verified_commit：<hash 或 null>
  - 是否 commit：否/是
- 已知问题/风险：
  - <...>
- 下一步（最多 3 项）：
  1. <...>
- 待用户确认：
  - <...>
- 证据目录：
  - <路径>
```

## 2. 状态同步命令

```powershell
$py = 'C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe'
& $py scripts/state_sync.py validate
& $py scripts/state_sync.py render
& $py scripts/state_sync.py check
```

三条都 exit 0 才算同步完成；`render` 成功后才可称 Markdown 已更新。

## 3. 信息分类

| 信息 | 写入位置 |
|---|---|
| 稳定项目事实 | `docs/memory/<topic>.md` |
| 当前阶段/任务/门禁/阻塞 | `docs/state/project_state.json` |
| 技术决策 | `docs/ADR/` |
| 本次变更/验证 | `docs/CHANGELOG_DEV.md` |
| 会话交接 | `docs/SESSION_HANDOFF.md` |
| 临时聊天 | 不写入项目事实 |

## 4. 完成前检查

- [ ] 测试真实运行，有命令/退出码/日志
- [ ] 未测项标“未测”
- [ ] `last_verified_commit` 只在真实 commit 后更新
- [ ] 未完成任务未标 DONE
- [ ] 门禁未提前 PASS
- [ ] JSON 与生成 Markdown 一致
- [ ] CHANGELOG 只追加
- [ ] 未 commit（除非用户明确批准）
- [ ] 无秘密/凭据/Session 标识
- [ ] 交接可由文件与命令核对

## 5. 失败处理

- `validate` 失败：修 JSON，不手改生成文件。
- `check` 失败：重新 `render`；若仍失败，查 CRLF/编码/手工编辑。
- 测试失败：记录原始失败，不修改 expected/阈值。
- Git 身份未配置：不 commit，报告 BLK-001。
