from pathlib import Path
import csv,json,hashlib,shutil,copy,math
import numpy as np,openpyxl
R=Path(__file__).resolve().parent;P=Path('/workspace/paper-reproduction-research/phase2/raw');P=P if P.exists() else R/'raw';(R/'raw').mkdir(exist_ok=True)
def save(n,m):(R/(n+'.json')).write_text(json.dumps(m,ensure_ascii=False,indent=2))
def action(id,cap,power,rate):return dict(id=id,cap_w=cap,power_w_per_gpu=power,normalized_rate=rate,source=dict(kind='SYNTHETIC analytic control'))
def gpu(id):return dict(id=id,idle_power_w=50,source=dict(kind='SYNTHETIC explicit idle50W'))
def model(n=3):return dict(model_kind='opt_gpu',name='SYNTHETIC discrete cap+work control',n_steps=n,dt_hours=1,gpus=[gpu('G0'),gpu('G1')],jobs=[dict(id='job',gpu_ids=['G0','G1'],actions=[action('cap200',200,200,.75),action('cap400',400,400,1)],reference_action='cap400',baseline_rate=[1,1]+[0]*(n-2),required_work_h=2,deadline_h=n,flex=2,sla_windows=[dict(start_h=0,end_h=2)],allow_pause=True,pause_power_w_per_gpu=50,source=dict(kind='SYNTHETIC exact2 unthrottled ganghours, fixed2GPU'))],price_usd_kwh=[1]*n,power_limit_kw=[None]*n,sla_window_semantics='synthetic_short_window',source=dict(kind='SYNTHETIC, not paper accuracy'))
x=model();save('synthetic_energy',x);x=model();x['jobs'][0]['flex']=3;x['power_limit_kw']=[None,.1,None];save('synthetic_pause',x)
x=model(4);j=x['jobs'][0];j.update(gpu_ids=['G0'],baseline_rate=[1,1,1,0],required_work_h=3,flex=2,sla_windows=[dict(start_h=0,end_h=3)]);j['actions'][0]['normalized_rate']=.5;z=copy.deepcopy(j);z.update(id='flex3',gpu_ids=['G1'],flex=3);x['jobs'].append(z);x.update(policy='fair_minimax',power_limit_kw=[.6,.6,.6,None]);save('synthetic_fair',x)
rows=list(csv.DictReader((P/'emerald_dvfs_sweep.csv').open()));groups={k:[x for x in rows if x['Workload']==k] for k in dict.fromkeys(x['Workload'] for x in rows)};cal=[100,200,300,400];hold=[250,350];fits=[];sources=[]
for n in ['emerald_dvfs_sweep.csv','emerald_SRP_exp_performance.csv','emerald_Fig345_data.xlsx','emerald2025_paginated.txt']:
 b=(P/n).read_bytes();shutil.copy2(P/n,R/'raw'/n) if (P/n).resolve()!=(R/'raw'/n).resolve() else None;sources.append(dict(file=n,bytes=len(b),sha256=hashlib.sha256(b).hexdigest()))
for name,rr in groups.items():
 train=sorted([r for r in rr if int(r['GPU power cap']) in cal],key=lambda r:int(r['GPU power cap']));xp=[int(r['GPU power cap']) for r in train]
 for r in rr:
  if int(r['GPU power cap']) not in hold:continue
  cap=int(r['GPU power cap']);pp=float(np.interp(cap,xp,[float(a['power per GPU']) for a in train]));pr=float(np.interp(cap,xp,[float(a['normalized throughput']) for a in train]));fits.append(dict(workload=name,cap_w=cap,predicted_power_w=pp,measured_power_w=float(r['power per GPU']),predicted_rate=pr,measured_rate=float(r['normalized throughput'])))
# Raw six SRP job identities/Flex tags, allocations inferred from its measured sweep groups.
perf=list(csv.DictReader((P/'emerald_SRP_exp_performance.csv').open()));jobspec=[]
for r in perf:
 if r['Model']=='Weighted Performance':continue
 name=next(k for k in sorted(groups,key=len,reverse=True) if r['Model'].strip().startswith(k+'-'));rr=groups[name];N=round(float(rr[0]['total GPU power'])/float(rr[0]['power per GPU']));jobspec.append((r['Model'].strip(),name,N,int(r['Flexibility'][-1]),float(r['Performance'])))
