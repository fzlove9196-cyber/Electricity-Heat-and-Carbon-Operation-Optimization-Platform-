"""Opt-in stateless annual migration policy. Not a DC-OPF/financial optimum."""
from typing import List, Literal
import numpy as np
from pydantic import BaseModel, Field, model_validator

class AnnualMigrationInput(BaseModel):
    dt_hours: Literal[1.0] = 1.0
    model_config = {"allow_inf_nan":False}
    name: str
    source: str = Field(min_length=1)
    currency: str = "USD"
    curtailment_mwh: List[float]
    baseline_dc_mw: List[float]
    source_ci_t_mwh: List[float]
    vre_lifecycle_t_mwh: List[float]
    utilizations: List[float] = Field(min_length=1,max_length=100)
    new_dc_counts: List[float] = Field(min_length=1,max_length=100)
    existing_dc_count: float = Field(ge=0)
    movable_fraction: float = Field(ge=0,le=1)
    server_idle_mw: float = Field(ge=0)
    server_dynamic_mw: float = Field(ge=0)
    cooling_intercept_mw: float = Field(ge=0)
    cooling_slope_mw: float = Field(ge=0)
    nominal_new_dc_mw: float = Field(gt=0)
    construction_t_per_mw_year: float = Field(ge=0)
    renewable_price_per_mwh: float = Field(ge=0)
    new_dc_annual_opex_per_mw: float = Field(ge=0)
    new_dc_annual_capital_charge_per_mw: float = Field(ge=0)
    displaced_source_cost_per_mw_year: float = Field(ge=0)
    baseline_dc_annual_mwh: float = Field(gt=0)
    hourly_case_index: int = Field(0,ge=0)

    @model_validator(mode="after")
    def domains(self):
        n=len(self.curtailment_mwh)
        if n not in (8760,8784): raise ValueError("annual input must explicitly contain 8760 or 8784 hourly samples; no truncation")
        for name in ("curtailment_mwh","baseline_dc_mw","source_ci_t_mwh","vre_lifecycle_t_mwh"):
            a=np.asarray(getattr(self,name),dtype=float)
            if len(a)!=n or not np.isfinite(a).all() or (a<0).any(): raise ValueError(name+": lengths must agree and values be finite/nonnegative")
        for name in ("utilizations","new_dc_counts"):
            a=np.asarray(getattr(self,name),dtype=float)
            if not np.isfinite(a).all() or (a<0).any(): raise ValueError(name+": invalid domain")
        if max(self.utilizations)>1: raise ValueError("utilization must be in [0,1]")
        if self.hourly_case_index>=len(self.utilizations)*len(self.new_dc_counts): raise ValueError("hourly_case_index out of range")
        return self

def evaluate(b:AnnualMigrationInput):
    curt=np.asarray(b.curtailment_mwh);baseline=np.asarray(b.baseline_dc_mw)
    source_ci=np.asarray(b.source_ci_t_mwh);vre_ci=np.asarray(b.vre_lifecycle_t_mwh)
    rows=[];hourly=[]
    for count in b.new_dc_counts:
        for utilization in b.utilizations:
            cap=b.server_idle_mw+(b.server_dynamic_mw+b.cooling_slope_mw)*utilization+b.cooling_intercept_mw
            # Exact closed-form solution of the hourly ordered linear policy:
            # first maximize existing absorption; then maximize additional absorption.
            existing=np.minimum(curt,np.maximum(0,cap-baseline)*b.existing_dc_count*b.movable_fraction)
            new=np.minimum(np.maximum(0,curt-existing),count*cap)
            total=existing+new
            op=float(source_ci@total);vre=float(vre_ci@total)
            embodied=count*b.nominal_new_dc_mw*b.construction_t_per_mw_year
            net=op-vre-embodied
            energy_credit=-b.renewable_price_per_mwh*float(total.sum())
            opex=b.new_dc_annual_opex_per_mw*count*b.nominal_new_dc_mw
            capital=b.new_dc_annual_capital_charge_per_mw*count*b.nominal_new_dc_mw
            displaced=-b.displaced_source_cost_per_mw_year*b.nominal_new_dc_mw/b.baseline_dc_annual_mwh*float(new.sum())
            cost=energy_credit+opex+capital+displaced
            row=dict(case_index=len(rows),new_dc_count=count,utilization=utilization,capacity_per_dc_mw=cap,existing_absorbed_mwh=float(existing.sum()),new_absorbed_mwh=float(new.sum()),absorbed_mwh=float(total.sum()),operational_avoided_t=op,vre_lifecycle_t=vre,construction_annual_t=embodied,net_avoided_t=net,net_avoided_kt=net/1000,energy_credit=energy_credit,annual_opex=opex,annual_capital_charge=capital,displaced_source_cost=displaced,total_cost=cost,net_abatement_cost_per_t=cost/net if abs(net)>1e-12 else None)
            if len(rows)==b.hourly_case_index:
                hourly=[dict(hour=h,curtailment_mwh=float(curt[h]),existing_headroom_mwh=float(max(0,cap-baseline[h])*b.existing_dc_count*b.movable_fraction),existing_absorbed_mwh=float(existing[h]),new_absorbed_mwh=float(new[h]),total_absorbed_mwh=float(total[h]),operational_avoided_t=float(source_ci[h]*total[h]),vre_lifecycle_t=float(vre_ci[h]*total[h]),construction_allocated_t=embodied/len(curt)) for h in range(len(curt))]
            rows.append(row)
    return dict(ok=True,model="ordered_existing_then_new_curtailment_migration",method="exact closed-form solution of stateless hourly ordered linear policy",not_full_facility_opf=True,not_financial_optimization=True,source=b.source,currency=b.currency,step_hours=1,n_hours=len(curt),n_grid_points=len(rows),grid=rows,hourly=hourly,scope_limits=["No inter-hour storage or job state; no electricity transmission", "Fixed utilization/capacity grid, not investment optimization", "Construction is annualized; operational and VRE lifecycle accounts are separate"])
