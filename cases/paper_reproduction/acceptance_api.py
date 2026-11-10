#!/usr/bin/env python3
"""Independent HTTP/export checks: no app imports, no solver self-reproduction.
Uses published Table I constants and cached original workbook outputs, not product code.
Run: python cases/paper_reproduction/acceptance_api.py [output-directory]
"""
import pathlib,json,sys,copy,urllib.request,urllib.error,uuid,io,zipfile,csv,time,hashlib
import numpy as np,openpyxl
P=pathlib.Path(__file__).resolve().parent;O=pathlib.Path(sys.argv[1] if len(sys.argv)>1 else '/workspace/sim-agent-change-evidence/independent');O.mkdir(parents=True,exist_ok=True)
BASE='http://127.0.0.1:8080';checks=[];failures=[]
def api(path,body=None,raw=False):
 q=urllib.request.Request(BASE+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
 try:
  with urllib.request.urlopen(q,timeout=180) as f:b=f.read()
 except urllib.error.HTTPError as e:raise RuntimeError(str(e.code)+':'+e.read().decode()) from e
 return b if raw else json.loads(b)
def check(name,ok,**metrics):
 row=dict(name=name,passed=bool(ok),**metrics);checks.append(row)
 if not ok:failures.append(row)
 print(json.dumps(row,ensure_ascii=False),flush=True)
 (O/'checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2));(O/'failures.json').write_text(json.dumps(failures,ensure_ascii=False,indent=2))
def export(sid,folder):
 b=api(f'/api/sessions/{sid}/export.zip',raw=True);folder.mkdir(parents=True,exist_ok=True);(folder/'export.zip').write_bytes(b)
 z=zipfile.ZipFile(io.BytesIO(b));read=lambda n:list(csv.DictReader(io.StringIO(z.read(n).decode())))
 return z,read
I=np.array([[1,1,0],[-1,0,1],[0,-1,-1.]])
for case,expected in enumerate([2920,2980,2997.5,3000,3000,3030,3050],1):
 s=json.loads((P/f'inputs/zhang_s{case}.json').read_text());sid='verifyzhang'+uuid.uuid4().hex[:16];folder=O/f'zhang_s{case}';folder.mkdir(exist_ok=True);(folder/'input.json').write_text(json.dumps(s))
 api(f'/api/sessions/{sid}/model/load',s);run=api(f'/api/sessions/{sid}/model/rerun',{'ac':False});result=api(f'/api/sessions/{sid}/results');(folder/'run.json').write_text(json.dumps(run));(folder/'results.json').write_text(json.dumps(result));(folder/'meta.json').write_text(json.dumps({'session_id':sid}))
 z,read=export(sid,folder);df=read('dispatch_optimized.csv');alloc=read('allocations_optimized.csv');admit=read('job_admission_optimized.csv');migration=read('migration_audit_optimized.csv');mapping=json.loads(z.read('audit_optimized.json'))['network_mapping'];nd=read('network_dispatch_optimized.csv');model=json.loads(z.read('scenario.json'));jj={j['id']:j for j in model['jobs']};residual=0.;welfare=[]
 for h in range(24):
  a=[x for x in alloc if int(x['hour'])==h];execution=np.array([sum(float(x['energy_mwh']) for x in a if x['destination']==f'DC{k}') for k in [1,2,3]])
  g=np.array([float(df[h][f'gen{k}_MW']) for k in [1,2,3]]);flow=np.array(json.loads(nd[h]['flow_mw']));theta=np.array(json.loads(nd[h]['theta_rad']))
  residual=max(residual,float(max(abs(g-execution-I@flow))),float(max(abs(flow-.5*(I.T@theta)))),max(0,float(max(abs(flow)-[5,10,10]))),max(0,float(max(g-[50,30,50]))),max(0,float(max(execution-125))))
  value=sum(float(x['value_cny_mwh'])*float(x['served_mwh']) for x in admit if jj[x['job']]['release']==h)
  migration_cost=0
  for link in model['links']:
   fw=sum(float(x['energy_mwh']) for x in a if x['origin']==link['a'] and x['destination']==link['b']);bw=sum(float(x['energy_mwh']) for x in a if x['origin']==link['b'] and x['destination']==link['a'])
   residual=max(residual,max(0,fw-link['bw_mw'],bw-link['bw_mw']));migration_cost+=abs(fw-bw)*link['fee_cny_mwh']
   row=next(x for x in migration if x['src']==link['a'] and x['dst']==link['b'] and int(x['hour'])==h)
   residual=max(residual,abs(float(row['gross_mwh'])-fw-bw),abs(float(row['signed_net_mwh'])-fw+bw))
  welfare.append(value-float(g@[10,20,10])-2*sum(abs(flow))-migration_cost)
 for j in model['jobs']:
  amount=sum(float(x['energy_mwh']) for x in alloc if x['job']==j['id']);ad=next(x for x in admit if x['job']==j['id'])
  residual=max(residual,abs(amount-float(ad['served_mwh'])),abs(amount+float(ad['unserved_mwh'])-j['energy_mwh']))
 error=max(abs(x-expected) for x in welfare)
 check('Zhang_s'+str(case),error<=1e-5 and residual<=1e-6 and abs(result['audit']['optimized']['market_clearing']['welfare_cny']-sum(welfare))<=1e-5,max_welfare_error_per_hour=error,max_constraint_audit_residual=residual,welfare_per_hour=welfare[0],session_id=sid,full_precision_allocations=len(alloc),mapping_B=[x['b_mw_per_rad'] for x in mapping['branches']])
# Synthetic diagnostics are explicitly NOT paper accuracy.
for cap in [1,100]:
 s=dict(name='B01_synthetic_control',network_case='custom',network=dict(buses=[dict(name='one',vn_kv=100)],ext_grids=[dict(bus=0,import_max_mw=2)]),data_centers=[dict(name='DC',bus=0,cap_it_mw=cap,pue=1,interactive_mw=[1]*24,batch_mwh=0)],storage=[],pv=[],jobs=[],carbon_weight=0)
 sid='verifypeak'+uuid.uuid4().hex[:16];api(f'/api/sessions/{sid}/model/load',s);v=api(f'/api/sessions/{sid}/model/validate');api(f'/api/sessions/{sid}/model/rerun',{'ac':False});z,read=export(sid,O/f'peak_cap{cap}');actual=max(float(x['DC_grid_MW']) for x in read('dispatch_optimized.csv'))
 (O/f'peak_cap{cap}/validation.json').write_text(json.dumps(v));check('B01_fixed1_cap'+str(cap),v['islands'][0]['peak_load_mw']==actual==1 and not any('大于可靠' in x for x in v['warnings']),actual_peak_mw=actual,validation=v,synthetic_not_paper=True)
s['data_centers'][0]['interactive_mw']=[3]*24;sid='verifyshort'+uuid.uuid4().hex[:16];api(f'/api/sessions/{sid}/model/load',s);v=api(f'/api/sessions/{sid}/model/validate')
try:api(f'/api/sessions/{sid}/model/rerun',{'ac':False});error='unexpected success'
except RuntimeError as e:error=str(e)
(O/'true_shortage_failure.txt').write_text(error);check('B01_true_shortage_preserved',any('大于可靠' in x for x in v['warnings']) and 'infeasible' in error,error=error,synthetic_not_paper=True)
# Product annual policy vs original cached published grid and per-hour migration outputs.
b=json.loads((P/'inputs/zheng2019_annual.json').read_text());annual=api('/api/paper-reproduction/annual-migration',b);(O/'annual_results.json').write_text(json.dumps(annual));(O/'annual_export.zip').write_bytes(api(annual['export_url'],raw=True))
w=openpyxl.load_workbook(P/'sources/zheng_7_Load_Migration.xlsx',data_only=True,read_only=True);rows=list(w['2019'].values)[1:8761];expected=np.array([float(r[11] or 0) for r in rows]);aa=np.array([x['total_absorbed_mwh'] for x in annual['hourly']]);err=float(max(abs(aa-expected)))
check('Zheng_8760_annual_policy_vs_original',err<=1e-6,n_hours=len(aa),max_hourly_error_mwh=err,absorbed_gwh=float(aa.sum()/1000),lifecycle_avoided_kt=annual['grid'][0]['net_avoided_kt'])
ref=openpyxl.load_workbook(P/'sources/zheng_6_Results_2019.xlsx',data_only=True,read_only=True);rr=list(ref['reduction'].values);cc=list(ref['abatement'].values);lookup={float(r[0]):r for r in rr[1:] if isinstance(r[0],(int,float))};cost={float(r[0]):r for r in cc[1:] if isinstance(r[0],(int,float))};de=[];dc=[]
for g in annual['grid']:
 col=min(range(1,27),key=lambda j:abs(float(rr[0][j])-g['utilization']));de.append(g['net_avoided_kt']-float(lookup[g['new_dc_count']][col]));dc.append(g['net_abatement_cost_per_t']-float(cost[g['new_dc_count']][col]))
check('Zheng_546_grid_carbon_and_cost_vs_original',len(de)==546 and max(abs(np.array(de)))<=1e-6 and max(abs(np.array(dc)))<=1e-4,grid_points=len(de),max_net_reduction_error_kt=float(max(abs(np.array(de)))),max_abatement_cost_error_usd_t=float(max(abs(np.array(dc)))))
selected=annual['grid'][b['hourly_case_index']];op=sum(r['operational_avoided_t'] for r in annual['hourly']);vre=sum(r['vre_lifecycle_t'] for r in annual['hourly']);construction=sum(r['construction_allocated_t'] for r in annual['hourly']);check('Zheng_annual_export_ledger_independent_recompute',abs(op-vre-construction-selected['net_avoided_t'])<=1e-6,operational_avoided_t=op,vre_lifecycle_t=vre,construction_t=construction,net_t=op-vre-construction)
# Fresh 365 native product LP runs. Inputs contain headroom/offers, NOT realized migration.
head=np.maximum(0,float(w['DC_2019']['G11'].value)-np.array(b['baseline_dc_mw']))*b['existing_dc_count']*b['movable_fraction'];native=[];lca=[];native_operational=[]
for day in range(365):
 sl=slice(day*24,day*24+24);h=head[sl];curt=np.array(b['curtailment_mwh'])[sl];ci=np.array(b['source_ci_t_mwh'])[sl];vre=np.array(b['vre_lifecycle_t_mwh'])[sl]
 s=dict(name=f'Zheng2019_native_lifecycle_day{day+1}',synthetic=False,note='Original 2019 offered headroom only; endogenous routing; mixed VRE lifecycle factor is author hourly proportional-curtailment mix, not separately optimized wind/solar dispatch',network_case='custom',network=dict(buses=[dict(name='CA',vn_kv=110),dict(name='PJM',vn_kv=110)],ext_grids=[dict(bus=0,name='CA_no_import',import_max_mw=0,price_cny_kwh=[0]*24),dict(bus=1,name='PJM',import_max_mw=20000,price_cny_kwh=[.001]*24)]),data_centers=[dict(name=name,bus=i,cap_it_mw=20000,pue=1,interactive_mw=[0]*24,batch_mwh=0,pf_q_ratio=0) for i,name in enumerate(['CA','PJM'])],storage=[],pv=[dict(name='author_mixed_curtailed_VRE',bus=0,cap_mw=5000,profile=(curt/5000).tolist(),lifecycle_tco2e_mwh_profile=vre.tolist())],jobs=[dict(id=f'h{t}',dc='PJM',release=t,deadline=t+1,energy_mwh=float(value),max_mw=float(value),allowed_dcs=['CA','PJM'],source='Original author baseline/headroom, no optimal decision') for t,value in enumerate(h) if value>1e-8],links=[dict(a='CA',b='PJM',bw_mw=20000,latency_ms=0)],mig_max_mw=20000,mig_day_share=1,pv_curtail_penalty=0,grid_markup_cny_mwh=0,gen_min_share=0,unserved_penalty_cny_mwh=20000,carbon_weight=0,carbon_factor=0,carbon_shape='flat',carbon_profiles={'CA':[0]*24,'PJM':ci.tolist()},bus_region={'0':'CA','1':'PJM'},price_cny_kwh=[.001]*24,lifecycle_enabled=True,lifecycle_counterfactual='jobs_origin_uniform',sources={'workbook':'Original 7 Load Migration2019 F/G/H/K; DC2019 G11; same 8760 rows, no leap-day modification','opportunity_cost':'1 perMWh is a positive curtailment-priority signal, not paper financial tariff'})
 sid='verifyzheng'+uuid.uuid4().hex[:16];folder=O/f'zheng_native/day{day+1:03}';folder.mkdir(parents=True,exist_ok=True);(folder/'input.json').write_text(json.dumps(s));api(f'/api/sessions/{sid}/model/load',s);api(f'/api/sessions/{sid}/model/rerun',{'ac':False});r=api(f'/api/sessions/{sid}/results');(folder/'results.json').write_text(json.dumps(r));(folder/'meta.json').write_text(json.dumps({'session_id':sid}));z,read=export(sid,folder);df=read('dispatch_optimized.csv');native.extend(float(x['CA_grid_MW']) for x in df);ledger=json.loads(z.read('audit_optimized.json'))['lifecycle_ledger'];lca.append(ledger['net_avoided_t']);native_operational.append(ledger['counterfactual_t']-ledger['legacy_location_t'])
 if day%25==0:print('fresh native LP day',day+1,'/365',flush=True)
actual=np.array(native);maxerr=float(max(abs(actual-expected)));lc=sum(lca)/1000;target=sum(float(r[20] or 0) for r in rows)/1e6
check('Zheng_8760_fresh_native_LP_and_product_lifecycle',maxerr<=1e-6 and abs(lc-target)<=1e-6,n_daily_native_runs=365,n_hours=len(actual),hourly_absorption_error_mwh=maxerr,absorbed_gwh=float(actual.sum()/1000),native_product_lifecycle_avoided_kt=lc,original_lifecycle_avoided_kt=target,native_legacy_location_avoided_kt=sum(native_operational)/1000)
with (O/'native_8760_comparison.csv').open('w') as f:
 wr=csv.writer(f);wr.writerow(['hour','original_mwh','fresh_product_mwh']);wr.writerows(zip(range(8760),expected,actual))
(O/'summary.json').write_text(json.dumps(dict(n_independent_gates=len(checks),passed=sum(x['passed'] for x in checks),failed=len(failures),checks=checks),ensure_ascii=False,indent=2));print('INDEPENDENT ACCEPTANCE COMPLETE',len(checks),'gates, failures',len(failures),flush=True)
sys.exit(bool(failures))
