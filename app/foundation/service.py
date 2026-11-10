from __future__ import annotations
import traceback
from ..solver_execution import contextual_task
import copy, hashlib, importlib.metadata, math
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from . import store as S
from ..scenario import Scenario, build_default, load_preset
from ..tools import sdco_engine as eng, model_edit as me

KINDS={'weather':'degC','price':'CNY/kWh','carbon':'tCO2/MWh','load':'MW'}
def required(d, keys):
    for k in keys:
        if k not in d or d[k] is None or d[k]=='': raise ValueError(f'缺少 {k}')
def axis(a):
    if set(a) != {"location","year","timezone","start","step_minutes","length"}: raise ValueError("时间轴仅允许 location/year/timezone/start/step_minutes/length")
    required(a,['location','year','timezone','start','step_minutes','length'])
    if not isinstance(a['location'],str) or not a['location'].strip(): raise ValueError('地点必须为非空名称')
    try: tz=ZoneInfo(a['timezone'])
    except (KeyError,ValueError): raise ValueError('无效IANA时区')
    dt=datetime.fromisoformat(a['start'])
    if dt.tzinfo is None: raise ValueError('start 必须带时区偏移')
    if dt.utcoffset()!=dt.astimezone(tz).utcoffset(): raise ValueError('start 偏移与 timezone 不一致')
    if dt.year!=int(a['year']): raise ValueError('year 与 start 不一致')
    if (a['step_minutes'],a['length']) not in [(60,24),(15,96)]: raise ValueError('日调度支持24点/60分钟或96点/15分钟；请显式预处理，不能自动截断')
    if dt.hour or dt.minute or dt.second or dt.microsecond: raise ValueError('日调度起始时间必须当地零点')
    return a

def validate(sc):
    errors=[]
    if sc.hours!=24: errors.append('原日调度引擎仅支持 hours=24')
    def finite(x):
        if isinstance(x,float) and not math.isfinite(x): errors.append('参数包含非有限值')
        elif isinstance(x,dict):
            for v in x.values(): finite(v)
        elif isinstance(x,list):
            for v in x: finite(v)
    finite(sc.model_dump())
    for d in sc.data_centers:
        if len(d.interactive_mw)!=sc.n_steps or not d.interactive_mw: errors.append(f'{d.name} 负荷点数必须匹配dt'); continue
        if d.cap_it_mw<=0 or d.pue<1 or min(d.interactive_mw)<0 or d.batch_mwh<0: errors.append(f'{d.name} 容量/PUE/负荷不合法')
        if d.power_model=='pdu_pwl':
            points=d.pdu_breakpoints or []
            try:
                us=[float(p['util']) for p in points]; ps=[float(p['power_mw']) for p in points]
                if len(points)<2 or us[0]!=0 or us[-1]!=1 or any(a>=b for a,b in zip(us,us[1:])) or min(ps)<0 or any(a>b for a,b in zip(ps,ps[1:])): errors.append(f'{d.name} 分段曲线必须单调，利用率覆盖0~1')
            except (KeyError,TypeError,ValueError): errors.append(f'{d.name} 分段功率曲线格式错误')
        t=d.thermal
        if t:
            if not t.t_min_c <= t.t0_c <= t.t_allow_max_c or not t.t_min_c<=t.t_rec_max_c<=t.t_allow_max_c: errors.append(f'{d.name} 温度边界不合法')
            if not (0<=t.tes_soc0<=1 and 0<=t.tes_loss_h<=1 and 0<=t.hr_max_frac<=1 and 0<=t.liquid_frac<=1) or t.cop_min>t.cop_max or t.chiller_units<1 or t.free_t_full_c>=t.free_t_zero_c: errors.append(f'{d.name} 冷却边界/SOC/损失参数不合法')
            if min(t.c_air_mwh_k,t.c_mass_mwh_k,t.cop_ref,t.cop_min,t.cop_max,t.hp_cop)<=0 or min(t.chiller_cap_mw_th,t.crah_cap_mw_th,t.free_cap_mw_th,t.hp_cap_mw_th)<0: errors.append(f'{d.name} 热模型参数不合法')
    for group in (sc.data_centers,sc.storage):
        if len({x.name for x in group})!=len(group): errors.append('设备名称重复')
    for s in sc.storage:
        if s.energy_mwh<=0 or s.power_mw<=0 or not 0<s.eta_ch<=1 or not 0<s.eta_dis<=1 or not 0<=s.reserve_frac<=1: errors.append(f'{s.name} 储能参数不合法')
    for p in sc.pv:
        if p.cap_mw<0 or (p.profile is not None and (len(p.profile)!=sc.n_steps or any(not 0<=x<=1 for x in p.profile))): errors.append('风光容量/出力系数不合法')
    if not sc.data_centers: errors.append('场景至少需要一个数据中心')
    if len(sc.outdoor_temp_c)!=sc.n_steps: errors.append('气象点数必须匹配dt')
    for profiles in (sc.outdoor_temp_profiles,sc.outdoor_rh_profiles,sc.carbon_marginal_profiles):
        if any(len(x)!=sc.n_steps for x in profiles.values()): errors.append('区域数据点数必须匹配dt')
    if sc.heat_network:
        hn=sc.heat_network
        if len(hn.demand_mw_th)!=sc.n_steps or min(hn.demand_mw_th)<0 or not 0<=hn.pipe_loss<1 or hn.storage_mwh_th<0 or not 0<=hn.storage_soc0<=1: errors.append('热网需求/储热/损失参数不合法')
    if sc.network:
        for b in sc.network.buses:
            if b.vn_kv<=0: errors.append('母线电压必须为正')
        for g in sc.network.gens:
            if g.pmin_mw<0 or g.pmax_mw<0: errors.append('机组容量不能为负')
        for e in sc.network.ext_grids:
            if e.import_max_mw<0 or e.export_max_mw<0: errors.append('外网容量不能为负')
    if errors: return {'ok':False,'errors':errors,'warnings':[]}
    errors+=eng.validate(sc)
    chk=me.check_model(sc); errors+=chk['errors']
    return {'ok':not errors,'errors':list(dict.fromkeys(errors)),'warnings':chk['warnings']}

