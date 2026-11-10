# B07：跨模型变量污染和 legacy SymbolMap 生命周期根因

本批遵循用户批准的本地例外：仅 /workspace/sim-agent，无仓库/远程/克隆，无密钥读写。最终状态以 /workspace/sim-agent-b07-evidence/release_validation.json 为准；本文机制证据不代替全量测试或论文精度。

## 1. 保留事故、区分旧现场与新受控调用栈

原失败任务 36fd6e75ba634101、5d8d5fc6edfb4e23 与 ZIP 原样保留。发布失败代码摘要 37ffa291816205886863fef67d13fda890ef22498842cac3db91705bb8cdb43c；f40 冻结输入摘要 4a75d8583bca2d1c797765a1128db5c3aa756841192deda3f31d8640d521d7a5。旧任务仅保存错误字符串，没有当时线程/对象的内存快照；绝不伪造回填“旧现场完整栈”。完整 traceback 来自本批当前安装依赖的确定性最小复现，见证据目录 ipm_unsafe.traceback.txt / simplex_unsafe.traceback.txt。

## 2. 确切机制：collector → solver变量字典 → owner弱引用 → legacy名字冲突

安装版 pyomo.contrib.appsi.utils.collect_vars_and_named_exprs.py:48–58 把 _visitor 放在模块全局。调用会重新初始化同一个 visitor，并在遍历完成后读取 visitor.variables。线程 A 返回前被线程 B 的合法模型构建抢占，可将 B 的 y[0]/y[1] 返回给 A。appsi 的 solver._vars 因而出现两个不属于 A 的 VarData；其 parent IndexedVar 属于 B，B 作用域结束后父对象弱引用失效，两个变量的名字都变成 [Unattached VarData]。legacy adapter 在 pyomo/contrib/appsi/base.py:1618 的 legacy_soln.variable[symbol_map.getSymbol(v)] 建结果字典时，symbol_map.py:151 对重复标签抛出原错误。不是 HiGHS 数值算法导致，也不是缺原论文输入。

cases/paper_reproduction/phase5/b07/minimal_collector_race.py 用 sys.settrace 仅控制真实 collector 的线程调度，不修改依赖逻辑、不伪造解、不给系统喂最优决策。A 的解析最优值 7/3，B 是普通短寿命模型。每种算法各跑 unsafe / serial / protected 三种；unsafe 两个外来变量、owner失效、真实完整 legacy 栈均保存；串行和保护模式 foreign=0 且最优 7/3。IPM 与 dual-simplex 都复现未保护错误、都在保护后通过。因此换算法不是根因修复。

## 3. 产品修复与失败语义

app/solver_execution.py 为整个 Pyomo 建模→表示→求解→解加载建立进程级 FIFO 域，不只包住 opt.solve。四类真实产品 builder（daily、annual、VCC、tiered）都进入该域；同线程递归重入，异常安全释放。入队等待与 pipeline 及 solver 软限分开计量。checked_solve 在 backend 前确认 solver._vars 全属当前模型，并在 update 后再次核验；外来变量直接失败，不改名、不吞错、不换 solver、不回退到假成功。

年度/普通结果与审计导出含 execution_serialization、声明/求解器/外来变量数量。新增只读 /api/solver-execution/status；正常项目任务页显示当前持有者/等待队列，轮询不创建任务。新的年度异常可导出 traceback（不包含 locals）；旧失败不回填。旧 realtime 模式原有显式 rules_fallback 不属于本批新增，也不能因此声称全部业务错误均已消失。

先保持 IPM 完成根因保护的 35 项靶向；保留 rootfix_ipm_source.tar.gz 与 rootfix_ipm_targeted35.json。再用原 B 失败时的同一 dual-simplex（strategy1、parallel off）重验原8760。算法恢复用于同算法前后对照和性能，不是修复理由。声明 solver 软件限时不包含 queue/build/export，不承诺硬墙钟限时。

