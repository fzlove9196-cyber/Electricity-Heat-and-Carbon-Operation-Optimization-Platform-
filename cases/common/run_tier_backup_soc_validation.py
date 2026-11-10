"""三级优化扩展验证：SOC 实测修正 + UPS/柴发应急（中卫/韶关/乌兰察布结构，【假设】备用参数）。"""
from __future__ import annotations
import json, os, sys, traceback, copy
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
from app.scenario import load_preset
from app.tools import Session, call_tool
from app.tools import sdco_engine as eng
from app.opt import tiered as T

OUT = os.path.join(ROOT, "cases", "validation", "out")
os.makedirs(OUT, exist_ok=True)
ART = os.path.join(OUT, "tier_backup_soc")
os.makedirs(ART, exist_ok=True)


def soc_case(preset, label):
    s = Session(f"soc_{preset}", os.path.join(ART, f"soc_{preset}"))
    sc = load_preset(preset)
    s.state["scenario"] = sc
    if not sc.storage:
        return {"preset": preset, "label": label, "ok": False, "error": "no storage for SOC test"}
    name = sc.storage[0].name
    row = {"preset": preset, "label": label, "storage": name}
    try:
        b = call_tool(s, "save_day_ahead_baseline", {})
        row["day_ahead_cost"] = b.get("cost_cny")
        r0 = call_tool(s, "reoptimize_intraday", {"from_t": 10, "text_patch": "光伏降10%", "dev_penalty_cny_mwh": 60})
        # measured low SOC
        s2 = Session(f"socm_{preset}", os.path.join(ART, f"socm_{preset}"))
        s2.state["scenario"] = load_preset(preset)
        call_tool(s2, "save_day_ahead_baseline", {})
        r1 = call_tool(s2, "reoptimize_intraday", {
            "from_t": 10, "text_patch": "光伏降10%", "dev_penalty_cny_mwh": 60,
            "soc_measured": {name: 0.30},
        })
        row["roll_prior"] = {"cost_cny": r0.get("cost_cny"), "soc_source": r0.get("soc_source")}
        row["roll_measured"] = {
            "cost_cny": r1.get("cost_cny"), "soc_source": r1.get("soc_source"),
            "deviation": r1.get("soc_deviation"),
        }
        row["d_cost_cny"] = None if r0.get("cost_cny") is None or r1.get("cost_cny") is None else round(r1["cost_cny"] - r0["cost_cny"], 2)
        row["ok"] = bool(r0.get("ok") and r1.get("ok") and r1.get("soc_source") == "measured")
    except Exception as e:
        row["ok"] = False
        row["error"] = f"{type(e).__name__}: {e}"
        row["trace"] = traceback.format_exc()[-1200:]
    return row


