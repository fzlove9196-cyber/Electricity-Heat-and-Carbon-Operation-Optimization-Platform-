# Phase7 离散GPU可复制验收

详见../../../docs/OPT_GPU_MODEL_CONTRACT.zh.md、PAPER_REPRODUCTION_PHASE7.zh.md及BROWSER_REPLAY_PHASE7.zh.md（实际根路径为项目docs/）。本目录不含.env、设备命令或现场调度状态。raw为公开作者原CSV/XLSX、论文分页文本及README/来源hash，不修改原表。

1. 同现有环境启动正常8080 Mock后，用独立空证据目录运行（会在正常项目新建自己的验收项目/场景/版本/任务，真实失败保留）：
   `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=cases/paper_reproduction/phase7 python cases/paper_reproduction/phase7/acceptance_api.py /workspace/new-phase7-acceptance`
   验收工具不导入app。原箱内6个旧task可hash验证；不存在的旧task不凭空重建/宣称历史恢复。若同目录已有索引，会复用已经冻结的本目录自建任务，避免覆盖；有意的冻结重跑会新建task。
2. `PYTHONPATH=cases/paper_reproduction/phase7 python cases/paper_reproduction/phase7/data_reference.py /workspace/new-phase7-acceptance`：独立32/16留出、原Gitblob、Fig5实际/预测时间对齐敏感性。
3. `PYTHONPATH=. python -m pytest -q tests/test_opt_gpu_phase7.py`：27产品回归；不算17独立门。完整pytest仍需原外部Octave/OMC/ParaView与原oracle，缺失要保留失败/跳过，不改测试绕过。
4. `independent_reference.py`的`reference(model)`另构稀疏SciPy MILP（同HiGHS后端，非完全独立求解器）；`enumerate_small`三个小例分别穷举27/27/6561动作序列；`load_zip/audit`可从正式ZIP六CSV独立重算电费、逐任务q/容量/时间/SLA/留出。不得用产品结果当LP模型的输入决策。
5. `build_inputs.py`可从已有phase2 raw或随包raw重建公开预设；固定4训练帽/2留出帽。不要改划分以追求更好RMSE，也不要把6h合成工作/9h时域/idle100W反事实协议标原现场负载。

本箱历史入口见证据索引 `/workspace/sim-agent-phase7-evidence/api_acceptance_index.json`，不应拿别人的私有历史库复制到新环境。`critical_compatibility.py`仅为当前箱的已知公开Phase5/6原冻结控制重跑，其他环境无这些ID时不能冒充通过。

额外JS单元：`node cases/paper_reproduction/phase7/check_ui_labels.cjs <证据目录>/ui_label_fixtures.json`调用真实renderGpu但仅stub字符串sink，3例校准/留出/失败明确分开；不是浏览器，不并入17独立门或27pytest。

真实GPU功率/任务控制命令从未执行。原论文33现场实验、212jobs、原工作长度/事件状态与精确混合Fair/resize尚未整篇复现；界面尚未通过真实浏览器，Shell可达不代表视觉通过。
