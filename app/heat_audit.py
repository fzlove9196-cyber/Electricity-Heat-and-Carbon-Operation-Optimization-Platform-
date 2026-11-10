"""Boundary-explicit heat accounting from full precision interval dispatch, not rounded KPIs."""
def boundary_audit(sc, df, effective_single_pipe_loss=None, heat_sites=None):
    hn=sc.heat_network
    if hn is None or 'heat_delivered_MWth' not in df: return None
    dt=sc.dt_hours; N=len(df)
    total=lambda key: dt*float(df[key].sum()) if key in df else 0.
    sites=heat_sites if heat_sites is not None else [d.name for d in sc.data_centers if d.thermal and d.thermal.hp_cap_mw_th>0]
    injection={d:total(d+'_hp_heat_MWth') for d in sites}
    source=sum(injection.values())+total('heat_boost_MWth');terminal=total('heat_delivered_MWth');nodes=[];pipes=[]
    if hn.nodes and 'heat_node_'+hn.nodes[0].id+'_soc' in df:
        for i,p in enumerate(hn.pipes or []):
            raw=df['heat_pipe_'+str(i)+'_MWth'].tolist();delay=int(round(p.delay_h/dt));cut=max(0,N-delay)
            sent=dt*sum(raw);loss=p.loss*sent;arrived=dt*(1-p.loss)*sum(raw[:cut]);transit=dt*(1-p.loss)*sum(raw[cut:]) if delay else 0.
            pipes.append(dict(pipe=p.name or str(i),from_node=p.frm,to_node=p.to,delay_h=p.delay_h,delay_steps=delay,sent_mwh=sent,pipe_loss_mwh=loss,arrived_mwh=arrived,end_in_transit_mwh=transit,initial_in_transit_mwh=0.,residual_mwh=sent-loss-arrived-transit,boundary='pipe outlet before receiving-node storage and demand'))
        at={d:(hn.inject_at or {}).get(d,hn.nodes[0].id) for d in sites};plant=at[sorted(sites)[0]] if sites else hn.nodes[0].id
        for nd in hn.nodes:
            prefix='heat_node_'+nd.id;initial=nd.storage_soc0*nd.storage_mwh_th;states=df[prefix+'_soc'].tolist();previous=[initial]+states[:-1];loss=(1-(1-nd.storage_loss_h)**dt)*sum(previous)
            inp=sum(x for d,x in injection.items() if at[d]==nd.id)+(total('heat_boost_MWth') if nd.id==plant else 0.)
            arrivals=sum(p['arrived_mwh'] for p in pipes if p['to_node']==nd.id);sent=sum(p['sent_mwh'] for p in pipes if p['from_node']==nd.id);served=total(prefix+'_del');ch=total(prefix+'_ch');dis=total(prefix+'_dis');end=states[-1]
            nodes.append(dict(node=nd.id,source_injected_mwh=inp,pipe_arrivals_mwh=arrivals,pipe_sent_mwh=sent,terminal_served_mwh=served,terminal_demand_mwh=dt*sum(nd.demand_mw_th),charge_mwh=ch,discharge_mwh=dis,initial_store_mwh=initial,end_store_mwh=end,store_change_mwh=end-initial,store_loss_mwh=loss,node_residual_mwh=inp+arrivals+dis-served-sent-ch,storage_residual_mwh=initial+ch-dis-loss-end))
    elif not hn.nodes:
        loss=(hn.pipe_loss if effective_single_pipe_loss is None else effective_single_pipe_loss)*source
        initial=hn.storage_soc0*hn.storage_mwh_th;states=df['heat_store_MWh'].tolist();previous=[initial]+states[:-1];sl=(1-(1-hn.storage_loss_h)**dt)*sum(previous)
        pipes=[dict(pipe='single_equivalent',from_node='source',to_node='terminal',sent_mwh=source,pipe_loss_mwh=loss,arrived_mwh=source-loss,end_in_transit_mwh=0.,initial_in_transit_mwh=0.,residual_mwh=0.,boundary='pipe outlet before receiving-node storage and demand')]
        nodes=[dict(node='terminal',source_injected_mwh=0.,pipe_arrivals_mwh=source-loss,pipe_sent_mwh=0.,terminal_served_mwh=terminal,terminal_demand_mwh=dt*sum(hn.demand_mw_th),charge_mwh=total('heat_charge_MWth'),discharge_mwh=total('heat_discharge_MWth'),initial_store_mwh=initial,end_store_mwh=states[-1],store_change_mwh=states[-1]-initial,store_loss_mwh=sl,node_residual_mwh=source-loss+total('heat_discharge_MWth')-terminal-total('heat_charge_MWth'),storage_residual_mwh=initial+total('heat_charge_MWth')-total('heat_discharge_MWth')-sl-states[-1])]
    else: return None
    pipe_loss=sum(p['pipe_loss_mwh'] for p in pipes);store_loss=sum(n['store_loss_mwh'] for n in nodes);delta=sum(n['store_change_mwh'] for n in nodes);transit=sum(p['end_in_transit_mwh']-p['initial_in_transit_mwh'] for p in pipes)
    return dict(schema='heat_boundaries_v1',unit='MWh_th',source_injected_mwh=source,terminal_served_mwh=terminal,terminal_demand_mwh=sum(n['terminal_demand_mwh'] for n in nodes),pipe_arrivals_sum_mwh=sum(p['arrived_mwh'] for p in pipes),pipe_loss_mwh=pipe_loss,store_loss_mwh=store_loss,store_change_mwh=delta,transit_change_mwh=transit,residual_mwh=source-terminal-pipe_loss-store_loss-delta-transit,nodes=nodes,pipes=pipes,definitions={'terminal_served_mwh':'customer demand withdrawn at terminal; sales revenue and boiler offset use this boundary','pipe_arrivals_sum_mwh':'sum of receipts over pipe boundaries before receiving storage/use; multi-hop can count same heat more than once; NOT terminal sales','global_balance':'source = terminal use + pipe loss + store loss + change in stores + change in transit','initial_pipe_state':'zero; daily model has no carried-in pipeline heat'})
