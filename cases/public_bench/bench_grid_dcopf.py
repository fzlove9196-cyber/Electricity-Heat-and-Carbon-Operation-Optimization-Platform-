"""B1: 公开电网案例 (pandapower 内置 IEEE14/30/57/118, 源自 MATPOWER / UW PSTCA) 验证
   (a) 引擎 B-theta 支路模型 vs pandapower rundcpp 线路潮流;
   (b) 引擎多时段 DC-OPF (case14, 无DC/储能 => 各小时解耦) vs pandapower rundcopp 每小时参考解(成本/功率平衡/线路约束)。
用法: python cases/public_bench/bench_grid_dcopf.py [--tag before|after]"""
import sys, json, hashlib, os, copy, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandapower as pp, pandapower.networks as pn
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from app.tools import sdco_engine as E
from app.scenario import Scenario
TAG = sys.argv[sys.argv.index("--tag")+1] if "--tag" in sys.argv else "run"
OUT = os.path.join(os.path.dirname(__file__), "results"); os.makedirs(OUT, exist_ok=True)
res = {"tag": TAG, "pandapower": pp.__version__, "flow_check": {}, "opf_check": {}}

def sha(fn): return hashlib.sha256(open(fn, "rb").read()).hexdigest()
nd = os.path.join(os.path.dirname(pn.__file__), "power_system_test_case_jsons")
res["raw_files"] = {f: sha(os.path.join(nd, f)) for f in sorted(os.listdir(nd)) if f in ("case14.json","case30.json","case57.json","case118.json")} if os.path.isdir(nd) else {}

# (a) branch model: engine arrays (fb,tb,xb[,tap]) -> flows from pandapower angles vs res_line/res_trafo
for name in ["case14", "case30", "case57", "case118"]:
    net = getattr(pn, name)(); pp.rundcpp(net)
    A = E.branch_arrays(net) if hasattr(E, "branch_arrays") else None
    br = net._ppc["branch"]; fb = br[:, 0].real.astype(int); tb = br[:, 1].real.astype(int)
    xb = A["xb"] if A else br[:, 3].real
    th = np.deg2rad(net._ppc["bus"][:, 8].real)
    f_eng = (th[fb] - th[tb]) / xb * net.sn_mva
    f_ref = np.r_[net.res_line.p_from_mw.values, net.res_trafo.p_hv_mw.values][:len(br)]
    err = np.abs(f_eng - f_ref); ntr = len(net.trafo)
    res["flow_check"][name] = dict(n_branch=len(br), max_abs_err_mw=float(err.max()), mean_abs_err_mw=float(err.mean()),
        max_rel_err_pct=float((err/np.maximum(np.abs(f_ref), 1.0)).max()*100), trafo_max_abs_err_mw=float(err[len(net.line):].max()) if ntr else 0.0,
        pass_=bool(err.max() < 1e-3))
    print(name, res["flow_check"][name])

# (b) multi-hour OPF on case14 vs pandapower rundcopp
_orig = list(E._LINE_RATING)
for RS in (1.0, 0.45):
  E._LINE_RATING[:] = [x*RS for x in _orig]
  sc = Scenario(); N = E.prepare_network(sc); N['rating'] = N['rating']*1.0
  lp = E.load_profile()*sc.load_scale
  r = E.solve(sc, optimize=True)
  df = r["df"]; gcols = [c for c in df.columns if c.startswith("gen") and c.endswith("_MW")]
  hours = []
  for t in range(24):
      net = pn.case14(); net.load.p_mw *= lp[t]
      rating = N["rating"]; nl = N["nl"]
      net.line["max_i_ka"] = rating[:nl]/(np.sqrt(3)*net.bus.vn_kv[net.line.from_bus].values); net.line["max_loading_percent"] = 100.0
      net.trafo["max_loading_percent"] = rating[nl:]/net.trafo.sn_mva.values*100  # 不改 sn_mva(会改变 pu 阻抗)
      g = r["gens"]; net.poly_cost.drop(net.poly_cost.index, inplace=True)
      for i in net.ext_grid.index:
          net.ext_grid.loc[i, ["max_p_mw","min_p_mw"]] = [g[0]["pmax"], 0.0]
          pp.create_poly_cost(net, i, "ext_grid", cp1_eur_per_mw=g[0]["cost"][t])
      for k, i in enumerate(net.gen.index):
          gg = g[1+k]; net.gen.loc[i, ["max_p_mw","min_p_mw","controllable"]] = [gg["pmax"], gg["pmin"], True]
          pp.create_poly_cost(net, i, "gen", cp1_eur_per_mw=gg["cost"][t])
      pp.rundcopp(net, verbose=False)
      ref_cost = float(net.res_cost); ref_ld = float(max(net.res_line.loading_percent.max(), net.res_trafo.loading_percent.max()))
      eng_cost = float(df.hour_cost[t]) if "hour_cost" in df else None
      eng_pg = [float(df[c][t]) for c in gcols]; ref_pg = [float(net.res_ext_grid.p_mw.sum())] + list(map(float, net.res_gen.p_mw))
      bal = float(sum(eng_pg) - net.load.p_mw.sum())
      hours.append(dict(t=t, load=float(net.load.p_mw.sum()), eng_cost=eng_cost, ref_cost=ref_cost,
                        cost_rel_err_pct=abs(eng_cost-ref_cost)/ref_cost*100, eng_pg=eng_pg, ref_pg=ref_pg,
                        balance_resid_mw=bal, eng_max_loading=float(df.max_line_loading_pct[t]), ref_max_line_loading=ref_ld))
  mx = max(h["cost_rel_err_pct"] for h in hours)
  key = "uncongested" if RS == 1.0 else "congested_rating_x0.45"
  res["opf_check"][key] = dict(case=f"case14 x 24h, engine ratings x{RS}", hours=hours, max_cost_rel_err_pct=mx,
      max_balance_resid_mw=max(abs(h["balance_resid_mw"]) for h in hours), max_eng_loading=max(h["eng_max_loading"] for h in hours),
      pass_=bool(mx < 0.01 and max(abs(h["balance_resid_mw"]) for h in hours) < 1e-3 and max(h["eng_max_loading"] for h in hours) <= 100+1e-6))
  print(key, {k: v for k, v in res["opf_check"][key].items() if k != "hours"})
E._LINE_RATING[:] = _orig
json.dump(res, open(os.path.join(OUT, f"b1_grid_{TAG}.json"), "w"), indent=1, ensure_ascii=False)
