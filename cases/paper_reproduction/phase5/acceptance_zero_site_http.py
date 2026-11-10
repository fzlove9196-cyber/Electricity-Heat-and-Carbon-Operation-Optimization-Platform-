"""External HTTP regression for a genuine frozen zero-assigned-site failure; no app imports."""
import sys,pathlib,json,urllib.request,zipfile,io,csv,hashlib
O=pathlib.Path(sys.argv[1]);O.mkdir(parents=True,exist_ok=True)
def api(p,b=None,raw=False):
 q=urllib.request.Request('http://127.0.0.1:8080'+p,data=None if b is None else json.dumps(b).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(q,timeout=1000) as f:v=f.read()
 return v if raw else json.loads(v)
oldid=sys.argv[2] if len(sys.argv)>2 else '94820c4c112846a1'
old=api('/api/foundation/tasks/'+oldid);oldhash=hashlib.sha256(json.dumps(old,ensure_ascii=False,sort_keys=True).encode()).hexdigest();assert old['status']=='failed' and 'ZeroDivisionError' in old['error']
r=api('/api/foundation/tasks/'+sys.argv[3]) if len(sys.argv)>3 else api('/api/foundation/tasks/'+oldid+'/rerun',{});r=r if r['status']=='completed' else api('/api/foundation/tasks/'+r['id']+'/run',{});assert r['status']=='completed',r.get('error')
b=api('/api/foundation/tasks/'+r['id']+'/export.zip',raw=True);(O/'zero_site_rate_fixed.zip').write_bytes(b);z=zipfile.ZipFile(io.BytesIO(b));out=json.loads(z.read('results.json'));model=json.loads(z.read('model.json'));rows=list(csv.DictReader(io.StringIO(z.read('hourly.csv').decode())));flows=list(csv.DictReader(io.StringIO(z.read('spatial_flows.csv').decode())));by={x['site']:x for x in out['investments']};zero=by['B'];assigned=sum(float(x['actual_load_mw'])*float(x['duration_h']) for x in rows if x['site']=='B');shift=sum(float(x['shift_mwh']) for x in flows)
# Analytic proof: total2MW served for2h; A's1 EUR/MW-year solar dominates B's1000, so capA2/capB0. Two shifted MWh at1e-5 cost2e-5.
expected=2+2e-5;actual=sum(g['capacity_mw']*g['capital_per_mw_year'] for inv in out['investments'] for g in inv['generators'])+shift*model['spatial_fee_per_mwh']
unchanged=hashlib.sha256(json.dumps(api('/api/foundation/tasks/'+oldid),ensure_ascii=False,sort_keys=True).encode()).hexdigest()==oldhash
ok=assigned==0 and zero['load_mwh']==0 and all(zero[k] is None for k in ['annual_generation_share','physical_clean_fraction','paper_cfe_score']) and abs(out['objective']-expected)<1e-8 and abs(actual-expected)<1e-8 and shift==2 and r['input_hash']==old['input_hash'] and r['snapshot']==old['snapshot'] and unchanged
check=dict(name='zero_assigned_site_rates_null_not_failed_actual_frozen_rerun',passed=ok,expected_objective=expected,actual_objective=out['objective'],independent_objective=actual,zero_site_load_mwh=assigned,shift_mwh=shift,undefined_rates={k:zero[k] for k in ['annual_generation_share','physical_clean_fraction','paper_cfe_score']},old_failed_task=oldid,new_completed_task=r['id'],original_failed_record_unchanged=unchanged,input_hash=r['input_hash'],execution_code_hash=r['execution_code_hash'])
(O/'zero_site_check.json').write_text(json.dumps(check,ensure_ascii=False,indent=2));(O/'zero_site_ui_entry.json').write_text(json.dumps(dict(project=old['snapshot']['project_id'],scenario=old['snapshot']['scenario_id'],version=old['snapshot']['version_id'],task=r['id']),ensure_ascii=False,indent=2));print(json.dumps(check,ensure_ascii=False),flush=True);assert ok
