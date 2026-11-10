"""Product regressions. Independent published-workbook/API acceptance is counted separately."""
import copy,io,json,zipfile,csv
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.scenario import Scenario
from app.tools import sdco_engine as E,model_edit as M
from app.paper_annual import AnnualMigrationInput,evaluate
ROOT=Path(__file__).resolve().parents[1]

def z(i=1):return json.loads((ROOT/f"cases/paper_reproduction/inputs/zhang_s{i}.json").read_text())
def peak(cap=100,load=1,firm=2):
 return Scenario.model_validate(dict(network_case="custom",network=dict(buses=[dict(name="one",vn_kv=100)],ext_grids=[dict(bus=0,import_max_mw=firm)]),data_centers=[dict(name="DC",bus=0,cap_it_mw=cap,pue=1,interactive_mw=[load]*24,batch_mwh=0)],storage=[],pv=[],jobs=[],carbon_weight=0))

def test_peak_capacity_is_not_required_load():
 a=M.check_model(peak());b=M.check_model(peak(1));assert a["islands"][0]["peak_load_mw"]==b["islands"][0]["peak_load_mw"]==1
 assert a["islands"][0]["installed_load_upper_bound_mw"]==100
 assert not any("大于可靠" in w for w in a["warnings"])

def test_true_shortage_warning_and_infeasible_preserved():
 sc=peak(100,3,2);assert any("大于可靠" in w for w in M.check_model(sc)["warnings"])
 with pytest.raises(RuntimeError,match="infeasible"):E.solve(sc,True)

@pytest.mark.parametrize("i,expected",enumerate([2920,2980,2997.5,3000,3000,3030,3050],1))
def test_endogenous_welfare(i,expected):
 r=E.solve(Scenario.model_validate(z(i)),True);assert -r["objective"]/24==pytest.approx(expected,abs=1e-7)
 assert sum(r["cost_terms"].values())==pytest.approx(r["objective"],abs=1e-7)
 assert r["network_mapping"]["branches"][0]["b_mw_per_rad"]==pytest.approx(.5)
 assert len(r["job_admission"])==72 and len(r["allocations"])==216

def test_physical_angle_bounds_remain_default():
 s=z();s["network_domain"]="physical";r=E.solve(Scenario.model_validate(s),True)
 assert -r["objective"]/24<2920-1
 assert max(abs(v) for row in r["network_dispatch"] for v in row["theta_rad"])<=3.141592653589794

def test_abstract_ac_explicitly_rejected():
 sc=Scenario.model_validate(z());r=E.solve(sc,True)
 with pytest.raises(ValueError,match="不适用交流"):E.ac_check(sc,r)

def test_welfare_missing_bid_rejected_before_solve():
 s=z();s["jobs"][0].pop("value_cny_mwh");assert any("value_cny_mwh" in x for x in E.validate(Scenario.model_validate(s)))

def test_cost_default_ignores_bid():
 s=peak().model_dump();s["jobs"]=[dict(id="j",dc="DC",energy_mwh=1,max_mw=1,value_cny_mwh=500)];s["data_centers"][0]["interactive_mw"]=[0]*24
 a=E.solve(Scenario.model_validate(s),True);s["jobs"][0]["value_cny_mwh"]=1;b=E.solve(Scenario.model_validate(s),True)
 assert a["objective"]==b["objective"] and a["market_clearing"]["welfare_cny"] is None

def carbon_case():
 s=z();s.update(network_domain="physical",objective_mode="cost",carbon_weight=0,carbon_profiles={"CA":[0]*24,"PJM":[1]*24},bus_region={"0":"CA","1":"PJM"},grid_markup_cny_mwh=0,pv_curtail_penalty=0)
 s["network"]=dict(buses=[dict(name="CA",vn_kv=100),dict(name="PJM",vn_kv=100)],ext_grids=[dict(bus=0,import_max_mw=0,price_cny_kwh=[0]*24),dict(bus=1,import_max_mw=2,price_cny_kwh=[.001]*24)])
 s["data_centers"]=s["data_centers"][:2]
 for i,d in enumerate(s["data_centers"]):d.update(name=["CA","PJM"][i],bus=i,cap_it_mw=2)
 s["pv"]=[dict(bus=0,cap_mw=1,profile=[.5]*24,lifecycle_tco2e_mwh=.01)]
 s["jobs"]=[dict(id=f"h{t}",dc="PJM",release=t,deadline=t+1,energy_mwh=1,max_mw=1) for t in range(24)]
 s["links"]=[dict(a="CA",b="PJM",bw_mw=2)];s["lifecycle_enabled"]=True;s["lifecycle_counterfactual"]="jobs_origin_uniform";s["lifecycle_embodied_t_per_year"]=87.6
 return s

