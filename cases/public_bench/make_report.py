"""汇总 B1-B4 结果 → figs/*.png + results/manifest.json (来源/许可/获取日期/哈希)。"""
import json, os, hashlib, glob, datetime
import numpy as np, pandas as pd, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
D = os.path.dirname(os.path.abspath(__file__)); RS = D + "/results"; FG = D + "/figs"; os.makedirs(FG, exist_ok=True)
L = lambda f: json.load(open(f"{RS}/{f}"))
b1b, b1a = L("b1_grid_before.json"), L("b1_grid_after.json")
cs = list(b1a["flow_check"]); x = np.arange(len(cs))
fig, ax = plt.subplots(1, 2, figsize=(11, 4))
ax[0].bar(x-0.2, [max(b1b["flow_check"][c]["max_abs_err_mw"], 1e-14) for c in cs], 0.4, label="before"); ax[0].bar(x+0.2, [max(b1a["flow_check"][c]["max_abs_err_mw"], 1e-14) for c in cs], 0.4, label="after")
ax[0].set_yscale("log"); ax[0].set_xticks(x, cs); ax[0].set_ylabel("max |ΔP_branch| MW vs pandapower"); ax[0].legend(); ax[0].set_title("B1a DC branch flow error")
for tag, b, ls in (("before", b1b, "--"), ("after", b1a, "-")):
    h = b["opf_check"]["congested_rating_x0.45"]["hours"]; ax[1].plot([z["cost_rel_err_pct"] for z in h], ls, label=tag)
ax[1].set_yscale("log"); ax[1].set_xlabel("hour"); ax[1].set_ylabel("OPF cost rel err %"); ax[1].set_title("B1b case14 congested DC-OPF vs rundcopp"); ax[1].legend()
plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]; fig.tight_layout(); fig.savefig(FG + "/b1_grid.png", dpi=110); plt.close()
b2 = L("b2_specpower.json"); ps = pd.DataFrame(b2["per_server"])
fig, ax = plt.subplots(1, 2, figsize=(11, 4))
ax[0].boxplot([ps.mape_identity, ps.mape_idle_dynamic, ps.mape_pwl3, ps.mape_pwl5], tick_labels=["identity", "idle_dyn(2pt)", "PWL 3pt", "PWL 5pt"]); ax[0].set_ylabel("hold-out MAPE %"); ax[0].set_title(f"B2 SPECpower n={len(ps)}")
r = b2["raw"][0]; u = np.r_[0, r["util"][::-1]]; p = np.r_[r["idle_w"], r["power_w"][::-1]]
for rr in b2["raw"][::6]:
    u = np.r_[0, rr["util"][::-1]]; p = np.r_[rr["idle_w"], rr["power_w"][::-1]]; ax[1].plot(u, p/p[-1], "o-", ms=3)
ax[1].plot([0, 1], [0, 1], "k:", label="identity"); ax[1].set_xlabel("utilization"); ax[1].set_ylabel("P / P(100%)"); ax[1].set_title("sample SPECpower curves"); ax[1].legend()
fig.tight_layout(); fig.savefig(FG + "/b2_specpower.png", dpi=110); plt.close()
fig, ax = plt.subplots(1, 2, figsize=(12, 4.2))
for k, (tag, ttl) in enumerate((("nominal_after", "nominal chiller"), ("stress_after", "stress chiller=1.05×IT"))):
    a = pd.DataFrame(L(f"b3_market_aemo_{tag}.json")["aggregate"]).set_index("strategy")
    a = a.loc[["naive", "myopic", "da_only", "da_id_rolling", "da_id_rolling_margin2K", "da_id_no_thermal", "oracle"]]
    ax[k].bar(a.index, a.cost_aud/1e6, color=["grey", "c", "b", "g", "olive", "r", "k"]); ax[k].set_ylabel("31-day cost (M AUD)"); ax[k].set_title(f"B3 AEMO SA1 2024-01 {ttl}")
    for i, (c, v) in enumerate(zip(a.cost_aud, a.thermal_viol_mwh)): ax[k].text(i, c/1e6, f"viol {v:.0f}MWh", ha="center", va="bottom", fontsize=7)
    ax[k].tick_params(axis="x", rotation=30)
