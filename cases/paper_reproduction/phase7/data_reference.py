"""Independent stdlib interpolation/metrics, source Git blob checks; no product/build_inputs imports."""
import csv,json,math,bisect,hashlib,sys
from pathlib import Path
from datetime import datetime
import openpyxl
R=Path(__file__).resolve().parent;E=Path(sys.argv[1]);rows=list(csv.DictReader((R/'raw/emerald_dvfs_sweep.csv').open()));train={100,200,300,400};hold={250,350};fits=[]
for group in sorted({r['Workload'] for r in rows}):
 rr={int(r['GPU power cap']):r for r in rows if r['Workload']==group}
 for cap in sorted(hold):
  low=max(t for t in train if t<cap);high=min(t for t in train if t>cap);fraction=(cap-low)/(high-low);out={'workload':group,'cap':cap}
  for f,key in [('power per GPU','power_w'),('normalized throughput','rate')]:out['predicted_'+key]=(1-fraction)*float(rr[low][f])+fraction*float(rr[high][f]);out['measured_'+key]=float(rr[cap][f])
  fits.append(out)
p_rmse=math.sqrt(sum((v['predicted_power_w']-v['measured_power_w'])**2 for v in fits)/16);q_rmse=math.sqrt(sum((v['predicted_rate']-v['measured_rate'])**2 for v in fits)/16);expected=json.loads((R/'data_evidence.json').read_text());assert abs(p_rmse-expected['power_rmse_w'])<1e-12 and abs(q_rmse-expected['normalized_rate_rmse'])<1e-12
blobs={}
for name,target in {'emerald_dvfs_sweep.csv':'6be26dd1e579f0fa386026614446de9b55ea053f','emerald_SRP_exp_performance.csv':'9dd55d004480029188a2d05b67a3ef82259bfd0a','emerald_Fig345_data.xlsx':'58c3b89ef6dd24a3cf69483bd427cae7d7a5309c'}.items():
 b=(R/'raw'/name).read_bytes();got=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest();assert got==target,(name,got,target);blobs[name]=dict(git_blob=got,sha256=hashlib.sha256(b).hexdigest(),source='archived author main contents index; exact blob, NOT asserted paper publication commit')
readme=json.loads((R/'raw/author_README_provenance.json').read_text());b=(R/'raw/author_README.md').read_bytes();assert hashlib.sha256(b).hexdigest()==readme['sha256'];assert hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()==readme['git_blob_sha1'];blobs['author_README.md']=readme
w=openpyxl.load_workbook(R/'raw/emerald_Fig345_data.xlsx',read_only=True,data_only=True);rr=list(w['Fig5'].values)[2:];actual=[(datetime.fromisoformat(a[0]),float(a[7])) for a in rr if isinstance(a[0],str) and isinstance(a[7],(int,float))];points=sorted({datetime.fromisoformat(a[9]):float(a[10]) for a in rr if isinstance(a[9],str) and isinstance(a[10],(int,float))}.items());times=[p[0] for p in points];errors=[[],[]];kept=[]
for t,v in actual:
 if not times[0]<=t<=times[-1]:continue
 i=max(0,bisect.bisect_right(times,t)-1);j=min(i+1,len(points)-1);f=(t-times[i]).total_seconds()/(times[j]-times[i]).total_seconds() if i!=j else 0;linear=points[i][1]*(1-f)+points[j][1]*f;errors[0].append((linear-v)**2);errors[1].append((points[i][1]-v)**2);kept.append(v)
mean=sum(kept)/len(kept);values=[math.sqrt(sum(v)/len(v))/mean for v in errors];assert len(kept)==400 and len(points)==37 and abs(values[0]-expected['fig5']['linear_nrmse'])<1e-12 and abs(values[1]-expected['fig5']['previous_hold_nrmse'])<1e-12
record=dict(passed=True,calibration_points=32,heldout_points=16,fit_power_rmse_w=p_rmse,fit_normalized_rate_rmse=q_rmse,blob_sources=blobs,fig5=dict(n_actual=400,n_projection=37,linear_nrmse=values[0],previous_hold_nrmse=values[1],time_axis='original source timestamps retained; source zone not established, no field clock inferred'),scope='power fit separate from policy/SLA and original33-experiment4.52%; Fig5 alignment sensitivity not exact author validation');(E/'data_reference.json').write_text(json.dumps(record,indent=2));g=json.loads((E/'independent_gates.json').read_text());g=[x for x in g if x['name']!='independent_original_data_split_blob_fit_and_figure_alignment'];g.append(dict(name='independent_original_data_split_blob_fit_and_figure_alignment',**record));(E/'independent_gates.json').write_text(json.dumps(g,indent=2));print(json.dumps(record,indent=2));print('new GPU independent gates',len(g))