def test_lifecycle_separate_optional_ledger():
 s=carbon_case();r=E.solve(Scenario.model_validate(s),True);l=r["lifecycle_ledger"]
 assert l["operational_generation_t"]==pytest.approx(12);assert l["vre_lifecycle_t"]==pytest.approx(.12)
 assert l["construction_allocated_t"]==pytest.approx(.24);assert l["net_avoided_t"]==pytest.approx(11.64)
 s["lifecycle_enabled"]=False;old=E.solve(Scenario.model_validate(s),True)
 assert "lifecycle_ledger" not in old and old["objective"]==r["objective"] and old["emissions_t"]==r["emissions_t"]

def test_lifecycle_hourly_mixed_factor():
 s=carbon_case();s["pv"][0]["lifecycle_tco2e_mwh_profile"]=[.02]*24
 assert E.solve(Scenario.model_validate(s),True)["lifecycle_ledger"]["vre_lifecycle_t"]==pytest.approx(.24)

def test_lifecycle_counterfactual_rejects_incompatible_model():
 s=carbon_case();s["thermal_mode"]="coupled";assert any("反事实" in x for x in E.validate(Scenario.model_validate(s)))

def test_gross_and_net_fee_audit():
 for basis in ("gross","net"):
  s=z(5);s["migration_fee_basis"]=basis;r=E.solve(Scenario.model_validate(s),True)
  assert sum(a["cost_cny"] for a in r["migration_audit"])==pytest.approx(r["cost_terms"]["migration_service"],abs=1e-6)
  for a in r["migration_audit"]:assert a["gross_mwh"]+1e-8>=a["abs_net_mwh"]

@pytest.fixture
def isolated(tmp_path,monkeypatch):
 from app import settings,main
 monkeypatch.setattr(settings,"DATA_DIR",str(tmp_path));monkeypatch.setattr(main,"ART_ROOT",str(tmp_path/"artifacts"));monkeypatch.setattr(main,"SESS_DIR",str(tmp_path/"sessions"));(tmp_path/"sessions").mkdir();return TestClient(app)

def test_official_api_audit_export(isolated):
 c=isolated;sid="regressionpaperapi";assert c.post(f"/api/sessions/{sid}/model/load",json=z(3)).status_code==200
 assert c.post(f"/api/sessions/{sid}/model/rerun",json={"ac":False}).status_code==200
 r=c.get(f"/api/sessions/{sid}/results").json();assert r["audit"]["optimized"]["market_clearing"]["welfare_cny"]/24==pytest.approx(2997.5)
 with zipfile.ZipFile(io.BytesIO(c.get(f"/api/sessions/{sid}/export.zip").content)) as f:
  assert {"allocations_optimized.csv","job_admission_optimized.csv","migration_audit_optimized.csv","audit_optimized.json","network_dispatch_optimized.csv"}<=set(f.namelist())
  assert len(list(csv.DictReader(io.StringIO(f.read("allocations_optimized.csv").decode()))))==216

def test_frozen_welfare_task_and_historical_export(isolated):
 c=isolated;P="/api/foundation";pr=c.post(P+"/projects",json={"name":"paper regression"}).json()
 d=c.post(P+"/scenarios",json=dict(project_id=pr["id"],name="Zhang",model=z(4),axis=dict(location="abstract",year=2020,timezone="Asia/Shanghai",start="2020-01-01T00:00:00+08:00",step_minutes=60,length=24))).json()
 v=c.post(P+f"/scenarios/{d['id']}/publish",json={"expected_revision":d["revision"]}).json()
 bad=c.post(P+"/tasks",json=dict(version_id=v["id"],objective="welfare"));assert bad.status_code==400
 t=c.post(P+"/tasks",json=dict(version_id=v["id"],objective="welfare",solver={"ac_check":False})).json();before=copy.deepcopy(t["snapshot"])
 r=c.post(P+f"/tasks/{t['id']}/run").json();assert r["status"]=="completed",r;assert r["snapshot"]==before
 opened=c.post(P+f"/tasks/{t['id']}/open").json();sid=opened["session_id"]
 assert c.get(f"/api/sessions/{sid}/results").json()["audit"]["optimized"]["market_clearing"]["welfare_cny"]==pytest.approx(72000)
 package=c.get(f"/api/sessions/{sid}/export.zip");assert package.status_code==200
 with zipfile.ZipFile(io.BytesIO(package.content)) as zz:
  assert json.loads(zz.read("input_snapshot.json"))==before
  assert json.loads(zz.read("frozen_task_metadata.json"))["input_hash"]==t["input_hash"]
 again=c.post(P+f"/tasks/{t['id']}/rerun").json();assert again["input_hash"]==t["input_hash"]
 assert c.get(P+f"/versions/{v['id']}").json()==v

