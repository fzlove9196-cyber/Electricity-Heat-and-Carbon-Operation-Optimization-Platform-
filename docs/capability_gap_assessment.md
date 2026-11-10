# 算电热碳能力差距评估（2026-11-05）

- 调研日：2026-11-05（Asia/Shanghai）
- 对象：`/workspace/sim-agent`（算电协同仿真智能体）
- 方法：对照 USAGE.md / README / ADAPTATION_MATRIX / docs/compute_load_mapping_survey.md + **新一轮** Web 文献与 OSS 检索（非复读旧调研）
- 完整 Page：[算电热碳 · 能力差距评估](https://cursor.com/canvas/store-438ad29e-dcf3-4fb6-8c13-9243b0bb3fe2/ffc75a96-53e4-4563-84f9-4d9d8a20e975)
- 约束：不改引擎代码；8080 服务保持原样

## 1. 当前能力地图（已覆盖较好）

| 层 | 已有能力 | 证据路径 |
|----|----------|----------|
| 对话/研究 | NL 编排、研究模式状态机、透明化六步工作台、UX 引导、知识沉淀 | `app/research/`、`app/transparency.py`、USAGE §透明化 / §研究模式 |
| 电网调度 | Pyomo DC-OPF + HiGHS；pandapower AC 校核；拓扑编辑/能流 | `sdco_engine`、`model_edit`、`model_viz` |
| 热与冷却 | RC 热、蓄冷/预冷、多散热方式库、液冷排热、热安全、余热品位 | `thermal.py`、`cooling.py`、`heat_grade.py` |
| 碳 | 平均/边际因子、成本-碳 Pareto、VCC、Carbon Aware SDK 适配 | `carbon.py`、`vcc.py`、`opt/carbon.py` |
| 算力负荷 | 聚合批 + 作业窗 LP、链路时延/带宽、idle+dynamic/PDU、trace 转换 | `power_model.py`、`traces.py`、phase1 jobs |
| 全年/投资 | 8760 / 代表日、容量共优、字典序/加权/帕累托、对偶解释 | `app/opt/` |
| 多仿真器 | MATPOWER / ANDES / OpenDSS / OpenModelica / ParaView | `multi_sim.py` |
| 验证 | paper_bench、公开项目预设、研究验证脚本 | `cases/`、`ADAPTATION_MATRIX.md` |

历史已记缺口（仍成立）：交互会话不可迁移；无 GPU 整数/不可抢占；年度铜板无 OPF/N-1/RC；代表日碳误差敏感；投资单价【假设】；无真实 PDU 标定；Liu 式冷却+可再生全联合仅方向性。

## 2. 对照总表（能力 × 代表文献/OSS × 我方 × 工业优先级）

| 能力维度 | 代表论文 / OSS（已核验 URL） | 我方 | 工业算电热碳优先级 |
|----------|------------------------------|------|-------------------|
| 站点功率标定 idle/PDU | Fan 2007；[arXiv:2103.13308](https://arxiv.org/abs/2103.13308)；Scaphandre/Kepler | **部分**（模型有，标定无） | P0 |
| VCC / 碳智能整形 | [arXiv:2106.11750](https://arxiv.org/abs/2106.11750) | **有** | — |
| 机队公平碳 DR | Carbon Responder [arXiv:2311.08589](https://arxiv.org/abs/2311.08589) | **部分**（站点 DR 有，机队公平无） | P1 |
| 分布鲁棒日前+实时跟踪 | [arXiv:2410.21510](https://arxiv.org/abs/2410.21510) | **无** | P1 |
| 在线 Lyapunov 算-能-热 | [arXiv:2412.20032](https://arxiv.org/abs/2412.20032) | **无**（日前确定性） | P1 |
| DAG 依赖碳感知调度 | PCAPS [arXiv:2502.09717](https://arxiv.org/abs/2502.09717)；[carbon-aware-dag](https://github.com/umass-solar/carbon-aware-dag/) | **无**（作业可切分 LP） | P1 |
| 算电协同 LLM+物理校验 | PowerAtlas [arXiv HTML](https://arxiv.org/html/2607.26710v1)；[PowerAtlas](https://github.com/JAVA-Jiang/PowerAtlas) | **部分**（NL+LP 有；ECBench/GRPO 无） | P2 |
| 配网–GPU 闭环 OFO | [OpenG2G](https://github.com/gpu2grid/openg2g) | **部分**（OpenDSS 有，OFO 闭环无） | P1 |
| 作业功率预测+功率封顶 | [RADDiT / NREL](https://github.com/NREL/raddit) | **无** | P1 |
| 多 DC 可持续调度 Gym | [SustainCluster](https://github.com/HewlettPackard/sustain-cluster) | **无**（RL 环境；可作对照） | P2 |
| Microsoft 时移碳感知 | [白书 PDF](https://msftstories.thesourcemediaassets.com/sites/418/2023/01/carbon_aware_computing_whitepaper.pdf)；[ISE 博文](https://devblogs.microsoft.com/ise/saving-co2-using-location-and-time-shifting-in-azure/) | **部分**（时移有，生产式插件无） | P2 |
| CarbonFlex 供给+调度 | [arXiv:2505.18357](https://arxiv.org/abs/2505.18357) | **无** | P2 |
| 区域供热/余热动力学 | [Modelica Buildings](https://github.com/lbl-srg/modelica-buildings)；[Buildings.DHC](https://build.openmodelica.org/Documentation/Buildings@master.DHC.UsersGuide.html)；[DH MPC](https://github.com/haoranli1988/Modelica-district-heating-optimization-MPC) | **部分**（LP 品位/单节点；无管网水力时延） | P0 |
| MES/EH 多能总线 | [oemof-solph](https://github.com/oemof/oemof-solph)；[Calliope](https://github.com/calliope-project/calliope/)；[PyPSA](https://pypsa.org/) | **部分**（电+热+蓄；无通用 EH 图） | P1 |
| 长期容量扩展 | [TEMOA](https://github.com/TemoaProject/temoa)；[GridPath](https://github.com/sylvan-energy/gridpath) | **部分**（8760 容量共优；无 RA/ELCC/UC） | P1 |
| 电网数据层 Julia | [PowerSystems.jl](https://github.com/Sienna-Platform/PowerSystems.jl) | **无**（非必需） | P2 |
| 建筑柔性实测台架 | [FLEXLAB](https://flexlab.lbl.gov/)；[HIL4DF](https://github.com/LBNL-ETA/HIL4DF) | **无**（对照标定） | P2 |
| FluidFlower | CCS 多孔介质可视化实验台（与算电热碳无关） | **不 chase** | — |

## 3. 缺失能力排序

### P0（直接影响工业可信度）

1. **本站功率实测标定流水线** — 无标定则 idle/PDU/投资结论不可交付。建议：Scaphandre/Kepler/NVML → CSV → 拟合 P_idle/P_peak/断点；对话标【校准】。契合现有 `power_model`；免费工具优先。
2. **年度模型与日内物理闭环** — 铜板 8760 无 OPF/N-1/RC，代表日碳残差敏感。建议：代表日抽检全日 DC-OPF+AC/N-1；或双时间尺度（年容量→日运行复核）。仍 LP，贴合 `app/opt` + `run_dispatch`。
3. **区域供热管网时延/水力简化** — 余热项目（Odense 类）单节点会高估可回收性。建议：多节点热平衡 + 输送延迟 LP（借鉴 Buildings.DHC / oemof DH 教程，不嵌 CFD）。

### P1（产品差异化）

4. **滚动重调度 / 不确定性** — 仅日前确定性。建议：滚动窗口重解 + 简单场景/DRO 外层；Lyapunov 仅作基线对照。
5. **DAG/不可切分作业约束** — 连续 LP 高估灵活性。建议：阶段能量窗 + 优先序软约束；GPU 整数仅聚合子问题。
6. **活碳强度与边际因子溯源** — SDK 适配在，生产曲线弱。建议：接 Carbon Aware SDK / Electricity Maps；报告标明平均 vs 边际。
7. **配网电压–算力反馈** — OpenDSS 有、闭环无。建议：借鉴 OpenG2G OFO，作为 `run_opendss` 后处理迭代（有限步）。
8. **多能枢纽图建模** — 气/氢/CHP/热网通用总线。建议：薄封装 oemof-solph 或自研 bus 层，导出到现有 Pyomo。

### P2（可后置）

9. PowerAtlas/ECBench 式 LLM 决策对照；SustainCluster RL 基准；GridPath RA；PowerSystems.jl 数据交换；FLEXLAB 标定数据集；CarbonFlex 弹性供给。

## 4. 明确不 chase

- 黑箱 RL 作为主求解器（可用 SustainCluster 等仅对照）
- 全场 CFD / 机柜级热流体
- CAD 可视化建模器（保持对话+拓扑参数编辑）
- 用 CloudSim/OpenDC 替换 Pyomo+DC-OPF
- FluidFlower（CCS 实验台，领域不符）
- 卡级不可抢占巨规模 MILP 进主问题

## 5. 建议接下来 3–5 个构建

1. **标定工作流**：测量导入 + 参数表【校准】标签 + paper_bench 扩展。
2. **年–日耦合校核**：8760 方案自动抽代表日跑 DC-OPF/热/AC，输出一致性报告。
3. **供热多节点延迟 LP**：配置构建器增加管段；研究模式“余热是否靠谱”证据更硬。
4. **活碳 + 滚动重调度 MVP**：SDK 真连接 + 每 N 小时热启动重解。
5. **作业优先序/聚合 GPU 子问题**（可选）：deadline 作业加 precedence 组；对照 PCAPS 思路但不引入 RL 主环。

## 6. 关键链接（仅列已核验）

- https://arxiv.org/abs/2103.13308 · https://arxiv.org/abs/2106.11750 · https://arxiv.org/abs/2311.08589 · https://arxiv.org/abs/2410.21510 · https://arxiv.org/abs/2412.20032 · https://arxiv.org/abs/2502.09717 · https://arxiv.org/abs/2505.18357 · https://arxiv.org/html/2607.26710v1
- https://github.com/oemof/oemof-solph · https://github.com/calliope-project/calliope/ · https://github.com/TemoaProject/temoa · https://github.com/sylvan-energy/gridpath · https://github.com/Sienna-Platform/PowerSystems.jl · https://github.com/lbl-srg/modelica-buildings · https://github.com/HewlettPackard/sustain-cluster · https://github.com/gpu2grid/openg2g · https://github.com/NREL/raddit · https://github.com/JAVA-Jiang/PowerAtlas · https://github.com/umass-solar/carbon-aware-dag/ · https://github.com/Green-Software-Foundation/carbon-aware-sdk · https://pypsa.org/ · https://flexlab.lbl.gov/ · https://msftstories.thesourcemediaassets.com/sites/418/2023/01/carbon_aware_computing_whitepaper.pdf

调研完成时间：2026-11-05 Asia/Shanghai。引擎未改动。

## 实现进度（2026-11-05 Asia/Shanghai）

| 项 | 状态 | 证据 |
|----|------|------|
| P0.1 PDU/利用率标定 | **已落地** | `app/calibration.py`，`calibrate_power_model`，样例 R²≈0.998（合成线性） |
| P0.2 年–日物理闭环 | **已落地** | `app/opt/day_check.py`；中卫 summer/heatwave 2/2 可行，N-1 可行；rep48 vs 8760 碳误差见 validation |
| P0.3 多节点热网+时延 | **已落地** | `HeatNode/HeatPipe`；Odense 单节点 357.5 → 多节点+1h 327.4 MWh_th |
| 活碳 file/url MVP | **已落地** | `CARBON_SOURCE=file|url` |
| 引擎/8080 | 未改启动方式 | 向后兼容 fingerprint 测试仍过 |