def backup_stress(preset, label, grid_cap_mw):
    """【假设】UPS+柴发；对比正常 vs 外网受限应急。"""
    s = Session(f"bk_{preset}", os.path.join(ART, f"bk_{preset}"))
    sc = load_preset(preset)
    s.state["scenario"] = sc
    row = {"preset": preset, "label": label, "grid_cap_mw": grid_cap_mw, "assumptions": []}
    try:
        cfg = call_tool(s, "configure_backup_resources", {
            "ups": {"source_note": "【假设】验证用 EUPS：0.25h×首站IT、η=0.94、reserve=0.5"},
            "diesel": {
                "dispatch_mode": "emergency_only",
                "source_note": "【假设】验证用柴发：Pmax≈1.3×ΣIT、1800元/MWh、0.7t/MWh、连续爬坡",
            },
            "replace": True,
        })
        row["assumptions"] = (cfg.get("notes") or [])
        row["params"] = cfg.get("params")
        # normal DA (diesel off)
        r_n = eng.solve(s.state["scenario"], True)
        row["normal"] = {
            "ok": True, "cost_cny": float(r_n.get("cost_cny", r_n["objective"])),
            "diesel_mwh": sum(d.get("energy_mwh", 0) for d in (r_n.get("diesel") or [])),
            "ups_dis_mwh": sum(u.get("discharge_mwh", 0) for u in (r_n.get("ups") or [])),
            "emergency": r_n.get("emergency_mode"),
        }
        # emergency + grid cap
        call_tool(s, "set_emergency_mode", {"enabled": True, "grid_import_max_mw": float(grid_cap_mw)})
        try:
            r_e = eng.solve(s.state["scenario"], True)
            row["emergency"] = {
                "ok": True, "cost_cny": float(r_e.get("cost_cny", r_e["objective"])),
                "diesel_mwh": sum(d.get("energy_mwh", 0) for d in (r_e.get("diesel") or [])),
                "diesel_peak_mw": max((d.get("peak_mw", 0) for d in (r_e.get("diesel") or [])), default=0),
                "ups_dis_mwh": sum(u.get("discharge_mwh", 0) for u in (r_e.get("ups") or [])),
                "thermal_safe": (r_e.get("thermal") or {}).get("safe"),
                "emergency": r_e.get("emergency_mode"),
            }
        except Exception as e:
            row["emergency"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        # without backup under same emergency — expect harder / fail or higher cost
        sc_bare = load_preset(preset)
        sc_bare.emergency_mode = True
        if sc_bare.network and sc_bare.network.ext_grids:
            for e in sc_bare.network.ext_grids:
                e.import_max_mw = float(grid_cap_mw)
        try:
            r_b = eng.solve(sc_bare, True)
            row["emergency_no_backup"] = {
                "ok": True, "cost_cny": float(r_b.get("cost_cny", r_b["objective"])),
            }
        except Exception as e:
            row["emergency_no_backup"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        row["ok"] = bool(row.get("normal", {}).get("ok")) and bool(row.get("emergency", {}).get("ok") or row.get("emergency_no_backup", {}).get("ok") is False)
        # envelope under emergency with backup
        s.state["results"] = {"optimized": r_n}
        call_tool(s, "save_day_ahead_baseline", {"solve_first": False})
        env = call_tool(s, "compute_flexibility_envelope", {"stage": "day_ahead", "stride": 6})
        row["envelope_da_mean_bw"] = (env.get("summary") or {}).get("mean_bandwidth_mw")
    except Exception as e:
        row["ok"] = False
        row["error"] = f"{type(e).__name__}: {e}"
        row["trace"] = traceback.format_exc()[-1500:]
    return row


def main():
    rows = []
    print("== SOC measured ==")
    for preset, label in [
        ("zhongwei_heatwave_stress", "中卫热浪"),
        ("ulanqab_21vianet_summer", "乌兰察布夏季"),
    ]:
        print(" ", label)
        rows.append({"kind": "soc", **soc_case(preset, label)})
        print(json.dumps(rows[-1], ensure_ascii=False)[:500])

    print("== UPS/diesel stress ==")
    # grid caps 【假设】收紧：相对站点规模的严峻供电受限
    for preset, label, cap in [
        ("zhongwei_heatwave_stress", "中卫断电压力", 80.0),   # 多 DC 大站
        ("shaoguan_summer", "韶关供电受限", 30.0),
        ("ulanqab_21vianet_summer", "乌兰察布供电受限", 40.0),
    ]:
        print(" ", label, "cap", cap)
        rows.append({"kind": "backup", **backup_stress(preset, label, cap)})
        print(json.dumps({k: rows[-1].get(k) for k in ("ok", "normal", "emergency", "emergency_no_backup", "d_cost_cny") if k in rows[-1] or True}, ensure_ascii=False, default=str)[:700])

    path = os.path.join(OUT, "tier_backup_soc_validation.json")
    ok = all(r.get("ok") for r in rows)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"ok": ok, "rows": rows}, f, ensure_ascii=False, indent=2)
    print("WROTE", path, "ok", ok)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