def checked(d):
    if d.get('model_kind')=='opt_gpu':
        from ..opt_gpu import GpuModel
        sc=GpuModel.model_validate(d)
        return sc,dict(ok=True,errors=[],warnings=['显式固定gang GPU子系统；不覆盖PUE/热安全，Flex窗口/工作deadline硬约束；公平可选明确吞吐minimax变体/公开DVFS-headroom语义离散实现，不宣称作者完整现场控制器；留出验证失败保留failed'])
    if d.get('model_kind')=='opt_grid_feedback':
        from ..opt_grid_feedback import GridFeedbackModel
        sc=GridFeedbackModel.model_validate(d)
        return sc,dict(ok=True,errors=[],warnings=['独立电网-计算反馈实验；每LP最优不等于闭环全局最优，信号不稳/周期/迭代上限显式显示；仅<=168h1h子集/benchmark，非完整论文全年'])
    if d.get("model_kind")=="opt_cfe":
        from ..opt_cfe import CfeModel
        sc=CfeModel.model_validate(d)
        return sc,{"ok":True,"errors":[],"warnings":["独立年度CFE模式：UTC/1h完整年或明确benchmark；纸面CFE分数是年度累计，非部分目标逐小时下限；不使用24h/AC/三级运行引擎"]}
    sc=Scenario.model_validate(d,extra="forbid"); v=validate(sc)
    if not v['ok']: raise ValueError('；'.join(v['errors']))
    return sc,v

