"""Explicit local API. Library/template/version records expose no update/delete route."""
import copy
from fastapi import APIRouter, HTTPException
from . import store as S, service as F
router=APIRouter(prefix='/api/foundation',tags=['product-foundation'])
def guard(fn,*args,**kwargs):
    try: return fn(*args,**kwargs)
    except F.AxisMismatch as e: raise HTTPException(400,e.detail)
    except KeyError as e: raise HTTPException(404,str(e))
    except (ValueError,TypeError) as e: raise HTTPException(400,str(e))

def session_context(s):
    c=s.state.get('foundation_context')
    if not c: return None
    try:
        d=S.get('scenario',c['scenario_id']); sc=s.state.get('scenario')
        current=S.digest(sc.model_dump()) if sc else None
        draft_model,_,_=F.expand(d['draft'])
        return {**c,'project_name':S.get('project',d['project_id'])['name'],'scenario_name':d['name'],'draft_revision':d['revision'],'unsaved':current!=S.digest(draft_model),'results_stale':bool(s.state.get('foundation_results_stale')),'current_hash':current,'message':'会话是编辑副本，写回草稿并发布后才能创建版本化任务'}
    except (KeyError,ValueError): return {**c,'unsaved':True,'results_stale':True}

@router.get('/catalog')
def catalog():
    with S.LOCK:
        F.seed(); F.seed_public_climate()
    out={k:S.all(k) for k in ('project','scenario','version','template','library')}
    out['task']=[{**{k:t.get(k) for k in ('id','name','status','created','input_hash','result')},'snapshot':{k:t['snapshot'].get(k) for k in ('project_id','scenario_id','version_id','version_number')}} for t in S.all('task')]
    return out
@router.post('/projects')
def project_new(b:dict): return guard(F.project_new,b)
@router.patch('/projects/{id}')
def project_update(id:str,b:dict):
    d=guard(S.get,'project',id)
    for k in ('name','documents','pending'):
        if k in b: d[k]=b[k]
    if not d['name']: raise HTTPException(400,'项目名称不能为空')
    return guard(S.put,'project',d,True)
@router.post('/scenarios')
def scenario_new(b:dict): return guard(F.scenario_new,b)
@router.get('/scenarios/{id}')
def scenario_get(id:str): return guard(S.get,'scenario',id)
@router.patch('/scenarios/{id}/draft')
def draft_update(id:str,b:dict):
    with S.LOCK: return guard(F.draft_update,id,b)
@router.post('/scenarios/{id}/bind')
def bind_resource(id:str,b:dict):
    with S.LOCK: return guard(F.bind_resource,id,b)
@router.post('/scenarios/{id}/validate')
def draft_validate(id:str):
    model,refs,v=guard(F.expand,guard(S.get,'scenario',id)['draft'])
    return {**v,'expanded_model':model,'resource_hashes':[{k:r[k] for k in ('id','hash','revision')} for r in refs]}
@router.post('/scenarios/{id}/publish')
def publish(id:str,b:dict):
    with S.LOCK: return guard(F.publish,id,b)
@router.get('/versions/{id}')
def version_get(id:str): return guard(S.get,'version',id)
@router.post('/templates')
def template_new(b:dict): return guard(F.template_new,b)
@router.post('/library')
def library_new(b:dict): return guard(F.library_new,b)
@router.get('/library/{id}')
def library_get(id:str): return guard(S.get,'library',id)
@router.post('/tasks')
def task_new(b:dict): return guard(F.task_new,b)
@router.get('/tasks/{id}')
def task_get(id:str): return guard(S.get,'task',id)
@router.post('/tasks/{id}/run')
def task_run(id:str): return guard(F.execute,id)
@router.post('/tasks/{id}/rerun')
def task_rerun(id:str):
    old=guard(S.get,'task',id)
    return guard(F.task_new,{'name':old['name']+' · 历史重跑','rerun_of':id},frozen=old['snapshot'])
@router.get('/sessions/{sid}/context')
def context_get(sid:str):
    from ..main import get_session
    s=get_session(sid)
    return {'context':session_context(s),'task_id':s.state.get('foundation_task_id')}
@router.post('/sessions/{sid}/import')
def session_import(sid:str,b:dict):
    from ..main import get_session,save_session
    s=get_session(sid)
    if 'scenario' not in s.state: raise HTTPException(400,'会话尚无场景')
    d=guard(F.scenario_new,{**b,'model':s.state['scenario'].model_dump()})
    s.state['foundation_context']={'scenario_id':d['id'],'project_id':d['project_id'],'base_version_id':None}
    save_session(s); return d
