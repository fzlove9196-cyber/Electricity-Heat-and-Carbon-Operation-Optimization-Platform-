"""Product regressions, separate from author/scipy/export-only independent acceptance."""
import copy,json,io,zipfile
from pathlib import Path
import pytest
from app.opt_cfe import CfeModel,solve,check_axis,export_task

def small(**kw):
 b=dict(capital_power_per_mw_year=1,capital_energy_per_mwh_year=1,eta_charge=1,eta_discharge=1,max_power_mw=0,max_energy_mwh=0)
 s=dict(id='A',region='A',load_mw=[1,1],generators=[dict(id='solar',technology='solar',region='A',availability=[1,0],capital_per_mw_year=1)],battery=b,grid_price_per_mwh=[2,2],grid_cfe=[0,0])
 return dict(model_kind='opt_cfe',name='SYNTHETIC analytic control NOT paper precision',horizon_mode='benchmark',sites=[s],**kw)
def test_res100_is_not_hourly_cfe():
 r=solve(small(matching='annual_res_share',max_excess_share=1))
 assert r['objective']==pytest.approx(4);assert r['investments'][0]['annual_generation_share']==pytest.approx(1)
 assert r['investments'][0]['paper_cfe_score']==pytest.approx(.5);assert r['investments'][0]['max_hourly_unmatched_mwh']==pytest.approx(1)
 assert sum(x['excess_excluded_mw'] for x in r['hourly'])==pytest.approx(1)
@pytest.mark.parametrize('policy',['paper_cfe_score','hourly_cfe_floor'])
def test_true_perfect_infeasible_without_night_clean(policy):
 with pytest.raises(RuntimeError,match='infeasible'):solve(small(matching=policy))
def test_partial_paper_score_is_not_hourly_floor():
 r=solve(small(matching='paper_cfe_score',target=.5));assert r['objective']==pytest.approx(3)
 with pytest.raises(RuntimeError,match='infeasible'):solve(small(matching='hourly_cfe_floor',target=.5))
def test_clean_storage_sized_once_and_cyclic():
 x=small();b=x['sites'][0]['battery'];b.pop('max_power_mw');b.pop('max_energy_mwh');r=solve(x);s=r['investments'][0]
 assert r['objective']==pytest.approx(4);assert [s['generators'][0]['capacity_mw'],s['battery_power_mw'],s['battery_energy_mwh']]==pytest.approx([2,1,1]);assert s['max_hourly_unmatched_mwh']<1e-8
 assert s['initial_green_soc_mwh']==pytest.approx(s['final_green_soc_mwh']);assert r['audit']['max_physical_residual']<1e-8
@pytest.mark.parametrize('boundary',['cyclic','empty'])
def test_no_free_initial_green_soc(boundary):
 x=small(storage_boundary=boundary);x['sites'][0]['generators'][0]['availability']=[0,0];x['sites'][0]['battery'].update(max_power_mw=2,max_energy_mwh=2)
 with pytest.raises(RuntimeError,match='infeasible'):solve(x)
def test_grid_charged_storage_keeps_brown_origin():
 x=small(target=0);s=x['sites'][0];s['generators'][0]['availability']=[0,0];s.update(grid_price_per_mwh=[1,10],grid_cfe=[.5,.5]);s['battery'].update(max_power_mw=2,max_energy_mwh=2,capital_power_per_mw_year=.1,capital_energy_per_mwh_year=.1);r=solve(x)
 assert r['objective']==pytest.approx(2.2);assert r['hourly'][0]['green_soc_mwh']==pytest.approx(.5);assert r['hourly'][0]['brown_soc_mwh']==pytest.approx(.5)
 assert r['hourly'][1]['green_discharge_mw']==pytest.approx(.5);assert r['hourly'][1]['brown_discharge_mw']==pytest.approx(.5);assert r['investments'][0]['physical_clean_fraction']==pytest.approx(.5)
def test_grid_full_clean_can_match_without_ppas():
 x=small();x['sites'][0]['grid_cfe']=[1,1];r=solve(x);assert r['objective']==pytest.approx(3);assert r['investments'][0]['paper_cfe_score']==pytest.approx(1)
def test_spatial_work_not_power_flow():
 x=small(flexibility=1,spatial_shifting=True,spatial_fee_per_mwh=1);s=copy.deepcopy(x['sites'][0]);s.update(id='B',region='B');s['generators'][0].update(region='B',availability=[0,1]);x['sites'].append(s);r=solve(x)
 assert r['objective']==pytest.approx(6);assert sum(f['shift_mwh'] for f in r['spatial_flows'])==pytest.approx(2);assert len(r['spatial_flows'])==2
 assert sum(a['actual_load_mw'] for a in r['hourly'])==pytest.approx(4)
def test_daily_temporal_work_conservation():
 r=solve(small(flexibility=1,temporal_shifting=True,temporal_fee_per_mwh=1));assert r['objective']==pytest.approx(4)
 assert r['daily_work'][0]['actual_mwh']==pytest.approx(2);assert r['daily_work'][0]['temporal_conservation_residual_mwh']==pytest.approx(0)
@pytest.mark.parametrize('patch',[dict(dt_hours=.25),dict(horizon_mode='year'),dict(weather_year=2024),dict(timezone='Asia/Shanghai'),dict(start='2013-01-01T00:00:00'),dict(target=1.1),dict(unknown_field=True)])
def test_explicit_contract_rejections(patch):
 x=small();x.update(patch)
 with pytest.raises(ValueError):CfeModel.model_validate(x)
