"""Product regressions. Independent HTTP/reference gates are counted separately."""
import json,copy
from pathlib import Path
import numpy as np
import pytest
from app.scenario import Scenario
from app.time_axis import resample_hourly
from app.tools import sdco_engine as E
from app.tools.sim_tools import _kpis
P=Path(__file__).resolve().parents[1]/'cases/paper_reproduction/phase4/inputs'
def load(n):return Scenario.model_validate_json((P/(n+'.json')).read_text())
@pytest.mark.parametrize('name',['energy_1h','energy_15min'])
def test_electrical_integrals_and_soc(name):
 s=load(name);r=E.solve(s,True);d=r['df'];dt=s.dt_hours;k=_kpis(s,r)
 assert dt*d.DC_batch_IT.sum()==pytest.approx(8)
 assert k['dc_energy_mwh']==pytest.approx(32)
 assert k['renewable_used_mwh']==pytest.approx(24)
 previous=2.
 for _,row in d.iterrows():
  assert row.BAT_soc==pytest.approx(previous+dt*(.9*row.BAT_ch-row.BAT_dis/.8),abs=1e-8);previous=row.BAT_soc
 assert r['lifecycle_ledger']['construction_allocated_t']==pytest.approx(.24)
 assert sum(r['cost_terms'].values())==pytest.approx(r['objective'])
@pytest.mark.parametrize('name',['thermal_1h','thermal_15min'])
def test_thermal_conservation(name):
 s=load(name);r=E.solve(s,True);d=r['df'];dt=s.dt_hours;th=s.data_centers[0].thermal;pa=pm=24.;ps=1.
 for _,row in d.iterrows():
  q=row.DC_chiller_MWth-row.DC_tes_ch_MWth+row.DC_free_MWth+row.DC_tes_dis_MWth+row.DC_hp_heat_MWth*(1-1/row.DC_HPCOP)
  assert th.c_air_mwh_k*(row.DC_Tin_C-pa)==pytest.approx(dt*(row.DC_IT_MW*1.025-q-4*(row.DC_Tin_C-row.DC_Tmass_C)+.15*(25-row.DC_Tin_C)),abs=1e-8)
  assert 6*(row.DC_Tmass_C-pm)==pytest.approx(dt*4*(row.DC_Tin_C-row.DC_Tmass_C),abs=1e-8)
  assert row.DC_tes_soc_MWh==pytest.approx(.98**dt*ps+dt*(row.DC_tes_ch_MWth-row.DC_tes_dis_MWth),abs=1e-8)
  assert abs(row.DC_Tin_C-pa)<=5*dt+1e-7
  pa,pm,ps=row.DC_Tin_C,row.DC_Tmass_C,row.DC_tes_soc_MWh
 assert r['thermal']['heat']['delivered_mwh']==pytest.approx(round(dt*d.heat_delivered_MWth.sum(),2))
 assert r['thermal']['heat']['revenue_cny']==pytest.approx(round(dt*d.heat_delivered_MWth.sum()*1000,1))
 assert r['thermal']['safe'];assert r['thermal']['dcs']['DC']['thermal_balance_max_residual']<1e-7
 assert sum(r['cost_terms'].values())==pytest.approx(r['objective'])
@pytest.mark.parametrize('name',['integer_continuity_1h','integer_continuity_15min'])
def test_binary_uninterrupted_not_fractional(name):
 s=load(name);r=E.solve(s,True);on=np.flatnonzero(r['df'].DC_batch_IT.to_numpy()>.5)
 assert len(on)*s.dt_hours==2 and np.all(np.diff(on)==1)
 assert r['objective']==pytest.approx(101)
 assert r['integer_tasks']['ledger'][0]['conservation_residual_mwh']==0
 assert 'MILP' in r['solver']['problem']
def test_divisible_legacy_remains_two():assert E.solve(load('divisible_control_1h'),True)['objective']==pytest.approx(2)
@pytest.mark.parametrize('name',['integer_restart_1h','integer_restart_15min'])
def test_cancel_returns_backlog_and_discards_progress(name):
 r=E.solve(load(name),True);a=r['integer_tasks']['ledger'][0]
 assert r['objective']==pytest.approx(12);assert a['cancellations']==1
 assert [a[k] for k in ['initial_progress_mwh','executed_mwh','completed_goodput_mwh','canceled_lost_mwh']]==[1,3,3,1]
 assert a['conservation_residual_mwh']==0 and a['unserved_mwh']==0
 assert sum(r['cost_terms'].values())==pytest.approx(12)
def test_required_deadline_negative_preserved():
 with pytest.raises(RuntimeError,match='infeasible'):E.solve(load('integer_deadline_infeasible_1h'),True)
@pytest.mark.parametrize('patch',[dict(duration_h=None),dict(energy_mwh=3),dict(duration_h=1.1),dict(initial_progress_h=4),dict(restart_delay_h=-1),dict(initial_dc='missing')])
def test_integer_invalid_rejected(patch):
 s=load('integer_continuity_15min');s.jobs[0]=s.jobs[0].model_copy(update=patch)
 assert E.validate(s)
