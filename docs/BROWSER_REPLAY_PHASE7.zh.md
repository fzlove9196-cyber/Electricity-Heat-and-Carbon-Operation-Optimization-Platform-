# Phase7 真实UI待复验（尚未通过，不循环连接尝试）

父任务先解决Chrome ERR_CONNECTION_REFUSED与Shell可达差异后再派真实computerUse。当前没有本批视觉证据/截图；curl200不代替UI。不要浏览器失败时无限重试，不改代理/安全控制。

URL：http://127.0.0.1:8080/ ，普通“项目/场景/版本任务”，不是/paper-reproduction。项目 `a61fc23199ae4ebf` / `Phase7 GPU discrete caps throughput SLA (public counterfactual + SYNTHETIC controls)`。

1. **正常可达控件**：新建或选择此项目→“新建GPU离散控制独立场景”预设；应见策略/相对gap/严格留出/15min细化控件、展开JSON、保存/校验/发布。新建自己的独立场景操作，勿覆盖下列冻结任务或旧项目。选择头部DVFS-headroom公平预设，检查来源里作者README和反事实工作/100W idle说明；不是作者完整混合算法。
2. **离散同工作**：任务`0e46f4c790ed4235`，SYNTHETIC1h→查看当时模型/结果：2/2 baseline-gang-hours，1.2kWh/1.2USD，完整3h含idle。该场景`ecb49ac84b8e43fb`草稿故意改为价格2、冻结v1仍价格1（历史差异验收），不误判UI费用串线。15min任务`a9566d2137614e64`同物理工作2、能量1.125kWh，24GPU×槽行；粒度改变允许最优策略不同。截图：草稿/版本对比、结果单位与horizon、下载六CSV。
3. **暂停不能丢工作**：`0450e35309a64f1c`第二槽功率预算0.1kW，两卡暂停，第三槽恢复，2/2工作、1.7kWh。打开job_slots.csv验证pause和恢复，GPU×槽共6行。截图动作和deadline/SLA。
4. **原曲线、合成协议**：`6b9ba0e583184edd`256GPU/6任务/9h，36各自gang-hour均完成，465.9927321294853kWh；不把36当可互换绝对算力。原曲线15min`6fa526dc99514bdb`为452.76118400516157kWh、36h完成、9216GPU×槽行。校准场景必须显示“无独立验证字段：仅规划一致，不算留出通过”；不能因validation_accepted=true把训练输入叫留出。截图来源和任务完成/验证口径。
5. **公平不能混名**：吞吐minimax变体`94c125d1ad0a4a66`574.126663425105kWh；公开DVFS-headroom离散`9b29b7e2dc7840e5`642.1750156382974kWh，power-headroom主目标0.6580125462096286、事件210.66511676184584kWh，三阶段gap0。详情应列headroom与吞吐余量两种口径、非完整作者hybrid声明。
6. **真实留出与真失败**：`8b1c37fe79304fd9`518.7205583116308kWh，训练预测决策、16留出另验证、未完成0；UI显示有输入验证字段投影，但独立分离仍须核对来源，不能说现场33实验通过。`20f5cc2939f44eb0` deadline不可行应failed无results.json；`69aa382031224e7d`规划完成2但实际留出仅1、未完成1，应红色failed及partial_NOT_ACCEPTED，绝不能成功；CSV保留全部动作/SLA。截图错误与失败下载包。

本批API/ZIP和输入hash的唯一索引：`/workspace/sim-agent-phase7-evidence/api_acceptance_index.json`。独立审计/模型合同见`OPT_GPU_MODEL_CONTRACT.zh.md`。最终代码/测试量以同目录`release_validation.json/current_full_result.json`为准。上述数值不是现场整体复现。

## 前批必须补验的具体入口（仍未声称新版视觉通过）

* Phase5项目`edb7b7959b024d03`：热`da4c5d48e4344406`（本批新鲜重跑`efeeaccb445e4937`），目标−10472.655547077002；终端11.5、管到达11.675256536669023、接收储损0.17525653666902236，明确不同边界，不机械改同数；CSV完整平衡。非空15min迁移`0ca2cc19587e460c`（新鲜`4f0252105c36470b`），864分配/288迁移行、192非零、dt.25、gross240MWh/福利72000；审计非空，不拿空表当验证。
* 旧1h成功：项目`c553df86964f4552`、场景`95c7a44f13244030`、版本`76817b1aebdf4406`、任务`2e8c374986114082`，目标−2416428.7；完整记录hash见本批`critical_compatibility.json`，原energyv1前缀8890209b6212591e不变。仅只读，不覆盖历史。
* Phase5 CFE成功`fafed10efe0c434c`，新鲜`61f7d46b689c429c`：2h解析基准EUR4；失败`fdb016abe6f44b60`仍不可行。三原8760成功在项目`43437ec6c9cb4eb7`：`ebd6070fb6354d81`473264255.7723827EUR、`7857b7977df14594`397176972.5000959、`17ba03251e3441ac`383708646.6518236；本批未重算3全年，历史哈希和路由兼容与小例新鲜求解分开。
* Phase6项目`23d38c373a73481b`：负LMCE`a925fe9191494430`（新鲜`f92e7fb3b1f745aa`）LMCE实际−.4t/+2USD；拥塞`26bd705f52ce4c6e`代理增排+2t应保留；RTS引用v2`ddebda1c1c75427b`仅闰日4h变体，原8784未删；失败上限`432a20407dc74c84`/无发电`ceec3da27d30417b`不接受。截图真实再出清与预测列分开，原1h/年度/GPU模式别串线。

截图必须实际保存文件并报告路径/时间(中国标准时间)，没截图不算视觉证据；当前本批没有截图。
