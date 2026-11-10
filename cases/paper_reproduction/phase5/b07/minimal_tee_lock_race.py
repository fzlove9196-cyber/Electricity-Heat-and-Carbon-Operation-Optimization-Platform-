"""Legal scheduling of deferred multiprocessing lock replacement, fresh process only."""
import pathlib,sys,json,threading,inspect,traceback,io
from pyomo.common import dependencies as deps
from pyomo.common.tee import capture_output
mode=sys.argv[1];out=pathlib.Path(sys.argv[2]);out.parent.mkdir(parents=True,exist_ok=True)
if mode=='protected':import app.solver_execution
before=id(deps.capture_output_lock);ready=threading.Event();done=threading.Event();proof={}
def resolve():
 assert ready.wait(10);deps.multiprocessing.get_start_method(allow_none=True);proof['lock_id_after_deferred_resolution']=id(deps.capture_output_lock);done.set()
t=threading.Thread(target=resolve);t.start();fn=capture_output.__exit__;src,first=inspect.getsourcelines(fn);line=first+next(i for i,s in enumerate(src) if 'capture_output_lock.release()' in s);paused=False
def trace(frame,event,arg):
 global paused
 if not paused and frame.f_code is fn.__code__ and event=='line' and frame.f_lineno==line:paused=True;ready.set();assert done.wait(10)
 return trace
err=None
try:
 sys.settrace(trace)
 with capture_output(output=io.StringIO(),capture_fd=False):pass
except Exception as e:err=f'{type(e).__name__}: {e}';out.with_suffix('.traceback.txt').write_text(traceback.format_exc())
finally:sys.settrace(None);ready.set();t.join(10)
proof.update(mode=mode,lock_id_before=before,error=err,replaced=before!=proof['lock_id_after_deferred_resolution']);out.write_text(json.dumps(proof,indent=2));print(json.dumps(proof))
if mode=='unsafe':assert err and 'released too many times' in err and proof['replaced']
else:assert err is None and not proof['replaced']
