from pathlib import Path
import json
from fastapi import APIRouter,HTTPException
from .opt_gpu import GpuModel
router=APIRouter(prefix='/api/opt-gpu',tags=['explicit-gpu-scheduling'])
PRESETS={'synthetic_energy':'SYNTHETIC · 离散帽/同工作/完整能量','synthetic_pause':'SYNTHETIC · 必须暂停/恢复后完成','synthetic_fair':'SYNTHETIC · 明确归一化Flex公平','emerald_calibration':'真实DVFS/SRP标签 + 明示合成工作/闲置假设','emerald_fair':'真实曲线·明确吞吐minimax公平变体','emerald_headroom':'真实曲线·作者公开DVFS-headroom公平离散实现','emerald_heldout':'真实留出动作预测 · 严格验证可能failed'}
@router.get('/presets')
def presets():return [dict(id=k,name=v) for k,v in PRESETS.items()]
@router.get('/presets/{key}')
def preset(key:str):
 if key not in PRESETS:raise HTTPException(404,'unknown GPU preset')
 p=Path(__file__).resolve().parents[1]/'cases/paper_reproduction/phase7'/f'{key}.json';m=GpuModel.model_validate(json.loads(p.read_text()));return dict(model=m.model_dump(),axis=dict(location='显式GPU子系统，不是整DC',year=int(m.start[:4]),timezone='Asia/Shanghai',start=m.start,step_minutes=m.dt_hours*60,length=m.n_steps))
@router.post('/validate')
def validate(raw:dict):
 try:m=GpuModel.model_validate(raw);return dict(ok=True,model_kind='opt_gpu',jobs=len(m.jobs),gpus=len(m.gpus),warnings=['固定校准gang/归一化吞吐，不假设任意GPU数可线性缩放','Flex0不改帽/不暂停，1/2/3在显式3–6h窗口≥90/75/50%；deadline同工作必须完成','吞吐minimax为独立变体；headroom为作者README公开DVFS Fair语义的离散实现，非完整混合暂停/resize算法','功率拟合、留出SLA控制、作者整实验是不同验收；GPU子模型不提供PUE/热安全证明'])
 except ValueError as e:raise HTTPException(400,str(e))
