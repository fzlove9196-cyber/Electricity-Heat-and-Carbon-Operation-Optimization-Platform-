#!/usr/bin/env python3
"""Independent HTTP/export/input parsing ONLY. No application imports.
Analytic controls clearly synthetic; 8760 author-input runs separately named.
"""
import json,sys,pathlib,urllib.request,urllib.error,zipfile,io,csv,copy,hashlib,datetime,uuid
P=pathlib.Path(__file__).resolve().parent;O=pathlib.Path(sys.argv[1]);O.mkdir(parents=True,exist_ok=True);checks=[];tasks={}
def api(path,b=None,raw=False,method=None):
 q=urllib.request.Request('http://127.0.0.1:8080'+path,data=None if b is None else json.dumps(b).encode(),headers={'Content-Type':'application/json'},method=method)
 try:
  with urllib.request.urlopen(q,timeout=1000) as f:r=f.read()
 except urllib.error.HTTPError as e:raise RuntimeError(str(e.code)+': '+e.read().decode())
 return r if raw else json.loads(r)
def check(name,ok,**kw):
 x=dict(name=name,passed=bool(ok),**kw);checks.append(x);print(json.dumps(x,ensure_ascii=False),flush=True);(O/'checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2))
def rejected(name,path,b):
 try:api(path,b);check(name,False,error='unexpected success')
 except Exception as e:check(name,('400:' in str(e) or '422:' in str(e)) and (name!='reject_daily_engine_annual' or '24h' in str(e)),error=str(e)[:1000])
def csvrows(z,n):return list(csv.DictReader(io.StringIO(z.read(n).decode())))
def small(**kw):
 return dict(model_kind='opt_cfe',name='SYNTHETIC analytic NOT paper precision',horizon_mode='benchmark',sites=[dict(id='A',region='A',load_mw=[1,1],generators=[dict(id='solar',technology='solar',region='A',availability=[1,0],capital_per_mw_year=1)],battery=dict(capital_power_per_mw_year=1,capital_energy_per_mwh_year=1,eta_charge=1,eta_discharge=1,max_power_mw=0,max_energy_mwh=0),grid_price_per_mwh=[2,2],grid_cfe=[0,0])],**kw)
project=api('/api/foundation/projects',dict(name='Phase5 年度CFE/热边界验收 · '+uuid.uuid4().hex[:6],documents=[{'source':'public scientific inputs, original 8760 vs synthetic boundaries explicitly separate'}]))
(O/'ui_project.json').write_text(json.dumps(project,ensure_ascii=False,indent=2))
def run(name,m,expected_failure=False):
 n=len(m['sites'][0]['load_mw']);axis=dict(location='original bidding zones' if n>168 else 'SYNTHETIC',year=m.get('weather_year',2013),timezone='UTC',start=m.get('start','2013-01-01T00:00:00+00:00'),step_minutes=60,length=n)
 d=api('/api/foundation/scenarios',dict(project_id=project['id'],name=name,axis=axis,model=m));v=api('/api/foundation/scenarios/'+d['id']+'/publish',dict(expected_revision=d['revision']));t=api('/api/foundation/tasks',dict(name=name,version_id=v['id'],solver=dict(ac_check=False,time_limit_s=600)));folder=O/name;folder.mkdir();(folder/'input.json').write_text(json.dumps(m,ensure_ascii=False));r=api('/api/foundation/tasks/'+t['id']+'/run',{});tasks[name]=dict(project=project['id'],scenario=d['id'],version=v['id'],version_hash=v['hash'],task=t['id'],input_hash=t['input_hash'],status=r['status']);(O/'ui_tasks.json').write_text(json.dumps(tasks,ensure_ascii=False,indent=2))
 check(name+'_status',r['status']==('failed' if expected_failure else 'completed'),status=r['status'],error=r.get('error'),task=t['id'])
 if r['status']!='completed':(folder/'failure.json').write_text(json.dumps(r,ensure_ascii=False,indent=2));return None
 b=api('/api/foundation/tasks/'+t['id']+'/export.zip',raw=True);(folder/'export.zip').write_bytes(b);z=zipfile.ZipFile(io.BytesIO(b));snap=json.loads(z.read('input_snapshot.json'));res=json.loads(z.read('results.json'));raw=z.read('hourly.csv');h=csvrows(z,'hourly.csv');flows=csvrows(z,'spatial_flows.csv');canonical=json.dumps(snap,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode();hash_match=hashlib.sha256(canonical).hexdigest()==t['input_hash'];op=api('/api/foundation/tasks/'+t['id']+'/open',{});check(name+'_freeze_open_export',hash_match and snap==r['snapshot'] and op.get('model_kind')=='opt_cfe' and len(h)==n*len(m['sites']),rows=len(h),input_hash_match=hash_match,hourly_sha256=hashlib.sha256(raw).hexdigest(),session_id_absent='session_id' not in op)
 (folder/'summary.json').write_text(json.dumps(res,ensure_ascii=False,indent=2));audit_export(name,snap['model'],res,h,flows)
 return dict(task=r,res=res,rows=h,flows=flows,model=snap['model'],folder=folder)
def audit_export(name,m,r,rows,flows):
 sites={s['id']:s for s in m['sites']};invest={s['site']:s for s in r['investments']};maxres=0.;capcost=0.;opcost=0.;sourcecap=[];totalgap=0.;allconstraints=0.;scores={};cpterms={'generation':0.,'grid':0.,'storage':0.,'shifts':0.};net={}
 for f in flows:
  q=float(f['shift_mwh']);t=int(f['step']);i=f['origin'];j=f['destination'];net[i,t]=net.get((i,t),0)-q;net[j,t]=net.get((j,t),0)+q;cpterms['shifts']+=q*m['spatial_fee_per_mwh']
 for i,s in sites.items():
  a=invest[i];b=s['battery'];period=[x for x in rows if x['site']==i];N=len(s['load_mw']);assert len(period)==N and [int(x['step']) for x in period]==list(range(N));caps={x['id']:x['capacity_mw'] for x in a['generators']};capcost+=sum(g['capital_per_mw_year']*caps[g['id']] for g in s['generators'])+b['capital_power_per_mw_year']*a['battery_power_mw']+b['capital_energy_per_mwh_year']*a['battery_energy_mwh'];prevG=float(period[-1]['green_soc_mwh']) if m['storage_boundary']=='cyclic' else 0.;prevB=float(period[-1]['brown_soc_mwh']) if m['storage_boundary']=='cyclic' else 0.;L=credit=clean=gen=excess=0.;dailydsm={}
  for t,x in enumerate(period):
   f=lambda k:float(x[k]);dt=f('duration_h');load=f('actual_load_mw');gd=f('grid_direct_mw');gc=f('grid_charge_mw');rc=f('local_charge_mw');rl=f('local_direct_mw');dg=f('green_discharge_mw');db=f('brown_discharge_mw');sg=f('green_soc_mwh');sb=f('brown_soc_mwh');g=sum(f('gen_'+z['id']+'_mw') for z in s['generators']);gamma=s['grid_cfe'][t];imp=gd+gc;ch=rc+gc;dis=dg+db;ex=f('excess_excluded_mw');recover=f('temporal_recover_mw');defer=f('temporal_defer_mw');c=g+dis-ch-ex+gamma*imp;physical=rl+dg+gamma*gd
   maxres=max(maxres,abs(load-rl-gd-dg-db),abs(g-rl-rc-ex),abs(sg-(1-b['loss_per_hour'])*prevG-dt*(b['eta_charge']*(rc+gamma*gc)-dg/b['eta_discharge'])),abs(sb-(1-b['loss_per_hour'])*prevB-dt*(b['eta_charge']*(1-gamma)*gc-db/b['eta_discharge'])),abs(load-s['load_mw'][t]-net.get((i,t),0)-recover+defer),abs(c-f('paper_cfe_credit_mwh')),abs(physical-f('physical_clean_served_mwh')),abs(g-f('local_generation_mw')),abs(dt-1),abs(f('grid_cfe')-gamma),abs(f('grid_price_per_mwh')-s['grid_price_per_mwh'][t]))
   allconstraints=max(allconstraints,max(0,(1-m['flexibility'])*s['load_mw'][t]-load,load-(1+m['flexibility'])*s['load_mw'][t],ch-a['battery_power_mw'],dis-a['battery_power_mw'],sg+sb-a['battery_energy_mwh'],imp-s['import_limit_mw']))
   for z in s['generators']:allconstraints=max(allconstraints,max(0,f('gen_'+z['id']+'_mw')-z['availability'][t]*caps[z['id']]));cpterms['generation']+=dt*f('gen_'+z['id']+'_mw')*z['marginal_per_mwh']
   cpterms['grid']+=dt*imp*s['grid_price_per_mwh'][t];cpterms['storage']+=dt*dis/b['eta_discharge']*b['discharge_cost_internal_per_mwh'];cpterms['shifts']+=dt*(defer+recover)*m['temporal_fee_per_mwh'];L+=dt*load;credit+=dt*c;clean+=dt*physical;gen+=dt*g;excess+=dt*ex;totalgap=max(totalgap,load-physical);prevG,prevB=sg,sb;dailydsm[t//24]=dailydsm.get(t//24,0)+dt*(recover-defer)
   assert datetime.datetime.fromisoformat(x['timestamp'])==datetime.datetime.fromisoformat(m['start'])+datetime.timedelta(hours=t)
   if m['matching']=='hourly_cfe_floor':allconstraints=max(allconstraints,m['target']*load-c)
  maxres=max(maxres,max(abs(x) for x in dailydsm.values()));scores[i]=dict(paper_score=credit/L,physical_clean=clean/L,annual_res=gen/L,actual_mwh=L);allconstraints=max(allconstraints,excess-m['max_excess_share']*sum(s['load_mw']))
  if m['matching']=='paper_cfe_score':allconstraints=max(allconstraints,m['target']*L-credit)
  if m['matching']=='annual_res_share':allconstraints=max(allconstraints,abs(gen-m['target']*L))
  if m['storage_boundary']=='cyclic':maxres=max(maxres,abs(prevG-float(period[0]['previous_green_soc_mwh'])),abs(prevB-float(period[0]['previous_brown_soc_mwh'])))
  for g in s['generators']:assert g['additional'] and g['region']==s['region']
 obj=capcost+sum(cpterms.values());error=obj-r['objective'];check(name+'_independent_export_recompute',maxres<1e-6 and allconstraints<1e-5 and abs(error)<.001,max_conservation_residual=maxres,max_constraint_violation=allconstraints,objective_recomputed=obj,objective_export=r['objective'],objective_error=error,max_hourly_unmatched_mwh=totalgap,scores=scores,capacity_cost=capcost,operating_costs=cpterms)
 return scores
# Thermal original browser ZIP, independent of new product accounting.
zpath=pathlib.Path('/home/box/Downloads/run_Phase4 RC_TES_heat-node-pipe conservation (SYNTHETIC)_a1b847074625.zip');z=zipfile.ZipFile(zpath);model=json.loads(z.read('scenario.json'));d=csvrows(z,'dispatch_optimized.csv');dt=model['dt_hours'];nodes=[]
for n in model['heat_network']['nodes']:
 prev=n['storage_soc0']*n['storage_mwh_th'];loss=0.
 for x in d:loss+=(1-(1-n['storage_loss_h'])**dt)*prev;prev=float(x['heat_node_'+n['id']+'_soc'])
 nodes.append(dict(node=n['id'],loss_mwh=loss,delta_mwh=prev-n['storage_soc0']*n['storage_mwh_th']))
source=sum(float(x['DC_hp_heat_MWth'])*dt for x in d);sent=sum(float(x['heat_pipe_0_MWth'])*dt for x in d);arrived=sum(float(x['heat_pipe_0_MWth'])*dt*.9 for x in d[:-4]);terminal=sum(float(x['heat_delivered_MWth'])*dt for x in d);receiving=next(n for n in nodes if n['node']=='load');balance=source-terminal-.1*sent-sum(n['loss_mwh']+n['delta_mwh'] for n in nodes)
check('original_browser_heat_boundary_root_cause',abs(terminal-11.5)<1e-8 and abs(arrived-terminal-receiving['loss_mwh']-receiving['delta_mwh'])<1e-8 and abs(balance)<1e-8,source_mwh=source,sent_mwh=sent,pipe_arrival_mwh=arrived,terminal_served_mwh=terminal,store_ledgers=nodes,global_residual_mwh=balance,classification='reasonable distinct boundary; real display-demand-series bug fixed separately; no change to11.5/revenue/objective')
# Fresh real daily frozen thermal + nonempty quarter-hour migration task are below in supplemental checker.
controls={}
controls['analytic_RES100_gap']=small(matching='annual_res_share',max_excess_share=1)
controls['analytic_CFE100_infeasible']=small()
x=small();x['sites'][0]['battery'].update(max_power_mw=2,max_energy_mwh=2);controls['analytic_CFE100_storage']=x
x=small(target=0);s=x['sites'][0];s['generators'][0]['availability']=[0,0];s.update(grid_price_per_mwh=[1,10],grid_cfe=[.5,.5]);s['battery'].update(max_power_mw=2,max_energy_mwh=2,capital_power_per_mw_year=.1,capital_energy_per_mwh_year=.1);controls['analytic_storage_origin']=x
controls['analytic_paperCFE50']=small(target=.5)
for name,x in controls.items():
 r=run(name,x,'infeasible' in name)
 if r:
  expected={'analytic_RES100_gap':4.,'analytic_CFE100_storage':4.,'analytic_storage_origin':2.2,'analytic_paperCFE50':3.}[name];check(name+'_independent_analytic_optimum',abs(r['res']['objective']-expected)<1e-7,expected=expected,actual=r['res']['objective'],evidence='two-slot algebraic lower bound plus constructive solution, SYNTHETIC NOT paper precision')
# Explicit invalid inputs; no silent year/calendar/provenance conversion.
for name,change in [('dt',{'dt_hours':.25}),('incomplete_year',{'horizon_mode':'year'}),('different_year',{'weather_year':2024})]:
 x=small();x.update(change);rejected('reject_'+name,'/api/opt-cfe/validate',x)
for field,value in [('region','foreign'),('additional',False)]:
 x=small();x['sites'][0]['generators'][0][field]=value;rejected('reject_'+field,'/api/opt-cfe/validate',x)
x=small();rejected('reject_daily_engine_annual','/api/sessions/phase5invalidkind/model/load',x)
for key in ([] if '--analytic-only' in sys.argv else ['riepin8760_f0','riepin8760_f40','riepin8760_f40_manuscript']):
 p=api('/api/opt-cfe/presets/'+key);m=p['model'];check(key+'_original_input_dimensions',len(m['sites'])==3 and all(len(s['load_mw'])==8760 and len(s['generators'])==2 for s in m['sites']) and m['source']['network_blob']=='e95dd9aba48f997b9ae27ca4df5123790b6f7a2e',sites=3,steps=8760,source_blob=m['source']['network_blob'],scope=m['source'].get('variant','published-effective'))
 run(key,m)
(O/'summary.json').write_text(json.dumps(dict(gates=len(checks),passed=sum(c['passed'] for c in checks),failed=[c for c in checks if not c['passed']],project=project['id'],tasks=tasks),ensure_ascii=False,indent=2));assert all(x['passed'] for x in checks)
