const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const md = (s, base) => { let h = marked.parse(esc(s).replace(/&gt;/g, ">"));
  if (base) h = h.replace(/(src|href)="(?!https?:|\/)([^"]+)"/g, `$1="${base}$2"`); return h; };
const api = async (u, o = {}) => { const r = await fetch(u, {headers: {"Content-Type": "application/json"}, ...o});
  if (!r.ok) throw new Error((await r.text()).slice(0, 300)); if(o.method && o.method !== "GET") window.PF?.changed?.(); return r.json(); };
let SID = localStorage.getItem("sid") || null, busy = false, scenario = null;
const TOOL_CN = {build_scenario:"构建场景", run_dispatch:"优化调度", run_ac_check:"交流潮流校核", compute_kpis:"计算KPI",
  compare_baseline:"基线对比", make_plots:"生成图表", write_report:"撰写报告", run_matpower:"MATPOWER", run_andes_tds:"ANDES 暂态",
  run_opendss:"OpenDSS 配网", run_openmodelica:"OpenModelica", run_paraview_render:"ParaView 3D", search_knowledge:"检索知识库", save_skill_card:"保存技能卡",
  get_carbon_profile:"碳强度曲线", run_pareto_sweep:"成本-碳 Pareto 扫描", generate_jobs:"生成任务", load_job_trace:"加载任务 trace", show_model_topology:"模型拓扑", plot_topology:"拓扑单线图", plot_energy_flow:"能流图"};
const ONBOARD = [
  {kicker: "🔬 研究 · 经济最优", rs: true, title: "中卫：成本与碳的寻优折中", desc: "看经济性最优、碳排放最优与中间折中方案（对话触发寻优）。", prompt: "中卫项目寻优：我想看经济性最优和碳排放最优的方案，以及中间的折中"},
  {kicker: "🔬 研究 · 热浪 + DR", rs: true, title: "热浪下保障热安全并参与需求响应", desc: "压力日：热安全硬约束 + 削峰响应，给出证据化方案。", prompt: "中卫夏季热浪下保障热安全同时参与需求响应的最优方案"},
  {kicker: "🔬 研究 · 余热供暖", rs: true, title: "余热供暖靠谱吗？", desc: "冬季余热回收可行性：末端、距离、热价与结论置信度。", prompt: "中卫冬季想用余热供暖，看值不值"},
  {kicker: "配置 · 散热对比", rs: false, title: "对比风冷与液冷散热", desc: "一键对比多种散热方式的能耗、PUE 与可行性卡片。", prompt: "对比风冷和液冷散热方式"},
  {kicker: "工作台 · 调度入门", rs: false, title: "三数据中心 + 储能调度", desc: "经典入门：峰谷电价下优化调度，核对参数后再求解。", prompt: "三个数据中心，加50MWh储能，峰谷电价，帮我优化调度并分析"},
];
const EXAMPLES = ONBOARD.map(o => (o.rs ? "🔬 " : "") + o.prompt);
// ---------- ECharts（本地打包 /static/vendor/echarts.min.js，无 CDN） ----------
function chartEl(option, parent) { const d = document.createElement("div"); d.className = "echart"; parent.append(d);
  if (option._height) { d.style.height = option._height + "px"; delete option._height; }
  if (!window.echarts) { d.textContent = "ECharts 未加载"; return d; }
  const c = echarts.init(d);
  if (option.series?.some(x => x.type === "graph" && x.data?.some(n => n.tip)))   // 拓扑图：悬停显示参数/来源
    option.tooltip = {trigger: "item", formatter: p => p.data?.tip || p.name};
  if (option.series?.some(x => x.type === "line" && Array.isArray(x.data?.[0]?.value)))
    option.tooltip = {trigger: "item", formatter: p => `${p.name}<br>排放 ${(+p.value[0]).toFixed(1)} t<br>成本 ${(+p.value[1]).toLocaleString()} 元`};
  c.setOption(option); new ResizeObserver(() => c.resize()).observe(d); return d; }

// ---------- 导航 ----------
$$("nav a[data-view]").forEach(a => a.onclick = () => show(a.dataset.view));
function show(v) { $$("nav a[data-view]").forEach(a => a.classList.toggle("active", a.dataset.view === v));
  $$(".view").forEach(x => x.classList.toggle("active", x.id === "v-" + v)); $("#side").classList.remove("open");
  ({market: () => window.loadMarket?.(), config: () => window.loadConfig?.(), model: loadModel, kb: () => { loadDocs(); kbInfo(); }, cards: loadCards, scenario: loadScenario, sims: loadSims, settings: loadSettings, tier: () => window.TierPanel?.refresh?.()})[v]?.(); window.IA?.update?.(v); window.PF?.render?.(); window.PF?.sessionContext?.(); }
