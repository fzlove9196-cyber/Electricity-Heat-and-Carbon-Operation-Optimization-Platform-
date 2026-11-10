# Phase5/B07真实浏览器复验（父任务computerUse；本批无截图）

入口 http://127.0.0.1:8080，先硬刷新避免旧JS缓存。普通项目→场景→已发布版本→仿真任务→查看当时模型与结果→下载正式ZIP。不是只看论文专页，不重跑3个长年任务，不覆盖老failed/草稿/版本。执行Python摘要 `7cbffe86052e9d73e65d8fbd6bcc7ff5b37875d197c38ab61ce6702c6ed3536f`；冻结rerun保持旧snapshot/code_hash，execution_code_hash是当前值，二者应分开。

软件/API/CSV已测不是视觉证据。当前全量实际342passed/6failed/3skipped：环境切换后octave-cli/omc/pvpython缺失、旧/tmp基线指纹丢失，apt源代理HTTP500；未弱化测试，不得说351全过。先前337passed已等待真实exit0，另有独立日志。浏览器不能替代这6失败/3跳过的环境补验。

## 1 新的短控制项目（热、非空迁移、成功和真实failed）

项目 `edb7b7959b024d03`，名称 **Phase5 年度CFE/热边界验收 · a3945c**。

|案例|场景 / 版本|正式任务|期望|
|---|---|---|---|
|thermal_boundary_15min|3a8e676b70f94128 /2747515575cc44c3|da4c5d48e4344406|目标−10472.655547077002，96点、dt0.25、delay1h=4steps|
|migration_s5_15min|8b27336539ee4ebf /26ef3579e7d649cc|0ca2cc19587e460c|福利72000、目标−72000、gross240MWh|
|analytic_RES100_gap|0a1777e62d57463d /a75887f30b7640a7|214cf193290142f9|cost4EUR、年RES100%、论文CFE50%、小时缺口1，不是24/7|
|analytic_CFE100_infeasible|90f2a31c238247bb /09469a8e85b44f11|fdb016abe6f44b60|真实failed，无伪造hourly；可下载输入/错误/新traceback|
|analytic_CFE100_storage|6c7dd133228d4867 /288e9f1581474140|fafed10efe0c434c|cost4EUR、逐时缺口0，SOC来源/年容量分列|
|analytic_storage_origin|585c9706c7cc4f45 /03ae2d36012f4cb7|b28e027d71e842de|cost2.2、绿灰SOC各0.5；效率1的解析控制|
|analytic_paperCFE50|0cb7f1100f5748fe /1706fd1da84c4101|1c52c4e1a86c41da|cost3，不是每小时50%地板|

热截图点 `heat_kpi_boundaries.png` / `heat_timeaxis.png`：KPI“终端实际用热”11.5MWh_th，DC列“热泵注入”13.05495466397364；发送12.97250726296558、管损1.297250726296558、到达11.675256536669023。到达−取热=接收TES损失0.17525653666902236，源TES损失0.08244740100805749；两SOC各0.5→0.5。新需求曲线积分11.5，不是旧单节点数组12。正式heat_nodes/heat_pipes CSV、results.json、audit_optimized.json完整分账，残差约1.28e−15。原15cc1fbe5b80472e历史不回填。证据：本批E/thermal_boundary_15min_frozen.zip、supplemental_checks.json；E=/workspace/sim-agent-b07-evidence。

迁移截图点 `migration_gross_net_dt.png`：allocations864行、migration288行、192个非零时段；三表duration_h0.25、hour=step×0.25（不为空，不拿空表冒充）。独立逐job/站/时段/费用重算残差0，lexicographic主目标放宽0；gross优化前1867.5→240，但第一阶段替代最优解可不同，不硬比旧1585。证据E/migration_s5_15min_frozen.zip与supplemental_checks.json。

年度小输入截图点 `annual_RES_vs_CFE.png` / `annual_failed_preserved.png` / `storage_origin.png`。冻结相同成功小输入另有 f06ceb85a5fe45b9，不覆盖fafed10。

## 2 当前B07修复后的三组完整原8760（正常项目历史，只看不重跑）

项目 `43437ec6c9cb4eb7`，名称 Phase5 年度CFE/热边界验收 · cda402。

