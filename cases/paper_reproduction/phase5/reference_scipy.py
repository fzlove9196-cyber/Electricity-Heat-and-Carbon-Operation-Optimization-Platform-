"""Independent 15-variable SciPy matrix LP, no application imports.
Two-hour analytic controls only, NEVER original paper accuracy.
"""
import numpy as np,json,pathlib,sys
from scipy.optimize import linprog
O=pathlib.Path(sys.argv[1]);checks=[]
# columns capacity, battery power/energy; then gen,grid,charge,discharge,SOC,excess at0/1
for label,policy,share,battery,expected in [('analytic_RES100_gap','res',1,False,4),('analytic_CFE100_storage','cfe',1,True,4),('analytic_paperCFE50','cfe',.5,False,3),('analytic_CFE100_infeasible','cfe',1,False,None)]:
 cost=np.zeros(15);cost[:3]=1;cost[5:7]=2;eq=[];rhs=[];ub=[];ubr=[]
 def row(**kw):
  a=np.zeros(15)
  for k,v in kw.items():a[int(k[1:])]=v
  return a
 for t,cf in enumerate([1,0]):
  a=np.zeros(15);a[3+t]=1;a[0]=-cf;ub.append(a);ubr.append(0)
  for start,capacity in [(7,1),(9,1),(11,2)]:
   a=np.zeros(15);a[start+t]=1;a[capacity]=-1;ub.append(a);ubr.append(0)
  a=np.zeros(15);a[3+t]=a[5+t]=a[9+t]=1;a[7+t]=a[13+t]=-1;eq.append(a);rhs.append(1)
  a=np.zeros(15);a[11+t]=1;a[11+(t-1)%2]-=1;a[7+t]=-1;a[9+t]=1;eq.append(a);rhs.append(0)
 if policy=='res':a=np.zeros(15);a[3:5]=1;eq.append(a);rhs.append(2*share)
 else:a=np.zeros(15);a[5:7]=1;ub.append(a);ubr.append(2*(1-share))
 a=np.zeros(15);a[13:15]=1;ub.append(a);ubr.append(2 if policy=='res' else 0)
 bounds=[(0,None)]*15
 if not battery:bounds[1:3]=[(0,0),(0,0)]
 sol=linprog(cost,A_ub=ub,b_ub=ubr,A_eq=eq,b_eq=rhs,bounds=bounds,method='highs')
 actual=json.loads((O/label/'summary.json').read_text())['objective'] if expected is not None else None
 checks.append(dict(control=label,scipy_status=int(sol.status),objective=None if not sol.success else float(sol.fun),product_objective=actual,expected=expected,passed=(sol.status==2 if expected is None else sol.success and abs(sol.fun-expected)<1e-8 and abs(actual-sol.fun)<1e-8)))
out=dict(name='independent_matrix_reference_4_synthetic_controls',gates=1,controls=4,passed=all(x['passed'] for x in checks),checks=checks,method='SciPy sparse-independent coefficient matrix, not imports from application; paper precision NOT claimed');(O/'independent_scipy_reference.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2));assert out['passed']