@router.post('/scenarios/{id}/checkout')
def checkout(id:str,b:dict):
    from ..main import get_session,save_session
    from ..scenario import Scenario
    from pathlib import Path
    d=guard(S.get,'scenario',id)
    if b.get('version_id'):
        version=guard(S.get,'version',b['version_id'])
        if version['scenario_id']!=id: raise HTTPException(400,'版本不属于此场景')
        model=version['model']
    else: model,refs,_=guard(F.expand,d['draft'])
    if model.get('model_kind') in ('opt_cfe','opt_grid_feedback','opt_gpu'): raise HTTPException(400,'独立CFE/电网反馈/GPU请在项目高级JSON草稿中编辑、保存、发布；不签出为24h拓扑会话')
    # Always a new edit session; never overwrite user's current or historical session.
    s=get_session(None); s.state['scenario']=Scenario.model_validate(model); s.state['results']={}; s.state['title']=d['name']+' · 编辑副本'
    s.state['foundation_context']={'project_id':d['project_id'],'scenario_id':id,'base_version_id':b.get('version_id')}
    Path(s.artifact_dir).mkdir(parents=True,exist_ok=True)
    Path(s.artifact_dir,'scenario.json').write_text(s.state['scenario'].model_dump_json(indent=2))
    source=version if b.get('version_id') else {**d['draft'],'model':model,'resources':refs}
    s.state['origin']={'kind':'preset','name':d['name']+' 编辑副本'}
    s.state['param_src']=F.parameter_sources(source)
    save_session(s); return {'session_id':s.id,'context':session_context(s)}
@router.post('/sessions/{sid}/save-draft')
def save_draft(sid:str,b:dict):
    from ..main import get_session,save_session
    s=get_session(sid); c=s.state.get('foundation_context')
    if not c or 'scenario' not in s.state: raise HTTPException(400,'请先签出场景或导入旧会话')
    # Store the expanded session as the new base. Drop bindings explicitly so a
    # user edit cannot be silently masked by re-applying a previously bound model.
    with S.LOCK:
        d=guard(F.draft_update,c['scenario_id'],{'expected_revision':b.get('expected_revision'),'model':s.state['scenario'].model_dump(),'bindings':[],'device_bindings':[], 'provenance':[{'type':'session_materialization','session_id':sid,'base_version_id':c.get('base_version_id'),'prior_bindings':S.get('scenario',c['scenario_id'])['draft'].get('bindings',[]),'prior_device_bindings':S.get('scenario',c['scenario_id'])['draft'].get('device_bindings',[])}]})
    save_session(s)
    return {'scenario':d,'note':'编辑副本已实体化写回；原绑定来源见历史版本，重绑请到数据绑定页，旧版本不变'}
@router.post('/tasks/{id}/open')
def task_open(id:str):
    from ..main import get_session,save_session
    from ..scenario import Scenario
    import pandas as pd
    from pathlib import Path
    t=guard(S.get,'task',id)
    if t['status']!='completed': raise HTTPException(400,'任务尚无成功结果')
    if t['snapshot']['model'].get('model_kind') in ('opt_cfe','opt_grid_feedback','opt_gpu'): return {'model_kind':t['snapshot']['model']['model_kind'],'task_id':id,'note':'独立CFE/电网反馈/GPU历史结果只读，显示此冻结任务；未切换/伪造24h会话'}
    # Display source task's immutable model and restore dispatch table for charts.
    s=get_session(None); s.state['title']=t['name']+' · 历史结果副本'; s.state['scenario']=Scenario.model_validate(t['snapshot']['model'])
    s.state['origin']={'kind':'preset','name':'历史场景版本 '+t['snapshot']['version_id']}
    s.state['param_src']=F.parameter_sources(t['snapshot'])
    s.state['foundation_task_id']=id; s.state.pop('foundation_context',None)
    s.state['foundation_results_stale']=False
    # Restore from immutable task output even after process restart or edits to
    # the task's display session; never reuse a newer session's result.
    if t.get('full_result'):
        s.state['results']={'optimized':F.unpack(t['full_result'])}
        s.state['kpis']={'optimized':t['kpis'].get('kpis',t['kpis'])}
        s.state['ac']={'optimized':t['ac']} if t.get('ac') else {}
        s.state['solver_cfg']=t['snapshot']['solver']
        s.state['foundation_result_model_hash']=S.digest(s.state['scenario'].model_dump())
        s.state['foundation_model_hash']=S.digest(s.state['scenario'].model_dump())
        s.state.pop('model_graph',None)
    else: s.state['results']={}
    Path(s.artifact_dir).mkdir(parents=True,exist_ok=True)
    Path(s.artifact_dir,'scenario.json').write_text(s.state['scenario'].model_dump_json(indent=2))
    from ..tools.sim_tools import _art
    import json
    Path(_art(s,'input_snapshot.json')).write_text(json.dumps(t['snapshot'],ensure_ascii=False,indent=2))
    if s.state.get('results'):
        s.state['results']['optimized']['df'].to_csv(_art(s,'dispatch_optimized.csv'),index=False)
    save_session(s)
    return {'session_id':s.id,'task':t,'note':'展示该任务当时模型；已恢复任务完整结果，可查看拓扑/结果并继续三级调度；修改副本不改变任务快照'}

@router.get('/tasks/{id}/export.zip')
def task_export_zip(id:str):
    from fastapi.responses import Response
    t=guard(S.get,'task',id)
    if t['snapshot']['model'].get('model_kind')=='opt_grid_feedback':from ..opt_grid_feedback import export_task
    elif t['snapshot']['model'].get('model_kind')=='opt_gpu':from ..opt_gpu import export_task
    else:from ..opt_cfe import export_task
    if t['snapshot']['model'].get('model_kind') not in ('opt_cfe','opt_grid_feedback','opt_gpu'): raise HTTPException(400,'日模型请用原历史结果运行包；此入口仅独立CFE/电网反馈/GPU')
    return Response(export_task(t),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="{t['snapshot']['model']['model_kind']}-{id}.zip"'})
