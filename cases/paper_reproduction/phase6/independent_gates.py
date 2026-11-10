"""12 named independent acceptance gates, NOT pytest count or whole-paper accuracy."""
from pathlib import Path
import json,csv,hashlib,zipfile,sys
from independent_reference import load_export,audit
R=Path(__file__).resolve().parent;E=Path(sys.argv[1]);idx=json.loads((E/'api_acceptance_index.json').read_text());checks=[]
def gate(name,ok,**m):checks.append(dict(name=name,passed=bool(ok),**m));assert ok,name
man=json.loads((R/'raw_manifest.json').read_text());raw={}
for x in man['files']:
 b=(R/'raw'/x['file']).read_bytes();assert hashlib.sha256(b).hexdigest()==x['sha256'];assert hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()==x['git_blob_sha1'];raw[x['file']]=list(csv.DictReader(b.decode().splitlines()))
load=raw['rts_day_ahead_load.csv'];gate('G08-I01 genuine raw content and complete leap-year index lock',len(load)==8784 and all(load[i]['Month']=='2' and load[i]['Day']=='29' for i in [1416,1417,1418,1419]),source_hours=len(load),subset_hours=4,whole_paper_precision=False,author_exact_commit='unestablished; content hashes != paper commit')
m,_=load_export(E/'rts_leap4h.zip');rates={g['GEN UID']:g for g in raw['rts_gen.csv']};maxc=maxe=maxb=0.
def number(s):
 try:return float(s)
 except ValueError:return 0.
for g in m['generators']:
 x=rates[g['id']];f=[number(x['Output_pct_'+str(i)]) for i in range(5)];heat=(f[0]*number(x['HR_avg_0'])+sum((f[j]-f[j-1])*number(x['HR_incr_'+str(j)]) for j in range(1,5)))/1000 if x['Fuel'] in ['Oil','NG','Coal','Nuclear'] else 0.;cost=heat*number(x['Fuel Price $/MMBTU'])+number(x['VOM']);emit=heat*number(x['Emissions CO2 Lbs/MMBTU'])*0.00045359237;maxc=max(maxc,abs(cost-g['cost_usd_mwh']));maxe=max(maxe,abs(emit-g['operational_tco2_mwh']))
for e,x in zip(m['lines'],raw['rts_branch.csv']):maxb=max(maxb,abs(e['b_mw_per_rad']-100/(float(x['X'])*(number(x['Tr Ratio']) or 1))))
gate('G08-I02 independent raw cost/carbon/line unit conversion',maxc<1e-10 and maxe<1e-12 and maxb<1e-9,max_cost_usd_mwh_error=maxc,max_metric_tco2_mwh_error=maxe,max_line_b_error=maxb,linearization='explicit full-load linear VARIANT; no verified author hourly VRE')
for k in ['benchmark_negative_lmce','benchmark_clean','benchmark_congestion','rts_leap4h']:
 mm,r=load_export(E/(k+'.zip'));stats=audit(mm,r);gate('G08-I0'+str(len(checks)+1)+' '+k+' frozen ZIP independent PTDF/LP/FD/work/migration audit',True,**stats)
neg=idx['cases']['benchmark_negative_lmce'];p={x['signal']:x for x in neg['policies']};mm,r=load_export(E/'benchmark_negative_lmce.zip');row=next(x for x in r['signals'] if x['site']=='computeB' and x['iteration']==0 and x['policy']=='lmce');gate('G08-I07 analytical stable negative LMCE retained',abs(row['fd_plus']+2)<1e-8 and row['stable'],lmce_tco2_mwh=row['fd_plus'],lmce_actual_delta_t=p['lmce']['actual_operational_delta_tco2'])
gate('G08-I08 four policies preserve the cost/carbon tradeoff',abs(p['lmce']['actual_operational_delta_tco2']+.4)<1e-8 and abs(p['lmce']['actual_cost_delta_usd']-2)<1e-8 and abs(p['lmp']['actual_operational_delta_tco2']-.4)<1e-8 and abs(p['lmp']['actual_cost_delta_usd']+2)<1e-8,baseline_usd=neg['baseline']['cost_usd'],lmce_delta_t=p['lmce']['actual_operational_delta_tco2'],cost_signal_delta_t=p['lmp']['actual_operational_delta_tco2'])
c={x['signal']:x for x in idx['cases']['benchmark_congestion']['policies']};gate('G08-I09 inaccessible regional clean surplus really increases emissions',abs(c['average']['actual_operational_delta_tco2']-2)<1e-8 and abs(c['excess']['actual_operational_delta_tco2']-2)<1e-8,average_actual_delta_t=c['average']['actual_operational_delta_tco2'],excess_actual_delta_t=c['excess']['actual_operational_delta_tco2'])
gate('G08-I10 linear prediction is not actual re-cleared emissions',abs(c['lmce']['predicted_operational_delta_from_initial_tco2']+2)<1e-8 and abs(c['lmce']['actual_operational_delta_tco2'])<1e-8,predicted_delta_t=c['lmce']['predicted_operational_delta_from_initial_tco2'],actual_delta_t=c['lmce']['actual_operational_delta_tco2'])
failed=[]
for k in ['expected_failed_iteration_limit','expected_failed_no_generation']:
 with zipfile.ZipFile(E/(k+'.zip')) as z:failed.append(idx['cases'][k]['status']=='failed' and 'results.json' not in z.namelist())
gate('G08-I11 real failed task ZIP is not accepted optimal results',all(failed),failed_task_ids=[idx['cases'][k]['task'] for k in ['expected_failed_iteration_limit','expected_failed_no_generation']])
gate('G08-I12 frozen rerun exact policy equality and original task immutability',idx['frozen_rerun']['original_unchanged'] and idx['frozen_rerun']['policies_equal'],**idx['frozen_rerun'])
out=dict(independent_named_gates=len(checks),passed=sum(x['passed'] for x in checks),failed=sum(not x['passed'] for x in checks),scope='new controls/original-data-subset variant, NOT whole-paper precision; LP groups are subchecks, not pytest tests',checks=checks);(E/'independent_gates.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));print(json.dumps(out,ensure_ascii=False,indent=2))