def library_new(b):
    required(b,['name','kind','source','applicability'])
    kind=b['kind']; payload=copy.deepcopy(b)
    if kind in KINDS:
        required(b,['axis','values','unit'])
        axis(b['axis'])
        if b.get('unit')!=KINDS[kind]: raise ValueError(f'单位必须 {KINDS[kind]}')
        vals=b.get('values',[])
        if len(vals)!=b['axis']['length'] or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in vals): raise ValueError('数据点数必须匹配时间轴，有限且无缺失')
        if b.get('timestamps') is not None:
            expected=[(datetime.fromisoformat(b['axis']['start'])+timedelta(minutes=i*b['axis']['step_minutes'])).isoformat() for i in range(b['axis']['length'])]
            if [datetime.fromisoformat(x).isoformat() for x in b['timestamps']]!=expected: raise ValueError('时间戳必须与时间轴逐小时一致，无重复/跳点')
        if kind in ('carbon','load') and min(vals)<0: raise ValueError('碳/负荷不能为负')
        if kind=='weather' and (min(vals)<-90 or max(vals)>65): raise ValueError('气象温度超出可接受范围')
    elif kind=='device':
        required(b,['device_type','parameters','units'])
        allowed={'data_center':{'pue','cap_it_mw','power_model','p_idle_mw','p_peak_mw','pdu_breakpoints','thermal'},'storage':{'energy_mwh','power_mw','eta_ch','eta_dis','soc0','soc_min','soc_max','reserve_frac'}}
        if b['device_type'] not in allowed or not set(b['parameters'])<=allowed[b['device_type']]: raise ValueError('设备类型或参数不支持')
        if not b['parameters'] or any(k not in b['units'] for k in b['parameters']): raise ValueError('每个参数须标注单位（无量纲用1）')
        expected_units={'pue':'1','cap_it_mw':'MW','power_model':'1','p_idle_mw':'MW','p_peak_mw':'MW','pdu_breakpoints':'util:1,power_mw:MW','thermal':'field-specific','energy_mwh':'MWh','power_mw':'MW','eta_ch':'1','eta_dis':'1','soc0':'1','soc_min':'1','soc_max':'1','reserve_frac':'1'}
        for k in b['parameters']:
            if k=='thermal':
                units=b['units'][k]
                th_units={'cop_ref':'1','cop_min':'1','cop_max':'1','free_cop':'1','hp_cop':'1','other_frac':'1','liquid_frac':'1','hr_max_frac':'1','c_air_mwh_k':'MWh_th/K','c_mass_mwh_k':'MWh_th/K','ua_am_mw_k':'MW_th/K','ua_env_mw_k':'MW_th/K','chiller_cap_mw_th':'MW_th','crah_cap_mw_th':'MW_th','free_cap_mw_th':'MW_th','hp_cap_mw_th':'MW_th','tes_mwh_th':'MWh_th','tes_p_mw_th':'MW_th','cop_slope_per_k':'1/K','t0_c':'degC','t_min_c':'degC','t_rec_max_c':'degC','t_allow_max_c':'degC','cooling_mode':'1','heat_rejection':'1'}
                if not isinstance(units,dict) or any(key not in th_units or units.get(key)!=th_units[key] for key in b['parameters'][k]): raise ValueError('thermal 各参数须提供已支持的字段单位映射')
                continue
            if b['units'][k]!=expected_units[k]: raise ValueError(f'{k} 单位必须 {expected_units[k]}')
        probe=build_default(1,50).model_dump()
        group='data_centers' if b['device_type']=='data_center' else 'storage'
        probe[group][0].update(b['parameters']); checked(probe)
        if 'curve' in b: raise ValueError('曲线请使用 parameters.pdu_breakpoints 或 thermal 参数；禁止仅存未接入曲线')
    else: raise ValueError('未知资源类型')
    # A revision points at its immutable predecessor, never replaces it.
    parent=b.get('previous_id')
    if parent:
        old=S.get('library',parent)
        if old['kind']!=kind: raise ValueError('版本类型不可改变')
        payload['revision']=old['revision']+1
    else: payload['revision']=1
    payload.update(id=S.uid(),created=S.now()); payload['hash']=S.digest({k:v for k,v in payload.items() if k not in ('id','created','hash')})
    return S.put('library',payload)

def project_new(b):
    required(b,['name'])
    return S.put('project',dict(id=S.uid(),name=b['name'],documents=b.get('documents',[]),pending=b.get('pending',[]),created=S.now()))

