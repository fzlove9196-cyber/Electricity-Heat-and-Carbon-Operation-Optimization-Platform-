"""场景 JSON Schema（pydantic）。所有默认数据均为合成示例数据（SYNTHETIC）。"""
from __future__ import annotations
from typing import Dict, List, Optional, Literal
import numpy as np
from pydantic import BaseModel, Field, model_validator

H = 24
_hrs = np.arange(H)

def tou_price(kind: str = "peak_valley") -> List[float]:
    """CNY/kWh，合成峰谷电价。"""
    if kind == "flat":
        return [0.65] * H
    return [0.30]*7 + [0.65]*3 + [1.05]*2 + [0.65]*5 + [1.05]*5 + [0.30]*2

def pv_shape() -> np.ndarray:
    return np.clip(np.sin((_hrs - 6) / 12 * np.pi), 0, None)

def gauss(base, amp, center, width):
    return list(base + amp*np.exp(-((_hrs-center)/width)**2))

class DataCenter(BaseModel):
    name: str
    bus: int = Field(description="IEEE14 母线编号 (0-index)")
    cap_it_mw: float = 30.0
    pue: float = 1.35
    interactive_mw: List[float] = Field(default_factory=lambda: [10.0]*H, description="交互式负载 IT MW, 24 点")
    batch_mwh: float = 150.0
    pf_q_ratio: float = 0.2
    # ---- IT 硬件功率模型（缺省 identity = 旧行为：P_IT = IT 工作功率）----
    power_model: Literal["identity", "idle_dynamic", "pdu_pwl"] = Field(
        "identity", description="identity=P_IT=IT工作功率（旧）；idle_dynamic=P_idle+(P_peak-P_idle)·u；pdu_pwl=分段线性")
    p_idle_mw: Optional[float] = Field(None, description="站点级空载功率 MW（全开机 idle）；与 p_peak_mw 成对；unset=不启用硬件层")
    p_peak_mw: Optional[float] = Field(None, description="站点级满载功率 MW（u=1）；unset=不启用")
    p_idle_kw: Optional[float] = Field(None, description="单机 idle kW；与 n_servers、p_peak_kw 合用换算站点 MW")
    p_peak_kw: Optional[float] = Field(None, description="单机峰值 kW")
    n_servers: Optional[int] = Field(None, description="服务器台数（与 p_idle_kw/p_peak_kw 合用）")
    pdu_breakpoints: Optional[List[dict]] = Field(
        None, description="PDU 分段线性断点 [{util:0..1, power_mw:float}, ...]；power_model=pdu_pwl 时用")
    thermal: Optional["DCThermal"] = Field(None, description="热管理/冷却/余热参数；thermal_mode='coupled' 时生效，None=沿用常数 PUE")

