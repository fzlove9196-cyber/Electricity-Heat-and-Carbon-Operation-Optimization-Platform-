"""其他仿真器工具：MATPOWER(Octave) / ANDES 暂态 / OpenDSS 配网 / OpenModelica / ParaView。
均通过 @tool 注册；外部程序以 subprocess 调用（无需额外 Python 依赖），结果落盘为 CSV/JSON/PNG。"""
from __future__ import annotations
import json, os, re, shutil, subprocess, textwrap
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from .base import tool, Session
from .sim_tools import _art

def _run(cmd, cwd, timeout=300, stdin=None):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, input=stdin)
    if p.returncode != 0:
        raise RuntimeError(f"{cmd[0]} 退出码 {p.returncode}: {(p.stderr or p.stdout)[-800:]}")
    return p.stdout

def _safe_name(x, pat=r"^[A-Za-z0-9_.]+$"):
    if not re.match(pat, x or ""): raise ValueError(f"非法名称: {x!r}")
    return x

# ---------------- MATPOWER ----------------
@tool("run_matpower", "用 GNU Octave + MATPOWER 8.1 运行潮流(runpf)/最优潮流(runopf)/直流潮流(rundcpf)。"
      "适用于“MATPOWER/Octave/标准算例潮流/OPF”。", {
    "type": "object", "properties": {
        "case": {"type": "string", "default": "case14", "description": "MATPOWER 算例名，如 case14/case30/case118/case9"},
        "mode": {"type": "string", "enum": ["runpf", "runopf", "rundcpf", "rundcopf"], "default": "runopf"},
        "load_scale": {"type": "number", "default": 1.0}}})
def run_matpower(s: Session, case="case14", mode="runopf", load_scale=1.0):
    case = _safe_name(case); os.makedirs(s.artifact_dir, exist_ok=True)
    pre = f"mp_{case}_{mode}"
    script = f"""mpopt=mpoption('verbose',0,'out.all',0); mpc=loadcase('{case}');
mpc.bus(:,3:4)=mpc.bus(:,3:4)*{float(load_scale)}; r={mode}(mpc,mpopt);
f=0; if isfield(r,'f') && ~isempty(r.f), f=r.f; end
nl=size(r.branch,1); ld=zeros(nl,1); rt=r.branch(:,6);
if size(r.branch,2)>=14, s=max(abs(r.branch(:,14)+1j*r.branch(:,15)),abs(r.branch(:,16)+1j*r.branch(:,17))); ld(rt>0)=s(rt>0)./rt(rt>0)*100; end
dlmwrite('{pre}_bus.csv', r.bus(:,[1 3 8 9]), 'precision', 8);
dlmwrite('{pre}_gen.csv', r.gen(:,[1 2 3]), 'precision', 8);
printf('JSON{{"success":%d,"f":%.4f,"vmin":%.5f,"vmax":%.5f,"max_loading":%.3f,"pg_total":%.3f,"pd_total":%.3f}}\\n', r.success, f, min(r.bus(:,8)), max(r.bus(:,8)), max(ld), sum(r.gen(:,2)), sum(r.bus(:,3)));
"""
    out = _run(["octave-cli", "-q", "--eval", script], s.artifact_dir, 180)
    m = re.search(r"JSON(\{.*\})", out)
    if not m: raise RuntimeError("MATPOWER 输出解析失败: " + out[-500:])
    res = json.loads(m.group(1))
    b = pd.read_csv(os.path.join(s.artifact_dir, f"{pre}_bus.csv"), header=None, names=["bus", "Pd_MW", "Vm_pu", "Va_deg"])
    b.to_csv(_art(s, f"{pre}_bus.csv"), index=False); _art(s, f"{pre}_gen.csv")
    s.state.setdefault("matpower", {})[f"{case}_{mode}"] = res
    return {"ok": bool(res["success"]), "case": case, "mode": mode, **res,
            "note": "max_loading 仅对有额定值(RATE_A>0)的支路且仅 OPF 输出时有效",
            "artifacts": [f"{pre}_bus.csv", f"{pre}_gen.csv"]}

