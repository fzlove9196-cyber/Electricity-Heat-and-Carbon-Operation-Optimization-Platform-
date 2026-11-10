"""Optional two-pass objective, never a silent epsilon in the primary economics."""
import time
import pyomo.environ as pyo

def apply(m,sc,opt,expr):
    primary=float(pyo.value(m.obj));before=float(pyo.value(expr));tol=sc.migration_cleanup_tolerance_cny
    report=dict(enabled=True,priority=['primary economics/carbon/welfare','minimum gross migrated MWh'],primary_optimum=primary,primary_tolerance_cny=tol,primary_primal_feasibility_tolerance=1e-7,gross_before_mwh=before)
    values=[(x,x.value) for x in m.component_data_objects(pyo.Var)];original=m.obj.expr
    m.primary_lock=pyo.Constraint(expr=original<=primary+tol);m.obj.deactivate();m.cleanup_obj=pyo.Objective(expr=expr)
    t=time.monotonic()
    try:
        result=opt.solve(m,load_solutions=False);status=str(result.solver.termination_condition)
        if status!='optimal': raise RuntimeError(status)
        m.solutions.load_from(result)
        after=float(pyo.value(original));delta=after-primary
        if delta>tol+1e-7: raise RuntimeError(f'primary lock violated: {delta}')
        report.update(status='optimal',primary_after=after,primary_delta_cny=delta,gross_after_mwh=float(pyo.value(expr)),secondary_bound=float(result.problem.lower_bound))
    except Exception as e:
        for var,value in values: var.set_value(value)
        report.update(status='failed_retained_primary',error=str(e),primary_after=primary,primary_delta_cny=0.,gross_after_mwh=before)
    finally:
        m.cleanup_obj.deactivate();m.obj.activate()
    report['time_s']=time.monotonic()-t
    return report
