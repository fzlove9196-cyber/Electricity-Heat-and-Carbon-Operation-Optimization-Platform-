/* 🎯 寻优：目标规格卡（可编辑 + 数学表述）/ 帕累托前沿（ECharts，点击查看方案）/ 方案对比表 / 边际减排追问。依赖 app.js 的 esc, send, bot, chartEl。 */
(function () {
  const OBJ = {cost: "年化总成本", carbon: "年净碳排放", green: "外购电量(绿电最大)", peak: "峰值购电", thermal_margin: "热安全裕度", npv: "净现值"};
  const CON = {green: "绿电占比 ≥", carbon: "年碳排放 ≤ (t)", cost: "年化成本 ≤ (元)", peak: "峰值购电 ≤ (MW)", payback: "回收期 ≤ (年)", thermal_margin: "热安全裕度 ≥", pue: "年均 PUE ≤"};
  const DEC = {wind: "风电", pv: "光伏", bat_e: "电池能量", bat_p: "电池功率", tes: "蓄冷罐", hs: "蓄热罐", chiller: "冷机增容", hp: "热泵"};
  const TAG = {cost_opt: ["💰 成本最优", "#d4a017"], carbon_opt: ["🌿 碳最优", "#2e8b57"], knee: ["⚖️ 折中(膝点)", "#6b4fbb"], optimum: ["⭐ 最优", "#c0392b"]};
  const f = (v, d = 0) => typeof v === "number" ? v.toLocaleString(undefined, {maximumFractionDigits: d, minimumFractionDigits: d}) : "—";
  const caps = k => Object.entries(k.caps || {}).map(([n, v]) => `${DEC[n] || DEC[n.split("_")[0]] || n}+${f(v, 1)}`).join("、") || "—";
  const go = t => { if (typeof send === "function") send(t); };
  let LAST = null;

  function specCard(c) {
    const s = c.spec;
    const objs = s.objectives.map(o => `<span class="tag">${esc(OBJ[o.key] || o.key)}${s.mode === "weighted" ? " w=" + o.weight : ""}${s.mode === "lexicographic" ? " P" + o.priority : ""}</span>`).join("");
    const cons = s.constraints.map((x, i) => `<div class="op-con"><select data-ck="${i}">${Object.entries(CON).map(([k, v]) => `<option value="${k}"${k === x.key ? " selected" : ""}>${v}</option>`).join("")}</select><input data-cv="${i}" value="${x.value}"><button class="sm" data-cdel="${i}">×</button></div>`).join("");
    const dec = Object.entries(DEC).map(([k, v]) => `<label class="op-dec"><input type="checkbox" data-dec="${k}"${s.decisions[k] ? " checked" : ""}>${v}</label>`).join("");
    return `<div class="rs-card op-spec"><div class="rs-h">🎯 目标规格卡 <span class="muted">（${esc(c.by)}：${(c.notes || []).map(esc).join("；")}）</span></div>
      <div class="rs-grid"><div><b>目标</b><div>${objs}</div>
        <label>模式 <select data-f="mode">${["single", "weighted", "lexicographic", "pareto"].map(m => `<option${m === s.mode ? " selected" : ""}>${m}</option>`).join("")}</select></label>
        <label>分辨率 <input data-f="resolution" value="${esc(String(s.resolution))}" size="5" title="full=8760h；或代表日数"></label>
        <label>碳因子 <select data-f="carbon_basis">${["marginal", "average"].map(m => `<option${m === s.carbon_basis ? " selected" : ""}>${m}</option>`).join("")}</select></label>
        ${s.mode === "pareto" ? `<label>前沿点数 <input data-f="pn" value="${s.pareto.n}" size="3"></label>` : ""}</div>
      <div><b>硬约束</b>${cons || '<div class="muted">无</div>'}<button class="sm" data-cadd>+ 约束</button></div>
      <div><b>容量决策变量</b><div>${dec}</div><div class="muted">散热方式枚举：${(s.cooling_modes || []).join("/") || "否"}</div></div></div>
      <details><summary>数学表述（透明）</summary><ol class="op-form">${c.formulation.map(x => `<li>${esc(x)}</li>`).join("")}</ol></details>
      <details><summary>JSON 规格（高级编辑）</summary><textarea class="op-json" rows="8">${esc(JSON.stringify(s, null, 1))}</textarea></details>
      <button class="sm pri" data-rerun>按此规格重新寻优</button></div>`;
  }
  function bindSpec(d, c) {
    const s = JSON.parse(JSON.stringify(c.spec));
    const collect = () => {
      const ta = d.querySelector(".op-json"); let x = s;
      try { const j = JSON.parse(ta.value); if (JSON.stringify(j) !== JSON.stringify(c.spec)) x = j; } catch {}
      d.querySelectorAll("[data-f]").forEach(e => { const k = e.dataset.f; if (k === "pn") x.pareto.n = +e.value; else if (k === "resolution") x.resolution = /^\d+$/.test(e.value) ? +e.value : e.value; else x[k] = e.value; });
      d.querySelectorAll("[data-ck]").forEach(e => { const i = +e.dataset.ck; x.constraints[i].key = e.value; x.constraints[i].value = +d.querySelector(`[data-cv="${i}"]`).value; });
      d.querySelectorAll("[data-dec]").forEach(e => x.decisions[e.dataset.dec] = e.checked);
      return x; };
    d.querySelector("[data-rerun]").onclick = () => go("【目标规格】" + JSON.stringify(collect()));
    d.querySelector("[data-cadd]").onclick = () => { const x = collect(); x.constraints.push({key: "green", value: 0.9}); c.spec = x; d.innerHTML = specCard(c); bindSpec(d, c); };
    d.querySelectorAll("[data-cdel]").forEach(b => b.onclick = () => { const x = collect(); x.constraints.splice(+b.dataset.cdel, 1); c.spec = x; d.innerHTML = specCard(c); bindSpec(d, c); });
  }
  function detail(p) {
    const k = p.kpi;
    return `<div class="op-detail"><b>${esc(p.label)} ${p.tag ? TAG[p.tag]?.[0] || "" : ""}</b>${p.mode ? ` · 散热 ${esc(p.mode)}` : ""}
      <div class="rs-grid"><div>年化总成本 <b>${f(k.cost_total / 1e4)}</b> 万元<br>其中投资年化 ${f(k.capex_ann / 1e4)} 万元 · 碳成本 ${f(k.carbon_cost / 1e4)} 万元<br>总投资 ${f(k.invest / 1e8, 2)} 亿元${k.payback_y ? ` · 回收期 ${f(k.payback_y, 1)} 年` : ""}</div>
      <div>净碳排 <b>${f(k.carbon_net_t)}</b> t（按边际 ${f(k.emis_marg_t)} / 按平均 ${f(k.emis_avg_t)}）<br>绿电占比 <b>${(k.green_share * 100).toFixed(1)}%</b> · PUE ${f(k.pue, 3)}<br>峰值购电 ${f(k.peak_mw, 1)} MW · 售热 ${f(k.heat_mwh)} MWh</div>
      <div>新增容量：${esc(caps(k))}</div></div>
      <ul>${(p.why || []).map(w => `<li>${esc(w)}</li>`).join("")}</ul>
      ${p.verify?.err ? `<div class="muted">8760h 复核偏差：${Object.entries(p.verify.err).map(([a, b]) => `${a} ${(b * 100).toFixed(1)}%`).join("，")}</div>` : ""}</div>`;
  }
  function resultCard(r) {
    const pts = r.front?.length ? r.front : r.schemes; const sp = r.spec;
    const rows = [["年化总成本(万元)", p => f(p.kpi.cost_total / 1e4)], ["净碳排(t)", p => f(p.kpi.carbon_net_t)], ["绿电占比", p => (p.kpi.green_share * 100).toFixed(1) + "%"],
      ["年均 PUE", p => f(p.kpi.pue, 3)], ["峰值购电(MW)", p => f(p.kpi.peak_mw, 1)], ["售热(MWh)", p => f(p.kpi.heat_mwh)], ["总投资(亿元)", p => f(p.kpi.invest / 1e8, 2)],
      ["回收期(年)", p => p.kpi.payback_y ? f(p.kpi.payback_y, 1) : "—"], ["新增容量", p => esc(caps(p.kpi))], ["ε 对偶(元/t)", p => p.eps_dual == null ? "—" : f(p.eps_dual)]];
    const base = r.baseline;
    return `<div class="rs-card op-res"><div class="rs-h">📈 寻优结果 <span class="muted">${esc(sp.preset)} · ${r.runtime_s}s · ${(r.log || []).map(esc).join("；")}</span></div>
      ${r.front?.length ? `<div class="op-chart"></div><div class="muted">点击前沿上的点查看方案；灰点=现状（不新增投资）</div>` : ""}
      <div class="op-sel">${detail(pts.find(p => p.tag === "knee") || pts[0])}</div>
      <div class="op-tbl"><table><tr><th>指标</th>${base ? "<th>现状</th>" : ""}${pts.map(p => `<th data-pl="${esc(p.label)}">${esc(p.label)}<br>${p.tag ? TAG[p.tag]?.[0] || "" : ""}</th>`).join("")}</tr>
        ${rows.map(([n, g]) => `<tr><td>${n}</td>${base ? `<td>${g(base)}</td>` : ""}${pts.map(p => `<td>${g(p)}</td>`).join("")}</tr>`).join("")}</table></div>
      ${r.front?.length ? `<button class="sm" data-ab="0.1">再降10%碳要多花多少钱？</button> <button class="sm" data-ab="0.2">再降20%？</button>` : ""}</div>`;
  }
  function bindResult(d, r) {
    const pts = r.front?.length ? r.front : r.schemes; const sel = d.querySelector(".op-sel");
    const show = p => { sel.innerHTML = detail(p); };
    d.querySelectorAll("[data-pl]").forEach(th => th.onclick = () => show(pts.find(p => p.label === th.dataset.pl)));
    d.querySelectorAll("[data-ab]").forEach(b => b.onclick = () => go(`再降${Math.round(+b.dataset.ab * 100)}%碳要多花多少钱`));
    const el = d.querySelector(".op-chart");
    if (el && window.echarts) {
      const sp = r.spec, xs = sp.pareto.x, ys = sp.pareto.y, sx = xs === "cost" || xs === "npv" ? 1e4 : 1;
      const data = pts.map(p => ({value: [p.x / sx, p.y], name: p.label, itemStyle: {color: TAG[p.tag]?.[1] || "#5470c6"}, symbolSize: p.tag ? 16 : 10,
        label: {show: !!p.tag, formatter: (TAG[p.tag] || [""])[0], position: "right"}}));
      const ch = echarts.init(el); const base = r.baseline;
      ch.setOption({tooltip: {formatter: q => q.data.name + "<br>" + f(q.data.value[0], 1) + " / " + f(q.data.value[1], 1)}, grid: {left: 70, right: 90, top: 20, bottom: 45},
        xAxis: {name: OBJ[xs] + (sx > 1 ? " (万元/年)" : ""), nameLocation: "middle", nameGap: 28, scale: true}, yAxis: {name: OBJ[ys], scale: true},
        series: [{type: "line", data, showSymbol: true, lineStyle: {color: "#999"}},
                 ...(base && ys === "carbon" && sx > 1 ? [{type: "scatter", data: [{value: [base.kpi.cost_total / 1e4, base.kpi.carbon_net_t], name: "现状"}], itemStyle: {color: "#bbb"}, symbolSize: 12}] : [])]});
      ch.on("click", q => { const p = pts.find(z => z.label === q.data.name); if (p) show(p); });
      el.dataset.ready = "1"; window._optChart = ch;
    }
    LAST = r;
  }
  function onEvent(e, t) {
    if (e.type !== "opt_card") return false;
    const c = e.card; let d;
    if (c.kind === "spec") { d = bot(specCard(c), t); bindSpec(d, c); }
    else if (c.kind === "result") { d = bot(resultCard(c.result), t); bindResult(d, c.result); }
    else if (c.kind === "scheme") { d = bot(`<div class="rs-card op-res">${detail(c.scheme)}</div>`, t); }
    else if (c.kind === "abate") { const a = c.abate; d = bot(a.ok ? `<div class="rs-card op-res"><div class="rs-h">💸 边际减排追问</div>参考 ${esc(a.ref.label)} → 新方案：年成本 +${f(a.d_cost / 1e4, 1)} 万元，减碳 ${f(a.d_carbon)} t，平均 ${f(a.avg_mac)} 元/t，对偶边际 ${f(a.marginal_mac)} 元/t${detail(a.scheme)}</div>` : `<div class="rs-card">⚠️ ${esc(a.msg)}</div>`, t); }
    const nt = document.createElement("div"); nt.className = "timeline"; t.tl.after(nt); t.tl = nt;
    return true;
  }
  window.OPT = {onEvent, last: () => LAST};
})();
