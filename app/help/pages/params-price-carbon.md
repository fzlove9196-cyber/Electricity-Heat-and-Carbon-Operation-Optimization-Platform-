# 电价、碳核算、VCC 与需求响应参数

> **目的**：配置电价、碳强度与核算口径、目标模式、绿电约束、VCC 与需求响应事件。
> **前置条件**：无。
> **界面入口**：② 输入参数「电价与碳」「碳」「需求响应」「约束」组；资源库绑定电价 / 碳；JSON。

[▶ 打开此功能：② 输入参数](/?view=chat&step=params)

## 电价

| 字段 | 含义 | 单位 | 默认 | 合理范围 / 约束 |
|---|---|---|---|---|
| `price_cny_kwh` | 购电电度电价曲线 | 元/kWh | 合成峰谷：0–6 时 0.30、7–9 时 0.65、10–11 时 1.05、12–16 时 0.65、17–21 时 1.05、22–23 时 0.30 | 点数 24/96（否则拒绝）；参数表 [0, 5] |
| `price_kind` | 曲线类型标签（`peak_valley` / `flat` 等） | — | `peak_valley` | — |
| `grid_markup_cny_mwh` | 购电附加（输配 / 附加费） | 元/MWh | 50 | [0, 2000] |

## 碳强度与核算口径

| 字段 | 含义 | 单位 | 默认 | 约束 / 不合理时 |
|---|---|---|---|---|
| `carbon_accounting` | `location`：数据中心用电 × 所在区域碳强度（运行位置基准）；`generation`：发电侧排放（外网区域曲线 + 本地机组排放因子） | — | `location` | 二选一 |
| `carbon_basis` | `average` 平均 / `marginal` 边际（需提供边际曲线） | — | `average` | 二选一 |
| `carbon_factor` | 电网平均排放因子（缺省曲线日均值），生态环境部 2023 全国因子 | tCO2/MWh | 0.5306 | 参数表 [0, 2] |
| `carbon_shape` | 缺省曲线的合成日内形状 `solar_dip` / `flat` | — | `solar_dip` | 合成 |
| `carbon_profiles` | 区域 → 逐时平均碳强度 | tCO2/MWh | 空 | 点数匹配且 ≥ 0，否则拒绝 |
| `carbon_marginal_profiles` | 区域 → 逐时边际碳强度 | tCO2/MWh | 空 | 点数匹配 |
| `bus_region` | 母线 → 区域名，缺省 national | — | 空 | — |
| `gen_emission_t_mwh` | 本地机组排放因子（case14，合成） | tCO2/MWh | [0.85, 0.85, 0.45, 0.45] | — |
| `carbon_price_cny_t` | 碳价 λ | 元/tCO2 | 100 | ≥ 0（负值拒绝）；参数表 [0, 2000] |
| `carbon_weight` | 碳权重 w：目标 = 成本 + w·λ·排放；0 = 纯成本 | — | 0 | ≥ 0（负值拒绝）；参数表 [0, 100] |

说明：位置口径未扣除本地光伏（保守）；有余热供热时总碳 = 电力碳 − 替代锅炉排放因子 × 终端供热量。

### 生命周期分账（研究可选，不改变优化目标）

| 字段 | 含义 | 默认 | 约束 |
|---|---|---|---|
| `lifecycle_enabled` | 开启生命周期分账（与运行碳分列） | false | — |
| `lifecycle_embodied_t_per_year` | 年度建设隐含碳 | 0 t/年 | ≥ 0 |
| `lifecycle_year_hours` | 年小时数 | 8760 | ≥ 24 |
| `lifecycle_counterfactual` | `none` / `jobs_origin_uniform`（净避排反事实） | `none` | `jobs_origin_uniform` 要求无常规负荷 / 储能 / 供热的 custom 增量模型、identity + constant_pue，否则拒绝 |

## 目标模式与绿电约束

| 字段 | 含义 | 默认 | 约束 |
|---|---|---|---|
| `objective_mode` | `cost` / `welfare`（版本化任务会按所选目标覆盖） | `cost` | welfare 需任务报价且 `carbon_weight = 0` |
| `min_green_share` | 绿电占比下限：外网购电 ≤ (1 − s) × 数据中心用电；空 = 不启用 | 空 | [0, 1]，否则拒绝 |
| `green_shortfall_penalty_cny_mwh` | 绿电缺口惩罚（软约束）；空 = 硬约束（低风日可能不可行） | 空 | — |
| `pv_curtail_penalty` | 弃风弃光惩罚 | 500 元/MWh | [0, 1e4] |

## VCC 虚拟容量曲线

| 字段 | 含义 | 默认 | 约束 |
|---|---|---|---|
| `vcc_mode` | `off` / `carbon` / `price` / `weighted`（灵活负荷容量整形） | `off` | 15min 或连续任务时必须 `off`，否则拒绝 |
| `vcc_stage` | `joint` 与 DC-OPF 同层 / `day_ahead` 先解 VCC 再约束批处理 | `joint` | — |
| `vcc_carbon_weight` / `vcc_price_weight` | weighted 模式权重 | 1 / 1 | 参数表 [0, 100] |
| `vcc_preserve_daily` | Σ Cap_vcc ≥ 日灵活需求 | true | — |
| `vcc_objective_scale` | 整形项乘子 | 1 | ≥ 0 |
| `vcc_cap_spread` | day_ahead Cap 与残差比例混合 | 0 | [0, 1] |

## 需求响应 `dr_events[i]`

| 字段 | 含义 | 单位 | 默认 | 约束 |
|---|---|---|---|---|
| `name` | 事件名 | — | `DR` | — |
| `start` / `end` | 开始 / 结束时刻（不含 end） | h | 18 / 21 | `0 ≤ start < end ≤ 24`，对齐时间步，否则拒绝 |
| `kind` | `reduce` 削峰 / `increase` 填谷 | — | `reduce` | 二选一 |
| `request_mw` | 申报 / 要求响应量 | MW | 30 | 参数表 [0, 1e4] |
| `price_cny_mwh` | 补偿价格（按实际响应量） | 元/MWh | 1500 | [0, 1e4] |
| `baseline_method` | `plan` 无 DR 优化计划 / `bau` 无协同基线 / `given` 给定 `baseline_mw` | — | `plan` | given 时 `baseline_mw` 点数须匹配 |
| `dcs` / `storages` | 参与 DC / 计入响应的表后储能；空 = 全部 DC | — | 空 | — |
| `max_mw` | 可响应容量上限 | MW | 空（不限） | — |
| `mandatory` | 必须达到 `request_mw`（硬约束） | — | false | — |
| `shortfall_penalty_cny_mwh` | 未达申报量考核 | 元/MWh | 0 | [0, 1e5] |

> 场景内 DR 是日调度中的响应建模；交易沙盘的 DR 基线另有方法，且**不是结算级**。
