"""HTTP-only regression of the UI binding contract. No browser automation."""
import copy,json,urllib.request,urllib.error
from pathlib import Path
from app.foundation import store as S
B='http://127.0.0.1:8080'
def req(path,body=None,method=None,status=200):
    request=urllib.request.Request(B+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'},method=method or ('POST' if body is not None else 'GET'))
    try:
        with urllib.request.urlopen(request,timeout=180) as r: code=r.status;out=json.load(r)
    except urllib.error.HTTPError as e: code=e.code;out=json.load(e)
    assert code==status,(path,code,out)
    return out
m=json.load(open('cases/product_foundation/results/ui_retest_manifest.json'));root='/api/foundation';public=m['selected_public_resource'];sample_id=m['old_example_id']
example=req(root+'/library/'+sample_id)
d=req(root+'/scenarios',{'project_id':m['project_id'],'name':'API探针-已操作（UI首次复验请选01/02）','axis':example['axis'],'template_id':m['template_id']})
base=root+'/scenarios/'+d['id']
d=req(base+'/bind',{'mode':'add','resource_id':sample_id,'expected_revision':d['revision']})['scenario']
oldv=req(base+'/publish',{'expected_revision':d['revision']});oldtask=req(root+'/tasks',{'version_id':oldv['id'],'name':'API探针原示例快照'})
# Original request appended public data after the example, then failed atomically.
legacy=req(base+'/draft',{'expected_revision':d['revision'],'bindings':d['draft']['bindings']+[{'resource_id':public['id'],'target':''}]},method='PATCH',status=400)
assert legacy['detail']['resource']['id']==public['id']
failed=req(base+'/bind',{'expected_revision':d['revision'],'mode':'replace','resource_id':public['id']},status=400)
assert failed['detail']['conflicts']==[{'field':'location','expected':'示例地点','actual':'中卫'}]
assert req(base)==d
result=req(base+'/bind',{'expected_revision':d['revision'],'mode':'replace','resource_id':public['id'],'align_axis':True});d=result['scenario']
assert d['draft']['bindings']==[{'resource_id':public['id'],'target':''}]
assert d['draft']['axis']==public['axis']
v=req(base+'/publish',{'expected_revision':d['revision']});t=req(root+'/tasks',{'version_id':v['id'],'name':'API探针公开中卫新快照'})
assert t['snapshot']['resources'][0]['id']==public['id']
assert req(root+'/tasks/'+oldtask['id'])==oldtask
checkout=req(base+'/checkout',{});sid=checkout['session_id']
assert req('/api/sessions/'+sid+'/model/rerun',{'ac':False})['ok']
assert req('/api/sessions/'+sid+'/results')['ok']
req('/api/sessions/'+sid+'/model/element/dc/DC_A',{'pue':1.4},method='PATCH')
context=req(root+'/sessions/'+sid+'/context')['context'];assert context['unsaved'] and context['results_stale']
assert not req('/api/sessions/'+sid+'/results')['ok']
changed=req(root+'/sessions/'+sid+'/save-draft',{'expected_revision':d['revision']})['scenario']
assert changed['draft']['model']['data_centers'][0]['pue']==1.4
assert req(root+'/versions/'+v['id'])==v
before=json.load(open('cases/product_foundation/results/ui_fix_existing_records_before.json'))
unchanged={kind:all(S.digest(S.get(kind,id))==hash for id,hash in records.items()) for kind,records in before.items()}
assert all(unchanged.values()),unchanged
out=dict(completed=S.now(),root_cause_reproduced=legacy['detail'],explicit_conflict=failed['detail'],selected_public_id=public['id'],saved_binding=d['draft']['bindings'],new_task_id=t['id'],frozen_public_id=t['snapshot']['resources'][0]['id'],old_snapshot_unchanged=True,checkout_edit_writeback_stale=True,all_preexisting_records_unchanged=unchanged,probe_scenario_id=d['id'],ui_fixture_scenarios_untouched=[m['binding_retest']['scenario_id'],m['edit_retest']['scenario_id']])
Path('cases/product_foundation/results/ui_fix_http_validation.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));print(json.dumps(out,ensure_ascii=False,indent=2))
