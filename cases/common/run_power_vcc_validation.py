"""真实案例上验证 ① idle+动态 与 ② VCC（诚实报告 sourced vs 假设参数）。"""
from __future__ import annotations
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from app.scenario import load_preset, list_presets
from app.tools import sdco_engine as eng

CASES = [
    "zhongwei_summer_highwind",
    "zhongwei_summer_coupled",
    "ulanqab_cicdata_summer",
    "shaoguan_summer",
]
OUT = os.path.join(os.path.dirname(__file__), "..", "validation", "out", "power_vcc_results.json")

def run():
    rows = []
    for name in CASES:
        if name not in list_presets():
            rows.append(dict(case=name, error="preset missing")); continue
        sc0 = load_preset(name)
        r0 = eng.solve(sc0, True)
        # VCC day-ahead carbon
        sc1 = load_preset(name); sc1.vcc_mode = "carbon"; sc1.vcc_stage = "day_ahead"
        sc1.sources = {**(sc1.sources or {}), "VCC": "【启用】carbon/day_ahead；碳信号=场景 carbon_profiles/factor"}
        r1 = eng.solve(sc1, True)
        # idle_dynamic assumed Fan
        sc2 = load_preset(name)
        for d in sc2.data_centers:
            d.power_model = "idle_dynamic"; d.p_peak_mw = d.cap_it_mw; d.p_idle_mw = round(0.4 * d.cap_it_mw, 3)
        sc2.sources = {**(sc2.sources or {}), "功率模型": "【假设】idle=0.4×Cap, peak=Cap（Fan 量级，未用本站 PDU 实测）"}
        try:
            r2 = eng.solve(sc2, True); e2 = None
        except Exception as ex:
            r2 = None; e2 = f"{type(ex).__name__}: {ex}"
        rows.append(dict(
            case=name,
            baseline=dict(cost=r0["cost_cny"], emis=r0["emissions_t"], obj=r0["objective"], status=r0["solver"]["status"]),
            vcc_carbon_day_ahead=dict(cost=r1["cost_cny"], emis=r1["emissions_t"], obj=r1["objective"],
                                      d_emis_pct=100*(r1["emissions_t"]-r0["emissions_t"])/max(r0["emissions_t"],1e-9),
                                      d_cost_pct=100*(r1["cost_cny"]-r0["cost_cny"])/max(abs(r0["cost_cny"]),1e-9),
                                      vcc=r1.get("vcc")),
            idle_dynamic_assumed=None if r2 is None else dict(
                cost=r2["cost_cny"], emis=r2["emissions_t"], obj=r2["objective"],
                d_emis_pct=100*(r2["emissions_t"]-r0["emissions_t"])/max(r0["emissions_t"],1e-9),
                d_cost_pct=100*(r2["cost_cny"]-r0["cost_cny"])/max(abs(r0["cost_cny"]),1e-9),
                power_model=r2.get("power_model"), error=e2),
            idle_dynamic_error=e2,
            notes="VCC 不保证降碳；idle 参数为假设标定",
        ))
        print(name, "base emis", round(r0["emissions_t"],2),
              "VCC", round(r1["emissions_t"],2),
              "idle", None if r2 is None else round(r2["emissions_t"],2), e2 or "")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(rows, open(OUT, "w"), indent=2, ensure_ascii=False, default=str)
    print("wrote", OUT)
    return rows

if __name__ == "__main__":
    run()
