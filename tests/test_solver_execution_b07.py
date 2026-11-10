import json,subprocess,sys,pathlib,threading,time,os
import pytest
ROOT=pathlib.Path(__file__).resolve().parents[1]
@pytest.mark.parametrize('algorithm',['ipm','simplex'])
@pytest.mark.parametrize('mode',['unsafe','serial','protected'])
def test_installed_collector_lifecycle(tmp_path,algorithm,mode):
 out=tmp_path/'proof.json';r=subprocess.run([sys.executable,str(ROOT/'cases/paper_reproduction/phase5/b07/minimal_collector_race.py'),algorithm,mode,str(out)],env=dict(os.environ,PYTHONPATH=str(ROOT)),text=True,capture_output=True,timeout=30);assert r.returncode==0,r.stdout+r.stderr;p=json.loads(out.read_text())
 if mode=='unsafe':assert p['foreign_vars_in_A_solver']==2 and 'Duplicate symbol' in p['error'] and 'legacy_soln.variable' in out.with_suffix('.traceback.txt').read_text()
 else:assert p['foreign_vars_in_A_solver']==0 and abs(p['objective']-7/3)<1e-8

def test_reentrant_and_failure_release():
 from app.solver_execution import pyomo_execution,execution_status
 with pytest.raises(ValueError):
  with pyomo_execution('outer') as a:
   with pyomo_execution('inner') as b:assert b['reentrant'] and b['ticket']==a['ticket']
   raise ValueError('expected negative')
 assert execution_status()['active'] is None

def test_fifo_wait_and_failure_not_swallowed():
 from app.solver_execution import pyomo_execution,execution_status
 start=threading.Event();release=threading.Event();done=[];metas=[]
 def first():
  try:
   with pyomo_execution('first'):start.set();assert release.wait(5);raise RuntimeError('expected')
  except RuntimeError:done.append('failed')
 def second():
  with pyomo_execution('second') as m:metas.append(m);done.append('second')
 a=threading.Thread(target=first);a.start();assert start.wait(5);b=threading.Thread(target=second);b.start();deadline=time.monotonic()+5
 while not execution_status()['queued_count'] and time.monotonic()<deadline:threading.Event().wait(.001)
 assert execution_status()['active']['scope']=='first' and execution_status()['queued_count']==1;release.set();a.join(5);b.join(5);assert not a.is_alive() and not b.is_alive();assert done==['failed','second'] and metas[0]['queue_wait_seconds']>0

def test_foreign_vars_rejected_before_backend():
 import pyomo.environ as pyo
 from app.solver_execution import pyomo_execution,checked_solve
 a=pyo.ConcreteModel();a.x=pyo.Var(bounds=(0,10));b=pyo.ConcreteModel();b.y=pyo.Var(bounds=(0,10));a.c=pyo.Constraint(expr=a.x+b.y>=2);a.obj=pyo.Objective(expr=a.x);o=pyo.SolverFactory('appsi_highs')
 with pyomo_execution('foreign'):
  with pytest.raises(RuntimeError,match='Foreign variables'):checked_solve(o,a,load_solutions=False)
 assert o._last_results_object is None

def test_owned_vars_and_mandatory_domain():
 import pyomo.environ as pyo
 from app.solver_execution import pyomo_execution,checked_solve
 a=pyo.ConcreteModel();a.x=pyo.Var(bounds=(2,10));a.obj=pyo.Objective(expr=a.x);o=pyo.SolverFactory('appsi_highs')
 with pytest.raises(RuntimeError,match='outside'):checked_solve(o,a,load_solutions=False)
 with pyomo_execution('valid') as meta:r=checked_solve(o,a,load_solutions=False);o.load_vars()
 assert pyo.value(a.x)==2 and meta['variable_ownership_checks']==[dict(declared_variables=1,solver_variables=1,foreign_variables=0)]

def test_all_builder_families_guarded():
 from app import opt_cfe,vcc
 from app.tools import sdco_engine
 from app.opt import tiered
 assert all(hasattr(f,'__wrapped__') for f in [opt_cfe.solve,vcc.day_ahead_curve,sdco_engine.solve,tiered.realtime_track])

def test_status_read_only():
 from fastapi.testclient import TestClient
 from app.main import app
 with TestClient(app) as c:
  j=c.get('/api/solver-execution/status').json();assert j['process_scope'] and 'FIFO' in j['policy']

@pytest.mark.parametrize("mode",["unsafe","protected"])
def test_deferred_capture_lock_lifecycle(tmp_path,mode):
 out=tmp_path/"tee.json";r=subprocess.run([sys.executable,str(ROOT/"cases/paper_reproduction/phase5/b07/minimal_tee_lock_race.py"),mode,str(out)],env=dict(os.environ,PYTHONPATH=str(ROOT)),capture_output=True,text=True,timeout=30);assert r.returncode==0,r.stdout+r.stderr
