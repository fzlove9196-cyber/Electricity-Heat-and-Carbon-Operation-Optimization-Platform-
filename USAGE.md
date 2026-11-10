# 使用指南

> 📘 完整的在线使用帮助（快速上手、各功能说明、参数配置手册、常见问题、已知限制）：启动服务后打开 `http://127.0.0.1:8080/help`，或在产品内点右上角「❓ 帮助」/ 按 F1。帮助内容源文件位于 `app/help/pages/`。

## 0. 两分钟上手（新人推荐）
1. 打开 `http://127.0.0.1:8080`，默认进入 **🧭 仿真工作台**（对话为主，不是 CAD 建模器）。
2. 在欢迎页点一张**示例卡片**（会自动发送），或自己输入中文问题。研究类问题先勾选 **🔬 研究模式**。
3. 智能体建模后会**暂停**：到右侧 **② 输入参数** 核对单位与来源（用户指定 / 智能体推断 / 默认值），再确认运行。
4. 跑完后可继续问「为什么」「如果…会怎样」，或导出可复现运行包；顶部状态条显示「当前在做什么」。
5. 常用示例：中卫经济最优寻优、热浪+需求响应、余热供暖靠谱吗、对比散热方式、三数据中心+储能调度。

点右上角 **?** 可看轻量提示（不会弹窗打断）。进阶能力（Pareto / VCC / 功率模型 / 8760 / 配置构建器）均可直接用中文说出来。

---
## 1. 打开
- 本机：浏览器访问 `http://127.0.0.1:8080`（服务监听 0.0.0.0:8080，同网段可用 `http://<服务器IP>:8080`）。
- 启动/停止：`/workspace/sim-agent/start.sh` / `stop.sh`。左下角显示当前模式（Mock / 真实 LLM）。

## 2. 配置 LLM
进入 **⚙️ 设置**：
- LLM Base URL：OpenAI 兼容地址，如 `https://api.openai.com/v1`、`https://api.deepseek.com/v1`、本地 vLLM/Ollama `http://localhost:11434/v1`
- API Key、模型名（需支持 function calling）
- Mock 模式：选“0 关闭”才会调用真实 LLM
- RAG：默认本地 bge-m3 嵌入 + bge-reranker-v2-m3 重排 + jieba BM25（无需 API Key）。可改“RAG 嵌入后端”为 `openai` 并填写 Embedding 模型（如 `text-embedding-3-small`），或 `none` 仅用 BM25。切换后到知识库页点“重建向量索引”。
- 碳强度来源：默认 synthetic；可填 Carbon Aware SDK WebAPI 地址（CARBON_SOURCE=carbon_aware_sdk）
保存后立即生效，Key 只以掩码显示。

## 2b. 论文基准对照（paper_bench）
用公开论文/SPEC 数字对照本引擎（功率模型 + VCC + OPF），**不编造论文数值**：
```bash
/workspace/sdco-env/bin/python cases/paper_bench/run_paper_bench.py
```
案例在 `cases/paper_bench/meta/manifest.json`（sourced vs assumed 已标注）；结果写入 `cases/paper_bench/meta/results.json`。

## 3. 示例提示词
| 需求 | 示例 | 调用的仿真器 |
|---|---|---|
| 算电协同调度 | 三个数据中心，加50MWh储能，峰谷电价，帮我优化调度并分析 | Pyomo/HiGHS + pandapower |
| 暂态稳定 | 数据中心负荷突增80MW，做暂态稳定仿真看频率 | ANDES |
| 标准算例潮流 | 用MATPOWER跑一下case30的潮流 / case118 最优潮流 | Octave + MATPOWER |
| 配网接入 | 10kV配网馈线接入数据中心5000kW，加储能4000kWh，看电压 | OpenDSS |
| 物理建模 | 用OpenModelica仿真数据中心负荷阶跃0.2pu的频率响应 | OpenModelica |
| 3D 可视化 | 把母线电压做成三维可视化（ParaView） | pvpython |
| 知识问答 | 根据知识库，储能SOC约束一般怎么设置？ | 检索 + 引用来源 |
| 碳感知调度 | 碳感知调度，碳价100，三个数据中心帮我优化 | 碳强度曲线 + 双目标调度 |
| 成本-碳 Pareto | 做一下成本和碳排放的Pareto分析，三个数据中心加50MWh储能 | 权重扫描 + ECharts 交互图 |
| 任务级调度 | 30个任务带截止时间，考虑迁移时延和带宽，碳价100，帮我优化调度 | 任务 LP + 链路约束 |

对话页会显示**步骤时间线**（可展开看参数/结果/重试），图表、表格、Markdown 报告直接内嵌，底部可下载所有产物。

自定义场景：在 **🧩 场景参数** 编辑数据中心/储能/光伏/电价（或完整 JSON），回到对话页勾选“使用场景参数面板”再发送。
- 🌱 碳感知：排放因子（默认全国 0.5306）、日内形状、碳价、碳权重 w、核算口径；下方实时显示逐时碳强度曲线（ECharts）。
- 🔗 迁移链路：每条链路的时延 ms、带宽上限 MW/h，以及迁移能耗 κ。
- 🧾 任务：点“生成合成任务”按数量/种子生成（合成数据），可逐行编辑释放/截止时间、能量、最大功率、允许 DC、时延上限；“清空”回到聚合批处理模型。
- 真实 trace：把 Alibaba `pai_task_table.csv` 或 Azure LLM trace CSV 放到服务器上，对话中让智能体调用 `load_job_trace(path, format)`。

