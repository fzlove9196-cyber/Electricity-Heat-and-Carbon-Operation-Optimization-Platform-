# Phase4：物理时间步与整数连续任务的实际落地

中国标准时间 2026-11-07T11:34:25.749112+08:00。t69顺序落实，本批完成可验收基础1+2（日窗口边界），不是六大类或八篇整篇全通过。源码/运行数据仅在本机`/workspace/sim-agent`，依本地环境例外修改，未克隆/接入/新建仓库，无已知远程URL。phase2/phase3报告、原文/页表/公式矩阵和失败工件继续保留。

## 结果与独立计数
- 最终pytest **302/302**=前批265（原236+29）+本批37；中间300项候选通过不是额外新测试。独立HTTP/正式ZIP **51/51**，另独立财务积分 **1/1**（4控制合计1门），本批52门；前批 **21/21兼容重跑**另计，重复运行不累加。
- 最终Python产品codehash `5df7484ef2b4538c7e20cd8298f716d1345b3ab08b25a767b53c683ad5bef241`；51门与21门的372原生包/全年输入执行hash一致。新UI文件另有manifest逐文件hash。JS syntax不等于浏览器验收。
- 合成电量控制1h/15min均IT32MWh、批8MWh、VRE24MWh、成本400。SOC电气最大残差4.45e-16，RC/TES≤1.39e-13，热节点/储热≤1.12e-16，独立生命周期误差<1e-14t。
- 热控制目标1h=-10472.343614246043、15min=-10472.655547077002：守恒都过；隐式RC离散化/可决策网格不同，不把策略差异误判bug。热延迟1h1步、15min4步；发送=损失+交付+期末在途存量。
- 连续性反例同物理输入energy可分成本2；continuous固定功率连续2h独立开始枚举101，两步长均101。取消控制初始1MWh+执行3=goodput3+损失1；电费5+取消费7=12，两步长一致。初始进度2、剩余窗口1、总时长3合法完成，本轮只耗1MWh。
- 真实连续窗口不足在会话API及普通冻结任务均infeasible/failed；错误长度/非对齐持续时长与未适配路径负例保留。
- s5显式词典序：主目标-72000→-72000，默认放宽0，gross1585→240MWh/日；原始HiGHS可行性容差1e-7、第二阶段bound240/optimal公开。无暗加epsilon；第二阶段注入失败保留原解并标记。
- Zhang七个小时福利2920/2980/2997.5/3000/3000/3030/3050保持。Zheng2019新鲜365个LP/8760点仍283.92709195412664GWh、生命周期113.44690977154075kt；546网格碳/成本误差1.335820343e-12kt/9.515588317e-11美元每吨。非历史包冒充新执行。

## 真正产品修改及合同
1. `dt_hours=1|.25`、日总长24h，输入24/96点强校验。正常项目axis/绑定必须60min×24或15min×96；显式sample-and-hold端点/编辑器不自动改保存对象。
2. SOC、批任务/任务量、发电能量上限、迁移耗电/费用、线路费、电价/碳/DR/VRE分账乘dt；峰需量费不乘dt；MW/h/K/h坡度乘dt；RC隐式欧拉、TES/储热/热管延迟/每小时损失均用物理小时。普通统计、拓扑/Sankey/AC手动时刻与96点结果贯通。
3. energy默认保留；continuous是真正二进制状态流MILP，非LP四舍五入。固定不可分功率/同站连续/截止/历史进度/取消丢进度/等待后全量重做/完成goodput与本轮耗电分账。无检查点/无无损暂停；required与soft分开。MILP界/gap/状态公开，不假装有LP对偶。整数job_admission的served代表完成goodput，可含初始历史进度，不能冒充本轮执行电量；后者由allocation/events与ledger独立重算。
4. `lexicographic_gross`显式选择，公差/优先级/失败恢复可见；任务取消/状态、gross/net和时间步进入正常结果、CSV和冻结ZIP。字段/案例/命令见`cases/paper_reproduction/phase4/README.zh.md`。
5. 常规项目“Phase4 最终验收（15min/整数任务）· a02bf5”，ID`a02bf5f12c1a44de`有3完成任务+1真不可行；详细UI入口/预期/截图点见`BROWSER_REPLAY_PHASE4.zh.md`。不是只论文专页；浏览器待父任务computerUse，本批无截图。

