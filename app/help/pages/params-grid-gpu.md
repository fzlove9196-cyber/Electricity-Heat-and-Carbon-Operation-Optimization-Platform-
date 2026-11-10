# 电网反馈与 GPU 独立模式参数

> **目的**：理解 `opt_grid_feedback` 与 `opt_gpu` 两种独立模式的字段与约束。
> **前置条件**：已通过项目页对应按钮创建独立场景。
> **界面入口**：项目页卡片 3「独立电网反馈实验」「离散GPU独立模式」控件与完整草稿 JSON。两种模型均严格拒绝未知字段与 NaN / Inf。

[▶ 打开此功能：项目与场景](/?view=foundation)

## 电网反馈 `opt_grid_feedback`

| 字段 | 含义 | 单位 | 默认 | 约束 |
|---|---|---|---|---|
| `horizon_mode` | `benchmark` / `original_data_subset` | — | 必填 | 子集须保留原 8784 小时索引（不删闰日） |
| `start` | 起点（UTC 整点） | ISO | 必填 | 1–168 小时 |
| `dt_hours` | 固定 1 | h | 1 | — |
| `buses[]` | `id`、`region`、`background_load_mw`（逐时，≥ 0） | MW | — | 网络须连通，含 `slack_bus` |
| `lines[]` | `from_bus`、`to_bus`、`b_mw_per_rad`（> 0）、`limit_mw`（> 0） | MW/rad、MW | — | 端点有效且不同 |
| `generators[]` | `bus`、`available_mw`（逐时，≥ pmin）、`pmin_mw`（0）、`cost_usd_mwh`、`operational_tco2_mwh`、`lifecycle_extra_tco2_mwh`（0）、`low_carbon` | — | — | ≥ 0 |
| `sites[]` | `bus`、`baseline_work_mw`（逐时）、`pue`（≥ 1，默认 1）、`capacity_work_mw`（> 0） | MW | — | 基线 ≤ 容量 |
| `max_abs_angle_rad` | 相角上限 | rad | π | (0, π] |
| `flexibility` | 站点工作 ± 比例 | — | 0.2 | [0, 1] |
| `trust_fraction_per_iteration` | 每次迭代信赖步长 | — | 0.2 | [0, 1] |
| `signals` / `selected_signal` | 参与比较的信号 / 主展示信号（`lmce`/`lmp`/`average`/`excess`） | — | 全部 / `lmce` | 主信号须在列表中 |
| `max_iterations` | 最多迭代 | 次 | 3 | 1–8 |
| `max_backtracks` | 回溯次数 | 次 | 4 | 0–8 |
| `convergence_mw` | 收敛阈值 | MW | 1e-6 | > 0 |
| `fd_step_mw` | 有限差分步长 | MW | 0.01 | (0, 10] |
| `signal_method` | `forward_fd`（同时审计负向 / 半步 / 活跃基）/ `validated_basis` | — | `forward_fd` | — |
| `unstable_signal_policy` | `fail` 显式失败 / `allow_directional` 接受方向导数实验 | — | `fail` | — |
| `iso_carbon_price_usd_t` | ISO 出清碳价（0 = 纯经济出清） | USD/t | 0 | ≥ 0 |
| `require_convergence` | 任一信号非固定点则任务 failed | — | false | — |

## GPU 离散控制 `opt_gpu`

| 字段 | 含义 | 单位 | 默认 | 约束 |
|---|---|---|---|---|
| `start` | 起点（带时区，对齐时间槽） | ISO | `2025-05-03T07:00:00+08:00` | — |
| `dt_hours` | 时间步 | h | 1 | 仅 1 或 0.25 |
| `n_steps` | 步数 | — | 必填 | 1–96 |
| `gpus[]` | `id`、`idle_power_w`（≥ 0，逐卡） | W | — | id 唯一 |
| `price_usd_kwh` | 逐时电价 | USD/kWh | — | 长度 = n_steps，≥ 0 |
| `power_limit_kw` | 逐时功率预算（可为空值） | kW | — | 长度 = n_steps，≥ 0 |
| `non_gpu_fixed_kw` | 固定非 GPU 功率 | kW | 0 | ≥ 0 |
| `policy` | `energy_cost` / `fair_minimax` / `author_dvfs_headroom_discrete` | — | `energy_cost` | 三选一 |
| `sla_window_semantics` | `paper_3_to_6_hours`（窗口 3–6 h）/ `synthetic_short_window` | — | `paper_3_to_6_hours` | — |
| `mip_relative_gap` | MIP 相对 gap | — | 0 | [0, 0.01] |
| `lex_tolerance` | 字典序公差 | — | 1e-7 | [0, 1e-3] |
| `require_validation_feasible` | 留出验证不满足则任务 failed | — | true | — |

任务 `jobs[i]`：

| 字段 | 含义 | 约束 |
|---|---|---|
| `gpu_ids` | 固定 gang | 非空、互不重叠、不共享 / 不 resize |
| `actions[]` | `cap_w`（> 0）、`power_w_per_gpu`（≥ 0）、`normalized_rate`（(0, 2]）、可选 `validation_*` | id 唯一 |
| `reference_action` | 参考动作 | `normalized_rate` 必须为 1 |
| `baseline_rate` | 逐时基线吞吐（0~1） | Σ × Δt = `required_work_h`；只在生命周期内为正 |
| `required_work_h` | 工作量（参考 gang 等效小时） | ≥ 1e-5 |
| `release_h` / `deadline_h` | 释放 / 截止 | 0 ≤ release < deadline ≤ 时域，对齐时间步 |
| `flex` | Flex 等级 0–3（吞吐下限 100/90/75/50%） | 整数 0–3 |
| `sla_windows[]` | `start_h` / `end_h` | 在生命周期内、对齐；paper 语义下长度 3–6 h；窗口基线不能为 0 |
| `allow_pause` / `pause_power_w_per_gpu` | 允许暂停 / 暂停功率 | 允许暂停时功率必填（不从 DVFS 猜测） |
