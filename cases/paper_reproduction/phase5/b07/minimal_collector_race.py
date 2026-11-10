"""Installed Pyomo singleton-collector race, controlled only by thread scheduling.
No dependency patch or fake solver values; synthetic lifecycle regression, NOT paper precision.
"""
import sys,pathlib,json,threading,traceback,inspect,gc,weakref,time,importlib
import pyomo.environ as pyo
from pyomo.core.expr.numeric_expr import LinearExpression,SumExpression
from pyomo.contrib.appsi.solvers.highs import Highs
from contextlib import nullcontext
module=importlib.import_module('pyomo.contrib.appsi.utils.collect_vars_and_named_exprs');collect=module.collect_vars_and_named_exprs
algorithm,mode=sys.argv[1:3];out=pathlib.Path(sys.argv[3]);out.parent.mkdir(parents=True,exist_ok=True)
if mode=='protected':
 from app.solver_execution import pyomo_execution
else:pyomo_execution=lambda scope:nullcontext()
a=pyo.ConcreteModel();a.x=pyo.Var([0,1],bounds=(0,10));ea=LinearExpression(linear_coefs=[2.,3.],linear_vars=[a.x[0],a.x[1]]);a.c0=pyo.Constraint(expr=a.x[0]>=0);a.c1=pyo.Constraint(expr=a.x[1]>=0);a.c=pyo.Constraint(expr=SumExpression([ea,1])>=8);a.obj=pyo.Objective(expr=a.x[0]+a.x[1]);own={id(v) for v in a.component_data_objects(pyo.Var)}
ready=threading.Event();built=threading.Event();backend=threading.Event();attempt=threading.Event();proof={};weakowners=[]
def other():
 assert ready.wait(10);attempt.set()
 with pyomo_execution('probe-B'):
  b=pyo.ConcreteModel();b.y=pyo.Var([0,1],bounds=(0,10));eb=LinearExpression(linear_coefs=[5.,7.],linear_vars=[b.y[0],b.y[1]]);weakowners.append(weakref.ref(b.y));rr=collect(SumExpression([eb,2]));proof['B_collector_vars']=[v.name for v in rr[1]];proof['shared_collector_id']=id(module._visitor);built.set()
  if mode=='unsafe':assert backend.wait(10)
thread=threading.Thread(target=other);thread.start();src,first=inspect.getsourcelines(collect);target=first+next(i for i,line in enumerate(src) if 'list(_visitor.variables.values())' in line);paused=False

def trace(frame,event,arg):
 global paused
 if not paused and frame.f_code is collect.__code__ and event=='line' and frame.f_lineno==target and frame.f_locals.get('expr') is a.c.body:
  paused=True;ready.set();assert attempt.wait(10);proof['B_entered_while_A_collects']=built.wait(.2 if mode=='protected' else 10)
 return trace
original=Highs._solve
def inspect_backend(self,timer):
 foreign=[v[0] for k,v in self._vars.items() if k not in own];proof['foreign_vars_in_A_solver']=len(foreign);proof['foreign_names_while_B_alive']=[v.name for v in foreign];backend.set()
 if mode=='unsafe':thread.join(10);assert not thread.is_alive();gc.collect()
 proof['foreign_names_after_B_scope']=[v.name for v in foreign];proof['B_owner_collected_before_legacy_dictionary']=bool(weakowners and weakowners[0]() is None)
 return original(self,timer)
Highs._solve=inspect_backend;opt=pyo.SolverFactory('appsi_highs');opt.config.time_limit=10;opt.highs_options.update(solver=algorithm,parallel='off');started=time.monotonic();error=None
try:
 with pyomo_execution('probe-A'):
  if mode!='serial':sys.settrace(trace)
  r=opt.solve(a,load_solutions=False);opt.load_vars();proof.update(objective=pyo.value(a.obj),constraint_lhs=pyo.value(a.c.body),termination=str(r.solver.termination_condition))
except Exception as e:error=f'{type(e).__name__}: {e}';out.with_suffix('.traceback.txt').write_text(traceback.format_exc())
finally:
 sys.settrace(None);backend.set();ready.set();thread.join(10);Highs._solve=original
proof.update(algorithm=algorithm,mode=mode,error=error,expected_objective=7/3,elapsed_s=time.monotonic()-started,installed_collector_return_line=target,purpose='shared visitor/lifecycle synthetic regression; not paper precision');out.write_text(json.dumps(proof,indent=2));print(json.dumps(proof),flush=True)
if mode=='unsafe':assert error and 'Duplicate symbol' in error and proof['foreign_vars_in_A_solver']==2 and proof['B_owner_collected_before_legacy_dictionary']
else:assert error is None and abs(proof['objective']-7/3)<1e-8 and proof['foreign_vars_in_A_solver']==0
