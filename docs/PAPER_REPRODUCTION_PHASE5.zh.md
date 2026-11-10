# Phase5：热边界纠偏＋正常项目年度CFE

本批依用户t67/t69授权在仅存本机的 `/workspace/sim-agent` 实际修改。未克隆/新建/接入仓库，无产品远程地址/PR；论文公开仓库只是外部研究来源，不是产品远程。没有用Shell驱动浏览器、读取密钥/私有数据库文件或启动外部服务。真实视觉复验仍由父任务派computerUse。

## 1. 先独立核对浏览器原包：11.5≠11.675256是合理边界，另有真实展示bug

原文件 `/home/box/Downloads/run_Phase4 RC_TES_heat-node-pipe conservation (SYNTHETIC)_a1b847074625.zip`，原任务 `15cc1fbe5b80472e`。

|边界|全精度MWh_th|含义|
|---|---:|---|
|热泵源注入|13.05495466397364|进入plant节点|
|管段发送|12.97250726296558|进入延迟管道|
|管损|1.297250726296558|发送量10%|
|管段出口到达|11.675256536669023|到load节点，**尚未经过接收储热/终端取热**|
|终端实际取热|11.5|实际节点需求11.5；售热和锅炉碳抵扣的正确分母|
|plant储热损失|0.08244740100805749|该节点SOC初末均0.5|
|load储热损失|0.17525653666902236|到达−取热；该节点SOC初末均0.5|

全局：源注入=终端取热+管损+两节点储热损失+库存/在途变化，独立残差−2.28e−15MWh_th。目标−10472.655547077002、售热11500元不应为了同数而改变。

**独立确认的真实实现bug**：多热节点求解以各节点需求为准（11.5），但dispatch/曲线仍取旧单节点`hn.demand_mw_th`（12）。已改为节点需求和，修正新运行的需求展示；不是求解器把供热积分错了。

新增`heat_boundary_audit`，明确源、管段到达/损耗/在途、节点收发/终端/储热充放/损失/库存变化；结果UI解释不同边界，KPI名为终端实际用热，按DC表另标热泵注入。正式`results.json`在存在新账时添加heat_boundaries，另导出heat_nodes/heat_pipes CSV。管段旧`delivered_mwh`兼容保留并明确是出口到达，另有arrived_mwh别名。旧任务存量数组/快照不回填，使用相同输入创建新任务来观察修正。

这是SYNTHETIC守恒控制，不算论文原精度。

## 2. 已实际接入年度CFE，不把日24h伪装为8760

实现文件：`app/opt_cfe.py`、`app/opt_cfe_api.py`、`app/foundation/service.py`、`app/foundation/api.py`、`app/main.py`、`app/scenario.py`、普通项目/任务UI；完整模型合同见 `OPT_CFE_MODEL_CONTRACT.zh.md`。

- `model_kind=opt_cfe`独立模式，完整源UTC年8760/8784×1h，气象年/规划年分列；全年只投资一次风光/储能容量，所有小时运行与同一容量耦合、SOC全时域闭合。
- 论文年累计小时CFE分数、严格每小时地板、年RES份额三政策分开；100%CFE时每小时无清洁缺口，超额从credit剔除，未发电潜在弃电从不记credit。
- 两类green/brown SOC跟踪，外网充电按当时CFE份额分源；本地新增同竞价区合同条件校验。合同元数据不是对现实PPA/额外性的自动核证。
- 空间完整虚拟工作流＋日内守恒DSM，实际各站负荷受(1±f)约束，费用原1e−5货币/MWh。迁移工作不是跨区输电，不是个体VM截止期/GPU动作。
- 费用单位/年化投资及8760运行费用边界明确；原背景欧洲OPF、内生电网CFE/LMCE未纳入本产品采购目标。
- 正常项目建场景→JSON/匹配/目标/弹性控件→保存校验发布→冻结任务→运行→历史年度结果→完整正式ZIP；旧日模式、历史与默认目标不变。
- 自包含全年数据冻结，无隐藏数据路径；长度/闰年/时区/步长/错地域/非新增/负价/混用日AC和目标均拒绝。短benchmark明确非全年，不拿解析合成案例声称原论文精度。

