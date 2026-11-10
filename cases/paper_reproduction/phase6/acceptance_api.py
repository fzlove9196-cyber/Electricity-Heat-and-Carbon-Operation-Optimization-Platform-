"""Normal project draft→publish→frozen task→execute→history→ZIP, public own cases only."""
from pathlib import Path
import json,urllib.request,copy,zipfile,hashlib,sys,io
from independent_reference import load_export,audit
E=Path(sys.argv[1] if len(sys.argv)>1 else '/workspace/sim-agent-phase6-evidence');E.mkdir(exist_ok=True);B='http://127.0.0.1:8080';index={}
def call(path,body=None):
 q=urllib.request.Request(B+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'});return json.load(urllib.request.urlopen(q,timeout=900))
def save(n,x): (E/(n+'.json')).write_text(json.dumps(x,ensure_ascii=False,indent=2))
def run(name,m,a,expected):
 d=call('/api/foundation/scenarios',dict(project_id=index['project']['id'],name=name,model=m,axis=a));assert call('/api/foundation/scenarios/'+d['id']+'/validate',{})['ok'];v=call('/api/foundation/scenarios/'+d['id']+'/publish',dict(expected_revision=1));t=call('/api/foundation/tasks',dict(version_id=v['id'],name=name,solver=dict(ac_check=False,time_limit_s=60)));r=call('/api/foundation/tasks/'+t['id']+'/run',{});save(name+'_task',r);assert r['status']==expected,(r['status'],r.get('error'));assert r['input_hash']==t['input_hash']
 z=urllib.request.urlopen(B+'/api/foundation/tasks/'+t['id']+'/export.zip',timeout=900).read();(E/(name+'.zip')).write_bytes(z)
 with zipfile.ZipFile(io.BytesIO(z)) as zz:assert json.loads(zz.read('input_snapshot.json'))==t['snapshot'];assert ('results.json' in zz.namelist())==(expected=='completed')
 rec=dict(scenario=d['id'],version=v['id'],task=t['id'],input_hash=t['input_hash'],version_hash=v['hash'],status=r['status'],zip_sha256=hashlib.sha256(z).hexdigest(),model_source=m['source'])
 if r.get('full_result') or r.get('partial_result'):
  mm,rr=load_export(E/(name+'.zip'));rec['independent']=audit(mm,rr);rec['policies']=rr['policies'];rec['baseline']=rr['baseline_totals']
 if expected=='completed':assert call('/api/foundation/tasks/'+t['id']+'/open',{})['model_kind']=='opt_grid_feedback'
 index['cases'][name]=rec;save('api_acceptance_index',index);print(name,r['status'],t['id'],flush=True);return r
assert call('/health')==dict(ok=True,mock=True);gate=call('/api/solver-execution/status');assert gate['active'] is None and not gate['queued']
index=dict(project=call('/api/foundation/projects',dict(name='Phase6 GridFeedback · 真实RTS闰日子集+合成边界（非整篇）',description='normal product immutable task/ZIP acceptance; browser remains blocked, no UI pass claimed')),cases={},browser='BLOCKED ERR_CONNECTION_REFUSED previously confirmed; Shell API acceptance only')
save('api_acceptance_index',index)
for key in ['benchmark_clean','benchmark_negative_lmce','benchmark_congestion','rts_leap4h']:
 p=call('/api/opt-grid-feedback/presets/'+key);run(key,p['model'],p['axis'],'completed')
p=call('/api/opt-grid-feedback/presets/benchmark_negative_lmce');m=copy.deepcopy(p['model']);m.update(max_iterations=1,require_convergence=True);run('expected_failed_iteration_limit',m,p['axis'],'failed')
m=copy.deepcopy(p['model'])
for g in m['generators']:g['available_mw']=[0]
run('expected_failed_no_generation',m,p['axis'],'failed')
old=index['cases']['benchmark_negative_lmce'];before=call('/api/foundation/tasks/'+old['task']);rr=call('/api/foundation/tasks/'+old['task']+'/rerun',{});fresh=call('/api/foundation/tasks/'+rr['id']+'/run',{});assert fresh['status']=='completed' and rr['snapshot']==before['snapshot'];assert call('/api/foundation/tasks/'+old['task'])==before;assert fresh['full_result']['policies']==before['full_result']['policies'];index['frozen_rerun']=dict(task=rr['id'],rerun_of=old['task'],input_hash=rr['input_hash'],original_unchanged=True,policies_equal=True);save('api_acceptance_index',index);print('frozen rerun',rr['id'],flush=True)