- riepin8760_f0: scenario `b25e748264ca4981`, version `d9dffa6782ac452c`, **新成功task `ebd6070fb6354d81`**；旧task `979d1b3824114c60` 保留。cost 473264255.7723827 EUR，input_hash `2429663c65e8b5d46a94ec0fad35653136162801bf17cab63bdc02e3517989ac`。
- riepin8760_f40: scenario `62112ee0cbba4fb6`, version `4670d05b7202441a`, **新成功task `7857b7977df14594`**；旧task `36fd6e75ba634101` 保留。cost 397176972.5000959 EUR，input_hash `4a75d8583bca2d1c797765a1128db5c3aa756841192deda3f31d8640d521d7a5`。
- riepin8760_f40_manuscript: scenario `fe0902ab792d457c`, version `3b3d795e9ffb42a5`, **新成功task `17ba03251e3441ac`**；旧task `5d8d5fc6edfb4e23` 保留。cost 383708646.6518236 EUR，input_hash `198358a388582eeaedc07086ec2068d753bfa47dc5cf677ec2a02acdc3fd8e6c`。

每组全8760×1h×3站=26280行；24行只是预览，选择起始小时8759可见末行。原气象2013、规划2025、源轴明确UTC；首小时北京时间2013-01-01 08:00、末小时北京时间2014-01-01 07:00（中国标准时间）。容量MW/MWh全年仅一次投资；三份额、清/灰来源、超额/缺口分列，100%CFE最大数值缺口≤1.43e−14MWh。不是24h日模型/AC/三级，不会偷偷建立日session。

执行域审计每组 declared_variables=solver_variables=420492、foreign_variables=0，ticket1/3/2，queue wait约0/256.544/73.892秒；solver软限不含排队。截图 `annual_original8760_current.png` / `annual_final_hour_origin.png` / `annual_execution_identity.png`。ZIP在E/original8760_replay/{case}/export.zip；独立参考最大目标差0.0001358EUR、守恒≤4.25e−11；采购模型不是完整背景电网/四配置/论文全部图表。

旧两failed **36fd6e75ba634101、5d8d5fc6edfb4e23**仍须能选中和下载，显示Duplicate symbol/Unattached VarData，不被新成功覆盖；截图 `symbol_map_failed_history.png`。本批不是换算法逃过：两算法未保护最小复现均真失败、保护均通过；正式全年使用与旧B同dual-simplex。

## 3 零用电站份额

原项目 `bbf306de58ae4b1d`，zero_site_before_rate_fix：旧failed94820c4c112846a1保留；当前同冻结输入新成功 **f763a073dcb4485e**，cost2.00002，B用电0，三份额JSONnull/UI“—（无用电）”，不是0%/100%/NaN。截图 `zero_site_null_rates.png`。E/zero_site/zero_site_check.json、zero_site_rate_fixed.zip。

## 4 明确旧1h成功历史（只读，不能拿新任务冒充）

项目 `c553df86964f4552`（中卫 · 产品化闭环验证），scenario `95c7a44f13244030`，version `76817b1aebdf4406`，completed task **2e8c374986114082**（中卫公开气象实际求解）。24点/dt1，旧存目标−2416428.7（历史四舍五入值，非新优化逐位承诺）。

版本hash `3e5bd08aa400851f3148d688bd84f2ac544488a8d1d77cb277a57937c5b2138a`；input_hash `bd56f868a99e3acf6d9e4c1c12c6b0eace6566e9ea88f808eaeb78d334da4ee4`；完整task canonical hash `53190214c5d6743cea410ff79a2b05a4506d3cb415f414ec812475450c90311a`。原energyv1前缀8890209b6212591e不变。截图 `old_1h_success_hash.png`；不要改旧模型/重写旧结果。原48versions/49完整tasks最终API逐条hash见E/history_preservation_final.json，不打包私有旧1hZIP。

## 5 新UI正常流程与执行域只读状态

普通项目→新建独立场景→公开年度CFE下拉→新建年度CFE独立场景→匹配/目标/弹性/空间/DSM/超额控件仅写编辑器→保存草稿→校验→发布新版本→cost且关闭AC→创建冻结任务。用新UI复验项目，仅运行2小时明确benchmark小输入，不改本批上述冻结案例，也不重复8760。截图 `annual_config_newversion.png`，确认原始JSON单位/来源、数据长度、地域/新增校验能达。

普通“仿真任务”页 pfSolverGate 每3秒只读轮询 /api/solver-execution/status。空闲应显示“Pyomo执行域：空闲；等待0项”；截图 `execution_queue_idle.png`。运行中的状态可包括排队，队列时间不得算成solver软限时。真实三请求并发/单持有者/最多4等待者已有E/original8760_replay/execution_status_samples.json，只是backend证据，不是截图；若需视觉等待态，父任务必须通过正常流程实际触发并保存，不能伪造。本批未做浏览器验收。
