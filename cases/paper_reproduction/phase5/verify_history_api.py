"""Compare every pre-batch complete API record; never store private payloads."""
import json,urllib.request,pathlib,hashlib,datetime,sys
O=pathlib.Path(sys.argv[1]);before=json.loads((O/'history_hashes_before.json').read_text());base='http://127.0.0.1:8080/api/foundation';api=lambda p:json.load(urllib.request.urlopen(base+p,timeout=120));c=api('/catalog');id=next(iter(before['version']));v=next(v for v in c['version'] if v['id']==id);candidates=[('compact',dict(sort_keys=True,ensure_ascii=False,separators=(',',':'))),('default',dict(sort_keys=True,ensure_ascii=False)),('ascii_default',dict(sort_keys=True))];matches=[(name,kw) for name,kw in candidates if hashlib.sha256(json.dumps(v,**kw).encode()).hexdigest()==before['version'][id]];assert len(matches)==1;name,kw=matches[0];h=lambda x:hashlib.sha256(json.dumps(x,**kw).encode()).hexdigest();diff=[];counts={}
for kind,records in before.items():
 if not isinstance(records,dict):continue
 current={x['id']:x for x in c[kind]} if kind!='tasks' else None;counts[kind]=len(records)
 for id,oldhash in records.items():
  now=api('/tasks/'+id) if kind=='tasks' else current.get(id)
  if now is None or h(now)!=oldhash:diff.append(dict(kind=kind,id=id,missing=now is None,old=oldhash,current=None if now is None else h(now)))
r=dict(time_asia_shanghai=datetime.datetime.now().astimezone().isoformat(),canonical=name,full_record_counts=counts,changed_existing_records=diff,passed=not diff,scope='all prebatch full version/task and project/template/library records; no private payload persisted');(O/'history_preservation_final.json').write_text(json.dumps(r,ensure_ascii=False,indent=2));print(json.dumps(r,ensure_ascii=False));assert not diff
