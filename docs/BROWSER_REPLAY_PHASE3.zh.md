# 待父任务浏览器复验

（没有用Shell驱动浏览器）
1. 首页⑤结果复盘 → 原文案例审计；或直接 `/paper-reproduction`。截图：页头/范围声明/默认welfare + paper_abstract + net三个显式选择。
2. 选Zhang场景4 → 加载原输入 → 运行。应显示福利总额72000、每小时3000、B=0.5、无物理角箱且不适用AC；下载ZIP有allocations216行、72个任务接纳和72条有向对账时段记录。截图结果与正式下载入口。
3. 场景4换migration fee=1/0需选原场景6/7重新加载；分别3030/3050，不能只是改名称。换physical应保持±π并改变可行/接纳，不把抽象解当物理安全。
4. 选Zheng2019 → 加载 → 运行全年。应显示8760小时、546行、首点113.44690977154kt；展开表可见opex/capital/construction单列，ZIP含完整输入、grid.csv、hourly.csv。截图摘要和非零新增DC行的建设碳。
5. 版本化任务目标选福利、抽象模式取消AC，运行并打开历史副本；原结果面板应出现福利/域/LCA审计及下载。旧项目/旧任务仍可开且旧快照不变。截图冻结任务输入hash、执行hash及结果面板。
这些是待浏览器验收项目，不虚称已有截图或视觉验收通过。

6. B01：先新会话 → 模型拓扑 →「加载JSON」(`#meLoad` / `#meFile`)，选择 `cases/paper_reproduction/inputs/b01_capacity100.json` →「校验」(`#meVal`)。应无欠供误警，装机设计上限100MW与固定/求解峰值1MW分开；取消AC(`#meAC`)后「重新仿真」(`#meRun`)，结果实际峰值1MW。capacity1对照也为1MW；true_shortage为固定3MW/电源2MW，必须仍告警且运行失败。required_batch显示固定峰值0、必需峰值下界1、供给0.5。各为合成回归反例，不是论文精度。截图：容量标签/无误警、实际1MW、真实欠供保留。