## 3. 原输入、原代码实际尝试及不能抹掉的差异

原34,093,522字节NetCDF已在本地，Git blob `e95dd9aba48f997b9ae27ca4df5123790b6f7a2e`，本轮不重复下载。参考原代码commit `6e3bd6e2bdcaf8ff25393218b09c737a018460bc`、`solve_network.py` blob `188a75df0b0578111d244ad002b779e797dce69c`，逐文件URL/hash见`author_sources/manifest.json`。原文p4式1–2、p5式3、p6式5–7。

**原发布代码的真实拓扑差异**：add_dsm建立3总线/6link；strip_full_network只保留DC/原区/battery，DSM变0/0。代码证据原883–904行、运行前后`author_reference/f0_topology.json`。因此正常预设分“发布代码有效拓扑f0/f40（无DSM）”与“论文式6 f40＋日内DSM（变体）”，不能假装原默认配置已同时启用DSM，也不能调模型凑论文图。

原Python3.13参考环境缺旧numpy wheel/依赖锁冲突，另建隔离Python3.11/PyPSA0.26/linopy0.3.15/xarray2024.2环境，不改产品依赖。原Gurobi改HiGHS并明示差异。初稿harness漏`__main__`的全局n，补齐后保留日志，归参考脚本而非作者bug。

**真实未通过**：原作者全背景模型f0与f40各尝试600秒，约902315变量/1909741约束；IPM未达最优，随后原后处理读取未成功结果抛KeyError。日志`author_reference/run_v2.log`、`f0_FAILED.txt`、`f40_FAILED.txt`，不把其中objective0或近最优迭代当复现成功。f0末轮原始primal473266505/dual473260853附近，目标间隙未闭合。不是缺原数据，也未证明产品算错。

另一个缩背景PyPSA诊断因空StorageUnit变量先失败，固定零占位后仍IPM/交叉恢复停滞，终止的是该冗余研究进程而非产品任务，失败和discontinued_note均保留，不计通过。

真正独立定量参照使用另写SciPy稀疏矩阵，**保留全部原8760小时和原风光/成本**，不是缩小天/合成曲线：perfectCFE、gridCFE0、excess0可证明所有灰进口/灰储能贡献为0；完整等费虚拟图最小费用=fee/2×净迁移绝对量和。该参照是同口径采购子模型，不称完整背景Europe OPF已复现，未用产品函数/最优决策当输入。

Phase5A已核实：f0产品473264255.7723827EUR，独立矩阵473264255.7724196；f40发布有效拓扑产品397176972.5000959EUR，独立397176972.500098；f40论文DSM变体产品383708646.6518235EUR，独立383708646.6516878。全时域独立重算守恒/容量/分源/匹配/成本，非只比总金额。

## 4. 明确未完成的范围

- 四原配置/全部flex档位、原Gurobi/完整背景欧洲OPF/多轮内生grid-CFE、论文所有图与收益斜率尚未验证。
- G08内生LMCE→算力调度→ISO再出清、G07离散GPU功率帽/吞吐SLA仍未实现，均是用户已批准的后续任务，不能写成完成。
- G04原Azure聚合/RNG/144h滚动Table1、G06原SustainDC同机架/HVAC/水塔31天策略、E01原Ma修改IEEE39及轨迹/线性化仍保留原缺口。
- 年度CFE仅1h/UTC自包含输入，不支持15min、日资源绑定/拓扑签出/AC/三级运行；不把新独立模式冒充所有旧入口统一全年。
- Phase5A正式IPM f40耗时692.654秒；同矩阵dual-simplex诊断133.536秒后，最终引擎已接串行dual-simplex并重新跑正式API三组全年。数学LP不变，诊断本身不计独立精度；求解器软限时仍非端到端硬墙钟。最终数值/耗时见运行总结，不倒写A历史。
- 本批没有浏览器截图/视觉通过结论，先前Phase4浏览器只覆盖用户已列出的项目与口径，不称此前全面验收。

