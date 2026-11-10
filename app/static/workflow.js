/* 透明化仿真工作台：步骤条 ①~⑥ + 每步面板（参数表/模型核对/求解配置与数学模型/运行日志/结果解释）。
   依赖 app.js 的 $, $$, esc, api, SID, chartEl, show, loadSessions。 */
(function () {
  const STEPS = [["goal", "① 场景与目标", "选案例或描述需求，明确优化目标"], ["params", "② 输入参数", "逐项核对参数值与来源，确认后才运行"],
    ["model", "③ 模型构建", "核对拓扑：母线、线路、电源、储能、数据中心"], ["solver", "④ 求解配置", "求解器选项与本次使用的数学模型"],
    ["run", "⑤ 运行与校核", "每一步做了什么、用时、求解状态、交流校核"], ["results", "⑥ 结果与分析", "KPI 定义、基线对比、收益归因、局限"]];
  const SRC_CLS = {"用户指定": "s-user", "智能体推断": "s-agent", "默认值": "s-default", "案例假设": "s-case", "公开资料": "s-public"};
  const ACT_ICON = a => /智能体/.test(a) ? "🤖" : "👤";
  let W = {view: null, pinned: false, wf: null, ps: null, onlyInf: false};
  const fmt = (v, d = 2) => (typeof v === "number") ? (Math.abs(v) >= 1000 ? v.toLocaleString(undefined, {maximumFractionDigits: 0}) : (+v.toFixed(d)).toString()) : esc(v ?? "—");
  const tex = s => { try { return window.katex ? katex.renderToString(s, {throwOnError: false, displayMode: false}) : `<code>${esc(s)}</code>`; } catch { return `<code>${esc(s)}</code>`; } };
  const body = () => $("#stepBody");
  const toast = (t, cls = "ok") => { const d = $("#wfToast"); d.className = "wf-toast " + cls; d.innerHTML = t; d.style.display = "block"; clearTimeout(d._t); d._t = setTimeout(() => d.style.display = "none", cls === "err" ? 8000 : 3000); };
  const loading = t => body().innerHTML = `<div class="wf-loading"><span class="spinner"></span>${esc(t)}</div>`;
  const errBox = (e, hint) => `<div class="wf-err">❌ ${esc(e.message || e)}${hint ? `<div class="muted">👉 ${hint}</div>` : ""}</div>`;
  const nav = (prev, next, extra = "") => `<div class="wf-nav">${prev ? `<button class="ghost" data-go="${prev}">← 上一步</button>` : "<span></span>"}${extra}${next ? `<button data-go="${next}">下一步：${STEPS.find(s => s[0] === next)[1]} →</button>` : ""}</div>`;
  const empty = (t, act = "") => `<div class="wf-empty"><div class="big">💬</div><p>${t}</p>${act}<p class="muted" style="margin-top:10px;font-size:12px">提示：左侧点「一键开始」示例，或在此选择案例预设。</p></div>`;
  function bindGo() { $$("#stepBody [data-go]").forEach(b => b.onclick = () => go(b.dataset.go, true)); }

  function stepper() {
    const st = W.wf?.steps || STEPS.map(([id, label]) => ({id, label, done: false, current: id === "goal"}));
    const rsBtn = `<button class="st rs ${W.view === "research" ? "view" : ""}" data-step="research" title="研究模式：问题卡/澄清/计划/时间线/诊断/结论/沉淀"><span class="n">🔬</span><span class="l">研究</span>${window.RS?.badge?.() || ""}</button><span class="arrow">|</span>`;
    $("#stepper").innerHTML = rsBtn + st.map((s, i) => { const d = STEPS[i];
      return `<button class="st ${s.done ? "done" : ""} ${s.current ? "cur" : ""} ${W.view === s.id ? "view" : ""}" data-step="${s.id}" title="${esc(d[2])}">
        <span class="n">${s.done ? "✓" : i + 1}</span><span class="l">${esc(d[1].slice(2))}</span>${s.current ? '<span class="now">当前</span>' : ""}</button>${i < 5 ? '<span class="arrow">›</span>' : ""}`; }).join("")
      + `<span class="wf-sc">${W.wf?.scenario ? `场景：<b>${esc(W.wf.scenario)}</b>${W.wf.confirmed ? ' <span class="pill ok">参数已确认</span>' : ' <span class="pill warn">参数待确认</span>'}` : '<span class="muted">尚未建立场景</span>'}</span>`;
    $$("#stepper .st").forEach(b => b.onclick = () => go(b.dataset.step, true));
  }
  async function refresh(follow = true) {
    if (!SID) { W.wf = null; if (!W.pinned) W.view = "goal"; stepper(); window.setStatus?.("idle", "就绪 — 用中文描述问题或点左侧示例开始"); return render(); }
    try { W.wf = await api(`/api/sessions/${SID}/workflow`); } catch (e) { W.wf = null; }
    if (follow && !W.pinned && W.wf) W.view = W.wf.current;
    stepper(); render();
  }
  function go(v, pin) { W.view = v; if (pin) W.pinned = true; stepper(); render(); }
  function follow(step) { W.pinned = false; if (step) W.view = step; }
  async function render() {
    const v = W.view || "goal";
    try { await ({research: () => window.RS.render(body(), {go, toast}), goal: pGoal, params: pParams, model: pModel, solver: pSolver, run: pRun, results: pResults})[v](); }
    catch (e) { body().innerHTML = errBox(e, "刷新页面或回到上一步重试；若问题持续，请查看「⑤ 运行与校核」日志。"); }
    bindGo();
  }
  const needSc = () => !W.wf?.has_scenario ? (body().innerHTML = empty("还没有场景。请先在「① 场景与目标」选择案例，或在左侧对话中描述你的需求。", `<button data-go="goal">去 ① 场景与目标</button>`), bindGo(), true) : false;

  // ① 场景与目标
  async function pGoal() {
    const pr = (await api("/api/scenario/presets")).presets;
    const groups = {}; pr.forEach(n => (groups[n.split("_")[0]] ??= []).push(n));
    const CN = {zhongwei: "宁夏中卫（大唐云基地绿电直供）", helinger: "内蒙古和林格尔", qingyang: "甘肃庆阳", qinghai: "青海海南州（龙羊峡）", zhangbei: "河北张北"};
    body().innerHTML = `<h3>① 场景与目标</h3>
      <div class="wf-guide"><b>工作流程</b>：① 选场景/写需求 → ② 核对参数（看清每个数从哪来）→ ③ 核对拓扑 → ④ 看求解配置与数学模型 → ⑤ 运行并看日志与校核 → ⑥ 看结果与收益来源。
      <br>智能体在左侧对话中的每个动作都会映射到这些步骤并高亮；<b>运行前一定会停下来请你确认参数</b>（可在对话框下方开启“自动运行”跳过）。</div>
      ${W.wf?.has_scenario ? `<div class="wf-cur">当前会话场景：<b>${esc(W.wf.scenario)}</b>　<button class="sm" data-go="params">查看参数 →</button></div>` : ""}
      <div class="wf-cards">
        <div class="card"><h4>🚀 方式一：手动选择案例（推荐新手）</h4>
          <label class="f">案例预设 <select id="gPreset">${Object.entries(groups).map(([g, ns]) => `<optgroup label="${esc(CN[g] || g)}">${ns.map(n => `<option ${n === "zhongwei_summer_highwind" ? "selected" : ""}>${n}</option>`).join("")}</optgroup>`).join("")}<optgroup label="合成示例"><option value="__default">IEEE14 + 3 数据中心 + 50MWh 储能（合成）</option></optgroup></select></label>
          <label class="f">优化目标 <select id="gObj"><option value="cost">最小化日运行成本（纯成本，碳权重 w=0）</option><option value="carbon">成本 + 碳（双目标）</option></select></label>
          <label class="f hidden" id="gWl">碳权重 w <span class="tip" data-tip="目标 = 成本 + w × 碳价 × 排放；w=1 表示按碳价计入碳成本">ⓘ</span><input id="gW" type="number" value="1" step="0.5"></label>
          <button id="gStart">载入场景 → 核对参数</button><div class="muted" style="margin-top:6px">示例：选「zhongwei_summer_highwind」= 中卫夏季大风典型日，含 PPA/外送/储能/上海迁移节点。</div></div>
        <div class="card"><h4>💬 方式二：用中文告诉智能体（推荐）</h4>
          <p class="muted">对话是主路径。点下方会填入并聚焦输入框；左侧欢迎页的卡片可<strong>一键直接发送</strong>。</p>
          <div class="muted" style="margin:4px 0 2px">研究类（勾选 🔬 研究模式）：</div>
          ${["中卫冬季想用余热供暖，看值不值", "中卫夏季热浪下保障热安全同时参与需求响应的最优方案", "中卫项目寻优：我想看经济性最优和碳排放最优的方案，以及中间的折中"].map(x => `<button class="ex ghost sm" data-rs="1">${esc(x)}</button>`).join("")}
          <div class="muted" style="margin:8px 0 2px">工作台 / 配置类：</div>
          ${["中卫夏季大风日，优化调度并分析", "对比风冷和液冷散热方式", "三个数据中心，加50MWh储能，峰谷电价，帮我优化调度并分析"].map(x => `<button class="ex ghost sm">${esc(x)}</button>`).join("")}
          <p class="muted" style="margin-top:8px">智能体建模后会<strong>暂停在 ②</strong>；值带 <span class="src s-agent">智能体推断</span> / <span class="src s-default">默认值</span> / 单位与来源，确认后再求解。</p>
          <p class="muted">进阶能力也可直接说：Pareto、VCC / 虚拟容量、硬件功率模型、8760 全年、配置构建器对比扫描。</p></div></div>
      ${nav(null, W.wf?.has_scenario ? "params" : null)}`;
    $("#gObj").onchange = () => $("#gWl").classList.toggle("hidden", $("#gObj").value !== "carbon");
    $$("#stepBody .ex").forEach(b => b.onclick = () => {
      $("#input").value = b.textContent; if (b.dataset.rs && $("#researchMode")) $("#researchMode").checked = true;
      $("#input").focus(); window.setStatus?.("idle", "已填入示例 — Enter 发送，或再改一改");
    });
    $("#gStart").onclick = async () => { const b = $("#gStart"); b.disabled = true; b.textContent = "载入中…";
      try { const p = $("#gPreset").value; const r = await api(`/api/sessions/${SID || "new"}/model/init`, {method: "POST", body: JSON.stringify(p === "__default" ? {default: true} : {preset: p})});
        SID = r.session_id; localStorage.setItem("sid", SID); window.loadSessions?.();
        if ($("#gObj").value === "carbon") await api(`/api/sessions/${SID}/params`, {method: "PATCH", body: JSON.stringify({path: "carbon_weight", value: +$("#gW").value})});
        toast("✅ 已载入场景，请逐项核对参数"); follow("params"); W.pinned = true; await refresh(false);
      } catch (e) { b.disabled = false; b.textContent = "载入场景 → 核对参数"; toast("载入失败：" + esc(e.message), "err"); } };
  }

  // ② 输入参数
  async function pParams() {
    if (needSc()) return; loading("读取参数表…");
    const p = W.ps = await api(`/api/sessions/${SID}/params`);
    const cnt = Object.entries(p.source_counts).filter(([, n]) => n).map(([k, n]) => `<span class="src ${SRC_CLS[k]}">${k} ${n}</span>`).join(" ");
    const pend = W.wf?.pending?.length ? `<div class="wf-pause">⏸ 智能体已暂停，等待你确认参数。确认后将继续执行：${W.wf.pending.map(n => `<code>${esc(n)}</code>`).join(" → ")}</div>` : "";
    const row = it => { const inp = !it.editable ? `<span class="ro">${esc(typeof it.value === "object" ? JSON.stringify(it.value) : it.value)}</span>`
        : it.type === "enum" || it.type === "bool" ? `<select data-path="${it.path}" data-t="${it.type}">${it.range.map(o => `<option ${String(o) === String(it.value) ? "selected" : ""}>${o}</option>`).join("")}</select>`
        : `<input data-path="${it.path}" data-t="${it.type}" type="number" step="any" value="${it.value ?? ""}" placeholder="${it.type === "optnum" ? "空=不启用" : ""}">`;
      const rng = Array.isArray(it.range) && it.type !== "enum" && it.type !== "bool" && it.range.length === 2 ? `${it.range[0]} ~ ${it.range[1]}` : (it.type === "list24" ? "24 点曲线" : "");
      const hl = it.source === "智能体推断" || it.source === "默认值";
      return `<tr class="${hl ? "hl" : ""} ${it.missing ? "miss" : ""} ${it.warning ? "warnr" : ""}" ${W.onlyInf && !hl ? 'style="display:none"' : ""}><td><b>${esc(it.name)}</b>${it.required ? '<span class="req" title="必填">*</span>' : ""}<div class="muted path">${esc(it.path)}</div></td>
        <td class="mean">${esc(it.meaning)}</td><td class="val">${inp}${it.warning ? `<div class="retry">⚠ ${esc(it.warning)}</div>` : ""}${it.missing ? '<div class="retry">缺少必填值</div>' : ""}</td><td>${esc(it.unit)}</td><td class="muted">${rng}</td>
        <td><span class="src ${SRC_CLS[it.source]}" title="${esc(it.source_note)}">${it.source}</span>${it.link ? ` <a href="${esc(it.link)}" target="_blank" title="${esc(it.source_note)}">🔗</a>` : ""}${it.msg_ref ? ` <a class="msgref" data-midx="${it.msg_ref.idx}" title="${esc(it.source_note)}：“${esc(it.msg_ref.quote || "")}”">💬#${it.msg_ref.idx}</a>` : ""}</td></tr>`; };
    body().innerHTML = `<h3>② 输入参数 <span class="muted sm2">引擎实际使用的全部输入，按类别分组</span></h3>${pend}
      <div class="wf-guide">每个参数都有<strong>单位</strong>与<strong>来源</strong>。优先核对橙色高亮的「智能体推断 / 默认值」；改完会变成「用户指定」。悬停来源标签可看说明。</div>
      <div class="wf-bar">来源统计：${cnt}　<label class="chk2"><input type="checkbox" id="onlyInf" ${W.onlyInf ? "checked" : ""}> 只看智能体推断/默认值</label>
        <span class="tip" data-tip="用户指定=你输入或修改的；智能体推断=从对话文字解析的；默认值=引擎内置合成值；案例假设=案例作者的假设；公开资料=有公开来源链接（🔗）">ⓘ 来源说明</span></div>
      ${p.errors.length ? `<div class="wf-err">❌ 参数校验未通过：${p.errors.map(esc).join("；")}<div class="muted">👉 修改标红的参数后再确认。</div></div>` : ""}
      ${p.missing.length ? `<div class="wf-err">缺少必填参数：${p.missing.map(esc).join("、")}</div>` : ""}
      <div class="muted">${esc(p.note)}</div>
      ${p.groups.map(g => `<details class="pgrp" open><summary>${esc(g.name)} <span class="muted">（${g.items.length} 项${g.items.filter(i => i.source === "智能体推断").length ? `，推断 ${g.items.filter(i => i.source === "智能体推断").length}` : ""}）</span></summary>
        ${g.items.length ? `<table class="ptbl"><tr><th style="width:20%">参数</th><th>含义</th><th style="width:16%">值</th><th>单位</th><th>合理范围</th><th style="width:11%">来源</th></tr>${g.items.map(row).join("")}</table>` : '<p class="muted">（无）</p>'}</details>`).join("")}
      <div class="wf-confirm"><div>${p.confirmed ? '✅ 参数已确认（修改任一参数会撤销确认）' : '请核对上表（尤其<span class="src s-agent">智能体推断</span>与<span class="src s-default">默认值</span>），确认后才能运行。'}</div>
        <div><button id="pConfirm" ${p.errors.length ? "disabled" : ""}>✅ 确认参数</button>${W.wf?.pending?.length ? ' <button id="pConfirmRun" class="ok">✅ 确认并继续运行</button>' : ""}</div></div>
      ${nav("goal", "model")}`;
    $("#onlyInf").onchange = e => { W.onlyInf = e.target.checked; pParams().then(bindGo); };
    $$("#stepBody [data-path]").forEach(el => el.onchange = async () => {
      let v = el.value; if (el.dataset.t === "num") v = +v; else if (el.dataset.t === "optnum") v = v === "" ? null : +v; else if (el.dataset.t === "bool") v = v === "true";
      try { await api(`/api/sessions/${SID}/params`, {method: "PATCH", body: JSON.stringify({path: el.dataset.path, value: v})}); toast(`✅ 已修改 ${esc(el.dataset.path)} = ${esc(v)}（来源改为“用户指定”）`); await refresh(false); }
      catch (e) { toast(esc(e.message.replace(/^\{"detail":"|"\}$/g, "")), "err"); el.classList.add("flash"); } });
    const conf = async run => { try { await api(`/api/sessions/${SID}/workflow/confirm`, {method: "POST", body: JSON.stringify({})}); toast("✅ 参数已确认");
      if (run) { follow("run"); W.pinned = true; await refresh(false); runNow(); } else { follow("model"); W.pinned = true; await refresh(false); } } catch (e) { toast(esc(e.message), "err"); } };
    $("#pConfirm").onclick = () => conf(false); if ($("#pConfirmRun")) $("#pConfirmRun").onclick = () => conf(true);
  }

  // ③ 模型构建
  async function pModel() {
    if (needSc()) return; loading("生成模型拓扑…");
    const [m, v] = await Promise.all([api(`/api/sessions/${SID}/model`), api(`/api/sessions/${SID}/model/validate`)]);
    const sm = m.graph?.summary || {};
    body().innerHTML = `<h3>③ 模型构建（拓扑核对）</h3>
      <div class="wf-guide">请核对：母线电压等级与连接、线路/变压器容量、风光/电源装机、储能与数据中心接入位置、迁移链路。需要改动时点「在拓扑编辑器中修改」，修改会同步到参数表与智能体。</div>
      <div class="wf-kv">${Object.entries(sm).slice(0, 14).map(([k, x]) => `<div><span class="muted">${esc(k)}</span><b>${esc(typeof x === "object" ? JSON.stringify(x) : x)}</b></div>`).join("")}</div>
      <div class="wf-valid">${v.errors?.length ? `<div class="retry">❌ ${v.errors.map(esc).join("；")}</div>` : '<span class="ok-t">✅ 模型校验通过</span>'}${v.warnings?.length ? `<div class="warn-t">⚠ ${v.warnings.map(esc).join("；")}</div>` : ""}</div>
      <div id="wfMv"></div>
      ${nav("params", "solver", `<button class="ghost" id="mEdit">✏️ 在拓扑编辑器中修改</button>`)}`;
    ModelViz.render($("#wfMv"), m.graph, {htmlUrl: m.html, pngUrl: m.png});
    $("#mEdit").onclick = () => { $$("[name=mvSrc]")[0].checked = true; show("model"); };
  }

  // ④ 求解配置 + 数学模型
  async function pSolver() {
    if (needSc()) return; loading("读取数学模型…");
    const [f, wf] = [await api(`/api/sessions/${SID}/formulation`), W.wf]; const c = wf.solver_cfg;
    const on = x => x.active ? '<span class="pill ok">启用</span>' : '<span class="pill off">关闭</span>';
    body().innerHTML = `<h3>④ 求解配置</h3>
      <div class="card"><div class="fs-grid">
        <label>求解器 <span class="tip" data-tip="开源线性规划求解器 HiGHS，经 Pyomo 调用">ⓘ</span><select data-c="solver"><option>HiGHS</option></select></label>
        <label>时间上限 s<input type="number" data-c="time_limit_s" value="${c.time_limit_s ?? ""}"></label>
        <label>计算基线 <span class="tip" data-tip="基线=批处理本地均匀运行、无迁移、无储能，用于量化优化收益">ⓘ</span><select data-c="run_baseline" data-b="1"><option ${c.run_baseline ? "selected" : ""}>true</option><option ${!c.run_baseline ? "selected" : ""}>false</option></select></label>
        <label>交流潮流校核<select data-c="ac_check" data-b="1"><option ${c.ac_check ? "selected" : ""}>true</option><option ${!c.ac_check ? "selected" : ""}>false</option></select></label>
        <label>校核时刻 h（空=峰值时刻）<input type="number" min="0" max="23.75" step="0.25" data-c="ac_hour" value="${c.ac_hour ?? ""}"></label>
        <label>收益归因 <span class="tip" data-tip="额外求解 2 个反事实 LP，把节省拆成 时移/迁移/储能 三部分">ⓘ</span><select data-c="attribution" data-b="1"><option ${c.attribution ? "selected" : ""}>true</option><option ${!c.attribution ? "selected" : ""}>false</option></select></label>
      </div></div>
      <h3>本次使用的数学模型 <span class="muted sm2">${esc(f.problem)}；${esc(f.horizon)}</span></h3>
      ${f.size ? `<div class="wf-kv"><div><span class="muted">决策变量</span><b>${f.size.n_vars}</b></div><div><span class="muted">固定变量</span><b>${f.size.n_fixed_vars}</b></div><div><span class="muted">约束</span><b>${f.size.n_constraints}</b></div><div><span class="muted">求解状态</span><b>${esc(f.size.status)}</b></div><div><span class="muted">求解时间</span><b>${f.size.time_s}s</b></div></div>` : '<div class="muted">模型规模（变量数/约束数）将在求解后显示。</div>'}
      <h4>目标函数 min J =</h4><table class="ftbl"><tr><th>项</th><th>表达式</th><th>状态</th><th>原因</th></tr>${f.objective.map(o => `<tr class="${o.active ? "" : "off"}"><td>${esc(o.name)}</td><td>${tex(o.latex)}</td><td>${on(o)}</td><td class="muted">${esc(o.reason)}</td></tr>`).join("")}</table>
      <h4>约束（步数/物理时间见上方时间轴，积分含Δt）</h4><table class="ftbl"><tr><th>约束</th><th>表达式</th><th>状态</th><th>说明 / 原因</th></tr>${f.constraints.map(o => `<tr class="${o.active ? "" : "off"}"><td>${esc(o.name)}</td><td>${tex(o.latex)}</td><td>${on(o)}</td><td class="muted">${esc([o.text, o.reason].filter(Boolean).join("；"))}</td></tr>`).join("")}</table>
      <h4>决策变量</h4><div class="wf-vars">${f.variables.map(x => `<span class="${x.active ? "" : "off"}">${tex(x.sym)} ${esc(x.name)} <span class="muted">${esc(x.unit)}</span></span>`).join("")}</div>
      ${(f.approximations || []).length ? `<h4 id="approxSec">线性化与近似（算-电-热-碳耦合）</h4><ul class="warns">${f.approximations.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
      <p class="muted">📌 ${esc(f.baseline_note)}<br>📌 ${esc(f.ac_note)}</p>
      <div class="wf-confirm"><div>${wf.confirmed ? "参数已确认，可以运行。" : '<span class="retry">参数尚未确认，请先回到 ② 点击「确认参数」。</span>'}</div><button id="sRun" ${wf.confirmed ? "" : "disabled"}>▶ 开始运行</button></div>
      ${nav("model", "run")}`;
    $$("#stepBody [data-c]").forEach(el => el.onchange = async () => { let v = el.value; if (el.dataset.b) v = v === "true"; else if (el.type === "number") v = v === "" ? null : +v;
      try { W.wf = await api(`/api/sessions/${SID}/solver`, {method: "PUT", body: JSON.stringify({cfg: {[el.dataset.c]: v}})}); toast("✅ 求解配置已更新"); } catch (e) { toast(esc(e.message), "err"); } });
    $("#sRun").onclick = () => { follow("run"); W.pinned = true; stepper(); render().then(runNow); };
  }

  // ⑤ 运行与校核
  const logItem = e => `<div class="lg ${e.ok === false ? "bad" : ""}"><div class="lg-h"><span class="dot ${e.ok === false ? "err" : "ok"}"></span><b>${esc(e.title)}</b><code class="muted">${esc(e.tool || "")}</code>
      <span class="muted">${ACT_ICON(e.actor || "")} ${esc(e.actor || "")} · ${esc(e.ts || "")} · ${e.duration_s ?? 0}s</span><span class="pill step">${esc(STEPS.find(s => s[0] === e.step)?.[1] || "")}</span></div>
    ${e.why ? `<div class="lg-why">💡 ${esc(e.why)}</div>` : ""}${e.error ? `<div class="retry">错误：${esc(e.error)}</div>` : ""}
    <details><summary class="muted">输入 / 输出</summary><div class="lg-io"><div><b>输入</b><pre>${esc(JSON.stringify(e.args ?? {}, null, 1))}</pre></div><div><b>输出摘要</b><pre>${esc(JSON.stringify(e.outputs ?? {}, null, 1))}</pre></div></div></details></div>`;
  async function pRun() {
    if (needSc()) return;
    const r = await api(`/api/sessions/${SID}/runlog`);
    const sv = Object.entries(r.solver || {}).filter(([, x]) => x);
    const ac = r.ac?.optimized;
    body().innerHTML = `<h3>⑤ 运行与校核</h3><div id="runProg"></div>
      <div class="wf-confirm"><div>${W.wf.confirmed ? "将按 ④ 的配置依次：求解优化方案 → 基线 → 交流校核 → KPI → 对比 → 图表/报告 → 收益归因。" : '<span class="retry">参数未确认：请先回到 ② 确认。</span>'}</div><button id="rRun" ${W.wf.confirmed ? "" : "disabled"}>${W.wf.solved ? "🔁 重新运行" : "▶ 开始运行"}</button></div>
      <h4>求解器</h4>${sv.length ? `<table class="tbl"><tr><th>方案</th><th>求解器</th><th>状态</th><th>目标函数 元</th><th>对偶界</th><th>Gap</th><th>用时</th><th>变量</th><th>约束</th></tr>${sv.map(([k, x]) => `<tr><td>${k === "optimized" ? "优化方案" : "基线"}</td><td>${esc(x.name)}</td><td>${x.status === "optimal" ? "✅ 最优" : esc(x.status)}</td><td>${fmt(x.objective)}</td><td>${fmt(x.bound)}</td><td>${(+x.gap_pct).toExponential(1)}%</td><td>${x.time_s}s</td><td>${x.n_vars}</td><td>${x.n_constraints}</td></tr>`).join("")}</table>` : '<p class="muted">尚未求解。</p>'}
      <h4>交流潮流校核（pandapower）</h4>${ac ? `<div class="wf-kv"><div><span class="muted">校核时刻</span><b>${ac.hour}:00</b></div><div><span class="muted">收敛</span><b>${ac.converged ? "✅ 是" : "❌ 否"}</b></div>
        <div><span class="muted">电压范围 pu</span><b class="${ac.voltage_ok ? "" : "bad-t"}">${ac.vmin_pu.toFixed(4)} ~ ${ac.vmax_pu.toFixed(4)}</b></div><div><span class="muted">最大支路负载</span><b class="${ac.loading_ok ? "" : "bad-t"}">${ac.max_branch_loading_pct.toFixed(1)}%</b></div>
        <div><span class="muted">DC-OPF 预测负载</span><b>${ac.dcopf_pred_loading_pct.toFixed(1)}%</b></div><div><span class="muted">网损</span><b>${ac.losses_mw} MW</b></div><div><span class="muted">越限</span><b>${ac.voltage_ok && ac.loading_ok ? "✅ 无" : "⚠ 有"}</b></div></div>` : '<p class="muted">尚未校核。</p>'}
      <h4>运行日志（${r.log.length} 条，含智能体与界面操作）</h4><div class="lgs">${r.log.length ? r.log.slice().reverse().map(logItem).join("") : empty("还没有运行记录。")}</div>
      ${nav("solver", W.wf.solved ? "results" : null, r.log.length ? `<a class="btn ghost" href="/api/sessions/${SID}/export.zip" ${W.wf.solved ? "" : 'style="display:none"'}>📦 导出运行包</a>` : "")}`;
    $("#rRun").onclick = runNow;
  }
  async function runNow() {
    const btn = $("#rRun"); if (btn) btn.disabled = true;
    const pg = $("#runProg"); if (!pg) return;
    pg.innerHTML = `<div class="prog"><div class="bar"><i style="width:2%"></i></div><div class="pt">准备运行…</div><div class="plog"></div></div>`;
    try {
      const r = await fetch(`/api/sessions/${SID}/workflow/run`, {method: "POST"});
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      const rd = r.body.getReader(), dec = new TextDecoder(); let buf = "", err = null;
      while (true) { const {value, done} = await rd.read(); if (done) break; buf += dec.decode(value, {stream: true}); let i;
        while ((i = buf.indexOf("\n\n")) >= 0) { const ln = buf.slice(0, i); buf = buf.slice(i + 2); if (!ln.startsWith("data: ")) continue; const e = JSON.parse(ln.slice(6));
          if (e.type === "progress") { pg.querySelector("i").style.width = (100 * (e.i - .5) / e.n) + "%"; pg.querySelector(".pt").innerHTML = `<span class="spinner"></span> 第 ${e.i}/${e.n} 步：<b>${esc(e.title)}</b> — ${esc(e.why)}`; window.setStatus?.("work", `求解中 ${e.i}/${e.n}：${e.title}`); }
          else if (e.type === "log") pg.querySelector(".plog").insertAdjacentHTML("beforeend", `<div>${e.log.ok === false ? "❌" : "✅"} ${esc(e.log.title)} <span class="muted">${e.log.duration_s ?? ""}s</span></div>`);
          else if (e.type === "error") err = e;
          else if (e.type === "end" && window.renderArts) renderArts(e.artifacts); } }
      if (err) { pg.innerHTML = errBox(`「${err.name}」失败：${err.error}`, esc(err.hint)); toast("运行失败", "err"); await refresh(false); return; }
      pg.querySelector("i").style.width = "100%"; toast("✅ 运行完成，正在打开结果"); follow("results"); W.pinned = true; await refresh(false);
    } catch (e) { const msg = (window.friendlyErr ? friendlyErr(e.message || e) : (e.message || e));
      pg.innerHTML = errBox(msg, "检查 ② 参数是否已确认；或查看下方运行日志。原始堆栈不必作为唯一提示。");
      window.setStatus?.("err", "运行未完成"); if (btn) btn.disabled = false; }
  }

  // ⑥ 结果与分析
  async function pResults() {
    if (needSc()) return; loading("汇总结果…");
    const r = await api(`/api/sessions/${SID}/results`);
    if (!r.ok) { body().innerHTML = empty(esc(r.error), `<button data-go="run">去 ⑤ 运行</button>`); return; }
    const a = r.attribution, cmp = r.compare, H = r.series.optimized.hours||Array.from({length:r.series.optimized.dc_total.length},(_,i)=>i*(r.series.optimized.dt_hours||1));
    body().innerHTML = `<h3>⑥ 结果与分析</h3>
      ${cmp ? `<div class="wf-hero">相对基线目标函数降低 <b>${fmt(cmp.saving_cny)}</b> 元/日（<b>${cmp.saving_pct}%</b>）；排放变化 ${cmp.emissions_reduction_pct}%</div>` : ""}
      ${r.audit?.optimized ? `<details open><summary>时间步 / 连续任务 / 迁移次目标 / 福利 / 生命周期审计</summary><pre>${esc(JSON.stringify({time_axis:r.audit.optimized.time_axis,integer_tasks:r.audit.optimized.integer_tasks,migration_cleanup:r.audit.optimized.migration_cleanup,heat_boundaries:r.audit.optimized.heat_boundary_audit,market:r.audit.optimized.market_clearing,network:r.audit.optimized.network_mapping,lifecycle:r.audit.optimized.lifecycle_ledger},null,2))}</pre><p>分配 ${r.audit.optimized.allocations?.length||0} 行；迁移 ${r.audit.optimized.migration_audit?.length||0} 行。正式运行包包含逐任务、迁移、潮流和独立分账。</p><a href="/api/sessions/${SID}/export.zip">下载审计运行包</a></details>` : ""}
      <h4>关键指标 <span class="muted sm2">悬停 ⓘ 查看定义与公式</span></h4>
      <div class="kpis">${r.kpis.map(k => `<div class="kpi"><div class="kn">${esc(k.name)} <span class="tip" data-tip="${esc(k.definition)}｜公式：${esc(k.formula)}">ⓘ</span></div><div class="kv">${fmt(k.value)} <small>${esc(k.unit)}</small></div>
        ${k.baseline !== null && k.baseline !== undefined ? `<div class="kb">基线 ${fmt(k.baseline)}　<span class="${k.delta < 0 ? "dn" : "up"}">${k.delta > 0 ? "+" : ""}${fmt(k.delta)}</span></div>` : ""}<div class="kf">${esc(k.formula)}</div></div>`).join("")}</div>
      <h4>💡 解释这个结果：收益从哪里来？</h4>${a ? `<div class="wf-guide">${esc(a.text)}</div><div id="chWater"></div>
        <table class="tbl"><tr><th>目标函数项</th><th>基线 元</th><th>优化 元</th><th>节省 元</th></tr>${a.terms.filter(t => Math.abs(t.baseline) + Math.abs(t.optimized) > 0.5).map(t => `<tr><td>${esc(t.name)}</td><td>${fmt(t.baseline)}</td><td>${fmt(t.optimized)}</td><td class="${t.saving >= 0 ? "dn" : "up"}">${fmt(t.saving)}</td></tr>`).join("")}</table>
        <div class="wf-kv">${Object.entries({"弃电减少 MWh": a.physical.curtail_reduction_mwh, "外网购电减少 MWh": a.physical.grid_import_reduction_mwh, "购电峰值降低 MW": a.physical.peak_import_reduction_mw, "储能放电 MWh": a.physical.storage_discharge_mwh, "迁移电量 MWh": a.physical.migrated_mwh, ...(a.physical.pue_avg_optimized ? {"日均 PUE 基线→优化": `${a.physical.pue_avg_baseline} → ${a.physical.pue_avg_optimized}`, "冷却节电 MWh": a.physical.cooling_reduction_mwh, "终端实际用热 MWh_th": a.physical.heat_delivered_mwh, "热碳抵扣 tCO2": a.physical.heat_carbon_offset_t} : {}), ...(a.physical.dr_requested_mwh ? {"DR 响应/要求 MWh": `${a.physical.dr_delivered_mwh} / ${a.physical.dr_requested_mwh}`} : {})}).map(([k, x]) => `<div><span class="muted">${k}</span><b>${fmt(x)}</b></div>`).join("")}</div>
        <p class="muted">方法：${esc(a.method)}</p>` : '<p class="muted">未计算归因（需在 ④ 打开“计算基线”和“收益归因”后重新运行）。</p>'}
      ${r.audit?.optimized?.heat_boundary_audit ? (()=>{const b=r.audit.optimized.heat_boundary_audit;return `<p class="wf-guide"><b>热量边界（MWh_th，全精度见审计/ZIP）：</b>热泵/补热源注入 ${b.source_injected_mwh.toFixed(6)}；各管段出口累计到达 ${b.pipe_arrivals_sum_mwh.toFixed(6)}（多跳可能重复计数，不是售热）；终端实际取热 ${b.terminal_served_mwh.toFixed(6)}；管损 ${b.pipe_loss_mwh.toFixed(6)}、储热损耗 ${b.store_loss_mwh.toFixed(6)}、库存变化 ${b.store_change_mwh.toFixed(6)}、在途变化 ${b.transit_change_mwh.toFixed(6)}。售热/替代锅炉碳抵扣使用终端取热；接收节点到达后可先储热并损耗，不能要求管网到达与终端用热相同。全局残差 ${b.residual_mwh.toExponential(3)}。</p>`})() : ''}
      ${r.series.optimized.thermal ? `<h4 id="coupleSec">🌡️ 算-电-热-碳耦合结果</h4>
        <div class="wf-guide">${(r.series.optimized.thermal_violations || []).length ? `<b style="color:#d1242f">⚠️ 热安全越限：${esc(r.series.optimized.thermal_violations.join("；"))}</b>` : "✅ 热安全硬约束全部满足（入口温度 18–允许上限、温变率、N+1 冷量、IT ≤ 可用冷却能力）。"}
        <table class="tbl"><tr><th>数据中心</th><th>入口温度 min~max °C</th><th>距允许上限裕度 K</th><th>超推荐(27°C) h</th><th>动态 PUE min/均/max</th><th>冷却电 MWh</th><th>自然冷却 MWh_th</th><th>蓄冷放冷 MWh_th</th><th>热泵注入热量 MWh_th</th><th>约束起作用 h（允许上限/N+1/温变率/IT≤冷量）</th></tr>
        ${Object.entries(r.series.optimized.thermal).map(([d, x]) => { const q = x.summary, b = q.binding_hours; return `<tr><td>${esc(d)}</td><td>${q.tin_min_c} ~ ${q.tin_max_c}</td><td class="${q.margin_to_allow_k < 1 ? "up" : ""}">${q.margin_to_allow_k}</td><td>${q.hours_above_rec}</td><td>${q.pue_min} / <b>${q.pue_avg}</b> / ${q.pue_max}</td><td>${fmt(q.cooling_mwh)}</td><td>${fmt(q.free_cooling_mwh)}</td><td>${fmt(q.tes_discharge_mwh)}</td><td>${fmt(q.hp_heat_mwh)}</td><td>${b.t_allow_max} / ${b.chiller_n1} / ${b.ramp} / ${b.it_vs_cooling}</td></tr>`; }).join("")}</table></div>
        <div id="chTin"></div><div id="chPue"></div><div id="chCool"></div><div id="chHeat"></div>` : ""}
      ${r.series.optimized.dr ? `<h4 id="drSec">⚡ 电网需求响应</h4><table class="tbl"><tr><th>事件</th><th>类型</th><th>时段</th><th>基线方法</th><th>要求 MWh</th><th>实际响应 MWh</th><th>完成率</th><th>补偿价 元/MWh</th><th>收益 元</th></tr>
        ${r.series.optimized.dr.events.map(e => `<tr><td>${esc(e.name)}</td><td>${e.kind === "reduce" ? "削峰" : "填谷"}</td><td>${e.start}:00–${e.end}:00</td><td>${esc(e.baseline_method)}</td><td>${fmt(e.requested_mwh)}</td><td><b>${fmt(e.delivered_mwh)}</b></td><td>${(e.delivered_mwh / Math.max(e.requested_mwh, 1e-9) * 100).toFixed(1)}%</td><td>${fmt(e.price_cny_mwh)}</td><td>${fmt(e.revenue_cny)}</td></tr>`).join("")}</table><div id="chDR"></div>` : ""}
      <h4>逐时结果（优化 vs 基线）</h4><div id="chLoad"></div><div id="chRe"></div><div id="chSto"></div><div id="chCost"></div>
      <h4>⚠ 假设与局限</h4><ul class="warns">${r.warnings.map(w => `<li>${esc(w)}</li>`).join("")}</ul>
      <div class="next-steps" style="margin:12px 0"><div class="ns-h">跑完了，可以继续问…</div>
        <div class="ns-row">
          <button type="button" class="ghost sm" data-ask="为什么是这个结论？主要节省从哪来？">可以问为什么</button>
          <button type="button" class="ghost sm" data-ask="如果储能容量翻倍会怎样？">如果…会怎样</button>
          <button type="button" class="ghost sm" data-ask="把关键假设和局限再总结一下">总结假设与局限</button>
          <a class="btn ghost sm" href="/api/sessions/${SID}/export.zip">导出报告包</a>
          ${r.report ? `<a class="btn ghost sm" href="${r.report}" target="_blank">打开报告</a>` : ""}
        </div></div>
      <div class="wf-nav"><button class="ghost" data-go="run">← 运行日志</button><span>
        ${r.report ? `<a class="btn ghost" href="${r.report}" target="_blank">📄 查看报告</a> ` : ""}<a class="btn" href="/api/sessions/${SID}/export.zip">📦 导出可复现运行包</a></span></div>`;
    const O = r.series.optimized, B = r.series.baseline, ax = {type: "category", data: H, name: "时"};
    const line = (n, d, o = {}) => ({name: n, type: "line", data: d, smooth: false, symbolSize: 3, ...o});
    if (a) { const P = a.parts; const names = [...P.map(p => p.name.replace(/（.*）/, "")), "合计"], vals = [...P.map(p => p.saving), a.total_saving];
      chartEl({_height: 280, title: {text: "节省来源分解（元/日，正值=节省）", left: "center", textStyle: {fontSize: 13}}, tooltip: {trigger: "axis", formatter: ps => `${ps[0].name}<br>${Math.round(ps[0].value).toLocaleString()} 元` + (ps[0].dataIndex < P.length ? `（${P[ps[0].dataIndex].share_pct}%）` : "")},
        grid: {left: 90, right: 30, top: 40, bottom: 30}, xAxis: {type: "category", data: names}, yAxis: {type: "value", name: "元"},
        series: [{type: "bar", barWidth: "45%", data: vals.map((v, i) => ({value: Math.round(v), itemStyle: {color: i === P.length ? "#1f6feb" : (v >= 0 ? "#1a9b55" : "#d1242f")}})),
          label: {show: true, position: "top", formatter: p => Math.round(p.value).toLocaleString() + (p.dataIndex < P.length ? ` (${P[p.dataIndex].share_pct}%)` : "")}}]}, $("#chWater")); }
    if (O.thermal) { const TL = r.thermal_limits || {}, ds = Object.keys(O.thermal), l0 = TL[ds[0]] || {t_min: 18, t_rec: 27, t_allow: 32};
      chartEl({_height: 340, title: {text: "入口温度与热安全边界（优化；虚线=基线定送风温度）", left: "center", textStyle: {fontSize: 13}}, tooltip: {trigger: "axis"}, legend: {top: 22, type: "scroll"}, grid: {top: 66, left: 55, right: 55}, xAxis: ax,
        yAxis: [{type: "value", name: "°C", min: v => Math.floor(Math.min(v.min, l0.t_min) - 1), max: v => Math.ceil(Math.max(v.max, l0.t_allow) + 1)}, {type: "value", name: "室外 °C"}],
        series: [...ds.map(d => line(d + " 入口温度", O.thermal[d].tin, {markArea: d === ds[0] ? {silent: true, data: [[{yAxis: l0.t_min, itemStyle: {color: "rgba(26,155,85,.08)"}}, {yAxis: l0.t_rec}], [{yAxis: l0.t_rec, itemStyle: {color: "rgba(230,160,0,.10)"}}, {yAxis: l0.t_allow}]]} : undefined,
            markLine: d === ds[0] ? {symbol: "none", data: [{yAxis: l0.t_allow, name: "允许上限", lineStyle: {color: "#d1242f", width: 2}, label: {formatter: `允许上限 ${l0.t_allow}°C`}}, {yAxis: l0.t_rec, lineStyle: {color: "#e6a000", type: "dashed"}, label: {formatter: `推荐上限 ${l0.t_rec}°C`}}, {yAxis: l0.t_min, lineStyle: {color: "#1a9b55", type: "dashed"}, label: {formatter: `下限 ${l0.t_min}°C`}}]} : undefined})),
          B?.thermal && line("基线入口温度", B.thermal[ds[0]].tin, {lineStyle: {type: "dashed", color: "#888"}, itemStyle: {color: "#888"}}),
          line("室外温度", O.thermal[ds[0]].tout, {yAxisIndex: 1, lineStyle: {type: "dotted", color: "#999"}, itemStyle: {color: "#999"}})].filter(Boolean)}, $("#chTin"));
      chartEl({_height: 300, title: {text: "动态 PUE（逐时）：优化 vs 基线", left: "center", textStyle: {fontSize: 13}}, tooltip: {trigger: "axis"}, legend: {top: 22, type: "scroll"}, grid: {top: 66, left: 55, right: 55}, xAxis: ax,
        yAxis: [{type: "value", name: "PUE", min: v => Math.max(1, +(v.min - 0.03).toFixed(2))}, {type: "value", name: "元/kWh"}],
        series: [...ds.map(d => line(d + " PUE", O.thermal[d].pue)), ...(B?.thermal ? ds.slice(0, 1).map(d => line(d + " 基线 PUE", B.thermal[d].pue, {lineStyle: {type: "dashed"}})) : []), line("电价", r.price, {yAxisIndex: 1, step: "middle", itemStyle: {color: "#111"}})]}, $("#chPue"));
      chartEl({_height: 300, title: {text: "冷却电功率与蓄冷罐 SOC（优化）", left: "center", textStyle: {fontSize: 13}}, tooltip: {trigger: "axis"}, legend: {top: 22, type: "scroll"}, grid: {top: 66, left: 55, right: 60}, xAxis: ax,
        yAxis: [{type: "value", name: "MW"}, {type: "value", name: "MWh_th"}],
        series: [...ds.map(d => ({name: d + " 冷却电", type: "bar", stack: "c", data: O.thermal[d].cool})), ...ds.filter(d => Math.max(...O.thermal[d].tes_soc) > 0).map(d => line(d + " 蓄冷 SOC", O.thermal[d].tes_soc, {yAxisIndex: 1}))]}, $("#chCool"));
      if (O.heat) chartEl({_height: 300, title: {text: "热边界：热泵注入 / 终端实际用热 / 储热（非管段到达量）", left: "center", textStyle: {fontSize: 13}}, tooltip: {trigger: "axis"}, legend: {top: 22, type: "scroll"}, grid: {top: 66, left: 55, right: 60}, xAxis: ax,
        yAxis: [{type: "value", name: "MW_th"}, {type: "value", name: "MWh_th"}],
        series: [...ds.filter(d => Math.max(...O.thermal[d].hp_heat) > 0).map(d => ({name: d + " 热泵供热", type: "bar", stack: "h", data: O.thermal[d].hp_heat, itemStyle: {}})), line("可接纳热负荷", O.heat.demand, {lineStyle: {type: "dashed", color: "#d1242f"}}), line("终端实际用热", O.heat.delivered, {itemStyle: {color: "#e8590c"}}), line("热网蓄热", O.heat.store, {yAxisIndex: 1, itemStyle: {color: "#9c36b5"}})]}, $("#chHeat"));
      else $("#chHeat").innerHTML = '<p class="muted">本场景未接入区域供热网（无余热回收）。</p>'; }
    if (O.dr) chartEl({_height: 300, title: {text: "需求响应：基线 vs 实际（参与 DC 合计）", left: "center", textStyle: {fontSize: 13}}, tooltip: {trigger: "axis"}, legend: {top: 22}, grid: {top: 60, left: 55, right: 30}, xAxis: ax, yAxis: {type: "value", name: "MW"},
      series: [{name: "响应量", type: "bar", data: O.dr.delivered, itemStyle: {color: "#1a9b55"}}, {name: "要求量", type: "bar", data: O.dr.request, itemStyle: {color: "rgba(209,36,47,.35)"}}]}, $("#chDR"));
    chartEl({_height: 300, title: {text: "数据中心电网侧总功率 vs 电价", left: "center", textStyle: {fontSize: 13}}, tooltip: {trigger: "axis"}, legend: {top: 22}, grid: {top: 60, left: 55, right: 55}, xAxis: ax,
      yAxis: [{type: "value", name: "MW"}, {type: "value", name: "元/kWh"}], series: [line("优化", O.dc_total), B && line("基线", B.dc_total, {lineStyle: {type: "dashed"}}), line("电价", r.price, {yAxisIndex: 1, step: "middle", itemStyle: {color: "#111"}})].filter(Boolean)}, $("#chLoad"));
    chartEl({_height: 280, title: {text: "新能源可用 vs 实际利用（差值=弃电）", left: "center", textStyle: {fontSize: 13}}, tooltip: {trigger: "axis"}, legend: {top: 22}, grid: {top: 60, left: 60, right: 20}, xAxis: ax, yAxis: {type: "value", name: "MW"},
      series: [line("可用", O.pv_avail, {areaStyle: {opacity: .15}}), line("优化 利用", O.pv_used), B && line("基线 利用", B.pv_used, {lineStyle: {type: "dashed"}})].filter(Boolean)}, $("#chRe"));
    const st = Object.entries(O.storage);
    if (st.length) chartEl({_height: 280, title: {text: "储能充放电与 SOC（优化）", left: "center", textStyle: {fontSize: 13}}, tooltip: {trigger: "axis"}, legend: {top: 22}, grid: {top: 60, left: 60, right: 60}, xAxis: ax, yAxis: [{type: "value", name: "MW"}, {type: "value", name: "MWh"}],
      series: st.flatMap(([n, x]) => [{name: n + " 充电", type: "bar", data: x.ch}, {name: n + " 放电", type: "bar", data: x.dis.map(v => -v)}, line(n + " SOC", x.soc, {yAxisIndex: 1})])}, $("#chSto"));
    else $("#chSto").innerHTML = '<p class="muted">本场景无储能。</p>';
    chartEl({_height: 280, title: {text: "逐时发购电费用（元）", left: "center", textStyle: {fontSize: 13}}, tooltip: {trigger: "axis"}, legend: {top: 22}, grid: {top: 60, left: 80, right: 20}, xAxis: ax, yAxis: {type: "value"},
      series: [line("优化", O.hour_cost), B && line("基线", B.hour_cost, {lineStyle: {type: "dashed"}})].filter(Boolean)}, $("#chCost"));
    $$("#stepBody [data-ask]").forEach(b => b.onclick = () => { $("#input").value = b.dataset.ask; $("#input").focus(); window.setStatus?.("idle", "已填入追问 — Enter 发送"); });
    window.setStatus?.("ok", "已有结论 — 可追问为什么 / 如果… / 导出报告");
    window.showNextSteps?.("done");
  }

  // 对话事件 -> 步骤高亮/刷新
  function onEvent(e) {
    if (e.type === "tool_start") { follow(e.step); W.wf && (W.wf.steps = W.wf.steps.map(s => ({...s, current: s.id === e.step}))); stepper();
      const lab = STEPS.find(s => s[0] === e.step); window.setStatus?.("work", lab ? `研究阶段：${lab[1]}` : "处理中…"); }
    else if (e.type === "tool_end" || e.type === "done") refresh(true);
    else if (e.type === "confirm_needed") { follow("params"); refresh(false); window.setStatus?.("ok", "已暂停 — 请确认参数"); }
  }
  window.WF = {refresh, go, onEvent, follow, runNow};
})();