## 3b. 模型拓扑 / 能流（通用建模视图）
任何场景（IEEE14 默认、自定义网络、中卫等预设、场景参数面板里手工编辑的模型）一旦被构建或修改，系统都会**自动**生成一张“模型拓扑 + 能流”图，方便在运行前核对模型：
- **拓扑内容**（全部从当前模型数据读取，不手画）：母线（按电压等级着色）、线路/变压器（长度、阻抗、容量、并联回数）、每个电源的类型与装机（🌬 风电 / ☀ 光伏 / 🏭 火电常规机组 / 🔌 外网购电上限）、🔋 储能（功率/容量/时长及接入母线）、🖥 数据中心（IT 容量×PUE=峰值负荷）、🏠 常规负荷、紫色虚线=算力迁移链路（时延/带宽；未定义链路时显示为“全连接”）、电气岛。
- **装机汇总表**：风电、光伏、火电、外网购电上限、储能 MW/MWh、数据中心峰值负荷、常规负荷峰值；网络类型、电压等级、母线/线路/变压器数量、电气岛。
- **能流**：未求解时只显示容量（容量条形图）；运行调度后自动叠加每条支路的**潮流方向（箭头）与大小（MW、负载率，线宽∝负载率，红>90%、橙>60%）**，可用“潮流时刻”滑块切换 0–23 时（默认峰荷时刻），下方显示日能量**桑基图**（新能源/购电/储能 → 区域汇集 → 数据中心/储能充电/外送/弃电）。
- **交互**：鼠标悬停显示元件参数；点击母线/线路/设备在右上“元件详情”中查看完整参数和 24h 潮流/出力曲线；滚轮缩放、拖拽平移。
- **导出**：“导出 PNG”（当前视图高清图）、“导出交互 HTML”（单文件离线可打开，含 ECharts）、“静态 PNG（服务端）”。文件同时出现在对话底部的产物栏：`model_topology.png / .html / .json`。

使用方法：
1. 对话中描述建模需求，例如“帮我建模：三个数据中心，加50MWh储能，核对模型”或“建模宁夏中卫夏季大风场景，核对模型并运行调度看能流”。智能体在“构建场景”步骤后会直接在对话里展示模型拓扑，请先核对装机/接线是否正确，再让它运行。
2. 左侧菜单 **🗺 模型拓扑** 页：选“当前会话模型”查看随智能体每一步（构建/修改/求解）自动更新的图；选“场景参数面板”则在“🧩 场景参数”里每次修改参数后实时预览（未求解）。场景参数页也有“🗺 预览模型拓扑”按钮。
3. 工具名 `show_model_topology`（任何网络通用）；`build_scenario` 与 `run_dispatch` 会自动调用它。API：`GET /api/sessions/{id}/model`、`POST /api/model/preview`（请求体为场景 JSON）。
4. 截图回归：服务启动后运行 `python tests/screens_model.py`，截图输出到 `screens/model_*.png`。

> 说明：拓扑图中的潮流由调度结果按 DC 潮流（B-θ，与调度模型同口径、无损）重建；精确的交流潮流/电压请用 `run_ac_check` 或 `plot_topology(with_flows=true)`（仅自定义网络）。

## 3c. 拓扑编辑与重新仿真
1. 侧栏「🗺 模型拓扑」→ 选「当前会话模型」，勾选「✏ 编辑模式」。IEEE14 等内置网络先点「🔧 转换为可编辑网络」。
2. 点击母线/线路/设备 → 右侧表单修改参数 →「保存」；「➕ 添加元件」可新增母线、线路、变压器、外网、机组、负荷、风光、储能、数据中心、DC 互联；新增线路时可直接在图上点两个母线作为端点。
3. 拖动节点自动保存布局；「重置布局」恢复自动布局。撤销/重做：按钮或 Ctrl+Z / Ctrl+Y；Delete 删除所选（删母线会级联删除相连元件，需确认）。
4. 「✔ 校验」给出中文错误/警告（悬空母线、电压等级不一致、无电源孤岛、PUE、储能时长等）；有错误时禁止仿真。
5. 「▶ 重新仿真」（可勾选交流校核）→ 右侧显示编辑前/后指标对比表，能流图与桑基图刷新。
6. 对话页的智能体自动使用编辑后的模型（会注入「模型编辑同步」说明）；「保存 JSON / 加载 JSON」导入导出场景；下拉框可把案例预设载入当前会话。
API：/api/sessions/{sid}/model/{init,edit,element,layout,undo,redo,validate,rerun,scenario.json,load}。

## 3d. 公开案例预设（cases/）
和林格尔（helinger_*）、庆阳（qingyang_*）、青海海南州（qinghai_hainan_*，含离网）、张北/阿里三地（zhangbei_*）。参数来源与假设见 cases/<名>/README 与 cases/ADAPTATION_MATRIX.md；批量运行：`/workspace/sdco-env/bin/python cases/common/run_cases.py`。这些是方法测试，不是工程结论。