assert sum(x[2] for x in jobspec)==256
for held in [False,True]:
 jobs=[];gpus=[];gid=0
 for id,name,N,flex,measuredperf in jobspec:
  rr={int(r['GPU power cap']):r for r in groups[name]};actions=[]
  for cap in ([250,350,400] if held else cal):
   row=rr[cap];fit=next((r for r in fits if r['workload']==name and r['cap_w']==cap),None);a=dict(id='cap'+str(cap),cap_w=cap,power_w_per_gpu=fit['predicted_power_w'] if fit else float(row['power per GPU']),normalized_rate=fit['predicted_rate'] if fit else float(row['normalized throughput']),source=dict(file='emerald_dvfs_sweep.csv',workload=name,training_caps=cal,heldout_caps=hold,split='HELDOUT prediction from4 calibration caps' if fit else 'CALIBRATION measured action',gang_size=N,raw_throughput_unit='unspecified in CSV; normalized only, do not invent tokens/steps units'))
   if fit:a.update(validation_power_w_per_gpu=fit['measured_power_w'],validation_normalized_rate=fit['measured_rate'])
   actions.append(a)
  ids=['G'+str(i) for i in range(gid,gid+N)];gid+=N
  gpus += [dict(id=k,idle_power_w=100,source=dict(kind='EXPLICIT COUNTERFACTUAL ASSUMPTION idle100W, not author measured idle')) for k in ids]
  jobs.append(dict(id=id,gpu_ids=ids,actions=actions,reference_action='cap400',baseline_rate=[1]*6+[0]*3,required_work_h=6,deadline_h=9,flex=flex,sla_windows=[dict(start_h=0,end_h=6)],allow_pause=True,pause_power_w_per_gpu=100,source=dict(file='SRP_exp_performance.csv',workload=name,reported_measured_performance=measuredperf,required_work='SYNTHETIC6 baseline-ganghours, recovery3h; real field job sizes/deadlines/control states NOT available',pause='EXPLICIT100W assumption; paperp6 negligible checkpoint overhead approximation, NOT measured pause power')))
 baseline=sum(len(j['gpu_ids'])*next(a['power_w_per_gpu'] for a in j['actions'] if a['id']=='cap400') for j in jobs)/1000
 m=dict(model_kind='opt_gpu',name=('HELDOUT predicted actions; strict validation may fail' if held else 'Real DVFS calibration + real SRP Flex tags; synthetic equal-work/recovery experiment'),n_steps=9,dt_hours=1,gpus=gpus,jobs=jobs,price_usd_kwh=[1]*9,power_limit_kw=[None]+[baseline*.75]*3+[None]*5,mip_relative_gap=0,source=dict(kind='PUBLIC_FIELD_CURVES_AND_FLEX_TAGS_WITH_EXPLICIT_COUNTERFACTUAL_WORKLOAD_NOT_AUTHOR_CONTROL_REPRODUCTION',paper='arxiv2507.00909v1',paper_evidence='p3Flex0/1/2/3 >=100/90/75/50% average3–6h; p6proportional fairness; p7Methods; p8Table1; public author README contains detailed DVFS Fair headroom/pause/resize pseudocode, archived separately',training_caps=cal,heldout_caps=hold,sweep_points=48,gpu_count=256,raw_manifest=sources,workload_and_idle='SYNTHETIC demand6h+recovery3h and idle/pause100W, not original field task state',weighted_performance='author reported .909560245, weights not established; our explicit GPUweighted/unweighted metrics NOT equated',power_boundary='GPU subtotal, not whole DC PUE/thermal or actual hardware commands'))
 save('emerald_heldout' if held else 'emerald_calibration',m)
for policy,key in [('fair_minimax','emerald_fair'),('author_dvfs_headroom_discrete','emerald_headroom')]:
 m=json.loads((R/'emerald_calibration.json').read_text());m['policy']=policy;m['source']['policy_evidence']='author_README.md DVFS Fair uses equal fraction of remaining power headroom; hybrid pause staggered enumeration described, not reproduced exactly. Our fair_minimax is separate normalized-throughput variant; headroom mode is discrete minimax/closest budget realization.';save(key,m)
# Separate source figure validation, never used to train our controller.
w=openpyxl.load_workbook(P/'emerald_Fig345_data.xlsx',read_only=True,data_only=True);rr=list(w['Fig5'].values)[2:]
from datetime import datetime
actual=[(datetime.fromisoformat(r[0]).timestamp(),float(r[7])) for r in rr if isinstance(r[0],str) and isinstance(r[7],(int,float))];pred=[(datetime.fromisoformat(r[9]).timestamp(),float(r[10])) for r in rr if isinstance(r[9],str) and isinstance(r[10],(int,float))];pp=dict(pred);xp=np.array(sorted(pp));yp=np.array([pp[t] for t in xp]);actual=[v for v in actual if xp[0]<=v[0]<=xp[-1]];tx=np.array([v[0] for v in actual]);ay=np.array([v[1] for v in actual]);linear=np.interp(tx,xp,yp);zoh=yp[np.maximum(0,np.searchsorted(xp,tx,side='right')-1)];fig=dict(n_actual_aligned=len(actual),n_prediction_points=len(pred),distinct_prediction_times=len(pp),actual_mean_w=float(ay.mean()),linear_nrmse=float(np.sqrt(np.mean((linear-ay)**2))/ay.mean()),previous_hold_nrmse=float(np.sqrt(np.mean((zoh-ay)**2))/ay.mean()),scope='Explicit no-extrapolation time alignment, linear vs previous-hold sensitivity; interpolation protocol not established; NOT all33 experiments or our controller prediction')

powererr=np.array([f['predicted_power_w']-f['measured_power_w'] for f in fits]);rateerr=np.array([f['predicted_rate']-f['measured_rate'] for f in fits]);authorweighted=float(next(r['Performance'] for r in perf if r['Model']=='Weighted Performance'));gpuweighted=sum(n*v for _,_,n,_,v in jobspec)/256
save('data_evidence',dict(raw_sources=sources,train_caps=cal,heldout_caps=hold,calibration_points=32,heldout_points=16,holdout= fits,power_rmse_w=float(np.sqrt(np.mean(powererr**2))),normalized_rate_rmse=float(np.sqrt(np.mean(rateerr**2))),fig5=fig,srp_author_weighted=authorweighted,srp_explicit_gpu_weighted=gpuweighted,weights_unestablished=True));print('raw48: train32/holdout16; jobs6GPU256; Figure5',fig)
