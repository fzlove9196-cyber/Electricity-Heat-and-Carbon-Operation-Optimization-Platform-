# 电源与网络参数（风光 / 火电 / 外网 / 线路）

> **目的**：配置风光、本地机组、柴发、外部电网与网络结构。
> **前置条件**：自定义网络需 `network_case = "custom"` 并提供 `network`。
> **界面入口**：② 输入参数「网络」「能源配置」「柴发/备用电源」组；拓扑编辑器；配置构建器「电源」。

[▶ 打开此功能：模型拓扑 / 能流](/?view=model)

## 网络模型

| 字段 | 含义 | 默认 | 约束 |
|---|---|---|---|
| `network_case` | `case14`（IEEE14 标准算例）/ `custom`（等值自定义网络） | `case14` | `custom` 时必须有 `network`，否则拒绝 |
| `network_domain` | `physical`（相角 ±π）/ `paper_abstract`（论文抽象域，仅取消相角箱） | `physical` | `paper_abstract` 必须 custom 网络且关闭交流校核 |
| `load_scale` | 常规负荷曲线整体倍数 | 1.0 | 参数表 [0, 5] |
| `gen_cost` | IEEE14 四台机组边际成本（case14） | [420, 480, 600, 650] 元/MWh | 参数表 [0, 5000] |
| `gen_min_share` | 机组最小出力比例（case14） | 0.25 | [0, 1] |

## 风光 `pv[i]`

| 字段 | 含义 | 单位 | 默认 | 约束 / 不合理时 |
|---|---|---|---|---|
| `bus` | 接入母线 | — | 必填 | 越界：拒绝 |
| `cap_mw` | 装机 | MW | 必填 | < 0：拒绝 |
| `profile` | 逐时出力系数（可用出力 / 装机） | p.u. | 缺省为合成正弦光伏曲线 | 点数 24/96，每点 0 ~ 1，否则拒绝 |
| `kind` | `wind` / `pv`；缺省按曲线判断（夜间有出力 → 风电） | — | 空 | — |
| `ppa_price_cny_kwh` | PPA / 直供结算价 | 元/kWh | 空 | 参数表 [0, 3] |
| `ppa_take_or_pay` | 照付不议：按可发电量结算（弃电不省钱） | — | true | — |
| `lifecycle_tco2e_mwh` / `lifecycle_tco2e_mwh_profile` | 生命周期强度（不改变运行碳） | tCO2e/MWh | 0 / 空 | ≥ 0、有限 |

弃风弃光惩罚 `pv_curtail_penalty`：默认 500 元/MWh（引导消纳的虚拟成本），参数表 [0, 1e4]。

## 自定义网络 `network`

| 对象 | 主要字段（单位，默认） | 约束 / 不合理时 |
|---|---|---|
| 母线 `buses[]` | `name`、`vn_kv`（kV，必填） | `vn_kv` ≤ 0：拒绝 |
| 线路 `lines[]` | `from_bus`、`to_bus`、`length_km`（必填）、`r_ohm_per_km`（0.03）、`x_ohm_per_km`（0.30）、`c_nf_per_km`（12）、`rating_mva`（必填，每回）、`parallel`（1）、`service_fee_cny_mwh`（0，≥0） | 端点越界 / 同一母线 / 两端电压等级不同 / 额定、长度、电抗 ≤ 0：拒绝 |
| 变压器 `trafos[]` | `hv_bus`、`lv_bus`、`sn_mva`（必填）、`vk_percent`（14）、`vkr_percent`（0.3）、`parallel`（1） | 容量 / 短路电压 ≤ 0：拒绝；高压侧电压低于低压侧：警告 |
| 外网 `ext_grids[]` | `bus`、`vm_pu`（1.0）、`import_max_mw`（1e4）、`export_max_mw`（0，> 0 允许外送）、`price_cny_kwh` / `export_price_cny_kwh`（逐时，缺省用场景电价）、`demand_charge_cny_mw_day`（需量电费折算到日，0） | 容量为负：拒绝；曲线点数不匹配：拒绝 |
| 机组 `gens[]` | `bus`、`kind`（hydro / thermal / gas / csp / diesel / other，默认 thermal）、`pmax_mw`（必填）、`pmin_mw`（0）、`cost_cny_mwh`（300）、`emission_t_mwh`（0）、`ramp_mw_h`（空 = 不限）、`energy_mwh_day`（水电日电量上限）、`vm_pu`、`dispatch_mode` | `pmin_mw > pmax_mw` 或为负：拒绝 |
| 常规负荷 `loads[]` | `bus`、`p_mw`（基准有功，按系统日负荷曲线缩放）、`q_mvar`（0） | 越界：拒绝 |

## 柴发与应急

| 字段 | 含义 | 默认 | 可选 |
|---|---|---|---|
| `gens[].dispatch_mode` | `economic` / `peak_shave` 可日常调度；`emergency_only` 仅应急时可用 | `economic` | 三选一 |
| `gens[].startup_cost_cny` / `min_up_h` | 启停成本 / 最小连续出力小时（仅透明记录，默认不进目标） | 0 / 0 | — |
| `emergency_mode` | 应急：UPS 可用至 soc_min，emergency_only 柴发放开 | false | — |

## 网络有效性告警

电气岛无电源（拒绝）、纯风光储孤岛、必需负荷峰值大于可靠出力、新能源装机远大于线路额定（警告），见 [拓扑编辑与校验](/help/topology)。