def scenario_new(b):
    required(b,['project_id','name','axis']); S.get('project',b['project_id'])
    if b.get('template_id'): raw=S.get('template',b['template_id'])['model']
    elif b.get('version_id'): raw=S.get('version',b['version_id'])['model']
    else: raw=b.get('model',build_default(1,0).model_dump())
    sc,v=checked(raw)
    if raw.get('model_kind') in ('opt_cfe','opt_grid_feedback','opt_gpu'):
        if raw['model_kind']=='opt_cfe':from ..opt_cfe import check_axis
        elif raw['model_kind']=='opt_grid_feedback':from ..opt_grid_feedback import check_axis
        else:from ..opt_gpu import check_axis
        check_axis(b['axis'],sc)
    else: axis(b['axis'])
    if b['axis']['step_minutes']!=sc.dt_hours*60 or b['axis']['length']!=sc.n_steps: raise ValueError('模型dt/长度与场景时间轴不匹配；必须显式转换模型和时间轴')
    provenance=b.get('provenance',[])
    if b.get('version_id'): provenance=[{'type':'version_copy','version_id':b['version_id'],'source_hash':S.get('version',b['version_id'])['hash']}]
    if b.get('template_id'): provenance=[{'type':'template_copy','template_id':b['template_id'],'source_hash':S.get('template',b['template_id'])['hash']}]
    d=dict(id=S.uid(),project_id=b['project_id'],name=b['name'],draft=dict(model=sc.model_dump(),axis=b['axis'],bindings=[],device_bindings=[],pending=b.get('pending',[]),provenance=provenance),revision=1,created=S.now())
    return S.put('scenario',d)

def expand(draft):
    raw=copy.deepcopy(draft['model']); refs=[]; targets=set()
    if raw.get('model_kind') in ('opt_cfe','opt_grid_feedback','opt_gpu'):
        if raw['model_kind']=='opt_cfe':from ..opt_cfe import check_axis
        elif raw['model_kind']=='opt_grid_feedback':from ..opt_grid_feedback import check_axis
        else:from ..opt_gpu import check_axis
        if draft.get('bindings') or draft.get('device_bindings'): raise ValueError('独立CFE/电网反馈当前仅支持冻结自包含剖面/成本；禁止绑定24h公共信号/日设备，不会隐式扩展成全年')
        sc,v=checked(raw); check_axis(draft['axis'],sc)
        return sc.model_dump(),[],v
    axis(draft['axis'])
    for bind in draft.get('bindings',[]):
        resource=S.get('library',bind['resource_id']); kind=resource['kind']
        if kind not in KINDS: raise ValueError('数据绑定必须引用时间序列资源')
        if resource['axis']!=draft['axis']: raise AxisMismatch(resource,draft['axis'],resource['axis'])
        target=bind.get('target','')
        if kind!='load' and target: raise ValueError('当前气象/电价/碳为场景公共信号，不支持设备级target；请选场景公共信号')
        key=(kind,target)
        if key in targets: raise ValueError('重复数据绑定')
        targets.add(key); vals=resource['values']
        if kind=='price':
            raw['price_cny_kwh']=vals
            for g in (raw.get('network') or {}).get('ext_grids',[]): g['price_cny_kwh']=vals
        elif kind=='weather':
            raw['outdoor_temp_c']=vals; raw['outdoor_temp_profiles']={r:vals for r in raw.get('outdoor_temp_profiles',{})}
        elif kind=='carbon':
            regions=set(raw.get('bus_region',{}).values())|{'national'}
            raw['carbon_profiles']={r:vals for r in regions}; raw['carbon_marginal_profiles']={r:vals for r in regions}; raw['carbon_source']=resource['source']
        elif kind=='load':
            dc=next((d for d in raw['data_centers'] if d['name']==target),None)
            if dc is None: raise ValueError('负荷绑定需要有效数据中心 target')
            dc['interactive_mw']=vals
        raw.setdefault('sources',{})['通用库绑定.'+kind+'.'+(target or '公共')]=f"{resource['source']}；固定资源{resource['id']} r{resource['revision']}；起点{resource['axis']['start']}"
        refs.append(resource)
    if draft.get('bindings'):
        raw['note']=raw.get('note','')+'；【通用库绑定】'+', '.join(S.get('library',b['resource_id'])['kind'] for b in draft['bindings'])+' @ '+draft['axis']['start']+'；未绑定的风光/任务等仍沿原场景，非同日现场实测整套数据'
    for bind in draft.get('device_bindings',[]):
        resource=S.get('library',bind['resource_id'])
        if resource['kind']!='device': raise ValueError('设备绑定必须引用设备模型')
        key=('device',bind['target'])
        if key in targets: raise ValueError('重复设备绑定')
        targets.add(key)
        group='data_centers' if resource['device_type']=='data_center' else 'storage'
        obj=next((d for d in raw[group] if d['name']==bind['target']),None)
        if obj is None: raise ValueError('设备绑定 target 不存在')
        params=resource['parameters']
        if 'thermal' in params: obj['thermal']={**(obj.get('thermal') or {}),**params['thermal']}
        obj.update({k:v for k,v in params.items() if k!='thermal'}); refs.append(resource)
    sc,v=checked(raw)
    if draft['axis']['step_minutes']!=sc.dt_hours*60 or draft['axis']['length']!=sc.n_steps: raise ValueError('模型dt/长度与时间轴不匹配；拒绝隐式重采样')
    return sc.model_dump(),refs,v

