"""Product regressions; independent scientific/CSV verification lives outside pytest."""
import copy,json,io,zipfile
from pathlib import Path
import pytest
from app.opt_grid_feedback import GridFeedbackModel,solve,clear,_signals,check_axis,FeedbackFailure,export_task
P=Path(__file__).resolve().parents[1]/'cases/paper_reproduction/phase6'
def case(name='benchmark_negative_lmce'):return json.loads((P/(name+'.json')).read_text())
def axis(m):return dict(location='SYNTHETIC',year=2020,timezone='UTC',start=m['start'],step_minutes=60,length=len(m['buses'][0]['background_load_mw']))
@pytest.mark.parametrize('patch',[dict(dt_hours=.25),dict(start='2020-02-29T00:00:00'),dict(start='2020-02-29T00:00:00+08:00'),dict(start='2020-02-29T00:15:00+00:00'),dict(fixed_lmce=[1]),dict(max_iterations=0),dict(selected_signal='unknown')])
def test_reject_unsupported_or_external_signal(patch):
 x=case();x.update(patch)
 with pytest.raises(ValueError):GridFeedbackModel.model_validate(x)
def test_no_silent_year_truncation():
 x=case()
 for b in x['buses']:b['background_load_mw']*=8784
 with pytest.raises(ValueError,match='168h'):GridFeedbackModel.model_validate(x)
def test_subset_index_and_leap_day_integrity():
 x=case('rts_leap4h');m=GridFeedbackModel.model_validate(x);assert m.n_steps==4 and m.source['source_hour_indices']==[1416,1417,1418,1419]
 x['source']['source_hour_indices']=[1392,1393,1394,1395]
 with pytest.raises(ValueError,match='timestamps'):GridFeedbackModel.model_validate(x)
def test_axis_rejects_15min_or_different_start():
 x=case();m=GridFeedbackModel.model_validate(x);a=axis(x);check_axis(a,m);a['step_minutes']=15
 with pytest.raises(ValueError):check_axis(a,m)
def test_disconnected_rejected():
 x=case();x['lines']=[]
 with pytest.raises(ValueError):GridFeedbackModel.model_validate(x)
def test_cost_clearing_negative_lmce_analytic():
 s=GridFeedbackModel.model_validate(case());r=clear(s,0,{'A':0,'B':30,'C':1});assert r['pg_mw']==pytest.approx([6,25]);assert r['cost_usd']==pytest.approx(560);assert r['operational_tco2']==pytest.approx(12)
 sig,_=_signals(s,[r],60);b=next(x for x in sig if x['bus']=='B');assert b['fd_plus']==pytest.approx(-2);assert b['fd_minus']==pytest.approx(-2);assert b['analytic_lmce']==pytest.approx(-2);assert b['stable'] and b['negative_lmce'];assert b['lmp_usd_mwh']==pytest.approx(30)
def test_four_policy_tradeoff_not_fixed_external_factors():
 r=solve(case());p={x['signal']:x for x in r['policies']};assert r['baseline_totals']['cost_usd']==pytest.approx(560)
 assert p['lmce']['actual_operational_delta_tco2']==pytest.approx(-.4);assert p['lmce']['actual_cost_delta_usd']==pytest.approx(2)
 assert p['lmp']['actual_operational_delta_tco2']==pytest.approx(.4);assert p['lmp']['actual_cost_delta_usd']==pytest.approx(-2)
 assert all(x['converged'] and not x['global_optimality_claimed'] and x['max_work_residual_mw']<1e-9 for x in p.values())
def test_no_change_stays_no_change_no_redundant_migration():
 r=solve(case('benchmark_clean'));assert not r['migrations'];assert all(x['final_net_work_moved_mwh']==0 and x['actual_operational_delta_tco2']==0 for x in r['policies'])
def test_wrong_way_surplus_and_linear_prediction_counterexample_retained():
 r=solve(case('benchmark_congestion'));p={x['signal']:x for x in r['policies']};assert p['average']['actual_operational_delta_tco2']==pytest.approx(2);assert p['excess']['actual_operational_delta_tco2']==pytest.approx(2);assert p['lmce']['predicted_operational_delta_from_initial_tco2']==pytest.approx(-2);assert p['lmce']['actual_operational_delta_tco2']==pytest.approx(0);assert any(any(x['active_set_changed'].values()) for x in r['signals'])
def test_strict_unstable_is_not_silently_replaced():
 x=case('benchmark_congestion');x.update(signals=['lmce'],selected_signal='lmce',unstable_signal_policy='fail',require_convergence=True)
 with pytest.raises(FeedbackFailure) as err:solve(x)
 assert err.value.partial_result['policies'][0]['status']=='signal_unstable'
