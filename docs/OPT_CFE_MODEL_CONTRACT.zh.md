# 独立年度CFE产品模式与原作者口径

## 正常产品入口与范围

8080 → 普通项目管理 → 创建/选择项目 → “年度CFE公开原输入” → “新建年度CFE独立场景” → CFE参数控件/完整JSON → 保存、校验与展开 → 发布不可变版本 → 版本化仿真任务（cost、AC关闭、年度默认600秒）→ 运行/查看当时模型与结果 → 正式ZIP。JSON导入亦支持自包含年度模型。不是只在论文页或外部脚本可用。

`model_kind=opt_cfe` 与原日模型分工，默认日模型仍24h/1h；原24h并未统一改成8760。全年仅UTC整年1h：一般年8760/闰年8784，气象年、规划年分列；不补齐/截断，15min、AC、三级运行、日设备/信号绑定、日碳目标/福利目标明确拒绝。benchmark明确非全年、最多168小时，容量费仍按输入年化系数全额计一次，不能把短时运行费用当年度结果。

原始剖面/成本全部自包含在版本/任务中，无隐藏本地文件路径、在线数据依赖或“最优容量/接纳决策”输入。模板/版本复制、草稿修订、发布、冻结、重跑、failed状态、历史只读、ZIP均走常规foundation对象。年度结果不伪造日会话/拓扑；日会话的Scenario解析显式拒绝年度model_kind。

## 目标、单位与共享容量

每站风/光容量K_r(MW)、电池充/放端功率P(MW)、能量E(MWh)各只有一个全时域变量，不按日或季节各自投资。8760个实际发电g_r,t ≤ CF_r,t K_r；弃电是潜在出力减实际发电，与已经发电但丢弃/弃售的excess分开。

目标=Σ年化K/P/E投资费＋Σ8760h实际风光变动费＋外网进口电费＋放电内部能量变动费＋空间/时间虚拟迁移费。输入币种EUR/CNY/USD必须一致；年化容量费单位货币/MW/年或货币/MWh/年，运行费货币/MWh。作者2025网络成本已年化，不再重复折现；作者onwind边际费用覆盖为0.015EUR/MWh，solar沿原NC0.01，电池原η_ch=η_dis=0.9797958971132712。原代码chargeP=η_dis×discharge内部P；本产品P指同一充电输入上限/放电输出上限，等价。

产品目标仅站点采购与调度，不含背景欧洲系统成本常数/扩建；原作者PyPSA背景网络结果另列objective及procurement_objective与offset，不强行把不同费用边界凑成一个值。

## 三种匹配政策：绝不能混淆

出处：arXiv2405.00036 p4式(1)(2)、p5式(3)、p6式(5)–(7)。论文式(2)/(7)是逐小时剔除超额之后的**年度求和分数**，不是x<100%时每小时都达到x。

- `paper_cfe_score`：Σ_t credit_t ≥ x Σ_t actual_load_t。
- `hourly_cfe_floor`：每小时credit_t ≥ x actual_load_t；这是显式更强的可选模型，x<1时与原文不同。
- `annual_res_share`：Σ实际合格风光发电=x Σ实际用电；不代表24/7清洁。原文RES分支同样为等式，原代码分母采用未移负荷且该分支缺flex约束；本产品RES含flex时使用明确实际负荷/边界，不能称与该未约束分支完全等价。

credit=generation+delivered_discharge−charging−excess+grid_CFE×imports
=actual_load−(1−grid_CFE)×total_imports。

所以任何小时超额清洁不会被挪去抵另外一个小时的脏电；x=1时所有grid_CFE<1的进口都必须为0，逐小时无清洁缺口（另输出数值公差）。annualRES100则可以白天弃售、夜间购灰电，系统必须如实显示小时缺口。

外网grid_CFE为给定0~1份额，不是tCO2/MWh，更不是内生LMCE；当前不支持负电价套利（输入明确拒绝）。额外性/地域为合同合格性条件：可采购资源须additional=true且region与站点竞价区一致，不接受存量/跨区证书当本地新增。自报合同元数据不是现实世界的额外性核证，产品没有自动验证真实PPA或物理交易。

## 物理来源与储能来源双账

可再生实际发电=直接供负荷+本地充电+excess。负荷=本地直接+外网直接+green/brown两类放电。外网充电按该小时grid_CFE拆成清/灰来源；两个SOC独立递推、分别cyclic或empty边界，合计受同一E约束；充电和输出放电受同一P约束。没有免费初始清电，cyclic表示同一源年周期闭合，不是每个子日重设SOC。

物理清洁供负荷=本地直接+green放电+grid_CFE×外网直接。与论文credit分别显示。若灰/清混合外网充电有储能损失，论文credit会再扣灰进口损失，可能低于实际清洁供负荷份额：两小时解析例可分别0.4375与0.5，不能机械改成同数。