# ---------------- ANDES ----------------
@tool("run_andes_tds", "用 ANDES 2.0 做时域暂态稳定仿真（Kundur 两区四机），模拟数据中心负荷阶跃/突变，"
      "返回频率与电压轨迹。适用于“暂态/稳定/频率响应/负荷突增/负荷波动”。", {
    "type": "object", "properties": {
        "case": {"type": "string", "default": "kundur/kundur_full.xlsx"},
        "load_idx": {"type": "string", "default": "PQ_1", "description": "阶跃负荷 (代表数据中心)"},
        "step_mw": {"type": "number", "default": 50, "description": "负荷阶跃 MW（正=增加）"},
        "t_step": {"type": "number", "default": 1.0}, "tf": {"type": "number", "default": 15.0},
        "keep_case_events": {"type": "boolean", "default": False, "description": "是否保留算例自带的 Toggle 事件"}}})
def run_andes_tds(s: Session, case="kundur/kundur_full.xlsx", load_idx="PQ_1", step_mw=50, t_step=1.0, tf=15.0,
                  keep_case_events=False):
    import andes
    andes.config_logger(stream_level=40)
    ss = andes.load(andes.get_case(case), setup=False, no_output=True, default_config=True,
                    config_option=["PQ.p2p=1", "PQ.p2z=0", "PQ.q2q=1", "PQ.q2z=0"])
    base = ss.config.mva
    if step_mw: ss.add("Alter", dict(t=t_step, model="PQ", dev=load_idx, src="Ppf", attr="v", method="+",
                                     amount=step_mw/base))
    ss.setup()
    if not keep_case_events and ss.Toggle.n: ss.Toggle.u.v[:] = 0
    ss.PFlow.run()
    if not ss.PFlow.converged: raise RuntimeError("ANDES 潮流不收敛")
    ss.TDS.config.tf = tf; ss.TDS.config.no_tqdm = 1; ss.TDS.run()
    t = np.array(ss.dae.ts.t); w = np.array(ss.dae.ts.x[:, ss.GENROU.omega.a]); v = np.array(ss.dae.ts.y[:, ss.Bus.v.a])
    fn = 60.0 if "kundur" in case else 50.0
    df = pd.DataFrame({"t": t, **{f"f_{g}_Hz": w[:, i]*fn for i, g in enumerate(ss.GENROU.idx.v)},
                       **{f"V_{b}_pu": v[:, i] for i, b in enumerate(ss.Bus.idx.v)}})
    df.to_csv(_art(s, "andes_tds.csv"), index=False)
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    for c in df.columns[1:1+len(ss.GENROU.idx.v)]: ax[0].plot(t, df[c], label=c)
    for c in [c for c in df if c.startswith("V_")]: ax[1].plot(t, df[c], lw=.8)
    ax[0].set_title(f"发电机频率 (负荷阶跃 {step_mw} MW @ {t_step}s)"); ax[0].set_xlabel("t (s)"); ax[0].legend(fontsize=7)
    ax[1].set_title("母线电压 (pu)"); ax[1].set_xlabel("t (s)"); fig.tight_layout()
    fig.savefig(_art(s, "andes_tds.png"), dpi=110); plt.close(fig)
    fcols = [c for c in df if c.startswith("f_")]; vcols = [c for c in df if c.startswith("V_")]
    res = dict(converged=bool(ss.TDS.converged), t_end=float(t[-1]), nominal_hz=fn,
               f_min_hz=float(df[fcols].min().min()), f_final_hz=float(df[fcols].iloc[-1].mean()),
               rocof_max_hz_s=float(np.abs(np.diff(df[fcols].mean(axis=1))/np.maximum(np.diff(t), 1e-6)).max()),
               v_min_pu=float(df[vcols].min().min()), v_final_min_pu=float(df[vcols].iloc[-1].min()))
    s.state["andes"] = res
    return {"ok": res["converged"], **res, "artifacts": ["andes_tds.csv", "andes_tds.png"],
            "note": "ANDES 算例为 Kundur 标准系统；负荷阶跃为合成场景"}

# ---------------- OpenDSS ----------------
_FEEDER = """clear
new circuit.sdco_feeder basekv=10.5 pu=1.02 phases=3 bus1=src MVAsc3=200
new linecode.lc nphases=3 r1=0.27 x1=0.35 r0=0.6 x0=1.2 units=km normamps=400
{lines}
new loadshape.office npts=24 interval=1 mult=({lshape})
new loadshape.dc npts=24 interval=1 mult=({dcshape})
new loadshape.pvs npts=24 interval=1 mult=({pvshape})
{loads}
new load.DC bus1=n{dc_bus} phases=3 kv=10.5 kw={dc_kw} pf=0.98 daily=dc
new pvsystem.PV bus1=n{pv_bus} phases=3 kv=10.5 pmpp={pv_kw} kva={pv_kva} irradiance=1 daily=pvs
{storage}
set voltagebases=[10.5]
calcvoltagebases
"""

