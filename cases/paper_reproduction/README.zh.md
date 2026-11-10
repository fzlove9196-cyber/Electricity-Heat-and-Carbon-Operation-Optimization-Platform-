# 原文输入与产品验收（本地授权实现，2026-11-07 中国标准时间 UTC+8）

本目录不是“8篇全部复现”。本轮只闭环 B01、G01、G02、G03、D01 的可验证首批；G04–G08/E01 仍见完整问题清单。

## 产品入口
- `http://127.0.0.1:8080/paper-reproduction`：加载7种 Zhang 原始报价/约束或 Zheng 全年输入、显式模式选择、运行及下载正式审计。
- 原工作台 → ⑤结果复盘 → 原文案例/福利与生命周期审计。原场景 JSON、版本化任务、正式结果面板亦支持新增字段。
- `GET /api/paper-reproduction/cases/zhang_s1`（s1…s7）及 `zheng2019_annual`。
- 日调度仍使用正式 `POST /api/sessions/{sid}/model/load`、`model/rerun`（`ac:false`）、`GET results` 和 `export.zip`，不是给研究脚本喂最优解。
- `POST /api/paper-reproduction/annual-migration`：8760/8784 个原始小时输入，固定容量/利用率网格的无状态有序迁移政策；精确闭式求解“先现有DC再新增DC最大消纳”的分层线性政策。不是金融/投资最优，也不是全年电力网络 OPF。

## 明确合同
- `Scenario.objective_mode=cost` 默认；新增 `welfare` 必须每任务提供 `Job.value_cny_mwh` 且碳权重0。需求接纳量、运行目的地、发电和潮流均内生。
- 福利最小化目标 = 供电/服务等成本 − 接纳价值；`market_clearing.welfare_cny=-objective`。`cost_cny` 不将需求价值当负现金成本。原文算例金额只是数值单位，字段 CNY 不代表汇率换算。
- `NetLine.service_fee_cny_mwh` × |物理潮流|；`Link.fee_cny_mwh` 与显式 `migration_fee_basis=gross/net`。默认 gross、默认报价0，不改变旧目标。净费不暗加去冗余次目标。
- 迁移容量仍是每方向容量；任务仍是可分连续能量、直接目的地分配，不支持整数连续作业或多跳中继。7组原文实例完全一致，不据此外推所有虚拟网络模型等价。
- `network_domain=physical` 保留原 ±π rad 箱；`paper_abstract` 必须 custom，显式不适用交流校核。100kV、x=20000Ω → xpu=200 → B=100/200=0.5MW/rad；原始 B 未被静默乘10000。抽象可行不是物理安全。
- `lifecycle_enabled=false` 默认。开启后在 `lifecycle_ledger` 单列运行发电碳、VRE生命周期、年化建设碳及反事实；不改变原运行碳指标/优化目标。VRE可给标量或24点 `lifecycle_tco2e_mwh_profile`。
- `lifecycle_counterfactual=jobs_origin_uniform` 仅支持无常规负荷/储能/供热、identity+constant_pue 的显式增量模型；否则拒绝，不伪称一般反事实。一般模型可选 none，只报绝对分账。
- 建设碳：`lifecycle_embodied_t_per_year ×24/lifecycle_year_hours`；8760或闰年8784需明确。全年政策输入强制明确8760/8784，既不截断也不补造小时。
- 峰值预检分列装机设计上限、同小时固定负荷峰值、必需能量导致的峰值下界和可拒绝的任务报价。恒PUE/identity聚合必需批任务有日能量下界；热耦合预检仅用电气IT下界，不能替代冷量/热安全求解。无警告不是全系统可行性证书。

## 原始材料与独立验收
`sources/zheng_7_Load_Migration.xlsx`、`zheng_6_Results_2019.xlsx` 为作者公开材料，来源 https://data.mendeley.com/datasets/wngs282m48/1（CC-BY-4.0；Zheng et al., Joule2020, DOI10.1016/j.joule.2020.08.001）。保留原文件与SHA256。2019输入 F/G/H/K 等列及原公式，不将迁移/减排输出列作为产品输入。
`inputs/zheng2019_annual.json` 转换原单位：kgCO2e/MWh→tCO2e/MWh；原始财务M美元→美元。288现有DC、65%阈值及0新增点，用原 baseline 到容量的 headroom 报价，不是给最优迁移量。1单位/MWh机会信号只实现弃电优先，不是论文财务电价。混合VRE逐时LCA因子按作者风/光同比例吸纳假设（11/48kg/MWh），不冒称独立风/光经济选择。
`inputs/zhang_s*.json` 对应 https://arxiv.org/abs/1910.05443 p2–5 / TableI。只提供源端需求上限/价值、发电报价、物理/迁移容量/服务费，不包含最优接纳、迁移或角度。

```bash
# 需要当前Mock产品在8080；只生成本地会话/工件，不外联。
/workspace/sdco-env/bin/python cases/paper_reproduction/acceptance_api.py /workspace/sim-agent-change-evidence/independent_final_v2
# 上述完成后，追加冻结输入/原角域失败/旧历史/代码hash验收
/workspace/sdco-env/bin/python cases/paper_reproduction/acceptance_provenance_api.py /workspace/sim-agent-change-evidence/independent_final_v2
/workspace/sdco-env/bin/python -m pytest -q
```
两个验收器都不 import app；以 HTTP、正式 ZIP/CSV、原文常数及原工作簿缓存输出独立重算。不是运行包 reproduce.py 用同一实现自检。D01固定注入探针仅测域差异，不计策略精度；B01合成反例不计论文精度。

## 审计、旧快照与未完成范围
正式运行包新增逐job×hour×destination（含不合格目的地显式0及eligible）、接纳/未完成、双向gross/signed-net/absolute-net/费用、逐支路潮流/相角/单位映射、独立生命周期分账和执行代码/输入哈希。冻结任务导出另带原始 `input_snapshot.json` 与 `frozen_task_metadata.json`，不把新默认字段倒写历史快照。
仍有替代最优解的无收益双向迁移。例s5：gross66.041667MWh/h、abs-net10，按net收费30；不隐藏成“实际只迁移10”。可选词典序去冗余尚未实现。
原产品236测试、新增产品回归、独立原文/API验收分别计数；最终数值与保留失败见 `docs/PAPER_REPRODUCTION_PHASE3.zh.md` 和证据目录，不把上轮27个保存文件核验算新增产品测试。

`inputs/b01_*.json` 是有明确SYNTHETIC标记的浏览器/接口回归探针，不是原论文数据。用原模型拓扑页加载JSON；或在专用页导入后明确选择cost/physical模式。
