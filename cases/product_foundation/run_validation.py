"""Reproducible full product workflow on public-project equivalents, no network calls.
Run from repository: PYTHONPATH=. /workspace/sdco-env/bin/python cases/product_foundation/run_validation.py
Creates local, inspectable validation projects/tasks; does not touch market transactions.
"""
import json,sys
from pathlib import Path
import numpy as np
from fastapi.testclient import TestClient
from app.main import app
from app.foundation import service as F,store as S
from app.scenario import Scenario,load_preset
from app.tools import sdco_engine as eng
C=TestClient(app);P='/api/foundation'
def req(method,path,body=None):
    r=C.request(method,P+path,json=body)
    assert r.status_code==200,(path,r.status_code,r.text)
    return r.json()
def post(path,b=None):return req('POST',path,{} if b is None else b)
F.seed();F.seed_public_climate()
rows=[]
for site,location,preset in [('zhongwei','中卫','zhongwei_summer_coupled'),('shaoguan','韶关','shaoguan_summer'),('ulanqab','乌兰察布','ulanqab_cicdata_summer')]:
    sc=load_preset(preset);a=dict(location=location,year=2024,timezone='Asia/Shanghai',start='2024-07-01T00:00:00+08:00',step_minutes=60,length=24)
    weather=next(r for r in S.all('library') if r.get('seed_key')=='openmeteo_'+site+'_20240701')
    pr=post('/projects',dict(name=location+' · 产品化闭环验证',documents=[{'title':preset+'已有公开资料等值场景','sources':sc.sources}],pending=[]))
    te=post('/templates',dict(name=location+'验证参考模板',source=sc.sources or preset,model=sc.model_dump(),assumptions=sc.note+'；等值结构，非原工程设计图'))
    d=post('/scenarios',dict(project_id=pr['id'],name='公开气象绑定验证',template_id=te['id'],axis=a))
    d=req('PATCH','/scenarios/'+d['id']+'/draft',dict(expected_revision=d['revision'],bindings=[{'resource_id':weather['id']}]))
    val=post('/scenarios/'+d['id']+'/validate');assert val['ok']
    v=post('/scenarios/'+d['id']+'/publish',dict(expected_revision=d['revision']))
    frozen=json.loads(json.dumps(v))
    t=post('/tasks',dict(version_id=v['id'],name=location+'公开气象实际求解',objective='cost',solver={'time_limit_s':120,'ac_check':True}))
    t=post('/tasks/'+t['id']+'/run');assert t['status']=='completed',t
    direct=eng.solve(Scenario.model_validate(t['snapshot']['model']),True)
    err=abs(direct['cost_cny']-t['result']['cost_cny'])
    assert err<.051
    rr=post('/tasks/'+t['id']+'/rerun');rr=post('/tasks/'+rr['id']+'/run');assert rr['status']=='completed',rr
    assert rr['input_hash']==t['input_hash']
    assert abs(rr['result']['cost_cny']-t['result']['cost_cny'])<.001
    edit=post('/scenarios/'+d['id']+'/checkout');sid=edit['session_id']
    # Existing configuration builder truly writes to the same edit session.
    cfg=C.get('/api/config/template').json()
    # Topology edits, transparent parameter sheet and explicit draft save share one path.
    dc=sc.data_centers[0].name
    r=C.patch(f'/api/sessions/{sid}/model/element/dc/{dc}',json={'pue':sc.data_centers[0].pue+.01})
    assert r.status_code==200,r.text
    ctx=req('GET','/sessions/'+sid+'/context')['context'];assert ctx['unsaved']
    changed=post('/sessions/'+sid+'/save-draft',{'expected_revision':d['revision']})['scenario']
    post('/scenarios/'+d['id']+'/publish',{'expected_revision':changed['revision']})
    assert req('GET','/versions/'+v['id'])==frozen
    opened=post('/tasks/'+t['id']+'/open');res=C.get('/api/sessions/'+opened['session_id']+'/results').json();assert res['ok']
    th=t['result'].get('thermal_safe');ac=t.get('ac',{})
    row=dict(site=site,project_id=pr['id'],scenario_id=d['id'],version_id=v['id'],task_id=t['id'],task_session_id=t['session_id'],snapshot_hash=t['input_hash'],weather_resource_id=weather['id'],weather_sha256=weather['original_file_sha256'],source=weather['source'],assumptions=sc.note,solver_status=t['result']['solver_status'],cost_cny=t['result']['cost_cny'],emissions_tco2=t['result']['emissions_tco2'],thermal_safe=th,tin_range_c=t['result'].get('tin_range_c'),direct_solver_cost_error_cny=err,rerun_cost_error_cny=abs(rr['result']['cost_cny']-t['result']['cost_cny']),ac=ac,version_unchanged=True,edit_writeback_and_task_restore=True)
    rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
out=dict(generated=S.now(),scope='公开项目等值模型叠加2024-07-01公开ERA5温度；风光/任务等未绑定曲线沿原预设，不是同期现场整套数据；非真实工程数字孪生/非交易收益验证',checks='创建项目/模板/独立场景、数据版本绑定、静态校验发布、原引擎求解、AC诊断、直接求解一致、冻结重跑、编辑写回不改历史、当时模型与结果恢复',results=rows)
Path('cases/product_foundation/results/workflow_validation.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
print('PASS: 3 complete project workflows')