class DCThermal(BaseModel):
    """数据中心集总 RC 热模型 + 冷却系统 + 冷/热储 + 余热回收（算-电-热耦合）。MW_th = 热功率 MW。"""
    c_air_mwh_k: float = Field(0.8, description="机房空气+机柜（快节点）热容 MWh_th/K")
    c_mass_mwh_k: float = Field(6.0, description="建筑结构/机架（慢节点）热容 MWh_th/K")
    ua_am_mw_k: float = Field(4.0, description="空气-结构换热系数 MW_th/K")
    ua_env_mw_k: float = Field(0.15, description="围护结构与室外换热系数 MW_th/K")
    t0_c: float = Field(24.0, description="初始/设定送风（入口）温度 °C（基线定值运行）")
    t_min_c: float = Field(18.0, description="入口温度下限 °C（ASHRAE 推荐下限）")
    t_rec_max_c: float = Field(27.0, description="ASHRAE 推荐上限 °C（超出部分软惩罚）")
    t_allow_max_c: float = Field(32.0, description="允许上限 °C（A1 级，硬约束）")
    ramp_max_k_h: float = Field(5.0, description="入口温度最大变化率 K/h（硬约束）")
    rec_exceed_penalty_cny_kh: float = Field(300.0, description="超出推荐上限的惩罚 元/(K·h)")
    chiller_cap_mw_th: float = Field(120.0, description="冷机总装机冷量 MW_th（含备用）")
    chiller_units: int = Field(4, description="冷机台数（N+1：可用 = 装机×(n−1)/n）")
    redundancy_n1: bool = True
    crah_cap_mw_th: float = Field(130.0, description="末端（CRAH/列间空调）最大排热能力 MW_th")
    cop_ref: float = Field(5.5, description="冷机参考 COP（室外 25°C）")
    cop_t_ref_c: float = 25.0
    cop_slope_per_k: float = Field(0.12, description="室外温度每升高 1K COP 下降量")
    cop_min: float = 2.5
    cop_max: float = 8.0
    tower_pump_kw_per_kw: float = Field(0.025, description="冷却塔风机+冷冻/冷却水泵 kW_e/kW_th")
    free_cap_mw_th: float = Field(80.0, description="自然冷却（板换/间接蒸发）最大冷量 MW_th")
    free_t_full_c: float = Field(8.0, description="室外 ≤ 此温度：自然冷却满出力")
    free_t_zero_c: float = Field(18.0, description="室外 ≥ 此温度：无自然冷却")
    free_cop: float = Field(20.0, description="自然冷却电效率 kW_th/kW_e（风机水泵）")
    other_frac: float = Field(0.05, description="配电/UPS 损耗+照明等占 IT 比例")
    tes_mwh_th: float = Field(0.0, description="冷水/冰蓄冷罐容量 MWh_th（0=无）")
    tes_p_mw_th: float = Field(0.0, description="蓄冷罐充/放冷功率上限 MW_th")
    tes_loss_h: float = Field(0.005, description="蓄冷罐每小时自损失比例")
    tes_soc0: float = 0.5
    hp_cap_mw_th: float = Field(0.0, description="余热回收热泵最大供热 MW_th（0=无）")
    hp_cop: float = Field(4.0, description="热泵供热 COP（供热量/耗电）")
    hr_max_frac: float = Field(0.6, description="可回收余热占 IT 发热比例上限")
    # ---- 散热方式库（cooling.py）：None=沿用上面的通用冷机/自然冷却参数 ----
    cooling_mode: Optional[str] = Field(None, description="散热方式：air_chw/air_iec/air_dec/liquid_cold_plate/liquid_immersion/hybrid；None=通用参数")
    liquid_frac: float = Field(0.0, description="液冷承担的 IT 发热比例（hybrid/冷板时有效；其余由风冷残余系统承担）")
    heat_rejection: Optional[str] = Field(None, description="液冷一次侧排热：dry=干冷器（按干球）/wet=闭式冷却塔（按湿球）/hybrid=干湿联合（取较优）；None=按散热方式库（dry）")
    air_residual_mode: str = Field("air_iec", description="液冷/混合模式中残余风冷部分采用的风冷方式")
    wue_l_kwh: Optional[float] = Field(None, description="WUE 覆盖值 L/kWh_IT（None=按散热方式库）")
    waste_heat_c: Optional[float] = Field(None, description="余热源温度覆盖值 °C（None=按散热方式：风冷回风/冷凝 30-40，冷板 45-55，浸没 50-60）")
    racks: Optional[int] = Field(None, description="机柜数（信息；功率密度=IT/机柜）")
    utilization: Optional[float] = Field(None, description="平均 IT 利用率（信息/构建器用）")

class Storage(BaseModel):
    name: str = "ESS_1"
    bus: int = 4
    energy_mwh: float = 50.0
    power_mw: float = 12.5
    eta_ch: float = 0.95
    eta_dis: float = 0.95
    soc0: float = 0.5
    soc_min: float = 0.1
    soc_max: float = 0.95
    kind: Literal["ess", "ups"] = Field("ess", description="ess=站用储能；ups=可调度 UPS/EUPS（默认与 ess 同动力学，可另设备用 SOC 底线）")
    reserve_frac: float = Field(0.0, description="UPS 经济调度保留备用比例：ops_soc_min = soc_min + reserve_frac×(soc_max-soc_min)；emergency 时退回 soc_min")
    source_note: str = Field("", description="参数来源/【假设】说明")

class PV(BaseModel):
    """新能源（风/光）。kind 缺省时按出力曲线自动判断（夜间有出力→风电）。ppa_price_cny_kwh：PPA/直供结算价（对实际利用电量计费）。"""
    bus: int
    cap_mw: float
    profile: Optional[List[float]] = None  # 0-1 出力系数，缺省为合成正弦曲线
    kind: Optional[Literal["wind", "pv"]] = None
    name: str = ""
    ppa_price_cny_kwh: Optional[float] = None
    lifecycle_tco2e_mwh_profile: Optional[List[float]] = Field(None, description="混合 VRE 逐小时生命周期强度 tCO2e/MWh；非运行碳")
    lifecycle_tco2e_mwh: float = Field(0.0, ge=0, allow_inf_nan=False, description="可选生命周期强度 tCO2e/MWh；不改变运行碳")
    ppa_take_or_pay: bool = Field(True, description="PPA 照付不议：按可发电量结算（弃电不省钱）；False=按实际利用电量结算")