fig.tight_layout(); fig.savefig(FG + "/b3_market.png", dpi=110); plt.close()
g = pd.DataFrame(L("b4_dr_bdg2.json")["summary"]); g["lab"] = g.method.str.replace("_", "\n") + np.where(g.day_type_filter, "\n+daytype", "")
fig, ax = plt.subplots(1, 2, figsize=(12, 4))
ax[0].bar(g.lab, g.bias_median_pct, color=np.where(g.day_type_filter, "g", "grey")); ax[0].set_ylabel("median baseline bias %"); ax[0].set_title("B4 BDG2 baseline bias (event 14-17h)")
ax[1].bar(g.lab, g.false_invalid_20*100, color=np.where(g.day_type_filter, "g", "grey")); ax[1].set_ylabel("% true 20% curtailment judged invalid"); ax[1].set_title("B4 false-invalid rate")
for a_ in ax: a_.tick_params(axis="x", labelsize=7)
fig.tight_layout(); fig.savefig(FG + "/b4_dr.png", dpi=110); plt.close()
sha = lambda f: hashlib.sha256(open(f, "rb").read()).hexdigest()
man = dict(generated=datetime.datetime.now().isoformat(timespec="seconds") + " (Asia/Shanghai)", retrieved="2026-11-06 (Asia/Shanghai)",
  sources=[
   dict(id="B1", name="IEEE 14/30/57/118 bus (pandapower 3.5.6 bundled, from MATPOWER / UW PSTCA)", url="https://github.com/e2nIEE/pandapower ; https://matpower.org", license="pandapower BSD-3; MATPOWER BSD-3; PSTCA public", files=b1a.get("raw_files", {})),
   dict(id="B2", name="SPECpower_ssj2008 published results (40 sampled, every 29th of index)", url="https://www.spec.org/power_ssj2008/results/", license="SPEC public results; fair-use citation per SPEC Fair Use Rule", files={os.path.basename(f): sha(f) for f in sorted(glob.glob(D + "/raw/specpower/*.txt"))}),
   dict(id="B3", name="AEMO NEM aggregated price & demand SA1 2023-12/2024-01", url="https://aemo.com.au/aemo/data/nem/priceanddemand/PRICE_AND_DEMAND_202401_SA1.csv", license="AEMO copyright permissions (general use with attribution)", files={os.path.basename(f): sha(f) for f in sorted(glob.glob(D + "/raw/aemo_*.csv"))}),
   dict(id="B3w", name="Open-Meteo historical weather API (ERA5) Adelaide hourly T2m", url="https://archive-api.open-meteo.com/v1/archive?latitude=-34.93&longitude=138.6&start_date=2023-12-01&end_date=2024-01-31&hourly=temperature_2m", license="CC BY 4.0", files={"openmeteo_adelaide_202312_202401.json": sha(D + "/raw/openmeteo_adelaide_202312_202401.json")}),
   dict(id="B4", name="Building Data Genome 2 electricity_cleaned.csv", url="https://github.com/buds-lab/building-data-genome-project-2", license="CC BY 4.0", files={"bdg2_electricity_cleaned.csv": sha(D + "/raw/bdg2_electricity_cleaned.csv")})],
  b4_aggregate=dict(script="bench_dr_bdg2_agg.py", result="results/b4agg_dr_bdg2.json", result_sha256=sha(RS + "/b4agg_dr_bdg2.json"),
                    events_csv_sha256=sha(RS + "/b4agg_dr_bdg2_events.csv"), raw="bdg2_electricity_cleaned.csv (same hash as B4)"),
  b4_methods=dict(script="bench_dr_methods.py", result="results/b4m_dr_methods.json", result_sha256=sha(RS + "/b4m_dr_methods.json"),
                  weather=dict(url="https://media.githubusercontent.com/media/buds-lab/building-data-genome-project-2/master/data/weather/weather.csv", license="CC BY 4.0", sha256=sha(D + "/raw/bdg2_weather.csv")),
                  references=["CAISO BPM for Demand Response §5.4 https://bpmcm.caiso.com/BPM%20Document%20Library/Demand%20Response/BPM_for_Demand_Response_V11_Redline.pdf",
                              "DNV KEMA for AEMO 2013 Baseline Consumption Methodology Phase I https://www.aemo.com.au/-/media/files/initiatives/wdr/baseline-consumption-methodology---phase-i-reportpdf.pdf",
                              "PJM Empirical Analysis of DR Baseline Methods https://www.nyiso.com/documents/20142/1393792/PJM_Baseline_Analysis_Mid-Course_Update.pdf",
                              "CAISO BAWG 2017 Nexant https://www.caiso.com/documents/2017baselineaccuracyworkgroupfinalproposalnexant.pdf",
                              "Coughlin et al. 2008 LBNL-63728 https://eta-publications.lbl.gov/sites/default/files/report-lbnl-63728.pdf",
                              "Mathieu et al. 2011 IEEE TSG doi:10.1109/TSG.2011.2145010 https://eta-publications.lbl.gov/sites/default/files/LBNL-4944E.pdf"]),
  default_vs_physics_fix={"transformer_tap": "物理修正，默认启用，不提供为默认回退（仅 SDCO_DC_IGNORE_TAP=1 用于复现旧错误）",
                          "dr_baseline": "默认方法仍为 similar_days_avg、无日类型过滤（向后兼容）；日类型过滤/adjusted 为可选"},
  code_snapshots_before_fix={"sdco_engine.py.before_fix": sha(D + "/raw/sdco_engine.py.before_fix"), "market_core.py.before_fix": sha(D + "/raw/market_core.py.before_fix")})
json.dump(man, open(RS + "/manifest.json", "w"), indent=1, ensure_ascii=False); print("ok")