$("#menuBtn").onclick = () => $("#side").classList.toggle("open");
function setStatus(kind, text) {
  const d = $("#statusDot"), t = $("#statusText");
  if (d) d.className = "sdot " + (kind || "idle");
  if (t) t.textContent = text || "就绪";
}
window.setStatus = setStatus;
function friendlyErr(raw) {
  let s = String(raw || "未知错误");
  try { const j = JSON.parse(s); if (j.detail) s = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch {}
  s = s.replace(/^\{"detail":"|"\}$/g, "").slice(0, 280);
  if (/Traceback|File \"|Error:/i.test(s) && s.length > 120) s = "服务端出错了。请稍后重试，或到「⑤ 运行与校核」查看日志。";
  return s;
}
window.friendlyErr = friendlyErr;
function showNextSteps(kind) {
  const box = $("#nextSteps"); if (!box) return;
  const sets = {
    pause: [["打开参数表核对", () => WF.go("params", true)], ["确认并继续", () => { WF.go("params", true); }], ["问：这些默认值合理吗？", () => { $("#input").value = "这些默认参数合理吗？哪些是假设？"; $("#input").focus(); }]],
    done: [["为什么是这个结论？", () => { $("#input").value = "为什么是这个结论？主要节省从哪来？"; $("#input").focus(); }], ["如果…会怎样？", () => { $("#input").value = "如果储能容量翻倍会怎样？"; $("#input").focus(); }], ["导出可复现报告", () => { if (SID) location.href = `/api/sessions/${SID}/export.zip`; }], ["查看结果面板", () => WF.go("results", true)]],
    research: [["为什么？", () => { $("#input").value = "为什么这个结论成立？"; $("#input").focus(); }], ["如果热价/热浪变化…", () => { $("#input").value = "如果热价降到80会怎样"; $("#input").focus(); }], ["生成研究报告", () => send("【生成报告】")], ["打开研究面板", () => WF.go("research", true)]],
  };
  const acts = sets[kind]; if (!acts) { box.classList.add("hidden"); box.innerHTML = ""; return; }
  box.classList.remove("hidden");
  box.innerHTML = `<div class="ns-h">下一步可以…</div><div class="ns-row"></div>`;
  const row = box.querySelector(".ns-row");
  acts.forEach(([label, fn]) => { const b = document.createElement("button"); b.type = "button"; b.textContent = label; b.onclick = fn; row.append(b); });
}
window.showNextSteps = showNextSteps;
function renderOnboard() {
  const el = $("#examples"); if (!el) return;
  el.innerHTML = ONBOARD.map((o, i) => `<button type="button" class="onb-card" data-i="${i}"><span class="onb-kicker${o.rs ? " rs" : ""}">${esc(o.kicker)}</span><span class="onb-title">${esc(o.title)}</span><span class="onb-desc">${esc(o.desc)}</span><span class="onb-go">一键开始 →</span></button>`).join("");
  $$("#examples .onb-card").forEach(b => b.onclick = () => {
    const o = ONBOARD[+b.dataset.i]; if (!o) return;
    if ($("#researchMode")) $("#researchMode").checked = !!o.rs;
    $("#input").value = o.prompt; send(o.prompt);
  });
}
function bindExamples() { renderOnboard(); }
renderOnboard();
// 轻量 ? 提示（非强制模态）
const helpPop = $("#helpPop"), helpTip = $("#helpTip"), helpClose = $("#helpClose");
const toggleHelp = (on) => { if (!helpPop) return; helpPop.classList.toggle("hidden", on === undefined ? !helpPop.classList.contains("hidden") : !on); };
helpTip && (helpTip.onclick = () => toggleHelp());
helpClose && (helpClose.onclick = () => toggleHelp(false));
document.addEventListener("keydown", e => {
  if (e.key === "Escape") toggleHelp(false);
  if ((e.ctrlKey || e.metaKey) && e.key === "/") { e.preventDefault(); $("#input")?.focus(); }
});

// ---------- 会话 ----------
async function loadSessions() {
  const ss = await api("/api/sessions");
  $("#sessList").innerHTML = ss.map(s => `<li data-id="${s.id}" class="${s.id === SID ? "active" : ""}"><span>${esc(s.title)}</span><b data-del="${s.id}" title="删除">✕</b></li>`).join("");
  $$("#sessList li").forEach(li => li.onclick = e => { if (e.target.dataset.del) return delSess(e.target.dataset.del); openSession(li.dataset.id); });
}
async function delSess(id) { if (!confirm("删除该会话及其结果文件？")) return; await api("/api/sessions/" + id, {method: "DELETE"});
  if (id === SID) newSession(); loadSessions(); }
function newSession() { window.RS?.reset(); SID = null; setTimeout(() => WF.refresh(), 0); localStorage.removeItem("sid"); $("#chatLog").innerHTML = $("#chatLog").dataset.welcome; bindExamples(); $("#artBar").innerHTML = ""; loadSessions(); show("chat"); }
$("#chatLog").dataset.welcome = $("#chatLog").innerHTML; $("#newSess").onclick = newSession;
async function openSession(id) {
  let s; try { s = await api("/api/sessions/" + id); } catch { return newSession(); }
  window.RS?.reset(); SID = id; localStorage.setItem("sid", id); $("#chatLog").innerHTML = ""; show("chat");
  const users = s.messages.filter(m => m.role === "user");
  s.events.forEach((evs, i) => { addUser(users[i]?.content || ""); const t = newTurn(); evs.forEach(e => handle(e, t)); });
  renderArts(s.artifacts); loadSessions(); WF.refresh(true); window.PF?.sessionContext?.();
}

// ---------- 对话 ----------
function addUser(t) { const d = document.createElement("div"); d.className = "msg user"; d.textContent = t; $("#chatLog").append(d); }
function newTurn() { const tl = document.createElement("div"); tl.className = "timeline"; $("#chatLog").append(tl); return {tl, steps: {}}; }
function bot(html, t) { const d = document.createElement("div"); d.className = "msg"; d.innerHTML = html; t.tl.after(d); t.tl = d; return d; }
function renderArts(arts) { $("#artBar").innerHTML = (arts || []).map(a => `<a href="${a.url}?download=1" title="下载">⬇ ${esc(a.name)}</a>`).join(""); }
const artUrl = n => `/artifacts/${SID}/${n}`;
async function inline(res, t, name) {
  const files = [].concat(res.artifacts || [], res.artifact || []);
  const box = document.createElement("div"); box.className = "msg hidden";
  t.tl.after(box); t.tl = box; const nt = document.createElement("div"); nt.className = "timeline"; box.after(nt); t.tl = nt;
  for (const f of files) {
    if (/_echarts\.json$/.test(f)) continue;
    if (/^model_topology\./.test(f)) continue;
    if (/\.png$/.test(f)) box.innerHTML += `<p><b>${esc(f)}</b><br><img src="${artUrl(f)}" loading="lazy"></p>`;
    else if (/\.md$/.test(f)) { const txt = await (await fetch(artUrl(f))).text(); box.innerHTML += `<div class="report">${md(txt, `/artifacts/${SID}/`)}</div>`; }
    else if (/\.csv$/.test(f) && name !== "run_dispatch") box.innerHTML += await csvTable(f);
  }
  if (name === "compare_baseline" && res.table) box.innerHTML += `<h4>基线对比（节省 ${res.saving_pct}%）</h4><table><tr><th>指标</th><th>基线</th><th>优化</th></tr>` +
    Object.entries(res.table).map(([k, v]) => `<tr><td>${k}</td><td>${v.baseline ?? ""}</td><td>${v.optimized ?? ""}</td></tr>`).join("") + "</table>";
  if (name === "run_pareto_sweep" && res.points) box.innerHTML += `<h4>Pareto 点（减排 ${res.tradeoff.emission_reduction_pct}%，成本 +${res.tradeoff.cost_increase_pct}%，边际减排成本 ${res.tradeoff.abatement_cost_cny_t} 元/t）</h4><table><tr><th>w</th><th>等效碳价 元/t</th><th>成本 元</th><th>排放 t</th><th>迁移 MWh</th></tr>` +
    res.points.map(p => `<tr><td>${p.weight}</td><td>${p.eff_carbon_price_cny_t}</td><td>${p.cost_cny.toLocaleString()}</td><td>${p.emissions_tco2}</td><td>${p.migrated_mwh}</td></tr>`).join("") + "</table>";
  if (name === "compute_kpis") box.innerHTML += `<h4>KPI</h4><table>${Object.entries(res.kpis).map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("")}</table>`;
  for (const f of [].concat(res.echarts || [])) { try { const opt = await (await fetch(artUrl(f))).json(); chartEl(opt, box); } catch (e) { console.warn(e); } }
  if (res.model_view) { const mv = document.createElement("div"); mv.className = "mv-inline";
    box.insertAdjacentHTML("beforeend", `<h4>🗺 模型拓扑${name === "build_scenario" ? "（建模完成，请核对模型后再运行）" : "（已叠加求解潮流/能流）"} <a class="sm" href="#" data-goto-model>在“模型拓扑”页打开</a></h4>`); box.append(mv);
    try { const g = await (await fetch(artUrl(res.model_view) + "?t=" + Date.now())).json(); ModelViz.render(mv, g, {htmlUrl: artUrl("model_topology.html"), pngUrl: artUrl("model_topology.png")});
      if ($("#v-model").classList.contains("active")) loadModel(); } catch (e) { mv.textContent = "模型图加载失败：" + e.message; }
    box.querySelector("[data-goto-model]").onclick = ev => { ev.preventDefault(); $$("[name=mvSrc]")[0].checked = true; show("model"); }; }
  if (box.innerHTML) box.classList.remove("hidden");
}
async function csvTable(f) {
  const rows = (await (await fetch(artUrl(f))).text()).trim().split("\n").slice(0, 13).map(r => r.split(","));
  const cols = rows[0].length > 10 ? 10 : rows[0].length;
  return `<details><summary>${esc(f)}（前 12 行）</summary><table>${rows.map((r, i) => `<tr>${r.slice(0, cols).map(c => i ? `<td>${esc((+c).toFixed ? (isNaN(+c) ? c : (+c).toFixed(3)) : c)}</td>` : `<th>${esc(c)}</th>`).join("")}</tr>`).join("")}</table></details>`;
}
function handle(e, t) {
  if (t.live && window.WF) WF.onEvent(e);
  if (window.OPT && e.type === "opt_card" && OPT.onEvent(e, t)) return;
  if (window.RS && ["study", "study_card", "user_ref", "progress", "run"].includes(e.type) && RS.onEvent(e, t)) return;
  if (e.type === "confirm_needed") { t.awaitConfirm = true; setStatus("ok", "已建模 — 请核对参数后继续"); showNextSteps("pause");
    const d = bot(`<div class="wf-pause">⏸ 智能体已构建模型并<b>暂停</b>，等待你确认参数（将继续：${(e.pending || []).map(esc).join(" → ")}）。<br>
    <div class="param-nudge">右侧「② 输入参数」可看到每个数的单位与来源（用户指定 / 智能体推断 / 默认值）。</div>
    <button class="sm" data-goparams>打开「② 输入参数」核对并确认</button></div>`, t);
    d.querySelector("[data-goparams]").onclick = () => WF.go("params", true); return; }
  if (e.type === "retrieval") { t.tl.insertAdjacentHTML("beforeend", `<div class="muted">🔎 检索到 ${e.cards.map(c => `<span class="tag">卡:${esc(c)}</span>`).join("")}${e.docs.map(d => `<span class="tag">文档:${esc(d)}</span>`).join("")}</div>`); }
  else if (e.type === "message") { bot(md(e.content), t); const nt = document.createElement("div"); nt.className = "timeline"; t.tl.after(nt); t.tl = nt; }
  else if (e.type === "tool_start") { setStatus("work", `正在：${TOOL_CN[e.name] || e.name}`);
    const d = document.createElement("details"); d.className = "step";
    d.innerHTML = `<summary><span class="dot spin"></span><b>${TOOL_CN[e.name] || e.name}</b><code class="muted">${esc(e.name)}</code><span class="muted st">运行中…</span></summary><pre>参数: ${esc(JSON.stringify(e.args, null, 1))}</pre>`;
    t.tl.append(d); t.steps[e.id] = d; }
  else if (e.type === "tool_end") { const d = t.steps[e.id] || (handle({type: "tool_start", ...e, args: {}}, t), t.steps[e.id]);
    d.querySelector(".dot").className = "dot " + (e.ok ? "ok" : "err");
    d.querySelector(".st").innerHTML = e.ok ? `完成 ${e.elapsed_s ?? ""}s` : `<span class="retry">未成功（第 ${e.result?.retry ?? "?"} 次）— 智能体将尝试修正</span>`;
    const raw = esc(JSON.stringify(e.result, null, 1));
    if (e.ok) d.insertAdjacentHTML("beforeend", `<pre>结果: ${raw}</pre>`);
    else { const msg = friendlyErr(e.result?.error || e.result?.message || raw);
      d.insertAdjacentHTML("beforeend", `<div class="friendly-err">${esc(msg)}<div class="hint">展开下方可看详细返回；一般无需阅读堆栈。</div></div><details><summary class="muted">详细返回</summary><pre>${raw}</pre></details>`);
      setStatus("err", `工具未成功：${TOOL_CN[e.name] || e.name}`); }
    if (e.ok) inline(e.result, t, e.name); }
  else if (e.type === "done") {
    if (t.awaitConfirm) { setStatus("ok", "已建模 — 请核对参数后继续"); showNextSteps("pause"); }
    else { setStatus("ok", $("#researchMode")?.checked ? "研究轮次完成 — 可追问为什么 / 如果…" : "本轮完成 — 可查看结果或继续追问");
      showNextSteps($("#researchMode")?.checked ? "research" : "done"); }
    if (e.citations?.length) bot(`<div class="cite">📎 引用来源：${e.citations.map(esc).join("；")}</div>`, t);
    renderArts(e.artifacts); }
}
async function send(text) {
  if (busy || !text.trim()) return; busy = true; $("#sendBtn").disabled = true;
  showNextSteps(null); setStatus("work", "智能体处理中…");
  if ($(".welcome")) $("#chatLog").innerHTML = "";
  addUser(text); const t = newTurn(); t.live = true;
  const body = {message: text, session_id: SID, auto_run: !!$("#autoRun")?.checked, research: !!$("#researchMode")?.checked}; if ($("#useScenario").checked && scenario) body.scenario = scenario;
  try {
    const r = await fetch("/api/chat/stream", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    const rd = r.body.getReader(), dec = new TextDecoder(); let buf = "";
    while (true) { const {value, done} = await rd.read(); if (done) break; buf += dec.decode(value, {stream: true});
      let i; while ((i = buf.indexOf("\n\n")) >= 0) { const line = buf.slice(0, i); buf = buf.slice(i + 2);
        if (!line.startsWith("data: ")) continue; const e = JSON.parse(line.slice(6));
        if (e.type === "session") { SID = e.session_id; localStorage.setItem("sid", SID); } else handle(e, t);
        $("#chatLog").scrollTop = 1e9; } }
  } catch (err) { setStatus("err", "请求失败"); bot(`<div class="friendly-err">请求没有成功：${esc(friendlyErr(err.message))}<div class="hint">👉 检查网络或到「⚙️ 设置」确认 Mock/LLM；也可新开会话重试。</div></div>`, t); }
  busy = false; $("#sendBtn").disabled = false; loadSessions(); WF.refresh(true);
}
$("#chatForm").onsubmit = e => { e.preventDefault(); const v = $("#input").value; $("#input").value = ""; send(v); };
$("#input").onkeydown = e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#chatForm").requestSubmit(); } };

// ---------- 上传 ----------
async function upload(files) { const out = [];
  for (const f of files) { const fd = new FormData(); fd.append("file", f);
    const r = await fetch("/api/kb/docs", {method: "POST", body: fd}); out.push(r.ok ? `✅ ${f.name}（${(await r.json()).n_chunks} 块）` : `❌ ${f.name}: ${await r.text()}`); }
  alert(out.join("\n")); loadDocs(); }
function dropify(el, cls) { el.ondragover = e => { e.preventDefault(); el.classList.add(cls); }; el.ondragleave = () => el.classList.remove(cls);
  el.ondrop = e => { e.preventDefault(); el.classList.remove(cls); upload(e.dataTransfer.files); }; }
dropify($("#dropZone"), "drag"); dropify($("#chatForm"), "drag");
$("#dropZone").onclick = () => $("#fileInput").click(); $("#fileInput").onchange = e => upload(e.target.files);
async function loadDocs() { const ds = await api("/api/kb/docs");
  $("#docTable").innerHTML = `<tr><th>文件</th><th>分块</th><th>索引</th><th>上传时间</th><th></th></tr>` + ds.map(d => `<tr><td>${esc(d.name)}</td><td>${d.n_chunks}</td><td>${d.embed}</td><td>${new Date(d.created * 1000).toLocaleString()}</td><td><button class="sm danger" data-id="${d.id}">删除</button></td></tr>`).join("");
  $$("#docTable button").forEach(b => b.onclick = async () => { await api("/api/kb/docs/" + b.dataset.id, {method: "DELETE"}); loadDocs(); }); }
$("#kbReindex").onclick = async () => { $("#kbInfo").textContent = "正在重建向量索引…"; const r = await api("/api/kb/reindex", {method: "POST"});
  $("#kbInfo").textContent = r.ok ? `✅ 已重建：${r.n_chunks} 个文档块 + ${r.n_cards} 张技能卡，模型 ${r.model}，存储 ${r.store}，用时 ${r.seconds}s` : "❌ " + r.error; };
async function kbInfo() { try { const i = await api("/api/kb/info"); $("#kbInfo").textContent = `检索后端：嵌入 ${i.embed} · 重排 ${i.rerank} · 分词 ${i.tokenizer} · 向量库 ${i.store}（混合检索：BM25 + 稠密向量 → RRF → 重排）`; } catch {} }
$("#kbSearchBtn").onclick = async () => { const r = await api("/api/kb/search?q=" + encodeURIComponent($("#kbQuery").value));
  $("#kbInfo").textContent = `耗时 ${r.latency_ms} ms · 嵌入 ${r.backend.embed} · 重排 ${r.backend.rerank} · 分词 ${r.backend.tokenizer} · ${r.backend.store}`;
  $("#kbResult").innerHTML = r.docs.map(d => `<div class="card"><b>${esc(d.source)}</b> <span class="muted">score ${d.score}</span><pre>${esc(d.text)}</pre></div>`).join("") +
    r.cards.map(c => `<div class="card">🧠 技能卡：<b>${esc(c.title)}</b></div>`).join("") || "<p class='muted'>无结果</p>"; };

// ---------- 技能卡 ----------
const CF = [["title", "标题"], ["task_type", "任务类型"], ["keywords", "关键词"], ["steps", "步骤（可写工具名顺序）"], ["params", "参数（可 JSON）"], ["checks", "校验要点"], ["example", "示例脚本"]];
async function loadCards() { const cs = await api("/api/cards");
  $("#cardList").innerHTML = cs.map(c => `<div class="card"><h4>${esc(c.title)}</h4><span class="tag">${esc(c.task_type)}</span><span class="muted">使用 ${c.uses} 次</span>
    <pre>${esc(c.steps)}</pre>${c.checks ? `<div class="muted">校验：${esc(c.checks)}</div>` : ""}<div class="row"><button class="sm ghost" data-e="${c.id}">编辑</button><button class="sm danger" data-d="${c.id}">删除</button></div></div>`).join("") || "<p class='muted'>暂无技能卡</p>";
  $$("#cardList [data-e]").forEach(b => b.onclick = () => editCard(cs.find(c => c.id === b.dataset.e)));
  $$("#cardList [data-d]").forEach(b => b.onclick = async () => { if (confirm("删除？")) { await api("/api/cards/" + b.dataset.d, {method: "DELETE"}); loadCards(); } }); }
function editCard(c = {}) { const ed = $("#cardEditor"); ed.classList.remove("hidden");
  ed.innerHTML = `<div class="form">${CF.map(([k, l]) => `<label>${l}</label>${["steps", "example", "params", "checks"].includes(k) ? `<textarea rows="3" name="${k}">${esc(c[k])}</textarea>` : `<input name="${k}" value="${esc(c[k])}">`}`).join("")}</div>
  <div class="row"><button id="cardSave">保存</button><button class="ghost" id="cardCancel">取消</button></div>`;
  $("#cardCancel").onclick = () => ed.classList.add("hidden");
  $("#cardSave").onclick = async () => { const d = Object.fromEntries([...ed.querySelectorAll("[name]")].map(i => [i.name, i.value]));
    await api(c.id ? "/api/cards/" + c.id : "/api/cards", {method: c.id ? "PUT" : "POST", body: JSON.stringify(d)}); ed.classList.add("hidden"); loadCards(); }; }
$("#newCard").onclick = () => editCard();

// ---------- 场景参数 ----------
async function loadScenario() { if (!scenario) scenario = JSON.parse(localStorage.getItem("scenario") || "null") || await api("/api/scenario/default"); renderSc(); }
function renderSc() {
  $("#scJson").value = JSON.stringify(scenario, null, 2); localStorage.setItem("scenario", JSON.stringify(scenario)); mvLive?.();
  const num = (path, label, v) => `<label>${label}<input type="number" step="any" data-p="${path}" value="${v}"></label>`;
  let h = `<fieldset><legend>全局</legend><div class="fs-grid"><label>电价类型<select data-p="price_kind">${[...new Set(["peak_valley", "flat", scenario.price_kind])].map(k => `<option ${scenario.price_kind === k ? "selected" : ""}>${k}</option>`).join("")}</select></label>
    ${num("load_scale", "负荷倍率", scenario.load_scale)}${num("mig_max_mw", "每小时迁移上限 MW", scenario.mig_max_mw)}${num("mig_day_share", "日迁移比例上限", scenario.mig_day_share)}${num("pv_curtail_penalty", "弃光惩罚 元/MWh", scenario.pv_curtail_penalty)}</div></fieldset>`;
  h += `<fieldset><legend>数据中心 <button class="sm" id="addDc" type="button">＋</button></legend>` + scenario.data_centers.map((d, i) => `<div class="fs-grid"><label>名称<input data-p="data_centers.${i}.name" value="${esc(d.name)}"></label>
    ${num(`data_centers.${i}.bus`, "母线", d.bus)}${num(`data_centers.${i}.cap_it_mw`, "IT容量 MW", d.cap_it_mw)}${num(`data_centers.${i}.pue`, "PUE", d.pue)}${num(`data_centers.${i}.batch_mwh`, "批处理 MWh/日", d.batch_mwh)}<label>&nbsp;<button type="button" class="sm danger" data-rm="data_centers.${i}">删除</button></label></div>`).join("") + "</fieldset>";
  h += `<fieldset><legend>储能 <button class="sm" id="addEss" type="button">＋</button></legend>` + scenario.storage.map((s, i) => `<div class="fs-grid"><label>名称<input data-p="storage.${i}.name" value="${esc(s.name)}"></label>
    ${num(`storage.${i}.bus`, "母线", s.bus)}${num(`storage.${i}.energy_mwh`, "容量 MWh", s.energy_mwh)}${num(`storage.${i}.power_mw`, "功率 MW", s.power_mw)}${num(`storage.${i}.soc0`, "初始SOC", s.soc0)}<label>&nbsp;<button type="button" class="sm danger" data-rm="storage.${i}">删除</button></label></div>`).join("") + "</fieldset>";
  h += `<fieldset><legend>光伏</legend>` + scenario.pv.map((p, i) => `<div class="fs-grid">${num(`pv.${i}.bus`, "母线", p.bus)}${num(`pv.${i}.cap_mw`, "容量 MW", p.cap_mw)}</div>`).join("") + "</fieldset>";
  const sel = (path, label, opts, v) => `<label>${label}<select data-p="${path}">${opts.map(o => `<option ${v === o ? "selected" : ""}>${o}</option>`).join("")}</select></label>`;
  scenario.carbon_factor ??= 0.5306; scenario.carbon_price_cny_t ??= 100; scenario.carbon_weight ??= 0; scenario.carbon_accounting ??= "location"; scenario.carbon_shape ??= "solar_dip";
  scenario.jobs ??= []; scenario.links ??= []; scenario.mig_energy_mwh_per_mwh ??= 0;
  h += `<fieldset><legend>🌱 碳感知（成本 + w × 碳价 × 排放）</legend><div class="fs-grid">${num("carbon_factor", "排放因子 kgCO2/kWh（全国 0.5306）", scenario.carbon_factor)}
    ${sel("carbon_shape", "日内形状（合成）", ["solar_dip", "flat"], scenario.carbon_shape)}${num("carbon_price_cny_t", "碳价 元/t", scenario.carbon_price_cny_t)}
    ${num("carbon_weight", "碳权重 w（0=纯成本）", scenario.carbon_weight)}${sel("carbon_accounting", "核算口径", ["location", "generation"], scenario.carbon_accounting)}</div>
    <div id="carbonChart"></div></fieldset>`;
  h += `<fieldset><legend>🔗 迁移链路（时延 / 带宽 / 迁移能耗） <button class="sm" id="addLink" type="button">＋</button></legend><div class="fs-grid">${num("mig_energy_mwh_per_mwh", "迁移能耗 κ（MWh/迁移MWh）", scenario.mig_energy_mwh_per_mwh)}</div>` +
    scenario.links.map((l, i) => `<div class="fs-grid"><label>A<input data-p="links.${i}.a" value="${esc(l.a)}"></label><label>B<input data-p="links.${i}.b" value="${esc(l.b)}"></label>${num(`links.${i}.latency_ms`, "时延 ms", l.latency_ms)}${num(`links.${i}.bw_mw`, "带宽上限 MW/h", l.bw_mw)}<label>&nbsp;<button type="button" class="sm danger" data-rm="links.${i}">删除</button></label></div>`).join("") +
    `<p class="muted">链路为空 = 不限链路（仅“每小时迁移上限”）；非空 = 只能沿已定义链路迁移，时延敏感任务不可走超过其时延上限的链路。</p></fieldset>`;
  h += `<fieldset><legend>🧾 任务级批处理作业（${scenario.jobs.length} 个，合计 ${scenario.jobs.reduce((a, j) => a + (+j.energy_mwh || 0), 0).toFixed(1)} MWh）</legend>
    <div class="row"><label class="muted">数量 <input type="number" id="nJobs" value="30" style="width:70px"></label><label class="muted">随机种子 <input type="number" id="jobSeed" value="42" style="width:70px"></label>
    <button type="button" class="sm" id="genJobs">生成合成任务（SYNTHETIC）</button><button type="button" class="sm danger" id="clearJobs">清空（回到聚合批处理模型）</button><button type="button" class="sm ghost" id="addJob">＋ 手动添加</button></div>
    ${scenario.jobs.length ? `<div style="max-height:320px;overflow:auto"><table class="tbl jobs-tbl"><tr><th>id</th><th>归属DC</th><th>释放 h</th><th>截止 h</th><th>能量 MWh</th><th>最大功率 MW</th><th>允许DC(逗号,空=全部)</th><th>时延上限 ms(空=不敏感)</th><th></th></tr>` +
    scenario.jobs.map((j, i) => `<tr><td><input data-p="jobs.${i}.id" value="${esc(j.id)}"></td><td><input data-p="jobs.${i}.dc" value="${esc(j.dc)}"></td>
      <td><input type="number" data-p="jobs.${i}.release" value="${j.release}"></td><td><input type="number" data-p="jobs.${i}.deadline" value="${j.deadline}"></td>
      <td><input type="number" step="any" data-p="jobs.${i}.energy_mwh" value="${j.energy_mwh}"></td><td><input type="number" step="any" data-p="jobs.${i}.max_mw" value="${j.max_mw}"></td>
      <td><input class="w" data-list="jobs.${i}.allowed_dcs" value="${esc((j.allowed_dcs || []).join(","))}"></td><td><input data-opt="jobs.${i}.max_latency_ms" value="${j.max_latency_ms ?? ""}"></td>
      <td><button type="button" class="sm danger" data-rm="jobs.${i}">✕</button></td></tr>`).join("") + "</table></div>" : `<p class="muted">无任务：使用各数据中心“批处理 MWh/日”聚合模型（与旧版一致）。</p>`}</fieldset>`;
  $("#scForm").innerHTML = h;
  const setp = (p, v) => { const ks = p.split("."); let o = scenario; ks.slice(0, -1).forEach(k => o = o[k]); o[ks.at(-1)] = v; };
  $$("#scForm [data-list]").forEach(el => el.onchange = () => { const v = el.value.split(",").map(x => x.trim()).filter(Boolean); setp(el.dataset.list, v.length ? v : null); renderSc(); });
  $$("#scForm [data-opt]").forEach(el => el.onchange = () => { setp(el.dataset.opt, el.value === "" ? null : +el.value); renderSc(); });
  $("#genJobs").onclick = async () => { scenario = await api("/api/jobs/generate", {method: "POST", body: JSON.stringify({scenario, n_jobs: +$("#nJobs").value, seed: +$("#jobSeed").value})}); renderSc(); };
  $("#clearJobs").onclick = () => { scenario.jobs = []; renderSc(); };
  $("#addJob").onclick = () => { scenario.jobs.push({id: "J" + (scenario.jobs.length + 1), dc: scenario.data_centers[0]?.name || "DC_A", release: 0, deadline: 24, energy_mwh: 5, max_mw: 2, allowed_dcs: null, max_latency_ms: null}); renderSc(); };
  $("#addLink").onclick = () => { scenario.links.push({a: "DC_A", b: "DC_B", latency_ms: 10, bw_mw: 5}); renderSc(); };
  api("/api/carbon/profile", {method: "POST", body: JSON.stringify(scenario)}).then(pr => { $("#carbonChart").innerHTML = "";
    chartEl({title: {text: "逐时碳强度 tCO2/MWh（合成形状，日均=排放因子）", left: "center", textStyle: {fontSize: 13}}, tooltip: {trigger: "axis"}, legend: {top: 24},
      xAxis: {type: "category", data: [...Array(24).keys()], name: "h"}, yAxis: {type: "value", scale: true},
      series: Object.entries(pr).map(([k, v]) => ({name: k, type: "line", data: v}))}, $("#carbonChart")); }).catch(e => $("#carbonChart").textContent = "碳强度曲线预览失败：" + e.message);
  $$("#scForm [data-p]").forEach(el => el.onchange = () => { const ks = el.dataset.p.split("."); let o = scenario; ks.slice(0, -1).forEach(k => o = o[k]);
    o[ks.at(-1)] = el.type === "number" ? +el.value : el.value; renderSc(); });
  $$("#scForm [data-rm]").forEach(b => b.onclick = () => { const [k, i] = b.dataset.rm.split("."); scenario[k].splice(+i, 1); renderSc(); });
  $("#addDc").onclick = () => { scenario.data_centers.push({...scenario.data_centers[0] || {name: "DC", bus: 4, cap_it_mw: 20, pue: 1.3, batch_mwh: 100, interactive_mw: Array(24).fill(8)}, name: "DC_" + (scenario.data_centers.length + 1)}); renderSc(); };
  $("#addEss").onclick = () => { scenario.storage.push({name: "ESS_" + (scenario.storage.length + 1), bus: 4, energy_mwh: 50, power_mw: 12.5, eta_ch: .95, eta_dis: .95, soc0: .5, soc_min: .1, soc_max: .95}); renderSc(); };
}
$("#scApply").onclick = () => { try { scenario = JSON.parse($("#scJson").value); renderSc(); } catch (e) { alert("JSON 错误：" + e.message); } };
$("#scReset").onclick = async () => { scenario = await api("/api/scenario/default"); renderSc(); };
(async () => { try { const r = await api("/api/scenario/presets"); for (const n of r.presets) { const o = document.createElement("option"); o.value = o.textContent = n; $("#scPreset").appendChild(o); } } catch (e) {} })();
$("#scLoadPreset").onclick = async () => { const n = $("#scPreset").value; if (!n) return; scenario = await api("/api/scenario/preset/" + encodeURIComponent(n)); renderSc(); };

// ---------- 模型拓扑（通用建模视图） ----------
const mvSrc = () => $$("[name=mvSrc]").find(r => r.checked).value;
async function loadModel() {
  $("#mvMsg").textContent = "加载中…";
  try {
    if (mvSrc() === "panel") { MEdit.hide();
      if (!scenario) scenario = JSON.parse(localStorage.getItem("scenario") || "null") || await api("/api/scenario/default");
      const r = await api("/api/model/preview", {method: "POST", body: JSON.stringify(scenario)});
      $("#mvMsg").innerHTML = "来源：场景参数面板（未求解，仅容量）" + (r.warnings?.length ? ` <span class="retry">校验提示：${esc(r.warnings.join("；"))}</span>` : "");
      ModelViz.render($("#mvBox"), r.graph, {});
    } else { await MEdit.load(); }
  } catch (e) { $("#mvMsg").textContent = "加载失败：" + e.message; }
}
$$("[name=mvSrc]").forEach(r => r.onchange = loadModel); $("#mvReload").onclick = loadModel;
let mvTimer; const mvLive = () => { if ($("#v-model").classList.contains("active") && mvSrc() === "panel") { clearTimeout(mvTimer); mvTimer = setTimeout(loadModel, 300); } };
$("#scModel").onclick = () => { $$("[name=mvSrc]")[1].checked = true; show("model"); };

// ---------- 仿真器 / 设置 ----------
async function loadSims() { const r = await api("/api/simulators");
  $("#simList").innerHTML = r.simulators.map(s => `<div class="card"><h4><span class="dot ${s.available ? "ok" : "err"}"></span> ${esc(s.name)}</h4><div class="muted">${s.available ? "可用" : "不可用"} ${esc(s.version || "")} · ${esc(s.path || "")}</div><div>${s.tools.map(t => `<span class="tag">${t}</span>`).join("")}</div></div>`).join("");
  $("#toolList").innerHTML = r.tools.map(t => `<details class="step"><summary><b>${t.name}</b><span class="muted">${esc(t.description.slice(0, 80))}</span></summary><pre>${esc(JSON.stringify(t.inputSchema, null, 1))}</pre></details>`).join(""); }
const SF = [["LLM_BASE_URL", "LLM Base URL"], ["LLM_API_KEY", "LLM API Key"], ["LLM_MODEL", "模型名"], ["LLM_MOCK", "Mock 模式(1=开)"], ["EMBED_MODEL", "Embedding 模型（空=BM25）"], ["EMBED_BASE_URL", "Embedding Base URL（空=同LLM）"], ["EMBED_API_KEY", "Embedding Key（空=同LLM）"],
  ["RAG_EMBED_BACKEND", "RAG 嵌入后端 local/openai/none"], ["LOCAL_EMBED_MODEL", "本地嵌入模型（默认 BAAI/bge-m3）"], ["RAG_RERANK", "重排 1=开 0=关"],
  ["RERANK_MODEL", "重排模型（默认 BAAI/bge-reranker-v2-m3）"], ["RAG_VECTOR_STORE", "向量库 lancedb/sqlite"],
  ["CARBON_SOURCE", "碳强度来源 synthetic/carbon_aware_sdk/watttime"], ["CARBON_AWARE_URL", "Carbon Aware SDK WebAPI 地址"], ["CARBON_LOCATION", "碳强度位置/区域"]];
async function loadSettings() { const s = await api("/api/settings");
  $("#setForm").innerHTML = SF.map(([k, l]) => `<label>${l}</label>${k === "LLM_MOCK" ? `<select name="${k}"><option value="1" ${s[k] === "1" ? "selected" : ""}>1 开启</option><option value="0" ${s[k] !== "1" ? "selected" : ""}>0 关闭（使用真实 LLM）</option></select>` : `<input name="${k}" value="${esc(s[k])}" ${k.includes("KEY") ? 'type="password" autocomplete="off"' : ""}>`}`).join("") + `<span></span><button>保存</button>`;
  $("#setForm").onsubmit = async e => { e.preventDefault(); const d = Object.fromEntries([...$("#setForm").querySelectorAll("[name]")].map(i => [i.name, i.value]));
    await api("/api/settings", {method: "PUT", body: JSON.stringify(d)}); $("#setMsg").textContent = "✅ 已保存"; badge(); }; }
async function badge() { const h = await api("/health"); $("#modeBadge").textContent = h.mock ? "🧪 Mock 模式（无需 API Key）" : "🤖 真实 LLM 模式"; }

const QP = new URLSearchParams(location.search); if (QP.get("s")) SID = QP.get("s");
window.loadSessions = loadSessions; window.renderArts = renderArts;
// 深链接：/?view=<视图>&step=<工作台步骤>（帮助中心「打开此功能」使用）；未知视图忽略，默认仍落在对话工作台
function openDeepLink() {
  const v = QP.get("view"), st = QP.get("step");
  if (!v || !document.getElementById("v-" + v)) return;
  show(v);
  if (v === "chat" && ["goal", "params", "model", "solver", "run", "results", "research"].includes(st)) WF.go(st, true);
}
badge(); loadSessions(); WF.refresh(); if (SID) openSession(SID).then(openDeepLink); else openDeepLink();