## 3e. 第二轮真实项目验证（8 个公开项目 + 极端场景）
- 预设：`ulanqab_cicdata_*`（中金数据乌兰察布 源网荷储）、`ulanqab_21vianet_*`（世纪互联乌兰察布）、`shaoguan_*`（韶关华南数谷 冷板+风冷，含热浪 DR、N-1）、`guian_huawei_*`（华为云贵安 直通风）、`renhe_alibaba_*`（阿里仁和 浸没液冷）、`wuhu_telecom_*`（芜湖智算 混合液冷）、`lingang_dr_*`（上海临港智算 2026-07-10 削峰事件）、`odense_meta_*`（Meta Odense 余热供暖）。
- 气象来自 Open-Meteo 免费历史 API（ERA5），`cases/common/climate.py` 自动下载缓存，挑选典型日/热浪/寒潮/低风日；来源与【假设】/【校准】写在每个预设的 `sources`。
- 一键复现：`python cases/common/build_validation.py && python cases/common/run_validation.py`；研究模式：`python cases/common/run_research_validation.py`（服务需已启动）；截图：`python tests/screens_validation.py` → `screens/val_*.png`。
- 研究模式现在按地点关键词选预设，例如“韶关华南数谷夏季热浪下保障热安全同时参与需求响应的最优方案”“Meta Odense 数据中心余热供暖值不值”。
- 新参数：`outdoor_rh` / `outdoor_rh_profiles`（逐时湿度）、`DCThermal.heat_rejection`（液冷一次侧 dry/wet/hybrid）、`DREvent.storages`（计入 DR 的表后储能）、`green_shortfall_penalty_cny_mwh`（绿电占比软约束）。
- 不可行时错误信息会给出“冷量不足（设计日预检）：某 DC 某时可用 X MW < 需 Y MW → 冷机需 ≥ Z MW”。

## 4. 教它知识
- **上传文档**：📚 知识库页拖拽上传（或直接拖到对话输入框）PDF/DOCX/MD/TXT/CSV/.py/.mo/.m；每轮对话自动检索，回答中标注 `[来源: 文件#块]`。
- **技能卡**：在对话中说
  `记住：配网数据中心接入校核。类型：配网校核。关键词：配网 数据中心 接入。步骤：run_opendss -> run_matpower。参数：{"run_opendss":{"dc_kw":6000}}。校验：电压0.93-1.07`
  智能体保存为结构化技能卡（任务类型/步骤/参数/校验/示例），之后类似任务自动检索并按卡执行。也可在 🧠 技能卡 页新建、编辑、删除。

## 5. 新增仿真器
见 README.md “如何新增一个仿真器工具”：写一个 `@tool` 函数 → 在 `app/tools/__init__.py` 导入 → 重启（`./stop.sh && ./start.sh`）。🛠 仿真器页可查看所有工具与可用性。

## 6. 注意
所有默认数据为合成示例数据，结论仅用于方法演示。服务无登录认证，勿直接暴露到公网。

## 透明化仿真工作台（六步工作流）

打开 http://<服务器>:8080 ，默认进入「🧭 仿真工作台」：左侧是智能体对话，右侧是步骤面板，顶部步骤条显示 **① 场景与目标 → ② 输入参数 → ③ 模型构建（拓扑核对）→ ④ 求解配置 → ⑤ 运行与校核 → ⑥ 结果与分析**。✓=已完成，蓝色“当前”=流程所处步骤；可随时点击任一步查看。智能体每调用一个工具，步骤条会自动跳到对应步骤。

### 两种用法
- **手动**：在 ① 选择案例预设（如 `zhongwei_summer_highwind`）与优化目标（纯成本 / 成本+碳）→「载入场景 → 核对参数」。
- **对话**：在左侧输入需求（如“中卫夏季大风日，优化调度并分析”）。智能体构建模型后**自动暂停**，提示“等待你确认参数”；确认前不会调用任何求解工具。对话框下方勾选「自动运行」可跳过暂停（API 调用不传 `auto_run` 时默认不暂停，兼容旧客户端）。

### ② 输入参数（参数表）
按 网络 / 电源 / 储能 / 数据中心与算力负荷 / 电价与碳 / 约束 / 求解器 分组，列出引擎实际使用的每个输入：名称、含义、值、单位、合理范围、**来源标签**：
`用户指定`（你输入或修改）、`智能体推断`（从对话解析，橙色高亮）、`默认值`（内置合成值，灰色高亮）、`案例假设`、`公开资料`（🔗 链接到案例 sources 中的公开来源）。
必填项标 *，缺失或越界会标红；数值可直接在表中修改（立即校验，失败会给出原因与修改建议），修改后来源变为“用户指定”且需重新确认。核对后点「✅ 确认参数」（若智能体已暂停，可点「确认并继续运行」）。

### ③ 模型构建
展示装机/规模汇总、模型校验结果与交互式拓扑图；需要改动时点「在拓扑编辑器中修改」（原「🗺 模型拓扑」页，功能不变）。

### ④ 求解配置与数学模型
可设置求解器（HiGHS）、时间上限、是否计算基线、是否交流校核及校核时刻、是否做收益归因。下方用 KaTeX 渲染**本次实际使用的**目标函数各项与约束，并标明每项“启用/关闭”及原因（如“无储能”“碳权重 w=0：纯成本目标”），列出决策变量；求解后显示变量数、约束数、求解状态与用时。

### ⑤ 运行与校核
点击「▶ 开始运行」后显示进度条与当前步骤说明；运行日志按时间列出每一次工具调用：做了什么、为什么（智能体说明或系统说明）、谁触发（🤖 智能体 / 👤 用户）、输入、输出摘要、用时、成功/失败。并给出求解器表（状态、目标、对偶界、Gap、用时、变量/约束数）与交流潮流校核（收敛、电压范围、最大支路负载、网损、是否越限）。