## 4. 同批发现的第二个依赖初始化竞态

真实靶向首轮 46 pass / 1 fail 的 semaphore or lock released too many times 未删除。Pyomo common.dependencies.py:970–979 的延迟 multiprocessing 回调可在 tee 取得旧锁后把 capture_output_lock 换成另一个锁；最终 release 释放错误对象。minimal_tee_lock_race.py 在独立新进程控制合法初始化时序，unsafe 真抛该错误、protected 锁身份不变。运行域模块导入时显式解析该 deferred callback，早于 RAG/请求线程；不启动子进程或外部服务、不禁用 RAG。tee_unsafe/protected.json 和 traceback 保留。修正后年度+新根因靶向 49 passed；这不替代完整回归。

## 5. 科学验证/回归各自计数

新 tests/test_solver_execution_b07.py 14 项是机制/软件回归；其中 8 个受控进程探针不可再当 8 项独立论文精度。三组原输入全年采购：每组 8760×3站，无采样/聚合，正常项目冻结重跑、ZIP CSV 独立守恒/费用审计、与另外编写的 SciPy 稀疏 LP 比较；不导入产品模型、不喂参考解。普通解析/热/非空迁移控制与兼容21门另记，最终实际通过数见 release_validation.json。

参考原 NetCDF SHA256 28aa779cce75f54eea7a0015b4d690b3eef244204334348055a84fd35811ba2b；作者 commit6e3bd6e2bdcaf8ff25393218b09c737a018460bc。公开发布 strip_full_network 会移除 add_dsm 的3bus/6link，所以 f0/f40 是发布有效拓扑，f40_manuscript 是显式论文式6变体，不混称作者原拓扑。

## 6. 未通过/未覆盖不隐藏

background_nonoptimal_diagnosis.json：实际仅 DKDEPT 配置的 flex0/40 各尝试600s软限，约902315变量/1909741约束；两次 Time limit、linopy unknown、后续 calculate_grid_cfe KeyError，无被接收的最优/可行结果。末次 IPM 日志gap约1.19e-5、6.42e-4只是迭代指标，不是认证最优gap。未跑全部四配置，未复现背景grid-CFE反馈/完整图表，不能用采购对照代替它们。LMCE/GPU仍排队未实现。

执行期间工具运行环境发生切换：旧8080 supervisor及部分新诊断文件未存活；窄范围确认无8080/无存活app后用原 start.sh 恢复同一 Mock 应用，并重做现存机制探针。没有读 .env/DB，没有创建仓库、重复服务或覆盖历史。当前 octave-cli/omc/pvpython 及 /tmp/baseline_fingerprint.json 缺失；apt Debian feeds 经代理返回HTTP500，已停止，不换域/下载二进制绕过。完整 current suite 必须保留实际FAIL/SKIP，不能借此前337 passed冒称新351全通过；详见 runtime_discontinuity.json 与最终测试日志。

恢复：/workspace/sim-agent-backups/20261107-124945-b07-public/RESTORE.zh.md。仅恢复白名单源码；先检查无 running/无活动域再停止服务，不能覆盖持久项目历史。旧私有项目数据只通过受支持API核对hash，不打入交付包。浏览器截图需父任务真实执行，本文没有截图证据。

## 最终观测（中国标准时间，详见release_validation.json）

当前49靶向/14新回归通过；原8760重审20/20、普通控制32/32（合52唯一检查），兼容21/21含7福利、365日新鲜LP、546政策网格和372包执行/输入hash。原48版本/49完整任务、19项目/16模板/8资源全记录未变。整体完整pytest仍342pass6fail3skip，不能称全绿。初次队列范围断言、CSV投影重审错误和180s旧客户端排队超时均保留，分别纠正验收范围/按原导出合同严比/待idle另跑，不改产品结果或重复年度求解。最终8080ok/mock、无运行任务、执行域active null/queue0；截图待父任务。
