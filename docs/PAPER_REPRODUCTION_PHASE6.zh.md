# Phase6 G08阶段交付：真实内生再出清，不是整篇论文通过

## 实际落地
- 本机 `/workspace/sim-agent` 明确授权的本地例外工作流；未接入/创建仓库，无登记远程地址。先做公共源码安全备份：`/workspace/sim-agent-backups/20261107-133409-phase6-public`，未包含.env/settings.json/数据库/私有项目负载。
- 新增显式 `opt_grid_feedback`：成本DCOPF→当前真实出力计算LMCE/LMP/区域平均/超额清洁四信号→每小时总工作硬守恒调度→真实电网再出清→再次更新信号。每个LP必须optimal；不靠固定碳序列、不弃任务、不把固定点当全局最优。
- 正常项目创建/JSON配置/校验/发布/不可变版本/冻结任务/历史只读/结果表/正式CSV ZIP全部接通。默认日模型和原opt_cfe仍分工，未把旧24h入口伪装全年。当前仅UTC1h、<=168h明示子集/benchmark，完整8784直接拒绝，不删闰日。详细目标/单位/费用/无路由迁移等边界见`OPT_GRID_FEEDBACK_MODEL_CONTRACT.zh.md`。
- 没有改日优化/热量/整数算法或B07 FIFO根因修复；新模式也进入完整Pyomo执行域。源Python执行摘要 `080b2787abe59c80761497247b06f9ba664ff740cd4d6b3dd59b062dde3e3bd5`；修改前摘要 `7cbffe86052e9d73e65d8fbd6bcc7ff5b37875d197c38ab61ce6702c6ed3536f`。

## 定量独立验收（不与pytest混算）
独立参考不导入产品模型：SciPy仅以发电变量/PTDF消去相角，产品是Pyomo角变量式；另查成本最优面排放范围、导出CSV节点/工作/迁移/费用/运行碳/LCA、正负FD与主目标锁定。

| 输入/边界 | 真正产品结果 | 独立结论 |
|---|---|---|
| 合成三节点稳定负LMCE | B节点−2tCO₂/MWh；基态560USD/12t；LMCE策略Δ−0.4t/+2USD；LMP策略Δ+0.4t/−2USD | 解析/SciPy与产品一致；负导数保留，不能拿便宜电自动当低碳 |
| 合成全清洁零变化 | 四信号0工作迁移/0排放变化 | 正确零变化，不为了“有结果”造迁移 |
| 合成拥塞、区域余量不可达 | average和excess均真实增排+2t；LMCE初始预测−2t、真实0 | 错方向和活跃集改变的线性预测失败保留，不事后择优过滤 |
| 真实RTS源数据**明示模型变体** | 73节点/158机组/120线路；完整8784行原负荷保留，取闰日4h原输入；基态149.20463201381028t/3311.3127335524036USD，四策略最终0运行排放 | 仅为本变体：四策略Δ−149.20463201381028t；初始预测分别约−546.03456/−546.03456/−496.68962/−506.00062t，不能当实际。不是TableI/II或全年结果 |

4个输入的29个LP审计组是子检查，不膨胀计成29新回归。RTS最大ISO目标差8.87e−12USD、节点残差1.66e−11MW、工作残差2.27e−13MW、迁移账残差1.82e−12MWh、独立FD差1.01e−10t/MWh；主调度目标差1.87e−9（目标单位随信号），均在声明容差内。

本批 **12个具名独立门12通过**（原内容锁定、单位转换、4冻结ZIP/PTDF审计、负LMCE、钱碳反向、区域余量增排、预测失效、真实失败ZIP、冻结重跑/历史）见`/workspace/sim-agent-phase6-evidence/independent_gates.json`。它们不是12篇论文，不是全年度精度。

## 原始版本与模型差异——不伪称“缺数据”
- 原PDF首页v1、共8页、SHA256 f40b0df886e4db4af0c92563b9d6f37b5b34b21e6b13ff953718c0e7e48c07a1。公式p2–4、RTS实验SecIV在p5、TableI实际和TableII预测在p6。初版来源曾写p4SecIV，真实逐页复核后仅纠正元数据，新发v2；原v1任务/ZIP保留，数值输入投影和四策略结果完全相同，不回写历史。
- 原公开RTS CSV在`cases/paper_reproduction/phase6/raw/`，bytes/SHA256/Gitblob和原URL在raw_manifest。master内容hash不等于作者发表commit。
- 本变体明确使用原Pmin=0/Pmax×1.5，原燃料热耗积分构造满载平均线性系数，lb→metric tonne，线路100MVA/(Xpu*tap)；独立从原CSV重新换算通过。但作者确切系数、吨制、节点3/7/28/70对应raw行序、时区仍未对齐。当前静态风光PMax不是原小时风光，储能无SOC故显式关闭其发电，不许免费放能。
- 公共RTS小时剖面未接入不等于不存在，未运行全8784是本阶段实现上限，不声称已实测“资源不足算不动”。原作者精度需要继续版本/剖面对齐；本轮不是整篇A级。
- 原数据来源声明不等于自动真实性认证：系统校验形状/轴/物理量，独立门额外核对本公开预置；自定义用户输入须自己保留来源，不能凭source文本变成作者数据。

