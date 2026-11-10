"""Fresh selected prior-mode reruns via normal frozen task API; original records hash-only."""
import json,urllib.request,hashlib,sys,zipfile,io,csv
from pathlib import Path
E=Path(sys.argv[1]);B='http://127.0.0.1:8080/api/foundation';out=[]
def api(p,x=None):return json.load(urllib.request.urlopen(urllib.request.Request(B+p,data=None if x is None else json.dumps(x).encode(),headers={'Content-Type':'application/json'}),timeout=240))
def h(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
for key,id in [('thermal','da4c5d48e4344406'),('migration15min','0ca2cc19587e460c'),('cfe_small','fafed10efe0c434c'),('grid_negative','a925fe9191494430')]:
 before=api('/tasks/'+id);rr=api('/tasks/'+id+'/rerun',{});t=api('/tasks/'+rr['id']+'/run',{});assert t['status']=='completed',t.get('error');assert t['snapshot']==before['snapshot'];assert h(api('/tasks/'+id))==h(before);r=t['full_result'];record=dict(case=key,original=id,rerun=t['id'],input_hash=t['input_hash'],execution_code_hash=t.get('execution_code_hash'),original_full_hash=h(before),original_unchanged=True)
 if key=='thermal':
  assert abs(r['objective']+10472.655547077002)<1e-6;assert t['kpis']['kpis']['heat_delivered_mwh']==11.5;record.update(objective=r['objective'],terminal_heat_mwh=11.5,heat_boundary=r['heat_boundary_audit'],pipe=r['heat_network_audit'])
 elif key=='migration15min':
  assert r['objective']==-72000;assert abs(t['kpis']['kpis']['migrated_mwh']-240)<1e-6;record.update(objective=r['objective'],gross_mwh=t['kpis']['kpis']['migrated_mwh'],migration_audit=r['migration_audit'])
 elif key=='cfe_small':assert r['objective']==4;record.update(objective=r['objective'],scope='2h analytic benchmark; NOT fresh 8760 solve')
 else:
  q={p['signal']:p for p in r['policies']};assert abs(q['lmce']['actual_operational_delta_tco2']+.4)<1e-8 and abs(q['lmce']['actual_cost_delta_usd']-2)<1e-8;record.update(policies=[{k:v for k,v in p.items() if k in ('signal','status','actual_operational_delta_tco2','actual_cost_delta_usd')} for p in r['policies']])
 if key in ('cfe_small','grid_negative'):url=B+'/tasks/'+t['id']+'/export.zip'
 else:opened=api('/tasks/'+t['id']+'/open',{});url='http://127.0.0.1:8080/api/sessions/'+opened['session_id']+'/export.zip'
 bb=urllib.request.urlopen(url,timeout=120).read();(E/('critical_'+key+'.zip')).write_bytes(bb)
 with zipfile.ZipFile(io.BytesIO(bb)) as z:
  assert json.loads(z.read('input_snapshot.json'))==t['snapshot']
  if key=='migration15min':
   names=[n for n in z.namelist() if 'migration' in n and n.endswith('.csv')];record['nonempty_migration_csv']=[dict(name=n,rows=len(list(csv.DictReader(io.StringIO(z.read(n).decode()))))) for n in names];assert any(v['rows']>0 for v in record['nonempty_migration_csv'])
 record['zip_sha256']=hashlib.sha256(bb).hexdigest();out.append(record);(E/'critical_compatibility.json').write_text(json.dumps(out,indent=2));print(key,t['id'],'passed',flush=True)
old=api('/tasks/2e8c374986114082');assert old['status']=='completed';out.append(dict(case='old_1h_frozen_readonly_NOT_new_solve',task=old['id'],full_record_hash=h(old),objective=old['full_result']['objective'],input_hash=old['input_hash']));(E/'critical_compatibility.json').write_text(json.dumps(out,indent=2))
