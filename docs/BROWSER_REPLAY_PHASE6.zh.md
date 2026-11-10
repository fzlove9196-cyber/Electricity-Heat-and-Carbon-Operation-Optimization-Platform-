# Phase6真实浏览器待验清单（不是已验收）

**阻断事实**：父任务Phase5浏览器重试仍ERR_CONNECTION_REFUSED，主截图也为Chrome错误页。Shell http://127.0.0.1:8080/health 可达/Mock=true **不等于浏览器可达、UI正确或截图已存在**。本轮未再循环浏览器、未改系统代理/安全控制、未Shell驱动浏览器。以下仅在浏览器环境恢复后由父任务安排；没有任何截图验收通过声明。

## 新G08入口
1. http://127.0.0.1:8080/ →「项目模型」→选择 **Phase6 GridFeedback · 真实RTS闰日子集+合成边界（非整篇）**，project `23d38c373a73481b`。
2. 正常新建入口在「创建独立场景」卡片：电网反馈预置下拉→新建电网反馈独立场景。已有项目内切换草稿会出现独立模式配置：selected_signal、最多迭代、FD步长、forward_fd/validated_basis、fail/方向导数实验、是否必须收敛。写入编辑器后仍须保存/校验/发布；不得影响原版本/任务。
3. 本次不用重跑大计算，直接「仿真任务」选下列已完成冻结任务→查看当时模型与结果→下载独立ZIP。任务页应显示四信号表格，初始预测/真实再出清分列、固定点不等于全局最优、运行/LCA/美元分账。

| 场景 | 已有任务 | 期望/截图点 |
|---|---|---|
| benchmark_negative_lmce | a925fe9191494430 | 基态560USD/12t，LMCE实际Δ−0.4t、费用+2USD；LMP实际Δ+0.4t、费用−2USD；两其它0；负LMCE B=−2保留，四者fixed_point但非全局最优。截图四信号表与不冒称最优说明。 |
| benchmark_clean | 2a79415f39df465d | 四信号0变化、没有虚构迁移，运行/LCA都0；工作守恒。 |
| benchmark_congestion | 26bd705f52ce4c6e | average/excess各真实增排+2t；LMCE初始预测−2t、实际0，不得机械显示为减排成功；活跃集切换/FD不稳在诊断/CSV。截图预测/实际反例。 |
| rts_leap4h | ddebda1c1c75427b | 2020-02-29T00Z起4小时，源8784/73/158/120和变体警告可见，不得写原文全年通过；四信号实际Δ−149.20463201381028t；初始预测约−546.03/−546.03/−496.69/−506.00t与实际不同。截图来源范围和预测/实际表。 |
| expected_failed_iteration_limit | 432a20407dc74c84 | task failed，部分过程红色/未接受，含iteration_limit；ZIP有partial_NOT_ACCEPTED.json，没有results.json；不得改成optimal/completed。失败任务不能“查看成功当时模型”，仍可下载审计ZIP并在任务详情看partial。 |
| expected_failed_no_generation | ceec3da27d30417b | 真不可行failed，无伪调度/结果；错误保留。 |
| 原冻结重跑 | b37d4e6f69c94104 | rerun_of a925…，输入快照相同，原任务不变，四策略定量相同。 |

每个ZIP在 `/workspace/sim-agent-phase6-evidence/<scene>.zip`，逐项输入hash与ZIPhash见`api_acceptance_index.json`；独立CSV/PTDF审计见`independent_gates.json`。这些API证据不是截图。

## 必须补验的前批UI（此前未通过）
- Phase5项目 `edb7b7959b024d03`：热任务 `da4c5d48e4344406`；终端实供11.5MWh、管网到达11.675256536669023、受端TES损耗0.17525653666902236，边界不同合理。原正式目标−10472.655547077002不变。截图“终端/管网/TES分账”与正常热KPI，不机械将两数改同。
- 同项目非空15min迁移任务 `0ca2cc19587e460c`：864 allocation/288 migration行，192正迁移时段、gross240MWh、福利72000、dt0.25；检查时间0:15/23:45和审计非空行。热例空migration不能替代此项。
- 旧1h成功入口：project `c553df86964f4552` / scenario `95c7a44f13244030` / version `76817b1aebdf4406` / task `2e8c374986114082`，目标−2416428.7。冻结hash见`docs/BROWSER_REPLAY_PHASE5.zh.md`和历史hash证据；查看副本不得改旧快照。
- 原CFE 3个8760成功任务及预期失败入口沿用 `docs/BROWSER_REPLAY_PHASE5.zh.md`，保留旧failed，不以新G08说明覆盖CFE未验项目。

所有截图应实际保存，包含项目/任务选择与量纲/状态，记录中国标准时间UTC+8；浏览器错误页仅为阻断证据，不是视觉验收。

页码更正的新RTS任务为ddebda1c1c75427b（同场景v2）；旧v1任务62443c5cb3f14acf及rts_leap4h_citation_v1.zip保留。实际PDF8页，SecIV在p5、两表在p6；数值输入投影与四策略结果完全相同。
