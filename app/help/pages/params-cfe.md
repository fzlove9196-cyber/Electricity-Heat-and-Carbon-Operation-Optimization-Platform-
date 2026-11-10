# 年度 CFE 参数（opt_cfe）

> **目的**：理解年度 CFE 模型字段、匹配规则与约束。
> **前置条件**：已通过「新建年度CFE独立场景」创建场景（或导入自包含 JSON，`model_kind = "opt_cfe"`）。
> **界面入口**：项目页卡片 3「独立年度CFE模式」控件（只写入编辑器）与「完整草稿JSON」。

[▶ 打开此功能：项目与场景](/?view=foundation)

模型严格：**未知字段一律拒绝**，数值不得为 NaN / Inf。

## 顶层字段

| 字段 | 含义 | 单位 | 默认 | 约束 |
|---|---|---|---|---|
| `model_kind` | 固定 `opt_cfe` | — | `opt_cfe` | — |
| `currency` | 币种 `EUR` / `CNY` / `USD`（全模型一致） | — | `EUR` | 三选一 |
| `planning_year` / `weather_year` | 规划年 / 气象年（分列） | 年 | 2025 / 2013 | `start` 年份须等于 `weather_year` |
| `timezone` | 固定 `UTC` | — | `UTC` | — |
| `start` | 起点（UTC 整点） | ISO | `2013-01-01T00:00:00+00:00` | 全年模式须 1 月 1 日 00:00 |
| `dt_hours` | 固定 1 | h | 1 | 15min 拒绝 |
| `horizon_mode` | `year` 全年（8760 / 闰年 8784 点）/ `benchmark`（1–168 点，明确非全年） | — | `year` | 点数不符拒绝，不填充 / 截断 |
| `matching` | `paper_cfe_score` / `hourly_cfe_floor` / `annual_res_share` | — | `paper_cfe_score` | 见下 |
| `target` | 目标比例 x | 0~1 | 1 | [0, 1] |
| `flexibility` | 负荷弹性：(1 − f) × 基线 ≤ 实际 ≤ (1 + f) × 基线 | 0~1 | 0 | [0, 1] |
| `spatial_shifting` | 空间虚拟迁移（虚拟工作，不是跨区输电） | — | false | — |
| `temporal_shifting` | 按源 UTC 日守恒的 DSM | — | false | — |
| `spatial_fee_per_mwh` / `temporal_fee_per_mwh` | 迁移费 | 货币/MWh | 1e-5 | ≥ 0 |
| `max_excess_share` | 超额弃售上限 / 原年负荷 | 0~1 | 0 | [0, 1]；超额不卖电、从 credit 扣除 |
| `storage_boundary` | `cyclic` 全周期闭合 / `empty` | — | `cyclic` | — |
| `sites` | 站点列表 | — | 必填 | 1–8 站，id 不重复 |

## 站点 `sites[i]`

| 字段 | 含义 | 单位 | 约束 |
|---|---|---|---|
| `id` / `region` | 站点 ID / 竞价区 | — | — |
| `load_mw` | 逐时负荷 | MW | 点数一致、有限；≥ 0；总量 > 0；单站峰值 ≤ 10000 |
| `grid_price_per_mwh` | 外网价格 | 货币/MWh | ≥ 0（**不支持负电价**） |
| `grid_cfe` | 外网 CFE 份额 | 0~1 | 0~1；**不是 tCO2/MWh，也不是 LMCE** |
| `import_limit_mw` | 进口上限 | MW | 默认 1e6，≥ 0 |
| `generators[]` | `technology`（wind / solar）、`availability`（0~1 逐时）、`capital_per_mw_year`（≥ 0）、`marginal_per_mwh`（默认 0）、`max_mw`、`region`、`additional` | — | 资产须 `additional = true` 且与站点同一竞价区 |
| `battery` | `capital_power_per_mw_year`、`capital_energy_per_mwh_year`（≥ 0）、`eta_charge` / `eta_discharge`（(0, 1]，默认 0.95）、`loss_per_hour`（[0, 1)）、`discharge_cost_internal_per_mwh`、`max_power_mw` / `max_energy_mwh` | — | — |

## 三种匹配规则

| 规则 | 约束 | 要点 |
|---|---|---|
| `paper_cfe_score` | Σ_t credit_t ≥ x · Σ_t 负荷_t | **年度累计**，不是每小时 ≥ x |
| `hourly_cfe_floor` | 每小时 credit_t ≥ x · 负荷_t | 更强的逐时下限 |
| `annual_res_share` | Σ 合格风光发电 = x · Σ 用电 | **年份额 ≠ 24/7 逐时匹配**，可能夜间购灰电 |

credit_t = 负荷_t − (1 − grid_cfe_t) × 进口_t。年份额达标不代表每小时都清洁；需要逐时保障请选 `hourly_cfe_floor`。

## 任务约束

版本化任务只允许 `cost` 目标、必须关闭交流校核；页面会自动设置软限时 600 秒。不支持日资源 / 设备绑定、签出到拓扑、15min、三级运行。
