# 数据中心参数

> **目的**：配置数据中心的 IT 容量、PUE、负荷、硬件功率模型与迁移。
> **前置条件**：场景中至少有一个数据中心（项目草稿中为必需）。
> **界面入口**：② 输入参数「数据中心与算力负荷」组；拓扑编辑器点数据中心；配置构建器；JSON `data_centers[]`。

[▶ 打开此功能：② 输入参数](/?view=chat&step=params)

## 基本参数 `data_centers[i]`

| 字段 | 含义 | 单位 | 默认值 | 合理范围 / 约束 | 不合理时 |
|---|---|---|---|---|---|
| `name` | 名称 | — | 必填 | 场景内不重复 | 重复：拒绝（项目） |
| `bus` | 接入母线编号（从 0 起） | — | 必填 | 0 ~ 母线数−1 | 越界：拒绝 |
| `cap_it_mw` | IT 容量（交互 + 批处理 IT 功率上限） | MW | 30 | > 0；参数表范围 [0, 1e5] | ≤ 0：拒绝 |
| `pue` | 电能利用效率，电网侧 = PUE × IT（`constant_pue` 模式） | — | 1.35 | 常见 1.0 ~ 3.0 | < 1：项目草稿拒绝；超出 1~3：警告 |
| `interactive_mw` | 交互式（不可调度）IT 负载曲线 | MW | 每点 10 | 点数 = 24 或 96；≥ 0；最大值 ≤ `cap_it_mw` | 拒绝 |
| `batch_mwh` | 批处理日能量（聚合模型，无 `jobs` 时） | MWh/日 | 150 | ≥ 0；≤ Δt × Σ(IT 容量 − 交互负载) | 超余量：拒绝 |
| `pf_q_ratio` | 无功 / 有功比（交流校核用） | — | 0.2 | — | — |

## 硬件功率模型

| 字段 | 含义 | 单位 | 默认值 | 约束 | 不合理时 |
|---|---|---|---|---|---|
| `power_model` | `identity`（P_IT = IT 工作功率，旧行为）/ `idle_dynamic`（P_idle + (P_peak−P_idle)·u）/ `pdu_pwl`（分段线性） | — | `identity` | 三选一 | 其他值：拒绝 |
| `p_idle_mw` / `p_peak_mw` | 站点空载 / 满载功率 | MW | 未设置 | `idle_dynamic` 必需；0 ≤ idle ≤ peak；参数表范围 [0, 1e4] | 缺失或顺序错：拒绝 |
| `p_idle_kw` / `p_peak_kw` + `n_servers` | 单机空载 / 峰值 kW 与台数，换算站点 MW | kW / 台 | 未设置 | 可替代上一行 | — |
| `pdu_breakpoints` | 分段功率曲线 `[{"util": 0, "power_mw": …}, …, {"util": 1, …}]` | util: 1；power_mw: MW | 未设置 | `pdu_pwl` 必需；≥ 2 点；util 从 0 开始、到 1 结束、严格递增；power_mw ≥ 0 且不下降 | 拒绝「分段曲线必须单调，利用率覆盖0~1」 |

示例：

```json
"power_model": "pdu_pwl",
"pdu_breakpoints": [{"util": 0, "power_mw": 8}, {"util": 0.5, "power_mw": 18}, {"util": 1, "power_mw": 30}]
```

## 热模型

`thermal` 为空时沿用常数 PUE；配置后在 `thermal_mode = "coupled"` 时生效，输出动态 PUE。详见 [热管理与散热参数](/help/params-thermal-cooling)。

## 迁移（场景级）

| 字段 | 含义 | 单位 | 默认值 | 合理范围 | 不合理时 |
|---|---|---|---|---|---|
| `mig_max_mw` | 每个数据中心每小时迁出 IT 功率上限 | MW | 8 | [0, 1e5] | 超出：警告 |
| `mig_day_share` | 日迁出能量 ≤ 比例 × 本地批处理能量 | — | 0.4 | [0, 1] | 超出：警告 |
| `mig_energy_mwh_per_mwh` | 迁移能耗：每迁移 1 MWh 在目的地额外消耗 | MWh/MWh | 0 | [0, 1] | 超出：警告 |
| `links[]` | 迁移链路；为空 = 不限链路（仅 `mig_max_mw`） | — | 空 | 两端必须是已有数据中心且不同 | 拒绝 |
| `links[].bw_mw` | 链路带宽（每小时可迁移 IT 功率） | MW | 5 | ≥ 0 | 负值：拒绝 |
| `links[].latency_ms` | 链路时延 | ms | 10 | ≥ 0 | 负值：拒绝 |
| `links[].fee_cny_mwh` | 迁移服务费 | 元/MWh | 0 | ≥ 0 | 负值：拒绝 |
| `migration_fee_basis` | 迁移费口径 `gross`（双向之和）/ `net`（净迁移） | — | `gross` | 二选一 | 拒绝 |
| `migration_cleanup` | `off` / `lexicographic_gross`（锁主目标后最小 gross 迁移） | — | `off` | 二选一 | 拒绝 |
| `migration_cleanup_tolerance_cny` | 主目标锁定公差 | 元 | 0 | [0, 1e-4] | 拒绝 |

## 常见问题

- 「交互负载超过 IT 容量」：降低 `interactive_mw` 峰值或提高 `cap_it_mw`。
- 「batch_mwh 超过日可用 IT 余量」：批处理能量放不进一天的剩余容量。
- 有 `jobs` 时 `batch_mwh` 不再使用（参数表中隐藏），见 [作业参数](/help/params-jobs)。