class Job(BaseModel):
    """任务级批处理作业（IT 侧能量）。release/deadline 为小时（deadline 为截止小时，不含该小时：可运行区间 [release, deadline)）。"""
    id: str
    dc: str = Field(description="归属（来源）数据中心名称")
    release: int | float = 0
    deadline: int | float = 24
    energy_mwh: float = Field(description="IT 能量 MWh")
    max_mw: float = Field(description="单小时最大 IT 功率 MW")
    allowed_dcs: Optional[List[str]] = Field(default=None, description="允许运行的数据中心；None=全部（仍受链路/时延约束）")
    max_latency_ms: Optional[float] = Field(default=None, description="时延敏感：迁移链路时延不得超过该值；None=不敏感")
    value_cny_mwh: Optional[float] = Field(None, ge=0, allow_inf_nan=False, description="接纳任务福利报价；welfare 必须显式给出")
    execution_mode: Literal["energy", "continuous"] = "energy"
    duration_h: Optional[float] = None
    initial_progress_h: float = 0.0
    initial_dc: Optional[str] = None
    allow_restart: bool = False
    restart_delay_h: float = 0.0
    cancellation_penalty_cny: float = Field(0.0, ge=0)
    required: bool = False
    source: str = "synthetic"

class Link(BaseModel):
    """数据中心间迁移链路（双向）。bw_mw: 每小时可迁移 IT 功率上限 MW（带宽折算）；latency_ms: 单向时延。"""
    a: str
    b: str
    latency_ms: float = 10.0
    bw_mw: float = 5.0
    fee_cny_mwh: float = Field(0.0, ge=0, allow_inf_nan=False)

class HeatNode(BaseModel):
    """多节点热网中的热母线/用户节点。nodes 为空时 HeatNetwork 退化为单节点旧模型。"""
    id: str
    name: str = ""
    demand_mw_th: List[float] = Field(default_factory=lambda: [0.0]*H, description="该节点逐时可接纳/需求热负荷 MW_th")
    storage_mwh_th: float = 0.0
    storage_p_mw_th: float = 0.0
    storage_loss_h: float = 0.01
    storage_soc0: float = 0.5
    t_supply_min_c: Optional[float] = Field(None, description="节点末端供水下限 °C（可选校核）")
    t_supply_max_c: Optional[float] = Field(None, description="节点末端供水上限 °C")

class HeatPipe(BaseModel):
    """热网管段：小时级输送时延 + 比例热损（LP 可表达）。"""
    name: str = ""
    frm: str = Field(..., description="起点节点 id")
    to: str = Field(..., description="终点节点 id")
    capacity_mw_th: float = Field(1e4, description="管段热功率上限 MW_th")
    loss: float = Field(0.02, description="管段热损失比例（到达量=(1-loss)×送出）")
    delay_h: int = Field(0, description="输送时延（整小时，0=瞬时）")