def draft_update(id,b):
    d=S.get('scenario',id)
    if b.get('expected_revision')!=d['revision']: raise ValueError('草稿已被其他操作修改，请刷新后重试')
    new=copy.deepcopy(d['draft'])
    if b.get('name'): d['name']=str(b['name'])
    for k in ('model','axis','bindings','device_bindings','pending','provenance'):
        if k in b: new[k]=b[k]
    # Allow explicit pending documentation but reject invalid engineering inputs.
    expand(new); d['draft']=new; d['revision']+=1; d['updated']=S.now()
    return S.put('scenario',d,True)

def publish(id,b):
    d=S.get('scenario',id)
    if b.get('expected_revision')!=d['revision']: raise ValueError('草稿版本冲突')
    if d['draft'].get('pending'): raise ValueError('存在待确认项，先确认再发布')
    model,refs,v=expand(d['draft'])
    versions=[x for x in S.all('version') if x['scenario_id']==id]
    out=dict(id=S.uid(),scenario_id=id,project_id=d['project_id'],name=d['name'],number=len(versions)+1,draft_revision=d['revision'],model=model,axis=d['draft']['axis'],resources=refs,provenance=d['draft'].get('provenance',[]),bindings=d['draft'].get('bindings',[]),device_bindings=d['draft'].get('device_bindings',[]),warnings=v['warnings'],created=S.now())
    out['hash']=S.digest({'model':model,'axis':out['axis'],'resources':refs})
    return S.put('version',out)

def template_new(b):
    required(b,['name','source'])
    raw=S.get('version',b['version_id'])['model'] if b.get('version_id') else b['model']
    sc,v=checked(raw)
    return S.put('template',dict(id=S.uid(),name=b['name'],source=b['source'],assumptions=b.get('assumptions','参考结构，不能替代工程设计审查'),model=sc.model_dump(),hash=S.digest(sc.model_dump()),created=S.now()))

def seed():
    if S.all('template'): return
    items=[('基础单园区',build_default(1,0)),('多数据中心与储能',build_default(3,50))]
    for name,preset in [('风光储直供参考·中卫','zhongwei_summer_coupled'),('余热回收参考·中卫','zhongwei_winter_coupled_heat'),('韶关参考','shaoguan_summer'),('乌兰察布参考','ulanqab_cicdata_summer')]:
        try: items.append((name,load_preset(preset)))
        except ValueError: pass
    for name,sc in items:
        template_new(dict(name=name,model=sc.model_dump(),source=sc.sources or {'code':'app/scenario.py build_default'},assumptions='公开项目资料整理的等值参考/合成工况，非原工程完整接线；'+sc.note))
    a=dict(location='示例地点',year=2024,timezone='Asia/Shanghai',start='2024-07-01T00:00:00+08:00',step_minutes=60,length=24)
    for kind,values in [('weather',[25.]*24),('price',[.3]*8+[.8]*12+[.4]*4),('carbon',[.53]*24),('load',[10.]*24)]:
        library_new(dict(name='示例·'+kind,kind=kind,source='明确合成示例，非现场实测',applicability='示例地点/2024年24小时演示',unit=KINDS[kind],axis=a,values=values))
    library_new(dict(name='示例·储能95%效率',kind='device',device_type='storage',parameters={'eta_ch':.95,'eta_dis':.95},units={'eta_ch':'1','eta_dis':'1'},source='合成设备参考，需厂商/现场标定',applicability='小时级能量模型，不用于电磁暂态'))

