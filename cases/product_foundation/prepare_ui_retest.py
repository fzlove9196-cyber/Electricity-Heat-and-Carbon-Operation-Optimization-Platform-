"""Create independent retest fixtures; never modifies an existing record."""
import copy,json
from pathlib import Path
from app.foundation import service as F,store as S

template=next(t for t in S.all('template') if t['name']=='基础单园区')
public=next(r for r in S.all('library') if r.get('seed_key')=='openmeteo_zhongwei_20240701')
example=next(r for r in S.all('library') if r['name']=='示例·weather')
p=F.project_new({'name':'UI复验-绑定修复-20261106-1336','documents':[{'note':'专用复制项目；不修改三套历史验证项目'}]})
a=F.scenario_new({'project_id':p['id'],'name':'01-气象替换待操作（示例→中卫）','axis':example['axis'],'template_id':template['id']})
a=F.bind_resource(a['id'],{'resource_id':example['id'],'expected_revision':a['revision'],'mode':'add'})['scenario']
av=F.publish(a['id'],{'expected_revision':a['revision']})
at=F.task_new({'version_id':av['id'],'name':'历史示例快照（不应跟随草稿改变）','solver':{'ac_check':False}})
b=F.scenario_new({'project_id':p['id'],'name':'02-编辑写回与结果过期（中卫已匹配）','axis':public['axis'],'template_id':template['id']})
b=F.bind_resource(b['id'],{'resource_id':public['id'],'expected_revision':b['revision'],'mode':'add'})['scenario']
bv=F.publish(b['id'],{'expected_revision':b['revision']})
bt=F.task_new({'version_id':bv['id'],'name':'中卫匹配气象·旧版本基准结果','solver':{'ac_check':True}});bt=F.execute(bt['id']);assert bt['status']=='completed',bt.get('error')
manifest=dict(created=S.now(),project_id=p['id'],project_name=p['name'],template_id=template['id'],selected_public_resource={k:public[k] for k in ('id','name','revision','axis')},old_example_id=example['id'],binding_retest={'scenario_id':a['id'],'name':a['name'],'published_v1':av['id'],'old_task_id':at['id'],'initial_revision':a['revision']},edit_retest={'scenario_id':b['id'],'name':b['name'],'published_v1':bv['id'],'old_task_id':bt['id'],'initial_revision':b['revision'],'device':'DC_A','old_pue':1.35,'test_pue':1.40})
Path('cases/product_foundation/results/ui_retest_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2));print(json.dumps(manifest,ensure_ascii=False,indent=2))
