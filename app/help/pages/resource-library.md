# 通用数据与设备模型库

> **目的**：维护带来源、单位、适用工况、时间轴与版本的通用气象 / 电价 / 碳 / 负荷数据，以及设备性能模型，供多个场景绑定复用。
> **前置条件**：知道数据的地点、年份、时区、起始时间和单位。
> **界面入口**：① 资源与建模 → 🗃 数据与设备模型库。状态：【部分实现】（设备库仅数据中心、储能两类）。

[▶ 打开此功能：数据与设备模型库](/?view=resources)

![数据与设备模型库](/help/img/f1106-library.png)
*截图：2026-11-06 产品基础层验收（Mock）。*

## 资源类型与强制单位

| kind | 中文 | 单位（必须完全一致） | 额外检查 |
|---|---|---|---|
| `weather` | 气象（室外干球温度） | `degC` | 数值在 −90 ~ 65 °C |
| `price` | 电价 | `CNY/kWh` | 有限、无缺失 |
| `carbon` | 碳强度 | `tCO2/MWh` | 非负 |
| `load` | 负荷（交互式 IT） | `MW` | 非负 |
| `device` | 设备模型 | 每个参数单独标注 | 见下表 |

时间序列点数必须等于 `axis.length`；可选 `timestamps` 必须与时间轴逐点一致，无重复、无跳点。

## 新增资源版本

1. 选择资源类型 → **填入明确示例**，得到可编辑的 JSON 模板。
2. 修改 `name`、`source`（来源）、`applicability`（适用工况）、`axis`、`values`、`unit`。
3. 点 **新增不可变资源版本**。任何校验失败都会拒绝入库。
4. 修订已有资源：在 JSON 中带上 `previous_id`（前一版本 ID），生成新的 r 版本；旧版本保持不变，类型不可改变。

> 库中新增版本**不会自动改变**已有场景的绑定，也不影响已发布版本和已建任务。

## 设备模型可用参数

| device_type | 允许的 parameters | 单位要求 |
|---|---|---|
| `data_center` | `pue`、`cap_it_mw`、`power_model`、`p_idle_mw`、`p_peak_mw`、`pdu_breakpoints`、`thermal` | `pue`=`1`，`cap_it_mw`/`p_idle_mw`/`p_peak_mw`=`MW`，`power_model`=`1`，`pdu_breakpoints`=`util:1,power_mw:MW`，`thermal` 需逐字段单位映射 |
| `storage` | `energy_mwh`、`power_mw`、`eta_ch`、`eta_dis`、`soc0`、`soc_min`、`soc_max`、`reserve_frac` | `energy_mwh`=`MWh`，`power_mw`=`MW`，其余=`1` |

设备参数会代入一个探针场景做完整校验（例如效率超过 1、单位写成 `kW` 都会被拒绝）。不接受未接入求解的 `curve` 字段——分段功率曲线请用 `parameters.pdu_breakpoints`。详细取值见 [数据中心参数](/help/params-datacenter) 与 [储能参数](/help/params-storage)。

## 内置种子

- **明确合成**的示例气象 / 电价 / 碳 / 负荷（「示例地点」、2024-07-01、24 点）与「示例·储能95%效率」。
- 「公开气象·中卫 / 韶关 / 乌兰察布·2024-07-01」：Open-Meteo ERA5 2 m 干球温度，记录原 URL、文件路径与 SHA256。**再分析温度不是机房现场测点。**

## 限制

- 气象通用绑定目前只覆盖干球温度；湿度、风光出力等沿用场景已有输入。
- 其他设备（风光、机组、线路、热网等）仍在场景 JSON 或模板中维护。
