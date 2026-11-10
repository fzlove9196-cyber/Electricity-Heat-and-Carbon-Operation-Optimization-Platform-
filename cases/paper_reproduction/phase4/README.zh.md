# Phase4：物理时间步与整数连续任务（本地真实产品）

本轮不接入/创建仓库。默认24h、dt_hours=1、energy任务、migration_cleanup=off保持旧语义；旧项目无需补字段。公开产品路径 `/api/sessions/{sid}/model/load` → `model/rerun` → `results` → `export.zip`，及常规项目→场景→不可变版本→冻结任务贯通。

## 配置与单位
- `dt_hours: 1 | 0.25`：物理小时。`hours=24`是总时长，不是点数；24或96点必须明确匹配。未经转换的24点输入设0.25会拒绝，不能默默重复。
- `POST /api/time-axis/resample-hourly`：用户显式把完整1h场景sample-and-hold为15min，功率/价格/强度逐点保持4份；MWh、release/deadline和物理小时持续时间不变。输出新模型/axis_patch，不改变任何历史对象；策略最优值不保证相同。
- 电池 `SOC[t]=prev+dt*(eta_ch*Pch-Pdis/eta_dis)`；批处理/任务/迁移/发电日电量/碳/电度费用/热量/水量都积分dt；发电和温度坡度按MW/h、K/h乘dt；需量峰值收费不乘dt，未完成量MWh和完成价值不重复乘dt。
- RC空气/结构为隐式欧拉；蓄冷/储热每小时损失`retention=(1-loss_h)**dt`；管段delay_h/dt转换成步数，初始无在途热，末端在途存量不冒充损失或交付。
- `migration_cleanup=lexicographic_gross`：先原主目标至optimal，再约束主目标不高于原最优值+显式公差，最小化gross迁移MWh。默认主目标放宽0；HiGHS原始可行性容差1e-7。输出优先级/两阶段数值/界/公差/失败状态，第二阶段失败保留第一阶段并明确标记，绝不暗加epsilon。

## 整数任务，与energy模式分开
`execution_mode=continuous, duration_h>0, energy_mwh=duration_h*max_mw`，固定功率不可分、同站点连续执行；release/deadline是物理小时且对齐dt。
`initial_progress_h`和`initial_dc`表示本轮开始前已有进度；带进度须release=0。`required=true`强制截止完成，可真实不可行；false允许未完成但计罚/不赚完成价值。
`allow_restart=true`才允许取消；取消丢掉所有进度并返回积压；`restart_delay_h`等待后从零做满duration，`cancellation_penalty_cny`逐次计费。0等待可同一步取消并重启；无检查点、无无损抢占。二进制状态流含pending/running(site,progress)/cooldown/done；同一任务每步只走一条状态弧。
独立守恒：初始历史进度MWh+本轮实际执行MWh=完成goodputMWh+取消损失MWh+截止未完成进度损失MWh。执行电量/重做成本不因取消而删除。正式ZIP含`integer_events_optimized.csv`和`integer_ledger_optimized.csv`。

## 固定输入及独立验收
`inputs/energy_{1h,15min}.json`、`thermal_{1h,15min}.json`、`integer_continuity_{1h,15min}.json`、`integer_restart_{1h,15min}.json`、`integer_deadline_infeasible_1h.json`等都是明确合成物理控制，不作论文精度。
连续性反例：同输入energy模式成本2，整数连续成本101；取消反例初始1MWh+本轮3=goodput3+作废1，成本12（电量5+取消费7）。真实deadline不可行输入保留失败。
`acceptance_http.py OUTPUT_DIR`不导入任何app代码：读取正式HTTP/ZIP，独立区间积分、连续开始时刻枚举、节点/电池/RC/TES/储热/时延守恒、摘要校验和冻结项目负例。
命令：`/workspace/sdco-env/bin/python cases/paper_reproduction/phase4/acceptance_http.py /workspace/sim-agent-phase4-evidence/independent_final`
产品回归：`/workspace/sdco-env/bin/python -m pytest -q tests/test_time_integer_phase4.py`。回归数量与外部独立门分开计，不把重复迭代累加。

## 原作者TSUSC证据对齐，不扩大复现声明
原文 https://arxiv.org/abs/2204.06654 p3–7整数/连续/取消/滚动状态，p7–9和Table1实验；作者 https://github.com/zavalab/JuliaBox/tree/master/DataCenterScheduling 。本轮复用已有材料，四个源文件Git blob SHA逐字节匹配，见`sources/source_manifest.json`，未重复下载。
main.jl L41–42是T168/Tend144，CSV192行；L53–60燃料生命周期强度公式；种子53/21/36均公开。data_gen.jl L13–49依赖公开Azure原VM表、<24h寿命、按核数/时长聚合及短时fractionals；原代码L49有`paris`拼写，不能无记录地改参考源码。
MISO192行全部独立解析；`tsusc_miso_signal_*`只把原始前24行信号用于明确合成单位任务的独立连续开始枚举。原价格USD/MWh以明确假设7CNY/USD转模型货币，非历史汇率或论文经济指标。不能据此宣称Azure任务轨迹、144h滚动、UTIL/PD奖励、Table1、预测扰动策略已复现。

## 显式边界
常规日调度与冻结任务支持15min/连续整数；年度投资/代表日与作者全年8760政策仍1h；15min年度明确拒绝。三级滚动/可行域/实时包装、VCC尚不支持15min或连续整数，显式阻止；市场沙盘15min明确拒绝。并未支持SustainDC同机架/HVAC/水塔环境、年CFE采购与共享容量/储能来源、内生LMCE再出清或离散GPU帽/SLA。
旧冻结输入以`input_snapshot.json`为权威；旧结果保持原字节逻辑/原时间步，不回填新审计或改写历史数字。当前schema展开后的参数表不是证明旧程序曾支持新字段。

## 另行财务积分参考与旧基线
`acceptance_financial_reference.py OUTPUT_DIR`从四份正式CSV独立重算电价×发电量、热报价×交付热量、旧合成储能吞吐费5CNY/MWh；不调用产品成本函数，不反推系数。该固定循环费沿用旧产品约定，非论文费用假设，也尚非可配置字段。此为单独1门/4控制，与51个HTTP门、37项新增pytest分计。
上一批21门需顺序执行`acceptance_api.py OUTPUT_DIR`和`acceptance_provenance_api.py OUTPUT_DIR`，包含新鲜365日LP/8760、546网格及372包摘要；勿在服务重启或另一HTTP求解器批次运行时启动。
