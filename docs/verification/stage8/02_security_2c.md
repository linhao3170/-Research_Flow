# 02 阶段 2C 三项安全配置运行态

## 1. 当前值（只读核对）

| 配置 | 当前值 | 证据 |
|---|---|---|
| `session-log-deepseek` | `enabled: false` | `02_security_2c.log` 第 27 行起 |
| `session-telemetry-otel` | `mode: DISABLED` | `02_security_2c.log` 第 31 行起 |
| `web-fetch-http` | `disabled: true` | `02_security_2c.log` 第 35 行起 |

- `cordis.patch.yml`：1,462 字节；SHA256 `6FF6F1FCB6CAE8F732F221710D9E4FFD5C6DF1E26F6EFDADE75F4B9B536159E1`，与阶段 6 写入后哈希一致。
- 阶段 6 备份：`cordis.patch.yml.bak-20261108-stage6`，1,200 字节；SHA256 `664CE561366D925DDA1AE382528565218ABB20072211DD36562F4D3CB894FFD8`；未删除。
- 阶段 6 的逐字节非回归核对：新文件前 1,200 字节与备份完全一致（`docs/verification/stage6/07_post_write_verify.log` 第 11 行 `prefix_1200_equal=True`）。

## 2. 与 2D 结论的一致性

- 项目内**没有独立的阶段 2D 报告目录**，**2D 未单独执行**；本次没有重新做 2C 全量调查。
- 引用阶段 6 的 2C 非回归核对（`08_apply_result.md` §4）与当前配置值：三项均未改动，静态配置一致。
- **运行态未观测**：本阶段没有实际触发日志写入、遥测上报或 web_fetch 请求来观察三项控制是否生效；只确认了配置值与阶段 6 记录一致。
- 该缺口已列入 [`docs/state/G0_DECISION_LIST.md`](../../state/G0_DECISION_LIST.md) 的“G0 残留风险清单”。

## 3. 判定

**静态确认 PASS / 运行态未观测**：三项 2C 配置当前值与阶段 6 记录一致，备份完整，Profile 未被修改；但 2D 未单独执行，不能把“配置存在”写成“运行态已验证”。

