# 整数连续作业：截止、取消与重启

> **目的**：为不可切分、需连续运行的作业建模（如训练任务），并如实记录取消重启造成的进度损失。
> **前置条件**：场景使用任务级作业 `jobs`（非空时替代数据中心聚合批处理模型）。
> **界面入口**：项目页草稿 JSON 的 `jobs`；或会话场景 JSON。状态：【部分实现】（日窗口已实现；原论文 144 h 滚动未复现）。

[▶ 打开此功能：项目与场景](/?view=foundation)

## 两种执行方式

| `execution_mode` | 模型 | 特点 |
|---|---|---|
| `energy`（默认） | LP | 能量可切分，可多站同时运行，单时段功率 ≤ `max_mw` |
| `continuous` | 二进制状态流 MILP（不是 LP 四舍五入） | 固定不可分功率、同站连续运行、截止期、可取消重启 |

## 配置连续作业

在 `jobs` 中为每个任务显式设置：

```json
{"id": "train-1", "dc": "DC_A", "release": 0, "deadline": 24,
 "execution_mode": "continuous", "duration_h": 6, "max_mw": 2, "energy_mwh": 12,
 "required": true, "allow_restart": true, "restart_delay_h": 1,
 "cancellation_penalty_cny": 0, "initial_progress_h": 0}
```

规则（违反即校验拒绝）：

- `duration_h` 必须 > 0，且 `energy_mwh = duration_h × max_mw`。
- `0 ≤ initial_progress_h < duration_h`；带初始进度的任务必须 `release = 0`；可用 `initial_dc` 指定初始运行站点（须存在）。
- `restart_delay_h ≥ 0`；`duration_h`、`initial_progress_h`、`restart_delay_h` 必须对齐时间步。
- `0 ≤ release < deadline ≤ 24`。
- 能量型任务**不能**携带 `initial_progress_h`、`allow_restart`、`duration_h`、`required`，否则报错「请显式execution_mode=continuous」。
- 连续任务时 `lifecycle_counterfactual` 必须为 `none`。

## 取消与重启

- 允许重启时，取消会**丢弃全部已执行进度**（无检查点、无无损暂停），可设重启等待与取消费。
- 账本守恒：初始进度能量 + 本轮执行能量 = 完成有效能量（goodput）+ 取消损失 + 截止时未完成。
- 连续窗口不足属于真实不可行，任务记为 failed，不会伪装为零成本成功。
- MILP 公开界 / gap / 状态，不提供 LP 对偶。

## 限制

整数连续任务目前**不支持**三级运行、VCC、交易沙盘与年度路径（显式拒绝）。
