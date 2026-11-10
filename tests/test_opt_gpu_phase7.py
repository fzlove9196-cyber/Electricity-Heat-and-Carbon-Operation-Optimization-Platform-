"""Product regressions, not paper accuracy or independent-reference count."""
import json,copy,io,zipfile
from pathlib import Path
import pytest
from app.opt_gpu import GpuModel,solve,GPUValidationFailure,export_task,check_axis
P=Path(__file__).resolve().parents[1]/'cases/paper_reproduction/phase7'
def case(n='synthetic_energy'):return json.loads((P/(n+'.json')).read_text())
def quarter(m):
 m=copy.deepcopy(m);m['dt_hours']=.25;m['n_steps']*=4
 for k in ['price_usd_kwh','power_limit_kw']:m[k]=[x for x in m[k] for _ in range(4)]
 for j in m['jobs']:j['baseline_rate']=[x for x in j['baseline_rate'] for _ in range(4)]
 return m
@pytest.mark.parametrize('patch',[dict(dt_hours=.5),dict(n_steps=97),dict(pue=1.2),dict(thermal={}),dict(policy='paper_fair_unknown'),dict(start='2025-05-03T00:00:00'),dict(price_usd_kwh=[1])])
def test_conflicting_or_unsupported_modes_rejected(patch):
 x=case();x.update(patch)
 with pytest.raises(ValueError):GpuModel.model_validate(x)
def test_same_work_is_explicit_not_hidden_drop():
 x=case();x['jobs'][0]['required_work_h']=1
 with pytest.raises(ValueError,match='same required work'):GpuModel.model_validate(x)
def test_pause_needs_explicit_power_and_gpu_gang_disjoint():
 x=case();x['jobs'][0].pop('pause_power_w_per_gpu')
 with pytest.raises(ValueError,match='pause power'):GpuModel.model_validate(x)
 x=case();x['jobs'].append(copy.deepcopy(x['jobs'][0]));x['jobs'][1]['id']='overlap'
 with pytest.raises(ValueError,match='disjoint'):GpuModel.model_validate(x)
def test_short_window_not_passed_off_as_author_window():
 x=case();x['sla_window_semantics']='paper_3_to_6_hours'
 with pytest.raises(ValueError,match='3–6h'):GpuModel.model_validate(x)
def test_no_hidden_resizing_of_calibrated_gang():
 x=case();x['jobs'][0]['gpu_ids'].append('nonexistent')
 with pytest.raises(ValueError):GpuModel.model_validate(x)
def test_discrete_caps_energy_and_useful_capacity_audit():
 r=solve(case());assert r['energy_kwh']==pytest.approx(1.2);assert r['completed_work_h']==pytest.approx(2);assert len(r['gpu_slots'])==6;assert sum(x['wasted_capacity_work_h'] for x in r['job_slots'])==pytest.approx(.25);assert all(x['action']=='cap200' for x in r['job_slots'])
def test_required_pause_and_recovery_not_lost_work():
 r=solve(case('synthetic_pause'));assert r['energy_kwh']==pytest.approx(1.7);assert r['job_slots'][1]['state']=='paused';assert [x['useful_work_h'] for x in r['job_slots']]==pytest.approx([1,0,1]);assert r['jobs'][0]['unfinished_work_h']==0
def test_fair_minimax_semantics_and_locked_priority():
 r=solve(case('synthetic_fair'));assert r['solver_phases'][0]['incumbent']==pytest.approx(2/3);assert r['fairness_rho']<=2/3+1.1e-7;assert r['energy_kwh']==pytest.approx(2.4);assert all(x['relative_gap']==0 for x in r['solver_phases'])
def test_15min_same_work_integrals_but_control_granularity_differs():
 r=solve(quarter(case()));assert r['energy_kwh']==pytest.approx(1.125);assert r['completed_work_h']==pytest.approx(2);assert len(r['gpu_slots'])==24;assert max(x['duration_h'] for x in r['gpu_slots'])==.25
 assert sum(x['energy_kwh'] for x in r['gpu_slots'])==pytest.approx(r['energy_kwh'])
def test_flex0_unmodified_per_slot_not_average_compensation():
 x=case();x['jobs'][0]['flex']=0;r=solve(x);assert [x['action'] for x in r['job_slots'][:2]]==['cap400','cap400'];assert [x['useful_work_h'] for x in r['job_slots'][:2]]==pytest.approx([1,1]);assert r['energy_kwh']==pytest.approx(1.7)
@pytest.mark.parametrize('flex,floor',[(1,.9),(2,.75),(3,.5)])
def test_flex_tier_floors_are_author_thresholds(flex,floor):
 x=case();x['jobs'][0]['flex']=flex;r=solve(x);assert r['sla_windows'][0]['minimum_performance']==floor;assert r['sla_windows'][0]['planning_performance']>=floor-1e-6
