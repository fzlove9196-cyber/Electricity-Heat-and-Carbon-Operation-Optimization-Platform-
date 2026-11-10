"""Independent full-8760 author portfolio formulation, background explicitly reduced (NOT whole original OPF). Does not import product code.
Python3.11/pypsa0.26, HiGHS substituted for licensed Gurobi, otherwise functions unmodified.
"""
import json,sys,pathlib,hashlib,types,traceback,copy
import yaml,pypsa
ROOT=pathlib.Path('/workspace/sim-agent-phase5-evidence');RAW=pathlib.Path('/workspace/paper-reproduction-research/phase2/raw');OUT=ROOT/'author_reference_portfolio';OUT.mkdir(exist_ok=True)
sys.path.insert(0,str(ROOT/'author_sources/scripts'));import solve_network as a
cfg=yaml.safe_load((RAW/'riepin_config.txt').read_text());cfg['solving']['solver']={'name':'highs','options':'reference_highs'};cfg['solving']['solver_options']['reference_highs']={'solver':'ipm','threads':4,'time_limit':600,'ipm_optimality_tolerance':1e-9,'primal_feasibility_tolerance':1e-7}
a.config=cfg;a.policy='cfe';a.penetration=1.;a.tech_palette='p1';a.zone='EU';a.year='2025';a.profile_shape='baseload';a.distance='DKDEPT';a.datacenters=cfg['ci']['DKDEPT']['datacenters'];a.locations=list(a.datacenters);a.names=list(a.datacenters.values())
netfile=RAW/'riepin_1h2025.nc';binary=netfile.read_bytes();assert hashlib.sha1(b'blob '+str(len(binary)).encode()+b'\0'+binary).hexdigest()=='e95dd9aba48f997b9ae27ca4df5123790b6f7a2e'
a.costs=a.prepare_costs(cost_file=ROOT/'author_sources/costs_2025_v0.6.2.csv',USD_to_EUR=cfg['costs']['USD2013_to_EUR2013'],discount_rate=cfg['costs']['discountrate'],year='2025',Nyears=1,config=cfg,lifetime=cfg['costs']['lifetime'])
n0=pypsa.Network(netfile,override_component_attrs=a.override_component_attrs())
# Product input independently extracted from the unmodified original NC, not synthetic wind/solar.
sites=[]
for loc,name in a.datacenters.items():
    ch=n0.links.loc[loc+' battery charger-2025'];dis=n0.links.loc[loc+' battery discharger-2025'];st=n0.stores.loc[loc+' battery-2025'];resources=[]
    for tech in ['onwind','solar']:
        key=f'{loc} {tech}-2025';r=n0.generators.loc[key];resources.append(dict(id=tech,technology='wind' if tech=='onwind' else 'solar',region=loc,additional=True,availability=n0.generators_t.p_max_pu[key].tolist(),capital_per_mw_year=float(r.capital_cost),marginal_per_mwh=.015 if tech=='onwind' else float(r.marginal_cost)))
    sites.append(dict(id=name,region=loc,load_mw=[100.]*8760,generators=resources,battery=dict(capital_power_per_mw_year=float(ch.capital_cost),capital_energy_per_mwh_year=float(st.capital_cost),eta_charge=float(ch.efficiency),eta_discharge=float(dis.efficiency),loss_per_hour=float(st.standing_loss),discharge_cost_internal_per_mwh=float(dis.marginal_cost)),grid_price_per_mwh=[0.]*8760,grid_cfe=[0.]*8760))
base=dict(model_kind='opt_cfe',name='Riepin DKDEPT 原输入8760 · f0',currency='EUR',planning_year=2025,weather_year=2013,timezone='UTC',start='2013-01-01T00:00:00+00:00',dt_hours=1.,horizon_mode='year',matching='paper_cfe_score',target=1.,flexibility=0.,spatial_shifting=True,temporal_shifting=False,sites=sites,source=dict(kind='AUTHOR_ORIGINAL_INPUT_FULL_8760',repository='https://github.com/Irieo/space-time-optimization',commit='6e3bd6e2bdcaf8ff25393218b09c737a018460bc',network_blob='e95dd9aba48f997b9ae27ca4df5123790b6f7a2e',network_sha256=hashlib.sha256(binary).hexdigest(),weather_year=2013,planning_year=2025,source_equations='arXiv2405.00036 p4eq1-2,p5eq3,p6eq5-7',onwind_override='author solve_network.py cost_parametrization sets marginal=.015',temporal_note='published strip_full_network excludes DSM bus; effective original code temporal capacity absent; dedicated formula-DSM case separately named'))
case=pathlib.Path('/workspace/sim-agent/cases/paper_reproduction/phase5')
for flex in [0,40]:
    model=copy.deepcopy(base);model['flexibility']=flex/100;model['name']=f'Riepin DKDEPT 原输入8760 · f{flex} · published-effective';(case/f'riepin8760_f{flex}.json').write_text(json.dumps(model,ensure_ascii=False))
