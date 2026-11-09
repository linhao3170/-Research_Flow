# Stage 5 — Skills 发现机制核实

> 核实时间：2026-11-08 11:45–11:53（Asia/Shanghai）
> 结论：当前 DSH **支持项目级 `.agents/skills`**；无需改配置，无需改用 `.dsh/skills` 或全局目录。
> 证据等级：本文件中的路径与行号来自实际安装文件；catalog 变化来自本会话实际观察。

## 1. 实际运行版本

| 项 | 值 | 证据 |
|---|---|---|
| 桌面壳 | `@deepseek-ai/dsh-desktop@0.2.2-rc.1` | `D:\deepseek_harness1\resources\app.asar` 内根 `package.json` |
| 内置 runtime | `@deepseek-ai/dsh-desktop-runtime@0.2.2-rc.1` | app.asar 内 `dsh/package.json` |
| 构建 commit | `c59d10aff167ad7eefead4b3a9082fb57c8fbfe8` | app.asar 根 `package.json` |
| 会话 Web URL | `http://127.0.0.1:63180` | 当前 runtime context |

注意：`C:\Users\Administrator\.dsh\profiles\node_modules\@deepseek-ai\dsh` 的版本是 `0.1.0-rc.8`，不是桌面壳实际使用的版本。核实扫描路径时以 app.asar 内的 `0.2.2-rc.1` 源码为准，避免把旧包的行为当成当前行为。

## 2. Provider：扫描路径

包：`@deepseek-ai/dsh-skill-filesystem@0.2.2-rc.1`

app.asar 内条目：

```text
dsh/node_modules/@deepseek-ai/dsh-skill-filesystem/lib/index.js
dsh/node_modules/@deepseek-ai/dsh-skill-filesystem/README.md
dsh/node_modules/@deepseek-ai/dsh-skill-filesystem/package.json
```

`lib/index.js` 第 160–190 行 `roots(cwd)`：

```js
const projectRoot = await findProjectRoot(resolve(cwd), optionalFileSystem(this.ctx));
roots.push({
  path: join(projectRoot, ".dsh/skills"),
  source: "project-dsh",
  rank: PROJECT_DSH_RANK,
  projectRoot
}, {
  path: join(projectRoot, ".agents/skills"),
  source: "project-agents",
  rank: PROJECT_AGENTS_RANK,
  projectRoot
});
```

同包 `README.md` 第 48–54 行给出同样的根顺序：

| Rank | Source | Path |
|---|---|---|
| 100 | `project-dsh` | `<projectRoot>/.dsh/skills` |
| 200 | `project-agents` | `<projectRoot>/.agents/skills` |
| 300 | `custom` | `Config.customSkillDirs` |
| 400 | `user-dsh` | `<dshHome>/skills` |
| 500 | `user-agents` | `<agentsHome>/skills` |

项目根判定：最近的含 `.git` 的祖先目录（README 第 56 行）。本项目 `D:\ResearchFlow-project\.git` 存在，所以 project root 是 `D:\ResearchFlow-project`，项目级路径解析为：

```text
D:\ResearchFlow-project\.agents\skills
```

## 3. Registry

包：`@deepseek-ai/dsh-skill@0.2.2-rc.1`

- README 第 12 行：registry 合并所有 provider，按需加载选中 Skill 的完整说明。
- README 第 28 行：provider 与 consumer 都通过 `ctx.skills` 交互；`dsh-skill` 本身不含 Skill 内容。
- 因此 `skill-filesystem` 只负责发现/读取，catalog 与加载由 consumer 负责。

## 4. Consumer

包：`@deepseek-ai/dsh-tool-skill@0.2.2-rc.1`

- README 第 12 行：`skill` 工具可见时，model-invocable 的 Skill 会在首个请求前形成 durable catalog；加载工具返回完整说明；entry/visibility 变化会追加 replacement catalog。
- README 第 28 行：发现、catalog 更新与显式调用使用 Session 的当前工作目录。
- README 第 30 行：该插件需要 `ctx.agents`、`ctx.tools`、`ctx.skills`。

本会话实际结果：

1. 创建 `researchflow-onboarding` 后，收到一次 catalog replacement，新增该名称；原有 9 个 Skill 仍在。
2. 再创建 4 个后，收到第二次 replacement，catalog 共 14 个 Skill。
3. 创建最后 4 个后，收到第三次 replacement，catalog 共 18 个 Skill，其中 9 个为 `researchflow-*`。
4. 未重启 Harness，未改配置，未重新打开会话。

结论：目录变更被 provider 观察，consumer 追加 replacement catalog；项目级 `.agents/skills` 在实际会话中生效。

## 5. 挂载声明（辅助证据）

当前 profile 的 `standard` preset 配置中仍有 provider/consumer 两行：

`C:\Users\Administrator\.dsh\profiles\node_modules\@deepseek-ai\dsh\config\agent-presets\standard\agent.cordis.yml`

```yaml
# line 83-87
- id: skill-filesystem
  name: '@deepseek-ai/dsh-skill-filesystem'

- id: tool-skill
  name: '@deepseek-ai/dsh-tool-skill'
```

说明：该 profile 包是 `0.1.0-rc.8`，与桌面壳 `0.2.2-rc.1` 不是同一份代码。它只能证明“当前 profile 配置声明了这两行”，不能单独证明运行版本行为；运行版本行为以第 2–4 节的 app.asar 源码和实际 catalog/工具调用为准。

## 6. 目录决策

- 统一使用：`D:\ResearchFlow-project\.agents\skills\`
- 未创建：`D:\ResearchFlow-project\.dsh\skills\`
- 未创建：`C:\Users\Administrator\.dsh\skills\researchflow-*`
- 未创建：`C:\Users\Administrator\.agents\skills\researchflow-*`
- 未修改：DSH Profile、preset、全局配置、`cordis.patch.yml`

未发现同名 Skill 重复；项目级路径是当前版本明确支持的默认根，不需要“改配置 / 换目录”二选一。

## 7. 限制与待核实

- 本次只验证“新增目录触发 catalog 刷新”，未删除或改名已加载 Skill 做破坏性测试。
- `references/` 内的文件变更不触发 catalog 刷新（Consumer 文档说明）；本次未单独测试。
- 未把 `.agents/skills` 复制到其他根；如未来需要跨项目共享，应另立 ADR，而不是复制同名 Skill。
