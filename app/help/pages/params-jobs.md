# 作业与截止参数

> **目的**：用任务级作业替代聚合批处理模型，配置释放 / 截止 / 能量 / 功率 / 站点 / 时延，以及整数连续任务。
> **前置条件**：`jobs` 非空即启用（替代数据中心 `batch_mwh` 聚合模型）。
> **界面入口**：② 输入参数「时间与任务模式」「数据中心与算力负荷 → 任务级作业」；JSON `jobs[]`；对话「生成 N 个任务」。

[▶ 打开此功能：② 输入参数](/?view=chat&step=params)

## 字段 `jobs[i]`

| 字段 | 含义 | 单位 | 默认 | 约束 / 不合理时 |
|---|---|---|---|---|
| `id` | 任务 ID | — | 必填 | 重复：拒绝 |
| `dc` | 来源（归属）数据中心 | — | 必填 | 不存在：拒绝 |
| `release` | 释放时刻（物理小时） | h | 0 | `0 ≤ release < deadline ≤ 24`，并对齐时间步，否则拒绝 |
| `deadline` | 截止时刻（不含） | h | 24 | 同上 |
| `energy_mwh` | IT 能量 | MWh | 必填 | ≥ 0；能量型须 ≤ `max_mw` × (deadline − release)，否则拒绝并提示「提高 max_mw 或放宽截止时间」 |
| `max_mw` | 单时段最大 IT 功率（连续任务为固定功率） | MW | 必填 | > 0，否则拒绝 |
| `allowed_dcs` | 允许运行的数据中心；空 = 全部（仍受链路 / 时延约束） | — | 空 | 含不存在的 DC：拒绝 |
| `max_latency_ms` | 时延敏感：迁移链路时延不得超过 | ms | 空（不敏感） | — |
| `value_cny_mwh` | 福利出清的接纳报价 | 元/MWh | 空 | ≥ 0；`welfare` 目标时每个任务必填 |
| `execution_mode` | `energy` 可分能量 / `continuous` 整数连续 | — | `energy` | 二选一 |
| `duration_h` | 连续任务总工时 | h | 空 | continuous 必须 > 0 且对齐时间步；`energy_mwh = duration_h × max_mw` |
| `initial_progress_h` | 历史已完成进度 | h | 0 | `0 ≤ 值 < duration_h`；非 0 时 `release` 必须为 0 |
| `initial_dc` | 初始运行站点 | — | 空 | 须存在 |
| `allow_restart` | 允许取消后从零重启 | — | false | — |
| `restart_delay_h` | 重启等待 | h | 0 | ≥ 0，对齐时间步 |
| `cancellation_penalty_cny` | 每次取消费用 | 元 | 0 | ≥ 0 |
| `required` | 必须完成（硬约束） | — | false | — |
| `source` | 来源说明 | — | `synthetic` | — |

能量型任务**不得**带 `initial_progress_h` / `allow_restart` / `duration_h` / `required`，否则拒绝。

## 相关场景字段

| 字段 | 含义 | 默认 | 合理范围 |
|---|---|---|---|
| `unserved_penalty_cny_mwh` | 截止前未完成的 IT 能量惩罚（cost 模式） | 20000 元/MWh | [0, 1e6] |
| `links`、`mig_*` | 迁移链路与上限 | 见 [数据中心参数](/help/params-datacenter) | — |

详细用法与取消损失口径见 [整数连续作业](/help/integer-jobs)。
