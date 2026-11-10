"""Independent sparse matrix LP on ALL original8760 points; no app/author solver imports.
Perfect CFE/grid-factor0/excess0 implies all imports0 and no brown storage.
Uniform complete virtual graph: minimal flow cost = fee/2 * sum(abs(net shift)).
No chronological aggregation, typical days, precomputed optimal capacities or synthetic profiles.
This is the procurement submodel, NOT background Europe OPF.
"""
import json,pathlib,sys,time
import numpy as np
from scipy.sparse import coo_matrix
from scipy.optimize import linprog
P=pathlib.Path(__file__).resolve().parent;O=pathlib.Path(sys.argv[1]);O.mkdir(parents=True,exist_ok=True)
for key in ['riepin8760_f0','riepin8760_f40','riepin8760_f40_manuscript']:
 start=time.monotonic();m=json.loads((P/(key+'.json')).read_text());S=m['sites'];N=len(S[0]['load_mw']);I=len(S);assert N==8760 and m['target']==1 and m['matching']=='paper_cfe_score' and all(all(x==0 for x in s['grid_cfe']) for s in S)
 V=4*I+10*I*N;c=np.zeros(V);bounds=[(0,None)]*V;ER=[];EC=[];ED=[];eb=[];UR=[];UC=[];UD=[];ub=[]
 def v(i,t,k):return 4*I+10*(i*N+t)+k
 def eq(pairs,rhs=0):
  r=len(eb);eb.append(rhs)
  for k,x in pairs:
   if x:ER.append(r);EC.append(k);ED.append(x)
 def le(pairs,rhs=0):
  r=len(ub);ub.append(rhs)
  for k,x in pairs:
   if x:UR.append(r);UC.append(k);UD.append(x)
 for i,s in enumerate(S):
  b=s['battery'];G=s['generators'];assert len(G)==2 and G[0]['id']=='onwind' and G[1]['id']=='solar'
  c[4*i:4*i+4]=[G[0]['capital_per_mw_year'],G[1]['capital_per_mw_year'],b['capital_power_per_mw_year'],b['capital_energy_per_mwh_year']]
  for t in range(N):
   z=lambda k:v(i,t,k)
   c[z(0)]=G[0]['marginal_per_mwh'];c[z(1)]=G[1]['marginal_per_mwh'];c[z(3)]=b['discharge_cost_internal_per_mwh']/b['eta_discharge'];c[z(6)]=c[z(7)]=m.get('spatial_fee_per_mwh',1e-5)/2;c[z(8)]=c[z(9)]=m.get('temporal_fee_per_mwh',1e-5)
   bounds[z(5)]=((1-m['flexibility'])*s['load_mw'][t],(1+m['flexibility'])*s['load_mw'][t])
   if not m['spatial_shifting'] or m['flexibility']==0:bounds[z(6)]=bounds[z(7)]=(0,0)
   if not m['temporal_shifting'] or m['flexibility']==0:bounds[z(8)]=bounds[z(9)]=(0,0)
   for a in [0,1]:le([(z(a),1),(4*i+a,-G[a]['availability'][t])])
   le([(z(2),1),(4*i+2,-1)]);le([(z(3),1),(4*i+2,-1)]);le([(z(4),1),(4*i+3,-1)])
   eq([(z(0),1),(z(1),1),(z(3),1),(z(2),-1),(z(5),-1)])
   eq([(z(4),1),(v(i,(t-1)%N,4),-(1-b.get('loss_per_hour',0))),(z(2),-b['eta_charge']),(z(3),1/b['eta_discharge'])])
   eq([(z(5),1),(z(6),-1),(z(7),1),(z(8),-1),(z(9),1)],s['load_mw'][t])
  if m['temporal_shifting']:
   for d in range(0,N,24):eq([(v(i,t,8),1) for t in range(d,d+24)]+[(v(i,t,9),-1) for t in range(d,d+24)])
 for t in range(N):eq([(v(i,t,6),1) for i in range(I)]+[(v(i,t,7),-1) for i in range(I)])
 Aeq=coo_matrix((ED,(ER,EC)),shape=(len(eb),V)).tocsr();Aub=coo_matrix((UD,(UR,UC)),shape=(len(ub),V)).tocsr();print(key,'START',V,len(eb),len(ub),flush=True)
 r=linprog(c,A_ub=Aub,b_ub=ub,A_eq=Aeq,b_eq=eb,bounds=bounds,method='highs',options={'time_limit':240,'primal_feasibility_tolerance':1e-7,'dual_feasibility_tolerance':1e-7})
 out=dict(name=key,source_kind='AUTHOR_ORIGINAL_8760_NO_TIME_AGGREGATION',reference_method='independent SciPy sparse coefficient LP; no product code imports; procurement scope only',status=int(r.status),message=r.message,optimal=bool(r.success),elapsed_s=time.monotonic()-start,variables=V,equalities=len(eb),inequalities=len(ub),objective=float(r.fun) if r.success else None,iterations=int(r.nit))
 if r.success:
  out.update(max_equality_residual=float(np.max(np.abs(Aeq@r.x-np.array(eb)))),max_inequality_violation=float(max(0,np.max(Aub@r.x-np.array(ub)))),investments=[dict(site=s['id'],wind_mw=float(r.x[4*i]),solar_mw=float(r.x[4*i+1]),battery_power_mw=float(r.x[4*i+2]),battery_energy_mwh=float(r.x[4*i+3])) for i,s in enumerate(S)])
  np.savez_compressed(O/(key+'_optimal_vector.npz'),x=r.x);out['vector_layout']='first4*sites: wind,solar,P,E; then10 values per site/hour: windgen,solargen,ch,dis,SOC,load,spacein,spaceout,recover,defer'
 (O/(key+'.json')).write_text(json.dumps(out,indent=2));print(json.dumps(out),flush=True)
