"""Versioned product foundation: real solver coupling, not metadata-only tests."""
import copy
import pytest
from fastapi.testclient import TestClient
from app.main import app,SESSIONS,get_session,save_session
from app import settings
from app.foundation import service as F,store as S
from app.scenario import build_default,Scenario
from app.tools import model_edit as me

c=TestClient(app)
P='/api/foundation'
@pytest.fixture(autouse=True)
def isolated_store(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,'DATA_DIR',str(tmp_path)); yield

def a(): return dict(location='中卫',year=2024,timezone='Asia/Shanghai',start='2024-07-01T00:00:00+08:00',step_minutes=60,length=24)
def simple():
    return dict(name='single',network_case='custom',network=dict(buses=[dict(name='b',vn_kv=110)],ext_grids=[dict(bus=0)]),data_centers=[dict(name='DC',bus=0,cap_it_mw=30,pue=1.3,interactive_mw=[10.]*24,batch_mwh=60)],price_cny_kwh=[.5]*24,storage=[dict(name='ESS',bus=0,energy_mwh=20,power_mw=10)])
def scene():
    p=F.project_new({'name':'公开项目'}); return F.scenario_new(dict(project_id=p['id'],name='夏季',axis=a(),model=simple()))
def pub(d): return F.publish(d['id'],{'expected_revision':d['revision']})
def lib(kind,values=None,**extra):
    return F.library_new(dict(name=kind,kind=kind,unit=F.KINDS[kind],axis=a(),values=values if values is not None else [.5]*24,source='明确合成测试',applicability='24小时测试',**extra))
def upd(d,**kw):return F.draft_update(d['id'],dict(expected_revision=d['revision'],**kw))
def execute(v,**kw):
    t=F.task_new(dict(version_id=v['id'],solver={'ac_check':False},**kw)); return F.execute(t['id'])

def test_project_multiple_scenarios_revision_protection():
    d=scene(); v=pub(d); before=copy.deepcopy(v)
    d2=F.scenario_new(dict(project_id=d['project_id'],name='独立复制',axis=a(),version_id=v['id']))
    raw=d2['draft']['model'];raw['data_centers'][0]['pue']=1.5
    d2=upd(d2,model=raw)
    assert S.get('version',v['id'])==before
    with pytest.raises(ValueError): F.draft_update(d2['id'],{'expected_revision':1})
    assert c.patch(P+'/versions/'+v['id'],json={'model':{}}).status_code==405
    assert c.delete(P+'/versions/'+v['id']).status_code==405
    with pytest.raises(ValueError):S.put('version',before,True)

def test_template_independent_copy_and_source():
    d=scene();v=pub(d);t=F.template_new(dict(name='参考模板',version_id=v['id'],source='公开资料+假设'))
    x=F.scenario_new(dict(project_id=d['project_id'],name='B',axis=a(),template_id=t['id']))
    raw=x['draft']['model'];raw['storage'][0]['energy_mwh']=40;upd(x,model=raw)
    assert S.get('template',t['id'])['model']['storage'][0]['energy_mwh']==20
    assert c.patch(P+'/templates/'+t['id'],json={}).status_code==404

def test_series_device_binding_changes_actual_solve_and_freezes():
    d=scene();v0=pub(d);r0=execute(v0);assert r0['status']=='completed',r0
    price=lib('price',[.9]*24)
    device=F.library_new(dict(name='PUE模型',kind='device',device_type='data_center',parameters={'pue':1.5},units={'pue':'1'},source='假设设备',applicability='测试'))
    d=upd(d,bindings=[dict(resource_id=price['id'])],device_bindings=[dict(resource_id=device['id'],target='DC')])
    v1=pub(d);r1=execute(v1);assert r1['status']=='completed',r1
    assert r1['result']['cost_cny']>r0['result']['cost_cny']*1.5
    assert v1['model']['network']['ext_grids'][0]['price_cny_kwh']==[.9]*24
    assert r1['snapshot']['model']['data_centers'][0]['pue']==1.5
    revision=lib('price',[1.8]*24,previous_id=price['id'])
    assert revision['revision']==2 and S.get('library',price['id'])['values']==[.9]*24
    assert S.get('task',r1['id'])['snapshot']['resources'][0]['values']==[.9]*24
    rerun=F.task_new({'rerun_of':r1['id']},frozen=r1['snapshot']);rr=F.execute(rerun['id'])
    assert rr['input_hash']==r1['input_hash']
    assert rr['result']['cost_cny']==pytest.approx(r1['result']['cost_cny'],abs=.001)
    with pytest.raises(ValueError):F.execute(rr['id'])

