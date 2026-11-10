# 算力任务到电热负荷映射 · 论文与开源方法调研（摘要镜像）

- 调研日：2026-11-05（Asia/Shanghai）
- 完整 Page：[算力任务到电热负荷映射 · 论文与开源方法调研](https://cursor.com/canvas/store-438ad29e-dcf3-4fb6-8c13-9243b0bb3fe2/81ea1988-a354-47a8-8dde-b49048ea53aa)
- 现状（sim-agent）：固定 24h IT + 灵活批（聚合/作业窗）→ IT MW；PUE 或 RC 热；同一 LP DC-OPF；批迁移；连续 LP；**尚无** `P_idle+(P_peak-P_idle)·u` 硬件功率模型。

## 实现状态（①②，2026-11-05 Asia/Shanghai）

| 项 | 状态 | 代码 | 验证 |
|----|------|------|------|
| ① Fan idle+动态 / PDU PWL | **已实现** | `app/power_model.py`，`DataCenter.power_model`（缺省 identity） | `tests/test_power_vcc.py`；指纹兼容 default/zhongwei_summer_coupled/ulanqab_cicdata_summer |
| ② Google VCC | **已实现** | `app/vcc.py`，`Scenario.vcc_mode`（缺省 off） | 真实案例 `cases/common/run_power_vcc_validation.py` |

**向后兼容**：新字段 unset 时目标/排放/变量数与改动前一致。参数未实测标定时须标【假设】。


## Top 5 推荐（优先复用）

1. **Fan / Google 分段线性功率** — Fan et al. ISCA 2007；Radovanović et al. [arXiv:2103.13308](https://arxiv.org/abs/2103.13308)。`P≈P_idle+(P_peak−P_idle)·u` 或 PDU 分段线性。**Pyomo 仿射，近端必加。**
2. **Google Carbon-Intelligent / VCC** — [arXiv:2106.11750](https://arxiv.org/abs/2106.11750)。日前虚拟容量约束可延迟批处理，日总量守恒。与现有批平移高度同构。
3. **Liu et al. 可再生+冷却感知调度** — SIGMETRICS 2012。IT 与冷却、电价/可再生联合；冷却用分段线性 COP(T) 保持 LP。
4. **Trace→功率流水线** — [Alibaba clusterdata](https://github.com/alibaba/clusterdata)、[Azure LLM Inference](https://github.com/Azure/AzurePublicDataset)、Google Borg；用 SPECpower/NVML 标定利用率→功率。只改输入生成。
5. **Lets-Wait-Awhile + Carbon Aware SDK** — [lets-wait-awhile](https://github.com/dos-group/lets-wait-awhile)、[carbon-aware-sdk](https://github.com/Green-Software-Foundation/carbon-aware-sdk)。时间平移基线与碳强度接口。

## 六主题要点

| 主题 | 代表方法 | 对本栈 |
|------|----------|--------|
| 1 功率模型 | Fan 2007；SPECpower（Hsu&Poole 2011）；Google PDU 分段线性；RAPL/NVML；MLPerf Power [arXiv:2410.12032](https://arxiv.org/abs/2410.12032)；综述 [arXiv:2004.12335](https://arxiv.org/abs/2004.12335) | 近端加 idle+动态；测量仅用于标定 |
| 2 作业→功率 | Alibaba / Azure / Borg traces；利用率→功率曲线 | Trace 转换器 → 24h IT MW |
| 3 时空碳感知 | VCC；地理负载均衡；K8s 碳插件；Compute Gardener | VCC 式小时上限；碳目标 λ·碳 |
| 4 算电协同 | 时空灵活 SCUC [arXiv:2605.18517](https://arxiv.org/html/2605.18517v1)；Alibaba LAD-Flex；批平移评估 | 与 DC-OPF 同构扩展；中文开源一体栈稀缺 |
| 5 热感知 | Tang TPDS 2008 XInt/MPIT-TA；Van Damme TCST 2017 | 中期：IT→冷却(T,负载)；可选进风约束 |
| 6 OSS | CloudSim Plus、OpenDC、SimGrid、Scaphandre、Kepler、CarbonSim、SustainCluster、pandapower | 仿真/测量对照；**勿替换 Pyomo 主引擎** |

## 三层路线图

### 近端（不重写引擎）
- 可选硬件功率层；碳双目标；保持批日能量守恒；trace 转换 + Lets-Wait 基线。

### 中期
- 分段线性冷却；迁移带宽/时延/能耗；弱耦合 SCUC；可选稀疏热再循环约束。

### 进阶
- GPU 整数仅作聚合子问题；DVFS 外层枚举；RL 仅对照；双层/LMP 按需。

## 不要照搬
- 不用 CloudSim 换 OPF；不用 TDP/SPECpower 分数直接当机房负荷；不上卡级不可抢占进主 LP；K8s 碳插件≠电网协同；平均碳≠边际碳；中文白皮书≠可复现代码。

## 关键链接速查
- Fan PDF: https://static.googleusercontent.com/media/research.google.com/en/us/archive/power_provisioning.pdf
- Power model: https://arxiv.org/abs/2103.13308
- VCC: https://arxiv.org/abs/2106.11750
- Thermal TPDS: https://doi.org/10.1109/TPDS.2008.111
- Scaphandre: https://github.com/hubblo-org/scaphandre
- Kepler: https://github.com/sustainable-computing-io/kepler
- OpenDC: https://github.com/atlarge-research/opendc