class HeatNetwork(BaseModel):
    """区域供热网络（余热回收对象）。heat demand 为可接纳的余热负荷（其余由锅炉补足）。"""
    name: str = "district_heat"
    dcs: List[str] = Field(default_factory=list, description="接入供热网的数据中心；空=所有配置热泵的 DC")
    demand_mw_th: List[float] = Field(default_factory=lambda: [0.0]*H, description="逐时可接纳热负荷 MW_th")
    price_cny_mwh_th: float = Field(200.0, description="余热售热价格 元/MWh_th")
    boiler_ef_t_mwh_th: float = Field(0.40, description="被替代锅炉排放因子 tCO2/MWh_th（燃煤≈0.40，燃气≈0.22）")
    pipe_loss: float = Field(0.05, description="管网热损失比例")
    storage_mwh_th: float = Field(0.0, description="热网热惯性/蓄热罐等效容量 MWh_th（虚拟储热）")
    storage_p_mw_th: float = Field(0.0, description="蓄热功率上限 MW_th")
    storage_loss_h: float = Field(0.01, description="蓄热每小时损失比例")
    storage_soc0: float = 0.5
    # ---- 余热品位与供热末端（heat_grade.py）；terminal_type=None 时沿用常数 COP/pipe_loss 旧模型 ----
    terminal_type: Optional[str] = Field(None, description="供热末端：floor(地暖35-45)/fcu(风机盘管45-55)/radiator(散热器60-75)/primary(城市一次网70-110)")
    t_supply_min_c: Optional[float] = Field(None, description="末端要求供水温度（室外温度≥15°C 时）°C；None=按末端类型")
    t_supply_max_c: Optional[float] = Field(None, description="末端要求供水温度（室外设计温度时）°C；None=按末端类型")
    t_return_c: Optional[float] = Field(None, description="回水温度 °C；None=按末端类型")
    t_out_design_c: float = Field(-12.0, description="供暖室外计算温度 °C（中卫约 -12）")
    pipe_length_km: float = Field(0.0, description="输热管线长度 km（单程）")
    pipe_dt_k_per_km: float = Field(0.3, description="沿程温降 K/km（保温良好大管径 0.1-0.3；小流量/老旧 0.5-1）")
    pipe_loss_per_km: float = Field(0.006, description="沿程热损失 比例/km（另加 pipe_loss 作为站内/二次网基础损失）")
    hx_approach_k: float = Field(3.0, description="板换端差 K（直接换热需 T_源 ≥ T_需 + 端差）")
    hp_eta_carnot: float = Field(0.5, description="热泵卡诺效率 η（COP=η·T_sink/(T_sink−T_evap)），典型 0.45-0.6")
    hp_max_out_c: float = Field(80.0, description="热泵最高出水温度 °C（常规 ~80，高温热泵 ~90-100）")
    hp_evap_approach_k: float = Field(5.0, description="蒸发器端差 K")
    booster: str = Field("gas_boiler", description="温度不足时的调峰补热：gas_boiler / electric / none")
    booster_price_cny_mwh_th: float = Field(280.0, description="燃气调峰锅炉热成本 元/MWh_th（≈天然气 3 元/m³÷(9.8kWh×0.92)）")
    booster_ef_t_mwh_th: float = Field(0.22, description="燃气锅炉排放因子 tCO2/MWh_th")
    ref_heat_price_cny_gj: float = Field(45.0, description="对标热价 元/GJ（燃煤热电联产趸售≈30-45；燃气锅炉≈75-90）")
    demand_mode: str = Field("given", description="given=用 demand_mw_th；degree_hour=按度时法由 design_load 与室外温度生成")
    design_load_mw_th: float = Field(0.0, description="设计热负荷 MW_th（degree_hour 模式）")
    dhw_share: float = Field(0.1, description="生活热水等基础热负荷占设计负荷比例")
    # ---- 多节点热网（可选；空=单节点旧行为）----
    nodes: List[HeatNode] = Field(default_factory=list, description="热母线/负荷节点；空列表=单节点")
    pipes: List[HeatPipe] = Field(default_factory=list, description="管段（含时延）")
    inject_at: Dict[str, str] = Field(default_factory=dict, description="DC 名 → 注入节点 id；缺省=nodes[0].id 或隐式 plant")

class DREvent(BaseModel):
    """电网需求响应事件。kind=reduce 削峰（相对基线减少用电）；increase 填谷（相对基线增加用电）。"""
    name: str = "DR"
    start: int | float = 18
    end: int | float = 21
    kind: Literal["reduce", "increase"] = "reduce"
    request_mw: float = 30.0
    price_cny_mwh: float = Field(1500.0, description="补偿价格 元/MWh（按实际响应量）")
    baseline_method: Literal["plan", "bau", "given"] = Field("plan", description="plan=无 DR 时的优化计划曲线；bau=常数 PUE 基线（无协同）曲线；given=baseline_mw 给定")
    baseline_mw: Optional[List[float]] = None
    dcs: List[str] = Field(default_factory=list, description="参与 DC，空=全部")
    storages: List[str] = Field(default_factory=list, description="计入响应的表后储能（与 DC 同一计量关口）名称；其净放电计为负荷削减")
    max_mw: Optional[float] = Field(None, description="可响应容量上限 MW（申报能力）；None=不限")
    mandatory: bool = Field(False, description="True=必须达到 request_mw（硬约束）")
    shortfall_penalty_cny_mwh: float = Field(0.0, description="未达申报量的考核 元/MWh")

class NetBus(BaseModel):
    name: str
    vn_kv: float

class NetLine(BaseModel):
    """等值线路。rating_mva 为单回热稳定额定值（DC-OPF 约束 = rating_mva × parallel）。"""
    name: str = ""
    from_bus: int
    to_bus: int
    length_km: float
    r_ohm_per_km: float = 0.03
    x_ohm_per_km: float = 0.30
    c_nf_per_km: float = 12.0
    rating_mva: float
    parallel: int = 1
    service_fee_cny_mwh: float = Field(0.0, ge=0, allow_inf_nan=False)

class NetTrafo(BaseModel):
    name: str = ""
    hv_bus: int
    lv_bus: int
    sn_mva: float
    vk_percent: float = 14.0
    vkr_percent: float = 0.3
    parallel: int = 1