## 根因、失败与纠偏
- 原1h模型缺显式dt合同，改24为96不是功能；积分、坡度、状态、窗口、图表和正式表单位必须贯通，不支持组合必须阻止。
- 本批初版AC fallback漏局部dt、旧DR range被float类型破坏、热汇总二次乘dt，定位后修复。`full_first.txt`11失败/254通过及分组日志保留。
- 旧21门首次重跑真实失败：CSV hour`0.0`不能被旧int读取。深查又发现15min迁移duration硬编码1、网络hour仍步号；之前50门数值通过未证明所有审计元数据。现在1h保留整数格式，15min三表统一step/hour/duration；新增2pytest+1独立元数据门。见`legacy_compat_main.log`、`audit_timeaxis_failure_before_fix.json`，不改旧失败。
- 新回归首稿helper/fixture定位错误2失败/35通过，修正后37过；独立财务参考首稿误假定gen1，实际外部电源gen0，保留错误后按本控制系统声明发电列汇总。验收脚本缺陷不归产品算错。
- 一次重启命令可选rg无匹配使同链前置检查跳过，而后续kill仍执行；当时HTTP求解已结束，无运行API验收。立即核验健康Mock、running=[]，所有历史仍不变；操作链问题保留`restart_safety_note.json`，以后安全断言与kill放同一程序，不能前置可选命令。未中断运行任务。

## 原作者证据，不扩大论文精度
P3原文p3–7整数/连续/取消/滚动，p7–9/Table1。作者main.jl T168/Tend144、CSV192行、种子53/21/36；4份源文件Git blob SHA逐字节一致。192行MISO CER独立差5.69e-14kg/MWh；原前24行价格/强度+明确合成任务独立枚举8422.095577743745（明确假设7CNY/USD），两步长一致，非原Table1或Azure任务精度。
公开Azure162.7MB VM表路线已查但未处理；Julia聚合/随机序列、兑现144h滚动/UTIL-PD/预测扰动和Table1未执行，不说数据不存在。当前individual日窗口MILP不是作者同类群组完整复刻；未做原20000VM规模状态压缩/性能验收，跨日续接与已迁移初始站点的no_migration反事实受限。
SustainDC 15min守恒基础已有，原31天机架/HVAC/水塔同环境/三智能体/checkpoint评估未适配；原资料公开，不归无数据。
年度作者政策及年度投资仅1h；三级/VCC不支持15min或continuous、市场仅1h，明确拒绝。按t69剩余顺序3全年CFE采购/共享容量/小时匹配/储能来源/超额剔除；4内生LMCE/电网再出清；5离散GPU帽/吞吐SLA；6全部原模型进一步常规配置/透明审计。本批只整合新日场景基础，未声称上述已做。Ma外部修改网络/轨迹与双层线性化仍待补，不合成冒充。
旧合成循环费5CNY/MWh-throughput保持兼容、非论文参数、尚非可配置字段；独立财务参考明确出处，不反推拟合。旧冻结input_snapshot.json权威，旧结果不回填新审计，新schema展开不证明旧程序已有新功能。

## 备份、恢复与交付
修改前`/workspace/sim-agent-backups/20261107-110611-phase4`，源码/私有持久数据备份排除.env/settings.json及密钥/令牌文件，未加入交付包。基线codehash150ac836408dbcadee1359a7c90d3d317abef6a28728f6f629cbf858aa514c9a；备份有manifest逐文件hash/RESTORE.zh.md。
恢复会覆盖备份后新增项目/历史，必须先确认无运行任务、停止supervisor和child并另备份当前状态；先在新目录解包验证manifest，经用户确认再恢复原路径，秘密配置不导出/覆盖。归档不会自动删除新增源码，按release清单处理；本轮未执行恢复/回滚。
最终证据`/workspace/sim-agent-phase4-evidence/independent_final_v2`；兼容`/workspace/sim-agent-phase4-evidence/legacy_compat_v2`；完整及失败日志`/workspace/sim-agent-phase4-evidence`。本次验收前41版本/42任务目录记录逐项未变；另外原26版本/27任务全快照及结果摘要复验不变；新验收额外加入但不清理老结果。
实现包`/workspace/sim-agent-phase4-implementation-20261107.zip`；验收包`/workspace/sim-agent-phase4-acceptance-20261107.zip`；补丁`/workspace/sim-agent-phase4-evidence/implementation.patch`。各<25MB，只有公开源码/案例和新合成/原作者公开结果，无秘密、用户数据库、私有catalog或历史备份。