## 5. 保全与恢复

修改前公共源码安全备份 `/workspace/sim-agent-backups/20261107-114556-phase5-public-source`：910文件、public-source.tar.gz、逐文件manifest、RESTORE.zh.md。排除.env/秘密配置、数据库、会话/用户历史及工件；不把私有项目负载打包。持久对象经实际公开API保存修改前全记录canonical hash（48版本/49完整任务及项目/资源等），最终逐条复核，不只比较数量或快照子集。

恢复先确认无running、停止原8080进程、另备份当前公共源码，核对manifest再按RESTORE恢复；不触碰被排除的配置/数据库，也不自动删除新增文件。前批重启检查`idle_restart_check.json`为同一Python流程assert无running后才发SIGTERM。B07执行期间环境切换后旧supervisor未存活；确认无8080/无原app后原start.sh恢复同一Mock应用，没有重复服务。不能声称旧PID一直保留。

最终测试/独立门/项目入口/hash/交付包以本目录Phase5运行总结、BROWSER_REPLAY_PHASE5及`/workspace/sim-agent-b07-evidence/release_validation.json`为当前准，原phase5-evidence是前期历史；没有用未终止/未通过的原作者求解补计通过。

## 6. 新发现必须保留的真实失败与修正

全空间弹性1可使站点实际用电0，原新模式后处理对3个份额除零，将有效最优LP标failed。冻结失败任务94820c4c112846a1保留，回归先真实失败后修复。份额分母0现在导出null、UI“—（无用电）”，不是改成0或100%。真实同冻结输入重跑成功，独立解析2MW×1＋2MWh×1e-5=2.00002，原失败完整记录未变。独立HTTP脚本首版误用workload_fee_per_mwh而实际字段spatial_fee_per_mwh，修正并重审同一已成功任务，不新增/覆盖产品结果；首版脚本日志保留。

首个全量335测试因BLAS/模型推理线程过量、缓存RAG测试耗时长在313通过处主动SIGINT，22未执行，不能报全通过；限定OMP/MKL/OpenBLAS线程1后336通过（新增零负荷用例在其收集后才加入）。最终337全量另跑，具体终态见release_validation，不混中断和完整计数。

## 7. B阶段事故历史（保留，不是当前未修结论）

旧B代码37ffa291816205886863fef67d13fda890ef22498842cac3db91705bb8cdb43c曾337回归/21兼容通过，但CFE两个正式弹性任务36fd6e75ba634101、5d8d5fc6edfb4e23真failed：legacy SymbolMap Duplicate symbol/Unattached VarData。曾临时恢复IPM而非根因修复。用户本次要求先等待的当前337任务已真实exit0、337passed/312warnings/318.91秒，代码0a4b1b5fb2b357cef678972151f936f0ae1c59a677036e2355387219488330b5；先完成此步才改产品。旧失败/临时回退/中断记录均保留。

## 8. 当前B07根因与实际修复，不靠换算法/绕开legacy

详细证据在B07_ROOT_CAUSE.zh.md。安装Pyomo6.10.1模块全局_visitor被跨线程重新初始化，A收集到B.y[0/1]，solver._vars混入2外来变量；B parent弱引用失效后都名[Unattached VarData]，base.py1618向legacy_soln.variable取symbol时重名。旧现场没有保存内存/完整栈；本批新受控调度保存同症状完整调用栈，不伪造旧栈。IPM/simplex unsafe都真失败，serial/protected都foreign0且最优7/3；仅控制线程调度，未修改依赖逻辑或伪造解。没有通过避开legacy名字字典掩盖污染。

