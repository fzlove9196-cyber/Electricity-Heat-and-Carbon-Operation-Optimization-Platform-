/* 🔬 研究模式：问题卡 / 澄清 / 计划编辑 / 研究时间线 / 运行与诊断 / 检查点 / 证据化结论 / What-if / 知识沉淀 / 报告。
   对话与研究编排器深度耦合：卡片按钮以“命令消息”形式回到对话（可追溯），右侧面板实时刷新。依赖 app.js 的 $, $$, esc, api, SID, send, chartEl, md。 */
(function () {
  let ST = null, ctx = null, openRun = null;
  const LV = {error: "❌", warn: "⚠️", info: "ℹ️", ok: "✅"};
  const KIND = {formulate: "📋", clarify: "❓", plan: "🗺", run: "▶️", diagnose: "🩺", revise: "🔧", checkpoint: "⏸", conclude: "✅", sediment: "🧠", why: "💡", whatif: "🔁", sync: "🔄"};
  const STAT = {pending: ["待执行", "s-default"], running: ["执行中", "s-agent"], done: ["完成", "s-public"], failed: ["不可行/失败", "s-err"], skipped: ["跳过", "s-default"]};
  const BY = {plan: "计划", diagnose: "诊断追加", revise: "诊断修订", whatif: "追问"};
  const n = (v, d = 1) => typeof v === "number" ? (Math.abs(v) >= 1000 ? v.toLocaleString(undefined, {maximumFractionDigits: 0}) : (+v.toFixed(d)).toString()) : esc(v ?? "—");
  const runChip = (rid, txt) => rid ? `<a class="rchip" data-rid="${esc(rid)}" title="查看运行 ${esc(rid)}">${esc(txt || rid)}</a>` : "";
  const cmd = t => { if (typeof send === "function") send(t); };
  async function load() { if (!SID) return (ST = null); try { ST = (await api(`/api/sessions/${SID}/study`)).study; } catch { ST = null; } return ST; }
  function badge() { return ST ? `<span class="now">${esc((ST.phases.find(p => p.current) || {}).label || "")}</span>` : ""; }

  // ---------- 对话事件 ----------
  function onEvent(e, t) {
    if (e.type === "study") { ST = e.study; if (window.WF && (ctx?.isOpen?.() || $("#stepper .st.rs.view"))) render($("#stepBody"), ctx || {}); else if (t.live && window.WF) WF.go("research", false); return true; }
    if (e.type === "user_ref") { const u = [...$$("#chatLog .msg.user")].pop(); if (u) { u.dataset.midx = e.idx; u.insertAdjacentHTML("afterbegin", `<span class="midx">#${e.idx}</span>`); } return true; }
    if (e.type === "progress") { t.tl.insertAdjacentHTML("beforeend", `<div class="rs-prog">⏳ <b>${esc(e.step)}</b> ${esc(e.title)} <span class="muted">— ${esc(e.why || "")}</span></div>`); return true; }
    if (e.type === "run") { const r = e.run; t.tl.insertAdjacentHTML("beforeend", `<div class="rs-prog">${["✅", "ℹ️", "⚠️", "❌"][r.worst] || "•"} ${runChip(r.id)} ${esc(r.label)} · ${r.status === "optimal" ? "日净成本 " + n(r.cost, 0) + " 元" : `<span class="retry">${esc(r.status)}</span>`}</div>`); return true; }
    if (e.type === "study_card") { const d = bot(card(e.card), t); bindCard(d, e.card); const nt = document.createElement("div"); nt.className = "timeline"; t.tl.after(nt); t.tl = nt; return true; }
    return false;
  }
  function card(c) {
    if (c.kind === "problem") { const s = c.study, k = s.card;
      return `<div class="rs-card prob"><div class="rs-h">📋 研究问题卡 <span class="muted">（${esc(k.by)}）</span></div><b>${esc(k.title)}</b><p>${esc(k.research_question)}</p>
        <div class="rs-grid"><div><b>决策变量</b><ul>${k.decision_variables.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div><div><b>约束</b><ul>${k.constraints.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>
        <div><b>评价指标</b><ul>${k.kpis.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div><div><b>情景</b><ul>${k.scenarios.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div></div>
        ${s.references?.length ? `<div class="rs-ref">📚 参考了哪些经验：${s.references.map(r => `<span class="tag" title="${esc(r.example)}">${esc(r.title)}</span>`).join("")}</div>` : ""}</div>`; }
    if (c.kind === "clarify") return `<div class="rs-card clar"><div class="rs-h">❓ 需要澄清的关键信息</div>
      ${c.answered?.length ? `<div class="muted">已从你的原话解析：${c.answered.map(q => `${esc(q.q.split("？")[0])} = <b>${esc(q.answer)}</b>`).join("；")}</div>` : ""}
      ${c.questions.map(q => `<div class="rs-q"><b>${esc(q.q)}</b> <span class="muted">— ${esc(q.why)}</span><div>${q.options.map(o => `<label class="opt"><input type="radio" name="${q.id}" value="${esc(String(o.v))}" ${String(o.v) === String(q.default) ? "checked" : ""}> ${esc(o.label)}</label>`).join("")}</div></div>`).join("")}
      <div class="row"><button class="sm" data-act="ans">提交回答</button><button class="sm ghost" data-act="def">用默认值继续</button></div></div>`;
    if (c.kind === "plan") return `<div class="rs-card plan"><div class="rs-h">🗺 研究计划</div><ol>${c.plan.map(p => `<li><b>${p.id}</b> ${esc(p.title)} <span class="muted">— ${esc(p.why)}</span></li>`).join("")}</ol>
      <div class="row"><button class="sm" data-act="approve">✅ 批准计划并执行</button><button class="sm ghost" data-act="edit">✏️ 在右侧编辑计划</button></div></div>`;
    if (c.kind === "checkpoint") { const k = c.checkpoint;
      return `<div class="rs-card ckpt"><div class="rs-h">⏸ 检查点 ${k.id}：${esc(k.title)}</div><p>${esc(k.detail)}</p><p class="muted">🤖 建议理由：${esc(k.why)}</p>
        ${k.candidates.map(x => `<button class="sm ${x.id === k.recommend ? "" : "ghost"}" data-kid="${k.id}" data-cand="${x.id}">${x.id === k.recommend ? "⭐ " : ""}${esc(x.label)}</button>`).join(" ")}</div>`; }
    if (c.kind === "conclusions") return `<div class="rs-card conc"><div class="rs-h">✅ 证据化结论</div>${c.conclusions.map(concl).join("")}
      <div class="row"><button class="sm ghost" data-act="why">💡 为什么？</button><button class="sm ghost" data-act="whatif">🔁 如果…会怎样？</button><button class="sm ghost" data-act="report">📄 生成报告</button></div></div>`;
    if (c.kind === "sediment") return `<div class="rs-card sed"><div class="rs-h">🧠 建议沉淀为知识（需你确认）</div>${c.items.map(x => `<label class="opt blk"><input type="checkbox" value="${x.id}" ${x.status === "saved" ? "checked disabled" : "checked"}> <b>${x.id}</b> [${esc(x.kind)}] ${esc(x.card.title)}${x.status === "saved" ? " ✔已保存" : ""}</label>`).join("")}
      <div class="row"><button class="sm" data-act="sed">采纳选中项</button></div></div>`;
    if (c.kind === "whatif") { const w = c.whatif; return `<div class="rs-card wi"><div class="rs-h">🔁 What-if ${w.id}</div>${esc(w.mods_desc)} → ${runChip(w.run)} vs 主方案 ${runChip(w.ref_run)}${w.value ? `<div>${esc(w.value.label)}：${n(w.value.before, 0)} → <b>${n(w.value.after, 0)}</b> 元/日</div>` : ""}</div>`; }
    if (c.kind === "report") return `<div class="rs-card"><div class="rs-h">📄 研究报告</div>${c.files.map(f => `<a href="/artifacts/${SID}/${f}?download=1">⬇ ${f}</a>`).join("　")} <a href="/artifacts/${SID}/study_report.html" target="_blank">在新窗口打开</a></div>`;
    return "";
  }
  function concl(c) {
    const ev = c.evidence.filter(e => e && e.run).map(e => runChip(e.run, `${e.run}·${e.label}=${n(e.value)}`)).join(" ");
    const ln = (c.links || []).map(l => l.kind === "param" ? `<a class="plink" data-path="${esc(l.path)}">⚙ ${esc(l.path)}</a>` : l.kind === "step" ? `<a class="slink" data-sid="${esc(l.id)}">🗺 ${esc(l.id)}</a>` : "").join(" ");
    return `<div class="rs-c"><div><b>${c.id}</b> <span class="pill ${c.confidence === "高" ? "ok" : c.confidence === "中" ? "warn" : "err"}">置信度 ${c.confidence}</span> <span>${md(c.text)}</span></div>
      ${c.narrative ? `<div class="muted">🤖 ${esc(c.narrative)}</div>` : ""}
      <div class="rs-ev">证据：${ev || "—"} ${ln}</div>${c.binding?.length ? `<div class="rs-ev">紧约束：${c.binding.map(b => `<span class="tag">${esc(b)}</span>`).join("")}</div>` : ""}
      <div class="rs-ev muted">依赖假设：${(c.assumptions || []).map(a => `<span class="tag" title="${esc((ST?.assumption_list || []).find(x => x.id === a)?.text || "")}">${a}</span>`).join("")}
        <button class="xs ghost" data-why="${c.id}">为什么？</button></div></div>`;
  }
  function bindCard(d, c) {
    d.querySelectorAll("[data-act=ans]").forEach(b => b.onclick = () => { const a = c.questions.map(q => { const r = d.querySelector(`input[name=${q.id}]:checked`); return r ? `${q.id}=${r.value}` : ""; }).filter(Boolean); cmd("【澄清回答】" + a.join("; ")); });
    d.querySelectorAll("[data-act=def]").forEach(b => b.onclick = () => cmd("【澄清回答】（采用默认值）"));
    d.querySelectorAll("[data-act=approve]").forEach(b => b.onclick = () => cmd("【批准计划】"));
    d.querySelectorAll("[data-act=edit]").forEach(b => b.onclick = () => WF.go("research", true));
    d.querySelectorAll("[data-cand]").forEach(b => b.onclick = () => cmd(`【检查点】${b.dataset.kid} ${b.dataset.cand}`));
    d.querySelectorAll("[data-act=why]").forEach(b => b.onclick = () => { $("#input").value = "为什么余热/DR 方案是这个结论？"; $("#input").focus(); });
    d.querySelectorAll("[data-why]").forEach(b => b.onclick = () => cmd(`为什么 ${b.dataset.why} 成立？`));
    d.querySelectorAll("[data-act=whatif]").forEach(b => b.onclick = () => { $("#input").value = ST?.topic === "heat_recovery" ? "如果热价降到80会怎样" : "如果热浪再高2度会怎样"; $("#input").focus(); });
    d.querySelectorAll("[data-act=report]").forEach(b => b.onclick = () => cmd("【生成报告】"));
    d.querySelectorAll("[data-act=sed]").forEach(b => b.onclick = () => cmd("【采纳沉淀】" + [...d.querySelectorAll("input[type=checkbox]:checked:not(:disabled)")].map(x => x.value).join(" ")));
  }

  // ---------- 右侧研究面板 ----------
  async function render(el, c) {
    ctx = c || ctx; if (!ST) await load();
    if (!ST) { el.innerHTML = `<h3>🔬 研究模式</h3><div class="wf-guide">勾选对话框下方 <b>🔬 研究模式</b> 后提问（例：“中卫冬季想用余热供暖，看值不值”）。智能体会：<br>① 形式化为<b>研究问题卡</b> → ② 针对关键缺失信息<b>澄清</b>（带选项与默认值）→ ③ 生成可编辑的<b>研究计划</b> → ④ 逐步<b>执行·诊断·修订</b>（不可行/异常自动定位并在检查点请你确认）→ ⑤ 输出带<b>证据链</b>的结论（可追问“为什么/如果…”）→ ⑥ 把方法与经验<b>沉淀</b>为知识。</div>`; return; }
    const s = ST, k = s.card;
    const phases = `<div class="rs-phases">${s.phases.map((p, i) => `<span class="ph ${p.done ? "done" : ""} ${p.current ? "cur" : ""}">${p.done ? "✓" : i + 1} ${esc(p.label)}</span>`).join('<span class="arrow">›</span>')}<span class="muted">　${esc(s.llm_mode)}</span></div>`;
    const qs = s.questions.map(q => { const src = q.source || {}; return `<tr><td>${esc(q.q)}</td><td><b>${esc(q.answer ?? "（待回答）")}</b> <span class="muted">默认 ${esc(q.default)}</span></td>
      <td>${src.tag ? `<span class="src ${src.tag === "用户指定" ? "s-user" : "s-agent"}" title="${esc(src.note)}">${esc(src.tag)}</span>` : ""}${src.msg ? ` <a class="msgref" data-midx="${src.msg.idx}" title="“${esc(src.msg.quote)}”">💬#${src.msg.idx}</a>` : ""}</td><td class="muted">${esc(q.path)}</td></tr>`; }).join("");
    const plan = s.plan.map(p => { const [sl, sc] = STAT[p.status] || [p.status, ""]; const sens = p.kind === "sensitivity" && p.status === "pending";
      return `<tr class="${p.status === "running" ? "hl" : ""}"><td>${p.status === "pending" ? `<input type="checkbox" data-en="${p.id}" ${p.enabled ? "checked" : ""}>` : ""}</td><td><b>${p.id}</b></td><td>${esc(p.title)}<div class="muted">${esc(p.why)}</div>
        ${sens ? `<div>取值 <input class="sv" data-sv="${p.id}" value="${p.variants.map(v => Object.values(v.mods)[0]).join(",")}" style="width:140px"></div>` : ""}${p.diag ? `<div class="rs-diag">🩺 ${esc(p.diag)}</div>` : ""}</td>
        <td><span class="src ${sc}">${sl}</span></td><td><span class="tag">${BY[p.added_by] || p.added_by}</span></td><td>${(p.runs || []).map(r => runChip(r)).join(" ")}</td></tr>`; }).join("");
    const tl = (s.timeline || []).map(x => `<li><span class="muted">${x.t}</span> ${KIND[x.kind] || "•"} ${x.step ? `<b>${esc(x.step)}</b> ` : ""}${esc(x.text)}${x.why ? `<div class="muted why">为什么：${esc(x.why)}</div>` : ""}</li>`).join("");
    const runs = Object.values(s.runs || {}).map(r => { const w = Math.max(0, ...r.findings.map(f => ({error: 3, warn: 2, info: 1, ok: 0})[f.level]));
      return `<tr data-rrow="${r.id}" class="${openRun === r.id ? "hl" : ""}"><td>${runChip(r.id)}</td><td>${esc(r.label)}<div class="muted">${esc(r.mods_desc)}</div></td><td>${r.status === "optimal" ? "optimal" : `<span class="retry">${esc(r.status)}</span>`}</td>
        <td>${n(r.kpis?.cost_cny, 0)}</td><td>${n(r.kpis?.tin_max_c)}</td><td>${n(r.kpis?.heat_delivered_mwh, 0)}</td><td>${n(r.kpis?.dr_delivered_mwh)}</td><td>${["✅", "ℹ️", "⚠️", "❌"][w]}</td></tr>`; }).join("");
    const ck = (s.checkpoints || []).filter(x => x.status === "open").map(x => card({kind: "checkpoint", checkpoint: x})).join("");
    const wi = (s.whatifs || []).map(w => `<div class="rs-card wi"><b>${w.id}</b> “${esc(w.question)}” → ${esc(w.mods_desc)} ${runChip(w.run)} ${w.rows ? `<table class="tbl sm"><tr><th>指标</th><th>主方案</th><th>What-if</th><th>Δ</th></tr>${w.rows.map(r => `<tr><td>${esc(r.name)}</td><td>${n(r.before)}</td><td>${n(r.after)}</td><td>${r.delta == null ? "" : (r.delta > 0 ? "+" : "") + n(r.delta)}</td></tr>`).join("")}</table>` : esc(w.status)}
      ${w.value ? `<div>${esc(w.value.label)}：${n(w.value.before, 0)} → <b>${n(w.value.after, 0)}</b> 元/日</div>` : ""}</div>`).join("");
    el.innerHTML = `<h3>🔬 研究：${esc(k.title)}</h3>${phases}
      <details ${s.state === "clarify" ? "open" : ""}><summary><b>📋 研究问题卡</b>　${esc(k.research_question)}</summary>${card({kind: "problem", study: s})}
        <b>假设</b><ul>${(s.assumption_list || k.assumptions.map((a, i) => ({id: "·", text: a, src: ""}))).map(a => `<li><b>${a.id}</b> ${esc(a.text)} <span class="muted">${esc(a.src)}</span></li>`).join("")}</ul></details>
      <details open><summary><b>❓ 澄清与关键参数</b>（来源可追溯到对话消息）</summary><table class="tbl"><tr><th>问题</th><th>取值</th><th>来源</th><th>参数路径</th></tr>${qs}</table>
        ${(s.ui_edits || []).length ? `<div class="muted">🔄 界面编辑同步：${s.ui_edits.map(u => u.diffs.map(d => `${esc(d.path)}: ${esc(d.old)}→${esc(d.new)}`).join("；")).join(" | ")}</div>` : ""}</details>
      ${ck ? `<div class="rs-sec">${ck}</div>` : ""}
      <div class="rs-sec"><div class="rs-h">🗺 研究计划 <span class="muted">（可勾选/修改敏感性取值；诊断会自动追加实验）</span></div>
        <table class="tbl"><tr><th></th><th>步骤</th><th>内容 / 为什么 / 诊断</th><th>状态</th><th>来源</th><th>运行</th></tr>${plan}</table>
        ${s.state === "plan" ? `<div class="row"><button class="sm ghost" id="rsSave">💾 保存计划修改</button><button class="sm" id="rsApprove">✅ 批准并执行</button><label class="chk2"><input type="checkbox" id="rsAuto" ${s.auto_revise ? "checked" : ""}> 诊断修订自动采纳（不在检查点暂停）</label></div>` : ""}
        <div class="muted">修订次数 ${s.iter.revisions}/${s.iter.cap}</div></div>
      <div class="rs-cols"><div class="rs-sec"><div class="rs-h">⏱ 研究时间线</div><ol class="rs-tl">${tl}</ol></div>
        <div class="rs-sec"><div class="rs-h">🧪 运行与诊断 <span class="muted">点击运行查看诊断/紧约束/逐时曲线</span></div><table class="tbl sm"><tr><th>运行</th><th>说明</th><th>状态</th><th>日净成本</th><th>最高入口°C</th><th>供热</th><th>DR</th><th>诊断</th></tr>${runs}</table><div id="rsRun"></div></div></div>
      ${s.conclusions?.length ? `<div class="rs-sec">${card({kind: "conclusions", conclusions: s.conclusions})}</div>` : ""}
      ${wi ? `<div class="rs-sec"><div class="rs-h">🔁 What-if 追问</div>${wi}</div>` : ""}
      ${s.sediment?.length ? `<div class="rs-sec">${card({kind: "sediment", items: s.sediment})}</div>` : ""}
      ${s.state === "done" ? `<div class="rs-sec"><div class="rs-h">📄 研究报告</div><a href="/artifacts/${SID}/study_report.md?download=1">⬇ study_report.md</a>　<a href="/artifacts/${SID}/study_report.html" target="_blank">🌐 study_report.html</a></div>` : ""}`;
    el.querySelectorAll(".rs-card").forEach(d => { const kk = d.classList.contains("ckpt") ? {kind: "checkpoint"} : d.classList.contains("conc") ? {kind: "conclusions"} : d.classList.contains("sed") ? {kind: "sediment"} : null; if (kk) bindCard(d, kk); });
    const save = async () => { const steps = s.plan.filter(p => p.status === "pending").map(p => { const o = {id: p.id, enabled: !!el.querySelector(`[data-en=${p.id}]`)?.checked}; const sv = el.querySelector(`[data-sv=${p.id}]`); if (sv) o.values = sv.value.split(/[,，\s]+/).filter(Boolean).map(Number); return o; });
      ST = (await api(`/api/sessions/${SID}/study/plan`, {method: "PATCH", body: JSON.stringify({steps, auto_revise: !!el.querySelector("#rsAuto")?.checked})})).study; };
    if (el.querySelector("#rsSave")) el.querySelector("#rsSave").onclick = async () => { await save(); ctx?.toast?.("计划已保存"); render(el); };
    if (el.querySelector("#rsApprove")) el.querySelector("#rsApprove").onclick = async () => { await save(); cmd("【批准计划】"); };
    if (openRun) showRun(openRun, false);
  }
  async function showRun(rid, scroll = true) {
    openRun = rid; const box = $("#rsRun"); if (!box) { if (window.WF) { WF.go("research", true); setTimeout(() => showRun(rid), 400); } return; }
    const r = (await api(`/api/sessions/${SID}/study/run/${rid}`)).run;
    if (!box.isConnected) return showRun(rid, scroll);
    box.innerHTML = `<div class="rs-card run"><div class="rs-h">🧪 ${r.id} ${esc(r.label)} <span class="muted">${esc(r.mods_desc)} · ${r.elapsed_s}s · ${r.artifact ? `<a href="/artifacts/${SID}/${r.artifact}?download=1">⬇ CSV</a>` : ""}</span></div>
      ${r.error ? `<div class="wf-err">${esc(r.error)}</div>` : ""}
      <ul class="rs-f">${r.findings.map(f => `<li>${LV[f.level]} <b>${esc(f.title)}</b> <span class="muted">[${f.code}]</span> ${esc(f.detail)}${f.suggest ? `<div class="muted">👉 ${esc(f.suggest.note || f.suggest.action)}</div>` : ""}</li>`).join("")}</ul>
      ${r.infeasibility ? `<table class="tbl sm"><tr><th>松弛试探</th><th>结果</th></tr>${r.infeasibility.tests.map(t => `<tr><td>${esc(t.relax)}</td><td>${t.feasible ? "✅ 可行" : t.feasible === false ? "❌ 仍不可行" : "—"}</td></tr>`).join("")}</table>` : ""}
      ${r.binding?.length ? `<b>紧约束 / 影子价格（LP 对偶）</b><table class="tbl sm"><tr><th>约束组</th><th>起作用/总数</th><th>Σ|对偶|</th><th>最大对偶</th></tr>${r.binding.map(b => `<tr><td>${esc(b.group)}</td><td>${b.n_binding}/${b.n}</td><td>${n(b.dual_abs_sum, 0)}</td><td>${n(b.dual_max)}</td></tr>`).join("")}</table>` : ""}
      <div id="rsChart"></div></div>`;
    const H = r.hourly, cb = box.querySelector("#rsChart"); if (H && H.tin_max_c && window.echarts && cb) chartEl({tooltip: {trigger: "axis"}, legend: {top: 0}, grid: {left: 40, right: 40, top: 30, bottom: 25}, xAxis: {type: "category", data: H.hour},
      yAxis: [{type: "value", name: "°C", min: v => Math.floor(v.min - 2)}, {type: "value", name: "PUE", min: 1}], series: [{name: "最高入口温度", type: "line", data: H.tin_max_c}, {name: "室外温度", type: "line", data: H.tout_c, lineStyle: {type: "dashed"}}, {name: "PUE", type: "line", yAxisIndex: 1, data: H.pue}]}, cb);
    $$("#stepBody [data-rrow]").forEach(tr => tr.classList.toggle("hl", tr.dataset.rrow === rid));
    if (scroll) box.scrollIntoView({behavior: "smooth", block: "nearest"});
  }
  document.addEventListener("click", e => {
    const a = e.target.closest(".rchip"); if (a) { e.preventDefault(); return showRun(a.dataset.rid); }
    const r = e.target.closest("[data-rrow]"); if (r && !e.target.closest("a")) return showRun(r.dataset.rrow);
    const m = e.target.closest(".msgref"); if (m) { const u = $(`#chatLog .msg.user[data-midx="${m.dataset.midx}"]`);
      if (u) { u.scrollIntoView({behavior: "smooth", block: "center"}); u.classList.add("flash"); setTimeout(() => u.classList.remove("flash"), 1800); } else alert(m.title); return; }
    const p = e.target.closest(".plink"); if (p && window.WF) { WF.go("params", true); setTimeout(() => { const i = $(`[data-path="${p.dataset.path}"]`); i?.scrollIntoView({block: "center"}); i?.closest("tr")?.classList.add("flash"); }, 900); return; }
    const sl = e.target.closest(".slink"); if (sl && window.WF) { WF.go("research", true); }
  });
  window.RS = {onEvent, render, badge, load, showRun, get: () => ST, reset: () => { ST = null; openRun = null; }};
})();
