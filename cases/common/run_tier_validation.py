"""三级优化验证：中卫热浪+DR / 韶关液冷 / 乌兰察布，含预测误差情景。"""
from __future__ import annotations
import json, os, sys, traceback
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
from app.scenario import load_preset
from app.tools import Session, call_tool
from app.tools import cfg_tools  # noqa
from app.tools import call_tool as _ct

OUT = os.path.join(ROOT, "cases", "validation", "out")
os.makedirs(OUT, exist_ok=True)
ART = os.path.join(OUT, "tier_artifacts")
os.makedirs(ART, exist_ok=True)

CASES = [
    ("zhongwei_heatwave_stress", None, "中卫热浪+DR"),
    ("shaoguan_summer", "liquid_cold_plate", "韶关液冷"),
    ("ulanqab_21vianet_summer", None, "乌兰察布夏季"),
]

def run_one(preset, cool, label):
    s = Session(f"tier_{preset}", os.path.join(ART, preset))
    sc = load_preset(preset)
    s.state["scenario"] = sc
    if cool:
        try:
            call_tool(s, "set_cooling_mode", {"mode": cool})
        except Exception as e:
            return {"preset": preset, "label": label, "ok": False, "error": f"set_cooling:{e}"}
    row = {"preset": preset, "label": label, "cooling": cool}
    try:
        b = call_tool(s, "save_day_ahead_baseline", {})
        row["day_ahead"] = {k: b.get(k) for k in ("ok", "cost_cny", "emissions_tco2", "thermal_safe", "site_peak_mw")}
        r = call_tool(s, "reoptimize_intraday", {
            "from_t": 10, "dev_penalty_cny_mwh": 60,
            "text_patch": "下午3点光伏少20%",
        })
        row["intra_day"] = {k: r.get(k) for k in ("ok", "cost_cny", "emissions_tco2", "thermal_safe", "from_t")}
        row["delta_vs_da"] = (r.get("compare") or {}).get("deltas_vs_day_ahead")
        e1 = call_tool(s, "compute_flexibility_envelope", {"stage": "day_ahead", "stride": 4})
        e2 = call_tool(s, "compute_flexibility_envelope", {"stage": "intra_day", "from_t": 10, "stride": 4})
        row["envelope_da"] = e1.get("summary")
        row["envelope_id"] = e2.get("summary")
        if e1.get("summary") and e2.get("summary"):
            da_bw = e1["summary"].get("mean_bandwidth_mw") or 0
            id_bw = e2["summary"].get("mean_bandwidth_mw") or 0
            row["envelope_shrink_frac"] = None if da_bw <= 1e-9 else round(1 - id_bw / da_bw, 4)
        rt = call_tool(s, "run_realtime_track", {"mode": "mpc_lite", "dt_min": 10, "hours": [12, 13, 14]})
        row["realtime"] = {k: rt.get(k) for k in ("ok", "rmse_mw", "max_tin_c", "thermal_violation", "n_steps")}
        coup = call_tool(s, "report_load_cooling_coupling", {"case": "intra_day"})
        row["coupling_corr_it_cool"] = coup.get("corr_it_cool")
        tl = call_tool(s, "get_tier_timeline", {})
        row["timeline_n"] = len(tl.get("timeline") or [])
        row["ok"] = True
    except Exception as e:
        row["ok"] = False
        row["error"] = f"{type(e).__name__}: {e}"
        row["trace"] = traceback.format_exc()[-1500:]
    return row

def main():
    rows = []
    for preset, cool, label in CASES:
        print("==", label, preset)
        rows.append(run_one(preset, cool, label))
        print(json.dumps(rows[-1], ensure_ascii=False, indent=2)[:800])
    path = os.path.join(OUT, "tier_validation.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"ok": all(r.get("ok") for r in rows), "rows": rows}, f, ensure_ascii=False, indent=2)
    print("WROTE", path, "ok", all(r.get("ok") for r in rows))
    return 0 if all(r.get("ok") for r in rows) else 1

if __name__ == "__main__":
    raise SystemExit(main())