def test_deadline_real_infeasible_not_zero_cost_success():
 x=case('synthetic_pause');x['jobs'][0]['deadline_h']=2
 with pytest.raises(RuntimeError,match='not optimal'):solve(x)
def test_heldout_fields_never_enter_decision_and_failure_is_real():
 x=case();x['require_validation_feasible']=False;baseline=solve(x)
 for a in x['jobs'][0]['actions']:a['validation_normalized_rate']=a['normalized_rate']*.5
 r=solve(x);assert [v['action'] for v in r['job_slots']]==[v['action'] for v in baseline['job_slots']];assert r['objective_value']==baseline['objective_value'];assert not r['validation_accepted'];assert r['validation_unfinished_work_h']==pytest.approx(1)
 x['require_validation_feasible']=True
 with pytest.raises(GPUValidationFailure) as e:solve(x)
 assert e.value.partial_result['validation_unfinished_work_h']==pytest.approx(1)
def test_non_gpu_and_unallocated_idle_not_omitted():
 x=case();x['gpus'].append(dict(id='idle',idle_power_w=100,source={'kind':'SYNTHETIC'}));x['non_gpu_fixed_kw']=1;r=solve(x);assert r['energy_kwh']==pytest.approx(4.5);assert len(r['gpu_slots'])==9;assert len([v for v in r['gpu_slots'] if v['state']=='unallocated_idle'])==3
def test_axis_rejects_silent_1h():
 x=quarter(case());s=GpuModel.model_validate(x);a=dict(start=s.start,step_minutes=60,length=12)
 with pytest.raises(ValueError):check_axis(a,s)
def test_normal_freeze_export_history_and_failed_partial(tmp_path,monkeypatch):
 from app import settings
 from app.foundation import service as f,store
 monkeypatch.setattr(settings,'DATA_DIR',str(tmp_path));x=case();p=f.project_new(dict(name='isolated GPU unit'));a=dict(location='synthetic',year=2025,timezone='Asia/Shanghai',start=GpuModel.model_validate(x).start,step_minutes=60,length=3);d=f.scenario_new(dict(project_id=p['id'],name='GPU',model=x,axis=a));v=f.publish(d['id'],dict(expected_revision=1));t=f.task_new(dict(version_id=v['id'],solver=dict(ac_check=False)));r=f.execute(t['id']);assert r['status']=='completed' and r['result']['model_kind']=='opt_gpu';z=zipfile.ZipFile(io.BytesIO(export_task(r)));assert len(z.read('gpu_slots.csv').splitlines())==7;assert json.loads(z.read('input_snapshot.json'))==t['snapshot'];old=copy.deepcopy(store.get('task',t['id']))
 for aa in x['jobs'][0]['actions']:aa['validation_normalized_rate']=aa['normalized_rate']*.5
 f.draft_update(d['id'],dict(expected_revision=1,model=x));v2=f.publish(d['id'],dict(expected_revision=2));t2=f.task_new(dict(version_id=v2['id'],solver=dict(ac_check=False)));r2=f.execute(t2['id']);assert r2['status']=='failed' and r2['partial_result'];z=zipfile.ZipFile(io.BytesIO(export_task(r2)));assert 'partial_NOT_ACCEPTED.json' in z.namelist() and 'results.json' not in z.namelist();assert store.get('task',t['id'])==old
 with pytest.raises(ValueError):f.task_new(dict(version_id=v['id'],solver=dict(ac_check=True)))

def test_author_public_headroom_fairness_is_not_throughput_minimax():
 x=case('synthetic_fair');x['policy']='author_dvfs_headroom_discrete'
 for j in x['jobs']:j['actions'][0]['normalized_rate']=.75
 r=solve(x);assert r['headroom_definition'];assert len(r['solver_phases'])==3;assert r['solver_phases'][0]['phase']=='minimax_power_headroom_fraction_from_author_pseudocode';assert r['solver_phases'][0]['incumbent']==pytest.approx(1);assert r['completed_work_h']==pytest.approx(6)
def test_heterogeneous_idle_is_individual_not_gang_average():
 x=case();x['jobs'][0]['flex']=0;x['gpus'][0]['idle_power_w']=20;x['gpus'][1]['idle_power_w']=80;r=solve(x);last=[z for z in r['gpu_slots'] if z['step']==2];assert {z['gpu']:z['power_w'] for z in last}=={'G0':20,'G1':80};assert sum(z['energy_kwh'] for z in r['gpu_slots'])==pytest.approx(r['energy_kwh'])

def test_author_discrete_minimum_eligible_cap_can_really_be_infeasible():
 x=case("synthetic_fair");x["policy"]="author_dvfs_headroom_discrete"
 with pytest.raises(RuntimeError,match="infeasible"):solve(x)
