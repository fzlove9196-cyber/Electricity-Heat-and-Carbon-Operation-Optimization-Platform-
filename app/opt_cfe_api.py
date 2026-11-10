"""Annual procurement contracts/presets; runs use normal immutable foundation jobs."""
import json
from pathlib import Path
from fastapi import APIRouter,HTTPException
from .opt_cfe import CfeModel
router=APIRouter(prefix='/api/opt-cfe',tags=['annual-cfe'])
PRESETS={'riepin8760_f0':'原作者输入全年8760 · f0 · 发布代码有效拓扑','riepin8760_f40':'原作者输入全年8760 · f40 · 发布代码有效拓扑（DSM被剥离）','riepin8760_f40_manuscript':'同原作者输入全年8760 · f40 · 论文式6日内DSM（不同于发布剥离拓扑）'}
@router.get('/presets')
def presets():return [{'id':k,'name':v,'scope':'AUTHOR_ORIGINAL_INPUT_FULL_8760'} for k,v in PRESETS.items()]
@router.get('/presets/{key}')
def preset(key:str):
    if key not in PRESETS:raise HTTPException(404,'未知公开预设')
    p=Path(__file__).resolve().parents[1]/'cases/paper_reproduction/phase5'/f'{key}.json'
    if not p.is_file():raise HTTPException(404,'公开原输入预设尚未安装；请导入完整自包含JSON，不会合成代替')
    m=CfeModel.model_validate(json.loads(p.read_text())).model_dump()
    return dict(model=m,axis=dict(location='DK1/DE1/PT1 bidding zones',year=m['weather_year'],timezone='UTC',start=m['start'],step_minutes=60,length=len(m['sites'][0]['load_mw'])))
@router.post('/validate')
def validate(raw:dict):
    try:
        sc=CfeModel.model_validate(raw)
        return dict(ok=True,mode=sc.model_kind,steps=sc.n_steps,horizon=sc.horizon_mode,units='MW/MWh; capacity annual currency; operating currency/MWh; UTC1h',warnings=['paper_cfe_score部分目标是年积分并逐小时剔除超额，不是每小时下限；100%才逐时无缺口','明确自包含全年输入，暂不使用日资源库绑定、AC、三级运行、整数任务、内生LMCE或GPU模式'])
    except ValueError as e:raise HTTPException(400,str(e))
