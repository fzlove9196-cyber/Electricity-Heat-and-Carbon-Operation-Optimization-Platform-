# opt_gpu 离散GPU/吞吐合同（Phase7，可验收子模型，不是整篇现场复现）

## 入口与边界
普通项目→独立场景→“新建GPU离散控制独立场景”→可见策略/gap/严格留出配置、完整JSON→保存/校验→发布→AC关闭、cost任务外壳→冻结任务→运行/历史→GPU结果→正式ZIP。API `/api/opt-gpu/presets`、`/api/opt-gpu/validate` 与正常 `/api/foundation/*`；不是论文专页。

显式 `model_kind=opt_gpu`；1h/15min、1–96步。每个任务固定且互不重叠的一组具体GPU，动作是该校准gang统一功率帽；不可假设任意GPU数线性扩展。每GPU有显式闲置W、每任务若允许暂停必须给暂停W。动作列为cap W、测量/预测平均W/GPU、相对该任务固定gang参考吞吐的normalized_rate。CSV未声明绝对吞吐单位，不创造tokens/s。配置出现PUE/热网络/日场景储能等未知字段、共享/resize、错时间轴、错误工作量/截止都会拒绝。

能量=∑完整时域功率kW×dt(h)，费用=∑能量×USD/kWh；全GPU含未分配GPU及完成/未发布后的idle、暂停、恢复尾段和显式固定非GPU功率。不会用GPU结果覆盖整DC PUE、整DC冷却/热安全或电网反馈。cap是动作标识/硬件设定，规划功耗来自显式测点，不把cap本身冒充实际W。活跃时每GPU的W由gang平均均匀记账，不是逐卡实测遥测；idle按各卡自身W导出，异质idle有回归。

## 工作、时间与SLA

* 每任务工作单位是**该任务参考固定gang等效小时**，W=∑baseline_rate×dt；各种任务的gang-hour不可互换、不是绝对通用计算量。逐任务相同W用于各策略对照，不通过丢任务节电。
* 二进制one-hot选择离散cap/暂停/已完成或未发布idle，连续q≤rate×dt为有用进度。完成状态单调；deadline前∑q=W，完成后idle。容量减有用工作为`wasted_capacity_work_h`；能量仍按整槽已选择功率，不偷偷按有用比例减少能耗。可以有通电但不产有用工作的容量，属于明确保守/松弛近似，不是原控制命令轨迹。
* release/deadline/SLA使用物理小时并与dt对齐；价格/预算/baseline长度必须与步数相同，禁止静默重采样。UI15min按钮仅显式重复阶梯输入四次，物理W和窗口不变，保存发布才生效。更细离散选择集可改变最优值；守恒不等于最优策略应相等。
* 论文arXiv2507.00909v1 p3：Flex0无性能降级；1/2/3在3–6h平均吞吐下降≤10/25/50%。本模式需明确窗口（不发明滚动窗口），并强制0/1/2/3窗口吞吐≥100/90/75/50%。短解析测试必须标`synthetic_short_window`。
* **当前Flex0额外采用保守参考帽锁定、baseline正时逐槽不减服务、无暂停**。原文“无吞吐降低”并不逻辑等于“必须锁400W”；这是更严格的实现允许集，不声称已覆盖原作者所有无损降帽选择。需进一步泛化时必须显式模式/独立验收，不能把本批最优值称作者Flex0全允许集最优。
* 暂停采用论文p6近似的可忽略checkpoint开销，保留进度；没有恢复耗时/重启损失、gang resize/跨站迁移。与日整数模型取消全丢进度是两个显式合同，不偷换。

## 三种明确策略及原作者Fair证据

作者公开README已归档，**不是“作者未公开公平算法”**：`raw/author_README.md` lines85–104给事件所需最小吞吐与DVFS Fair的等比例剩余功率headroom；105–124为DVFS+暂停集合枚举/交错暂停，125–157另有Greedy与pause+resize。详细伪代码可得不等于完整状态/命令时间线或数值实现全部可得。