沿作者线性模型允许同时充放，不含互斥整数/负价套利；没有偷偷加ε或声称电池MILP。超额不卖电、不计收益；从credit扣除，默认max_excess_share=0；潜在未发电弃电从来未计credit。ZIP全精度逐时表可独立重算来源、SOC、损失、匹配缺口、成本与容量上限。

## 空间/时间弹性与作者代码版本差异

actual_i,t=base_i,t+空间净迁入+recover−defer，受(1±flexibility)base约束；空间完整有向虚拟图、1e6MW显式上限，迁移工作而非跨区输电；每站每源UTC日Σrecover−defer=0。不是逐VM字节迁移/截止期模型，也不是TSUSC整数工作负载。

固定作者仓库commit `6e3bd6e2bdcaf8ff25393218b09c737a018460bc`；原网络Git blob `e95dd9aba48f997b9ae27ca4df5123790b6f7a2e`，34,093,522字节，不重复下载。

**实际确认的外部版本差异**：`solve_network.py:803–848`先建立3个DSM总线和6个DSM link；`strip_full_network:883–904`只保留DC/原竞价区及battery总线，不含DSM；实际运行前后拓扑证据`author_reference/f0_topology.json`中DSM从3/6变0/0。因此“temporal_shifting=true”配置并不代表该默认剥离拓扑真的有DSM。

- `riepin8760_f0/f40`：同原8760输入，匹配发布代码有效拓扑，无DSM；不是伪装原temporal同时运行。
- `riepin8760_f40_manuscript`：同原始输入，另启论文式6日内DSM，明确是论文公式变体，不叫原代码原封复现。

原作者代码用Python3.11/PyPSA0.26/linopy0.3.15隔离环境；许可Gurobi被公开HiGHS IPM替换，参数和失败日志保留。外部旧依赖在Python3.13缺numpy1.26 wheel、以及xarray/linopy锁版本冲突属于参考环境适配，不是产品bug或论文数据缺失。参考脚本初稿遗漏原__main__模块全局n，已纠正为同等CLI上下文；原harness失败保留，不错误归因给作者。

四原配置、所有flex档位、背景欧洲OPF/碳因子迭代、全部论文回归/地图及1.29±0.07收益斜率本批不宣称完成。后续内生LMCE与GPU仍是已批准未完成项。

## 透明导出

`GET /api/foundation/tasks/{id}/export.zip`：input_snapshot.json / model.json / task_metadata.json / results.json / hourly.csv / spatial_flows.csv / daily_work.csv / README.json。真实失败同样导出冻结输入/错误，不生成假的成功hourly。

空间表为稀疏，省略≤1e-8MW的数值零；CSV duration_h=1、step/hour=0…8759或8783，timestamp明确源UTC。结果UI仅预览某站24小时，完整求解/冻结/导出没有裁切。输入快照hash、执行Python代码hash、求解器版本/状态/容差/界均保留；历史重跑创建新任务不覆盖旧结果。

## 求解时间与性能边界

当前执行Python摘要7cbffe86052e9d73e65d8fbd6bcc7ff5b37875d197c38ab61ce6702c6ed3536f。根因修复不是算法：安装Pyomo6.10.1全局collector跨线程把B变量放进A映射，B父对象释放后legacy字典名字冲突。两算法未保护都可确定性复现，串行/保护都最优7/3；见B07_ROOT_CAUSE.zh.md和完整栈。产品进程级FIFO覆盖建模到加载，变量归属前后校验，执行域本身不重试/换算法/伪造结果；已有tiered显式rules_fallback不属于本次新增，不能泛称所有业务异常均已消失。

正式3组原8760采用与旧B失败相同的dual-simplex(strategy1/parallel off)，同冻结输入创建新任务，不改变数学LP。全部completed，420492个solver变量每组外来0；独立目标差最大0.0001358EUR，CSV守恒最大4.25e-11。求解管线约74.76/133.81/183.36秒，队列等待另约0/256.54/73.89秒，软限不含queue/build/export，非硬墙钟。metadata的snapshot.code_hash保持旧值而execution_code_hash记录当前值。

本批独立原8760重审20门通过，初次19/20队列范围误判及重审首版JSON/CSV投影误判均保留，不重复求解。旧B失败输入/错误/代码hash未覆盖。当前全量342pass6fail3skip是环境缺外部CLI及旧临时oracle，不能引用先前337pass覆盖，也不把采购闭环等同完整背景/四配置/原Gurobi结果。

原100MW/站为作者规划假设，2013天气/2025成本，不是三座真实数据中心的现场计量。

## 无用电站点的份额

flexibility=1允许全年度迁出某站全部负荷。此时该站实际用电0、容量/成本/运行仍可合法最优；年RES、物理清洁份额与论文CFE分数分母为0，导出JSON null，UI显示“—（无用电）”，不填0/100%或NaN。真实失败任务94820c4c112846a1保留；同输入冻结重跑2.00002通过独立容量＋迁移费用解析对照。