@tool("run_opendss", "用 OpenDSS (opendssdirect) 做 10kV 配电馈线 24h 时序潮流，含数据中心负荷、光伏和可选储能；"
      "返回电压、线路负载、网损。适用于“配网/馈线/OpenDSS/低压/电压越限”。", {
    "type": "object", "properties": {
        "n_nodes": {"type": "integer", "default": 8}, "dc_kw": {"type": "number", "default": 3000},
        "dc_bus": {"type": "integer", "default": 8}, "pv_kw": {"type": "number", "default": 2000},
        "pv_bus": {"type": "integer", "default": 6}, "storage_kwh": {"type": "number", "default": 0},
        "seg_km": {"type": "number", "default": 1.0}}})
def run_opendss(s: Session, n_nodes=8, dc_kw=3000, dc_bus=8, pv_kw=2000, pv_bus=6, storage_kwh=0, seg_km=1.0):
    import opendssdirect as dss
    n = int(n_nodes); dc_bus = min(int(dc_bus), n); pv_bus = min(int(pv_bus), n)
    h = np.arange(24)
    lshape = 0.6 + 0.3*np.exp(-((h-11)/3.5)**2) + 0.35*np.exp(-((h-19)/2.5)**2)
    dcshape = 0.8 + 0.15*np.exp(-((h-20)/3)**2)
    pvshape = np.clip(np.sin((h-6)/12*np.pi), 0, None)
    lines = "\n".join(f"new line.L{i} bus1={'src' if i == 1 else f'n{i-1}'} bus2=n{i} linecode=lc length={seg_km} units=km"
                      for i in range(1, n+1))
    loads = "\n".join(f"new load.LD{i} bus1=n{i} phases=3 kv=10.5 kw=400 pf=0.95 daily=office" for i in range(1, n+1))
    sto = ""
    if storage_kwh:
        sto = (f"new storage.ESS bus1=n{dc_bus} phases=3 kv=10.5 kwrated={storage_kwh/4} kwhrated={storage_kwh} "
               f"%stored=50 dispmode=follow daily=essshape")
        ess = np.where((h < 7) | (h >= 22), -0.8, np.where(((h >= 10) & (h < 12)) | ((h >= 17) & (h < 22)), 0.8, 0))
        sto = f"new loadshape.essshape npts=24 interval=1 mult=({' '.join(map(str, ess))})\n" + sto
    f = lambda a: " ".join(f"{x:.4f}" for x in a)
    txt = _FEEDER.format(lines=lines, loads=loads, lshape=f(lshape), dcshape=f(dcshape), pvshape=f(pvshape), dc_bus=dc_bus,
                         dc_kw=dc_kw, pv_bus=pv_bus, pv_kw=pv_kw, pv_kva=pv_kw*1.1, storage=sto)
    with open(_art(s, "feeder.dss"), "w") as fh: fh.write(txt)
    dss.Basic.ClearAll()
    for line in txt.splitlines():
        if line.strip():
            dss.Text.Command(line)
    dss.Text.Command("set mode=daily stepsize=1h number=1")
    rows = []
    for t in range(24):
        dss.Solution.Solve()
        if not dss.Solution.Converged(): raise RuntimeError(f"OpenDSS 第 {t} 小时不收敛")
        vpu = np.array(dss.Circuit.AllBusMagPu())
        loading = []
        for nm in dss.Lines.AllNames():
            dss.Lines.Name(nm); dss.Circuit.SetActiveElement(f"line.{nm}")
            loading.append(max(dss.CktElement.CurrentsMagAng()[0:6:2])/dss.Lines.NormAmps()*100)
        p, q = dss.Circuit.TotalPower(); loss = dss.Circuit.Losses()[0]/1000
        rows.append(dict(hour=t, vmin_pu=vpu.min(), vmax_pu=vpu.max(), max_line_loading_pct=max(loading),
                         substation_kw=-p, losses_kw=loss))
    df = pd.DataFrame(rows); df.to_csv(_art(s, "opendss_timeseries.csv"), index=False)
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    ax[0].plot(df.hour, df.vmin_pu, label="Vmin"); ax[0].plot(df.hour, df.vmax_pu, label="Vmax")
    ax[0].axhline(0.93, ls="--", c="r"); ax[0].axhline(1.07, ls="--", c="r"); ax[0].legend(); ax[0].set_title("馈线电压 (pu)")
    ax[1].plot(df.hour, df.substation_kw/1000, label="变电站功率 MW"); ax[1].plot(df.hour, df.max_line_loading_pct/100, label="最大线路负载率(×100%)")
    ax[1].legend(); ax[1].set_xlabel("小时"); fig.tight_layout(); fig.savefig(_art(s, "opendss_timeseries.png"), dpi=110); plt.close(fig)
    res = dict(vmin_pu=float(df.vmin_pu.min()), vmax_pu=float(df.vmax_pu.max()),
               max_line_loading_pct=float(df.max_line_loading_pct.max()), energy_losses_kwh=float(df.losses_kw.sum()),
               peak_substation_kw=float(df.substation_kw.max()),
               voltage_violation_hours=int(((df.vmin_pu < 0.93) | (df.vmax_pu > 1.07)).sum()))
    s.state["opendss"] = res
    return {"ok": True, **res, "artifacts": ["feeder.dss", "opendss_timeseries.csv", "opendss_timeseries.png"],
            "note": "馈线参数为合成数据"}