进程级FIFO锁覆盖四类完整Pyomo建模→表示→solve→load，同线程可重入/异常释放；backend前和update后变量归属fail-closed。正常任务UI/结果/导出含队列、变量数量及执行摘要，只读status可见队列，running可含等待，软限不含排队。另真实发现Pyomo deferred multiprocessing在tee持锁间替换capture_output_lock，首轮46pass1fail留档；在RAG/请求线程前解析延迟回调，不启动子进程或服务、不禁用RAG，独立新进程unsafe/protected证明锁身份/释放差异。当前49靶向通过（35原＋14新）；8机制探针含在14内，不重复算论文实验。

正式用旧B相同dual-simplex重跑原3组冻结8760，未喂最优决策：新f0 ebd6070fb6354d81、f40 7857b7977df14594、论文DSM变体17ba03251e3441ac全部completed。成本473264255.7723827 /397176972.5000959 /383708646.6518236EUR；独立SciPy差−0.00003690 /−0.00000209 /+0.00013578EUR。各26280行CSV独立重算守恒最大4.25e-11、约束违反0、100%最大缺口1.43e-14MWh；每组420492变量foreign0。队列等待0/256.544/73.892秒另账，不以等待超时冒称模型非最优。

原8760当前20门最终重审通过，初次19/20将“其他正常客户端尚活动”当年度重叠失败；重审首版19/20把存储full_result三张表与故意拆CSV的results.json错误全等比较。两次失败日志不删；最终对JSON投影及三个原CSV逐行严格比较、原failed/成功完整记录未变，无额外年度求解。普通解析/热/非空15min迁移/冻结/导出控制32门另过；旧21兼容见最终release_validation。并发首轮旧客户端180s在全年队列等待超时，保留TimeoutError，待无活动域才新目录重跑同21门，未改数字期待。

## 9. 当前整体不是全绿：环境红门/完整背景/视觉未完成

当前完整pytest已真正终止exit1：**342passed、6failed、3skipped、313warnings、656.12秒，共351**（旧337=328pass6fail3skip，新14全pass）。环境切换后octave-cli/omc/pvpython不在，6Fail都指向这些实际缺失；/tmp/baseline_fingerprint.json丢失使原3指纹被原有逻辑skip，未用当前代码生成假旧oracle、未改测试/跳过期待。管理员apt更新Debian源经代理HTTP500，停止不换域/下载二进制绕过。需要恢复受信运行环境及原基线后复验，不能把旧337pass挪来冒称当前351pass。B09是当前真实交付阻断。

完整背景实际仅DKDEPT flex0/40各600s软限，两次Time limit/linopy unknown/后处理KeyError，无被接收最优或可行结果；末次IPM迭代gap1.19e-5/6.42e-4不是认证最优gap。四配置未全部运行，不能写“四配置全都各600秒失败”。背景内生grid-CFE/LMCE、GPU/SLA、原完整TSUSC/SustainDC仍未实现/验证；采购通过不等于八篇整篇通过。

当前Python摘要7cbffe86052e9d73e65d8fbd6bcc7ff5b37875d197c38ab61ce6702c6ed3536f，修改前B07公共源码备份/workspace/sim-agent-backups/20261107-124945-b07-public，恢复按RESTORE.zh.md、先确认无任务及无活动域。历史仅经公开API全记录hash核验，旧私有数据/ZIP不交付。当前证据/workspace/sim-agent-b07-evidence；实施包/workspace/sim-agent-phase5-b07-implementation-20261107.zip、验收包/workspace/sim-agent-phase5-b07-acceptance-20261107.zip（大小/SHA/dry-run见delivery_packages.json，各小于25MB）。新热/迁移项目edb7b7959b024d03、旧1h成功入口及真实CFE成功/failed/截图点见BROWSER_REPLAY_PHASE5.zh.md。没有本批浏览器截图，不称前批全面验收。最终历史/兼容/健康终态以本批release_validation.json为准。
