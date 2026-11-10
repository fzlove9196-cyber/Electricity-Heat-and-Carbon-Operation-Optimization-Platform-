"""Read-only independent re-audit. No solves; retain initial19/20 harness failure.
Annual client must not assert that OTHER valid clients have already stopped.
"""
import sys,pathlib,json,urllib.request,zipfile,io,csv,hashlib,datetime,ast
O=pathlib.Path(sys.argv[1]);ROOT=pathlib.Path(__file__).resolve().parents[4];REF=pathlib.Path('/workspace/sim-agent-phase5-evidence/scipy_original8760');E=pathlib.Path('/workspace/sim-agent-phase5-evidence');checks=[]
def api(p):
 with urllib.request.urlopen('http://127.0.0.1:8080'+p,timeout=180) as f:return json.load(f)
def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def check(name,passed,**kw):
 d=dict(name=name,passed=bool(passed),**kw);checks.append(d);(O/'reaudit_checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2));print(json.dumps(d,ensure_ascii=False),flush=True)
ns=dict(io=io,csv=csv,datetime=datetime,check=check);tree=ast.parse((ROOT/'cases/paper_reproduction/phase5/acceptance_http.py').read_text());exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ['csvrows','audit_export']],type_ignores=[]),'independent_csv_auditor', 'exec'),ns)
def csv_matches_native(native,z,name):
 rows=ns['csvrows'](z,name)
 if len(rows)!=len(native):return False
 for a,b in zip(native,rows):
  if set(a)!=set(b):return False
  for k,v in a.items():
   if v is None:
    if b[k]!='':return False
   elif isinstance(v,(int,float)) and not isinstance(v,bool):
    if float(b[k])!=float(v):return False
   elif b[k]!=str(v):return False
 return True
entries=json.loads((O/'ui_entries.json').read_text());unchanged=[]
oldzip={'riepin8760_f0':E/'release_B/independent_http/riepin8760_f0/export.zip','riepin8760_f40':E/'release_B/annual_symbol_map_failed_frozen.zip','riepin8760_f40_manuscript':E/'release_B/annual_symbol_map_DSM_failed_frozen.zip'}
for key,e in entries.items():
 r=api('/api/foundation/tasks/'+e['new_task']);z=zipfile.ZipFile(O/key/'export.zip');snap=json.loads(z.read('input_snapshot.json'));res=json.loads(z.read('results.json'));rows=ns['csvrows'](z,'hourly.csv');flows=ns['csvrows'](z,'spatial_flows.csv');model=snap['model'];check(key+'_original_input_dimensions',model['source']['network_blob']=='e95dd9aba48f997b9ae27ca4df5123790b6f7a2e' and len(model['sites'])==3 and all(len(s['load_mw'])==8760 for s in model['sites']),source_kind='AUTHOR_ORIGINAL8760; not synthetic/control/time aggregation');check(key+'_status',r['status']=='completed',task=r['id'],status=r['status']);check(key+'_freeze_open_export',snap==r['snapshot'] and digest(snap)==e['input_hash']==r['input_hash'] and len(rows)==26280,rows=len(rows),input_hash=r['input_hash'],execution_code_hash=r['execution_code_hash']);ns['audit_export'](key,model,res,rows,flows);ref=json.loads((REF/(key+'.json')).read_text());diff=res['objective']-ref['objective'];check(key+'_independent_original8760_LP_optimum',ref['optimal'] and res['solver']['optimal'] and abs(diff)<.05,product_eur=res['objective'],reference_eur=ref['objective'],difference_eur=diff,algorithm=res['solver']['lp_algorithm'],total_seconds=res['solver']['total_seconds']);g=res['execution_serialization'];check(key+'_variable_ownership_and_execution_domain',g['scope']=='annual_cfe' and not g['reentrant'] and g['time_limit_excludes_queue'] and len(g['variable_ownership_checks'])==1 and all(v['foreign_variables']==0 for v in g['variable_ownership_checks']),ownership=g['variable_ownership_checks'],queue_wait_seconds=g['queue_wait_seconds']);old=api('/api/foundation/tasks/'+e['old_task']);oz=zipfile.ZipFile(oldzip[key]);meta=json.loads(oz.read('task_metadata.json'));osnap=json.loads(oz.read('input_snapshot.json'));ok=all(old.get(k)==v for k,v in meta.items()) and old['snapshot']==osnap and old['input_hash']==e['input_hash']
 if old.get('full_result') is not None:
  stored=old['full_result'];tables={'hourly':'hourly.csv','spatial_flows':'spatial_flows.csv','daily_work':'daily_work.csv'};ok=ok and {k:v for k,v in stored.items() if k not in tables}==json.loads(oz.read('results.json')) and all(csv_matches_native(stored[k],oz,v) for k,v in tables.items())
 unchanged.append(ok)
check('original_failed_and_successful_records_unchanged',all(unchanged),fresh_api_vs_original_frozen_zip=unchanged,export_projection='results.json intentionally excludes3 tables; separately compare every old native hourly/spatial/daily row exactly against original CSV, no tolerance relaxation',initial_live_before_after_gate=next(x for x in json.loads((O/'checks.json').read_text()) if x['name']=='original_failed_and_successful_records_unchanged'))
samples=json.loads((O/'execution_status_samples.json').read_text());labels={'task:'+e['new_task'] for e in entries.values()};overlap=any(s['active'] and s['active']['request_label'] in labels and sum(q['request_label'] in labels for q in s['queued'])>=2 for s in samples);check('real_overlapping_requests_serialized_with_visible_FIFO_queue',overlap,max_queued=max(s['queued_count'] for s in samples),samples=len(samples),correction='Initial failed check also required global idle while unrelated clients were validly solving. This is client-envelope scope error, not overlap. Preserve original19/20 and traceback; defer global idle until all clients finish. No repeats of any annual solve.')
(O/'reaudit_summary.json').write_text(json.dumps(dict(gates=len(checks),passed=sum(c['passed'] for c in checks),failed=[c for c in checks if not c['passed']],original_harness_preserved=True,repeat_solves=0,scope='20 unique original8760 gates; do not add original19 to this20'),ensure_ascii=False,indent=2));assert len(checks)==20 and all(c['passed'] for c in checks)