# ---------------- OpenModelica ----------------
_DEFAULT_MO = """model DCLoadSwing "合成: 单机等值系统频率响应, 数据中心负荷阶跃 (synthetic)"
  parameter Real H = 5 "惯性常数 s";
  parameter Real D = 1 "阻尼";
  parameter Real R = 0.05 "调差";
  parameter Real Tg = 0.5 "调速器时间常数";
  parameter Real dP = {dp} "负荷阶跃 pu";
  parameter Real tStep = 1;
  Real df(start=0) "频率偏差 pu";
  Real Pm(start=0) "机械功率增量 pu";
  Real Pl;
equation
  Pl = if time >= tStep then dP else 0;
  2*H*der(df) = Pm - Pl - D*df;
  Tg*der(Pm) = -df/R - Pm;
end DCLoadSwing;
"""

@tool("run_openmodelica", "用 OpenModelica (omc) 编译仿真 Modelica 模型，返回 CSV。可传自定义 .mo 源码、"
      "或 PowerSystems 2.0 / MSL 4.1 库中的模型名；缺省为合成的单机频率响应模型(数据中心负荷阶跃)。"
      "适用于“Modelica/OpenModelica/物理建模/动态模型”。", {
    "type": "object", "properties": {
        "model_name": {"type": "string", "description": "如 PowerSystems.Examples.PowerWorld.PowerWorld；缺省 DCLoadSwing"},
        "mo_source": {"type": "string", "description": "自定义 Modelica 源码（可选）"},
        "step_pu": {"type": "number", "default": 0.1}, "stop_time": {"type": "number", "default": 20},
        "variables": {"type": "array", "items": {"type": "string"}, "description": "返回的变量(可选)"}}})
