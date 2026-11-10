# Phase7：离散GPU功率帽/暂停/同工作SLA实际实现与局部独立验收

2026-11-07 中国标准时间。用户t69逐项完善及本地例外持续有效；仅/workspace/sim-agent修改，不创建/接入仓库，不克隆，无已登记远程。未执行设备/外部服务/交易，不读取.env/密钥，不驱动/重试已被阻的Chrome。

## 本批实际闭环

新增app/opt_gpu.py、opt_gpu_api.py；普通foundation配置/校验/发布/版本化冻结/运行/重跑/历史/结果/正式ZIP完整接入，用户可见energy_cost、吞吐minimax变体、作者公开DVFS-headroom公平离散实现。旧日能量/整数、CFE、grid默认不替换；不绑定日拓扑或拿GPU模型覆盖DC PUE/热安全。1h/15min物理工作与能量账，固定校准gang、离散帽/暂停/累计/完成idle、deadline/显式Flex窗口、逐GPU及任务审计真实优化。

**这是可验收局部产品模式，不是Emerald整篇现场实验通过。** 完整合同及所有保守/模型差异见OPT_GPU_MODEL_CONTRACT.zh.md；真实UI尚未通过，当前Chrome/Shell表面差异B10不改、不猜原因。

## 可独立定量结果

所有优化都输入工作/动作曲线/预算，不输入最优动作；参考另写SciPy稀疏MILP（不导入产品，披露同用HiGHS后端）。小例另穷举动作序列。当前17新具名独立门见`/workspace/sim-agent-phase7-evidence/independent_gates.json`，不是pytest/不是17篇；另21旧兼容门实际结果由legacy目录汇总，不挪用上批。

|输入（均同一任务工作）|产品完整时域kWh（价1USD/kWh）|独立比较及范围|
|---|---:|---|
|SYNTHETIC两卡2gang-hour，1h|1.2000000000000002|27序列穷举+独立MILP同值|
|强制第二槽暂停、后恢复|1.7000000000000002|27序列穷举，同工作仍2；不能靠不完成节电|
|两个任务Flex2/3，吞吐minimax|2.4000000000000004|6561序列，主ρ=2/3；锁主后费用|
|同阶梯输入细化15min|1.1249999999999998|同W2、独立MILP；控制粒度不同允许能量变优|
|真实校准曲线/原SRP标签+反事实工作1h|465.9927321294853|独立465.9927321294854；六任务各W6，9h含恢复/idle|
|真实留出预测动作1h|518.7205583116308|独立518.7205583116304；严格静态实测投影工作未完成0|
|同真实曲线·吞吐公平变体|574.126663425105|独立误差约1.14e-13USD，非作者Fair|
|同曲线·公开DVFS-headroom离散Fair|642.1750156382974|独立642.1750156382973；主ρ=.6580125462096286/事件210.66511676184584kWh/全费用三阶段均gap0|
|真实校准曲线反事实15min|452.76118400516157|独立误差约3.41e-13USD；36各自gang-hour完成，9216逐GPU行|

九成功模型相对独立MILP最大费用差4.55e−13USD。逐GPU能量、任务q/累计/容量/窗口、留出投影均由CSV另算；GPU可行性公差与实际残差明确：合成公平有1.5e−7h容量数值差，阈值1e−6；原曲线最大约5.2e−15h。不能把gap0说成浮点约束绝无公差。

真实失败：deadline预算反例task20f5cc2939f44eb0为infeasible、无成功results；留出50%速率负例69aa382031224e7d规划完成2、实际仅1/缺1，严格failed，保留partial_NOT_ACCEPTED及六CSV。新增回归还保留离散最低合格帽无法满足预算时的headroom infeasible；不能在离散允许集之外插值动作冒充通过。

## 原数据与原文证据：校准不等于预测，预测不等于现场控制

* arXiv2507.00909v1：p3 Flex0–3及3–6h窗口；p5Fig6功率帽、p6可忽略checkpoint近似/公平、p7Methods/33实验4.52%、p8Table1 ensemble。已存分页文本，不换版本混报。
* 作者README**确有详细伪代码**：lines85–104最小事件吞吐+等比例功率headroom；105–124 DVFS+pause集合与交错时间线、125–157 Greedy/resize。先前“只给定性无算法”需纠正；完整README和URL/Gitblob/SHA256归档raw，不执行其设备指令。当前是DVFS Fair离散实现和另标minimax对照，不是完整作者hybrid/resize。
* 公开sweep48点=8曲线×6帽。预声明训练32点[100,200,300,400]，留出16点[250,350]；只训练点线性预测。独立RMSE功率2.32416370938452W/GPU、归一吞吐0.019972999213951157。真实留出字段不入规划、只做静态投影，单位未明的原吞吐不造tokens/sec。
* Gitblob精确核对sweep6be26dd...、SRPperf9dd55d...、Fig34558c3b89...；README blob e80c4b9...；完整SHA和来源在data_reference.json。锁的是已取作者main内容，不是已证明论文发表commit。
* 原SRP6个job身份/Flex标签与sweep固定gang组合256GPU。计数来自各sweep totalW/perGPUW，未独立证明原SRP当时分配相同。每任务6gang-hour、9h时域、恢复3h、idle/pause100W、1USD/kWh与+08重放时钟均**明示合成/反事实**。它们不是原现场任务长度/截止/暂停测量。原最小活跃测量97.9375W，idle100W是假设且可能稍高，节电不能外推真实硬件。
* 原作者WeightedPerformance=.909560245；对已锁sweep gang数作明确GPU加权得.8770978125。权重/现场分配与窗口尚未建立，不拟合权重凑一致、不归产品算错，也不宣称相关公开材料不存在。
* Fig5有400实际点和37非等距预测点，不能按行相减。明确无外推对时：线性NRMSE6.443016728%、previous-hold4.729093331%；独立用stdlib时间插值复算。对齐协议未与作者定义建立，二者是敏感性，**都不能称33实验4.52%重现**，更非本批控制器功率预测精度。

