"""Freeze already-downloaded raw RTS content; no network or optimal decisions."""
from pathlib import Path
import csv,json,hashlib,shutil,copy,datetime
R=Path(__file__).resolve().parent;P=Path('/workspace/paper-reproduction-research/phase2/raw');(R/'raw').mkdir(exist_ok=True)
def save(n,m): (R/(n+'.json')).write_text(json.dumps(m,ensure_ascii=False,indent=2))
def bus(i,region,load):return dict(id=i,region=region,background_load_mw=[load])
def gen(i,b,cap,c,e,clean=False):return dict(id=i,bus=b,available_mw=[cap],cost_usd_mwh=c,operational_tco2_mwh=e,low_carbon=clean,source=dict(kind='SYNTHETIC analytic control, not paper precision'))
def site(i,b,work):return dict(id=i,bus=b,baseline_work_mw=[work],capacity_work_mw=work*2)
def line(i,a,b,limit):return dict(id=i,from_bus=a,to_bus=b,b_mw_per_rad=100,limit_mw=limit)
base=dict(model_kind='opt_grid_feedback',name='SYNTHETIC',horizon_mode='benchmark',start='2020-02-29T00:00:00+00:00',slack_bus='A',source=dict(kind='SYNTHETIC; analytic independent references only'),max_iterations=3)
m=dict(base,buses=[bus('A','R1',0),bus('B','R2',0),bus('C','R2',0)],lines=[line('AB','A','B',5),line('CB','C','B',5)],generators=[gen('dirtyA','A',100,10,1),gen('dirtyB','B',100,30,2),gen('cleanC','C',100,0,0,True)],sites=[site('computeA','A',10),site('computeB','B',10)],unstable_signal_policy='allow_directional');m['name']='SYNTHETIC congestion: regional clean surplus inaccessible; actual emissions can rise';save('benchmark_congestion',m)
m=dict(base,buses=[bus('A','R',0),bus('B','R',0)],lines=[line('AB','A','B',100)],generators=[gen('cleanA','A',100,1,0,True)],sites=[site('computeA','A',10),site('computeB','B',10)]);m['name']='SYNTHETIC all-clean no-change';save('benchmark_clean',m)
m=dict(base,buses=[bus('A','R1',0),bus('B','R2',29),bus('C','R2',0)],lines=[line('AB','A','B',12),line('AC','A','C',100),line('BC','B','C',100)],generators=[gen('dirtyA','A',100,10,2),gen('cleanC','C',100,20,0,True)],sites=[site('computeB','B',1),site('computeC','C',1)]);m['name']='SYNTHETIC stable negative LMCE at B=-2t/MWh, congestion redispatch';save('benchmark_negative_lmce',m)
raw={};manifest=[]
for n in ['rts_bus.csv','rts_branch.csv','rts_gen.csv','rts_day_ahead_load.csv']:
 b=(P/n).read_bytes();shutil.copy2(P/n,R/'raw'/n);raw[n]=list(csv.DictReader(b.decode().splitlines()));manifest.append(dict(file=n,bytes=len(b),sha256=hashlib.sha256(b).hexdigest(),git_blob_sha1=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest(),source='https://raw.githubusercontent.com/GridMod/RTS-GMLC/master/RTS_Data/'+({'rts_bus.csv':'SourceData/bus.csv','rts_branch.csv':'SourceData/branch.csv','rts_gen.csv':'SourceData/gen.csv','rts_day_ahead_load.csv':'timeseries_data_files/Load/DAY_AHEAD_regional_Load.csv'}[n])))
bb=raw['rts_bus.csv'];gg=raw['rts_gen.csv'];ll=raw['rts_branch.csv'];loads=raw['rts_day_ahead_load.csv'];assert len(loads)==8784 and len(bb)==73 and len(gg)==158 and len(ll)==120
idx=[i for i,x in enumerate(loads) if x['Month']=='2' and x['Day']=='29'][:4];assert idx==[1416,1417,1418,1419]
area={a:sum(float(b['MW Load']) for b in bb if b['Area']==a) for a in ['1','2','3']}
buses=[dict(id=b['Bus ID'],region=b['Area'],background_load_mw=[float(loads[i][b['Area']])*float(b['MW Load'])/area[b['Area']] for i in idx]) for b in bb]
lines=[dict(id=l['UID'],from_bus=l['From Bus'],to_bus=l['To Bus'],b_mw_per_rad=100/(float(l['X'])*(float(l['Tr Ratio']) or 1)),limit_mw=float(l['Cont Rating']),source=dict(raw_file='rts_branch.csv',raw_uid=l['UID'],x_pu=float(l['X']),tap=float(l['Tr Ratio']) or 1,base_mva=100,formula='b=100/(x_pu*tap)MW/rad; RATE=Cont Rating MW; lossless DC')) for l in ll]
def num(x):
 try:return float(x)
 except ValueError:return None