def code_identity():
    root=Path(__file__).resolve().parents[1]
    return S.digest({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*.py'))})

def task_new(b, frozen=None):
    if frozen is None:
        required(b,['version_id'])
        v=S.get('version',b['version_id'])
        if S.digest({'model':v['model'],'axis':v['axis'],'resources':v['resources']})!=v['hash']: raise ValueError('场景版本内容与摘要不一致，拒绝创建任务')
        objective=b.get('objective','cost'); cfg=b.get('solver',{})
        if objective not in ('cost','weighted_carbon','carbon','welfare'): raise ValueError('目标支持 cost/weighted_carbon；carbon 请用加权碳目标明确权重，不能冒充纯碳最优')
        if objective=='carbon': raise ValueError('本任务日调度不支持纯碳目标，请使用 weighted_carbon 并明确权重；原多目标工具仍保留')
        if set(cfg)-{'time_limit_s','ac_check'}: raise ValueError('未知求解配置')
        if not 0<float(cfg.get('time_limit_s',120))<=600: raise ValueError('求解时间须在0~600秒')
        model=copy.deepcopy(v['model'])
        weight=float(b.get('carbon_weight',1)) if objective=='weighted_carbon' else 0.
        if not math.isfinite(weight) or weight<0: raise ValueError('碳权重不合法')
        if model.get('model_kind') in ('opt_cfe','opt_grid_feedback','opt_gpu'):
            if objective!='cost' or cfg.get('ac_check',True):raise ValueError('年度CFE仅支持显式cost采购目标且必须关闭日模型AC校核；不冒充24h/三级仿真')
        else:
            model['carbon_weight']=weight
            model['objective_mode']='welfare' if objective=='welfare' else 'cost'
        if model.get('network_domain')=='paper_abstract' and cfg.get('ac_check',True): raise ValueError('paper_abstract 必须显式关闭交流校核')
        checked(model)
        frozen=dict(version_id=v['id'],scenario_id=v['scenario_id'],project_id=v['project_id'],version_number=v['number'],project_documents=S.get('project',v['project_id']).get('documents',[]),scenario_provenance=v.get('provenance',[]),bindings=v.get('bindings',[]),device_bindings=v.get('device_bindings',[]),axis=v['axis'],resources=v['resources'],scenario_hash=v['hash'],model=model,objective=objective,solver={'time_limit_s':float(cfg.get('time_limit_s',120)),'ac_check':bool(cfg.get('ac_check',True))},code_hash=code_identity(),solver_identity={p:importlib.metadata.version(p) for p in ('pyomo','highspy','pandapower')})
    snap=copy.deepcopy(frozen)
    return S.put('task',dict(id=S.uid(),name=b.get('name','仿真任务'),snapshot=snap,input_hash=S.digest(snap),status='ready',created=S.now(),rerun_of=b.get('rerun_of')))

@contextual_task
def execute(id):
    # task unique session prevents editing an active project's model or previous result.
    from ..main import get_session,save_session
    from ..tools.sim_tools import run_dispatch,compute_kpis,run_ac_check
    with S.LOCK:
        t=S.get('task',id)
        if S.digest(t['snapshot'])!=t['input_hash']: raise ValueError('冻结输入摘要不匹配，拒绝求解')
        if t['status']!='ready': raise ValueError('任务已执行/正在执行；历史重跑请创建新任务')
        t['status']='running'; S.put('task',t,True)
    if t['snapshot']['model'].get('model_kind') in ('opt_cfe','opt_grid_feedback','opt_gpu'):
        if t['snapshot']['model']['model_kind']=='opt_cfe':from ..opt_cfe import solve
        elif t['snapshot']['model']['model_kind']=='opt_grid_feedback':from ..opt_grid_feedback import solve
        else:from ..opt_gpu import solve
        try:
            result=solve(t['snapshot']['model'],t['snapshot']['solver'])
            summary={'model_kind':'opt_gpu','objective_value':result['objective_value'],'currency':'USD GPU plan; inspect validation/gap','steps':result['horizon']['steps'],'validation_accepted':result['validation_accepted']} if result['model_kind']=='opt_gpu' else {'model_kind':'opt_cfe','objective_value':result['objective'],'currency':result['currency'],'steps':result['horizon']['steps']} if result['model_kind']=='opt_cfe' else {'model_kind':'opt_grid_feedback','objective_value':result['selected_policy']['final_totals']['cost_usd'],'currency':'USD; experiment NOT global optimum','steps':result['horizon']['steps'],'feedback_status':result['selected_policy']['status']}
            t.update(status='completed',full_result=result,result=summary,completed=S.now(),execution_code_hash=code_identity(),execution_solver_identity={p:importlib.metadata.version(p) for p in ('pyomo','highspy')})
        except Exception as e:
            t.update(status='failed',error=f'{type(e).__name__}: {e}',error_traceback=traceback.format_exc(),completed=S.now(),execution_code_hash=code_identity())
            if getattr(e,'partial_result',None) is not None:t['partial_result']=e.partial_result
        t=pack(t);S.put('task',t,True);return t
    s=get_session('pf'+id); t['session_id']=s.id
    try:
        snap=t['snapshot']; s.state['scenario']=Scenario.model_validate(snap['model']); s.state['solver_cfg']=snap['solver']; s.state['title']=t['name']
        s.state['foundation_task_id']=id
        s.state['origin']={'kind':'preset','name':'固定场景版本 '+snap['version_id']}
        s.state['param_src']=parameter_sources(snap)
        Path(s.artifact_dir).mkdir(parents=True,exist_ok=True)
        Path(s.artifact_dir,'scenario.json').write_text(s.state['scenario'].model_dump_json(indent=2))
        from ..tools.sim_tools import _art
        import json
        Path(_art(s,'input_snapshot.json')).write_text(json.dumps(snap,ensure_ascii=False,indent=2))
        out=run_dispatch(s); k=compute_kpis(s)
        ac=run_ac_check(s) if snap['solver']['ac_check'] else None
        t.update(status='completed',full_result=pack(s.state['results']['optimized']),result=out,kpis=k,ac=ac,dispatch=s.state['results']['optimized']['df'].to_dict(orient='list'),completed=S.now(),execution_code_hash=code_identity(),execution_solver_identity={p:importlib.metadata.version(p) for p in ('pyomo','highspy','pandapower')})
    except Exception as e:
        t.update(status='failed',error=f'{type(e).__name__}: {e}',error_traceback=traceback.format_exc(),completed=S.now())
    save_session(s); t=pack(t); S.put('task',t,True)
    return t

def pack(x):
    """Lossless tabular result persistence (non-finite diagnostics become null)."""
    import numpy as np
    import pandas as pd
    if isinstance(x,pd.DataFrame): return {'__dataframe__':True,'columns':list(x.columns),'data':pack(x.values.tolist())}
    if isinstance(x,np.ndarray): return pack(x.tolist())
    if isinstance(x,np.generic): return pack(x.item())
    if isinstance(x,float) and not math.isfinite(x): return None
    if isinstance(x,dict): return {str(k):pack(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [pack(v) for v in x]
    return x

def unpack(x):
    import pandas as pd
    if isinstance(x,dict) and x.get('__dataframe__') is True: return pd.DataFrame(x['data'],columns=x['columns'])
    if isinstance(x,dict): return {k:unpack(v) for k,v in x.items()}
    if isinstance(x,list): return [unpack(v) for v in x]
    return x

def seed_public_climate():
    """Publish existing public cache as traceable daily resources; never downloads."""
    import json
    root=Path(__file__).resolve().parents[2]
    for site,location in [('zhongwei','中卫'),('shaoguan','韶关'),('ulanqab','乌兰察布')]:
        key='openmeteo_'+site+'_20240701'
        if any(r.get('seed_key')==key for r in S.all('library')): continue
        path=root/'cases'/'common'/'climate'/f'{site}_2024-01-01_2024-12-31.json'
        if not path.is_file(): continue
        raw=json.loads(path.read_text()); h=raw['hourly']; idx=h['time'].index('2024-07-01T00:00')
        library_new(dict(name=f'公开气象·{location}·2024-07-01',kind='weather',unit='degC',values=h['temperature_2m'][idx:idx+24],axis=dict(location=location,year=2024,timezone='Asia/Shanghai',start='2024-07-01T00:00:00+08:00',step_minutes=60,length=24),source=raw.get('_url','https://open-meteo.com/en/docs/historical-weather-api'),applicability='ERA5历史再分析室外2m干球温度，非园区传感器测量；不能等同实测机房入口温度',seed_key=key,original_file=str(path.relative_to(root)),original_file_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))

def recover_interrupted_tasks():
    """A restarted local process cannot still own an old in-flight task."""
    for task in S.all('task'):
        if task['status']=='running':
            task.update(status='failed',error='服务重启，中断任务未自动重试；请从原快照创建重跑',completed=S.now())
            S.put('task',task,True)

def parameter_sources(snapshot):
    """Exact pinned-resource provenance for the existing transparent parameter UI."""
    refs={r['id']:r for r in snapshot.get('resources',[])};model=snapshot['model'];out={}
    def note(r):
        source=str(r['source']);tag='案例假设' if any(x in source for x in ('假设','合成','示例')) else ('公开资料' if 'http' in source else '用户指定')
        return {'tag':tag,'note':f"固定资源 {r['name']} r{r['revision']} ({r['id']})；{source}；工况：{r['applicability']}"}
    for b in snapshot.get('bindings',[]):
        r=refs.get(b['resource_id'])
        if not r: continue
        kind=r['kind'];paths={'weather':['outdoor_temp_c','outdoor_temp_profiles'],'price':['price_cny_kwh'],'carbon':['carbon_profiles','carbon_marginal_profiles','carbon_source']}.get(kind,[])
        if kind=='load': paths=[f'data_centers.{i}.interactive_mw' for i,d in enumerate(model['data_centers']) if d['name']==b.get('target')]
        if kind=='price': paths += [f'network.ext_grids.{i}.price_cny_kwh' for i,_ in enumerate((model.get('network') or {}).get('ext_grids',[]))]
        for path in paths: out[path]=note(r)
    for b in snapshot.get('device_bindings',[]):
        r=refs.get(b['resource_id'])
        if not r: continue
        group='data_centers' if r['device_type']=='data_center' else 'storage'
        for i,d in enumerate(model[group]):
            if d['name']!=b['target']: continue
            for key,value in r['parameters'].items():
                paths=[f'{group}.{i}.{key}.{sub}' for sub in value] if key=='thermal' else [f'{group}.{i}.{key}']
                for path in paths: out[path]=note(r)
    return out

class AxisMismatch(ValueError):
    def __init__(self,resource,expected,actual):
        fields=['location','year','timezone','start','step_minutes','length']
        self.detail={'code':'axis_mismatch','resource':{k:resource[k] for k in ('id','name','revision')},'conflicts':[{'field':k,'expected':expected.get(k),'actual':actual.get(k)} for k in fields if expected.get(k)!=actual.get(k)]}
        self.detail['message']=f"所选资源 {resource['name']} r{resource['revision']} ({resource['id']}) 与场景时间轴不一致；未保存绑定，也未改变历史版本。"+'；'.join(f"{x['field']}: 期待（场景）={x['expected']!r}，实际（数据）={x['actual']!r}" for x in self.detail['conflicts'])
        super().__init__(self.detail['message'])

def bind_resource(id,b):
    required(b,['resource_id','mode','expected_revision'])
    d=S.get('scenario',id);resource=S.get('library',b['resource_id']);target=b.get('target','');mode=b['mode']
    if mode not in ('add','replace'): raise ValueError('mode 必须为 add 或 replace')
    if resource['kind']!='device' and resource['kind']!='load' and target: raise ValueError('气象/电价/碳仅支持场景公共信号')
    key='device_bindings' if resource['kind']=='device' else 'bindings';old=d['draft'].get(key,[])
    def same(binding):
        r=S.get('library',binding['resource_id'])
        if r['kind']!=resource['kind']: return False
        if r['kind']=='device': return r['device_type']==resource['device_type'] and binding.get('target','')==target
        return r['kind']!='load' or binding.get('target','')==target
    previous=[x for x in old if same(x)]
    if mode=='add' and previous: raise ValueError('同类/同目标已有绑定；请显式选择“替换同类绑定”，不会自动叠加或覆盖')
    if mode=='replace' and not previous: raise ValueError('没有同类/同目标绑定；请使用“新增绑定”')
    update={'expected_revision':b['expected_revision'],key:[x for x in old if not same(x)]+[{'resource_id':resource['id'],'target':target}]}
    align=bool(b.get('align_axis'))
    if align:
        if resource['kind']=='device': raise ValueError('设备性能模型无时间轴，不能对齐场景时间轴')
        update['axis']=copy.deepcopy(resource['axis'])
    changed=draft_update(id,update)
    return {'scenario':changed,'binding':{k:resource[k] for k in ('id','name','revision','kind')},'replaced':[S.get('library',x['resource_id'])['id'] for x in previous],'axis_changed':align and d['draft']['axis']!=changed['draft']['axis']}