### ⑥ 结果与分析
- KPI 卡片：数值、基线值与变化，悬停 ⓘ 查看定义与公式。
- 「解释这个结果」：按 *基线 → 仅负荷时移 → +跨中心迁移 → +储能* 顺序求解反事实 LP，把节省拆成 时移 / 迁移 / 储能 三部分（柱状图 + 文字），并给出目标函数逐项（购电、外送收入、弃电惩罚、储能损耗、PPA、需量电费等）的基线/优化对比与物理量（弃电减少、购电峰值降低、储能放电、迁移电量）。
- 逐时曲线：数据中心功率 vs 电价、新能源可用 vs 利用、储能充放电与 SOC、逐时费用。
- 假设与局限：合成数据、案例假设、DC-OPF 线性化、确定性预测、惩罚项为虚拟成本、交流校核只针对单一时刻等。
- 「📦 导出可复现运行包」：zip 内含 `scenario.json`、`params.json`（含来源）、`formulation.json`、`solver_config.json`、`runlog.json`、`results.json`、`dispatch_*.csv`、`report.md` 与独立脚本 `reproduce.py`。解压后运行 `SIM_AGENT_ROOT=/workspace/sim-agent /workspace/sdco-env/bin/python reproduce.py` 即可用同一引擎重算并核对目标函数（测试保证一致）。

