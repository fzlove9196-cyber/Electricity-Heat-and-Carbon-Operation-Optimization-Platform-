# B07可复制根因与验收（非原论文最小合成精度）

本地cwd /workspace/sim-agent，解释器 /workspace/sdco-env/bin/python；安装Pyomo6.10.1/HiGHS1.15.1，详细版本/源文件hash在 /workspace/sim-agent-b07-evidence/installed_dependency_provenance.json。没有仓库远程。

- 单进程独立诊断：`PYTHONPATH=. /workspace/sdco-env/bin/python cases/paper_reproduction/phase5/b07/minimal_collector_race.py simplex unsafe /workspace/proof-unsafe.json`；unsafe预期真Duplicate symbol错误写JSON与完整.traceback.txt，软件诊断脚本退出0表示预期行为出现，不表示LP成功。把simplex换ipm也应相同；mode换serial/protected应foreign0、objective7/3。
- 机制回归：`/workspace/sdco-env/bin/python -m pytest -q tests/test_solver_execution_b07.py`，14case；其中8探针不可另算论文实验。
- 已有原输入/正常项目新结果：`/workspace/sim-agent-b07-evidence/original8760_replay/ui_entries.json`，3组完整8760、每组26280行，不是缩日；export.zip保存实际冻结输入与正式结果，无最优决策作输入。
- 只读独立复审：`python3 cases/paper_reproduction/phase5/b07/reaudit_frozen_exports.py /workspace/sim-agent-b07-evidence/original8760_replay`；不会运行模型。保留CSV/JSON分拆合同，旧结果三表逐行精确比；20唯一门含状态/冻结/守恒费用/SciPy最优/变量归属/旧历史/并发队列。
- 真正重跑三组长年：`python3 cases/paper_reproduction/phase5/b07/replay_original8760.py NEW_EMPTY_EVIDENCE_DIR`，只在Mock健康/无活动域/无正在运行任务时，确认不是重复已有作业后执行。创建新task，不覆盖旧task；三请求同时提交、由产品FIFO串行管线，排队不算求解器600s软限。
- 原SciPy参考程序`../reference_full_scipy.py`，已有结果/workspace/sim-agent-phase5-evidence/scipy_original8760；成本473264255.7724196、397176972.500098、383708646.6516878EUR。当前产品差均<0.000136EUR，声明验收0.05EUR；CSV守恒/约束另核，不只金额。发布f40不含DSM，manuscript是论文公式变体。

实际全量351当前342pass6fail3skip：外部CLI及原临时oracle丢失，apt代理HTTP500未绕过，不声称全通过。当前52独立检查、21兼容、8机制（已含14回归）各自计数。旧SymbolMap失败ZIP、46/1tee失败、首轮队列断言19/20、投影重审19/20、180s客户端超时都保留；不要删除或把它们改成pass。

完整背景仅两次600s未最优，四配置未全跑；LMCE/GPU/完整TSUSC/SustainDC未完成。浏览器入口、旧1h成功、热/非空15min迁移/CFE成功失败/截图点见docs/BROWSER_REPLAY_PHASE5.zh.md。备份/恢复/交付限制见docs/B07_ROOT_CAUSE.zh.md及E/release_validation.json。只复制公共案例，不包含.env、密钥、私有projectpayload/数据库。
