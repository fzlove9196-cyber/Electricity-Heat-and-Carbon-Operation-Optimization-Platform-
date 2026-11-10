"""多公开项目案例（和林格尔/庆阳/海南州/张北）+ 引擎新特性（PPA/需量电费/水电/绿电下限/离网孤岛）测试。"""
import pytest
from app.scenario import load_preset, list_presets, preset_from_text
from app.tools import sdco_engine as eng
from app.tools.sim_tools import _kpis

NEW = ["helinger_typical_day", "qingyang_typical", "qinghai_hainan_grid_summer", "qinghai_hainan_offgrid_summer", "zhangbei_summer"]

def test_presets_listed_and_routed():
    for n in NEW: assert n in list_presets()
    assert preset_from_text("和林格尔小风日优化") == "helinger_lowwind"
    assert preset_from_text("青海海南州离网微网冬季") == "qinghai_hainan_offgrid_winter"
    assert preset_from_text("张北阿里数据中心冬季") == "zhangbei_winter"
    assert preset_from_text("庆阳绿电聚合") == "qingyang_typical"

@pytest.mark.parametrize("name", NEW)
def test_case_dispatch_and_ac(name):
    sc = load_preset(name); assert not eng.validate(sc)
    b = eng.solve(sc, optimize=False); o = eng.solve(sc, optimize=True)
    assert o["cost_cny"] <= b["cost_cny"] + 1e-6
    ac = eng.ac_check(sc, o); assert ac["converged"]

def test_ppa_take_or_pay_and_demand_charge():
    sc = load_preset("helinger_typical_noBJ"); r = eng.solve(sc, optimize=True)
    avail = sum(p.cap_mw*sum(p.profile)*p.ppa_price_cny_kwh*1000 for p in sc.pv)
    assert r["ppa_cost_cny"] == pytest.approx(avail, rel=1e-6)          # 照付不议：按可发电量结算
    peak = r["df"].gen0_MW.max(); assert r["demand_charge_cny"] == pytest.approx(peak*sc.network.ext_grids[0].demand_charge_cny_mw_day, rel=1e-4)
    sc.pv[0].ppa_take_or_pay = False; r2 = eng.solve(sc, optimize=True)
    assert r2["ppa_cost_cny"] <= avail + 1e-6

def test_hydro_energy_budget_and_clean100():
    sc = load_preset("qinghai_hainan_clean100_winter"); r = eng.solve(sc, optimize=True)
    g = next(i for i, x in enumerate(r["gens"]) if x.get("kind") == "hydro")
    assert r["df"][f"gen{g}_MW"].sum() <= sc.network.gens[0].energy_mwh_day + 1e-4
    assert r["df"].grid_import_MW.sum() <= 1e-6                          # 100% 清洁：不购电
    assert (r["df"].grid_import_MW * r["df"].grid_export_MW).max() < 1e-6  # 无同时购售

def test_min_green_share_infeasible_reported():
    sc = load_preset("helinger_typical_green85")
    with pytest.raises(RuntimeError, match="min_green_share"):
        eng.solve(sc, optimize=True)
    k = _kpis(load_preset("helinger_highwind_noBJ_green60"), eng.solve(load_preset("helinger_highwind_noBJ_green60"), optimize=True))
    assert k["grid_import_mwh"] <= 0.4*k["dc_energy_mwh"] + 1e-3

def test_offgrid_island_baseline_keeps_storage_and_ac_slack():
    sc = load_preset("qinghai_hainan_offgrid_summer"); assert not sc.network.ext_grids
    b = eng.solve(sc, optimize=False); assert "ESS_MG" in b["storage"]
    ac = eng.ac_check(sc, eng.solve(sc, optimize=True)); assert ac["converged"]

def test_three_region_migration():
    sc = load_preset("zhangbei_summer"); r = eng.solve(sc, optimize=True)
    assert len(sc.network.ext_grids) == 3 and r["df"][[c for c in r["df"] if c.endswith("_mig_out")]].sum().sum() > 1
