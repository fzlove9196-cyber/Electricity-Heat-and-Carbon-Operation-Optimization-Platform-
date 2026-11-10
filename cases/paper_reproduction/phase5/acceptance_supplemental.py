"""Extra real HTTP gates: corrected kind negative, new heat ledger, nonempty dt migration,
annual rerun/failure/history compatibility. No product imports.
"""
import json,sys,pathlib,urllib.request,urllib.error,zipfile,io,csv,copy,hashlib,uuid
O=pathlib.Path(sys.argv[1]);P=pathlib.Path(__file__).resolve().parent;g=[]
def api(p,b=None,raw=False,method=None):
 q=urllib.request.Request('http://127.0.0.1:8080'+p,data=None if b is None else json.dumps(b).encode(),headers={'Content-Type':'application/json'},method=method)
 with urllib.request.urlopen(q,timeout=1000) as f:r=f.read()
 return r if raw else json.loads(r)
def check(name,ok,**kw):
 d=dict(name=name,passed=bool(ok),**kw);g.append(d);print(json.dumps(d,ensure_ascii=False),flush=True);(O/'supplemental_checks.json').write_text(json.dumps(g,ensure_ascii=False,indent=2))
def csvrows(z,n):return list(csv.DictReader(io.StringIO(z.read(n).decode())))
base=O/'independent_http';project=json.loads((base/'ui_project.json').read_text())['id'];entries=json.loads((base/'ui_tasks.json').read_text());extra={}
# Correct legal session ID: ensure 400 came from model-kind guard, not ID format.
m=json.loads((base/'analytic_CFE100_storage/input.json').read_text())
try:api('/api/sessions/phase5invalidkind/model/load',m);check('reject_daily_engine_annual',False)
except urllib.error.HTTPError as e:
 text=e.read().decode();check('reject_daily_engine_annual',e.code==400 and '24h' in text,error=text)
 before=json.loads((base/'checks.json').read_text());(O/'first_http_checks_before_session_harness_correction.json').write_text(json.dumps(before,ensure_ascii=False,indent=2))
 for row in before:
  if row['name']=='reject_daily_engine_annual':row.update(passed=(e.code==400 and '24h' in text),error=text,harness_verification='legal session ID confirms model-kind400 contains24h guard; initial Phase5A hyphen-ID harness failure retained separately')
 (base/'checks.json').write_text(json.dumps(before,ensure_ascii=False,indent=2))
# Same immutable annual snapshot, actually run again rather than just queue a rerun.
t=api('/api/foundation/tasks/'+entries['analytic_CFE100_storage']['task']);rr=api('/api/foundation/tasks/'+t['id']+'/rerun',{});r=api('/api/foundation/tasks/'+rr['id']+'/run',{});check('annual_actual_frozen_rerun',r['status']=='completed' and r['snapshot']==t['snapshot'] and r['input_hash']==t['input_hash'] and abs(r['full_result']['objective']-4)<1e-8,new_task=rr['id'],original_task=t['id'],input_hash=t['input_hash']);extra['annual_rerun']=dict(task=rr['id'],project=project)
failed=api('/api/foundation/tasks/'+entries['analytic_CFE100_infeasible']['task']);b=api('/api/foundation/tasks/'+failed['id']+'/export.zip',raw=True);(O/'annual_failed_frozen_export.zip').write_bytes(b);z=zipfile.ZipFile(io.BytesIO(b));check('annual_failed_export_not_success',failed['status']=='failed' and 'infeasible' in failed['error'] and 'hourly.csv' not in z.namelist() and json.loads(z.read('task_metadata.json'))['status']=='failed',task=failed['id'])
# Unsupported daily binding, AC and objectives rejected before modifying a draft/job.
for name,path,body,required in [
 ('annual_AC_reject','/api/foundation/tasks',dict(version_id=entries['analytic_CFE100_storage']['version'],solver=dict(ac_check=True)),'AC'),
 ('annual_daily_objective_reject','/api/foundation/tasks',dict(version_id=entries['analytic_CFE100_storage']['version'],objective='welfare',solver=dict(ac_check=False)),'年度CFE')]:
 try:api(path,body);check(name,False)
 except urllib.error.HTTPError as e:text=e.read().decode();check(name,e.code==400 and required in text,error=text)