@pytest.mark.parametrize('kind',['length','nan','negative','foreign','existing','grid_factor','negative_price'])
def test_invalid_inputs_not_filled_or_credited(kind):
 x=small();s=x['sites'][0]
 if kind=='length':s['grid_cfe']=[0]
 if kind=='nan':s['load_mw'][0]=float('nan')
 if kind=='negative':s['load_mw'][0]=-1
 if kind=='foreign':s['generators'][0]['region']='B'
 if kind=='existing':s['generators'][0]['additional']=False
 if kind=='grid_factor':s['grid_cfe'][0]=1.01
 if kind=='negative_price':s['grid_price_per_mwh'][0]=-1
 with pytest.raises(ValueError):CfeModel.model_validate(x)
def test_leap_year_needs_all_8784():
 x=small();x.update(horizon_mode='year',weather_year=2024,start='2024-01-01T00:00:00+00:00');s=x['sites'][0]
 for k in ['load_mw','grid_cfe','grid_price_per_mwh']:s[k]=[1.]*8760
 s['generators'][0]['availability']=[1.]*8760
 with pytest.raises(ValueError,match='8784'):CfeModel.model_validate(x)
 for k in ['load_mw','grid_cfe','grid_price_per_mwh']:s[k]+=[1.]*24
 s['generators'][0]['availability']+=[1.]*24
 assert CfeModel.model_validate(x).n_steps==8784
@pytest.mark.parametrize('patch',[dict(length=24),dict(step_minutes=15),dict(timezone='Asia/Shanghai')])
def test_year_axis_is_not_daily_axis(patch):
 x=CfeModel.model_validate(small());a=dict(location='A',year=2013,timezone='UTC',start=x.start,step_minutes=60,length=2);a.update(patch)
 with pytest.raises(ValueError):check_axis(a,x)
def test_daily_engine_rejects_explicit_annual():
 from app.scenario import Scenario
 with pytest.raises(ValueError,match='24h'):Scenario.model_validate(small())
def test_normal_frozen_tasks_export_and_failure(tmp_path,monkeypatch):
 from app import settings
 from app.foundation import service as f,store
 monkeypatch.setattr(settings,'DATA_DIR',str(tmp_path));p=f.project_new(dict(name='SYNTHETIC unit isolated'));x=small();a=dict(location='A',year=2013,timezone='UTC',start=x.get('start','2013-01-01T00:00:00+00:00'),step_minutes=60,length=2)
 d=f.scenario_new(dict(project_id=p['id'],name='CFE',axis=a,model=x));v=f.publish(d['id'],dict(expected_revision=1));t=f.task_new(dict(version_id=v['id'],solver=dict(ac_check=False)));r=f.execute(t['id']);assert r['status']=='failed' and 'infeasible' in r['error'];assert store.get('task',t['id'])['input_hash']==t['input_hash']
 x['sites'][0]['battery'].update(max_power_mw=2,max_energy_mwh=2);f.draft_update(d['id'],dict(expected_revision=1,model=x));v=f.publish(d['id'],dict(expected_revision=2));t=f.task_new(dict(version_id=v['id'],solver=dict(ac_check=False)));r=f.execute(t['id']);assert r['status']=='completed';z=zipfile.ZipFile(io.BytesIO(export_task(r)));assert json.loads(z.read('input_snapshot.json'))==t['snapshot'];assert json.loads(z.read('results.json'))['objective']==pytest.approx(4)
 with pytest.raises(ValueError):f.task_new(dict(version_id=v['id'],solver=dict(ac_check=True)))
 with pytest.raises(ValueError):f.task_new(dict(version_id=v['id'],objective='weighted_carbon',solver=dict(ac_check=False)))
@pytest.mark.parametrize('name',['thermal_1h','thermal_15min'])
def test_terminal_use_is_not_receiving_pipe_arrival(name):
 from app.scenario import Scenario
 from app.tools import sdco_engine
 path=Path(__file__).resolve().parents[1]/'cases/paper_reproduction/phase4/inputs'/f'{name}.json';s=Scenario.model_validate_json(path.read_text());r=sdco_engine.solve(s,True);a=r['heat_boundary_audit'];node=next(n for n in a['nodes'] if n['node']=='load')
 assert a['terminal_served_mwh']==pytest.approx(11.5);assert a['pipe_arrivals_sum_mwh']>11.5
 assert a['pipe_arrivals_sum_mwh']-11.5==pytest.approx(node['store_loss_mwh']+node['store_change_mwh'],abs=1e-8)
 assert abs(a['residual_mwh'])<1e-8;assert s.dt_hours*r['df'].heat_demand_MWth.sum()==pytest.approx(11.5)

def test_paper_credit_vs_physical_clean_storage_losses_are_separate():
 x=small(target=0);s=x['sites'][0];s['generators'][0]['availability']=[0,0];s.update(grid_price_per_mwh=[1,10],grid_cfe=[.5,.5]);s['battery'].update(max_power_mw=2,max_energy_mwh=2,capital_power_per_mw_year=.1,capital_energy_per_mwh_year=.1,eta_charge=.8);r=solve(x);a=r['investments'][0]
 assert r['objective']==pytest.approx(2.475);assert a['physical_clean_fraction']==pytest.approx(.5);assert a['paper_cfe_score']==pytest.approx(.4375)

def test_zero_assigned_site_has_undefined_rates_not_false_failure():
 x=small(flexibility=1,spatial_shifting=True);s=x['sites'][0];s['generators'][0]['availability']=[1,1];s['grid_price_per_mwh']=[0,0];other=copy.deepcopy(s);other.update(id='B',region='B');other['generators'][0].update(region='B',capital_per_mw_year=1000);x['sites'].append(other)
 r=solve(x);b=next(z for z in r['investments'] if z['site']=='B');assert r['objective']==pytest.approx(2.00002)
 assert b['load_mwh']==0 and b['paper_cfe_score'] is None and b['physical_clean_fraction'] is None and b['annual_generation_share'] is None