def test_weather_carbon_load_binding_expands():
    d=scene();w=lib('weather',[30.]*24);co=lib('carbon',[.8]*24);lo=lib('load',[8.]*24)
    d=upd(d,bindings=[dict(resource_id=w['id']),dict(resource_id=co['id']),dict(resource_id=lo['id'],target='DC')]);v=pub(d)
    assert v['model']['outdoor_temp_c']==[30.]*24
    assert v['model']['carbon_profiles']['national']==[.8]*24
    assert v['model']['data_centers'][0]['interactive_mw']==[8.]*24
    assert len(v['resources'])==3

@pytest.mark.parametrize('key,value',[('location','韶关'),('year',2023),('timezone','UTC'),('step_minutes',15),('length',23),('start','2024-07-01T01:00:00+08:00')])
def test_axis_errors_and_binding_mismatch(key,value):
    d=scene();r=lib('price');aa=a();aa[key]=value
    if key=='location':
        with pytest.raises(ValueError):upd(d,axis=aa,bindings=[{'resource_id':r['id']}])
    else:
        with pytest.raises((ValueError,KeyError)):F.axis(aa)

@pytest.mark.parametrize('values,unit',[([.5]*23,'CNY/kWh'),([None]*24,'CNY/kWh'),([float('nan')]*24,'CNY/kWh'),([.5]*24,'USD/MWh')])
def test_missing_units_length_rejected(values,unit):
    with pytest.raises(ValueError):F.library_new(dict(name='错误',kind='price',unit=unit,axis=a(),values=values,source='测试',applicability='测试'))

@pytest.mark.parametrize('edit',[
    lambda m:m['data_centers'][0].update(pue=.5),
    lambda m:m['storage'][0].update(eta_ch=1.2),
    lambda m:m['data_centers'][0].update(bus=99),
    lambda m:m['network'].update(lines=[dict(from_bus=0,to_bus=0,length_km=1,rating_mva=100)]),
    lambda m:(m['network'].update(ext_grids=[]),m.update(storage=[])),
])
def test_illegal_parameters_topology_rejected(edit):
    d=scene();m=d['draft']['model'];edit(m)
    with pytest.raises(ValueError):upd(d,model=m)


def test_pending_documents_not_automatically_modelled():
    d=scene();d=upd(d,pending=['确认PDF中储能接线'])
    with pytest.raises(ValueError):pub(d)
    assert c.patch(P+'/projects/'+d['project_id'],json={'documents':[{'title':'设计资料','url':'https://example.org/design.pdf'}]}).status_code==200
    assert S.get('scenario',d['id'])['draft']['pending']


def test_checkout_edit_writeback_legacy_and_expired_results():
    d=scene();v=pub(d)
    r=c.post(P+'/scenarios/'+d['id']+'/checkout',json={});assert r.status_code==200,r.text
    sid=r.json()['session_id'];s=get_session(sid)
    t=execute(v);assert t['status']=='completed'
    # Topology/parameter changes remain only in checkout until explicit save.
    assert c.patch(f'/api/sessions/{sid}/params',json={'path':'data_centers.0.pue','value':1.6}).status_code==200
    ctx=c.get(P+'/sessions/'+sid+'/context').json()['context'];assert ctx['unsaved'] and ctx['results_stale']
    assert S.get('scenario',d['id'])['draft']['model']['data_centers'][0]['pue']==1.3
    r=c.post(P+'/sessions/'+sid+'/save-draft',json={'expected_revision':d['revision']});assert r.status_code==200,r.text
    assert S.get('scenario',d['id'])['draft']['model']['data_centers'][0]['pue']==1.6
    assert S.get('version',v['id'])['model']['data_centers'][0]['pue']==1.3
    # Restore task input+output after restart AND after user edits display session.
    tsid=t['session_id'];SESSIONS.pop(tsid,None)
    r=c.post(P+'/tasks/'+t['id']+'/open',json={});assert r.status_code==200,r.text
    tsid=r.json()['session_id']
    assert c.get(f'/api/sessions/{tsid}/results').json()['ok']
    live=get_session(tsid);live.state['scenario'].data_centers[0].pue=2;save_session(live)
    assert not live.state['results']
    tsid=c.post(P+'/tasks/'+t['id']+'/open',json={}).json()['session_id']
    assert get_session(tsid).state['scenario'].data_centers[0].pue==1.3
    assert c.get(f'/api/sessions/{tsid}/results').json()['ok']
    # Existing sessions are opt-in imported rather than auto-migrated.
    old=get_session('legacy'+S.uid());old.state['scenario']=Scenario.model_validate(simple());save_session(old)
    assert c.get(P+'/sessions/'+old.id+'/context').json()['context'] is None
    imp=c.post(P+'/sessions/'+old.id+'/import',json={'project_id':d['project_id'],'name':'旧模型','axis':a()});assert imp.status_code==200,imp.text


