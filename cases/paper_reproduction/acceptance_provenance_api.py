#!/usr/bin/env python3
"""Additional independent API checks for mode boundaries, frozen history and file hashes.
Run after acceptance_api.py finishes to avoid concurrent solver calls.
"""
import pathlib,json,urllib.request,urllib.error,uuid,hashlib,io,zipfile,csv,copy,sys
P=pathlib.Path(__file__).resolve().parent;ROOT=P.parents[1];O=pathlib.Path(sys.argv[1] if len(sys.argv)>1 else '/workspace/sim-agent-change-evidence/independent_final_v2');BASE='http://127.0.0.1:8080';checks=[]
def api(path,body=None,raw=False):
 q=urllib.request.Request(BASE+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
 try:
  with urllib.request.urlopen(q,timeout=180) as f:b=f.read()
 except urllib.error.HTTPError as e:raise RuntimeError(str(e.code)+':'+e.read().decode()) from e
 return b if raw else json.loads(b)
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()).hexdigest()
def check(name,ok,**kw):
 d=dict(name=name,passed=bool(ok),**kw);checks.append(d);print(json.dumps(d,ensure_ascii=False),flush=True);(O/'extra_checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2))
def export(sid):return zipfile.ZipFile(io.BytesIO(api(f'/api/sessions/{sid}/export.zip',raw=True)))
s=json.loads((P/'inputs/zhang_s1.json').read_text());s.update(name='D01_fixed_injection_domain_probe_NOT_strategy',objective_mode='cost',jobs=[],pv=[],storage=[])
for d,load in zip(s['data_centers'],[40,42.5,40]):d['interactive_mw']=[load]*24
s['network_domain']='physical';sid='domain'+uuid.uuid4().hex[:16];api(f'/api/sessions/{sid}/model/load',s)
try:api(f'/api/sessions/{sid}/model/rerun',{'ac':False});failure='unexpected success'
except RuntimeError as e:failure=str(e)
(O/'D01_physical_original_scale_failure.txt').write_text(failure)
s['network_domain']='paper_abstract';sid2='domain'+uuid.uuid4().hex[:16];api(f'/api/sessions/{sid2}/model/load',s);api(f'/api/sessions/{sid2}/model/rerun',{'ac':False});r=api(f'/api/sessions/{sid2}/results');a=r['audit']['optimized'];angle=max(abs(x) for h in a['network_dispatch'] for x in h['theta_rad']);check('D01_domain_pair_original_B','infeasible' in failure and angle>3.141592653589793 and all(abs(l['b_mw_per_rad']-.5)<1e-12 and l['x_ohm']==20000 for l in a['network_mapping']['branches']),max_abstract_theta_rad=angle,physical_failure_retained=True,purpose='conditional fixed-injection domain probe only; not counted as strategy accuracy')
d=api('/api/scenario/default');check('default_contract_not_relaxed',d['network_domain']=='physical' and d['objective_mode']=='cost' and d['migration_fee_basis']=='gross' and not d['lifecycle_enabled'],default_network_domain=d['network_domain'])
# Mandatory aggregate batch is not optional welfare admission and cannot disappear.
b=dict(name='B01_mandatory_batch_synthetic',network_case='custom',network=dict(buses=[dict(name='one',vn_kv=100)],ext_grids=[dict(bus=0,import_max_mw=.5)]),data_centers=[dict(name='DC',bus=0,cap_it_mw=100,pue=1,interactive_mw=[0]*24,batch_mwh=24)],jobs=[],pv=[],storage=[],carbon_weight=0)
sid='required'+uuid.uuid4().hex[:16];api(f'/api/sessions/{sid}/model/load',b);v=api(f'/api/sessions/{sid}/model/validate');check('B01_mandatory_energy_lower_bound',v['islands'][0]['required_peak_lower_bound_mw']==1 and v['islands'][0]['forecast_fixed_peak_mw']==0 and any('大于可靠' in x for x in v['warnings']),validation=v,synthetic_not_paper=True)
# New explicit welfare task, then immutable historical result replay and rerun.
F='/api/foundation';pr=api(F+'/projects',{'name':'论文复现·显式目标与生命周期验收'});axis=dict(location='published_abstract',year=2020,timezone='Asia/Shanghai',start='2020-01-01T00:00:00+08:00',step_minutes=60,length=24)
def freeze(model,name,objective):
 axis_used=copy.deepcopy(axis)
 if model.get('name','').startswith('Zheng2019'):axis_used.update(year=2019,start='2019-01-01T00:00:00+08:00',location='author2019_CA_PJM_hour_index_not_timezone_reconstruction')
 d=api(F+'/scenarios',dict(project_id=pr['id'],name=name,axis=axis_used,model=model));v=api(F+f"/scenarios/{d['id']}/publish",{'expected_revision':d['revision']});t=api(F+'/tasks',dict(version_id=v['id'],objective=objective,solver={'ac_check':False}));before=copy.deepcopy(t['snapshot']);run=api(F+f"/tasks/{t['id']}/run",{});assert run['status']=='completed',run
 op=api(F+f"/tasks/{t['id']}/open",{});zz=export(op['session_id']);folder=O/('frozen_'+name);folder.mkdir(exist_ok=True);(folder/'task.json').write_text(json.dumps(run));(folder/'export.zip').write_bytes(api(f"/api/sessions/{op['session_id']}/export.zip",raw=True));return t,run,v,zz,before
model=json.loads((P/'inputs/zhang_s4.json').read_text());t,run,v,z,before=freeze(model,'welfare_s4','welfare');again=api(F+f"/tasks/{t['id']}/rerun",{});repeat=api(F+f"/tasks/{again['id']}/run",{});snap=json.loads(z.read('input_snapshot.json'));check('frozen_welfare_replay_and_rerun',run['snapshot']==before==snap and digest(snap)==t['input_hash'] and again['input_hash']==t['input_hash'] and abs(run['full_result']['market_clearing']['welfare_cny']-72000)<1e-6 and repeat['status']=='completed' and api(F+f"/versions/{v['id']}")==v,task_id=t['id'],rerun_task_id=again['id'],input_hash=t['input_hash'],welfare_per_hour=3000,execution_code_hash=run['execution_code_hash'])
model=json.loads((O/'zheng_native/day001/input.json').read_text());t2,run2,v2,z2,before2=freeze(model,'lifecycle_day001','cost');ledger=json.loads(z2.read('audit_optimized.json'))['lifecycle_ledger'];dd=list(csv.DictReader(io.StringIO(z2.read('dispatch_optimized.csv').decode())));src=model['carbon_profiles']['PJM'];factor=model['pv'][0]['lifecycle_tco2e_mwh_profile'];head={j['release']:j['energy_mwh'] for j in model['jobs']};expected=sum(src[h]*head.get(h,0)-float(dd[h]['emis_generation_t'])-float(dd[h]['pv_used'])*factor[h] for h in range(24));check('frozen_lifecycle_export_independent_recompute',abs(expected-ledger['net_avoided_t'])<1e-7 and json.loads(z2.read('input_snapshot.json'))==before2,task_id=t2['id'],independent_net_avoided_t=expected,official_net_avoided_t=ledger['net_avoided_t'])
# Existing 26 versions / 27 tasks must remain byte-for-byte canonical-hash stable.
old=json.loads(pathlib.Path('/workspace/sim-agent-change-evidence/history_before_restart.json').read_text());cat=api(F+'/catalog');h=lambda x:hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False).encode()).hexdigest();diff=[]
for kind in ['version','template','library']:
 current={x['id']:h(x) for x in cat[kind]}
 diff += [[kind,id] for id,value in old[kind].items() if current.get(id)!=value]
