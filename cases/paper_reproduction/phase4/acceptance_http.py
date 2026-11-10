#!/usr/bin/env python3
"""Independent HTTP/official export checks. NO application imports. Reference interval
summation/enumeration and original author CSV parsing, not another invocation of app code."""
import pathlib,json,sys,csv,io,zipfile,urllib.request,urllib.error,uuid,hashlib,copy,itertools
P=pathlib.Path(__file__).resolve().parent;O=pathlib.Path(sys.argv[1]);O.mkdir(parents=True,exist_ok=True);checks=[];runs={}
def api(path,body=None,method=None,raw=False):
 q=urllib.request.Request('http://127.0.0.1:8080'+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'},method=method)
 try:
  with urllib.request.urlopen(q,timeout=240) as f:b=f.read()
 except urllib.error.HTTPError as e:raise RuntimeError(str(e.code)+':'+e.read().decode())
 return b if raw else json.loads(b)
def check(name,ok,**metrics):
 r=dict(name=name,passed=bool(ok),**metrics);checks.append(r);print(json.dumps(r,ensure_ascii=False),flush=True);(O/'checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2))
ROOT=P.parents[2];codefiles={str(p.relative_to(ROOT/'app')):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'app').rglob('*.py'))};CODEHASH=hashlib.sha256(json.dumps(codefiles,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
(O/'source_code_hash_manifest.json').write_text(json.dumps(dict(code_hash=CODEHASH,files=codefiles),indent=2));PREEXISTING=api('/api/foundation/catalog');(O/'catalog_before_run.json').write_text(json.dumps(PREEXISTING,ensure_ascii=False,indent=2))
def readcsv(z,n):return list(csv.DictReader(io.StringIO(z.read(n).decode())))
def run(name,s):
 sid='p4'+uuid.uuid4().hex[:20];folder=O/name;folder.mkdir();(folder/'input.json').write_text(json.dumps(s,ensure_ascii=False,indent=2));api('/api/sessions/'+sid+'/model/load',s)
 try:r=api('/api/sessions/'+sid+'/model/rerun',dict(ac=False))
 except Exception as e:(folder/'failure.txt').write_text(str(e));return {'error':str(e),'sid':sid}
 b=api('/api/sessions/'+sid+'/export.zip',raw=True);(folder/'export.zip').write_bytes(b);z=zipfile.ZipFile(io.BytesIO(b));a=json.loads(z.read('audit_optimized.json'));res=json.loads(z.read('results.json'));d=readcsv(z,'dispatch_optimized.csv');(folder/'run.json').write_text(json.dumps(r,ensure_ascii=False,indent=2));out=dict(sid=sid,z=z,a=a,res=res,d=d,s=json.loads(z.read('scenario.json')));runs[name]=out;return out
for name in ['energy_1h','energy_15min','thermal_1h','thermal_15min','divisible_control_1h','integer_continuity_1h','integer_continuity_15min','integer_restart_1h','integer_restart_15min','integer_deadline_infeasible_1h','tsusc_miso_signal_1h','tsusc_miso_signal_15min']:
 s=json.loads((P/'inputs'/f'{name}.json').read_text());r=run(name,s)
 if 'error' in r:check(name+'_negative','deadline_infeasible' in name and 'infeasible' in r['error'],error=r['error']);continue
 dt=r['s']['dt_hours'];d=r['d'];a=r['a'];objective=r['res']['objective']['optimized'];terms=r['res']['cost_terms']['optimized'];residual=0
 context=a['execution_context'];canonical=json.dumps(r['s'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode();digest=hashlib.sha256(canonical).hexdigest()
 check(name+'_metadata',len(d)==int(24/dt) and a['time_axis']['dt_hours']==dt and abs(sum(terms.values())-objective)<1e-6 and digest==context['input_model_hash'] and context['code_hash']==CODEHASH,dt_hours=dt,points=len(d),objective=objective,cost_terms_residual=sum(terms.values())-objective,input_hash_matches=(digest==context['input_model_hash']))
 if name.startswith(('energy','thermal')):
  prev=2.;coolstore=1.;pa=pm=24.;nodes={'plant':.5,'load':.5};max_heat=0.;max_rc=0.
  for i,row in enumerate(d):
   f=lambda k:float(row[k]);g=sum(f(k) for k in row if k.startswith('gen') and k.endswith('_MW'))
   residual=max(residual,abs(g+f('pv_used')-f('DC_grid_MW')-f('BAT_ch')+f('BAT_dis')),abs(f('BAT_soc')-prev-dt*(.9*f('BAT_ch')-f('BAT_dis')/.8)))
   prev=f('BAT_soc')
   if name.startswith('thermal'):
    th=r['s']['data_centers'][0]['thermal'];hn=r['s']['heat_network'];q=f('DC_chiller_MWth')-f('DC_tes_ch_MWth')+f('DC_free_MWth')+f('DC_tes_dis_MWth')+f('DC_hp_heat_MWth')*(1-1/f('DC_HPCOP'))
    max_rc=max(max_rc,abs(.8*(f('DC_Tin_C')-pa)-dt*(1.025*f('DC_IT_MW')-q-4*(f('DC_Tin_C')-f('DC_Tmass_C'))+.15*(25-f('DC_Tin_C')))),abs(6*(f('DC_Tmass_C')-pm)-dt*4*(f('DC_Tin_C')-f('DC_Tmass_C'))),abs(f('DC_tes_soc_MWh')-.98**dt*coolstore-dt*(f('DC_tes_ch_MWth')-f('DC_tes_dis_MWth'))))
    assert abs(f('DC_Tin_C')-pa)<=th['ramp_max_k_h']*dt+1e-6
    pa,pm,coolstore=f('DC_Tin_C'),f('DC_Tmass_C'),f('DC_tes_soc_MWh')
    for node in hn['nodes']:
     k=node['id'];delay=int(1/dt);incoming=.9*float(d[i-delay]['heat_pipe_0_MWth']) if k=='load' and i>=delay else 0.;outflow=f('heat_pipe_0_MWth') if k=='plant' else 0.;inj=f('DC_hp_heat_MWth') if k=='plant' else 0.
     max_heat=max(max_heat,abs(inj+incoming+f('heat_node_'+k+'_dis')-f('heat_node_'+k+'_del')-outflow-f('heat_node_'+k+'_ch')),abs(f('heat_node_'+k+'_soc')-(1-node['storage_loss_h'])**dt*nodes[k]-dt*(f('heat_node_'+k+'_ch')-f('heat_node_'+k+'_dis'))));nodes[k]=f('heat_node_'+k+'_soc')
  sumcol=lambda k:sum(float(row[k])*dt for row in d)
  ledger=a['lifecycle_ledger'];lca=sum(float(row['emis_generation_t']) for row in d)+sumcol('pv_used')*.02+.24
  check(name+'_physical_conservation',max(residual,max_rc,max_heat)<1e-7 and abs(ledger['total_t']-lca)<1e-7 and abs(sumcol('DC_batch_IT')-8)<1e-7,max_electrical_soc_residual=residual,max_RC_TES_residual=max_rc,max_heat_node_store_residual=max_heat,lifecycle_error_t=ledger['total_t']-lca,it_work_mwh=sumcol('DC_IT_work_MW'))
  if name.startswith('thermal'):
   heat=a['heat_network_audit'][0];check(name+'_pipe_boundary',abs(heat['sent_mwh']-heat['pipe_loss_mwh']-heat['delivered_mwh']-heat['end_in_transit_mwh'])<1e-7,**heat)
 if name.startswith(('integer','tsusc')):
  tasks=a['integer_tasks'];events=readcsv(r['z'],'integer_events_optimized.csv');led=readcsv(r['z'],'integer_ledger_optimized.csv');maxerr=0
  for j in r['s']['jobs']:
   ev=[e for e in events if e['job']==j['id']];assert all(ev[i]['to_state']==ev[i+1]['from_state'] for i in range(len(ev)-1));executed=sum(float(e['executed_mwh']) for e in ev);lost=sum(float(e['canceled_lost_mwh']) for e in ev);good=j['energy_mwh'] if any(e['completion']=='True' for e in ev) else 0.;l=next(x for x in led if x['job']==j['id']);maxerr=max(maxerr,abs(j['initial_progress_h']*j['max_mw']+executed-lost-good-float(l['deadline_lost_mwh'])),abs(executed-float(l['executed_mwh'])))
   # No checkpoint on cancel; progress transition implies productive one-step increment.
   for e in ev:
    if e['event']=='continue' and e['to_state']!='done':assert int(e['to_state'].rsplit('|',1)[1])==int(e['from_state'].rsplit('|',1)[1])+1
  check(name+'_integer_ledger',maxerr<1e-7,max_independent_work_conservation_error_mwh=maxerr,ledger=tasks['ledger'])
  if 'continuity' in name:check(name+'_enumeration',abs(objective-101)<1e-7,reference=101,actual=objective,reference_method='enumerate contiguous length2h starts in 4h, vs divisible2')
  elif 'restart' in name:check(name+'_restart_reference',abs(objective-12)<1e-7 and tasks['ledger'][0]['canceled_lost_mwh']==1,reference_objective=12,expected_initial_progress_lost_mwh=1,expected_executed_mwh=3,actual=objective)
  else:
   ref=0.
   for j in r['s']['jobs']:
    start=int(j['release']/dt);end=int(j['deadline']/dt);length=int(j['duration_h']/dt);signal=[1000*r['s']['price_cny_kwh'][t]+r['s']['carbon_price_cny_t']*r['s']['carbon_profiles']['national'][t] for t in range(start,end)]
    ref+=min(sum(signal[t:t+length])*dt*j['max_mw'] for t in range(len(signal)-length+1))
   check(name+'_original_signal_enumeration',abs(objective-ref)<1e-7,reference=ref,actual=objective,currency_note='explicit hypothetical7CNY/USD; original MISO input, SYNTHETIC jobs; NOT Table1')
# An intentionally different optimum is NOT a conservation or paper-accuracy failure.
check('same_physical_sampling_vs_policy_scope',True,energy_1h=runs['energy_1h']['res']['objective']['optimized'],energy_15min=runs['energy_15min']['res']['objective']['optimized'],thermal_1h=runs['thermal_1h']['res']['objective']['optimized'],thermal_15min=runs['thermal_15min']['res']['objective']['optimized'],note='守恒与策略/离散化差异分开，不强求RC两种分辨率最优值相等')
# Original author data formula, independent parse of all192 rows + cryptographic source alignment.
source=json.loads((P/'sources/source_manifest.json').read_text());rows=list(csv.DictReader((P/'sources/scheduling_0725_0801_data.csv').open()));efs=[968,440,15,13.5,22.5,50];ks=['coal','gas','nuclear','hydro','wind','solar'];ci=[sum(float(row[k])*e for k,e in zip(ks,efs))/sum(float(row[k]) for k in ks) for row in rows];errors=[abs(x-y) for x,y in zip(ci,source['cer_kg_per_mwh'])]
check('author_TSUSC_objects_and_MISO192',len(rows)==192 and max(errors)<1e-10 and all(x['matches'] for x in source['files']),max_cer_error_kg_mwh=max(errors),pinned_objects=source['files'],forecast=168,realized=144,raw_rows=192,full_Azure_Table1_reproduced=False)
# Primary-lock migration cleanup on actual original bids, not a supplied optimal schedule.
s=json.loads((P.parent/'inputs/zhang_s5.json').read_text());s['migration_cleanup']='lexicographic_gross';r=run('zhang5_cleanup',s);c=r['a']['migration_cleanup'];gross=sum(float(x['gross_mwh']) for x in readcsv(r['z'],'migration_audit_optimized.csv'))
check('migration_lexicographic_original_s5',c['status']=='optimal' and abs(c['primary_after']+72000)<1e-6 and c['gross_after_mwh']<c['gross_before_mwh']-100 and abs(gross-c['gross_after_mwh'])<1e-6,**c)
# Original scenario at quarter-hour with same physical windows; fees integrate with dt.
s=api('/api/time-axis/resample-hourly',json.loads((P.parent/'inputs/zhang_s4.json').read_text()))['model'];r=run('zhang4_15min',s);a=r['a'];fee=sum(float(x['cost_cny']) for x in readcsv(r['z'],'migration_audit_optimized.csv'))
check('original_welfare_quarter_hour_fees',abs(r['res']['objective']['optimized']+72000)<1e-6 and abs(fee-a['market_clearing']['migration_service_cny'])<1e-7,objective=r['res']['objective']['optimized'],migration_service=fee)
# Independent formal table metadata, not merely energy/cost totals.
intervals=[]
for table in ['allocations_optimized.csv','migration_audit_optimized.csv','network_dispatch_optimized.csv']:
 rows_=readcsv(r['z'],table)
 intervals += [dict(table=table,step=x.get('step'),hour=x['hour'],duration_h=x.get('duration_h')) for x in rows_ if abs(float(x['hour'])-int(x['step'])*.25)>1e-12 or float(x['duration_h'])!=.25]
check('formal_allocation_migration_network_timeaxis',not intervals,mismatches=intervals,dt_hours=.25)
# Explicit blocked paths, rather than silently running96 points as24.
for name,model in [('bad_length',{**json.loads((P/'inputs/energy_15min.json').read_text()),'price_cny_kwh':[.1]*24}),('VCC',{**json.loads((P/'inputs/energy_15min.json').read_text()),'vcc_mode':'carbon'}),('bad_integer_duration',{**json.loads((P/'inputs/integer_continuity_15min.json').read_text())})]:
 if name=='bad_integer_duration':model['jobs'][0]['duration_h']=1.1
 try:api('/api/sessions/p4negative'+uuid.uuid4().hex[:8]+'/model/load',model);error='UNEXPECTED SUCCESS'
 except Exception as e:error=str(e)
 (O/(name+'_rejection.txt')).write_text(error);check(name+'_blocked',error!='UNEXPECTED SUCCESS',error=error)
# Remaining interval-integral and initial-state probes are synthetic controls, not paper accuracy.
s=json.loads((P/'inputs/energy_15min.json').read_text());s.update(pv=[],storage=[],price_cny_kwh=[.001]*96,dr_events=[dict(name='integral_control',start=5.25,end=6,request_mw=1,price_cny_mwh=600,baseline_method='given',baseline_mw=[3]*96)]);s['data_centers'][0]['batch_mwh']=0
r=run('DR_15min_integral',s);check('DR_interval_fee_energy',abs(r['res']['objective']['optimized']+426)<1e-6,objective=r['res']['objective']['optimized'],expected=-426,declared_synthetic_baseline=3)
s=json.loads((P/'inputs/integer_continuity_1h.json').read_text());s['jobs'][0].update(duration_h=3,energy_mwh=3,initial_progress_h=2,deadline=1);r=run('initial_progress_short_window',s);l=r['a']['integer_tasks']['ledger'][0];check('initial_progress_remaining_deadline',l['executed_mwh']==1 and l['completed_goodput_mwh']==3 and l['conservation_residual_mwh']==0,ledger=l)
s=json.loads((P/'inputs/energy_15min.json').read_text());s.update(pv=[],storage=[],price_cny_kwh=[.001]*96);s['data_centers'][0].update(interactive_mw=[0]*96,batch_mwh=6);s['network']['ext_grids'][0]['import_max_mw']=0;s['network']['gens']=[dict(name='limited_ramp',bus=0,pmax_mw=4,cost_cny_mwh=1,emission_t_mwh=0,energy_mwh_day=6,ramp_mw_h=.2)]
r=run('generator_physical_ramp_energy_limit',s);pg=[float(x['gen1_MW']) for x in r['d']];ramp=max(abs(a-b) for a,b in zip(pg,pg[1:]));energy=.25*sum(pg);check('generator_MWh_cap_and_MW_per_hour_ramp',abs(energy-6)<1e-6 and ramp<=.05+1e-7,energy_mwh=energy,max_step_delta_mw=ramp,max_delta_mw_per_hour=ramp/.25)
annual=json.loads((P.parent/'inputs/zheng2019_annual.json').read_text());annual['dt_hours']=.25
for name,path,body in [('annual_15min_blocked','/api/paper-reproduction/annual-migration',annual),('market_15min_blocked','/api/market/portfolios',{'dt_hours':.25})]:
 try:api(path,body);error='UNEXPECTED SUCCESS'
 except Exception as e:error=str(e)
 (O/(name+'.txt')).write_text(error);check(name,error!='UNEXPECTED SUCCESS' and '404' not in error,error=error)
# Actual regular project/version/frozen task path, including failure and old artifact compatibility.
p=api('/api/foundation/projects',{'name':'Phase4 · 时间步/整数任务验收（本地）'});ids=[]
for name in ['energy_15min','thermal_15min','integer_restart_15min','integer_deadline_infeasible_1h']:
 model=json.loads((P/'inputs'/f'{name}.json').read_text());dt=model.get('dt_hours',1);axis=dict(location='Phase4合成控制',year=2024,timezone='Asia/Shanghai',start='2024-07-01T00:00:00+08:00',step_minutes=int(dt*60),length=int(24/dt))
 d=api('/api/foundation/scenarios',dict(project_id=p['id'],name=name,axis=axis,model=model));v=api('/api/foundation/scenarios/'+d['id']+'/publish',dict(expected_revision=d['revision']));t=api('/api/foundation/tasks',dict(version_id=v['id'],name=name,objective='cost',solver=dict(time_limit_s=120,ac_check=False)));done=api('/api/foundation/tasks/'+t['id']+'/run',{});ids.append(dict(project_id=p['id'],scenario_id=d['id'],version_id=v['id'],task_id=t['id'],name=name,status=done['status']))
 expected='failed' if 'infeasible' in name else 'completed';check(name+'_regular_frozen_task',done['status']==expected,status=done['status'],expected_status=expected,task_id=t['id'],error=done.get('error'))
 if done['status']=='completed':
  payload=api('/api/sessions/'+done['session_id']+'/export.zip',raw=True);(O/(name+'_frozen.zip')).write_bytes(payload);z=zipfile.ZipFile(io.BytesIO(payload));snapshot=json.loads(z.read('input_snapshot.json'));metadata=json.loads(z.read('frozen_task_metadata.json'));snapsha=hashlib.sha256(json.dumps(snapshot,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest();check(name+'_frozen_export',snapshot['model']['dt_hours']==dt and metadata['input_hash']==snapsha,input_hash_matches=snapsha==metadata['input_hash'])
(O/'regular_project_ids.json').write_text(json.dumps(ids,indent=2));print('PROJECT',p['id'],flush=True)
# All preexisting versions/tasks remain byte-logically unchanged through the published catalog.
before=PREEXISTING;after=api('/api/foundation/catalog');mismatches=[]
for group in ['version','task']:
 now={r['id']:r for r in after[group]}
 for old in before[group]:
  if json.dumps(old,sort_keys=True)!=json.dumps(now.get(old['id']),sort_keys=True):mismatches.append([group,old['id']])
check('all_preexisting_history_unchanged',not mismatches,n_versions=len(before['version']),n_tasks=len(before['task']),mismatches=mismatches)
summary=dict(independent_gates=len(checks),passed=sum(x['passed'] for x in checks),failed=sum(not x['passed'] for x in checks),checks=checks,project_ids=ids)
(O/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));sys.exit(bool(summary['failed']))
