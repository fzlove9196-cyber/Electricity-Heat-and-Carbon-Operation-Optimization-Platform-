"""Binary state-flow nonpreemptible jobs. Not a claim of full TSUSC receding-horizon reproduction.
One unit has pending/running(site, progress)/cooldown/completed states. Cancellation discards
all prior progress, returns to backlog, and a restarted run needs its full duration again.
"""
from collections import defaultdict
import pyomo.environ as pyo
from ..time_axis import boundary,window

def build(m,sc,jobs,jx,sites,optimize):
    tasks=[j for j in jobs if j.execution_mode=='continuous'];dt=sc.dt_hours
    arcs=[];data={};flow=defaultdict(list);incoming=defaultdict(list);power=defaultdict(list);complete=defaultdict(list)
    def add(j,t,a,b,kind,d=None,lost=0):
        key=len(arcs);arcs.append(key);data[key]=(j.id,t,a,b,kind,d,lost)
        flow[j.id,t,a].append(key);incoming[j.id,t+1,b].append(key)
        if d is not None: power[j.id,d,t].append(key)
        if b=='done' and a!='done': complete[j.id].append(key)
    states={};initial={}
    for j in tasks:
        length=boundary(sc,j.duration_h);delay=boundary(sc,j.restart_delay_h);ss=sites(sc,j,optimize)
        states[j.id]=['pending','done']+[f'{d}|{k}' for d in ss for k in range(1,length)]+[f'cool|{k}' for k in range(1,delay)]
        p=boundary(sc,j.initial_progress_h);initial[j.id]=f'{j.initial_dc or j.dc}|{p}' if p else 'pending'
        if initial[j.id] not in states[j.id]: raise ValueError(f'{j.id} 初始状态不在允许站点；不能悄悄迁移已运行任务')
        for t in window(sc,j):
            add(j,t,'pending','pending','wait');add(j,t,'done','done','completed_idle')
            for d in ss: add(j,t,'pending','done' if length==1 else f'{d}|1','start',d)
            for state in states[j.id]:
                if state in ['pending','done']: continue
                d,k=state.rsplit('|',1);k=int(k)
                if d=='cool': add(j,t,state,'pending' if k==1 else f'cool|{k-1}','cooldown');continue
                add(j,t,state,'done' if k+1==length else f'{d}|{k+1}','continue',d)
                if j.allow_restart:
                    lost=k*dt*j.max_mw
                    add(j,t,state,'pending' if delay<=1 else f'cool|{delay-1}','cancel',lost=lost)
                    if delay==0:
                        for dest in ss: add(j,t,state,'done' if length==1 else f'{dest}|1','cancel_restart',dest,lost)
    m.job_arc=pyo.Var(arcs,within=pyo.Binary);c=m.c;penalty=0
    for j in tasks:
        ts=window(sc,j);start=ts.start;end=ts.stop
        for t in ts:
            for state in states[j.id]:
                rhs=(1 if state==initial[j.id] else 0) if t==start else sum(m.job_arc[a] for a in incoming[j.id,t,state])
                c.add(sum(m.job_arc[a] for a in flow[j.id,t,state])==rhs)
            for d in sites(sc,j,optimize): c.add(m.pj[j.id,d,t]==j.max_mw*sum(m.job_arc[a] for a in power[j.id,d,t]))
        c.add(m.un[j.id]==j.energy_mwh*(1-sum(m.job_arc[a] for a in complete[j.id])))
        if j.required: m.un[j.id].fix(0)
        for a in arcs:
            jid,t,fr,to,kind,d,lost=data[a]
            if jid==j.id and kind.startswith('cancel'): penalty+=j.cancellation_penalty_cny*m.job_arc[a]
    def extract(v):
        rows=[];ledgers=[]
        for j in tasks:
            selected=[(a,data[a]) for a in arcs if data[a][0]==j.id and v(m.job_arc[a])>.5]
            executed=0.;lost=0.;starts=0;cancels=0;good=0.;end_state=initial[j.id]
            for a,(_,t,fr,to,kind,d,loss) in selected:
                energy=j.max_mw*dt if d is not None else 0.;executed+=energy;lost+=loss;starts+=int(kind in ['start','cancel_restart']);cancels+=int(kind.startswith('cancel'));end_state=to
                if to=='done' and fr!='done': good=j.energy_mwh
                rows.append(dict(job=j.id,step=t,hour=t if dt==1 else t*dt,duration_h=dt,from_state=fr,to_state=to,event=kind,destination=d,executed_mwh=energy,canceled_lost_mwh=loss,completion=(to=='done' and fr!='done')))
            terminal=0.
            if end_state not in ['done','pending'] and not end_state.startswith('cool|'): terminal=int(end_state.rsplit('|',1)[1])*dt*j.max_mw
            init=j.initial_progress_h*j.max_mw
            ledgers.append(dict(job=j.id,initial_progress_mwh=init,executed_mwh=executed,completed_goodput_mwh=good,canceled_lost_mwh=lost,deadline_lost_mwh=terminal,unserved_mwh=float(v(m.un[j.id])),starts=starts,cancellations=cancels,end_state=end_state,required=j.required,conservation_residual_mwh=init+executed-good-lost-terminal,cancellation_cost_cny=cancels*j.cancellation_penalty_cny))
        return dict(model='binary_state_flow_v1',semantics='连续固定功率；取消丢弃全部进度，等待后从零重启；截止未完成进度单列损失；初始进度是历史工作不重复计电',events=rows,ledger=ledgers)
    return dict(milp=bool(tasks),penalty=penalty,extract=extract)