@pytest.mark.parametrize('field',['interactive_mw','price_cny_kwh','outdoor_temp_c','carbon_profiles'])
def test_dt_wrong_profile_is_not_silently_hourly(field):
 s=load('energy_15min')
 if field=='interactive_mw':s.data_centers[0].interactive_mw=[1]*24
 elif field=='carbon_profiles':s.carbon_profiles={'national':[.4]*24}
 else:setattr(s,field,[1]*24)
 assert E.validate(s)
@pytest.mark.parametrize('target',['vcc','tier','annual'])
def test_unsupported_paths_block(target):
 s=load('energy_15min')
 if target=='vcc':s.vcc_mode='carbon';assert E.validate(s)
 elif target=='tier':
  from app.opt.tiered import run_day_ahead
  with pytest.raises(ValueError,match='尚不支持'):run_day_ahead(s)
 else:
  from app.opt.engine import run
  with pytest.raises(ValueError,match='只支持1h'):run({'dt_hours':.25})
def test_explicit_converter_no_input_mutation():
 x=load('energy_1h').model_dump();before=copy.deepcopy(x);y=resample_hourly(x)
 assert x==before and len(y['price_cny_kwh'])==96 and y['data_centers'][0]['batch_mwh']==8
@pytest.mark.parametrize('number',[4,5,6,7])
def test_lexicographic_gross_keeps_primary(number):
 p=P.parents[1]/'inputs'/f'zhang_s{number}.json';s=Scenario.model_validate_json(p.read_text());a=E.solve(s,True);s.migration_cleanup='lexicographic_gross';b=E.solve(s,True);c=b['migration_cleanup']
 assert c['status']=='optimal';assert abs(b['objective']-a['objective'])<1e-6
 assert c['gross_after_mwh']<=c['gross_before_mwh']+1e-6
 if number==5:assert c['gross_after_mwh']<c['gross_before_mwh']-100

def test_secondary_failure_transparent_and_preserves_primary():
 import pyomo.environ as p
 from app.tools.migration_cleanup import apply
 m=p.ConcreteModel();m.x=p.Var(initialize=2);m.obj=p.Objective(expr=m.x)
 class Fail:
  def solve(self,*args,**kwargs):raise RuntimeError('intentional secondary failure')
 r=apply(m,load('energy_1h'),Fail(),m.x)
 assert r['status']=='failed_retained_primary' and m.x.value==2 and m.obj.active and 'intentional' in r['error']
@pytest.mark.parametrize('dt',[1,.25])
def test_generator_ramp_physical_hours(dt):
 s=load('energy_1h');s.pv=[];s.storage=[];s.jobs=[];s.data_centers[0].interactive_mw=[0]*24;s.data_centers[0].batch_mwh=24
 from app.scenario import NetGen
 s.network.gens=[NetGen(name='ramp',bus=0,pmax_mw=4,cost_cny_mwh=0,emission_t_mwh=0,ramp_mw_h=.2)];s.network.ext_grids[0].import_max_mw=0
 if dt==.25:s=Scenario.model_validate(resample_hourly(s.model_dump()))
 r=E.solve(s,True);assert np.max(np.abs(np.diff(r['df'].gen1_MW)))<=.2*dt+1e-6


def test_initial_progress_can_finish_with_short_remaining_window():
 s=load('integer_continuity_1h');j=s.jobs[0];j.duration_h=3;j.energy_mwh=3;j.initial_progress_h=2;j.deadline=1
 r=E.solve(s,True);a=r['integer_tasks']['ledger'][0]
 assert a['executed_mwh']==1 and a['completed_goodput_mwh']==3 and a['conservation_residual_mwh']==0

def test_normal_sankey_quarter_hour_not_four_times_energy():
 from app.tools.viz_tools import energy_balance
 s=load('energy_15min');r=E.solve(s,True);flows,meta=energy_balance(s,r)
 assert sum(v for (a,b),v in flows.items() if b=='DC DC')==pytest.approx(32)

def test_quarter_hour_ac_peak_and_explicit_physical_time():
 s=load('energy_15min');r=E.solve(s,True)
 a=E.ac_check(s,r,3.25)
 assert a['hour']==3.25 and a['step']==13 and a['converged']

def test_source_pinned_blobs_are_original():
 import hashlib
 root=P.parent/'sources';manifest=json.loads((root/'source_manifest.json').read_text())
 for row in manifest['files']:
  b=(root/row['file']).read_bytes();assert hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()==row['expected_git_blob_sha']

@pytest.mark.parametrize("dt",[1,.25])
def test_audit_hours_durations_and_hourly_lexical_compatibility(dt):
    raw=json.loads((P.parents[1]/'inputs/zhang_s4.json').read_text())
    if dt==.25:raw=resample_hourly(raw)
    out=E.solve(Scenario.model_validate(raw),True)
    for field in ["allocations","migration_audit","network_dispatch"]:
        for row in out[field]:
            assert row["hour"]==row["step"]*dt
            assert row["duration_h"]==dt
            if dt==1:assert isinstance(row["hour"],int)
