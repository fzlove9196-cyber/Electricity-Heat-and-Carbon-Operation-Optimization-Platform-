"""Independent SciPy/PTDF model and frozen CSV audit. NO imports of product code.
PTDF eliminates angle variables; emission optimal-face ranges distinguish degeneracy.
Inputs are public raw/presets; this oracle is NEW, never replaces lost historical oracle.
"""
from pathlib import Path
import json,csv,io,zipfile,hashlib,sys
import numpy as np
from scipy.optimize import linprog
from collections import defaultdict
R=Path(__file__).resolve().parent
class Ref:
 def __init__(self,m):
  self.m=m;self.bs=[x['id'] for x in m['buses']];self.g=m['generators'];self.n=len(self.bs);self.ng=len(self.g);self.slack=self.bs.index(m['slack_bus']);self.non=[i for i in range(self.n) if i!=self.slack];self.C=np.zeros((self.n,self.ng));self.A=np.zeros((len(m['lines']),self.n));self.b=[]
  for j,g in enumerate(self.g):self.C[self.bs.index(g['bus']),j]=1
  for j,e in enumerate(m['lines']):self.A[j,self.bs.index(e['from_bus'])]=1;self.A[j,self.bs.index(e['to_bus'])]=-1;self.b.append(e['b_mw_per_rad'])
  self.b=np.array(self.b);B=self.A.T@np.diag(self.b)@self.A;self.K=np.zeros((self.n,self.n));self.K[np.ix_(self.non,self.non)]=np.linalg.inv(B[np.ix_(self.non,self.non)]);self.H=np.diag(self.b)@self.A@self.K
  self.cost=np.array([g['cost_usd_mwh'] for g in self.g]);self.emit=np.array([g['operational_tco2_mwh'] for g in self.g]);self.iso=self.cost+m.get('iso_carbon_price_usd_t',0)*self.emit
 def loads(self,work,t):return np.array([b['background_load_mw'][t]+sum(work[i][t]*s.get('pue',1) for i,s in enumerate(self.m['sites']) if s['bus']==b['id']) for b in self.m['buses']],dtype=float)
 def solve(self,d,t,face=False):
  lim=np.array([e['limit_mw'] for e in self.m['lines']]);theta=self.m.get('max_abs_angle_rad',np.pi);G=np.vstack((self.H@self.C,-self.H@self.C,self.K@self.C,-self.K@self.C));h=np.r_[lim+self.H@d,lim-self.H@d,np.repeat(theta,self.n)+self.K@d,np.repeat(theta,self.n)-self.K@d];bounds=[(g.get('pmin_mw',0),g['available_mw'][t]) for g in self.g];opt=dict(A_ub=G,b_ub=h,A_eq=np.ones((1,self.ng)),b_eq=[sum(d)],bounds=bounds,method='highs-ds',options={'dual_feasibility_tolerance':1e-8,'primal_feasibility_tolerance':1e-8});r=linprog(self.iso,**opt)
  if not r.success:raise AssertionError('INDEPENDENT LP failed: '+r.message)
  inj=self.C@r.x-d;out=dict(pg=r.x,cost=float(self.cost@r.x),emissions=float(self.emit@r.x),iso=float(r.fun),flows=self.H@inj,theta=self.K@inj)
  if face:
   # Absolute $1e-6 optimal face tolerance declared; no fake matching of arbitrary ties.
   opt.update(A_ub=np.vstack((G,self.iso)),b_ub=np.r_[h,r.fun+1e-6]);lo=linprog(self.emit,**opt);hi=linprog(-self.emit,**opt)
   assert lo.success and hi.success;out['emission_face']=[float(lo.fun),float(-hi.fun)]
  return out
 def schedule(self,work,signals,policy):
  ns=len(self.m['sites']);nt=len(work[0]);N=ns*nt;lookup={(r['site'],r['step']):r for r in signals};key={'lmce':'lmce_tco2_mwh','lmp':'lmp_usd_mwh','average':'average_tco2_mwh','excess':'excess_mw'}[policy];c=np.array([lookup[s['id'],t][key]*s.get('pue',1) for s in self.m['sites'] for t in range(nt)]);A=np.zeros((nt,N));bounds=[]
  for i,s in enumerate(self.m['sites']):
   for t in range(nt):
    A[t,i*nt+t]=1;b=s['baseline_work_mw'][t];step=b*self.m.get('trust_fraction_per_iteration',.2);flex=self.m.get('flexibility',.2);bounds.append((max(0,b*(1-flex),work[i][t]-step),min(s['capacity_work_mw'],b*(1+flex),work[i][t]+step)))
  z=np.array([sum(s['baseline_work_mw'][t] for s in self.m['sites']) for t in range(nt)]);r=linprog(c,A_eq=A,b_eq=z,bounds=bounds,method='highs-ds');assert r.success;return float(r.fun)