# Normal-project daily frozen runs, no user history altered.
for name,raw in [('thermal_boundary_15min',json.loads((P.parent/'phase4/inputs/thermal_15min.json').read_text())),('migration_s5_15min',json.loads((P.parent/'inputs/zhang_s5.json').read_text()))]:
 if name.startswith('migration'):
  raw=api('/api/time-axis/resample-hourly',raw)['model'];raw['migration_cleanup']='lexicographic_gross'
 raw['name']='Phase5 '+name+' (original parameters; explicit resolution control)';axis=dict(location='SYNTHETIC heat control' if name.startswith('thermal') else 'Zhang original3node, explicit15min resampling',year=2024,timezone='Asia/Shanghai',start='2024-07-01T00:00:00+08:00',step_minutes=15,length=96)
 d=api('/api/foundation/scenarios',dict(project_id=project,name=name,model=raw,axis=axis));v=api('/api/foundation/scenarios/'+d['id']+'/publish',dict(expected_revision=1));t=api('/api/foundation/tasks',dict(name=name,version_id=v['id'],objective='welfare' if name.startswith('migration') else 'cost',solver=dict(ac_check=False,time_limit_s=120)));r=api('/api/foundation/tasks/'+t['id']+'/run',{});assert r['status']=='completed',r.get('error');op=api('/api/foundation/tasks/'+t['id']+'/open',{});sid=op['session_id'];b=api('/api/sessions/'+sid+'/export.zip',raw=True);(O/(name+'_frozen.zip')).write_bytes(b);z=zipfile.ZipFile(io.BytesIO(b));model=json.loads(z.read('scenario.json'));a=json.loads(z.read('audit_optimized.json'));res=json.loads(z.read('results.json'));df=csvrows(z,'dispatch_optimized.csv');extra[name]=dict(project=project,scenario=d['id'],version=v['id'],version_hash=v['hash'],task=t['id'],input_hash=t['input_hash'],session_id=sid)
 if name.startswith('thermal'):
  hb=a['heat_boundary_audit'];dt=.25;losses={};deltas={}
  for n in model['heat_network']['nodes']:
   prev=n['storage_soc0']*n['storage_mwh_th'];loss=0.
   for row in df:loss+=(1-(1-n['storage_loss_h'])**dt)*prev;prev=float(row['heat_node_'+n['id']+'_soc'])
   losses[n['id']]=loss;deltas[n['id']]=prev-n['storage_soc0']*n['storage_mwh_th']
  source=dt*sum(float(row['DC_hp_heat_MWth']) for row in df);sent=dt*sum(float(row['heat_pipe_0_MWth']) for row in df);arrival=.9*dt*sum(float(row['heat_pipe_0_MWth']) for row in df[:-4]);terminal=dt*sum(float(row['heat_delivered_MWth']) for row in df);demand=dt*sum(float(row['heat_demand_MWth']) for row in df);residual=source-terminal-.1*sent-sum(losses.values())-sum(deltas.values());check('fresh_heat_boundaries_and_actual_demand_series',abs(terminal-11.5)<1e-7 and abs(demand-11.5)<1e-7 and abs(arrival-terminal-losses['load']-deltas['load'])<1e-7 and abs(residual)<1e-7 and res['heat_boundaries']['optimized']==hb and 'heat_nodes_optimized.csv' in z.namelist(),source_mwh=source,pipe_arrival_mwh=arrival,terminal_mwh=terminal,demand_display_integral_mwh=demand,node_storage_loss_mwh=losses,residual_mwh=residual,objective=res['objective']['optimized'],task=t['id'])
 else:
  alloc=csvrows(z,'allocations_optimized.csv');mig=csvrows(z,'migration_audit_optimized.csv');net=csvrows(z,'network_dispatch_optimized.csv');error=0.;count=0;welfare=0.
  for k,row in enumerate(df):
   aa=[x for x in alloc if int(x['step'])==k];utility=sum(float(x['energy_mwh'])*float(x['value_cny_mwh']) for x in aa);fuel=.25*sum(float(row['gen'+str(j)+'_MW'])*c for j,c in zip([1,2,3],[10,20,10]));flow=json.loads(net[k]['flow_mw']);fee=.25*2*sum(abs(x) for x in flow);mcost=0.
   for link in model['links']:
    fw=sum(float(x['energy_mwh']) for x in aa if x['origin']==link['a'] and x['destination']==link['b']);bw=sum(float(x['energy_mwh']) for x in aa if x['origin']==link['b'] and x['destination']==link['a']);ma=next(x for x in mig if int(x['step'])==k and x['src']==link['a'] and x['dst']==link['b']);error=max(error,abs(float(ma['forward_mwh'])-fw),abs(float(ma['reverse_mwh'])-bw),abs(float(ma['gross_mwh'])-fw-bw),abs(float(ma['signed_net_mwh'])-fw+bw),max(0,fw/.25-link['bw_mw'],bw/.25-link['bw_mw']));mcost+=abs(fw-bw)*link['fee_cny_mwh'];count+=fw+bw>1e-8
   welfare+=utility-fuel-fee-mcost
  for table in [alloc,mig,net]:
   for row in table:error=max(error,abs(float(row['hour'])-.25*int(row['step'])),abs(float(row['duration_h'])-.25))
  gross=sum(float(x['gross_mwh']) for x in mig);check('nonempty_quarter_migration_allocations_independent',count>0 and error<1e-7 and abs(welfare-72000)<1e-5 and abs(gross-240)<1e-6,max_audit_residual=error,positive_migration_slots=count,allocations=len(alloc),migration_rows=len(mig),gross_mwh=gross,welfare_recomputed=welfare,objective=res['objective']['optimized'],cleanup=a['migration_cleanup'],task=t['id'])
(O/'ui_supplemental_tasks.json').write_text(json.dumps(extra,ensure_ascii=False,indent=2))
(O/'supplemental_summary.json').write_text(json.dumps(dict(gates=len(g),passed=sum(x['passed'] for x in g),failed=[x for x in g if not x['passed']]),ensure_ascii=False,indent=2));assert all(x['passed'] for x in g)