def test_task_solver_configuration_unknown_and_pure_carbon_not_faked():
    v=pub(scene())
    with pytest.raises(ValueError):F.task_new({'version_id':v['id'],'solver':{'typo':1}})
    with pytest.raises(ValueError):F.task_new({'version_id':v['id'],'objective':'carbon'})
    with pytest.raises(ValueError):F.task_new({'version_id':v['id'],'solver':{'time_limit_s':-1}})
    with pytest.raises(ValueError):F.task_new({'version_id':v['id'],'carbon_weight':-1,'objective':'weighted_carbon'})


def test_invalid_device_and_curve_rejected():
    for parameters,units in [({'eta_ch':1.2},{'eta_ch':'1'}),({'power_mw':10},{'power_mw':'kW'})]:
        with pytest.raises(ValueError):F.library_new(dict(name='设备',kind='device',device_type='storage',parameters=parameters,units=units,source='测试',applicability='测试'))
    m=simple();m['data_centers'][0].update(power_model='pdu_pwl',pdu_breakpoints=[dict(util=0,power_mw=20),dict(util=1,power_mw=10)])
    with pytest.raises(ValueError):F.checked(m)


def test_frontend_has_paths_not_only_metadata():
    from pathlib import Path
    html=Path('app/static/index.html').read_text();js=Path('app/static/foundation.js').read_text()
    for id in ('pfProject','pfScenario','pfVersion','pfSaveSession','pfTaskCreate','pfTaskRun','pfTaskOpen','pfBind'):
        assert id in html+js
    assert '/tasks/' in js and '/run' in js and '/save-draft' in js


def test_unknown_fields_and_timestamp_gaps_rejected():
    d=scene();m=d['draft']['model'];m['data_centers'][0]['pue_typo']=2
    with pytest.raises(ValueError):upd(d,model=m)
    with pytest.raises(ValueError):lib('price',timestamps=['2024-07-01T00:00:00+08:00']*24)


def test_snapshot_and_completed_result_cannot_be_replaced():
    t=execute(pub(scene()));assert t['status']=='completed',t.get('error')
    broken=copy.deepcopy(t);broken['snapshot']['model']['name']='tamper'
    with pytest.raises(ValueError):S.put('task',broken,True)
    broken=copy.deepcopy(t);broken['result']['cost_cny']=0
    with pytest.raises(ValueError):S.put('task',broken,True)
    assert S.digest(S.get('task',t['id'])['snapshot'])==t['input_hash']


def test_project_checkout_invalid_edit_rolls_back():
    d=scene();sid=c.post(P+'/scenarios/'+d['id']+'/checkout',json={}).json()['session_id']
    before=get_session(sid).state['scenario'].model_dump()
    assert c.patch(f'/api/sessions/{sid}/params',json={'path':'data_centers.0.pue','value':.2}).status_code==400
    assert get_session(sid).state['scenario'].model_dump()==before
    assert c.patch(f'/api/sessions/{sid}/model/element/dc/DC',json={'pue':.2}).status_code==400
    assert get_session(sid).state['scenario'].model_dump()==before


def test_no_branch_network_solve_and_ac_are_finite():
    sc=Scenario.model_validate(simple());r=F.eng.solve(sc,True)
    assert r['df'].max_line_loading_pct.max()==0
    ac=F.eng.ac_check(sc,r)
    assert ac['converged'] and ac['loading_ok']
    assert ac['max_line_loading_pct']==0 and ac['max_trafo_loading_pct']==0


def test_weather_carbon_load_signals_change_real_physics():
    d=scene();model=d['draft']['model'];model['thermal_mode']='coupled';model['data_centers'][0]['thermal']={}
    d=upd(d,model=model)
    outputs=[]
    for temp,carbon,load in [(35,.9,10),(5,.2,8)]:
        w=lib('weather',[temp]*24);co=lib('carbon',[carbon]*24);lo=lib('load',[load]*24)
        d=upd(d,bindings=[dict(resource_id=w['id']),dict(resource_id=co['id']),dict(resource_id=lo['id'],target='DC')])
        t=execute(pub(d));assert t['status']=='completed',t.get('error');outputs.append(t)
    assert outputs[1]['result']['cost_cny']<outputs[0]['result']['cost_cny']
    assert outputs[1]['result']['emissions_tco2']<outputs[0]['result']['emissions_tco2']/2
    assert outputs[0]['result']['thermal_safe'] and outputs[1]['result']['thermal_safe']