## 开发期失败与已修正项（不删证据）

1. 初始headroom测试错误期望原SYNTHETIC fair仍可行，但它的最低合格离散帽只能400W，与0.6kW预算矛盾；求解infeasible正确。原1fail132pass日志保留，增加对应真失败回归，另用明确.75低帽速率控制验证主headroomρ=1和三阶段。
2. 初版逐卡completed_idle行用了gang平均W，异质两卡20/80W被显示成50/50，虽然聚合和成本不变。现逐卡自身idleW，新增回归独立期望20/80，非回填旧任务。
3. 独立harness初版容量阈值1e−7比MIP默认1e−6严，实差1.5e−7h导致真断言失败。保留初始ZIP/index/log；修正为透明声明公差、报告最大实差，而非改求解器/模型或隐藏差值。
4. 初版冻结验证给PATCH包裹draft导致无实际变更，不能当“修改后冻结仍不变”。已按实际PATCH合同改有效price=2、读取确认，再独立核对v1price1/快照、重跑仍1.2，旧完整任务hash不变。失败和说明在initial_harness_failure。

5. 首次制包真实patch apply失败：PDF分页文本含form-feed，splitlines把它误当换行，No-newline标记落入hunk中。已仅按实际LF分行、保留原字节，重新真实apply/逐文件校验；没有改产品结果，原失败日志和原因保留packaging_failure_*。

6. 完整Python回归结束后的静态UI口径复核发现：无验证字段的校准场景也被旧文案叫“留出通过”。只修正实际产品JS条件/文字：无字段只规划一致；有字段静态投影也不自动证明独立留出。未改Python/求解或冻结结果；node语法及真实renderGpu函数的stub渲染三例单独通过，仍非浏览器验证。

## 回归、历史与健康（最终数量以机器结果为准）

最终新GPU27回归通过；最终GPU+grid+CFE/FIFO/正常项目134靶向通过（16.18s）。当前完整唯一一轮真实exit1：**401项=392通过/6环境失败/3旧oracle跳过，310warnings，651.71秒**；相较前批374新增27全部通过。六失败ID与Phase6逐字相同，实际退出已Await确认，不以旧337/374覆盖。B09原6外部工具失败、3原oracle缺失仍保留；不apt重试，不造新oracle。

本批4个前模块真实冻结重跑：热efeeaccb445e4937目标−10472.655547077002，终端11.5/到达11.675256536669023/接收损.17525653666902236；15min迁移4f0252105c36470b，福利72000、gross240、正式迁移288行非空；CFE2h解析61f7d46b689c429c费用4；负LMCE f92e7fb3b1f745aa实际−.4t/+2USD。原task完整hash未改。旧1h任务仅只读核对目标−2416428.7，不冒称本批新鲜重算；原三8760采购亦未重复解，前批成功/本批路由与小例新鲜验证分开。

旧48versions/49完整tasks及19project/16template/8library全hash由verify_history_api真查；本批正常新增的独立项目/任务不替代旧记录。原6个Phase5/6锁定完整任务另hash验证。最终健康/队列/进程见final_health.json；浏览器仍未验，B10不能由curl关闭。

## 交付与下一步范围（不无限扩大）

普通项目a61fc23199ae4ebf及11个明示输入场景（9成功/2预期失败）和冻结重跑。全部任务/输入hash/ZIP在api_acceptance_index；UI复验精确ID、入口、预期及截图点见BROWSER_REPLAY_PHASE7.zh.md；没有本批视觉截图。

修改前公共源码备份/workspace/sim-agent-backups/20261107-140456-phase7-public，前hash080b2787abe59c80761497247b06f9ba664ff740cd4d6b3dd59b062dde3e3bd5；本批Python hash5067bc7880da2ca2350371b424c2959d6cdcf41b54f5afd5fde85aa5740ab3df。恢复只涉及公共源文件、列出新增文件后人工移开并按原备份还原，不动.env/数据库/历史；现有supervisor只在无running且FIFO闲时正常reload。

实现/验收包由phase7/build_release.py生成，分别<25MB，文本patch真实在独立临时基线apply、逐文件hash；XLSX独立二进制复制而非误作UTF8patch。包不含.env/settings.json/数据库/私有历史负载/旧私有1hZIP。最终路径/大小/SHA见packages.json和release_validation.json。

仍需：B09工具/旧oracle、B10真实浏览器；G04原Azure聚合/RNG/144h/Table1；G06 SustainDC原机架/HVAC/水塔31天；G05完整背景四配置未最优和内生grid-CFE；G08作者发表版本/小时VRE/吨制节点映射/完整8784/OPF-FLEX及跨时状态；G07原33实验212任务真实工作/idle/暂停/检查点、精确hybrid/resize、作者权重及Flex0更一般无损降帽允许集；所有新模式跨模块物理耦合与全面视觉验收；Ma精确网络/曲线/线性化及双层能力。**八篇整篇A级仍0，不把几个小时/合成探针当全面完成。**