### 新增 API
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/sessions/{sid}/workflow` | 步骤状态、当前步骤、是否已确认、待执行工具、求解配置 |
| GET / PATCH | `/api/sessions/{sid}/params` | 参数表；PATCH `{"path": "storage.0.energy_mwh", "value": 300}`（`solver.*` 为求解配置） |
| POST | `/api/sessions/{sid}/workflow/confirm` | 确认参数（可带 `auto_run`） |
| PUT | `/api/sessions/{sid}/solver` | `{"cfg": {"time_limit_s": 60, "ac_check": true, ...}}` |
| POST | `/api/sessions/{sid}/workflow/run` | 按配置运行全流程（SSE 进度；`?stream=0` 返回 JSON） |
| GET | `/api/sessions/{sid}/formulation` | 本次数学模型（目标项、约束、变量、规模） |
| GET | `/api/sessions/{sid}/runlog` | 运行日志 + 求解器统计 + 交流校核 |
| GET | `/api/sessions/{sid}/results` | KPI 定义/数值/基线、归因、告警、逐时序列 |
| GET | `/api/sessions/{sid}/export.zip` | 可复现运行包 |

`/api/chat` 新增可选字段 `auto_run`：`false` 时智能体在求解前暂停（返回事件 `confirm_needed`）。截图脚本：`python tests/screens_ux.py`（输出 `screens/ux_*.png`）。


## IT 硬件功率模型与 VCC（近端 ①②，2026-11）

**向后兼容**：`power_model` 缺省 `identity`、`vcc_mode` 缺省 `off` 时，目标/约束/结果与旧引擎一致。

### ① Idle+动态 / PDU
- 场景字段（每 DC）：`power_model=identity|idle_dynamic|pdu_pwl`，`p_idle_mw`/`p_peak_mw` 或 `p_idle_kw`+`p_peak_kw`+`n_servers`，`pdu_breakpoints`。
- 对话：`硬件功率模型` / `idle功率40%` / `PDU功率` → `build_scenario(power_model=..., idle_frac=0.4)`（【假设】标定）。
- 耦合热模型发热用实际 `P_IT`；`constant_pue` 下电网侧=`PUE×P_IT`。
- Trace：`app/traces.py` 利用率→功率。

### ② VCC
- 场景：`vcc_mode=off|carbon|price|weighted`，`vcc_stage=joint|day_ahead`。
- 对话：`虚拟容量` / `VCC` / `碳智能` / `日前整形`。
- 真实案例验证脚本：`python cases/common/run_power_vcc_validation.py` → `cases/validation/out/power_vcc_results.json`。
- **诚实说明**：日前 VCC 按碳/电价信号整形灵活容量，不保证相对无 VCC 基线一定降碳；请看并列 deltas。

详见 `knowledge_seed/07_IT功率模型与VCC.md`。

## 算-电-热-碳 耦合仿真与优化（虚拟储冷 / 虚拟储热 / 需求响应 / 热安全）

软件核心能力：在 **算力负载 ↔ 电网 ↔ 机房热 ↔ 碳排放** 相互耦合的场景下做仿真与优化。场景字段 `thermal_mode`：
- `constant_pue`（旧模型，默认）：电网侧功率 = PUE × IT；
- `coupled`：每个数据中心两节点 RC 热模型 + 冷机 COP(室外温度) + 自然冷却 + 冷却塔/水泵 + 蓄冷罐 + 余热热泵，输出**逐时动态 PUE**。仍为 LP（HiGHS），无整数变量。

### 能力一览
| 能力 | 说明 | 关键参数（参数表分组） |
|---|---|---|
| 动态 PUE | (IT+冷却+其他)/IT 逐时计算；COP = COP_ref − k(T_out−25) 逐时预计算 | 热管理与冷却 |
| 虚拟储冷 | 预冷：利用空气+建筑热惯性在低价/高 COP 时段压低入口温度；日末温度不高于初值 | `c_mass_mwh_k`、`t_min_c` |
| 显式蓄冷 | 冷冻水/冰蓄冷罐，容量/功率/自损失，日末 SOC ≥ 初值 | `tes_mwh_th`、`tes_p_mw_th` |
| 余热回收/虚拟储热 | 热泵 → 区域供热网（可接纳热负荷曲线、售热价），热网惯性/蓄热罐；热碳抵扣 | 余热回收与供热 |
| 热安全（硬约束） | ASHRAE 入口温度 18–32°C（推荐 27°C 以上软惩罚）、温变率 ≤5K/h、冷机 N+1、IT ≤ 可用冷量、末端排热能力 | 热管理与冷却 |
| 需求响应 | 削峰/填谷事件、补偿价、基线方法 plan/bau/given、申报能力、强制达标、未达考核 | 需求响应 |
| 碳耦合 | 逐时平均/边际碳强度（`carbon_basis`），总碳 = 电力碳 − 余热热碳抵扣；碳价×权重进目标 | 碳 |

### 案例预设（cases/，热参数均标注【假设】）
- `zhongwei_summer_coupled`：中卫夏季大风日，耦合 + 蓄冷 + 预冷，碳权重 1；
- `zhongwei_summer_coupled_dr`：再加 19–22 时削峰 40MW（2000 元/MWh）、11–14 时填谷 30MW；
- `zhongwei_heatwave_stress`：热浪 25–39°C + ZW_NEW_A 冷机检修 + 晚高峰 DR —— 热安全约束起作用的压力测试；
- `zhongwei_winter_coupled_heat`：中卫冬季，热泵 80MW_th 向沙坡头城区集中供热 + 热网虚拟储热 + DR；
- `helinger_winter_coupled_heat`：和林格尔冬季余热供暖（热泵 67MW_th）。
生成脚本：`python cases/common/build_coupled.py`；批量研究：`python cases/common/run_coupled_study.py`（输出 `cases/zhongwei/results/coupled_study.json`）。

### 示例提示词（Mock 模式也能识别关键词：虚拟储冷/预冷/蓄冷/余热/供热/需求响应/削峰/热安全/入口温度/PUE/热浪）
- 「中卫夏季，考虑虚拟储冷和预冷，看动态 PUE 和入口温度」→ `zhongwei_summer_coupled`
- 「中卫夏季需求响应，削峰 50MW，19-22点」→ `zhongwei_summer_coupled_dr`（覆盖申报量/时段）
- 「中卫热浪热安全压力测试」→ `zhongwei_heatwave_stress`
- 「中卫冬季余热供热」/「和林格尔冬季余热供暖」→ 冬季余热案例
- 「三个数据中心，50MWh储能，考虑余热回收和需求响应 30MW，18-21点」→ 默认 IEEE14 场景自动加热模型（`build_scenario(thermal, tes, heat_recovery, heatwave, dr_mw, dr_window)`）

### 工作台中看什么
- ② 参数表：新分组 **热管理与冷却 / 余热回收与供热 / 需求响应 / 碳**（单位、合理范围、来源标签：公开资料/案例假设）；常数 PUE 场景只显示一行「热-电耦合模式」提示。
- ③ 拓扑：每个 DC 下挂 ❄冷却系统、🧊蓄冷罐、♨热泵，🏘区域供热网；蓝线=冷流，红线=热流，求解后标注 MW_th。编辑器「➕ 添加」中可「❄ 热管理（为 DC 启用热模型）」「♨ 区域供热网」，点选这些节点可修改参数或删除（回退常数 PUE）。
- ④ 数学模型：新增 RC 热平衡、排热构成、热安全（入口温度/温变率/N+1/IT≤冷量）、自然冷却、预冷日末、蓄冷、热泵、供热网热平衡、DR、电-热碳核算等约束，并显示启用/关闭原因与「线性化与近似」清单。
- ⑤ 运行日志：run_dispatch 输出 thermal_safe、PUE 范围、入口温度范围、各约束起作用小时数、电/热平衡残差、DR 与售热摘要。
- ⑥ 结果：🌡️ 耦合结果表（入口温度 min~max、裕度、超推荐小时、动态 PUE、冷却电、自然冷却、蓄冷、余热、binding 小时）；入口温度+安全带图、动态 PUE 曲线、冷却电+蓄冷 SOC、余热供热；⚡ DR 要求 vs 实际与收益；收益归因扩展为 时移→迁移→储能→**虚拟储冷→余热→DR**。
- 桑基图：电 → IT → ♨机房热量 → ❄冷机/自然冷却/蓄冷 → ♨余热回收 → 区域供热。

### 截图
`screens/couple_*.png`（脚本 `tests/screens_couple.py <preset> [前缀]`）。

### 主要近似（详见 knowledge_seed/05_算电热碳耦合建模方法.md）
两节点集总 RC（入口温度为机房平均，不含热点）；COP 只随室外干球温度线性变化；热泵 COP 常数；热网单节点无输送时延；1 h 步长日前确定性；DR 基线 plan 法先求一次无 DR 优化计划。

## 🧪 配置构建器 / 散热方式 / 对比扫描 / 余热供暖可行性

**入口**：左侧导航「🧪 配置构建器」。
1. **散热方式库**：风冷冷冻水、间接蒸发、直接蒸发、冷板液冷、单相浸没、混合（可调液冷比例）。每种方式有送回水温度、COP 分段线性曲线（按干球或湿球）、自然冷却阈值、WUE、余热源温度、热安全边界和文献来源（`app/tools/cooling.py`，API `GET /api/cooling/modes`）。
2. **从零构建配置**：可设数据中心（数量、IT MW、机柜、利用率、可调比例、散热方式、液冷比例、蓄冷罐类型/容量/功率、热泵 MW 与类型）、电池、蓄热罐、虚拟储能开关（预冷、蓄冷、余热、DR）、风/光/火/水/燃气 CHP/外网/PPA，以及供热末端（地暖、风机盘管、散热器、一次网）、管线长度、温降、补热方式和热价。点「校验」会给出错误和告警（例如风冷单柜超过 25 kW）；点「构建为当前会话场景」后，到工作台 ② 确认参数，再求解。
3. **对比 / 扫描**：内置四个一键研究：散热方式对比、储能容量扫描、蓄冷容量扫描（夏季）、余热供暖可行性（散热方式 × 末端 × 距离）。也可以自定义 1–2 个参数的网格，用点路径写，如 `dcs.*.cooling_mode`、`battery.energy_mwh`、`heat.pipe_length_km`、`heat.terminal_type`、`dcs.0.hp_type`。输出 KPI 表、柱状图和可行性判定卡片；结果文件在 artifacts 里，名为 `cfg_sweep_*.json/md/png`、`cfg_heat_feasibility.*`。
4. **参数表**（工作台 ②）新增四个分组：能源配置、蓄能配置、散热方式、余热品位与供热末端。修改 `cooling_mode` 会按散热方式库重设温度边界、辅机电耗和回收比例。
5. **对话**（mock 路由）：例如“对比风冷和液冷散热方式”“余热供暖靠谱吗？末端温度满足吗？散热器 10 公里”“储能容量扫描对比”“新建配置 冷板 80MW 数据中心 储能 200MWh”。
6. **智能体工具**：`list_cooling_modes`、`build_config(spec|set)`、`set_cooling_mode(mode, dc, liquid_frac)`、`run_config_sweep(variants|params)`、`heat_feasibility_study(modes, terminals, lengths_km)`。
7. **API**：`GET /api/config/template`、`POST /api/config/validate`、`POST /api/sessions/{sid}/config/build|sweep|heat_study`。
8. **中卫研究脚本**：`python cases/zhongwei/run_cooling_study.py`，结果写到 `cases/zhongwei/results/cooling_study/`，包括冬季/夏季/热浪下的散热方式对比、末端×距离网格、高温热泵、无补热 20 km、电池/蓄冷/蓄热扫描。
9. **余热品位模型**（`app/tools/heat_grade.py`）：热泵 COP = η·T_sink/(T_sink−T_evap)，逐时预计算；源温 − 端差 ≥ 站出口要求温度时直接板换；末端供水随室外温度质调节；管网温降和热损按长度计；热泵出水温度不足时由燃气或电补热，比例为 f。KPI 包括末端温度裕度、热成本（元/GJ）、补热量、余热供暖判定（可行 / 有条件可行 / 不可行）。
10. **截图**：`python tests/screens_cfg.py` → `screens/cfg_*.png`。

## 🔬 研究模式（对话驱动的自主研究闭环）

不是“画模型再点运行”，而是：**一句中文问题 → 研究问题卡 → 澄清 → 研究计划 → 执行·诊断·修订循环 → 证据化结论 → 知识沉淀**。

1. **开启**：在「🧭 仿真工作台」对话框下方勾选 **🔬 研究模式**（或点击带 🔬 的示例），提问如：
   - `中卫冬季想用余热供暖，看值不值`
   - `中卫夏季热浪下保障热安全同时参与需求响应的最优方案`
2. **问题形式化**：智能体生成 **📋 研究问题卡**（研究问题、决策变量、约束、评价指标、情景、假设），并显示“📚 参考了哪些经验”（检索已沉淀的方法卡/经验卡）。
3. **澄清**：对决定结论方向的关键缺失信息（末端类型、管线长度、热价、是否计投资 / DR 是否硬承诺、削峰量、热安全上限、热浪强度）给出**选项 + 默认值**。原话中已说明的会自动解析（如“末端是地暖”）。
   - 每个参数的来源可追溯：参数表「② 输入参数」中出现 **💬#n** 链接，点击跳到对应对话消息；未回答的标为“智能体推断（默认值）”，诊断修订的标为“诊断修订（用户确认）”。
4. **研究计划**：基线 → 主方案 → 敏感性 → 方案比较 → 压力测试 → 交流校核。在右侧「🔬 研究」可勾选/删减步骤、修改敏感性取值；点「✅ 批准并执行」（或对话卡片按钮）开始。
5. **执行 · 诊断 · 修订**：每次运行后自动做确定性诊断（求解状态、PUE 合理范围、热/电/供热平衡残差、同一外网接口同时购售电、储能同时充放、热安全裕度、DR 缺额、余热末端温度、紧约束与 LP 影子价格）。
   - **不可行**：自动逐项松弛关键约束定位原因（DR 硬约束 / 温度上限 / 冷机容量 / 温变率 / 室外温度），必要时二分搜索可行边界，然后弹出 **⏸ 检查点卡片**请你选择修订方案（可勾选“诊断修订自动采纳”跳过暂停）；修订次数上限 3 次。
   - **异常**：如入口温度零裕度 → 自动追加“裕度复核”实验；供热达热网上限 → 追加“热泵扩容验证”。
   - 右侧 **⏱ 研究时间线**显示每一步做了什么、为什么；**🧪 运行与诊断**表点击任一运行 R# 查看诊断、松弛试探、紧约束/影子价格和逐时温度/PUE 曲线，可下载 CSV。
6. **证据化结论**：每条结论带置信度、证据链（R# 运行与关键数字，可点击）、紧约束、敏感性、依赖假设（A#）。所有数字均来自运行结果（Mock 模式也不编造）。
7. **追问**：
   - “为什么 C2 成立？” → 用紧约束/影子价格、目标函数逐项归因（基线→主方案）、敏感性、不可行原因解释；
   - “如果热价降到 80 会怎样 / 如果热浪再高 2 度 / 如果蓄冷翻倍 / 如果削峰 30 MW / 如果改成地暖 / 如果管线 10 公里 / 碳价 200” → 修改模型重算主方案与同工况基线，给出变化量表。
   - 在参数表/拓扑中手动修改后继续对话，智能体会提示“检测到你在界面修改了模型…”并以编辑后的模型为基准。
8. **知识沉淀**：研究结束后提议沉淀“方法卡（研究流程+参数+检查项）”和“经验卡（如：热浪日 DR 硬承诺需先校核可承诺上限）”，勾选后「采纳选中项」写入技能卡库，后续相似问题在形式化阶段自动引用。
9. **报告**：自动生成 `study_report.md / study_report.html`（问题卡、参数来源、计划与执行、运行清单、诊断与修订、结论证据链、what-if、局限），可在研究面板或对话卡片下载。

**LLM 模式**：Mock（默认，无 Key）下形式化/计划/诊断决策/结论全部由确定性规则完成；在「⚙️ 设置」填写任意 OpenAI 兼容端点（LLM_BASE_URL / LLM_API_KEY / LLM_MODEL，并把 LLM_MOCK 设为 0）后，研究编排器通过 function calling（`submit_problem_card` / `decide_next` / `narrate_conclusions`）让 LLM 完善问题卡、在候选修订中做选择并撰写解读；LLM 调用失败自动回退规则，数字始终来自仿真。

## 3f. 全年 8760h · 逐时边际碳因子 · 需求驱动寻优

**对话即可触发**（含“寻优/经济性最优/碳排放最优/成本最优/容量规划/帕累托前沿/折中方案/8760/全年优化”等词）：

- `乌兰察布项目寻优：我想看经济性最优和碳排放最优的方案，以及中间的折中` → ε-约束帕累托（成本×碳），标注 💰成本最优 / 🌿碳最优 / ⚖️膝点
- `韶关：成本最低，绿电不低于90%，回收期不超过8年，全年8760` → 单目标 + 硬约束
- `欧登塞 先保证碳排放最低，其次成本` → 字典序；`成本权重0.7 碳权重0.3 加权寻优` → 加权和
- `不新增风电` / `电池上限 200MWh` / `只运行优化` / `比较散热方式` / `平均碳因子` / `碳价300` / `48个代表日` → 决策变量与口径
- 追问：`再降10%碳要多花多少钱`（重解 + 对偶边际减排成本）、`为什么选折中方案`、`查看方案3`
- 目标规格卡可直接编辑（模式/分辨率/碳因子/约束/决策变量/JSON），点「按此规格重新寻优」；帕累托图点击查看方案，下方为方案对比表。

实现：`app/opt/annual.py`（scipy.sparse 组装 + HiGHS，代表日 k-means + Kotzur 日间 SOC 链接；`Session` 热启动 ε 扫描）、`app/opt/carbon.py`（剩余负荷-优先顺序边际碳因子，参数为【假设】）、`app/opt/engine.py`（单目标/加权/字典序/帕累托、对偶解释、回收期/NPV、边际减排）、`app/opt/nl.py`（中文规则解析）、`app/opt/schema.py`（`submit_objective_spec` 函数调用 schema）、`app/research/opt_flow.py`（编排器分支）、`app/tools/opt_tools.py`（`submit_objective_spec`/`run_optimization`/`query_abatement`/`explain_scheme`）、`app/static/opt.js`。
验证：`python cases/common/run_opt_validation.py [acc|cprice|ulq|pareto|full_front]` → `cases/validation/out/opt_validation.json`；乌兰察布年风电复核 `cases/common/ulanqab_annual_check.py`。截图：`python tests/screens_opt.py` → `screens/opt_*.png`。
年度模型是“铜板 + 准稳态冷却”（无 RC 热惯性/潮流/N-1，那些由日内模型校核）；投资单价、渗透率等为【假设】量级。

## P0 能力补齐（标定 / 年日闭环 / 多节点热网 / 活碳文件，2026-11-05）

**向后兼容**：`power_model` 缺省仍为 `identity`；`HeatNetwork.nodes` 空列表走原单节点路径；碳源缺省 `synthetic`。

### P0.1 站点 PDU/利用率标定
- 模块：`app/calibration.py`；工具：`calibrate_power_model`；API：`POST /api/sessions/{sid}/calibrate/power`（multipart `file`）。
- CSV 列：`timestamp` + (`util` 或 `IT_kW`) + `PDU_kW`。拟合 `idle_dynamic` 或 `pdu_pwl`，返回 R²/MAPE/RMSE；写入 DC 后 `sources` 标【标定】。
- 样例：`tests/data/pdu_calib_sample.csv`。对话关键词：功率标定 / PDU标定 / 实测标定。

### P0.2 年–日物理闭环
- 模块：`app/opt/day_check.py`；工具：`check_year_days`；API：`POST /api/sessions/{sid}/check_year_days`。
- 抽选典型/极端日，叠加 ERA5 气象后跑完整日内引擎（DC-OPF+RC 热+可选公网 N-1）；输出违规与修复建议；可选 `compare_rep48` 报告代表日相对 8760 铜板误差。
- 产物：`year_day_check.json`。

### P0.3 多节点热网 + 管段时延
- Schema：`HeatNode` / `HeatPipe`；`HeatNetwork.nodes/pipes/inject_at`（空=旧单节点）。
- 工具：`build_multi_heat_network`（`from_odense=true` 可拆 plant+city）；API：`POST /api/sessions/{sid}/heat/multi`。
- 时延为整小时 LP；日初 t<delay 到达量按 0（保守）。

### 活碳强度文件/URL（薄 MVP）
- `CARBON_SOURCE=file|url` + `CARBON_FILE` / `CARBON_URL`（设置页/环境变量）。失败回退合成并标注。演示：`tests/data/carbon_hourly_demo.json`。

验证：`pytest tests/test_gap_p0.py`；结果镜像 `cases/validation/out/gap_p0_results.json`。

## 三级优化（日前定基线 / 日内滚动 / 实时跟踪，2026-11-05）

对齐 BIT 研讨会「日前（定基线）→ 日内（滚动校准）→ 实时（快速跟踪）」与可行响应域理念。**默认关闭**：不调用则求解路径与旧版完全一致。

### 对话触发
| 说法 | 工具 |
|---|---|
| 保存日前基线 / 定基线 | `save_day_ahead_baseline` |
| 日内滚动 / 滚动校准；可加「下午3点光伏少20%」 | `reoptimize_intraday`（先自动补跑基线） |
| 可行响应域 / 灵活包络 / 上下调 | `compute_flexibility_envelope` |
| 实时跟踪 / MPC-lite | `run_realtime_track` |
| 预测补丁 / 风电少 / 光伏少 | `apply_forecast_patch` |
| 负载率冷却 / 耦合报告 | `report_load_cooling_coupling` |
| 三级优化（一键流水线） | 基线→滚动→包络→实时→时间线 |

### API
- `GET /api/sessions/{sid}/tier`
- `POST .../tier/{baseline,patch,reoptimize,envelope,realtime,coupling}`

### 前端
工作台右侧 **⏱ 三级优化** 面板：时间线胶囊 + 关口对比图 + 可行域带宽图（`static/tier.js`）。

### 验证
```bash
python cases/common/run_tier_validation.py   # → cases/validation/out/tier_validation.json
pytest tests/test_tiered_opt.py -q
```
截图：`screens/tier_*.png`。实现：`app/opt/tiered.py`、`app/tools/tier_tools.py`；`sdco_engine.solve(..., roll=None)` 钩子默认关闭。

### 扩展（2026-11-05）：SOC 实测修正 · UPS/柴发可调度

**默认关闭**，不调用则滚动仍硬锁定日前 SOC 轨迹；场景无 UPS/柴发字段行为与旧版一致。

| 能力 | 用法 |
|---|---|
| 滚动 SOC 实测 | `reoptimize_intraday` 传 `soc_measured={"ESS_ZW":0.42}` 或 `soc_measured_path`；对话「SOC实测0.42」；结果含 `soc_source` / `soc_deviation`（值·单位·相对日前偏差） |
| 配置 UPS/柴发 | `configure_backup_resources`（`ups`/`diesel`=true 用【假设】；或显式 JSON）；`list_backup_resources` 透明列出 |
| 应急模式 | `set_emergency_mode`：UPS 可用至 `soc_min`；`dispatch_mode=emergency_only` 柴发放开；可同时收紧 `grid_import_max_mw` |
| API | `POST .../tier/reoptimize`（含 soc_*）；`POST/GET .../tier/backup`；`POST .../tier/emergency` |
| 前端 | 三级面板 SOC JSON 输入、UPS/柴发、应急按钮 |

柴发为连续爬坡模型（默认不引入启停二进制）；`startup_cost_cny` / `min_up_h` 仅透明记录。UPS 与 `other_frac` 损耗并存时勿把损耗再当成可放电能量。

验证：
```bash
python cases/common/run_tier_backup_soc_validation.py
pytest tests/test_tiered_opt.py -q
```


## 新增：从项目模型运行，而不是只靠会话选模型

1. 打开“① 资源与建模 → 项目与场景”，输入项目名创建项目。
2. 选择基础模板，填写场景名和时间轴，从模板创建。多套方案分别建场景，用顶部下拉框切换。
3. 需要修改结构时“签出草稿”，进入原拓扑/配置构建器/参数表；改完回项目页“当前会话模型 → 写回场景草稿”。顶部会显示未保存或旧结果过期。
4. 可在“数据与设备模型库”维护带来源/单位/工况的新版本，在项目页绑定固定资源版本。气象/电价/碳选“场景公共信号”，负荷选对应数据中心，设备模型选对应设备。公开气象的axis需与场景一致；不能把不同时区/日期/币种数据默默混用。
5. “校验与展开”后“发布不可变版本”。旧版本不被修改，新数据版本也不会自动更新旧场景。
6. 去“② 仿真优化 → 版本化仿真任务”，选顶部已发布版本，创建冻结任务后运行。这里调用现有求解，不是空的任务台账。
7. 点击任务看输入与结果；“查看当时模型与结果”会打开独立历史副本，可继续原结果分析和三级运行；“按原快照创建重跑”不会重新读取库中的最新参数。

注意：顶部模型选择与当前对话会话是两个明确上下文。更换顶部场景不会偷偷替换对话模型；应先签出编辑，或运行选定版本任务。原会话可以继续独立使用，也可通过“将当前旧会话导入为场景”纳入项目。

高级场景编辑、资料引用、通用资源导入目前提供JSON编辑器。工程PDF只保存资料引用和待确认项，不会被当作完整且可靠的接线模型。本轮统一任务仅24h，原8760/投资多目标仍从原入口使用。详见`docs/product_foundation.md`。

### 绑定替换与冲突提示
下拉选择只是待操作预览，不会直接改变下方已保存绑定。无同类绑定时使用“新增”；已有同类时明确使用“替换同类绑定”。地点/时间轴不同时页面会列出具体字段的场景期待值和数据实际值；可勾选“同时按所选数据设置草稿时间轴”并确认，只有全部绑定校验通过才原子保存，不会静默回退示例。历史任务始终保持原输入；成功替换后需发布新版并创建新任务。详细复验路径见`docs/product_foundation_ui_fix.md`。
