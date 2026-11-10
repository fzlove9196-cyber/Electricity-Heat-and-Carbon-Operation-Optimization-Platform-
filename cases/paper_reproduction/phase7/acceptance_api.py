"""Normal public HTTP API acceptance, frozen ZIP independently re-audited; no product imports."""
import json,sys,copy,hashlib,urllib.request,urllib.error,zipfile
from pathlib import Path
from independent_reference import reference,audit,load_zip,enumerate_small
E=Path(sys.argv[1]);E.mkdir(exist_ok=True);R=Path(__file__).resolve().parent;BASE='http://127.0.0.1:8080/api/foundation'
def api(path,body=None,method=None):
 req=urllib.request.Request(BASE+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'},method=method)
 with urllib.request.urlopen(req,timeout=240) as r:return json.load(r)
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
old=['da4c5d48e4344406','0ca2cc19587e460c','2e8c374986114082','ebd6070fb6354d81','a925fe9191494430','ddebda1c1c75427b'];before={}
for k in old:
 try:before[k]=digest(api('/tasks/'+k))
 except urllib.error.HTTPError as e:
  if e.code!=404:raise
old=list(before);(E/'phase5_6_hashes_before.json').write_text(json.dumps(before,indent=2))
prior=json.loads((E/'api_acceptance_index.json').read_text()) if (E/'api_acceptance_index.json').exists() else None
p={'id':prior['project_id']} if prior else api('/projects',{'name':'Phase7 GPU discrete caps throughput SLA (public counterfactual + SYNTHETIC controls)'});index={'project_id':p['id'],'entries':[]};gates=[]
existing={v['key']:v for v in prior['entries']} if prior else {}
def gate(name,**evidence):gates.append(dict(name=name,passed=True,**evidence));(E/'independent_gates.json').write_text(json.dumps(gates,indent=2))
for key in ['synthetic_energy','synthetic_pause','synthetic_fair','synthetic_energy_15min','emerald_calibration','emerald_heldout','emerald_fair','emerald_headroom','emerald_calibration_15min','expected_deadline_failure','expected_heldout_failure']:
 base='synthetic_energy' if key in ('synthetic_energy_15min','expected_heldout_failure') else 'synthetic_pause' if key=='expected_deadline_failure' else 'emerald_calibration' if key=='emerald_calibration_15min' else key;m=json.loads((R/(base+'.json')).read_text());m.setdefault('start','2025-05-03T07:00:00+08:00');m.setdefault('policy','energy_cost');m.setdefault('lex_tolerance',1e-7);m['name']=key+' · '+m['name']
 if key.endswith('_15min'):
  m['dt_hours']=.25;m['n_steps']*=4
  for k in ['price_usd_kwh','power_limit_kw']:m[k]=[v for v in m[k] for _ in range(4)]
  for j in m['jobs']:j['baseline_rate']=[v for v in j['baseline_rate'] for _ in range(4)]
 if key=='expected_deadline_failure':m['jobs'][0]['deadline_h']=2
 if key=='expected_heldout_failure':
  for a in m['jobs'][0]['actions']:a['validation_normalized_rate']=a['normalized_rate']*.5
 axis=dict(location='GPU isolated, NOT whole DC',year=2025,timezone='Asia/Shanghai',start=m['start'],step_minutes=m['dt_hours']*60,length=m['n_steps'])
 if key in existing:
  v={'id':existing[key]['version']};sc=api('/scenarios/'+existing[key]['scenario']);t=api('/tasks/'+existing[key]['task'])
 else:
  sc=api('/scenarios',dict(project_id=p['id'],name=key,axis=axis,model=m));valid=api('/scenarios/'+sc['id']+'/validate',{});assert valid.get('ok'),valid;v=api('/scenarios/'+sc['id']+'/publish',{'expected_revision':sc['revision']});t=api('/tasks',{'version_id':v['id'],'name':key,'solver':{'ac_check':False,'time_limit_s':90}});t=api('/tasks/'+t['id']+'/run',{})
 failed=key.startswith('expected_');assert t['status']==('failed' if failed else 'completed'),(key,t.get('error'));zpath=E/(key+'.zip');zpath.write_bytes(urllib.request.urlopen(BASE+'/tasks/'+t['id']+'/export.zip',timeout=60).read());entry=dict(key=key,scenario=sc['id'],version=v['id'],task=t['id'],status=t['status'],zip_file=str(zpath),input_sha256=digest(t['snapshot']),zip_sha256=hashlib.sha256(zpath.read_bytes()).hexdigest());index['entries'].append(entry);(E/'api_acceptance_index.json').write_text(json.dumps(index,indent=2));print(key,t['id'],t['status'],flush=True)
 if failed:
  with zipfile.ZipFile(zpath) as z:assert 'results.json' not in z.namelist()
  if key=='expected_deadline_failure':assert 'infeasible' in t['error'];gate(key,error=t['error'])
  else:
   mm,rr=load_zip(zpath);aa=audit(mm,rr);assert not rr['validation_accepted'] and rr['validation_unfinished_work_h']==1;gate(key,audit=aa,accepted=False)
  continue
 mm,rr=load_zip(zpath);aa=audit(mm,rr);ref=reference(mm);delta=abs(ref['cost_usd']-rr['objective_value']);assert delta<1e-4,(key,delta,ref,rr['objective_value']);entry.update(objective=rr['objective_value'],reference_energy=rr['reference_energy_kwh'],work=rr['completed_work_h'],validation_unfinished=rr['validation_unfinished_work_h'],validation_accepted=rr['validation_accepted']);gate(key,independent_MILP=ref,cost_error_usd=delta,audit=aa)
 if key.startswith('synthetic') and not key.endswith('15min'):
  ee=enumerate_small(mm);assert abs(ee['cost_usd']-rr['objective_value'])<1e-6;gate(key+'_enumeration',**ee)
 opened=api('/tasks/'+t['id']+'/open',{});assert opened['model_kind']=='opt_gpu' and not opened.get('session_id')
 if key=='synthetic_energy':
  original=digest(api('/tasks/'+t['id']));snap=copy.deepcopy(t['snapshot']);draft=api('/scenarios/'+sc['id']);newm=copy.deepcopy(draft['draft']);newm['model']['price_usd_kwh']=[2]*m['n_steps'];api('/scenarios/'+sc['id']+'/draft',{'expected_revision':draft['revision'],**newm},'PATCH');assert api('/scenarios/'+sc['id'])['draft']['model']['price_usd_kwh']==[2]*m['n_steps'];again=api('/tasks/'+t['id']);assert again['snapshot']==snap;rer=api('/tasks/'+t['id']+'/rerun',{});rer=api('/tasks/'+rer['id']+'/run',{});assert rer['status']=='completed' and rer['snapshot']==snap and rer['full_result']['objective_value']==rr['objective_value'];assert digest(api('/tasks/'+t['id']))==original;index['frozen_rerun_task']=rer['id'];gate('frozen_history_and_rerun_not_edited_draft',rerun=rer['id'],original_hash=original)
(E/'api_acceptance_index.json').write_text(json.dumps(index,indent=2));after={k:digest(api('/tasks/'+k)) for k in old};assert before==after;(E/'phase5_6_history_preserved.json').write_text(json.dumps(dict(before=before,after=after,passed=True),indent=2));
if old:gate('phase5_6_full_frozen_task_hashes_preserved',count=len(old))
else:index['legacy_history']='NOT_APPLICABLE: original box records absent; no restoration claimed';(E/'api_acceptance_index.json').write_text(json.dumps(index,indent=2))
print('independent gates',len(gates),flush=True)