class NetGen(BaseModel):
    """自定义网络中的可调度电源（水电/火电/燃气/光热/柴发等）。energy_mwh_day：日可用电量上限（水电来水约束），None=不限。"""
    name: str = "G"
    bus: int
    kind: Literal["hydro", "thermal", "gas", "csp", "diesel", "other"] = "thermal"
    pmax_mw: float
    pmin_mw: float = 0.0
    cost_cny_mwh: float = 300.0
    emission_t_mwh: float = 0.0
    energy_mwh_day: Optional[float] = None
    vm_pu: Optional[float] = Field(None, description="交流校核电压设定（PV 节点）；None=仅有功注入")
    ramp_mw_h: Optional[float] = Field(None, description="爬坡上限 MW/h；None=不限制（简化连续模型）")
    startup_cost_cny: float = Field(0.0, description="启停成本（简化：计入固定项仅作透明参数；默认 0 不进目标，避免引入二进制）")
    min_up_h: int = Field(0, description="最小连续出力小时（简化：0=不建模二进制启停）")
    dispatch_mode: Literal["economic", "emergency_only", "peak_shave"] = Field(
        "economic", description="economic/peak_shave=可参与日常调度；emergency_only=仅 emergency_mode/roll.emergency 时可用")
    source_note: str = Field("", description="参数来源/【假设】说明")

class NetLoad(BaseModel):
    """常规负荷（按系统日负荷曲线 load_profile 缩放，p_mw 为基准值）。"""
    name: str = "load"
    bus: int
    p_mw: float
    q_mvar: float = 0.0

class NetExtGrid(BaseModel):
    """外部电网（购电点）。price_cny_kwh 缺省用场景 price_cny_kwh；export_max_mw>0 允许反送（售电价 export_price_cny_kwh）。"""
    bus: int
    name: str = "grid"
    vm_pu: float = 1.0
    import_max_mw: float = 1e4
    price_cny_kwh: Optional[List[float]] = None
    export_max_mw: float = 0.0
    export_price_cny_kwh: Optional[List[float]] = None
    demand_charge_cny_mw_day: float = Field(0.0, description="需量电费折算到日 元/MW·日（两部制：月需量电价/30）；对日最大购电功率计费")

class CustomNetwork(BaseModel):
    """自定义等值网络（network_case='custom'）。母线按列表顺序编号 0..n-1。"""
    buses: List[NetBus]
    lines: List[NetLine] = Field(default_factory=list)
    trafos: List[NetTrafo] = Field(default_factory=list)
    ext_grids: List[NetExtGrid] = Field(default_factory=list)
    gens: List[NetGen] = Field(default_factory=list)
    loads: List[NetLoad] = Field(default_factory=list)
    note: str = ""