def test_configuration_builder_writeback_preserves_old_version():
    d=scene();v=pub(d);sid=c.post(P+'/scenarios/'+d['id']+'/checkout',json={}).json()['session_id']
    spec=c.get('/api/config/template').json()['template']
    r=c.post(f'/api/sessions/{sid}/config/build',json={'spec':spec});assert r.status_code==200,r.text
    assert c.get(P+'/sessions/'+sid+'/context').json()['context']['unsaved']
    r=c.post(P+'/sessions/'+sid+'/save-draft',json={'expected_revision':d['revision']});assert r.status_code==200,r.text
    changed=S.get('scenario',d['id'])
    assert S.digest(changed['draft']['model'])==S.digest(get_session(sid).state['scenario'].model_dump())
    assert S.get('version',v['id'])['model']['name']=='single'


def test_transparent_parameter_sheet_shows_pinned_source():
    d=scene();r=lib('price',[.7]*24);d=upd(d,bindings=[{'resource_id':r['id']}]);v=pub(d)
    t=execute(v);assert t['status']=='completed',t.get('error')
    sid=c.post(P+'/tasks/'+t['id']+'/open',json={}).json()['session_id']
    sheet=c.get(f'/api/sessions/{sid}/params').json()
    serialized=str(sheet)
    assert r['id'] in serialized and '固定资源' in serialized


def test_binding_replace_exact_selected_version_and_precise_axis_failure():
    d=scene();public=lib('weather',[30.]*24)
    example=copy.deepcopy(public);example.pop('id');example.pop('hash');example.pop('created');example['name']='示例weather';example['axis']['location']='示例地点';example=F.library_new(example)
    draft_axis=copy.deepcopy(a());draft_axis['location']='示例地点';d=upd(d,axis=draft_axis)
    base=P+'/scenarios/'+d['id']
    r=c.post(base+'/bind',json={'expected_revision':d['revision'],'resource_id':example['id'],'mode':'add'});assert r.status_code==200,r.text
    d=r.json()['scenario'];v=pub(d)
    # Selection differs from saved state until a successful, explicit replacement.
    r=c.post(base+'/bind',json={'expected_revision':d['revision'],'resource_id':public['id'],'mode':'add'});assert r.status_code==400 and '替换' in r.text
    r=c.post(base+'/bind',json={'expected_revision':d['revision'],'resource_id':public['id'],'mode':'replace'});assert r.status_code==400,r.text
    detail=r.json()['detail'];assert detail['code']=='axis_mismatch'
    assert detail['resource']['id']==public['id']
    assert detail['conflicts']==[{'field':'location','expected':'示例地点','actual':'中卫'}]
    assert S.get('scenario',d['id'])==d
    r=c.post(base+'/bind',json={'expected_revision':d['revision'],'resource_id':public['id'],'mode':'replace','align_axis':True});assert r.status_code==200,r.text
    result=r.json();changed=result['scenario']
    assert result['binding']['id']==public['id'] and result['replaced']==[example['id']] and result['axis_changed']
    assert changed['draft']['bindings']==[{'resource_id':public['id'],'target':''}]
    assert changed['draft']['axis']==public['axis']
    v2=pub(changed);t=F.task_new({'version_id':v2['id']})
    assert [r['id'] for r in t['snapshot']['resources']]==[public['id']]
    assert S.get('version',v['id'])['resources'][0]['id']==example['id']


def test_align_binding_conflicts_with_other_data_is_atomic():
    d=scene();price=lib('price');w=lib('weather',[30.]*24)
    other=copy.deepcopy(w);other.pop('id');other.pop('hash');other.pop('created');other['axis']['location']='韶关';other=F.library_new(other)
    d=upd(d,bindings=[{'resource_id':w['id']},{'resource_id':price['id']}])
    r=c.post(P+'/scenarios/'+d['id']+'/bind',json={'resource_id':other['id'],'expected_revision':d['revision'],'mode':'replace','align_axis':True})
    assert r.status_code==400,r.text
    assert r.json()['detail']['resource']['id']==price['id']
    assert r.json()['detail']['conflicts']==[{'field':'location','expected':'韶关','actual':'中卫'}]
    assert S.get('scenario',d['id'])==d


def test_axis_conflict_enumerates_each_field_and_missing_selection_no_fallback():
    d=scene();r=lib('weather');expected=a();actual={k:'DIFFERENT' for k in expected}
    e=F.AxisMismatch(r,expected,actual)
    assert {x['field'] for x in e.detail['conflicts']}==set(expected)
    assert all(x['expected']==expected[x['field']] and x['actual']=='DIFFERENT' for x in e.detail['conflicts'])
    response=c.post(P+'/scenarios/'+d['id']+'/bind',json={'resource_id':'unknown','mode':'add','expected_revision':d['revision']})
    assert response.status_code==404 and S.get('scenario',d['id'])==d


def test_binding_javascript_contract():
    import subprocess
    out=subprocess.run(['node','tests/test_foundation_binding_js.cjs'],capture_output=True,text=True)
    assert out.returncode==0,out.stdout+out.stderr
