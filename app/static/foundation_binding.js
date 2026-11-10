/* Pure binding contract used by the UI and node regressions; no DOM/browser. */
(function(root){
  const fields=['location','year','timezone','start','step_minutes','length'];
  function differences(expected,actual){return fields.filter(k=>expected?.[k]!==actual?.[k]).map(field=>({field,expected:expected?.[field],actual:actual?.[field]}));}
  function plan({draft,resources,resourceId,target='',mode='add',alignAxis=false}){
    const resource=resources.find(r=>r.id===resourceId);
    if(!resource)throw Error('所选资源版本不存在，请重新选择；不会回退到示例或首项');
    if(!['add','replace'].includes(mode))throw Error('未知绑定操作');
    const device=resource.kind==='device',key=device?'device_bindings':'bindings';
    if(!device&&resource.kind!=='load'&&target)throw Error('气象/电价/碳请选场景公共信号');
    const previous=(draft[key]||[]).filter(b=>{const r=resources.find(x=>x.id===b.resource_id);if(!r)throw Error('已有绑定资源缺失，需先修复');return r.kind===resource.kind&&(device?r.device_type===resource.device_type&&b.target===target:resource.kind!=='load'||(b.target||'')===target)});
    if(mode==='add'&&previous.length)throw Error('同类/同目标已有绑定，请明确使用“替换同类绑定”');
    if(mode==='replace'&&!previous.length)throw Error('没有同类/同目标绑定，请使用“新增绑定”');
    const bindings=(draft[key]||[]).filter(b=>!previous.includes(b));bindings.push({resource_id:resource.id,target});
    const payload={[key]:bindings};if(alignAxis&&!device)payload.axis=JSON.parse(JSON.stringify(resource.axis));
    return {resource,payload,previous,differences:device?[]:differences(draft.axis,resource.axis),axisChanged:!!(alignAxis&&!device&&differences(draft.axis,resource.axis).length)};
  }
  function restoreSelection(select,html,value){select.innerHTML=html;if(value&&Array.from(select.options).some(x=>x.value===value))select.value=value;else select.value='';return select.value;}
  const api={differences,plan,restoreSelection};if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.PFBinding=api;
})(typeof window==='undefined'?globalThis:window);
