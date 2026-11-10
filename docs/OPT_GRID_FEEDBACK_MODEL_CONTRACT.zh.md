# G08 独立电网—计算反馈模型合同（Phase6，可回放阶段，不是整篇论文复现）

## 正常产品路径与默认兼容
- 模式 `model_kind=opt_grid_feedback`；普通项目「新建电网反馈独立场景」或JSON导入→草稿保存/校验→不可变版本→冻结任务（cost任务封套、关闭AC）→运行→历史只读→正式ZIP。不是独立脚本代替产品，也不签出成24h会话。
- 四信号从同一基态分别出发，默认全跑；`selected_signal`仅选择主要展示，未改ISO默认成本目标。旧日模型、年度CFE、运行碳默认口径不变，旧快照不回写。日资源绑定/日拓扑/AC被显式拒绝。
- 新模式 **仅UTC整点、1h、1–168小时** `benchmark`或`original_data_subset`。不支持15min、完整8784年度、年度CFE联合清算、三级滚动；超过长度直接校验失败，绝不截断/删除闰日。原输入子集必须给完整闰年源轴和精确索引，并与时间戳逐项一致。

## 物理出清、目标及单位
- 连通、无损DC网络；发电MW、负荷MW、线路额定MW、`b_mw_per_rad`、相角rad，参考节点0且默认±π角箱（不可超过π）。硬节点平衡、硬线路和机组上下界，无弃负荷/虚构供电/平衡松弛，不为论文放松物理限制。
- ISO目标：`Σ(c_USD/MWh + carbon_price_USD/t * g_operational_t/MWh)*Pg_MW*1h`。默认显式碳价0，故纯经济出清。允许显式正碳价，但必须独立报告纯运行费用、货币化ISO目标、运行排放、LCA附加排放；`lmp_usd_mwh`是ISO目标导数，不假称纯燃料成本导数。
- 固定PUE将IT等效工作MW映射为电负荷MW。每小时 `Σ work = Σ original_work`；每站原负荷±flexibility、站容量、每次信赖步长均硬约束。无取消/弃任务/延期，不能通过少做工作“减排”。本模式是**空间流体工作**，不含整数作业、截止期、GPU吞吐、跨时迁移/储能/热量。它们仍由既有日模式提供各自能力。
- 费用边界只含全系统机组可变运行费及显式碳价后的ISO目标；actual_cost_delta为前后差额，既不是数据中心账单/收益/利润，也不含年化容量投资、迁移交易费、输电服务费或售电收益。要比较运营商净收益需另有报价/合同模型，本阶段不假报。
- 迁移是完全图、无路由容量/延迟/价格的一阶流体调整；只输出规范配对的净工作迁移，不等于论文所有`s_ij/d_ij`或G01路由报价完整实现。电网线路是输电，不是计算迁移网络。本阶段没有DC OPF-FLEX式(7)的全局联合优化，不能宣称反馈固定点是该全局最优。

## 四信号与闭环
1. 基态成本DCOPF最优→每站信号。
2. `lmce`：系统运行排放的正向有限差分；同时保留负向/半步、原文(5)(6)活跃约束基的解析导数、矩阵秩/条件数/多余绑定行、扰动错误和活跃集切换。负LMCE保留，不夹成0。`validated_basis`必须与这些FD通过稳定性检查才可在strict策略继续。
3. `lmp`：节点ISO目标对负荷的USD/MWh边际价格；`average`：同区域真实发电加权tCO₂/MWh，零出力则无定义而非0；`excess`：同区域未用清洁发电容量的负数MW，**单位不是吨碳**。
4. 工作调度首先最小相应信号×PUE×工作；再锁主目标最优值（默认放宽0）最小gross步内工作变化。单独导出主目标最优/次目标后值/显式公差。LMCE/average与LMP/超额容量的代理目标不混成一个量纲。
5. 根据候选真实电负荷再次ISO出清；仅为物理可行性做显式记录的回退缩步。**不按实际减排择优过滤**，所以反而增排的策略、线性预测失效反例真实保留。
6. 每步重新计算信号，检查固定点/周期/迭代上限/信号不稳/调度失败/再次出清失败。默认完成的是实验评估，不是全局最优；每个LP必须optimal，限时/不可行不当成功。`require_convergence=true`下任一策略未固定点则任务真实failed，保留partial_NOT_ACCEPTED，不生成results.json。默认`unstable_signal_policy=fail`停止相应策略；只有显式allow_directional才使用方向导数实验。

