"""Build small public patch + acceptance packages; never include private data or .env."""
from pathlib import Path,PurePosixPath
import json,hashlib,tarfile,difflib,zipfile,tempfile,subprocess,datetime,importlib.metadata
ROOT=Path(__file__).resolve().parents[3];E=Path('/workspace/sim-agent-phase7-evidence');BASE=Path('/workspace/sim-agent-backups/20261107-140456-phase7-public');OUT=ROOT.parent
assert (E/'current_full_result.json').exists() and (E/'history_preservation_final.json').exists()
full=json.loads((E/'current_full_result.json').read_text());assert not json.loads((E/'history_preservation_final.json').read_text())['changed_existing_records']
codefiles={str(p.relative_to(ROOT/'app')):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'app').rglob('*.py'))};codehash=hashlib.sha256(json.dumps(codefiles,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()).hexdigest();before={}
with tarfile.open(BASE/'public-source.tar.gz') as t:
 for x in t:
  if x.isfile() and PurePosixPath(x.name).parts[0] in ('app','tests','docs','cases'):before[x.name]=t.extractfile(x).read()
paths=[]
for folder in ['app','tests','docs','cases/paper_reproduction/phase7']:
 for p in (ROOT/folder).rglob('*'):
  if p.is_file() and not any(k in p.parts for k in ['__pycache__','.pytest_cache','.git','vendor']) and p.suffix in {'.py','.js','.cjs','.html','.css','.md','.json','.csv','.txt','.patch','.sh','.toml','.ini','.yaml','.yml','.xlsx'} and not p.name.startswith('.env') and p.name!='settings.json':paths.append(p)
changed={str(p.relative_to(ROOT)):p.read_bytes() for p in paths if before.get(str(p.relative_to(ROOT)))!=p.read_bytes()};patch=[]
binaries={n:b for n,b in changed.items() if Path(n).suffix=='.xlsx'}
def physical_lines(b):
 parts=b.decode().split('\n');return [v+'\n' for v in parts[:-1]]+([parts[-1]] if parts[-1] else [])
for n,b in sorted(changed.items()):
 if n in binaries:continue
 old=before.get(n,b'');a=physical_lines(old);bb=physical_lines(b);patch += difflib.unified_diff(a,bb,fromfile='a/'+n if n in before else '/dev/null',tofile='b/'+n)
 # All current public text files use trailing newline except raw/preset files. GNU patch needs explicit marker.
 # difflib leaves unterminated hunk lines; normalize below per line.
fixed=[]
for line in patch:
 if not line.endswith('\n'):fixed.extend([line+'\n','\\ No newline at end of file\n'])
 else:fixed.append(line)
patchtext=''.join(fixed);(E/'phase7-public.patch').write_text(patchtext)
with tempfile.TemporaryDirectory(prefix='phase7-patch-smoke-',dir=E) as td:
 d=Path(td)
 for n,b in before.items():p=d/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
 q=subprocess.run(['patch','-p1','--batch','--forward','-i',str(E/'phase7-public.patch')],cwd=d,text=True,capture_output=True);(E/'patch_smoke.log').write_text(q.stdout+q.stderr);assert q.returncode==0
 for n,b in binaries.items():p=d/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
 for n,b in changed.items():assert (d/n).read_bytes()==b,n
info=dict(created_china_standard_time=datetime.datetime.now().astimezone().isoformat(),baseline_backup=str(BASE),before_python_hash=json.loads((E/'checkpoint_before.json').read_text())['source_hash'],execution_python_hash=codehash,changed_public_files=len(changed),files={n:hashlib.sha256(b).hexdigest() for n,b in changed.items()},code_files=codefiles,versions={n:importlib.metadata.version(n) for n in ['pyomo','highspy','scipy','numpy','pydantic','fastapi']},full_suite=full,patch_applied_and_exact_file_hashes_verified=True,binary_assets_copy_after_patch={n:hashlib.sha256(b).hexdigest() for n,b in binaries.items()},excluded=['.env','settings.json','private project payloads','databases','old private 1h ZIP','original missing oracle NOT replaced'])
(E/'source_manifest.json').write_text(json.dumps(info,ensure_ascii=False,indent=2))
restore='''基线公共源码备份：%s/public-source.tar.gz；baseline hash%s。\n恢复仅适用于公共源码，不含也不覆盖项目/版本/任务数据：先确认catalog无running且执行域active=null、queue0；备份当前已验证源码；按source_manifest中文件表移开本批新增公共文件，再从原备份恢复列出的原公共源码。不得删除项目数据库/历史；不得还原.env/settings.json。通过现有app supervisor正常reload，确认/health ok/mock。补丁用于原基线上patch -p1；XLSX为公开原始二进制资产，不进入文本patch，须从changed/对应原路径逐项复制（清单binary_assets_copy_after_patch）；已在独立临时目录真实apply并逐文件验证，不对运行产品做回滚测试。\n旧环境的外部CLI与原oracle不在本包，不能用本批新SciPy参考冒充恢复旧兼容指纹。\n'''%(BASE,info['before_python_hash'])
(E/'RESTORE_PHASE6.zh.md').write_text(restore)
impl={'phase7-public.patch':(E/'phase7-public.patch').read_bytes(),'source_manifest.json':(E/'source_manifest.json').read_bytes(),'RESTORE_PHASE6.zh.md':restore.encode()};impl.update({'changed/'+n:b for n,b in changed.items()})
accept={}
# Own public frozen tasks, public raw evidence, canonical hashes and final logs only.
for pat in ['*.zip','api_acceptance_index.json','independent_gates.json','independent_direct.json','data_reference.json','data_reference.log','current_full_result.json','pytest_full.log','pytest_targeted*.log','pytest_gpu_final.log','history_hashes_before.json','history_preservation_final.json','source_manifest.json','checkpoint_before.json','code_identity.json','final_health.json','verification_summary.json','ui_static_contract.json','ui_label*','critical_compatibility.json','critical_compatibility.log','phase5_6_history_preserved.json','api_acceptance.log','legacy_compatibility.log','history_preservation.log','cross_module_status.json','packaging_failure*']:
 for p in E.glob(pat):
  if p.is_file():accept['evidence/'+p.name]=p.read_bytes()
for p in (E/'initial_harness_failure').glob('*'):
 if p.is_file():accept['evidence/initial_harness_failure/'+p.name]=p.read_bytes()
for n in ['summary.json','extra_summary.json','checks.json','extra_checks.json','failures.json','source_code_hash_manifest.json']:
 p=E/'legacy_compatibility'/n
 if p.exists():accept['evidence/legacy_compatibility/'+n]=p.read_bytes()
for n,b in changed.items():
 if n.startswith(('docs/','cases/paper_reproduction/phase7/')):accept['public/'+n]=b
packages=[]
for kind,files in [('implementation',impl),('acceptance',accept)]:
 manifest={n:hashlib.sha256(b).hexdigest() for n,b in files.items()};files['SHA256_MANIFEST.json']=json.dumps(manifest,sort_keys=True,indent=2).encode();p=OUT/f'sim-agent-phase7-gpu-{kind}-20261107.zip'
 with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED) as z:
  for n,b in sorted(files.items()):assert not any(k in n for k in ['.env','settings.json','.sqlite']);z.writestr(n,b)
 assert p.stat().st_size<25_000_000
 with zipfile.ZipFile(p) as z:
  assert z.testzip() is None
  for n,h in manifest.items():assert hashlib.sha256(z.read(n)).hexdigest()==h
 packages.append(dict(kind=kind,path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),members=len(files)))
(E/'packages.json').write_text(json.dumps(packages,indent=2));print(json.dumps(packages,indent=2))