def load_export(path):
 with zipfile.ZipFile(path) as z:
  m=json.loads(z.read('model.json'));r=json.loads(z.read('results.json') if 'results.json' in z.namelist() else z.read('partial_NOT_ACCEPTED.json'))
  for name in ['signals','basis','iterations','generation','lines','work','migrations']:
   rr=list(csv.DictReader(io.StringIO(z.read(name+'.csv').decode())))
   for row in rr:
    for k,v in row.items():
     if v=='':row[k]=None
     elif k in {'policy','generator','bus','site','from_bus','to_bus','line','from_site','to_site','method','status','timestamp','units'}:continue
     elif v in ('True','False'):row[k]=v=='True'
     else:
      try:row[k]=json.loads(v)
      except (ValueError,TypeError):pass
   r[name]=rr
 return m,r
def audit(m,r):
 ref=Ref(m);groups=defaultdict(list);work=defaultdict(list);flows=defaultdict(list);stats=dict(lp_groups=0,max_iso_objective_abs_error_usd=0.,max_flow_abs_error_mw=0.,max_balance_residual_mw=0.,max_work_residual_mw=0.,max_migration_residual_mw=0.,max_fd_abs_error_tco2_mwh=0.,max_scheduler_primary_abs_error=0.,degenerate_emission_groups=0,negative_lmce_rows=0,active_switch_rows=0)
 for x in r['generation']:groups[x['policy'],x['iteration'],x['step']].append(x)
 for x in r['work']:work[x['policy'],x['iteration'],x['step']].append(x)
 for x in r['lines']:flows[x['policy'],x['iteration'],x['step']].append(x)
 baseline=[s['baseline_work_mw'] for s in m['sites']];totals=defaultdict(lambda:dict(cost=0.,emissions=0.,lca=0.))
 for key,rows in groups.items():
  p,k,t=key;wr={x['site']:x for x in work[key]};w=[[wr[s['id']]['work_mw'] if j==t else s['baseline_work_mw'][j] for j in range(len(baseline[0]))] for s in m['sites']];d=ref.loads(w,t);rr=ref.solve(d,t,face=True);pg=np.array([next(x['p_mw'] for x in rows if x['generator']==g['id']) for g in m['generators']]);f=np.array([next(x['flow_mw'] for x in flows[key] if x['line']==e['id']) for e in m['lines']]);th=np.array([next((x['theta_from_rad'] if x['from_bus']==b else x['theta_to_rad'] for x in flows[key] if x['from_bus']==b or x['to_bus']==b),0.) for b in ref.bs]);balance=ref.C@pg-d-ref.A.T@f
  err=abs(float(ref.iso@pg)-rr['iso']);stats['max_iso_objective_abs_error_usd']=max(stats['max_iso_objective_abs_error_usd'],err);assert err<2e-5
  stats['max_flow_abs_error_mw']=max(stats['max_flow_abs_error_mw'],float(max(abs(f-np.diag(ref.b)@ref.A@th),default=0)));assert max(abs(balance),default=0)<1e-5 and max(abs(f)-np.array([e['limit_mw'] for e in m['lines']]),default=0)<1e-5
  assert np.max(abs(th))<=m.get('max_abs_angle_rad',np.pi)+1e-7;stats['max_balance_residual_mw']=max(stats['max_balance_residual_mw'],float(max(abs(balance))))
  e=float(ref.emit@pg);assert rr['emission_face'][0]-1e-5<=e<=rr['emission_face'][1]+1e-5
  if rr['emission_face'][1]-rr['emission_face'][0]>1e-5:stats['degenerate_emission_groups']+=1
  stats['max_work_residual_mw']=max(stats['max_work_residual_mw'],abs(sum(wi[t] for wi in w)-sum(wi[t] for wi in baseline)))
  for i,s in enumerate(m['sites']):b=baseline[i][t];assert -1e-7<=w[i][t]<=s['capacity_work_mw']+1e-7 and b*(1-m.get('flexibility',.2))-1e-7<=w[i][t]<=b*(1+m.get('flexibility',.2))+1e-7
  totals[p,k]['cost']+=float(ref.cost@pg);totals[p,k]['emissions']+=e;totals[p,k]['lca']+=sum(g.get('lifecycle_extra_tco2_mwh',0)*pg[j] for j,g in enumerate(m['generators']));stats['lp_groups']+=1
 for p in r['policies']:
  pairs=[k for k in totals if k[0]==p['signal']];kk=max(pairs,key=lambda x:x[1]) if pairs else ('baseline',0);z=totals[kk]
  for a,b in [('cost','cost_usd'),('emissions','operational_tco2'),('lca','lifecycle_extra_tco2')]:assert abs(z[a]-p['final_totals'][b])<2e-5
  assert abs(z['emissions']-totals['baseline',0]['emissions']-p['actual_operational_delta_tco2'])<2e-5
 for key,rows in work.items():
  p,k,t=key
  if p=='baseline':continue
  old=work.get((p,k-1,t),work['baseline',0,t]);delta={x['site']:x['work_mw']-next(y['work_mw'] for y in old if y['site']==x['site']) for x in rows};ledger={s['id']:0. for s in m['sites']}
  for x in r['migrations']:
   if (x['policy'],x['iteration'],x['step'])==(p,k-1,t):ledger[x['from_site']]-=x['work_mwh'];ledger[x['to_site']]+=x['work_mwh']
  resid=max(abs(ledger[i]-delta[i]) for i in ledger);stats['max_migration_residual_mw']=max(stats['max_migration_residual_mw'],resid);assert resid<1e-6
 # Baseline one-sided LP finite differences independently rebuilt in generator/PTDF space.
 for row in [x for x in r['signals'] if x['policy']=='lmce' and x['iteration']==0]:
  t=row['step'];d=ref.loads(baseline,t);z=ref.solve(d,t);j=ref.bs.index(row['bus']);h=row['fd_step_mw'];d[j]+=h;u=ref.solve(d,t);fd=(u['emissions']-z['emissions'])/h
  if row['fd_plus'] is not None:
   err=abs(fd-row['fd_plus']);stats['max_fd_abs_error_tco2_mwh']=max(stats['max_fd_abs_error_tco2_mwh'],err);assert err<1e-4
  stats['negative_lmce_rows']+=int(row['negative_lmce']);stats['active_switch_rows']+=int(any(row['active_set_changed'].values()))
 for it in r['iterations']:
  if 'scheduler' not in it:continue
  p=it['policy'];k=it['iteration'];ww=[[next((x['work_mw'] for x in work.get((p,k,t),work['baseline',0,t]) if x['site']==s['id'])) for t in range(len(baseline[0]))] for s in m['sites']];ss=[x for x in r['signals'] if x['policy']==p and x['iteration']==k];expected=ref.schedule(ww,ss,p);err=abs(expected-it['scheduler']['primary_optimum']);stats['max_scheduler_primary_abs_error']=max(stats['max_scheduler_primary_abs_error'],err);assert err<1e-5 and it['scheduler']['primary_after']<=expected+m.get('scheduler_primary_tolerance',0)+1e-5
 assert stats['max_work_residual_mw']<1e-6 and stats['max_flow_abs_error_mw']<1e-5
 return stats
if __name__=='__main__':
 # CLI can consume product frozen ZIP without application imports.
 src=Path(sys.argv[1]);out=Path(sys.argv[2]);m,r=load_export(src);stats=audit(m,r);out.write_text(json.dumps(dict(ok=True,independent_model='SciPy generator/PTDF, no app imports',statistics=stats),indent=2));print(stats)
