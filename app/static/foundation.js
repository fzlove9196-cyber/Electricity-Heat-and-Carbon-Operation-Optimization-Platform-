/* 产品对象闭环：项目→场景草稿→不可变版本→冻结任务→历史模型与结果。 */
(function(){
  const $=s=>document.querySelector(s), E=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const P='/api/foundation'; let C=null, project=localStorage.getItem('pfProject')||'', scenario=localStorage.getItem('pfScenario')||'', version='', selectedTask='', selectedDetail=null, dirty=false, draftOwner=null, context=null, bindingResource='', bindingTarget='';
  const call=async(path,body,method)=>{const r=await fetch(P+path,{method:method||(body?'POST':'GET'),headers:{'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:(d.detail?.message||JSON.stringify(d.detail)));return d};
  const msg=(text,bad=false)=>{const e=$('#pfMsg');if(e){e.textContent=text;e.className=bad?'pf-error':'pf-success'}};
  const run=fn=>async()=>{try{await fn()}catch(e){msg(e.message,true)}};
  const options=(arr,id= '')=>arr.map(x=>`<option value="${E(x.id)}" ${x.id===id?'selected':''}>${E(x.name||x.id)}${x.number?' · v'+x.number:x.revision?' · r'+x.revision:''}${x.kind?' · '+E(x.id.slice(0,6)):''}</option>`).join('');
  const isCfe=m=>m?.model_kind==='opt_cfe',isGrid=m=>m?.model_kind==='opt_grid_feedback',isGpu=m=>m?.model_kind==='opt_gpu',isIndependent=m=>isCfe(m)||isGrid(m)||isGpu(m);
  const modelAxis=model=>isGpu(model)?{location:'GPU独立子系统',year:Number(model.start.slice(0,4)),timezone:'Asia/Shanghai',start:model.start,step_minutes:model.dt_hours*60,length:model.n_steps}:isGrid(model)?{location:'电网反馈独立模式',year:Number(model.start.slice(0,4)),timezone:'UTC',start:model.start,step_minutes:60,length:model.buses[0].background_load_mw.length}:isCfe(model)?{location:'年度CFE独立模式',year:model.weather_year,timezone:'UTC',start:model.start,step_minutes:60,length:model.sites[0].load_mw.length}:ax();
  const compact=x=>Array.isArray(x)?(x.length>168?{array_length:x.length,preview:x.slice(0,3),full:'冻结任务JSON及ZIP保留全部原值'}:x.map(compact)):x&&typeof x==='object'?Object.fromEntries(Object.entries(x).map(([k,v])=>[k,compact(v)])):x;
  const chosen=()=>C?.scenario.find(x=>x.id===scenario);
  const ax=()=>({location:'示例地点',year:2024,timezone:'Asia/Shanghai',start:'2024-07-01T00:00:00+08:00',step_minutes:60,length:24});
  function remember(){localStorage.setItem('pfProject',project);localStorage.setItem('pfScenario',scenario)}
  function toolbar(){
    const pr=C.project;if(!pr.some(x=>x.id===project))project=pr[0]?.id||'';
    const scenes=C.scenario.filter(x=>x.project_id===project);if(!scenes.some(x=>x.id===scenario))scenario=scenes[0]?.id||'';
    const vs=C.version.filter(x=>x.scenario_id===scenario);if(!vs.some(x=>x.id===version))version=vs.at(-1)?.id||'';
    $('#pfContext').innerHTML=`<div class="pf-context-row"><b>当前项目模型</b><label>项目 <select id="pfProject">${options(pr,project)||'<option>先创建项目</option>'}</select></label><label>场景 <select id="pfScenario">${options(scenes,scenario)||'<option>尚无场景</option>'}</select></label><label>任务输入版本 <select id="pfVersion"><option value="">— 先发布版本 —</option>${options(vs,version)}</select></label><button id="pfHome" class="sm ghost">管理模型</button></div><div id="pfSessionState" class="hint">模型选择与对话会话独立：先签出编辑；运行任务只读所选已发布版本，不使用未保存会话。</div>`;
    $('#pfProject').onchange=()=>{if(dirty&&!confirm('编辑器草稿尚未保存，切换项目将放弃本次编辑。继续？')){toolbar();return}dirty=false;selectedTask='';selectedDetail=null;project=$('#pfProject').value;scenario='';version='';remember();refresh()};
    $('#pfScenario').onchange=()=>{if(dirty&&!confirm('编辑器草稿尚未保存，切换场景将放弃本次编辑。继续？')){toolbar();return}dirty=false;selectedTask='';selectedDetail=null;scenario=$('#pfScenario').value;version='';remember();refresh()};
    $('#pfVersion').onchange=()=>{version=$('#pfVersion').value;render()};
    $('#pfHome').onclick=()=>window.show('foundation');remember();sessionContext();
  }
  async function sessionContext(){
    if(!$('#pfSessionState')||!C)return;
    const sid=typeof SID!=='undefined'?SID:null;
    if(!sid)return;
    try{const d=await call('/sessions/'+sid+'/context');context=d.context;
      $('#pfSessionState').textContent=context?`编辑会话：${context.project_name||''} / ${context.scenario_name||''} · 草稿 r${context.draft_revision} · ${context.unsaved?'⚠ 会话修改尚未写回草稿':'已与草稿一致'}${context.results_stale?' · ⚠ 旧结果已过期':''}`:d.task_id?`当前会话展示历史任务 ${d.task_id} 的模型副本；任务快照/结果不随副本修改。`:'当前是旧式独立会话，未自动绑定项目；可在项目页显式导入。';
    }catch(e){$('#pfSessionState').textContent='上下文读取失败：'+e.message}
  }
  async function refresh(){C=await call('/catalog');if(selectedTask)selectedDetail=await call('/tasks/'+selectedTask);toolbar();render()}
  function showPanel(name){document.querySelectorAll('[data-pf-panel]').forEach(x=>x.hidden=x.dataset.pfPanel!==name)}
  function render(){
    if(!C)return;
    const current=document.querySelector('.view.active')?.id?.slice(2);
    if(!['foundation','templates','resources','tasks'].includes(current))return;
    showPanel(current);const d=chosen(),annual=isIndependent(d?.draft.model);
    for(const id of ['pfCheckout','pfSaveSession','pfExpand15','pfCleanup','pfSetCleanup','pfBind','pfBindReplace'])$('#'+id).disabled=annual;
    const limit=$('#pfTimeLimit');if(annual&&limit.dataset.mode!=='cfe'){limit.dataset.daily=limit.value;limit.value=600}else if(!annual&&limit.dataset.mode==='cfe')limit.value=limit.dataset.daily||120;limit.dataset.mode=annual?'cfe':'daily';
    const ac=$('#pfAC');if(annual){if(!ac.disabled)ac.dataset.previous=ac.checked?'1':'0';ac.checked=false}else if(ac.disabled)ac.checked=ac.dataset.previous!=='0';ac.disabled=annual;
    for(const op of $('#pfObjective').options)op.disabled=annual&&op.value!=='cost';if(annual)$('#pfObjective').value='cost';$('#pfObjective').options[0].text=annual?(isGpu(d?.draft.model)?'GPU MILP（策略/公平见配置）':isGrid(d?.draft.model)?'电网闭环实验（ISO成本/配置内信号）':'年度容量+运行费用（配置币种）'):'运行成本最优';
    if(current==='foundation'){
      $('#pfProjectInfo').value=JSON.stringify(C.project.find(x=>x.id===project)||{},null,2);
      $('#pfTemplate').innerHTML=options(C.template);
      if(!dirty||draftOwner!==d?.id){$('#pfDraft').value=JSON.stringify(d?.draft||{axis:ax(),model:{},bindings:[],device_bindings:[],pending:[]},null,2);dirty=false;draftOwner=d?.id}
      $('#pfCleanup').value=d?.draft.model.migration_cleanup||'off';
      $('#pfCfeConfig').hidden=!isCfe(d?.draft.model);if(isCfe(d?.draft.model)){const m=JSON.parse($('#pfDraft').value).model;$('#pfCfeMatching').value=m.matching;$('#pfCfeTarget').value=m.target;$('#pfCfeFlex').value=m.flexibility;$('#pfCfeSpatial').checked=m.spatial_shifting;$('#pfCfeTemporal').checked=m.temporal_shifting;$('#pfCfeExcess').value=m.max_excess_share;}
      $('#pfGridConfig').hidden=!isGrid(d?.draft.model);if(isGrid(d?.draft.model)){const m=JSON.parse($('#pfDraft').value).model;$('#pfGridSignal').value=m.selected_signal;$('#pfGridIterations').value=m.max_iterations;$('#pfGridFD').value=m.fd_step_mw;$('#pfGridMethod').value=m.signal_method;$('#pfGridUnstable').value=m.unstable_signal_policy;$('#pfGridRequire').checked=m.require_convergence;}
      $('#pfGpuConfig').hidden=!isGpu(d?.draft.model);if(isGpu(d?.draft.model)){const m=JSON.parse($('#pfDraft').value).model;$('#pfGpuPolicy').value=m.policy;$('#pfGpuGap').value=m.mip_relative_gap;$('#pfGpuValidation').checked=m.require_validation_feasible;}
      $('#pfRevision').textContent=d?`${d.name} · 草稿 r${d.revision} · ${C.version.filter(x=>x.scenario_id===d.id).length} 个已发布版本${dirty?' · ⚠ 编辑器未保存':''}`:'先创建项目，再从模板创建独立场景。';
      $('#pfVersions').innerHTML=C.version.filter(x=>x.scenario_id===scenario).map(v=>`<tr><td>v${v.number}</td><td>${E(v.created)}</td><td><code>${E(v.hash.slice(0,16))}</code></td><td>${E(v.warnings.join('；'))}</td></tr>`).join('');
      $('#pfBindRows').innerHTML=(d?.draft.bindings||[]).concat(d?.draft.device_bindings||[]).map(b=>`<li>${E(C.library.find(x=>x.id===b.resource_id)?.name||b.resource_id)} · r${E(C.library.find(x=>x.id===b.resource_id)?.revision||'?')} → ${E(b.target||'场景公共信号')}</li>`).join('')||'<li>无绑定；使用场景自带参数</li>';
      bindingResource=PFBinding.restoreSelection($('#pfResourcePick'),'<option value="">— 明确选择资源版本 —</option>'+options(C.library),$('#pfResourcePick').value||bindingResource);
      bindingTarget=PFBinding.restoreSelection($('#pfTargetPick'),'<option value="">场景公共信号（气象/电价/碳）</option>'+[...(d?.draft.model.data_centers||[]),...(d?.draft.model.storage||[])].map(x=>`<option>${E(x.name)}</option>`).join(''),$('#pfTargetPick').value||bindingTarget);
      bindingPreview();
    }
    if(current==='templates')$('#pfTemplateCards').innerHTML=C.template.map(t=>`<article class="card"><h3>${E(t.name)}</h3><p class="pf-template-source">${E(typeof t.source==='object'?JSON.stringify(t.source):t.source)}</p><p class="hint">${E(t.assumptions)}</p><code>${E(t.hash.slice(0,16))}</code><p><button data-pf-template="${E(t.id)}">复制为新场景</button></p></article>`).join('');
    if(current==='resources'){
      $('#pfLibraryList').innerHTML=C.library.map(r=>`<tr><td><button class="ghost sm" data-pf-resource="${E(r.id)}">${E(r.name)}</button></td><td>${E(r.kind)} · r${r.revision}</td><td>${E(r.unit||JSON.stringify(r.units))}</td><td>${E(r.source)}</td><td>${E(r.applicability)}</td></tr>`).join('');
      if(!$('#pfLibraryJson').value)resourceExample();
    }
    if(current==='tasks'){
      $('#pfTaskList').innerHTML=C.task.filter(t=>t.snapshot.project_id===project).slice().reverse().map(t=>`<tr><td><button class="ghost" data-pf-task="${E(t.id)}">${E(t.name)}</button></td><td>v${t.snapshot.version_number}</td><td>${E(t.status)}</td><td>${t.result?(['opt_cfe','opt_grid_feedback','opt_gpu'].includes(t.result.model_kind)?E(t.result.objective_value)+' '+E(t.result.currency):E(t.result.cost_cny)+' 元'):''}</td><td>${E(t.created)}</td></tr>`).join('');
      const t=selectedDetail;const taskScene=t&&C.scenario.find(s=>s.id===t.snapshot.scenario_id);$('#pfTaskSelection').textContent=t?`当前所选任务：${t.name} · ${taskScene?.name||t.snapshot.scenario_id} v${t.snapshot.version_number} · ${t.status}（运行使用该任务冻结输入，不跟随顶部版本切换）`:'尚未选择任务；请创建或点击任务列表。';$('#pfTaskDetail').textContent=t?JSON.stringify(isIndependent(t.snapshot.model)?compact(t):t,null,2):'选择任务查看完整冻结输入、来源版本、代码/求解器标识及结果。';
      $('#pfTaskExport').textContent=t&&isIndependent(t.snapshot.model)?'下载独立模式ZIP（冻结/结果/审计CSV）':'下载任务/输入/结果JSON';renderCfe(t);renderGrid(t);renderGpu(t);
      $('#pfTaskRun').disabled=!t||t.status!=='ready';$('#pfTaskOpen').disabled=!t||t.status!=='completed';$('#pfTaskRerun').disabled=!t;
    }
    document.querySelectorAll('[data-pf-template]').forEach(b=>b.onclick=run(()=>newScene(b.dataset.pfTemplate)));
    document.querySelectorAll('[data-pf-resource]').forEach(b=>b.onclick=()=>{$('#pfLibraryJson').value=JSON.stringify(C.library.find(r=>r.id===b.dataset.pfResource),null,2)});
    document.querySelectorAll('[data-pf-task]').forEach(b=>b.onclick=run(async()=>{selectedTask=b.dataset.pfTask;selectedDetail=await call('/tasks/'+selectedTask);render()}));
  }
  function renderGpu(t){
    const box=$('#pfGpuResults'),r=t?.full_result||t?.partial_result;if(!isGpu(t?.snapshot.model)||!r){box.hidden=true;return}box.hidden=false;
    const hasValidation=t.snapshot.model.jobs.some(j=>j.actions.some(a=>a.validation_normalized_rate!=null||a.validation_power_w_per_gpu!=null));
    box.innerHTML=`<h3>GPU离散控制 · ${E(t.status)} · ${E(r.status)}</h3><p class="pf-error">仅固定gang GPU子系统，不是整DC PUE/热安全或作者完整现场控制器。${t.status==='failed'?'部分结果未接受；不可当成功。':''} 验证口径：${!hasValidation?'无独立验证字段：仅规划一致，不算留出通过':r.validation_accepted?'输入验证字段的静态投影通过（是否独立留出须核对来源）':'验证投影未通过，不得承诺SLA'}。</p><p>完整任务量 ${E(r.completed_work_h)} / ${E(r.required_work_h)} baseline-gang-hours；验证投影未完成 ${E(r.validation_unfinished_work_h)} h。全时域能量 ${E(r.energy_kwh)} kWh（含空闲/恢复尾段）；参考 ${E(r.reference_energy_kwh)} kWh；验证功率投影（无字段即规划值） ${E(r.validation_energy_kwh)} kWh；费用 ${E(r.objective_value)} USD。</p><p>策略 ${E(r.objective_policy)}；吞吐Flex余量归一化最大损耗 ${E(r.fairness_rho)}；功率headroom主目标 ${E(r.solver_phases.find(p=>p.phase.startsWith('minimax_power'))?.incumbent??'非此策略')}；GPU加权性能 ${E(r.gpu_weighted_window_performance)}（不假称作者权重）；${E(r.horizon.steps)}×${E(r.horizon.dt_hours)}h。</p><table class="tbl"><thead><tr><th>任务/Flex</th><th>GPU数</th><th>必需/完成h</th><th>验证投影未完成h</th><th>deadline h</th></tr></thead><tbody>${r.jobs.map(j=>`<tr><td>${E(j.job)} / ${E(j.flex)}</td><td>${E(j.gpu_count)}</td><td>${E(j.required_work_h)} / ${E(j.completed_work_h)}</td><td>${E(j.validation_unfinished_work_h)}</td><td>${E(j.deadline_h)}</td></tr>`).join('')}</tbody></table><details><summary>逐窗口SLA/公平/求解器gap（逐GPU×时段在ZIP）</summary><pre class="pf-detail">${E(JSON.stringify({windows:r.sla_windows,solver:r.solver_phases,headroom:r.headroom_definition,boundaries:r.boundaries},null,2))}</pre></details>`;
  }
  function renderGrid(t){
    const box=$('#pfGridResults'),r=t?.full_result||t?.partial_result;if(!isGrid(t?.snapshot.model)||!r){box.hidden=true;return}box.hidden=false;
    box.innerHTML=`<h3>电网↔计算反馈 · ${E(t.status)} · ${E(r.status)}</h3><p class="pf-error">逐个LP最优 ≠ 闭环全局最优；${t.status==='failed'?'此结果仅失败过程证据，不是接受结果。':'本页为显式模式实验；非收敛仍保留，不能报最优。'} 来源范围：${E(r.source.kind||'见冻结JSON')}</p><p>基态：${E(r.baseline_totals.cost_usd)} USD；运行排放 ${E(r.baseline_totals.operational_tco2)} tCO₂；LCA附加 ${E(r.baseline_totals.lifecycle_extra_tco2)} tCO₂（独立分账）。${E(r.horizon.steps)}×1h；${E(r.horizon.start)}</p><table class="tbl"><thead><tr><th>信号</th><th>迭代状态</th><th>初始LMCE预测ΔtCO₂</th><th>真实再出清ΔtCO₂</th><th>真实ΔUSD</th><th>工作守恒残差MW</th></tr></thead><tbody>${r.policies.map(p=>`<tr><td>${E(p.signal)}</td><td>${E(p.status)}${p.converged?'（固定点，非全局最优）':'（未收敛/未证最优）'}</td><td>${E(p.predicted_operational_delta_from_initial_tco2??'无定义')}</td><td>${E(p.actual_operational_delta_tco2)}</td><td>${E(p.actual_cost_delta_usd)}</td><td>${E(p.max_work_residual_mw)}</td></tr>`).join('')}</tbody></table><p class="hint">正Δ排放=反而增排，不做过滤。LMCE含负值；FD正/负/半步、基矩阵秩/条件数、活跃集切换、扰动失败均在审计ZIP。average为区域出力加权因子，excess为负的闲置清洁容量MW，不能将不同单位的代理目标当实际吨碳。仅空间流体工作每小时守恒，无弃任务/整数任务/GPU/跨时储能；ISO目标=USD运行成本+显式USD/t运行碳价，LCA不并入LMCE。selected=${E(r.selected_signal)}；底层每LP最优，整个实验不声明全局最优。</p><details><summary>信号/迭代诊断（完整见CSV）</summary><pre class="pf-detail">${E(JSON.stringify({iterations:r.iterations,signals:r.signals.slice(0,12)},null,2))}</pre></details>`;
  }
  function renderCfe(t){
    const pct=v=>v==null?'—（无用电）':(100*v).toFixed(6)+'%';
    const box=$('#pfCfeResults'),r=t?.full_result;if(!isCfe(t?.snapshot.model)||!r){box.hidden=true;return}box.hidden=false;
    box.innerHTML=`<h3>年度CFE · 冻结任务 ${E(t.id)}</h3><p>${E(r.horizon.mode==='year'?'完整全年':'非全年解析benchmark')} · ${r.horizon.steps} × 1h · 气象年 ${r.horizon.weather_year} / 规划年 ${r.horizon.planning_year} · 源时间UTC · 全年共享容量</p><p><b>年度化投资+本输入时域运行费：${r.objective.toFixed(6)} ${E(r.currency)}</b> · ${E(r.matching.mode)} 目标 ${100*r.matching.target}%</p><p class="hint">CFE部分目标：论文式2/7为累计清洁电量年分数，不是每小时地板；annual_res_share不等于24/7。容量为全时域共享；储能来源分账，超额剔除；仅负荷虚拟迁移，非跨区电力传输。当前独立采购LP，不是电网内生LMCE、GPU或24h三级运行。</p><table class="tbl"><thead><tr><th>站点/竞价区</th><th>新增风光容量 MW</th><th>电池 MW/MWh</th><th>年RES份额</th><th>论文CFE分数</th><th>实际清洁供负荷</th><th>最大小时缺口 MWh</th></tr></thead><tbody>${r.investments.map(s=>`<tr><td>${E(s.site)} / ${E(s.region)}</td><td>${s.generators.map(g=>E(g.id)+': '+g.capacity_mw.toFixed(6)).join('<br>')}</td><td>${s.battery_power_mw.toFixed(6)} / ${s.battery_energy_mwh.toFixed(6)}</td><td>${pct(s.annual_generation_share)}</td><td>${pct(s.paper_cfe_score)}</td><td>${pct(s.physical_clean_fraction)}</td><td>${s.max_hourly_unmatched_mwh.toExponential(3)}</td></tr>`).join('')}</tbody></table><p>成本分账：${E(JSON.stringify(r.cost_terms))} · 最大守恒残差 ${r.audit.max_physical_residual.toExponential(3)} · 状态 ${E(r.solver.termination)} / 容差 ${r.solver.primal_tolerance}</p><label>逐时审计预览站点 <select id="pfCfeSite">${r.investments.map(s=>`<option>${E(s.site)}</option>`).join('')}</select></label><label>起始小时 <input id="pfCfeStep" type="number" min="0" max="${r.horizon.steps-1}" value="0"></label><div id="pfCfeHours"></div><details><summary>来源/约束/费用与储能来源口径</summary><pre>${E(JSON.stringify({source:r.source,matching:r.matching,solver:r.solver,execution_context:r.execution_context},null,2))}</pre></details><p class="hint">预览24小时，不截断实际求解/冻结/导出。完整8760/8784×各站逐时表、稀疏虚拟迁移、每日任务守恒、输入与投资账可用上方正式ZIP下载后独立重算；源UTC时间轴与北京时间显示的任务创建时间不同。</p>`;
    const hours=()=>{const site=$('#pfCfeSite').value,start=Math.max(0,+$('#pfCfeStep').value||0),rows=r.hourly.filter(x=>x.site===site&&x.step>=start).slice(0,24);$('#pfCfeHours').innerHTML='<table class="tbl"><thead><tr><th>小时/源UTC</th><th>请求→实际 MW</th><th>风光 MW</th><th>外网 MW</th><th>清/灰SOC MWh</th><th>清洁供用/缺口 MWh</th><th>超额剔除 MW</th></tr></thead><tbody>'+rows.map(x=>`<tr><td>${x.step} / ${E(x.timestamp)}</td><td>${x.requested_load_mw.toFixed(4)} → ${x.actual_load_mw.toFixed(4)}</td><td>${x.local_generation_mw.toFixed(4)}</td><td>${x.grid_import_mw.toFixed(4)}</td><td>${x.green_soc_mwh.toFixed(4)} / ${x.brown_soc_mwh.toFixed(4)}</td><td>${x.physical_clean_served_mwh.toFixed(4)} / ${x.unmatched_load_mwh.toFixed(6)}</td><td>${x.excess_excluded_mw.toFixed(6)}</td></tr>`).join('')+'</tbody></table>'};$('#pfCfeSite').onchange=hours;$('#pfCfeStep').onchange=hours;hours();
  }
  function bindingPreview(){
    const r=C.library.find(r=>r.id===$('#pfResourcePick').value),d=chosen(),box=$('#pfBindingPreview');
    if(!r||!d){box.textContent='先选场景与确定资源版本。选择本身不会改变已保存绑定。';return}
    const diffs=r.kind==='device'?[]:PFBinding.differences(d.draft.axis,r.axis);
    box.textContent=`待操作选择：${r.name} r${r.revision} (${r.id})\n当前场景时间轴：${JSON.stringify(d.draft.axis)}\n${r.axis?'所选数据时间轴：'+JSON.stringify(r.axis):'设备性能模型无时间轴'}\n${diffs.length?'冲突：'+diffs.map(x=>`${x.field} 期待（场景）=${JSON.stringify(x.expected)}，实际（数据）=${JSON.stringify(x.actual)}`).join('；'):'时间轴匹配'}\n下方列表仅表示已保存绑定；失败时不会改成待操作选择。`;
  }
  async function performBinding(mode){
    try{
      const d=chosen();if(!d)throw Error('先建场景');if(dirty)throw Error('先保存草稿');
      const resourceId=$('#pfResourcePick').value,target=$('#pfTargetPick').value,alignAxis=$('#pfAlignAxis').checked;
      const plan=PFBinding.plan({draft:d.draft,resources:C.library,resourceId,target,mode,alignAxis});
      if(mode==='replace'||plan.axisChanged){
        const old=plan.previous.map(b=>C.library.find(r=>r.id===b.resource_id)?.name+' ('+b.resource_id+')').join('、')||'无';
        if(!confirm(`${mode==='replace'?'明确替换':'新增'}：${old} → ${plan.resource.name} r${plan.resource.revision} (${resourceId})${plan.axisChanged?'\n同时修改草稿时间轴为 '+JSON.stringify(plan.resource.axis)+'；其他绑定若冲突会整体拒绝保存。':''}\n历史发布版本及旧任务不变。确认？`))return;
      }
      const result=await call('/scenarios/'+scenario+'/bind',{expected_revision:d.revision,resource_id:resourceId,target,mode,align_axis:alignAxis});
      await refresh();$('#pfAlignAxis').checked=false;
      const text=`${mode==='replace'?'替换':'新增'}绑定成功：${result.binding.name} r${result.binding.revision} (${result.binding.id})${result.axis_changed?'；草稿时间轴已按明确选择更新':''}。尚未改变历史版本；需发布新版本创建新任务。`;
      $('#pfBindingMsg').textContent=text;$('#pfBindingMsg').className='pf-success';msg(text);
    }catch(e){$('#pfBindingMsg').textContent=e.message;$('#pfBindingMsg').className='pf-error';throw e}
  }
  async function newScene(tid){
    if(!project)throw Error('请先在项目页创建项目');
    const name=$('#pfSceneName').value.trim()||'场景 '+new Date().toLocaleTimeString();
    const model=C.template.find(t=>t.id===tid)?.model;const a=isIndependent(model)?modelAxis(model):JSON.parse($('#pfAxis').value);const d=await call('/scenarios',{project_id:project,name,axis:a,template_id:tid});scenario=d.id;version='';await refresh();window.show('foundation');msg(isIndependent(model)?'独立模式模板已复制，按模式显式时间轴编辑JSON/参数后保存发布；不签出日拓扑。':'已独立复制模板，可修改拓扑/参数/数据；尚未发布。');
  }
  function resourceExample(){const kind=$('#pfResourceKind').value;
    $('#pfLibraryJson').value=JSON.stringify(kind==='device'?{name:'设备模型示例',kind:'device',device_type:'data_center',parameters:{pue:1.25},units:{pue:'1'},source:'【假设】示例；请替换厂商/论文/标定来源',applicability:'恒定PUE、小时级模型'}:{name:kind+'数据示例',kind,source:'【假设】合成示例；请替换真实数据及来源',applicability:'24小时日调度',unit:{weather:'degC',price:'CNY/kWh',carbon:'tCO2/MWh',load:'MW'}[kind],axis:chosen()?.draft.axis||ax(),values:Array((chosen()?.draft.axis||ax()).length).fill({weather:25,price:.5,carbon:.53,load:10}[kind])},null,2);
  }
  async function activateSession(id){await openSession(id);await sessionContext()}
  function boot(){
    $('#pfAxis').value=JSON.stringify(ax(),null,2);
    $('#pfCreateProject').onclick=run(async()=>{const name=$('#pfProjectName').value.trim();if(!name)throw Error('请输入项目名称');const d=await call('/projects',{name,documents:[],pending:[]});project=d.id;await refresh();msg('项目已创建。')});
    $('#pfSaveProject').onclick=run(async()=>{const d=JSON.parse($('#pfProjectInfo').value);await call('/projects/'+project,{name:d.name,documents:d.documents||[],pending:d.pending||[]},'PATCH');await refresh();msg('项目资料引用已保存；设计资料不会自动可靠转成拓扑。')});
    fetch('/api/opt-gpu/presets').then(r=>r.json()).then(a=>$('#pfGpuPreset').innerHTML=options(a)).catch(e=>msg(e.message,true));
    $('#pfGpuCreate').onclick=run(async()=>{if(!project)throw Error('先创建项目');const r=await fetch('/api/opt-gpu/presets/'+$('#pfGpuPreset').value);const p=await r.json();if(!r.ok)throw Error(p.detail);const d=await call('/scenarios',{project_id:project,name:$('#pfSceneName').value||p.model.name,...p});scenario=d.id;version='';dirty=false;await refresh();msg('GPU独立草稿已创建；不覆盖PUE/热模型。先校验保存发布，再AC关闭创建冻结任务。')});
    $('#pfGpuApply').onclick=run(async()=>{const d=JSON.parse($('#pfDraft').value);if(!isGpu(d.model))throw Error('先创建GPU场景');Object.assign(d.model,{policy:$('#pfGpuPolicy').value,mip_relative_gap:Number($('#pfGpuGap').value),require_validation_feasible:$('#pfGpuValidation').checked});$('#pfDraft').value=JSON.stringify(d,null,2);dirty=true;msg('仅写入编辑器，保存/发布才生效；旧快照不变。')});
    $('#pfGpu15').onclick=run(async()=>{const d=JSON.parse($('#pfDraft').value),m=d.model;if(!isGpu(m)||m.dt_hours!==1)throw Error('仅将1h GPU阶梯输入明确细化15min');if(m.n_steps*4>96)throw Error('超过GPU96步上限，不截断');for(const k of ['price_usd_kwh','power_limit_kw'])m[k]=m[k].flatMap(v=>[v,v,v,v]);for(const j of m.jobs)j.baseline_rate=j.baseline_rate.flatMap(v=>[v,v,v,v]);m.n_steps*=4;m.dt_hours=.25;d.axis={...d.axis,step_minutes:15,length:m.n_steps};$('#pfDraft').value=JSON.stringify(d,null,2);dirty=true;msg('已按相同阶梯物理输入细化；离散控制粒度改变，最优策略可不同，不强称数值相等。须保存发布。')});
    fetch('/api/opt-grid-feedback/presets').then(r=>r.json()).then(a=>$('#pfGridPreset').innerHTML=options(a)).catch(e=>msg(e.message,true));
    $('#pfGridCreate').onclick=run(async()=>{if(!project)throw Error('先创建项目');const r=await fetch('/api/opt-grid-feedback/presets/'+$('#pfGridPreset').value);const p=await r.json();if(!r.ok)throw Error(p.detail);const d=await call('/scenarios',{project_id:project,name:$('#pfSceneName').value||p.model.name,...p});scenario=d.id;version='';dirty=false;await refresh();msg('电网反馈独立草稿已创建；来源/单位/局限在JSON。保存→校验→发布→关闭AC创建冻结任务；不代表整篇论文复现。')});
    $('#pfGridApply').onclick=run(async()=>{const d=JSON.parse($('#pfDraft').value);if(!isGrid(d.model))throw Error('先创建电网反馈场景');Object.assign(d.model,{selected_signal:$('#pfGridSignal').value,max_iterations:Number($('#pfGridIterations').value),fd_step_mw:Number($('#pfGridFD').value),signal_method:$('#pfGridMethod').value,unstable_signal_policy:$('#pfGridUnstable').value,require_convergence:$('#pfGridRequire').checked});$('#pfDraft').value=JSON.stringify(d,null,2);dirty=true;msg('已写入编辑器；尚未保存/发布，不影响旧版本和任务。')});
    fetch('/api/opt-cfe/presets').then(r=>r.json()).then(a=>$('#pfCfePreset').innerHTML=options(a)).catch(e=>msg(e.message,true));
    $('#pfCfeCreate').onclick=run(async()=>{if(!project)throw Error('先创建项目');const r=await fetch('/api/opt-cfe/presets/'+$('#pfCfePreset').value);const p=await r.json();if(!r.ok)throw Error(p.detail);const d=await call('/scenarios',{project_id:project,name:$('#pfSceneName').value||p.model.name,...p});scenario=d.id;version='';dirty=false;await refresh();msg('年度CFE草稿已创建，全年自包含输入；先校验、发布，再到任务页关闭AC创建冻结任务。')});
    $('#pfCfeApply').onclick=run(async()=>{const draft=JSON.parse($('#pfDraft').value);if(!isCfe(draft.model))throw Error('先选择年度CFE草稿');Object.assign(draft.model,{matching:$('#pfCfeMatching').value,target:+$('#pfCfeTarget').value,flexibility:+$('#pfCfeFlex').value,spatial_shifting:$('#pfCfeSpatial').checked,temporal_shifting:$('#pfCfeTemporal').checked,max_excess_share:+$('#pfCfeExcess').value});const r=await fetch('/api/opt-cfe/validate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(draft.model)});const out=await r.json();if(!r.ok)throw Error(out.detail);$('#pfDraft').value=JSON.stringify(draft,null,2);dirty=true;msg('仅写入编辑器并通过年度输入合同；须保存→发布新版本→新任务。历史任务未变。')});
    $('#pfCreateScene').onclick=run(()=>newScene($('#pfTemplate').value));
    $('#pfCopyScene').onclick=run(async()=>{if(!version)throw Error('先选已发布版本');const d=await call('/scenarios',{project_id:project,name:$('#pfSceneName').value||'复制场景',version_id:version,axis:chosen().draft.axis});scenario=d.id;version='';await refresh();msg('已从版本独立复制。')});
    $('#pfDraft').oninput=()=>{dirty=true;$('#pfRevision').textContent='⚠ 编辑器内容未保存；任务仍使用已发布版本'};
    $('#pfExpand15').onclick=run(async()=>{const raw=JSON.parse($('#pfDraft').value);if(raw.bindings?.length||raw.device_bindings?.length)throw Error('存在绑定；请先签出并写回以实体化，再显式展开');const r=await fetch('/api/time-axis/resample-hourly',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(raw.model)});const out=await r.json();if(!r.ok)throw Error(out.detail);raw.model=out.model;raw.axis={...raw.axis,...out.axis_patch};$('#pfDraft').value=JSON.stringify(raw,null,2);dirty=true;msg(out.warning+'；当前仅修改编辑器，需保存→发布新版本。')});
    $('#pfSetCleanup').onclick=run(async()=>{const raw=JSON.parse($('#pfDraft').value);raw.model.migration_cleanup=$('#pfCleanup').value;$('#pfDraft').value=JSON.stringify(raw,null,2);dirty=true;msg('次目标写入编辑器，尚未保存或改变历史；运行后查看锁定公差/第一目标偏差。')});
    $('#pfSaveDraft').onclick=run(async()=>{if(!scenario)throw Error('先建场景');await call('/scenarios/'+scenario+'/draft',{...JSON.parse($('#pfDraft').value),expected_revision:chosen().revision},'PATCH');dirty=false;await refresh();msg('草稿已保存并通过静态校验；未改变任何历史版本/结果。')});
    $('#pfValidateDraft').onclick=run(async()=>{if(dirty)throw Error('先保存编辑器草稿');const d=await call('/scenarios/'+scenario+'/validate',{});msg('校验通过；告警：'+(d.warnings.join('；')||'无')+'。不替代求解与工程审查。')});
    $('#pfPublish').onclick=run(async()=>{if(dirty)throw Error('先保存草稿');const v=await call('/scenarios/'+scenario+'/publish',{expected_revision:chosen().revision});version=v.id;await refresh();msg('已发布不可变 v'+v.number+'，可到仿真任务创建运行。')});
    $('#pfCheckout').onclick=run(async()=>{if(dirty)throw Error('先保存草稿');const d=await call('/scenarios/'+scenario+'/checkout',{});await activateSession(d.session_id);window.show('model');msg('已创建独立编辑会话；修改后在项目页写回草稿。')});
    $('#pfSaveSession').onclick=run(async()=>{if(!SID)throw Error('尚无当前会话');await sessionContext();if(!context)throw Error('当前会话未签出项目；请先导入');const r=await call('/sessions/'+SID+'/save-draft',{expected_revision:context.draft_revision});project=r.scenario.project_id;scenario=r.scenario.id;await refresh();msg(r.note)});
    $('#pfImportSession').onclick=run(async()=>{if(!SID||!project)throw Error('需要当前会话和项目');const d=await call('/sessions/'+SID+'/import',{project_id:project,name:$('#pfSceneName').value||'旧会话导入',axis:JSON.parse($('#pfAxis').value)});scenario=d.id;await refresh();msg('已复制旧会话为项目草稿，原会话和结果未覆盖。')});
    $('#pfJsonImport').onchange=run(async()=>{const f=$('#pfJsonImport').files[0];if(!f)return;const raw=JSON.parse(await f.text()),model=raw.model||raw;const axis=raw.axis||(isIndependent(model)?modelAxis(model):JSON.parse($('#pfAxis').value));const d=await call('/scenarios',{project_id:project,name:$('#pfSceneName').value||f.name,axis,model});scenario=d.id;await refresh();msg('结构化JSON已校验并导入为草稿。')});
    $('#pfResourcePick').onchange=()=>{bindingResource=$('#pfResourcePick').value;bindingPreview()};
    $('#pfTargetPick').onchange=()=>{bindingTarget=$('#pfTargetPick').value;bindingPreview()};
    $('#pfBind').onclick=run(()=>performBinding('add'));
    $('#pfBindReplace').onclick=run(()=>performBinding('replace'));
    $('#pfSaveTemplate').onclick=run(async()=>{const v=version&&C.version.find(x=>x.id===version);if(!v)throw Error('请先发布并选择版本');await call('/templates',{name:$('#pfTemplateName').value||v.name+'模板',version_id:version,source:'项目场景版本 '+v.id,assumptions:'从用户确认版本复制；工程参数适用条件请复核'});await refresh();msg('模板已独立保存；旧模板不被覆盖。')});
    $('#pfResourceKind').onchange=resourceExample;$('#pfResourceExample').onclick=resourceExample;
    $('#pfLibrarySave').onclick=run(async()=>{let d=JSON.parse($('#pfLibraryJson').value);if(d.id){d.previous_id=d.id;delete d.id;delete d.hash;delete d.created;delete d.revision}await call('/library',d);await refresh();msg('新增不可变资源版本；既有场景/任务不变，需显式重新绑定。')});
    $('#pfTaskCreate').onclick=run(async()=>{if(!version)throw Error('先发布并选择场景版本');const t=await call('/tasks',{version_id:version,name:$('#pfTaskName').value||'版本化仿真',objective:$('#pfObjective').value,carbon_weight:+$('#pfCarbonWeight').value,solver:{time_limit_s:+$('#pfTimeLimit').value,ac_check:$('#pfAC').checked}});selectedTask=t.id;await refresh();msg('任务输入已冻结，将按所选模型模式运行，不读取未保存草稿。')});
    $('#pfTaskRun').onclick=run(async()=>{msg('正在求解固定版本输入，请勿重复点击…');$('#pfTaskRun').disabled=true;const t=await call('/tasks/'+selectedTask+'/run',{});await refresh();msg(t.status==='completed'?(isGpu(t.snapshot.model)?'GPU MILP已返回：核对求解gap、同工作deadline、逐窗口SLA及留出验证；不是整DC/原作者现场控制复现。':isGrid(t.snapshot.model)?'电网反馈实验已返回：请核对固定点/不稳定/迭代上限与实际排放，非全局最优；正式ZIP包含冻结输入与诊断。':isCfe(t.snapshot.model)?'年度采购LP最优求解完成，可查看此任务年度结果/正式ZIP；不进入24h三级运行。':'求解完成，可查看当时模型、进入结果与三级运行。'):t.error,t.status!=='completed')});
    $('#pfTaskOpen').onclick=run(async()=>{const d=await call('/tasks/'+selectedTask+'/open',{});if(['opt_cfe','opt_grid_feedback','opt_gpu'].includes(d.model_kind)){selectedDetail=await call('/tasks/'+selectedTask);render();$(d.model_kind==='opt_gpu'?'#pfGpuResults':d.model_kind==='opt_grid_feedback'?'#pfGridResults':'#pfCfeResults').scrollIntoView({behavior:'smooth'});msg(d.note)}else{await activateSession(d.session_id);window.show('chat');window.WF?.go('results',true);msg(d.note)}});
    $('#pfTaskRerun').onclick=run(async()=>{const t=await call('/tasks/'+selectedTask+'/rerun',{});selectedTask=t.id;await refresh();msg('已按原冻结输入创建新任务，不重新解析资源库。代码变化可从运行标识比较。')});
    $('#pfTaskExport').onclick=()=>{const t=selectedDetail;if(!t)return;const a=document.createElement('a');if(isIndependent(t.snapshot.model)){a.href=P+'/tasks/'+t.id+'/export.zip';a.download=t.snapshot.model.model_kind+'-'+t.id+'.zip';a.click();return;}a.href=URL.createObjectURL(new Blob([JSON.stringify(t,null,2)],{type:'application/json'}));a.download='task-'+t.id+'.json';a.click();URL.revokeObjectURL(a.href)};
    window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='草稿未保存'}});
    refresh().catch(e=>msg(e.message,true));
  }
  window.PF={refresh,render,sessionContext,changed(){clearTimeout(this.timer);this.timer=setTimeout(()=>sessionContext(),150)}};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();

// Read-only shared-Pyomo runtime status, no task submission.
setInterval(async()=>{const b=document.querySelector("#pfSolverGate");if(!b||document.hidden)return;try{const r=await fetch("/api/solver-execution/status");if(!r.ok)return;const x=await r.json();b.textContent=x.active?`Pyomo执行域：${x.active.request_label} · ${x.active.scope}，${x.active.elapsed_seconds.toFixed(1)} 秒；等待 ${x.queued_count} 项。排队不计求解器软限时。`:`Pyomo执行域：空闲；等待 ${x.queued_count} 项，无隐式fallback。`}catch(e){b.textContent="执行域状态暂不可读，不据此宣称任务完成"}},3000);
