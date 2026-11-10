"""Public preset/validation surface; execution only through normal versioned tasks."""
import json
from pathlib import Path
from fastapi import APIRouter,HTTPException
from .opt_grid_feedback import GridFeedbackModel
router=APIRouter(prefix='/api/opt-grid-feedback',tags=['endogenous-grid-feedback'])
PRESETS={'benchmark_negative_lmce':'SYNTHETIC · 稳定负LMCE/拥塞/成本与减排冲突','benchmark_congestion':'SYNTHETIC · 三节点拥塞/再出清/预测反例','benchmark_clean':'SYNTHETIC · 零碳/零变化守恒','rts_leap4h':'真实RTS输入 · 2020闰日4小时 · 明示建模变体，非整篇复现'}
@router.get('/presets')
def presets():return [dict(id=k,name=v) for k,v in PRESETS.items()]
@router.get('/presets/{key}')
def preset(key:str):
    if key not in PRESETS:raise HTTPException(404,'unknown preset')
    p=Path(__file__).resolve().parents[1]/'cases/paper_reproduction/phase6'/f'{key}.json'
    if not p.is_file():raise HTTPException(404,'pinned local preset unavailable; no synthetic substitution')
    m=GridFeedbackModel.model_validate(json.loads(p.read_text()));return dict(model=m.model_dump(),axis=dict(location='DC grid feedback '+key,year=int(m.start[:4]),timezone='UTC',start=m.start,step_minutes=60,length=m.n_steps))
@router.post('/validate')
def validate(raw:dict):
    try:
        m=GridFeedbackModel.model_validate(raw);return dict(ok=True,model_kind=m.model_kind,steps=m.n_steps,warnings=['每个成本出清LP最优不代表迭代反馈全局最优','LMCE为当前grid扰动/活跃基所得，负值/不稳/扰动失败均保留；禁止固定外部因子冒充','四信号不同单位；预测减排与ISO重出清实际全系统排放分账','仅<=168小时原输入子集/benchmark、UTC1h、空间流体工作逐小时守恒；非完整8784h或GPU/整数/储能跨时模型'])
    except ValueError as e:raise HTTPException(400,str(e))