def run_openmodelica(s: Session, model_name=None, mo_source=None, step_pu=0.1, stop_time=20, variables=None):
    os.makedirs(s.artifact_dir, exist_ok=True)
    loads = ["loadModel(Modelica);"]
    if model_name and model_name.startswith("PowerSystems"): loads.append("loadModel(PowerSystems);")
    if not model_name and not mo_source:
        mo_source = _DEFAULT_MO.format(dp=float(step_pu)); model_name = "DCLoadSwing"
    if mo_source:
        m = re.search(r"^\s*model\s+(\w+)", mo_source, re.M)
        model_name = model_name or (m and m.group(1))
        if not model_name: raise ValueError("无法从 mo_source 识别模型名")
        with open(_art(s, "model.mo"), "w") as fh: fh.write(mo_source)
        loads.append('loadFile("model.mo");')
    _safe_name(model_name)
    mos = "\n".join(loads + ["getErrorString();",
        f'res := simulate({model_name}, stopTime={float(stop_time)}, numberOfIntervals=1000, outputFormat="csv");',
        'print(res.resultFile + "\\n");', "getErrorString();"])
    with open(_art(s, "run.mos"), "w") as fh: fh.write(mos)
    out = _run(["omc", "run.mos"], s.artifact_dir, 600)
    csv = os.path.join(s.artifact_dir, f"{model_name}_res.csv")
    if not os.path.exists(csv): raise RuntimeError("OpenModelica 仿真失败: " + out[-1200:])
    df = pd.read_csv(csv)
    cols = [c for c in (variables or []) if c in df] or [c for c in df.columns if c != "time" and not c.startswith("der(")][:8]
    out_csv = f"om_{model_name}.csv"; df[["time"] + cols].to_csv(_art(s, out_csv), index=False)
    fig, ax = plt.subplots(figsize=(9, 4))
    for c in cols: ax.plot(df.time, df[c], label=c)
    ax.legend(fontsize=7); ax.set_xlabel("time (s)"); ax.set_title(f"OpenModelica: {model_name}"); fig.tight_layout()
    fig.savefig(_art(s, f"om_{model_name}.png"), dpi=110); plt.close(fig)
    for f in os.listdir(s.artifact_dir):   # 清理编译中间文件
        if f.startswith(model_name) and not f.endswith("_res.csv"):
            p = os.path.join(s.artifact_dir, f)
            if os.path.isfile(p): os.remove(p)
    summ = {c: dict(min=float(df[c].min()), max=float(df[c].max()), final=float(df[c].iloc[-1])) for c in cols}
    s.state["openmodelica"] = summ
    return {"ok": True, "model": model_name, "n_points": len(df), "summary": summ,
            "artifacts": [out_csv, f"om_{model_name}.png"]}

# ---------------- ParaView (optional) ----------------
@tool("run_paraview_render", "可选：用 ParaView pvpython 把 IEEE14 母线电压渲染为 3D 柱状图(VTK+PNG)。"
      "需先 run_ac_check。适用于“三维/3D/可视化/ParaView/VTK”。", {"type": "object", "properties": {}})
def run_paraview_render(s: Session):
    if not shutil.which("pvpython"): raise RuntimeError("未安装 pvpython")
    import pandapower.networks as pn
    from .sim_tools import _sc, _res
    from . import sdco_engine as eng
    net = pn.case14(); coords = np.array([[c[0], c[1]] for c in _bus_xy(net)])
    vm = s.state.get("_vm")
    if vm is None:
        eng.ac_check(_sc(s), _res(s)); vm = np.ones(len(net.bus))
    vm = np.asarray(s.state.get("_vm", vm))
    vtk = _art(s, "bus_voltage.vtk")
    with open(vtk, "w") as f:
        f.write(f"# vtk DataFile Version 3.0\nbus voltage\nASCII\nDATASET POLYDATA\nPOINTS {len(vm)} float\n")
        for (x, y) in coords: f.write(f"{x} {y} 0\n")
        f.write(f"VERTICES {len(vm)} {2*len(vm)}\n" + "".join(f"1 {i}\n" for i in range(len(vm))))
        f.write(f"POINT_DATA {len(vm)}\nSCALARS vm_pu float 1\nLOOKUP_TABLE default\n" + "".join(f"{v}\n" for v in vm))
    png = os.path.join(s.artifact_dir, "bus_voltage_3d.png")
    script = textwrap.dedent(f"""
        from paraview.simple import *
        r = LegacyVTKReader(FileNames=[{vtk!r}])
        g = Glyph(Input=r, GlyphType='Sphere'); g.ScaleArray=['POINTS','No scale array']; g.ScaleFactor=0.3
        d = Show(g); ColorBy(d, ('POINTS','vm_pu')); d.SetScalarBarVisibility(GetActiveView(), True)
        v = GetActiveView(); v.ViewSize=[800,600]; ResetCamera(); SaveScreenshot({png!r}, v)
    """)
    _run(["pvpython", "--force-offscreen-rendering", "-"], s.artifact_dir, 180, stdin=script)
    _art(s, "bus_voltage_3d.png")
    return {"ok": os.path.exists(png), "artifacts": ["bus_voltage.vtk", "bus_voltage_3d.png"]}

def _bus_xy(net):
    ang = np.linspace(0, 2*np.pi, len(net.bus), endpoint=False)
    return np.c_[3*np.cos(ang), 3*np.sin(ang)]