def annual():return json.loads((ROOT/"cases/paper_reproduction/inputs/zheng2019_annual.json").read_text())

def test_annual_public_api_and_audit(isolated):
 b=annual();b["utilizations"]=[.65];b["new_dc_counts"]=[0,5];r=isolated.post("/api/paper-reproduction/annual-migration",json=b);assert r.status_code==200,r.text
 out=r.json();assert out["n_hours"]==8760 and out["n_grid_points"]==2
 with zipfile.ZipFile(io.BytesIO(isolated.get(out["export_url"]).content)) as zf:assert {"input.json","results.json","grid.csv","hourly.csv"}==set(zf.namelist())

@pytest.mark.parametrize("change",["length","negative","nan","utilization"])
def test_annual_rejects_invalid_domain(change):
 b=annual()
 if change=="length":b["curtailment_mwh"].pop()
 if change=="negative":b["curtailment_mwh"][0]=-1
 if change=="nan":b["source_ci_t_mwh"][0]=float("nan")
 if change=="utilization":b["utilizations"]=[1.01]
 with pytest.raises(ValueError):AnnualMigrationInput.model_validate(b)


def test_mandatory_batch_energy_lower_bound_warns():
 sc=peak().model_dump();sc["data_centers"][0].update(interactive_mw=[0]*24,batch_mwh=24);sc["network"]["ext_grids"][0]["import_max_mw"]=.5
 v=M.check_model(Scenario.model_validate(sc));assert v["islands"][0]["forecast_fixed_peak_mw"]==0
 assert v["islands"][0]["required_peak_lower_bound_mw"]==1 and any("大于可靠" in x for x in v["warnings"])

def test_coincident_forecast_not_sum_of_site_maxima():
 sc=peak().model_dump();sc["data_centers"][0]["interactive_mw"]=[1]+[0]*23
 other=copy.deepcopy(sc["data_centers"][0]);other.update(name="other",interactive_mw=[0,1]+[0]*22);sc["data_centers"].append(other)
 assert M.check_model(Scenario.model_validate(sc))["islands"][0]["forecast_fixed_peak_mw"]==1

def test_welfare_resource_cost_excludes_negative_demand_value():
 r=E.solve(Scenario.model_validate(z(4)),True)
 assert r["cost_cny"]==pytest.approx(r["objective"]+r["market_clearing"]["admitted_value_cny"])
 assert r["cost_cny"]>0 and r["objective"]<0


def test_thermal_precheck_is_it_floor_not_assumed_pue_peak():
 sc=peak().model_dump();sc["thermal_mode"]="coupled";sc["data_centers"][0].update(pue=2,thermal={})
 v=M.check_model(Scenario.model_validate(sc))["islands"][0]
 assert v["forecast_fixed_peak_mw"]==1 and not v["thermal_load_exact"] and v["fixed_profile_is_electrical_floor"]


def test_api_export_input_hash_uses_serialized_defaults(isolated):
 import hashlib
 c=isolated;sid="regressiondefaulttypehash"
 raw=dict(network_case="custom",network=dict(buses=[dict(name="one",vn_kv=100)],ext_grids=[dict(bus=0,import_max_mw=2)]),data_centers=[dict(name="DC",bus=0,cap_it_mw=100,pue=1,interactive_mw=[1]*24,batch_mwh=0)],storage=[],pv=[],jobs=[],carbon_weight=0)
 assert "gen_cost" not in raw
 assert c.post(f"/api/sessions/{sid}/model/load",json=raw).status_code==200
 assert c.post(f"/api/sessions/{sid}/model/rerun",json={"ac":False}).status_code==200
 with zipfile.ZipFile(io.BytesIO(c.get(f"/api/sessions/{sid}/export.zip").content)) as zf:
  model=json.loads(zf.read("scenario.json"));ctx=json.loads(zf.read("audit_optimized.json"))["execution_context"]
  value=hashlib.sha256(json.dumps(model,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(",",":")).encode()).hexdigest()
  assert ctx["input_model_hash"]==value and ctx["input_model_hash_basis"]=="canonical_export_json_v1"