class Scenario(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def forbid_annual_in_daily(cls,value):
        if isinstance(value,dict) and value.get("model_kind") is not None:
            raise ValueError("显式model_kind不能进入24h日调度；年度opt_cfe请走普通项目的年度CFE入口，不截断/忽略为日模型")
        return value

    dt_hours: Literal[1.0, 0.25] = 1.0
    migration_cleanup: Literal["off", "lexicographic_gross"] = "off"
    migration_cleanup_tolerance_cny: float = Field(0.0, ge=0, le=1e-4, allow_inf_nan=False)

    @property
    def n_steps(self):
        return int(round(self.hours / self.dt_hours))

    objective_mode: Literal["cost", "welfare"] = "cost"
    migration_fee_basis: Literal["gross", "net"] = "gross"
    network_domain: Literal["physical", "paper_abstract"] = "physical"
    lifecycle_enabled: bool = False
    lifecycle_embodied_t_per_year: float = Field(0.0, ge=0, allow_inf_nan=False)
    lifecycle_year_hours: int = Field(8760, ge=24)
    lifecycle_counterfactual: Literal["none", "jobs_origin_uniform"] = "none"
    name: str = "sdco_ieee14"
    synthetic: bool = True
    note: str = "ALL DEFAULT DATA ARE SYNTHETIC EXAMPLE DATA / 默认数据均为合成示例数据"
    network_case: Literal["case14", "custom"] = "case14"
    network: Optional[CustomNetwork] = Field(None, description="network_case='custom' 时的等值网络")
    sources: Dict[str, str] = Field(default_factory=dict, description="参数来源说明（key -> URL/说明）")
    hours: int = H
    price_kind: str = "peak_valley"
    price_cny_kwh: List[float] = Field(default_factory=tou_price)
    grid_markup_cny_mwh: float = 50.0
    data_centers: List[DataCenter] = Field(default_factory=list)
    storage: List[Storage] = Field(default_factory=list)
    pv: List[PV] = Field(default_factory=list)
    mig_max_mw: float = 8.0
    mig_day_share: float = 0.4
    pv_curtail_penalty: float = 500.0
    gen_cost: List[float] = Field(default_factory=lambda: [420, 480, 600, 650])
    gen_min_share: float = 0.25
    load_scale: float = 1.0
    # ---- Phase 1：碳感知双目标（默认 carbon_weight=0 与旧版目标一致）----
    carbon_factor: float = Field(0.5306, description="全国电网平均排放因子 kgCO2/kWh（=tCO2/MWh），生态环境部 2023")
    carbon_shape: Literal["solar_dip", "flat"] = Field("solar_dip", description="合成日内形状（SYNTHETIC）")
    carbon_profiles: Dict[str, List[float]] = Field(default_factory=dict, description="区域 -> 24 点碳强度 tCO2/MWh；缺省用 factor×形状")
    bus_region: Dict[int, str] = Field(default_factory=dict, description="母线 -> 区域名，缺省 national")
    carbon_source: str = "synthetic"
    carbon_price_cny_t: float = Field(100.0, description="碳价 元/tCO2")
    carbon_weight: float = Field(0.0, description="目标 = 成本 + w × 碳价 × 排放；0=纯成本")
    carbon_accounting: Literal["location", "generation"] = Field("location", description="location: 数据中心用电×所在母线区域碳强度；generation: 发电侧排放")
    gen_emission_t_mwh: List[float] = Field(default_factory=lambda: [0.85, 0.85, 0.45, 0.45], description="本地机组排放因子（合成）")
    # ---- Phase 1：任务级批处理与迁移约束（jobs 为空时沿用 batch_mwh 聚合模型）----
    jobs: List[Job] = Field(default_factory=list)
    links: List[Link] = Field(default_factory=list, description="为空=不限链路（仅 mig_max_mw）；非空=仅允许已定义链路迁移")
    mig_energy_mwh_per_mwh: float = Field(0.0, description="迁移能耗：每迁移 1 MWh IT 工作在目的地额外消耗的 IT 能量 MWh")
    unserved_penalty_cny_mwh: float = Field(20000.0, description="任务未在截止前完成的惩罚 元/MWh")
    min_green_share: Optional[float] = Field(None, description="数据中心绿电占比下限 0-1：外网购电总量 ≤ (1-s)×数据中心总用电（直供/聚合项目考核）")
    green_shortfall_penalty_cny_mwh: Optional[float] = Field(None, description="绿电占比软约束：未达下限的缺口电量惩罚 元/MWh（如绿证价格）；None=硬约束（低风日可能不可行）。年度考核指标用于单日仿真时建议设置")
    # ---- 算-电-热-碳耦合 ----
    thermal_mode: Literal["constant_pue", "coupled"] = Field("constant_pue", description="constant_pue=电网侧=PUE×IT；coupled=热模型+冷却 COP+动态 PUE")
    outdoor_temp_c: List[float] = Field(default_factory=lambda: [25.0]*H, description="逐时室外干球温度 °C（缺省区域）")
    outdoor_temp_profiles: Dict[str, List[float]] = Field(default_factory=dict, description="区域 -> 24 点室外温度")
    outdoor_rh: float = Field(0.35, description="室外相对湿度 0-1（缺省区域，常数；用于湿球温度→冷却塔/蒸发冷却 COP）")
    outdoor_rh_profiles: Dict[str, List[float]] = Field(default_factory=dict, description="区域 -> 24 点相对湿度 0-1（>1 视为 %）")
    heat_network: Optional[HeatNetwork] = None
    dr_events: List[DREvent] = Field(default_factory=list)
    carbon_basis: Literal["average", "marginal"] = Field("average", description="碳强度口径：平均/边际")
    carbon_marginal_profiles: Dict[str, List[float]] = Field(default_factory=dict, description="区域 -> 24 点边际碳强度")
    # ---- VCC 虚拟容量曲线（Google Carbon-Intelligent 风格；缺省 off=旧行为）----
    vcc_mode: Literal["off", "carbon", "price", "weighted"] = Field(
        "off", description="off=关闭；carbon/price/weighted=日前或同层灵活负荷容量整形")
    vcc_stage: Literal["joint", "day_ahead"] = Field(
        "joint", description="joint=与 DC-OPF 同层；day_ahead=先解 VCC 再约束批处理")
    vcc_carbon_weight: float = Field(1.0, description="weighted 模式下碳信号权重")
    vcc_price_weight: float = Field(1.0, description="weighted 模式下电价信号权重")
    vcc_preserve_daily: bool = Field(True, description="Σ Cap_vcc ≥ 日灵活需求")
    vcc_objective_scale: float = Field(1.0, description="VCC 整形项乘子（joint 模式）；1=按碳价/电价量纲")
    vcc_cap_spread: float = Field(0.0, ge=0.0, le=1.0, description="day_ahead Cap 与残差比例混合 [0,1]；0 时 vcc.py 按核算口径选默认（location≈0.05, generation≈0.45）")
    emergency_mode: bool = Field(False, description="True=断电/外网受限应急：UPS 可用至 soc_min，emergency_only 柴发放开；默认 False 不影响旧场景")
    layout: Dict[str, List[float]] = Field(default_factory=dict, description="模型拓扑图布局（b<i> -> [x,y] 0..1；dev:<id> -> [x,y]），由拓扑编辑器保存")

DataCenter.model_rebuild()

def outdoor_rh(sc: Scenario, bus: int) -> np.ndarray:
    """逐时相对湿度 0-1（区域曲线优先，否则常数 outdoor_rh；输入为百分数时自动 /100）。"""
    r = region_of(sc, bus); v = np.asarray(sc.outdoor_rh_profiles.get(r, [sc.outdoor_rh]*sc.n_steps), float)
    if v.size == 1: v = np.full(sc.n_steps, float(v))
    v = np.where(v > 1.0, v/100.0, v)
    return np.clip(v, 0.01, 1.0)

def outdoor_temp(sc: Scenario, bus: int) -> np.ndarray:
    r = region_of(sc, bus)
    return np.asarray(sc.outdoor_temp_profiles.get(r, sc.outdoor_temp_c), float)

DEFAULT_DCS = [
    dict(name="DC_A", bus=4, cap_it_mw=30, pue=1.35, interactive_mw=gauss(10, 5, 20, 3), batch_mwh=200),
    dict(name="DC_B", bus=8, cap_it_mw=25, pue=1.30, interactive_mw=gauss(8, 4, 14, 3), batch_mwh=150),
    dict(name="DC_C", bus=13, cap_it_mw=20, pue=1.45, interactive_mw=gauss(6, 3, 20, 3), batch_mwh=120),
]
DEFAULT_PV = [dict(bus=3, cap_mw=80), dict(bus=8, cap_mw=60), dict(bus=13, cap_mw=50)]

def build_default(n_dc: int = 3, storage_mwh: float = 0.0, storage_bus: int = 4,
                  price_kind: str = "peak_valley", n_jobs: int = 0, jobs_seed: int = 42, **overrides) -> Scenario:
    dcs = DEFAULT_DCS[:max(1, min(n_dc, 3))]
    sto = [Storage(bus=storage_bus, energy_mwh=storage_mwh, power_mw=storage_mwh/4)] if storage_mwh > 0 else []
    sc = Scenario(data_centers=[DataCenter(**d) for d in dcs], pv=[PV(**p) for p in DEFAULT_PV],
                  storage=sto, price_kind=price_kind, price_cny_kwh=tou_price(price_kind))
    sc = sc.model_copy(update=overrides) if overrides else sc
    if n_jobs:
        names = {d.name for d in sc.data_centers}
        sc.links = [Link(**l) for l in DEFAULT_LINKS if l["a"] in names and l["b"] in names]
        sc.mig_energy_mwh_per_mwh = sc.mig_energy_mwh_per_mwh or 0.03
        sc.jobs = generate_jobs(sc, n_jobs, jobs_seed)
    return sc

def region_of(sc: Scenario, bus: int) -> str:
    return sc.bus_region.get(bus, "national")

def carbon_profile(sc: Scenario, bus: int) -> np.ndarray:
    """母线所在区域逐时碳强度 tCO2/MWh。"""
    from .carbon import synthetic_profile
    r = region_of(sc, bus)
    if getattr(sc, "carbon_basis", "average") == "marginal" and r in sc.carbon_marginal_profiles: return np.asarray(sc.carbon_marginal_profiles[r], float)
    if r in sc.carbon_profiles: return np.asarray(sc.carbon_profiles[r], float)
    return np.repeat(np.asarray(synthetic_profile(sc.carbon_factor, sc.carbon_shape), float),int(round(1/sc.dt_hours)))

DEFAULT_LINKS = [dict(a="DC_A", b="DC_B", latency_ms=8, bw_mw=6), dict(a="DC_A", b="DC_C", latency_ms=28, bw_mw=4),
                 dict(a="DC_B", b="DC_C", latency_ms=22, bw_mw=5)]

def generate_jobs(sc: Scenario, n_jobs: int = 30, seed: int = 42, latency_sensitive_share: float = 0.3,
                  energy_share: float = 1.0) -> List[Job]:
    """合成任务（SYNTHETIC）：每个 DC 的任务总能量≈ energy_share×batch_mwh；窗口/功率随机，保证单任务可行。"""
    rng = np.random.default_rng(seed); dcs = sc.data_centers; jobs = []
    if not dcs: return jobs
    per = [max(1, round(n_jobs * d.batch_mwh / sum(x.batch_mwh for x in dcs))) for d in dcs]
    k = 0
    for d, n in zip(dcs, per):
        w = rng.dirichlet(np.ones(n)) * d.batch_mwh * energy_share
        for e in w:
            dur = int(rng.integers(4, 13))                      # 最短运行窗口 h
            rel = int(rng.integers(0, 24 - dur + 1))
            slack = int(rng.integers(0, 24 - rel - dur + 1))     # 截止期松弛
            dl = rel + dur + slack
            mx = round(max(e / dur * 1.6, e / (dl - rel) * 1.05, 0.2), 3)
            sens = bool(rng.random() < latency_sensitive_share)
            jobs.append(Job(id=f"J{k:03d}", dc=d.name, release=rel, deadline=dl, energy_mwh=round(float(e), 3), max_mw=mx,
                            max_latency_ms=float(rng.choice([10, 15])) if sens else None, source="synthetic"))
            k += 1
    return jobs

# ---- 场景预设（cases/<project>/*.json）----
import os as _os, glob as _glob
CASES_DIR = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "cases")

