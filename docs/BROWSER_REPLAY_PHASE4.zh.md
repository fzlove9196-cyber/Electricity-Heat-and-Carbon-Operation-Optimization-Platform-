# Phase4常规项目浏览器复验（待父任务computerUse）

中国标准时间 2026-11-07T11:34:25.749112+08:00。8080 Mock；本轮只做API/导出/JS语法验收，未运行浏览器、无截图、未宣称视觉通过。

入口 http://127.0.0.1:8080/ → 左栏项目管理页 → 顶部项目选择“Phase4 最终验收（15min/整数任务）· a02bf5”。唯一项目ID `a02bf5f12c1a44de`。以前同名控制项目保留但不是本次复验对象。项目改名仅改新项目显示标签，冻结输入中的旧名称/hash不变。

| 场景 | 冻结任务ID | 应有状态 |
|---|---|---|
| energy_15min | 67258fb195f44870 | completed |
| thermal_15min | 15cc1fbe5b80472e | completed |
| integer_restart_15min | 07c55cb452f7481e | completed |
| integer_deadline_infeasible_1h | cce3619f308f414e | failed |

## 逐项截图/核验点
1. 项目/场景页选energy_15min，展开“完整草稿JSON（高级）”：model.dt_hours=.25，axis.step_minutes=15、length=96。截图唯一项目名、场景、时间轴；默认旧1h项目不得自动转96点。
2. 左栏“版本化仿真任务”，点击对应任务，核对上述ID、completed、冻结输入和代码hash=`5df7484ef2b4538c7e20cd8298f716d1345b3ab08b25a767b53c683ad5bef241`。点“查看当时模型与结果”，而非重新运行/改旧任务。结果96点，物理0至23.75h；IT工作32MWh、批8MWh、成本400，不能4倍电量。截图冻结详情及常规结果/审计。
3. 模型/拓扑时间滑块0–95；末端应23:45（非95:00），切0:15与第1步一致。普通Sankey日电量按dt积分。截图末端标签/图；热网时延证明在正式审计，不是示意Sankey。
4. thermal_15min结果目标-10472.655547077002，audit.time_axis=.25，热管delay_h1/delay_steps4；sent12.97250726296558、loss1.297250726296558、delivered11.675256536669023MWh，守恒残差<1e-7。截图RC/热指标与audit；不能强求等于1h目标-10472.343614246043。
5. integer_restart_15min成本12，integer_tasks.ledger应initial1+executed3=goodput3+canceled_lost1，cancellations1、cancellation_cost7、end_state=done。截图普通审计展开。历史进度不重复计本轮电费；取消不能抹掉耗电。
6. 点“下载审计运行包”：allocations/migration_audit/network_dispatch三CSV有step、物理hour、duration_h，满足hour=step*.25、duration=.25；含integer_events_optimized.csv、integer_ledger_optimized.csv、input_snapshot.json、frozen_task_metadata.json。与`/workspace/sim-agent-phase4-evidence/independent_final_v2/integer_restart_15min_frozen.zip`比对；不要只下载任务JSON代替正式ZIP。
7. integer_deadline_infeasible_1h保持failed，详情明确MILP infeasible/连续窗口/截止期；不能伪装零成本成功。截图失败状态及冻结输入。
8. 新建副本/测试草稿（不改旧版本）点“显式展开为15分钟草稿”，只改编辑器并提示保存→发布；有资源绑定先实体化否则明确拒绝。次目标选“锁主目标后最小gross”→“写入编辑器”，保存发布才生效；旧任务hash/结果不得变。
9. 打开一个旧1h完成任务：24点、原结果/输入hash未变。不要清理旧项目、删除历史或编辑冻结任务。

原输入`cases/paper_reproduction/phase4/inputs`；原始请求/正式ZIP`/workspace/sim-agent-phase4-evidence/independent_final_v2`。年度/三级/VCC未适配15min应明确失败，不能默默按1h继续。浏览器发现真实缺陷保留截图/项目ID/任务ID/期望，不用Shell操控浏览器。
