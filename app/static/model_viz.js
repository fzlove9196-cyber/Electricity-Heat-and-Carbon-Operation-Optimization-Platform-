/* 通用“模型拓扑 + 能流”渲染器：ModelViz.render(el, graph, {artBase, standalone})。
   graph 由后端 app/tools/model_viz.py::build_model_graph 生成；同一脚本用于导出的独立 HTML。 */
(function () {
  const SYM = {grid: "rect", thermal: "pin", hydro: "pin", wind: "triangle", pv: "circle", ess: "diamond", dc: "roundRect", load: "arrow", cool: "path://M0,-10L3,-3L10,0L3,3L0,10L-3,3L-10,0L-3,-3Z", tes: "diamond", hp: "triangle", heatnet: "roundRect", pipe: "rect", terminal: "circle"};
  const ICON = {grid: "🔌", thermal: "🏭", hydro: "💧", wind: "🌬", pv: "☀", ess: "🔋", dc: "🖥", load: "🏠", cool: "❄", tes: "🧊", hp: "♨", heatnet: "🏘", pipe: "〰", terminal: "🏠"};
  const e = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const fmt = v => v === null || v === undefined ? "不限" : (typeof v === "number" ? (+v.toFixed(2)).toLocaleString() : v);
  const ptab = p => `<table class="mv-ptab">${Object.entries(p || {}).map(([k, v]) => `<tr><td>${e(k)}</td><td>${e(fmt(v))}</td></tr>`).join("")}</table>`;
  const CSS = `.mv{font-size:13px}.mv h3{margin:6px 0}.mv-top{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-start}
  .mv-sum{border-collapse:collapse;font-size:12px;background:#fff}.mv-sum td,.mv-sum th{border:1px solid #e5e7eb;padding:3px 8px;white-space:nowrap}.mv-sum th{background:#f3f4f6}
  .mv-sum td.v{text-align:right;font-weight:600}.mv-bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:6px 0}
  .mv-bar button{background:#1f6feb;color:#fff;border:0;border-radius:5px;padding:3px 10px;cursor:pointer;font:inherit;font-size:12px}
  .mv-chart{width:100%;height:600px;background:#fff;border:1px solid #e5e7eb;border-radius:8px}
  .mv-sk{width:100%;height:440px;background:#fff;border:1px solid #e5e7eb;border-radius:8px;margin-top:8px}
  .mv-detail{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:8px 12px;min-width:260px;max-width:380px;font-size:12px;height:240px;overflow:auto;box-sizing:border-box}
  .mv-ptab{border-collapse:collapse}.mv-ptab td{padding:1px 6px;border-bottom:1px dashed #eee}.mv-ptab td:first-child{color:#6b7280}
  .mv-tag{display:inline-block;border-radius:4px;padding:0 6px;margin:1px;font-size:12px;color:#fff}.mv-note{color:#6b7280;font-size:12px}`;
  function css() { if (document.getElementById("mv-css")) return; const s = document.createElement("style"); s.id = "mv-css"; s.textContent = CSS; document.head.append(s); }

  function devPos(g) {   // 设备围绕母线放射布置（像素坐标，ECharts 自动缩放）
    const W = 1000, H = 560, cnt = {}, tot = {}, out = {};
    const E = g.devices.filter(d => !d.thermal), TH = g.devices.filter(d => d.thermal);
    E.forEach(d => tot[d.bus] = (tot[d.bus] || 0) + 1);
    E.forEach(d => { const k = cnt[d.bus] = (cnt[d.bus] || 0) + 1, n = tot[d.bus], b = g.buses[d.bus];
      const a = -Math.PI / 2 + (n === 1 ? 0 : (k - 1 - (n - 1) / 2) * Math.min(0.85, 2 * Math.PI / n)) + (b.y > 0.5 ? Math.PI : 0);
      const r = 62 + (k % 2) * 16; out[d.id] = d.x != null && d.y != null ? [d.x * W, d.y * H] : [b.x * W + r * Math.cos(a), b.y * H + r * Math.sin(a)]; });
    const OFF = {cool: [0, 75], tes: [-80, 52], hp: [80, 52]};
    TH.forEach(d => { if (d.x != null && d.y != null) { out[d.id] = [d.x * W, d.y * H]; return; }
      if (d.kind === "heatnet" || d.kind === "pipe" || d.kind === "terminal") return;
      const par = out["dc:" + d.id.split(":").slice(1).join(":")]; if (!par) { const b = g.buses[d.bus]; out[d.id] = [b.x * W, b.y * H + 60]; return; }
      const o = OFF[d.kind] || [0, 60], up = par[1] > H * 0.75 ? -1 : 1; out[d.id] = [par[0] + o[0], par[1] + up * o[1]]; });
    const hn = TH.find(d => d.kind === "heatnet");
    if (hn && !out[hn.id]) { const hps = TH.filter(d => d.kind === "hp" && out[d.id]).map(d => out[d.id]);
      out[hn.id] = hps.length ? [hps.reduce((a, p) => a + p[0], 0) / hps.length, Math.max(...hps.map(p => p[1])) + 70] : [W / 2, H - 20]; }
    if (hn) { const p0 = out[hn.id];
      TH.filter(d => d.kind === "pipe" || d.kind === "terminal").forEach(d => { if (!out[d.id]) out[d.id] = [p0[0] + (d.kind === "pipe" ? 150 : 300), p0[1]]; }); }
    return {W, H, out};
  }
  function topoOption(g, hr, opt = {}) {
    const sel = opt.selected, hi = id => id === sel ? {borderColor: "#e11d48", borderWidth: 4, shadowBlur: 12, shadowColor: "#e11d48"} : null;
    const {W, H, out} = devPos(g), nodes = [], links = [], kvs = Object.keys(g.kv_colors);
    const cats = kvs.map(k => ({name: k + " kV母线", itemStyle: {color: g.kv_colors[k]}}))
      .concat(Object.keys(SYM).map(k => ({name: g.kind_cn[k], itemStyle: {color: g.kind_color[k]}}))).concat([{name: "算力迁移链路", itemStyle: {color: "#8e44ad"}}]).filter(c => !/冷却|蓄冷|热泵|供热网|管线|末端/.test(c.name) || g.devices.some(d => g.kind_cn[d.kind] === c.name));
    const ci = n => cats.findIndex(c => c.name === n);
    g.buses.forEach(b => nodes.push({id: b.id, name: b.name, x: b.x * W, y: b.y * H, symbol: "rect", symbolSize: [46, 9], category: ci(`${+b.kv} kV母线`),
      label: {show: true, position: "bottom", fontSize: 10, fontWeight: "bold", formatter: `${b.name}`}, _t: "bus", _o: b, ...(hi(b.id) ? {itemStyle: hi(b.id), symbolSize: [56, 13]} : {})}));
    g.devices.forEach(d => { const [x, y] = out[d.id], solved = g.solved && d.p_mw;
      const cap = d.cap_mw === null ? "∞" : `${fmt(d.cap_mw)}MW`, lab = d.kind === "load" ? cap : `${ICON[d.kind]}${d.name}\n${cap}${d.kind === "ess" ? "/" + d.params["容量 MWh"] + "MWh" : ""}`;
      nodes.push({id: d.id, name: d.name, x, y, symbol: SYM[d.kind], symbolSize: d.kind === "load" ? 12 : 20, category: ci(g.kind_cn[d.kind]),
        label: {show: true, position: y < g.buses[d.bus].y * H ? "top" : "bottom", fontSize: 9, formatter: lab + (solved ? `\n${d.p_mw[hr].toFixed(0)}MW` : "")},
        itemStyle: hi(d.id) || {borderColor: "#333", borderWidth: 1}, _t: "dev", _o: d});
      if (!d.thermal) links.push({source: d.id, target: "b" + d.bus, lineStyle: {color: "#999", width: 1, type: "dotted"}, symbol: ["none", "none"], silent: true, label: {show: false}}); });
    g.branches.forEach(br => { let s = "b" + br.a, t = "b" + br.b, lab = "", arrow = false, w = 1.2 + br.parallel, col = g.kv_colors[String(+br.kv)] || "#566573";
      if (g.solved && br.flow_mw) { const f = br.flow_mw[hr], ld = Math.abs(f) / (br.rating_mw || 1e9) * 100; if (f < 0) [s, t] = [t, s];
        lab = `${Math.abs(f).toFixed(0)}MW ${ld.toFixed(0)}%`; arrow = Math.abs(f) > 0.05; w = 1.5 + Math.min(7, Math.abs(f) / (br.rating_mw || 100) * 8);
        col = ld > 90 ? "#c0392b" : ld > 60 ? "#e67e22" : col; }
      if (br.id === sel) { col = "#e11d48"; w += 3; }
      links.push({source: s, target: t, symbol: ["none", arrow ? "arrow" : "none"], symbolSize: 11, _o: br, _t: "br",
        label: {show: !!lab, formatter: lab, fontSize: 9, color: "#333", backgroundColor: "rgba(255,255,255,.8)"},
        lineStyle: {color: col, width: w, type: br.kind === "trafo" ? "dashed" : "solid", curveness: 0}}); });
    (g.thermal_links || []).forEach(l => { if (!out[l.a] || !out[l.b]) return; const hot = l.kind === "heat", col = hot ? "#e03131" : "#1c7ed6";
      const dv = g.devices.find(x => x.id === l.b), v = g.solved && dv?.p_mw ? ` ${Math.abs(dv.p_mw[hr]).toFixed(0)}MW_th` : "";
      links.push({source: l.a, target: l.b, symbol: ["none", "arrow"], symbolSize: 8, silent: true, label: {show: true, fontSize: 8, color: col, formatter: (hot ? "♨" : "❄") + l.label + v},
        lineStyle: {color: col, width: 2.2, type: "solid", curveness: 0.15, opacity: g.thermal_mode === "coupled" ? 0.9 : 0.35}}); });
    g.links.forEach((l, li) => { const a = "dc:" + l.a, b = "dc:" + l.b; if (!out[a] || !out[b]) return; l.idx = li; const on = !l.implicit && "link" + li === sel;
      links.push({source: a, target: b, symbol: ["arrow", "arrow"], symbolSize: 7, _o: l, _t: "link", label: {show: true, fontSize: 8, color: "#8e44ad",
        formatter: (l.latency_ms === null ? "" : l.latency_ms + "ms/") + l.bw_mw + "MW"}, lineStyle: {color: on ? "#e11d48" : "#8e44ad", type: "dashed", width: on ? 4 : 1.2, curveness: 0.3}}); });
    return {title: {text: `${g.title} · 模型拓扑（${g.network}）`, subtext: g.solved ? `${hr}:00 有功潮流（箭头=方向，线宽∝负载率，红>90% 橙>60%；${g.case === "baseline" ? "基线" : "优化"}结果）` : "建模视图：未求解，仅显示容量参数（运行调度后自动叠加潮流与能流）", left: "center", textStyle: {fontSize: 15}},
      tooltip: {trigger: "item", confine: true, formatter: p => tip(g, p.data, hr)}, legend: {data: cats.map(c => c.name), bottom: 4, type: "scroll"},
      animation: false, series: [{type: "graph", layout: "none", roam: true, draggable: !!opt.editable, top: 80, bottom: 90, left: 90, right: 90, categories: cats, data: nodes, links,
        emphasis: {focus: "adjacency", lineStyle: {width: 4}}}]};
  }
  function tip(g, d, hr) { if (!d || !d._o) return ""; const o = d._o;
    if (d._t === "bus") return `<b>母线 [${o.i}] ${e(o.name)}</b><br>${o.kv} kV · 电气岛 ${o.island}` + (o.base_load_mw ? `<br>常规负荷峰值 ${o.base_load_mw} MW` : "");
    if (d._t === "dev") return `<b>${e(g.kind_cn[o.kind])}：${e(o.name)}</b> @ ${e(g.buses[o.bus].name)}${ptab(o.params)}` + (o.p_mw ? `${hr}:00 出力/用电 ${o.p_mw[hr]} MW` : "");
    if (d._t === "br") return `<b>${o.kind === "line" ? "线路" : "变压器"} ${e(o.name)}</b><br>${e(g.buses[o.a].name)} → ${e(g.buses[o.b].name)}${ptab(o.params)}` + (o.flow_mw ? `${hr}:00 潮流 ${o.flow_mw[hr]} MW；日最大负载率 ${o.max_loading_pct}%` : "");
    if (d._t === "link") return `<b>算力迁移链路</b> ${e(o.a)} ↔ ${e(o.b)}<br>${o.implicit ? "未定义链路：仅受每小时迁移上限" : "时延 " + o.latency_ms + " ms"}<br>带宽上限 ${o.bw_mw} MW`;
    return ""; }
  function sankeyOption(g) {
    const names = [...new Set(g.sankey.flatMap(l => [l.source, l.target]))];
    const col = n => /光伏/.test(n) ? "#f1c40f" : /风电/.test(n) ? "#1abc9c" : /购电/.test(n) ? "#34495e" : /常规机组/.test(n) ? "#7f5539" : /ESS|储能/.test(n) ? "#9b59b6" : /^DC/.test(n) ? "#e67e22" : /外送/.test(n) ? "#2980b9" : /弃电/.test(n) ? "#e74c3c" : /^♨/.test(n) ? "#e03131" : /^❄/.test(n) ? "#1c7ed6" : /\(电\)/.test(n) ? "#f08c00" : "#95a5a6";
    return {title: {text: g.thermal_mode === "coupled" ? "日能量流：电 → IT → 热 → 冷却/余热利用（MWh / MWh_th；红=热流，蓝=冷流）" : "日能量流（桑基图，MWh）", subtext: g.sankey_note || "", left: "center", textStyle: {fontSize: 14}}, tooltip: {trigger: "item"}, animation: false,
      series: [{type: "sankey", top: 60, bottom: 20, left: 20, right: 150, nodeGap: 12, emphasis: {focus: "adjacency"}, data: names.map(n => ({name: n, itemStyle: {color: col(n)}})),
        links: g.sankey, lineStyle: {color: "gradient", curveness: 0.5, opacity: 0.45}, label: {fontSize: 11}}]};
  }
  function capOption(g) {
    const s = g.summary, ks = ["风电 MW", "光伏 MW", "火电/常规机组 MW", "水电/清洁可调 MW", "储能 MW", "数据中心装机负荷上限 MW", "常规负荷峰值 MW"], cs = ["#1abc9c", "#f1c40f", "#7f5539", "#2980b9", "#9b59b6", "#e67e22", "#95a5a6"];
    return {title: {text: "装机 / 负荷容量（未求解，能流图将在运行调度后显示）", left: "center", textStyle: {fontSize: 14}}, tooltip: {trigger: "axis"}, animation: false,
      grid: {left: 150, right: 60, top: 50, bottom: 30}, xAxis: {type: "value", name: "MW"}, yAxis: {type: "category", data: ks, inverse: true},
      series: [{type: "bar", data: ks.map((k, i) => ({value: +s[k] || 0, itemStyle: {color: cs[i]}})), label: {show: true, position: "right"}}]};
  }
  function summaryHtml(g) {
    const s = g.summary, row = (a, b) => `<tr><td>${a}</td><td class="v">${e(fmt(s[b]))}</td></tr>`;
    return `<table class="mv-sum"><tr><th colspan="2">装机 / 容量汇总</th></tr>${row("🌬 风电 MW", "风电 MW")}${row("☀ 光伏 MW", "光伏 MW")}${row("🏭 火电/常规机组 MW", "火电/常规机组 MW")}${s["水电/清洁可调 MW"] ? row("💧 水电/清洁可调 MW", "水电/清洁可调 MW") : ""}
      ${row("🔌 外网购电上限 MW", "外网购电上限 MW")}${row("🔋 储能 MW", "储能 MW")}${row("🔋 储能 MWh", "储能 MWh")}${row("🖥 数据中心装机负荷上限 MW", "数据中心装机负荷上限 MW")}${row("🏠 常规负荷峰值 MW", "常规负荷峰值 MW")}</table>
      <table class="mv-sum"><tr><th colspan="2">网络</th></tr><tr><td>类型</td><td class="v">${e(g.network)}</td></tr>${row("电压等级 kV", "电压等级 kV")}<tr><td>母线 / 线路 / 变压器</td><td class="v">${s["母线数"]} / ${s["线路数"]} / ${s["变压器数"]}</td></tr>
      <tr><td>电气岛</td><td class="v">${g.islands.map(i => `#${i.id}:${i.n_bus}母线${i.has_grid ? "" : "(无外网)"}`).join(" ")}</td></tr>
      <tr><td>算力迁移链路</td><td class="v">${g.links.length}${g.links.some(l => l.implicit) ? "（未定义=全连接）" : ""}</td></tr></table>` +
      (g.kpi ? `<table class="mv-sum"><tr><th colspan="2">求解结果（${g.case === "baseline" ? "基线" : "优化"}）</th></tr>${Object.entries(g.kpi).map(([k, v]) => `<tr><td>${k}</td><td class="v">${e(fmt(v))}</td></tr>`).join("")}</table>` : "");
  }
  function render(el, g, opt = {}) {
    css(); el.innerHTML = ""; el.classList.add("mv"); let hr = g.solved ? g.peak_hour : 0;const dt=g.dt_hours||1,N=g.n_steps||24,timeLabel=i=>{const m=Math.round(i*dt*60);return Math.floor(m/60)+":"+String(m%60).padStart(2,"0")};
    const top = document.createElement("div"); top.className = "mv-top"; top.innerHTML = summaryHtml(g);
    const det = document.createElement("div"); det.className = "mv-detail"; det.innerHTML = `<b>元件详情</b><div class="mv-note">点击图中母线 / 线路 / 设备查看完整参数${g.solved ? "与 24h 曲线" : ""}</div>`; top.append(det);
    const bar = document.createElement("div"); bar.className = "mv-bar";
    bar.innerHTML = (g.solved ? `<label>潮流时刻 <input type="range" min="0" max="${N-1}" value="${hr}" class="mv-hr"> <b class="mv-hrv">${timeLabel(hr)}</b>（默认=峰荷时刻）</label>` : `<span class="mv-note">⚠ 未求解：仅容量。运行调度后自动叠加潮流方向/大小与能量桑基图。</span>`) +
      `<button class="mv-png">导出 PNG</button>` + (opt.htmlUrl ? `<a href="${opt.htmlUrl}" target="_blank" download><button type="button">导出交互 HTML</button></a>` : "") +
      (opt.pngUrl ? `<a href="${opt.pngUrl}" target="_blank" download><button type="button">静态 PNG（服务端）</button></a>` : "");
    const ch = document.createElement("div"); ch.className = "mv-chart"; const sk = document.createElement("div"); sk.className = "mv-sk";
    el.append(top, bar, ch, sk);
    if (!window.echarts) { ch.textContent = "ECharts 未加载"; return; }
    const c = echarts.init(ch), c2 = echarts.init(sk); c.setOption(topoOption(g, hr, opt)); c2.setOption(g.solved && g.sankey?.length ? sankeyOption(g) : capOption(g));
    if (window.ResizeObserver) { new ResizeObserver(() => c.resize()).observe(ch); new ResizeObserver(() => c2.resize()).observe(sk); }
    const slider = bar.querySelector(".mv-hr"); if (slider) slider.oninput = () => { hr = +slider.value; bar.querySelector(".mv-hrv").textContent = timeLabel(hr); c.setOption(topoOption(g, hr, opt), true); };
    bar.querySelector(".mv-png").onclick = () => { const a = document.createElement("a"); a.href = c.getDataURL({type: "png", pixelRatio: 2, backgroundColor: "#fff"}); a.download = `${g.title}_model_topology.png`; a.click(); };
    let mini = null;
    let md = null; if (opt.onDrag) c.on("mousedown", p => { const ev = p.event?.event; md = ev ? [ev.clientX, ev.clientY] : null; });
    if (opt.onDrag) c.on("mouseup", p => { if (p.dataType !== "node" || !p.data?._o) return;
      const ev = p.event?.event; if (!ev || !md || Math.hypot(ev.clientX - md[0], ev.clientY - md[1]) < 4) return; md = null; const r = ch.getBoundingClientRect();
      const xy = c.convertFromPixel({seriesIndex: 0}, [ev.clientX - r.left, ev.clientY - r.top]); if (!xy) return;
      const {W, H} = devPos(g); opt.onDrag(p.data, xy[0] / W, xy[1] / H); });
    c.on("click", p => { const d = p.data; if (!d || !d._o) return; if (opt.onPick) opt.onPick(d); det.innerHTML = `<b>元件详情</b><div>${tip(g, d, hr)}</div><div class="mv-mini" style="height:150px"></div>`;
      const ser = d._o.flow_mw || d._o.p_mw; if (mini) mini.dispose(); mini = null;
      if (ser) { mini = echarts.init(det.querySelector(".mv-mini")); mini.setOption({animation: false, grid: {left: 40, right: 10, top: 20, bottom: 20}, tooltip: {trigger: "axis"},
        title: {text: d._o.flow_mw ? "24h 潮流 MW（正=箭头方向 from→to）" : "24h 出力(+)/用电(−) MW", textStyle: {fontSize: 11}}, xAxis: {type: "category", data: Array.from({length:ser.length},(_,i)=>timeLabel(i))}, yAxis: {type: "value"},
        series: [{type: "line", data: ser, areaStyle: {opacity: .2}, markLine: {data: [{xAxis: hr}], symbol: "none"}}]}); } });
    el._mv = {chart: c, sankey: c2};
  }
  window.ModelViz = {render, topoOption, sankeyOption, devPos};
})();