def list_presets() -> List[str]:
    return sorted(_os.path.splitext(_os.path.basename(f))[0] for f in _glob.glob(_os.path.join(CASES_DIR, "*", "*.json")))

def load_preset(name: str) -> Scenario:
    fs = _glob.glob(_os.path.join(CASES_DIR, "*", f"{name}.json"))
    if not fs: raise ValueError(f"未找到场景预设 {name}；可用: {', '.join(list_presets())}")
    with open(fs[0]) as f: return Scenario.model_validate_json(f.read())

def preset_from_text(text: str) -> Optional[str]:
    """中文关键词 -> 预设名（Mock 路由用）。支持 中卫/大唐、和林格尔、庆阳、海南州/龙羊峡、张北/阿里。"""
    P = list_presets(); low = any(k in text for k in ["小风", "低风", "弱风", "无风", "枯"]); hi = any(k in text for k in ["大风", "高风"])
    win = "冬" in text; jobs = any(k in text for k in ["任务", "作业", "截止"])
    pick = lambda *c: next((x for x in c if x in P), None)
    th = any(k in text.lower() for k in ["虚拟储冷", "虚冷", "预冷", "蓄冷", "余热", "供热", "供暖", "虚拟储热", "虚热", "需求响应", "削峰", "热安全", "入口温度", "pue", "热耦合", "算电热碳", "冷却", "热浪", "高温"])
    heat = any(k in text for k in ["余热", "供热", "供暖", "虚拟储热", "虚热"])
    if th and any(k in text for k in ["和林格尔", "华电", "呼和浩特"]) and (heat or win): return pick("helinger_winter_coupled_heat")
    if th and any(k in text for k in ["中卫", "大唐"]):
        if any(k in text for k in ["热浪", "高温", "压力测试", "热安全"]): return pick("zhongwei_heatwave_stress")
        if heat or win: return pick("zhongwei_winter_coupled_heat")
        if any(k in text for k in ["需求响应", "削峰"]): return pick("zhongwei_summer_coupled_dr")
        return pick("zhongwei_summer_coupled")
    if any(k in text for k in ["和林格尔", "华电", "呼和浩特"]):
        return pick("helinger_typical_jobs40" if jobs else "", "helinger_lowwind" if low else "", "helinger_highwind" if hi else "",
                    "helinger_typical_noBJ" if any(k in text for k in ["不含北京", "无北京"]) else "", "helinger_typical_day")
    if "庆阳" in text:
        return pick("qingyang_typical_jobs40" if jobs else "", "qingyang_winter_lowwind" if (low or win) else "", "qingyang_highwind" if hi else "", "qingyang_typical")
    if any(k in text for k in ["海南州", "龙羊峡", "青海"]):
        if any(k in text for k in ["离网", "微网", "孤岛"]): return pick(f"qinghai_hainan_offgrid_{'winter' if win else 'summer'}")
        if "100%" in text or "全清洁" in text: return pick("qinghai_hainan_clean100_winter")
        return pick(f"qinghai_hainan_grid_{'winter' if win else 'summer'}")
    if any(k in text for k in ["张北", "阿里", "察北"]):
        return pick("zhangbei_summer_jobs40" if jobs else "", "zhangbei_winter" if win else "", "zhangbei_summer")
    if not any(k in text for k in ["中卫", "大唐"]): return None
    season = "winter" if "冬" in text else "summer"
    wind = "lowwind" if any(k in text for k in ["小风", "低风", "弱风", "无风"]) else "highwind"
    name = f"zhongwei_{season}_{wind}"
    if any(k in text for k in ["不含上海", "无上海", "不迁移", "单区域"]): name += "_noSH"
    elif any(k in text for k in ["任务", "作业", "截止"]) and season == "summer" and wind == "highwind": name += "_jobs40"
    return name if name in list_presets() else f"zhongwei_{season}_{wind}"
