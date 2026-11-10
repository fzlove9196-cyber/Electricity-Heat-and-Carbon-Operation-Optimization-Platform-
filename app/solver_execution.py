"""Process-wide FIFO execution domain for Pyomo's non-thread-safe shared visitors.
Covers construction -> representation -> solver -> solution load, not just HiGHS.run.
No exception swallowing, retries, alternative answers or changed mathematical constraints.
"""
from __future__ import annotations
import contextlib,contextvars,functools,threading,time
from collections import deque
# Resolve the deferred callback before RAG/worker threads can replace the tee lock
# between its acquire/release. This starts no process or service.
from pyomo.common import dependencies as _pyomo_dependencies
_pyomo_dependencies.multiprocessing.get_start_method(allow_none=True)
_condition=threading.Condition(threading.RLock())
_queue=deque();_active=None;_serial=0;_local=threading.local()
_request=contextvars.ContextVar('pyomo_request',default=None)

def execution_status():
    with _condition:
        now=time.monotonic()
        def visible(item,waiting):
            return {k:v for k,v in item.items() if k not in ('enqueued','started','thread')}|{('wait_seconds' if waiting else 'elapsed_seconds'):max(0,now-item['enqueued' if waiting else 'started'])}
        return dict(schema='pyomo_execution_domain_v1',process_scope=True,policy='FIFO; all product Pyomo construction/representation/solve/load serialized; nested same-thread calls reentrant',active=None if _active is None else visible(_active,False),queued=[visible(q,True) for q in _queue],queued_count=len(_queue),time_limit_boundary='solver soft limit excludes queue/build/export; queue wait is separately audited')

@contextlib.contextmanager
def pyomo_execution(scope):
    global _active,_serial
    depth=getattr(_local,'depth',0)
    if depth:
        _local.depth=depth+1
        try:yield dict(schema='pyomo_execution_domain_v1',scope=scope,reentrant=True,queue_wait_seconds=0.,ticket=_local.ticket)
        finally:_local.depth=depth
        return
    start=time.monotonic()
    with _condition:
        _serial+=1;item=dict(ticket=_serial,scope=scope,request_label=_request.get() or scope,enqueued=start,thread=threading.get_ident());_queue.append(item)
        try:
            while _active is not None or _queue[0] is not item:_condition.wait()
        except BaseException:
            _queue.remove(item);_condition.notify_all();raise
        _queue.popleft();_active=item|dict(started=time.monotonic());_local.depth=1;_local.ticket=item['ticket'];_local.validations=[]
    meta=dict(schema='pyomo_execution_domain_v1',scope=scope,request_label=item['request_label'],ticket=item['ticket'],reentrant=False,queue_wait_seconds=time.monotonic()-start,policy='FIFO full Pyomo pipeline; no solver fallback',time_limit_excludes_queue=True)
    try:yield meta
    finally:
        meta['pipeline_seconds']=time.monotonic()-_active['started'];meta['variable_ownership_checks']=list(_local.validations)
        with _condition:_active=None;_local.depth=0;_local.validations=[];_condition.notify_all()

def serialized_pyomo(scope):
    def decorate(fn):
        @functools.wraps(fn)
        def run(*args,**kwargs):
            with pyomo_execution(scope) as metadata:result=fn(*args,**kwargs)
            if isinstance(result,dict):result['execution_serialization']=metadata
            return result
        return run
    return decorate

def contextual_task(fn):
    @functools.wraps(fn)
    def run(id,*args,**kwargs):
        token=_request.set('task:'+str(id))
        try:return fn(id,*args,**kwargs)
        finally:_request.reset(token)
    return run

def checked_solve(solver,model,**kwargs):
    """Fail closed on foreign variables before optimization; never rename bad symbols.
    This is an assertion in addition to the full-pipeline domain, not its replacement.
    The installed appsi adapter exposes its variable map; an incompatible future
    adapter is explicitly rejected rather than silently skipping the assertion.
    """
    if not getattr(_local,'depth',0):raise RuntimeError('Pyomo solve outside the process-wide execution domain')
    import pyomo.environ as pyo
    solver.set_instance(model)
    expected={id(v) for v in model.component_data_objects(pyo.Var,descend_into=True)}
    variables=getattr(solver,'_vars',None)
    if not isinstance(variables,dict):raise RuntimeError('Unsupported appsi variable-map contract; ownership cannot be audited')
    foreign=set(variables)-expected
    proof=dict(declared_variables=len(expected),solver_variables=len(variables),foreign_variables=len(foreign))
    _local.validations.append(proof)
    if foreign:raise RuntimeError('Foreign variables detected in Pyomo solver mapping; refusing solve, not renaming or falling back')
    result=solver.solve(model,**kwargs)
    if set(solver._vars)-expected:raise RuntimeError('Foreign variables appeared during solver update; refusing result')
    return result