1. `energy_cost`：在同工作、预算、SLA下最小完整时域电费。
2. `fair_minimax`：**我们的明确对照变体**，先最小各窗口吞吐Flex余量使用比例ρ=max((1−Q/B)/(1−floor))，锁ρ≤ρ*+显式lex_tolerance，再最小电费。不能改名当作者功率Fair。
3. `author_dvfs_headroom_discrete`：一个声明窗口覆盖全部有限预算事件槽；按原伪代码窗口总量/事件外基准服务计算事件最小rate，筛选满足rate的离散动作定义power headroom。首先minimax逐槽功率缩减/headroom，锁定后最大化事件能量使其尽量接近预算，再锁两主目标最小全时域费用，避免恢复阶段任意空耗。这是**公开DVFS Fair语义的离散minimax实现**，不是精确连续水填充，也不实现作者完整hybrid集合/交错timeline或resize。离散最低合格cap无法满足预算时真实infeasible，不能借混合时间/插值偷偷补动作。输入事件期间任务已提前完成等允许集也可能比原长运行作者实验更窄；本批原曲线控制均显式6h工作/9h恢复范围。

每阶段状态/限时/请求gap/incumbent/dualbound/实际gap/单位导出，主目标锁公差显式。仅`optimal`（含所请求gap公差）才接收，不把限时可行说成认证最优；无隐式求解器fallback。HiGHS LP primal设置1e−8，MIP默认可行性约1e−6；独立审计以声明1e−6h/kW边界检查并报告实际最大残差。合成公平例曾出现q容量1.5e−7h数值超差，原更严1e−7独立门失败留档；未改模型/算法遮掩。本批原曲线模型实际容量残差约5.2e−15h以下。MILP gap0不等于无浮点可行性容差。

## 校准/留出与失效

预声明8曲线×4帽[100,200,300,400]=32校准；[250,350]×8=16留出。留出规划动作W/rate仅用训练点线性预测，实测留出字段**不进入优化**。逐任务有用时间比例q/rate用于静态留出实现投影，实测rate可使工作/窗口不足，实测W可超预算；不补未计划恢复。严格开关默认true，任意deadline/SLA/power投影违反即真实failed，保留`partial_NOT_ACCEPTED`，没有成功results.json。若用户明确关闭严格检查，UI/JSON仍报告验证未接受，不承诺现场SLA。

未提供任何验证字段时，validation_accepted只表示规划一致性，不算留出验证；UI显式显示无独立验证字段。即使输入有验证字段，是否真正独立留出仍须检查来源/分离，字段存在不自动证明独立。

此方法不是现场闭环反馈/突发状态估计。真实48点与SRP六个身份/Flex采用真实数据；固定gang计数由各自sweep的total GPU power / power perGPU反推，组合合计256，不据此断言原SRP当时分配/权重相同；每任务6参考gang-hours+3h恢复、idle/pause100W、1USD/kWh、重放时钟2025-05-03+08均为明确**反事实/合成协议**，不是原现场工作/价格/本地时区。原曲线最小活跃测量97.9375W，假定idle100W甚至可能略高于最低活跃功率，不能将基于此假设的节电外推真实硬件收益；后续需原idle/pause测量或独立敏感性。

## 导出独立重算
ZIP：`input_snapshot.json/model.json/task_metadata.json/results.json`（成功）或`partial_NOT_ACCEPTED.json`（失败），`gpu_slots.csv/job_slots.csv/jobs.csv/sla_windows.csv/hourly.csv/solver_phases.csv`。每GPU×槽唯一、dt、功率/能量、动作/状态、gang工作分摊；逐任务有用/潜力/浪费/累计/留出量；窗口baseline、floor、两种性能、短缺；完整目标gap与headroom定义(JSON)。可独立重建电费、守恒、预算、截止/SLA和留出失败。参考能量是baseline>0整槽占用参考动作、其他槽idle的固定基准，不是另一个优化基准。

独立参考在`cases/paper_reproduction/phase7/independent_reference.py`：另写SciPy稀疏MILP不导入产品，同用HiGHS后端需披露；三个小例另用27/27/6561种动作序列穷举，不依赖求解器。`data_reference.py`另算训练/留出、Gitblob和Fig5。不能把同一产品函数自检算独立算法验证。