## 碳、钱、归一化与CSV独立重算
- 运行排放=全电网ΣPg*g；LCA附加ΣPg*lca独立分账，**不加入运行LMCE**，不把站点消费分摊当实际系统减排。
- `predicted_operational_delta_from_initial_tco2`=初始LMCE·最终净电负荷变化；actual=末次真实再出清全系统排放−基态排放。正Δ为增排，负Δ为减排。不能把excess的MW²目标下降冒充tCO₂下降。
- 单步预测纯运行费用取纯费用FD，ISO目标预测取LMP；两者分别与真实再出清变化对比，避免正碳价时误标口径。
- 归一化分母allowed_work=Σε·baseline（原文式定义的弹性总量，不是假称网络可路由的最大gross）；actual_work用最终相对基态净再分配的绝对值和/2。逐迭代迁移是同一静态时段内候选调整的规范账，不是已经真实执行的多次工作/实测网络流量；迭代gross与最终net分开，不将数值迭代计成额外完成的任务。
- `generation.csv`：每次接受的发电、节点、可用容量、USD/MWh、运行与LCA系数；`lines.csv`：潮流/额定/相角/导纳；`work.csv`：原工作、实际工作、PUE、电负荷；`migrations.csv`：非空规范工作迁移（MWh）；`signals.csv`、`basis.csv`、`iterations.csv`记录导数/活跃集/目标锁定/失败/回退。
- `model.json/input_snapshot.json/task_metadata.json`保留原输入/来源/代码和求解器标识，results仅汇总。失败ZIP没有accepted results.json；可有partial_NOT_ACCEPTED.json和过程CSV。独立验证器只读这些冻结文件，用SciPy发电变量/PTDF消去相角，与产品Pyomo角变量模型不同；若成本退化，用独立成本最优面排放上下界，不能以任意某个机组解当唯一真值。

## 原文与原数据锁定、不能宣称的精度
- 原文现存PDF首页明确 **arXiv:2105.09120v1, 19May2021**，SHA256 `f40b0df886e4db4af0c92563b9d6f37b5b34b21e6b13ff953718c0e7e48c07a1`。p2(1)(2) ISO/负荷调度，p3(3)区域平均/(4)超额/(5)(6)活跃基和LMCE，原PDF共8页；p4式(7)、p5 SecIV与RTS试验；p6 TableI实际与TableII预测不可混淆。
- 现有RTS公开文件73节点/158机组/120线路/2020年8784小时；`cases/paper_reproduction/phase6/raw_manifest.json`同时列原URL、bytes、SHA256、Gitblob。全8784行负荷仍完整保存；本阶段用闰日索引1416–1419的**4小时原输入子集**，非合成负荷，未删闰日。没有跑8784闭环；本阶段上限是实现范围，不声称已实测证明全年度资源不足。
- 原文件URL在GridMod/RTS-GMLC master，**不是作者发表时commit证据**。原paper节点3/7/28/70到rawBusID103/107/204/322用“1-based原始行序”假设；未拿作者代码证实。源CSV只有civil Year/Month/Day/Period无时区，显式变体采用UTC，不声称作者时区已核实。
- 原文Pmin=0/Pmax×1.5在变体显式应用。原fuel heat-rate积分构造满载平均线性热耗，`Btu/kWh /1000 = MMBtu/MWh`；费用=heat*FuelPrice+VOM，`lb/MMBtu*heat*0.00045359237=metric tCO₂/MWh`。线路b=100/(Xpu*tap)，原tap0解释为1；基准100MVA假设明列。paper仅称carbon tons，本文统一metric tonnes，**不以未对齐吨制的数值宣称TableI复现**。
- 四小时变体以原PMax静态可用容量替代未接入的小时风光；这不是原作者小时VRE。储能/同步调相机发电可用容量显式0，未允许无SOC的免费储能。确切作者commit、小时VRE、节点映射、线性成本/排放处理仍需逐项对齐；已有公开RTS内容可以扩展，不把“尚未接入”说成“外部数据不存在”。
- 因上述模型差异，真实RTS子集只检验**所声明变体**的闭环/独立LP/碳策略与审计，不是Lindberg TableI/II或全年A级复现。合成负LMCE/拥塞/零变化反例只作解析边界，不算论文精度。

## 页码纠错（不改历史）
首次输入来源注释曾误写p4SecIV，独立pdfinfo/逐页formfeed复核发现PDF实际8页，试验SecIV在p5、两表在p6；源PDFv1/hash未变。已纠正公开预置的证据注释并发布同场景v2新任务，原v1冻结任务/ZIP保留；数学输入逐字投影相同，不改历史来源快照。
