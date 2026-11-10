# 产品基础层端到端验证

## 复现
```bash
cd /workspace/sim-agent
PYTHONPATH=. RAG_PRELOAD=0 /workspace/sdco-env/bin/python cases/product_foundation/run_validation.py
/workspace/sdco-env/bin/python -m pytest -q tests/test_product_foundation.py
```
每次会创建新的本地验证项目/模板/场景版本/任务，不覆盖既有版本。测试没有调用真实交易系统。

## 输入与证据
- 项目等值场景：`cases/zhongwei/zhongwei_summer_coupled.json`、`cases/shaoguan/shaoguan_summer.json`、`cases/ulanqab_cicdata/ulanqab_cicdata_summer.json`。
- 公开气象：既有 `cases/common/climate/*_2024-01-01_2024-12-31.json` 中的2024年7月1日逐时温度。来源Open-Meteo历史再分析，原URL与文件SHA256记录在通用库资源和结果JSON中；不是现场计量。
- 输出：`results/workflow_validation.json`；包含可在8080应用中检查的project/scenario/version/task ID及任务会话、输入摘要、AC诊断与误差。

## 验收含义
每个项目必须经过“模板独立复制→公开气象资源版本绑定→静态校验→发布版本→冻结任务→调用原求解→同输入直接求解对比→原快照重跑→拓扑修改→写回发布新版本→检查旧版未变→恢复历史模型与结果”。直接复核使用任务实际输入（含cost目标明确置零碳权重），避免与原预设不同目标错比。

数值一致性误差只来自界面任务摘要保留0.1元的四舍五入；完整结果在full_result内保存。这里验证的是产品层与原求解器接线一致性，以及这三个工况的供电/热/交流边界，不是独立证明每个数学模型绝对准确，也不是正式市场结算验证。已有公开基准中的DR基线未通过项保持原警示。

本轮额外修复单母线无支路时的空max和交流校核NaN最大负载率问题；A01电池方向已有回归继续验证。完整实施、API对象和用户路径见 `docs/product_foundation.md`。

## 三项目本次实测结果（2026-11-06T13:13:58.118611+08:00，北京时间）

公开7月1日温度叠加原等值场景；未绑定风光/任务沿原预设，并非同日整套实测。

| 等值项目 | 求解 | 热安全 | AC收敛/电压/容量 | 最大支路负载率 | 同输入直接求解成本误差 | 冻结重跑成本误差 |
|---|---|---|---|---:|---:|---:|
| zhongwei | optimal | True | True/True/True | 42.35% | 0.0257元 | 0.0000元 |
| shaoguan | optimal | True | True/True/True | 62.62% | 0.0485元 | 0.0000元 |
| ulanqab | optimal | True | True/True/True | 77.21% | 0.0378元 | 0.0000元 |
