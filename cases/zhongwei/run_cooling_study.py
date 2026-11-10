"""中卫：散热方式 × 季节 × 余热末端/距离 × 储能 研究（配置构建器 + 耦合 LP）。输出 results/cooling_study/。"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from app.tools import config_builder as B, sweep as SW
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "cooling_study"); os.makedirs(OUT, exist_ok=True)
MODES = ["air_chw", "air_iec", "liquid_cold_plate", "liquid_immersion"]
BASE = dict(name="中卫集群(构建器近似)", climate="zhongwei", season="winter",
    dcs=[dict(name="ZW_EXIST", cap_it_mw=87.5, utilization=0.68, flex_share=0.3, hp_mw=20), dict(name="ZW_NEW_A", cap_it_mw=80, utilization=0.68, flex_share=0.3, hp_mw=30),
         dict(name="ZW_NEW_B", cap_it_mw=80, utilization=0.68, flex_share=0.3, hp_mw=30)],
    battery=dict(power_mw=75, energy_mwh=150), heat_storage=dict(mwh=150, mw=35),
    sources=dict(wind_mw=1500, pv_mw=500, grid_import_mw=1000, grid_export_mw=1200),
    heat=dict(terminal_type="radiator", pipe_length_km=5, design_load_mw=95, price_cny_gj=33, ref_heat_price_cny_gj=45, booster="gas_boiler"))
R = {}
def save(k, res):
    R[k] = res; json.dump(res, open(os.path.join(OUT, f"{k}.json"), "w"), ensure_ascii=False, indent=1, default=str)
    open(os.path.join(OUT, f"{k}.md"), "w").write(SW.to_markdown(res)); print(k, "done", len(res["rows"]))
t = time.time()
save("winter_modes", SW.sweep(BASE, [{"path": "dcs.*.cooling_mode", "values": MODES}]))
save("summer_modes", SW.sweep({**BASE, "season": "summer"}, [{"path": "dcs.*.cooling_mode", "values": MODES}]))
save("heatwave_modes", SW.sweep({**BASE, "season": "heatwave"}, [{"path": "dcs.*.cooling_mode", "values": MODES}]))
rows = []
for m in MODES:
    r = SW.sweep(B.set_path(BASE, "dcs.*.cooling_mode", m), [{"path": "heat.terminal_type", "values": ["floor", "fcu", "radiator", "primary"]}, {"path": "heat.pipe_length_km", "values": [1, 5, 10]}])
    for x in r["rows"]: x["mode"] = m; x["label"] = m + " · " + x["label"]
    rows += r["rows"]
save("heat_grid", dict(ok=True, kind="heat_grid", rows=rows))
ht = B.set_path(B.set_path(BASE, "dcs.*.hp_type", "high_temp"), "heat.terminal_type", "primary")
save("primary_hightemp_hp", SW.sweep(ht, [{"path": "dcs.*.cooling_mode", "values": ["air_chw", "liquid_cold_plate", "liquid_immersion"]}]))
save("booster_none_radiator_20km", SW.sweep(B.set_path(B.set_path(BASE, "heat.booster", "none"), "heat.pipe_length_km", 20), [{"path": "dcs.*.cooling_mode", "values": MODES}]))
save("battery_sweep_winter", SW.sweep(BASE, [{"path": "battery.energy_mwh", "values": [0, 150, 300, 600]}, {"path": "battery.power_mw", "values": [75, 150]}]))
save("tes_sweep_summer", SW.sweep(B.set_path({**BASE, "season": "heatwave"}, "dcs.*.cooling_mode", "air_chw"), [{"path": "dcs.*.tes_mwh", "values": [0, 40, 80, 160]}, {"path": "dcs.*.tes_mw", "values": [20]}]))
save("heatstore_sweep", SW.sweep(BASE, [{"path": "heat_storage.mwh", "values": [0, 150, 300, 600]}]))
print("total", round(time.time() - t, 1), "s")