def test_iteration_limit_never_claimed_optimal():
 x=case();x.update(max_iterations=1,require_convergence=True)
 with pytest.raises(FeedbackFailure) as err:solve(x)
 assert err.value.partial_result['policies'][0]['status']=='iteration_limit';assert err.value.partial_result['generation'];assert not err.value.partial_result['selected_policy']['global_optimality_claimed']
def test_infeasible_grid_not_shedding_or_fallback():
 x=case()
 for g in x['generators']:g['available_mw']=[0]
 with pytest.raises(RuntimeError,match='not optimal'):solve(x)
def test_perturbation_infeasible_preserved_as_error_not_zero():
 x=case('benchmark_clean');x.update(signals=['lmce'],selected_signal='lmce',require_convergence=True);x['generators'][0]['available_mw']=[20]
 with pytest.raises(FeedbackFailure) as err:solve(x)
 rows=err.value.partial_result['signals'];assert rows[0]['fd_plus'] is None and 'plus' in rows[0]['fd_errors'] and not rows[0]['stable']
def test_lca_does_not_pollute_operational_lmce():
 x=case();x['generators'][0]['lifecycle_extra_tco2_mwh']=.1;r=solve(x);assert r['baseline_totals']['lifecycle_extra_tco2']==pytest.approx(.6);assert r['selected_policy']['actual_operational_delta_tco2']==pytest.approx(-.4)
def test_priced_carbon_iso_lmp_vs_operating_cost_are_separate():
 x=case();x['iso_carbon_price_usd_t']=1;r=solve(x);b=next(v for v in r['signals'] if v['site']=='computeB' and v['iteration']==0 and v['policy']=='lmce');assert b['lmp_usd_mwh']==pytest.approx(28);assert b['fd_cost_plus']==pytest.approx(30);assert b['fd_iso_objective_plus']==pytest.approx(28)
 q=next(v for v in r['iterations'] if v['policy']=='lmce' and v['status']=='recleared_optimal');assert q['actual_cost_delta_usd']==pytest.approx(2);assert q['actual_iso_objective_delta_usd']==pytest.approx(1.6);assert q['predicted_cost_delta_usd']==pytest.approx(2)
def test_validated_basis_matches_fd_without_primary_loosening():
 x=case();x['signal_method']='validated_basis';r=solve(x);assert r['selected_policy']['actual_operational_delta_tco2']==pytest.approx(-.4)
 for row in r['iterations']:
  if 'scheduler' in row:assert row['scheduler']['primary_after']<=row['scheduler']['primary_optimum']+1e-8
def test_freeze_success_failed_partial_export_and_history(tmp_path,monkeypatch):
 from app import settings
 from app.foundation import service as f,store
 monkeypatch.setattr(settings,'DATA_DIR',str(tmp_path));p=f.project_new(dict(name='SYNTHETIC grid unit isolated'));x=case();d=f.scenario_new(dict(project_id=p['id'],name='grid',axis=axis(x),model=x));v=f.publish(d['id'],dict(expected_revision=1));t=f.task_new(dict(version_id=v['id'],solver=dict(ac_check=False)));r=f.execute(t['id']);assert r['status']=='completed';assert r['result']['model_kind']=='opt_grid_feedback'
 z=zipfile.ZipFile(io.BytesIO(export_task(r)));assert json.loads(z.read('input_snapshot.json'))==t['snapshot'];assert 'generation.csv' in z.namelist();assert json.loads(z.read('results.json'))['baseline_totals']['cost_usd']==pytest.approx(560)
 old=copy.deepcopy(store.get('task',t['id']));x.update(max_iterations=1,require_convergence=True);f.draft_update(d['id'],dict(expected_revision=1,model=x));v2=f.publish(d['id'],dict(expected_revision=2));t2=f.task_new(dict(version_id=v2['id'],solver=dict(ac_check=False)));r2=f.execute(t2['id']);assert r2['status']=='failed' and r2['partial_result'];z=zipfile.ZipFile(io.BytesIO(export_task(r2)));assert 'results.json' not in z.namelist() and 'partial_NOT_ACCEPTED.json' in z.namelist();assert store.get('task',t['id'])==old
 with pytest.raises(ValueError):f.task_new(dict(version_id=v['id'],solver=dict(ac_check=True)))
 with pytest.raises(ValueError):f.task_new(dict(version_id=v['id'],objective='welfare',solver=dict(ac_check=False)))