model=copy.deepcopy(base);model.update(flexibility=.4,temporal_shifting=True,name='Riepin原输入8760 · f40 · manuscript spatial+daily-DSM');model['source']['variant']='Manuscript eq6 DSM retained; DIFFERENT from published strip_full_network effective topology';(case/'riepin8760_f40_manuscript.json').write_text(json.dumps(model,ensure_ascii=False))
for flex,variant in [(0,'published'),(40,'published'),(40,'manuscript')]:
    tag=f'f{flex}'+('_manuscript' if variant=='manuscript' else '')
    try:
        print('AUTHOR START FLEX',flex,flush=True);a.flexibility=str(flex);n=n0.copy();a.n=n;a.snakemake=types.SimpleNamespace(log=types.SimpleNamespace(solver=str(OUT/f'{tag}_solver.log')),output=types.SimpleNamespace(grid_cfe=str(OUT/f'{tag}_grid_cfe.csv')),config=cfg)
        a.strip_network(n,cfg);a.cost_parametrization(n,cfg);a.shutdown_lineexp(n);a.limit_resexp(n,'2025',a.datacenters,cfg);a.nuclear_policy(n,cfg);a.coal_policy(n,'2025',cfg);a.biomass_potential(n);a.co2_policy(n,'2025',cfg);a.add_ci(n,'2025');a.add_vl(n,a.names);a.add_dsm(n);before=dict(dsm_buses=[x for x in n.buses.index if 'DSM' in x],dsm_links=n.links.index[n.links.carrier=='dsm'].tolist());a.revert_links(n);a.strip_full_network(n,cfg)
        # Exact portfolio reduction ONLY for CFE100, grid-CFE0, excess0: annual
        # nonnegative dirty import must sum to0, hence every importer=0. Background
        # zero-load OPF is disconnected from procurement and is NOT claimed reproduced.
        if variant=='manuscript':a.add_dsm(n);a.revert_links(n)
        keepbus=set(a.names)|{name+' battery' for name in a.names}|set(a.locations)
        if variant=='manuscript':keepbus|={name+' DSM' for name in a.names}
        for component in ['Generator','Store','StorageUnit','Load']:
            table=n.df(component);keep=table.bus.isin(set(a.names)|{name+' battery' for name in a.names}|({name+' DSM' for name in a.names} if variant=='manuscript' else set()));n.mremove(component,table.index[~keep])
        links=n.links;keep=(links.bus0.isin(a.names)|links.bus1.isin(a.names))&links.bus0.isin(keepbus)&links.bus1.isin(keepbus);n.mremove('Link',links.index[~keep]);n.mremove('Line',n.lines.index);n.mremove('Bus',n.buses.index.difference(keepbus))
        # Author's generic national constraint expects a StorageUnit variable even
        # when its selected set is empty. A fixed-zero placeholder has no energy/cost.
        n.add('StorageUnit','reference_fixed_zero_placeholder',bus=a.locations[0],carrier='hydro',p_nom=0.,max_hours=0.,inflow=0.)
        after=dict(dsm_buses=[x for x in n.buses.index if 'DSM' in x],dsm_links=n.links.index[n.links.carrier=='dsm'].tolist());(OUT/f'{tag}_topology.json').write_text(json.dumps(dict(before=before,after=after,n_snapshots=len(n.snapshots),n_sites=3),indent=2));assert len(n.snapshots)==8760
        a.solve_network(n,'cfe',1.,'p1',1,cfg)
        obj=float(n.objective);own=0.;invest=[]
        for name in a.names:
            gs=n.generators.query('bus==@name');st=n.stores.query('bus==@name+" battery"') if False else n.stores.loc[[name+' battery']];ls=n.links.loc[[name+' battery charger',name+' battery discharger']]
            capital=float((gs.p_nom_opt*gs.capital_cost).sum()+(st.e_nom_opt*st.capital_cost).sum()+(ls.p_nom_opt*ls.capital_cost).sum());op=float((n.generators_t.p[gs.index]*gs.marginal_cost).sum().sum()+(n.links_t.p0[ls.index]*ls.marginal_cost).sum().sum());flexcols=n.links.index[(n.links.carrier.isin(['virtual_link','dsm']))&(n.links.bus0==name)];fee=float((n.links_t.p0[flexcols]*n.links.loc[flexcols].marginal_cost).sum().sum());total=capital+op+fee;own+=total
            invest.append(dict(site=name,annual_total=total,capital=capital,generation_and_storage_op=op,spatial_fee=fee,wind_mw=float(n.generators.at[name+' onwind','p_nom_opt']),solar_mw=float(n.generators.at[name+' solar','p_nom_opt']),battery_power_mw=float(ls.at[name+' battery charger','p_nom_opt']),battery_energy_mwh=float(st.at[name+' battery','e_nom_opt'])))
        out=dict(flexibility=flex/100,author_functions_unmodified=True,background_model_reduced=True,reduction_scope='8760 time points unchanged, same original DC generators/storage/flex equations; background zero-load grid explicitly removed after proving all imports0; not whole European OPF',variant=variant,solver_substitution='HiGHS IPM instead of Gurobi',network_snapshots=len(n.snapshots),solver_status=str(n.model.status),termination=str(n.model.termination_condition),objective_including_background=obj,procurement_objective=own,background_offset=obj-own,investments=invest,DSM_before=before,DSM_after=after)
        (OUT/f'{tag}_reference.json').write_text(json.dumps(out,indent=2));print(json.dumps(out),flush=True)
    except Exception as e:
        (OUT/f'{tag}_FAILED.txt').write_text(traceback.format_exc());traceback.print_exc()
