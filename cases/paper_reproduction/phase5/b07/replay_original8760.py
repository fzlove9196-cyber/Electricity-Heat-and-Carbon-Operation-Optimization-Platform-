"""Three real frozen API reruns, same original inputs/algorithm as failed B.
Independently reconstruct every CSV constraint/cost and compare separate SciPy LP.
"""
import sys,pathlib,json,urllib.request,zipfile,io,csv,hashlib,datetime,ast,time,concurrent.futures
O=pathlib.Path(sys.argv[1]);O.mkdir(parents=True,exist_ok=True);ROOT=pathlib.Path(__file__).resolve().parents[4];REF=pathlib.Path('/workspace/sim-agent-phase5-evidence/scipy_original8760');checks=[];samples=[]
def api(p,b=None,raw=False):
 q=urllib.request.Request('http://127.0.0.1:8080'+p,data=None if b is None else json.dumps(b).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(q,timeout=2400) as f:v=f.read()
 return v if raw else json.loads(v)
def check(name,passed,**kw):
 d=dict(name=name,passed=bool(passed),**kw);checks.append(d);(O/'checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2));print(json.dumps(d,ensure_ascii=False),flush=True)
def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
# Extract only the independent CSV audit functions, never application code or top-level run side effects.
text=(ROOT/'cases/paper_reproduction/phase5/acceptance_http.py').read_text();tree=ast.parse(text);ns=dict(io=io,csv=csv,datetime=datetime,check=check);exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ['csvrows','audit_export']],type_ignores=[]),'independent_csv_auditor','exec'),ns)
originals={'riepin8760_f0':'979d1b3824114c60','riepin8760_f40':'36fd6e75ba634101','riepin8760_f40_manuscript':'5d8d5fc6edfb4e23'};before={};new={};entries={}
assert api('/health')=={'ok':True,'mock':True};assert api('/api/solver-execution/status')['active'] is None
for key,id in originals.items():
 old=api('/api/foundation/tasks/'+id);before[id]=digest(old);r=api('/api/foundation/tasks/'+id+'/rerun',{});new[key]=r;entries[key]=dict(old_task=id,new_task=r['id'],project=old['snapshot']['project_id'],scenario=old['snapshot']['scenario_id'],version=old['snapshot']['version_id'],input_hash=old['input_hash']);check(key+'_original_input_dimensions',old['snapshot']['model']['source']['network_blob']=='e95dd9aba48f997b9ae27ca4df5123790b6f7a2e' and len(old['snapshot']['model']['sites'])==3 and all(len(s['load_mw'])==8760 for s in old['snapshot']['model']['sites']),source_kind='AUTHOR_ORIGINAL8760; not synthetic/control/time aggregation')
(O/'ui_entries.json').write_text(json.dumps(entries,indent=2))
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
 pending={pool.submit(api,'/api/foundation/tasks/'+t['id']+'/run',{}):key for key,t in new.items()}
 while pending:
  done,_=concurrent.futures.wait(pending,timeout=5,return_when=concurrent.futures.FIRST_COMPLETED)
  try:samples.append(api('/api/solver-execution/status'));(O/'execution_status_samples.json').write_text(json.dumps(samples,indent=2))
  except Exception as e:print('status sample failed',type(e).__name__,str(e),flush=True)
  for future in done:
   key=pending.pop(future);r=future.result();f=O/key;f.mkdir(exist_ok=True);check(key+'_status',r['status']=='completed',status=r['status'],task=r['id'],error=r.get('error'))
   b=api('/api/foundation/tasks/'+r['id']+'/export.zip',raw=True);(f/'export.zip').write_bytes(b)
   if r['status']!='completed':(f/'failure.json').write_text(json.dumps(r,ensure_ascii=False,indent=2));continue
   z=zipfile.ZipFile(io.BytesIO(b));snap=json.loads(z.read('input_snapshot.json'));res=json.loads(z.read('results.json'));rows=ns['csvrows'](z,'hourly.csv');flows=ns['csvrows'](z,'spatial_flows.csv');t=new[key];check(key+'_freeze_open_export',digest(snap)==t['input_hash'] and snap==t['snapshot'] and r['input_hash']==entries[key]['input_hash'] and len(rows)==26280 and api('/api/foundation/tasks/'+r['id']+'/open',{}).get('model_kind')=='opt_cfe',rows=len(rows),input_hash=t['input_hash'],execution_code_hash=r['execution_code_hash']);ns['audit_export'](key,snap['model'],res,rows,flows);ref=json.loads((REF/(key+'.json')).read_text());difference=res['objective']-ref['objective'];check(key+'_independent_original8760_LP_optimum',ref['optimal'] and res['solver']['optimal'] and abs(difference)<.05,product_eur=res['objective'],reference_eur=ref['objective'],difference_eur=difference,elapsed_s=res['solver']['total_seconds'],algorithm=res['solver']['lp_algorithm'],scope='full original8760 same procurement model; NOT entire background/four configurations');g=res['execution_serialization'];check(key+'_variable_ownership_and_execution_domain',g['scope']=='annual_cfe' and not g['reentrant'] and g['time_limit_excludes_queue'] and len(g['variable_ownership_checks'])==1 and all(v['foreign_variables']==0 for v in g['variable_ownership_checks']),queue_wait_seconds=g['queue_wait_seconds'],pipeline_seconds=g['pipeline_seconds'],ownership=g['variable_ownership_checks']);(f/'summary.json').write_text(json.dumps(res,ensure_ascii=False,indent=2));entries[key]['objective']=res['objective'];entries[key]['code_hash']=r['execution_code_hash'];(O/'ui_entries.json').write_text(json.dumps(entries,indent=2))
check('original_failed_and_successful_records_unchanged',all(digest(api('/api/foundation/tasks/'+id))==h for id,h in before.items()),original_tasks=originals)
check('real_overlapping_requests_serialized_with_visible_FIFO_queue',any(s['active'] and s['queued_count']>=2 for s in samples),max_queued=max(s['queued_count'] for s in samples),evidence='3 simultaneous real full-year API requests; one active domain,2+ visible waiters; queue wait excluded from solver softlimit; global idle checked separately after ALL independent clients finish')
(O/'summary.json').write_text(json.dumps(dict(gates=len(checks),passed=sum(c['passed'] for c in checks),failed=[c for c in checks if not c['passed']],entries=entries),ensure_ascii=False,indent=2));assert len(checks)==20 and all(c['passed'] for c in checks)