## 回归、失败和兼容（真实退出）
- 当前完整 **374项：365passed、6failed、3skipped，exit1，310warnings，635.20秒**（中国标准时间2026-11-07 13:56完成）。351旧项之外新增23产品回归均通过；靶向107通过。不能写374全绿，不能挪用旧337passed。
- 6失败名称与前批351逐项相同，全在`tests/test_multi_sim.py`：test_matpower、test_openmodelica_default、test_openmodelica_powersystems、test_paraview和两条MATPOWER/OpenModelica routing_and_agent。真实原因仍缺octave-cli/omc/pvpython；原/tmp/baseline_fingerprint.json缺失造成3skip，未以当前代码造旧oracle、未调整测试躲红。被代理HTTP500阻断的apt路径未重试/换镜像绕过。
- 旧**21独立兼容门本轮重新跑21通过**：Zhang七福利2920/2980/2997.5/3000/3000/3030/3050；365个新鲜原生LP/8760与Zheng546网格/运行-LCA分账、372包hash。原48版本/49完整任务、19项目/16模板/8资源所有完整API记录hash未变。新G08原冻结重跑相同。
- 当前旧CFE正常ZIP路由只读回检通过：task ebd6070fb6354d81原目标473264255.7723827EUR、26280小时站点行；**本轮没有重算那三组全年采购**，原三组精度仍为前批B07证据，不能说成当前新年度实验。既有热1h/15min、整数、FIFO、CFE全部相应回归通过。
- 两个新真实failed正常任务保留：迭代上限必须收敛失败（有partial_NOT_ACCEPTED/过程CSV，无results.json），发电能力0真实不可行（无伪调度）。开发初次dual加载/变量作用域错误、独立验证器整数FD截断/默认信赖步长错误、引用PATCH客户端405的失败日志亦保留；修正后重新验，不把初次失败抹掉，也不混成当前6环境失败。

## 正常项目与真实浏览器尚未验收
项目 `23d38c373a73481b`，当前RTS页码更正v2任务 `ddebda1c1c75427b`，原v1 `62443c5cb3f14acf`未变；负LMCE `a925fe9191494430`、清洁 `2a79415f39df465d`、拥塞 `26bd705f52ce4c6e`、上限failed `432a20407dc74c84`、不可行failed `ceec3da27d30417b`、原冻结重跑 `b37d4e6f69c94104`。

Chrome先前重试和父任务截图确为ERR_CONNECTION_REFUSED，**本轮未重复尝试、不改代理或安全控制**。Shell根页200/health Mock、执行域空闲/无running只是API健康，不能算视觉通过。待验精确入口/截图点见`BROWSER_REPLAY_PHASE6.zh.md`（另含前批热/非空15min迁移/旧1h成功/CFE入口）。本轮没有UI截图。

## 交付与剩余
- 汇总：`/workspace/sim-agent-phase6-evidence/release_validation.json`；全量日志pytest_full_phase6.log/current_full_result.json，独立门independent_gates.json，历史history_preservation_final.json，冻结输入/CSV ZIP均在同目录。
- 小型公共实现/验收包：`/workspace/sim-agent-phase6-grid-implementation-20261107.zip`、`/workspace/sim-agent-phase6-grid-acceptance-20261107.zip`；每个<25MB，以packages.json的真实字节/sha为准。仅白名单公共源码/原公开数据/本次自建公共验收任务；不含.env/密钥/私有项目负载/数据库/旧私有1hZIP。补丁独立目录apply/逐文件hash与ZIP内部manifest校验，恢复方法见包内RESTORE_PHASE6.zh.md。
- 尚未完成：B09可信原外部工具/原oracle恢复、B10真实浏览器；完整8784/作者输入版本/真实小时VRE/节点映射/吨制；式7全局OPF-FLEX与路由迁移价格/容量/跨时状态；内生grid-CFE；完整背景四配置（前批只两配置600s未最优，不算通过）；用户已批准的GPU离散功率帽/吞吐SLA继续排队。没有写成全部论文或全部优化已完成。