gens=[]
for g in gg:
 fuel=g['Fuel'];thermal=fuel in ['Oil','Coal','NG','Nuclear'];pts=[(i,num(g['Output_pct_'+str(i)])) for i in range(5) if num(g['Output_pct_'+str(i)]) is not None];heat=0.
 if thermal:
  if not pts or num(g['HR_avg_0']) is None:raise ValueError('missing thermal heat rate '+g['GEN UID'])
  heat=pts[0][1]*float(g['HR_avg_0'])
  for (i,f),(j,h) in zip(pts,pts[1:]):
   v=num(g['HR_incr_'+str(j)])
   if v is None:raise ValueError('missing incremental heat rate')
   heat+=(h-f)*v
  heat/=1000 # Btu/kWh -> MMBtu/MWh
 price=num(g['Fuel Price $/MMBTU']) or 0;vom=num(g['VOM']) or 0;lb=num(g['Emissions CO2 Lbs/MMBTU'])
 if fuel in ['Oil','Coal','NG'] and lb is None:raise ValueError('missing fossil CO2 rate')
 rate=heat*(lb or 0)*.00045359237;cost=heat*price+vom;disabled=fuel in ['Storage','Sync_Cond'];cap=0 if disabled else float(g['PMax MW'])*1.5
 gens.append(dict(id=g['GEN UID'],bus=g['Bus ID'],available_mw=[cap]*4,pmin_mw=0,cost_usd_mwh=cost,operational_tco2_mwh=rate,low_carbon=fuel in ['Wind','Solar','Hydro','Nuclear'],source=dict(raw_file='rts_gen.csv',raw_uid=g['GEN UID'],fuel=fuel,raw_pmax_mw=float(g['PMax MW']),paper_capacity_multiplier=1.5,pmin_override='paper p4=0',heat_mmbtu_mwh=heat,co2_lb_mmbtu=lb,usd_mmbtu=price,vom_usd_mwh=vom,coefficient_choice='VARIANT: integrated raw full-load average heat rate used as linear slope, not verified author conversion',availability='VARIANT: static nameplate all selected hours, original hourly renewable profiles NOT used',disabled_reason='storage requires SOC model / synchronous condenser not active generation' if disabled else None)))
sites=[dict(id='paper_node_'+str(i),bus=bb[i-1]['Bus ID'],baseline_work_mw=[250.]*4,capacity_work_mw=300.,pue=1.) for i in [3,7,28,70]]
m=dict(model_kind='opt_grid_feedback',name='RTS actual data leap-day4h; explicit static-availability/coefficient variant, NOT paper reproduction',horizon_mode='original_data_subset',start='2020-02-29T00:00:00+00:00',buses=buses,lines=lines,generators=gens,sites=sites,slack_bus=bb[0]['Bus ID'],max_iterations=2,unstable_signal_policy='allow_directional',source=dict(kind='PUBLIC_ORIGINAL_RTS_DATA_SUBSET_MODEL_VARIANT_NOT_AUTHOR_RESULTS',paper='https://arxiv.org/abs/2105.09120',paper_pages='PDF8pages: p2(1)(2),p3(3)-(6),p4(7),p5SecIV,p6TableI(actual)/TableII(predicted)',source_total_hours=8784,source_hour_indices=idx,source_start='2020-01-01T00:00:00+00:00',exact_author_commit='NOT ESTABLISHED; local content pinned by SHA256 and Gitblob; master URL is not paper-version evidence',raw_manifest=manifest,node_mapping_assumption={str(i):bb[i-1]['Bus ID'] for i in [3,7,28,70]},time_basis='raw civil Year/Month/Day/Period has no offset; interpreted UTC for this explicit variant, author timezone not established',variant_limits=['raw regional load allocated by bus nominal-load weights','static renewable availability from rawPMax, NOT same hour wind/solar','linear full-load-integrated heat coefficients; author exact rates unknown','storage/synchronous condenser generation disabled, no free storage','no UC/ramping, no AC; subset not full8784, leap day retained']))
save('rts_leap4h',m);(R/'raw_manifest.json').write_text(json.dumps(dict(files=manifest,raw_dimensions=dict(buses=73,generators=158,lines=120,source_hours=8784),subset_indices=idx,conversion='cost=MMBtu/MWh*USD/MMBtu+VOM; tCO2/MWh=MMBtu/MWh*lb/MMBtu*0.00045359237; rates are explicit modelling variant'),ensure_ascii=False,indent=2));print('frozen73/158/120; source8784 retained; four leap-day hours, no optimal inputs')