legacy=None
for id,values in old['tasks'].items():
 rec=api(F+'/tasks/'+id);now={'snapshot':h(rec['snapshot']),'full_result':h(rec.get('full_result')),'status':rec['status']}
 if values!=now:diff.append(['task',id])
 if legacy is None and rec['status']=='completed' and rec.get('full_result'):legacy=rec
op=api(F+f"/tasks/{legacy['id']}/open",{});zz=export(op['session_id']);check('preexisting_frozen_history_and_legacy_export_preserved',not diff and json.loads(zz.read('input_snapshot.json'))==legacy['snapshot'],old_versions=len(old['version']),old_tasks=len(old['tasks']),changed_existing_records=diff,legacy_export_task_id=legacy['id'])
# Independent source and every final native export code/input hashes; no app import.
app=ROOT/'app';code_files={str(p.relative_to(app)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(app.rglob('*.py'))};code_hash=digest(code_files);mismatch=[];count=0
for file in sorted(O.glob('zhang_s*/export.zip'))+sorted(O.glob('zheng_native/day*/export.zip')):
 with zipfile.ZipFile(file) as zz:
  a=json.loads(zz.read('audit_optimized.json'))['execution_context'];model=json.loads(zz.read('scenario.json'))
  if a['code_hash']!=code_hash or a['input_model_hash']!=digest(model):mismatch.append(str(file))
 count+=1
annual=json.loads((O/'annual_results.json').read_text())
with zipfile.ZipFile(O/'annual_export.zip') as annual_zip:annual_input_match=digest(json.loads(annual_zip.read('input.json')))==annual['input_hash']
check('independent_execution_and_input_hashes',count==372 and not mismatch and annual_input_match and annual['execution_code_hash']==code_hash and run['execution_code_hash']==code_hash and run2['execution_code_hash']==code_hash,n_final_native_exports=count,annual_input_hash_matches=annual_input_match,product_python_code_hash=code_hash,mismatch=mismatch)
(O/'source_code_hash_manifest.json').write_text(json.dumps({'code_hash':code_hash,'files':code_files},indent=2))
(O/'extra_summary.json').write_text(json.dumps({'n_independent_gates':len(checks),'passed':sum(x['passed'] for x in checks),'failed':sum(not x['passed'] for x in checks),'checks':checks},ensure_ascii=False,indent=2))
sys.exit(any(not x['passed'] for x in checks))
