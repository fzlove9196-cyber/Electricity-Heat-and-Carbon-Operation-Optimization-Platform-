"""自制原理图（非界面截图）。运行：.venv/bin/python make_figures.py → figures/*.png"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from pathlib import Path
for f in ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"]:
    fm.fontManager.addfont(f)
plt.rcParams["font.family"] = ["Noto Sans CJK SC", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
OUT = Path(__file__).parent / "figures"; OUT.mkdir(exist_ok=True)
C = dict(blue="#DCE9F7", green="#DFF2E1", amber="#FFF1D6", red="#FBE0E0", grey="#ECEFF3", purple="#ECE3F7", edge="#3B4A5A")

def canvas(w, h):
    fig, ax = plt.subplots(figsize=(w, h), dpi=200); ax.set_xlim(0, w*10); ax.set_ylim(0, h*10); ax.axis("off"); return fig, ax

def box(ax, x, y, w, h, text, color="blue", fs=9, bold=False, ls="-", ec=None):
    p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.25,rounding_size=1.2", fc=C.get(color, color), ec=ec or C["edge"], lw=1.0, ls=ls)
    ax.add_patch(p)
    ax.text(x+w/2, y+h/2, text, ha="center", va="center", fontsize=fs, fontweight="bold" if bold else "normal", wrap=True, linespacing=1.35)
    return (x, y, w, h)

def arrow(ax, p, q, text="", fs=7.5, style="-|>", color="#33475B", ls="-", rad=0.0, off=(0, 1.2)):
    a = FancyArrowPatch(p, q, arrowstyle=style, mutation_scale=11, color=color, lw=1.1, ls=ls, connectionstyle=f"arc3,rad={rad}")
    ax.add_patch(a)
    if text:
        ax.text((p[0]+q[0])/2+off[0], (p[1]+q[1])/2+off[1], text, fontsize=fs, ha="center", va="bottom", color="#22313F")

def save(fig, name):
    fig.savefig(OUT/name, bbox_inches="tight", pad_inches=0.08, facecolor="white"); plt.close(fig)

# F1 总体功能架构与信息分层
fig, ax = canvas(16, 10)
ax.text(80, 97, "顶部上下文：当前项目 · 场景 · 发布版本（与对话会话是两个显式上下文，切换不会替换会话模型）", ha="center", fontsize=9.5, fontweight="bold")
box(ax, 2, 86, 156, 7, "", "grey")
ax.text(80, 89.5, "左栏六业务域（导航 IA v2）＋ 页内任务条 ＋ 面包屑“下一步” ＋ Ctrl+K 搜索", ha="center", fontsize=9)
doms = [("① 资源与建模", "项目与场景\n基础模板库\n数据与设备模型库\n配置构建器\n模型拓扑/能流\n〔高级〕场景JSON", "blue"),
        ("② 仿真优化", "版本化仿真任务\n仿真工作台（对话）\n参数透明核对\n模型构建核对\n透明模型/数学表述\n研究模式", "green"),
        ("③ 三级运行", "日前基线\n日内滚动\n可行响应域\n实时跟踪\nUPS/柴发/应急", "amber"),
        ("④ 电力交易运营", "P0 沙盘（非真实）\n台账/申报审批\n日内/实时/DR\n结算/审计\n真实提交→403", "red"),
        ("⑤ 结果复盘", "结果与分析\n运行日志与校核\n原文案例/福利与\n生命周期审计专页", "purple"),
        ("⑥ 知识·工具·设置", "知识库（RAG）\n技能卡\n〔高级〕仿真器/工具\n〔高级〕LLM 设置", "grey")]
for i, (t, s, c) in enumerate(doms):
    x = 2 + i*26.5
    box(ax, x, 60, 24, 22, s, c, fs=7.8); ax.text(x+12, 83.6, t, ha="center", fontsize=8.6, fontweight="bold")
box(ax, 2, 40, 156, 13, "", "white", ls="--")
ax.text(80, 50.5, "产品基础层（app/foundation，本地 SQLite data/foundation.sqlite3）", ha="center", fontsize=9, fontweight="bold")
for i, t in enumerate(["项目 Project", "场景草稿 Draft\n(revision 乐观锁)", "发布版本 Version\n(不可变·hash)", "冻结任务 Task\n(input_hash)", "结果/历史副本\n/重跑/导出"]):
    box(ax, 6+i*31, 41.5, 25, 6.5, t, "white", fs=7.8)
    if i: arrow(ax, (6+i*31-6, 44.7), (6+i*31-0.3, 44.7))
box(ax, 2, 18, 156, 17, "", "white", ls="--")
ax.text(80, 32.5, "模型与求解引擎层（不同路径模型不完全统一）", ha="center", fontsize=9, fontweight="bold")
eng = ["日调度 sdco_engine\nPyomo+HiGHS LP/MILP\n1h/15min·cost/加权碳/福利", "年度 8760 寻优\nopt/annual (scipy+HiGHS)\n原入口，未纳入统一任务", "opt_cfe 年度CFE\n8760/8784·1h·UTC", "opt_grid_feedback\n再出清/LMCE ≤168h", "opt_gpu 离散功率帽\n1h/15min·MILP", "三级 tiered / 市场\nmarket.core MILP（仅1h）"]
for i, t in enumerate(eng):
    box(ax, 3.5+i*25.8, 19.5, 23.5, 10.5, t, "white", fs=7.1)
box(ax, 2, 2, 76, 12, "进程级 Pyomo FIFO 执行域（B07/B08 修复）\n变量归属前后校验，fail-closed", "amber", fs=8)
box(ax, 82, 2, 76, 12, "校核/外部仿真：pandapower AC（峰值/指定时刻）\nANDES · OpenDSS ·（MATPOWER/OMC/ParaView 当前环境缺失）", "grey", fs=8)
for x in (15, 41, 68):
    arrow(ax, (x, 60), (x, 53.5), color="#6B7C8F")
arrow(ax, (80, 40), (80, 35.5), "任务按 model_kind 分派", color="#6B7C8F")
save(fig, "fig_architecture.png")

# F2 主闭环
fig, ax = canvas(16, 7.2)
steps = [("资源库/模板库", "模板（只追加）\n气象/电价/碳/负荷\n设备性能模型（r 版本）", "blue"),
         ("项目·场景草稿", "从模板复制\n绑定固定资源版本\nexpected_revision", "green"),
         ("校验与展开", "物理/单位/时间轴\n拓扑/孤岛/引用\n告警与错误分开", "amber"),
         ("发布不可变版本", "模型+axis+资源\n内容与 hash 冻结\n无覆盖/删除 API", "purple"),
         ("创建冻结任务", "选择版本+目标\n+求解配置\ninput_hash/code_hash", "red"),
         ("求解与审计", "调用原引擎\nAC 校核(可选)\n结果/失败均落库", "grey")]
for i, (t, s, c) in enumerate(steps):
    x = 2 + i*26.3
    box(ax, x, 36, 23, 22, s, c, fs=8); ax.text(x+11.5, 60, t, ha="center", fontsize=9, fontweight="bold")
    if i: arrow(ax, (x-3, 47), (x-0.3, 47))
box(ax, 2, 4, 48, 20, "签出编辑会话（独立副本）\n拓扑/参数表/配置构建器/对话修改\n→ 结果失效提示 → 显式“写回草稿”", "green", fs=8)
box(ax, 56, 4, 48, 20, "历史恢复：查看当时模型与结果\n（新建展示副本，不借用当前会话）\n→ 结果页/拓扑/三级运行", "purple", fs=8)
box(ax, 110, 4, 48, 20, "按原快照重跑（新任务）\n不重新解释资源库；\n冻结 code_hash 与执行 code_hash 分列", "red", fs=8)
arrow(ax, (26, 24.5), (28, 35.5), "写回→新 revision", rad=-0.2)
arrow(ax, (140, 35.5), (80, 24.5), "", rad=0.15)
arrow(ax, (148, 35.5), (134, 24.5))
save(fig, "fig_mainloop.png")

# F3 对象状态
fig, ax = canvas(16, 7.5)
box(ax, 2, 50, 22, 12, "Draft r(n)\n可编辑", "green")
box(ax, 34, 50, 22, 12, "Draft r(n+1)", "green")
box(ax, 70, 50, 24, 12, "Version v(k)\n不可变 + hash", "purple")
box(ax, 104, 50, 24, 12, "Version v(k+1)", "purple")
arrow(ax, (24.5, 56), (33.5, 56), "PATCH draft\n(revision 匹配)")
arrow(ax, (56.5, 56), (69.5, 56), "validate→publish\n(无 pending)")
arrow(ax, (94.5, 56), (103.5, 56), "下一次发布\n只追加")
box(ax, 2, 18, 22, 12, "ready", "amber")
box(ax, 36, 18, 22, 12, "running", "amber")
box(ax, 72, 26, 24, 10, "completed\n结果不可覆盖", "green")
box(ax, 72, 8, 24, 10, "failed\n错误/partial 保留", "red")
box(ax, 112, 18, 30, 12, "重跑 → 新 Task\n(rerun_of 指向原任务)", "grey")
arrow(ax, (82, 49.5), (14, 30.5), "POST /tasks\n冻结快照", rad=0.15)
arrow(ax, (24.5, 24), (35.5, 24), "run")
arrow(ax, (58.5, 26), (71.5, 30))
arrow(ax, (58.5, 22), (71.5, 13))
arrow(ax, (96.5, 31), (111.5, 26))
arrow(ax, (96.5, 13), (111.5, 21))
ax.text(47, 3, "服务重启时 running 任务被标记 failed（不偷偷续算）；任务状态只能 ready→running→completed/failed", ha="center", fontsize=8)
save(fig, "fig_states.png")

# F4 绑定校验
fig, ax = canvas(16, 6.2)
box(ax, 2, 30, 30, 22, "待操作选择（下拉）\n资源名 · r 版本 · ID\n目标：场景公共信号 /\n指定 DC / 指定设备", "blue", fs=8)
box(ax, 42, 30, 34, 22, "逐字段比对场景时间轴\nlocation · year · timezone(IANA)\nstart · step_minutes · length\n单位/有限值/无缺失", "amber", fs=8)
box(ax, 86, 38, 34, 16, "一致 → add / replace\n（同类已存在须显式 replace）\n原子保存，草稿 revision+1", "green", fs=8)
box(ax, 86, 14, 34, 18, "不一致 → axis_mismatch\n逐字段：期待值 vs 实际值\n不保存、不回退示例、不猜测", "red", fs=8)
box(ax, 128, 22, 30, 24, "可选：勾选“同时按所选\n数据设置草稿时间轴”\n确认后与替换原子提交；\n其他绑定冲突则整体拒绝", "grey", fs=8)
arrow(ax, (32.5, 41), (41.5, 41)); arrow(ax, (76.5, 44), (85.5, 46)); arrow(ax, (76.5, 37), (85.5, 24))
arrow(ax, (120.5, 23), (127.5, 30), ls="--")
ax.text(80, 5, "设备性能模型无时间轴：按设备类型+目标匹配；负荷按 kind+DC；气象/电价/碳按 kind 唯一", ha="center", fontsize=8)
save(fig, "fig_binding.png")

# F5 模型族与时间步支持
fig, ax = canvas(16, 8)
rows = [("日调度 sdco_engine（会话/版本化任务）", "1h ✔ / 15min ✔", "energy ✔ / continuous MILP ✔", "cost · weighted_carbon · welfare", "green"),
        ("三级运行 tiered", "仅 1h", "仅 energy", "滚动/包络/实时（显式拒绝15min）", "amber"),
        ("VCC 容量整形", "仅 1h", "仅 energy", "carbon/price/weighted（拒绝15min）", "amber"),
        ("市场沙盘 market.core", "仅 1h", "—", "示范规则包（拒绝15min）", "amber"),
        ("年度 8760 寻优 opt/annual（原入口）", "仅 1h", "—", "单目标/加权/字典序/Pareto", "amber"),
        ("opt_cfe 年度 CFE（版本化任务）", "1h·UTC·8760/8784", "—", "cost 采购；三种匹配政策", "blue"),
        ("opt_grid_feedback（版本化任务）", "1h·UTC·≤168h", "空间流体工作", "cost 封套；四信号实验", "blue"),
        ("opt_gpu（版本化任务）", "1h / 15min·1–96 步", "固定 gang 离散 MILP", "energy_cost/fair_minimax/headroom", "blue")]
hdr = ["引擎/模式", "时间步", "任务形态", "目标/说明"]
xs = [2, 62, 94, 124]; ws = [58, 30, 28, 34]
for x, w, h in zip(xs, ws, hdr): box(ax, x, 72, w, 6, h, "grey", fs=8.5, bold=True)
for r, row in enumerate(rows):
    y = 64 - r*8.2
    for k in range(4): box(ax, xs[k], y, ws[k], 6.2, row[k], row[4] if k == 0 else "white", fs=7.6)
save(fig, "fig_engines.png")

# F6 三级运行
fig, ax = canvas(16, 5.5)
seq = [("日前基线", "save_day_ahead_baseline\nbaseline_vN.json", "blue"), ("预测补丁", "apply_forecast_patch\n“下午3点光伏少20%”", "grey"),
       ("日内滚动", "reoptimize_intraday\n锁定已过时段+偏离罚\n可选 SOC 实测", "green"), ("可行响应域", "compute_flexibility_envelope\n日前→日内→实时收缩", "amber"),
       ("实时跟踪", "run_realtime_track\nMPC-lite / rules（A01 已修）", "red"), ("兜底", "UPS/柴发可调度\n应急模式 emergency", "purple")]
for i, (t, s, c) in enumerate(seq):
    x = 2 + i*26.3
    box(ax, x, 14, 23, 22, s, c, fs=7.6); ax.text(x+11.5, 38.5, t, ha="center", fontsize=9, fontweight="bold")
    if i: arrow(ax, (x-3, 25), (x-0.3, 25))
ax.text(80, 4, "仅 1h/energy 任务；15min 或 continuous 场景调用时显式报错（time_axis.require_hourly）", ha="center", fontsize=8.5)
save(fig, "fig_tier.png")

# F7 交易沙盘状态流
fig, ax = canvas(16, 6)
st = [("draft", "green"), ("submitted", "blue"), ("approved", "blue"), ("sandbox_cleared", "amber"), ("settled", "purple")]
for i, (t, c) in enumerate(st):
    x = 4 + i*31
    box(ax, x, 30, 24, 10, t, c, fs=9, bold=True)
    if i: arrow(ax, (x-6.5, 35), (x-0.3, 35))
ax.text(35, 42.5, "物理检查不通过不可提交", ha="center", fontsize=7.5)
ax.text(66, 42.5, "四眼：审核人≠编制人", ha="center", fontsize=7.5)
box(ax, 66, 6, 30, 11, "rejected", "grey", fs=9)
arrow(ax, (54, 30), (75, 17.5), rad=-0.1)
box(ax, 108, 4, 50, 15, "external_submit（真实提交）\n→ PermissionError → HTTP 403\n“真实外部下单不可执行”，写审计", "red", fs=8)
ax.text(30, 10, "所有转移写 SHA256 哈希链审计 audit.jsonl", ha="center", fontsize=8)
save(fig, "fig_market.png")

# F8 电网再出清反馈环
fig, ax = canvas(16, 7)
box(ax, 4, 42, 32, 14, "① 基态成本 DCOPF\n(ISO 目标，碳价默认 0)", "blue", fs=8.5)
box(ax, 50, 42, 34, 14, "② 信号计算\nLMCE(±FD/活跃基) · LMP\n区域平均 · 超额清洁(MW)", "amber", fs=8)
box(ax, 98, 42, 34, 14, "③ 工作调度 LP\nΣwork 每小时守恒 · ±flex\n锁主目标→最小 gross", "green", fs=8)
box(ax, 98, 10, 34, 14, "④ 候选负荷真实再出清\n每个 LP 必须 optimal", "blue", fs=8.5)
box(ax, 50, 10, 34, 14, "⑤ 判定：固定点/周期/\n迭代上限/信号不稳/失败", "red", fs=8)
box(ax, 4, 10, 32, 14, "输出：预测Δ vs 实际Δ\n运行碳/LCA/USD 分账\n固定点≠全局最优", "purple", fs=8)
arrow(ax, (36.5, 49), (49.5, 49)); arrow(ax, (84.5, 49), (97.5, 49)); arrow(ax, (115, 41.5), (115, 24.5))
arrow(ax, (97.5, 17), (84.5, 17)); arrow(ax, (49.5, 17), (36.5, 17)); arrow(ax, (67, 24.5), (67, 41.5), "未收敛→更新信号")
save(fig, "fig_gridfeedback.png")

# F9 热边界分账
fig, ax = canvas(16, 5.2)
seq = [("热泵源注入", "13.055"), ("管段发送", "12.973"), ("管段出口到达", "11.675"), ("终端实际取热", "11.500")]
for i, (t, v) in enumerate(seq):
    x = 4 + i*39
    box(ax, x, 24, 28, 14, f"{t}\n{v} MWh_th", ["blue", "green", "amber", "purple"][i], fs=8.5)
    if i: arrow(ax, (x-10.5, 31), (x-0.3, 31))
ax.text(37.5, 19, "plant TES 损失 0.082", ha="center", fontsize=7.8)
ax.text(76.5, 19, "管损 10% = 1.297", ha="center", fontsize=7.8)
ax.text(115.5, 19, "受端 TES 损失 0.175", ha="center", fontsize=7.8)
ax.text(80, 6, "SYNTHETIC 守恒控制（Phase5 任务 da4c5d48e4344406）：售热/锅炉碳抵扣以“终端实际取热”为分母；全局残差约 1e-15", ha="center", fontsize=8)
save(fig, "fig_heat.png")

# F10 执行域与审计导出
fig, ax = canvas(16, 6)
box(ax, 2, 30, 30, 18, "并发请求\n（日调度/年度/\nVCC/三级/新模式）", "grey", fs=8)
box(ax, 42, 30, 36, 18, "进程级 FIFO 执行域\n建模→表示→求解→加载\n同线程可重入；异常释放", "amber", fs=8)
box(ax, 88, 30, 32, 18, "checked_solve\nbackend 前/后变量归属校验\nforeign>0 → 失败(fail-closed)", "red", fs=8)
box(ax, 128, 30, 30, 18, "结果/失败落库\n排队时间与求解软限分账\n/api/solver-execution/status", "green", fs=8)
for a, b in [(32.5, 41.5), (78.5, 87.5), (120.5, 127.5)]: arrow(ax, (a, 39), (b, 39))
box(ax, 2, 4, 156, 16, "审计导出：日模型→历史副本“下载审计运行包”（scenario/params/formulation/solver_config/runlog/results/dispatch/heat_nodes/heat_pipes/\nallocations/job_admission/migration_audit/network_dispatch/integer_events/ledger/input_snapshot/frozen_task_metadata/reproduce.py）；\nopt_cfe / opt_grid_feedback / opt_gpu → GET /api/foundation/tasks/{id}/export.zip（失败任务无 results.json，可有 partial_NOT_ACCEPTED.json）", "white", fs=7.3)
save(fig, "fig_exec.png")
print("figures:", sorted(p.name for p in OUT.glob("*.png")))
