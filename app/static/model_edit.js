/* 「🗺 模型拓扑」页的拓扑编辑器：选中元件编辑参数、增删元件、拖拽布局、选端点连线、撤销/重做、校验、重新仿真对比、保存/加载场景 JSON。
   所有修改都通过后端 API 写入会话场景（与对话智能体共享）。依赖 app.js 中的 $, esc, api, SID。 */
(function () {
  const F = {   // 元件类型 -> 表单字段 [key, 标签, 类型(text|num|int|bus|dc|sel:a,b), 提示]
    bus: [["name", "名称", "text"], ["vn_kv", "电压等级 kV", "num"]],
    line: [["name", "名称", "text"], ["from_bus", "起点母线", "bus"], ["to_bus", "终点母线", "bus"], ["length_km", "长度 km", "num"], ["r_ohm_per_km", "r Ω/km", "num"],
      ["x_ohm_per_km", "x Ω/km", "num"], ["c_nf_per_km", "c nF/km", "num"], ["rating_mva", "单回额定 MVA", "num"], ["parallel", "并联回数", "int"]],
    trafo: [["name", "名称", "text"], ["hv_bus", "高压侧母线", "bus"], ["lv_bus", "低压侧母线", "bus"], ["sn_mva", "单台容量 MVA", "num"], ["vk_percent", "uk %", "num"],
      ["vkr_percent", "ukr %", "num"], ["parallel", "并联台数", "int"]],
    grid: [["name", "名称", "text"], ["bus", "接入母线", "bus"], ["vm_pu", "电压设定 pu", "num"], ["import_max_mw", "购电上限 MW(≥10000=不限)", "num"],
      ["export_max_mw", "外送上限 MW", "num"], ["demand_charge_cny_mw_day", "需量电费 元/MW·日", "num"]],
    gen: [["name", "名称", "text"], ["bus", "接入母线", "bus"], ["kind", "类型", "sel:hydro=水电,thermal=火电,gas=燃气,csp=光热,other=其它"], ["pmax_mw", "Pmax MW", "num"],
      ["pmin_mw", "Pmin MW", "num"], ["cost_cny_mwh", "成本 元/MWh", "num"], ["emission_t_mwh", "排放 tCO2/MWh", "num"], ["energy_mwh_day", "日电量上限 MWh(空=不限)", "num"]],
    load: [["name", "名称", "text"], ["bus", "接入母线", "bus"], ["p_mw", "基准有功 MW", "num"], ["q_mvar", "无功 Mvar", "num"]],
    re: [["name", "名称", "text"], ["kind", "类型", "sel:wind=风电,pv=光伏"], ["bus", "接入母线", "bus"], ["cap_mw", "装机 MW", "num"], ["ppa_price_cny_kwh", "PPA/直供价 元/kWh(空=无)", "num"]],
    ess: [["name", "名称", "text"], ["bus", "接入母线", "bus"], ["power_mw", "功率 MW", "num"], ["energy_mwh", "容量 MWh", "num"], ["eta_ch", "充电效率", "num"],
      ["eta_dis", "放电效率", "num"], ["soc0", "初始 SOC", "num"], ["soc_min", "SOC 下限", "num"], ["soc_max", "SOC 上限", "num"]],
    dc: [["name", "名称", "text"], ["bus", "接入母线", "bus"], ["cap_it_mw", "IT 容量 MW", "num"], ["pue", "PUE", "num"], ["avg_it_mw", "平均 IT 负荷 MW", "num"],
      ["flex_share", "可时移(批处理)比例 0-1", "num"], ["pf_q_ratio", "无功/有功比", "num"]],
    link: [["a", "数据中心 A", "dc"], ["b", "数据中心 B", "dc"], ["latency_ms", "单向时延 ms", "num"], ["bw_mw", "带宽折算 MW", "num"]],
    thermal: [["dc", "所属数据中心", "dc"], ["t_min_c", "入口温度下限 °C", "num"], ["t_rec_max_c", "推荐上限 °C", "num"], ["t_allow_max_c", "允许上限 °C(硬)", "num"], ["ramp_max_k_h", "最大温变率 K/h", "num"],
      ["chiller_cap_mw_th", "冷机装机冷量 MW_th", "num"], ["chiller_units", "冷机台数", "int"], ["cop_ref", "冷机参考 COP", "num"], ["free_cap_mw_th", "自然冷却冷量 MW_th", "num"],
      ["c_mass_mwh_k", "建筑/机架热容 MWh/K", "num"], ["tes_mwh_th", "蓄冷罐容量 MWh_th", "num"], ["tes_p_mw_th", "蓄冷罐功率 MW_th", "num"], ["hp_cap_mw_th", "余热热泵供热 MW_th", "num"], ["hp_cop", "热泵 COP", "num"]],
    heatnet: [["name", "名称", "text"], ["peak_mw_th", "峰值可接纳热负荷 MW_th(新增时)", "num"], ["price_cny_mwh_th", "售热价 元/MWh_th", "num"], ["boiler_ef_t_mwh_th", "替代锅炉排放 tCO2/MWh_th", "num"],
      ["pipe_loss", "管网热损", "num"], ["storage_mwh_th", "热网蓄热 MWh_th", "num"], ["storage_p_mw_th", "蓄热功率 MW_th", "num"]]};
  const CN = {bus: "母线", line: "线路", trafo: "变压器", grid: "外网购电点", gen: "可调度电源(水/火/气)", load: "常规负荷", re: "风电/光伏", wind: "风电", pv: "光伏", ess: "储能", dc: "数据中心负荷", link: "算力迁移链路", thermal: "热管理/冷却系统", heatnet: "区域供热网"};
  const ADD = [["bus", "母线"], ["line", "线路（选两端母线）"], ["trafo", "变压器（选高/低压母线）"], ["wind", "风电"], ["pv", "光伏"], ["ess", "储能"], ["dc", "数据中心负荷"],
    ["grid", "外网购电点"], ["gen", "可调度电源"], ["load", "常规负荷"], ["link", "算力迁移链路"], ["thermal", "❄ 热管理（为 DC 启用热模型）"], ["heatnet", "♨ 区域供热网"]];
  let st = {on: false, g: null, sel: null, form: null, pickIdx: 0, busy: false, last: null};
  const sid = () => SID;   // app.js 顶层 let SID（跨脚本共享的全局词法变量）
  const url = p => `/api/sessions/${sid()}/model${p}`;
  const msg = (t, cls = "") => { const m = $("#meMsg"); if (m) { m.className = "me-msg " + cls; m.innerHTML = t; } };

  function elemOf(d) {   // 图元素 -> {type, key}
    const o = d._o;
    if (d._t === "bus") return {type: "bus", key: o.i};
    if (d._t === "br") { const k = +o.id.slice(2), nl = st.g.summary["线路数"]; return k < nl ? {type: "line", key: k} : {type: "trafo", key: k - nl}; }
    if (d._t === "link") return o.implicit ? null : {type: "link", key: o.idx};
    const id = o.id; let m;
    if ((m = id.match(/^grid(\d+)$/))) return {type: "grid", key: +m[1]};
    if ((m = id.match(/^ngen(\d+)$/))) return {type: "gen", key: +m[1]};
    if ((m = id.match(/^nload(\d+)$/))) return {type: "load", key: +m[1]};
    if ((m = id.match(/^re(\d+)$/))) return {type: "re", key: +m[1]};
    if (id.startsWith("ess:")) return {type: "ess", key: id.slice(4)};
    if (id.startsWith("dc:")) return {type: "dc", key: id.slice(3)};
    if ((m = id.match(/^(cool|tes|hp):(.+)$/))) return {type: "thermal", key: m[2]};
    if (id === "heatnet") return {type: "heatnet", key: 0};
    return null;   // IEEE14 原生元件（需先转换）
  }
  const gid = el => el.type === "bus" ? "b" + el.key : el.type === "line" ? "br" + el.key : el.type === "trafo" ? "br" + (el.key + st.g.summary["线路数"]) :
    el.type === "link" ? "link" + el.key : el.type === "grid" ? "grid" + el.key : el.type === "gen" ? "ngen" + el.key : el.type === "load" ? "nload" + el.key :
    el.type === "re" ? "re" + el.key : el.type === "thermal" ? "cool:" + el.key : el.type === "heatnet" ? "heatnet" : el.type + ":" + el.key;

  function field([k, lab, t], v) {
    const val = v === null || v === undefined ? "" : v;
    if (t === "bus") return `<label>${lab}<select data-k="${k}" data-t="int" class="me-bus">${st.g.buses.map(b => `<option value="${b.i}" ${+val === b.i ? "selected" : ""}>[${b.i}] ${esc(b.name)} (${b.kv}kV)</option>`).join("")}</select></label>`;
    if (t === "dc") { const ds = st.g.devices.filter(d => d.kind === "dc").map(d => d.name);
      return `<label>${lab}<select data-k="${k}" data-t="text">${ds.map(n => `<option ${n === val ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></label>`; }
    if (t.startsWith("sel:")) return `<label>${lab}<select data-k="${k}" data-t="text">${t.slice(4).split(",").map(x => x.split("=")).map(([a, b]) => `<option value="${a}" ${a === val ? "selected" : ""}>${b}</option>`).join("")}</select></label>`;
    return `<label>${lab}<input data-k="${k}" data-t="${t}" value="${esc(val)}" ${t !== "text" ? 'inputmode="decimal"' : ""}></label>`;
  }
  function readForm(box, orig) {
    const out = {};
    box.querySelectorAll("[data-k]").forEach(i => { const k = i.dataset.k, t = i.dataset.t; let v = i.value.trim();
      if (t === "num" || t === "int") v = v === "" ? null : (t === "int" ? parseInt(v) : parseFloat(v));
      if ((t === "num" || t === "int") && v !== null && isNaN(v)) throw new Error(`「${i.parentElement.firstChild.textContent}」不是数字`);
      if (orig && String(orig[k] ?? "") === String(v ?? "")) return;   // 只提交改动字段
      if (v === null && !["energy_mwh_day", "ppa_price_cny_kwh"].includes(k)) return;
      out[k] = v; });
    return out;
  }
  function busPickHint() { return `<div class="me-hint">💡 可直接在图中点击母线填入端点（依次填入${'「起点/终点」'}）</div>`; }

  async function select(el) {
    st.sel = el; st.form = "edit"; draw();
    const side = $("#meForm");
    if (!el) { side.innerHTML = `<div class="muted">点击图中元件进行编辑，或用上方「➕ 添加」新增元件。</div>`; return; }
    try {
      const r = await api(url(`/element/${el.type}/${encodeURIComponent(el.key)}`)); const p = r.params;
      if (el.type === "dc") { const avg = p.interactive_mw.reduce((a, b) => a + b, 0) / 24 + p.batch_mwh / 24; p.avg_it_mw = +avg.toFixed(3); p.flex_share = +(p.batch_mwh / 24 / Math.max(avg, 1e-9)).toFixed(3); }
      if (el.type === "re" && !p.kind) p.kind = st.g.devices.find(d => d.id === "re" + el.key)?.kind || "pv";
      const fs = F[el.type]; st.orig = Object.fromEntries(fs.map(([k]) => [k, p[k]]));
      side.innerHTML = `<h4>✏️ 编辑${CN[el.type]}：${esc(p.name || (el.type === "link" ? p.a + "↔" + p.b : el.key))}</h4><div class="me-fields">${fs.map(f => field(f, p[f[0]])).join("")}</div>
        ${["line", "trafo"].includes(el.type) ? busPickHint() : ""}
        <div class="row"><button id="meSave">保存修改</button><button id="meDel" class="danger">🗑 删除</button><button id="meCancel" class="ghost">取消选择</button></div>`;
      $("#meSave").onclick = async () => { let ch; try { ch = readForm(side, st.orig); } catch (e) { return msg("❌ " + e.message, "err"); }
        if (!Object.keys(ch).length) return msg("没有改动");
        await call("PATCH", `/element/${el.type}/${encodeURIComponent(el.key)}`, ch, () => { if (ch.name && ["ess", "dc"].includes(el.type)) st.sel = {type: el.type, key: ch.name}; }); };
      $("#meDel").onclick = () => del(el); $("#meCancel").onclick = () => select(null);
    } catch (e) { side.innerHTML = `<div class="retry">${esc(e.message)}</div>`; }
  }
  function addForm(type) {
    const t = ["wind", "pv"].includes(type) ? "re" : type, side = $("#meForm"); st.form = "add"; st.pickIdx = 0;
    const b0 = st.sel?.type === "bus" ? st.sel.key : 0, dflt = {bus: b0, from_bus: b0, to_bus: b0, hv_bus: b0, lv_bus: b0, kind: type === "wind" ? "wind" : type === "pv" ? "pv" : t === "gen" ? "hydro" : undefined};
    if (t === "bus") { const kv = st.g.buses[b0]?.kv; dflt.vn_kv = kv; }
    if (t === "dc") Object.assign(dflt, {cap_it_mw: 30, pue: 1.25, avg_it_mw: 24, flex_share: 0.25});
    if (t === "ess") Object.assign(dflt, {power_mw: 25, energy_mwh: 50});
    if (t === "thermal") Object.assign(dflt, {dc: st.g.devices.find(d => d.kind === "dc" && !st.g.devices.some(x => x.id === "cool:" + d.name))?.name});
    if (t === "heatnet") Object.assign(dflt, {name: "区域供热网", peak_mw_th: 50, price_cny_mwh_th: 120, boiler_ef_t_mwh_th: 0.4, pipe_loss: 0.06, storage_mwh_th: 100, storage_p_mw_th: 25});
    if (t === "re") dflt.cap_mw = 100;
    if (t === "line") Object.assign(dflt, {length_km: 10, rating_mva: 200, parallel: 1, x_ohm_per_km: 0.3, r_ohm_per_km: 0.03, c_nf_per_km: 12});
    if (t === "trafo") Object.assign(dflt, {sn_mva: 240, vk_percent: 14, vkr_percent: 0.3, parallel: 1});
    if (t === "link") { const ds = st.g.devices.filter(d => d.kind === "dc"); Object.assign(dflt, {a: ds[0]?.name, b: ds[1]?.name, latency_ms: 20, bw_mw: 10}); }
    const fs = F[t].filter(f => !(t === "re" && f[0] === "kind"));
    side.innerHTML = `<h4>➕ 新增${CN[type]}</h4><div class="me-fields">${fs.map(f => field(f, dflt[f[0]])).join("")}</div>${["line", "trafo"].includes(t) ? busPickHint() : ""}
      <div class="muted">留空字段使用默认值${t === "re" ? "（典型日出力曲线为合成假设）" : ""}${t === "dc" ? "（交互负载平直，批处理=比例×平均×24h）" : ""}${t === "thermal" ? "（其余热参数按 IT 容量缩放默认值；启用后场景切换为算-电-热耦合模式）" : ""}。</div>
      <div class="row"><button id="meAddGo">添加</button><button id="meCancel" class="ghost">取消</button></div>`;
    $("#meAddGo").onclick = async () => { let p; try { p = readForm(side, null); } catch (e) { return msg("❌ " + e.message, "err"); }
      if (t === "re") p.kind = type;
      await call("POST", "/element", {type: t, params: p}); };
    $("#meCancel").onclick = () => select(null);
  }
  async function del(el) {
    let q = `/element/${el.type}/${encodeURIComponent(el.key)}`;
    if (!confirm(`确定删除${CN[el.type]}「${el.key}」？（可撤销）`)) return;
    try { await call("DELETE", q, null, () => { st.sel = null; }, true); }
    catch (e) { if (el.type === "bus" && /级联/.test(e.message) && confirm(e.message.replace(/^.*detail":"|"}$/g, "") + "\n\n是否级联删除该母线及其上所有元件？")) await call("DELETE", q + "?cascade=1", null, () => { st.sel = null; }); }
  }
  async function call(method, path, body, after, rethrow) {
    if (st.busy) return; st.busy = true; msg("⏳ 处理中…");
    try { const r = await api(url(path), {method, ...(body ? {body: JSON.stringify(body)} : {})}); after && after(r); apply(r); msg("✅ " + esc(r.message || "已完成"), "ok"); if (st.form === "add") select(null); else if (st.sel) select(st.sel); return r; }
    catch (e) { msg("❌ " + esc(e.message.replace(/^\{"detail":"?|"?\}$/g, "")), "err"); if (rethrow) throw e; }
    finally { st.busy = false; }
  }
  function apply(r) {
    st.g = r.graph; st.state = r; draw();
    $("#meUndo").disabled = !r.can_undo; $("#meRedo").disabled = !r.can_redo;
    const v = r.validation, vb = $("#meValid");
    vb.innerHTML = `<h4>✔ 模型校验 ${v.ok ? '<span class="ok">通过</span>' : '<span class="err">有错误</span>'}</h4>` +
      (v.errors.length ? `<ul class="err">${v.errors.map(x => `<li>❌ ${esc(x)}</li>`).join("")}</ul>` : "") +
      (v.warnings.length ? `<ul class="warn">${v.warnings.map(x => `<li>⚠ ${esc(x)}</li>`).join("")}</ul>` : "") + (!v.errors.length && !v.warnings.length ? `<div class="muted">无悬空元件 / 无无电源孤岛 / 容量合理</div>` : "");
    $("#meLog").innerHTML = (r.edit_log || []).slice(-8).reverse().map(x => `<li><span class="muted">${x.t}</span> ${esc(x.desc)}</li>`).join("");
    if (r.compare) showCompare(r);
    $("#meNet").textContent = r.network_case === "custom" ? "" : "（IEEE14 标准算例：编辑网络元件前将自动转换为等值自定义网络）";
  }
  function showCompare(r) {
    const fmt = v => v === null || v === undefined ? "—" : (+v).toLocaleString();
    const good = {"总成本 元": -1, "外网购电 MWh": -1, "新能源占比 %": 1, "新能源利用 MWh": 1, "弃电 MWh": -1, "碳排放 tCO2": -1};
    $("#meCmp").innerHTML = `<h4>📊 重新仿真：编辑前 → 编辑后（${r.seconds}s）</h4><table class="me-cmp"><tr><th>指标</th><th>编辑前</th><th>编辑后</th><th>变化</th></tr>` +
      r.compare.map(c => { const s = good[c.metric], d = c.delta, cls = d === null || !s || Math.abs(d) < 1e-6 ? "" : (d * s > 0 ? "ok" : "err");
        return `<tr><td>${c.metric}</td><td>${fmt(c.before)}</td><td><b>${fmt(c.after)}</b></td><td class="${cls}">${d === null ? (c.before === null ? "首次" : "—") : (d > 0 ? "+" : "") + fmt(d) + (c.delta_pct !== null ? ` (${c.delta_pct > 0 ? "+" : ""}${c.delta_pct}%)` : "")}</td></tr>`; }).join("") + "</table>" +
      (r.ac ? `<div class="me-ac">交流校核（${r.ac.hour ?? "-"}:00）：${r.ac.converged ? "✅ 收敛" : "❌ 不收敛"}${r.ac.vmin_pu ? `，电压 ${r.ac.vmin_pu.toFixed(3)}–${r.ac.vmax_pu.toFixed(3)} pu ${r.ac.voltage_ok ? "✅" : "⚠ 越限"}，最大支路负载率 ${r.ac.max_branch_loading_pct.toFixed(1)}% ${r.ac.loading_ok ? "✅" : "⚠ 过载"}` : ""}${r.ac.error ? "：" + esc(r.ac.error) : ""}</div>` : "") +
      `<div class="muted">“编辑前”= 上一次仿真（或首次编辑前模型）的优化调度结果；能流图/潮流已按新结果刷新。</div>`;
  }
  function draw() {
    if (!st.g) return;
    ModelViz.render($("#mvBox"), st.g, {editable: st.on, selected: st.sel ? gid(st.sel) : null, htmlUrl: st.state?.html, pngUrl: st.state?.png,
      onPick: d => onPick(d), onDrag: (d, x, y) => onDrag(d, x, y)});
  }
  function onPick(d) {
    if (!st.on) return;
    if (st.form === "add" || (st.form === "edit" && ["line", "trafo"].includes(st.sel?.type))) {   // 选端点
      const bs = [...document.querySelectorAll("#meForm .me-bus")];
      if (d._t === "bus" && bs.length) { const i = st.pickIdx % bs.length; bs[i].value = d._o.i; bs[i].classList.add("flash"); setTimeout(() => bs[i].classList.remove("flash"), 600);
        st.pickIdx++; msg(`已选择端点：${esc(d._o.name)}`); return; }
      if (st.form === "add") return;
    }
    const el = elemOf(d);
    if (!el) { msg(st.state?.network_case !== "custom" ? "IEEE14 原生元件：请先点「转换为可编辑网络」" : "该元素不可编辑（隐式全连接链路请新增显式链路）", "err"); return; }
    select(el);
  }
  async function onDrag(d, x, y) {
    if (!st.on) return;
    const k = d._t === "bus" ? "b" + d._o.i : "dev:" + d._o.id;
    try { await api(url("/layout"), {method: "POST", body: JSON.stringify({positions: {[k]: [x, y]}})});
      if (d._t === "bus") d._o.x = x, d._o.y = y; else d._o.x = x, d._o.y = y; msg(`📌 已保存布局：${esc(d._o.name)}`); } catch (e) { msg("布局保存失败：" + esc(e.message), "err"); }
  }
  async function rerun() {
    if (st.busy) return; st.busy = true; msg("⏳ 重新仿真中（DC-OPF 优化调度" + ($("#meAC").checked ? " + 交流校核" : "") + "）…");
    try { const r = await api(url("/rerun"), {method: "POST", body: JSON.stringify({ac: $("#meAC").checked})}); apply(r); msg(`✅ 重新仿真完成（${r.seconds}s），能流图已刷新`, "ok"); }
    catch (e) { msg("❌ " + esc(e.message.replace(/^\{"detail":"?|"?\}$/g, "")), "err"); } finally { st.busy = false; }
  }
  async function start(r) { st.g = r.graph; st.state = r; st.sel = null; apply(r); select(null);
    $("#mvMsg").textContent = `来源：当前会话 ${r.session_id}（${r.graph.title}；${r.graph.solved ? "已求解，叠加潮流与能流" : "已建模，未求解"}）。勾选「✏️ 编辑模式」后可点选/拖拽/增删元件。`; }

  function toolbar() {
    return `<div id="meBar" class="me-bar">
      <label class="me-sw"><input type="checkbox" id="meOn"> ✏️ 编辑模式</label>
      <select id="meAdd"><option value="">➕ 添加元件…</option>${ADD.map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select>
      <button id="meDelSel" class="sm danger" type="button">🗑 删除所选</button>
      <button id="meUndo" class="sm ghost" type="button" title="Ctrl+Z">↶ 撤销</button><button id="meRedo" class="sm ghost" type="button" title="Ctrl+Y">↷ 重做</button>
      <button id="meVal" class="sm ghost" type="button">✔ 校验</button>
      <button id="meConv" class="sm ghost" type="button">🔧 转换为可编辑网络</button>
      <span class="me-sep"></span>
      <label class="chk2"><input type="checkbox" id="meAC" checked> 交流校核</label><button id="meRun" type="button">▶ 重新仿真</button>
      <span class="me-sep"></span>
      <a id="meDl" class="sm" href="#" download><button class="sm ghost" type="button">💾 保存 JSON</button></a>
      <button id="meLoad" class="sm ghost" type="button">📂 加载 JSON</button><input type="file" id="meFile" accept=".json" hidden>
      <button id="meResetLay" class="sm ghost" type="button">↺ 重置布局</button>
      <span class="me-sep"></span>
      <select id="mePreset"><option value="">— 新建：选择预设 —</option><option value="__default">IEEE14 默认场景</option></select><button id="meNew" class="sm ghost" type="button">载入到当前会话</button>
      <span id="meNet" class="muted"></span></div><div id="meMsg" class="me-msg"></div>`;
  }
  function mount() {
    if ($("#meBar")) return;
    $("#mvMsg").insertAdjacentHTML("afterend", toolbar());
    const box = $("#mvBox"); const wrap = document.createElement("div"); wrap.id = "meWrap"; box.parentNode.insertBefore(wrap, box); wrap.append(box);
    wrap.insertAdjacentHTML("beforeend", `<div id="meSide"><div id="meForm"></div><div id="meCmp"></div><div id="meValid"></div><h4>🕘 编辑记录</h4><ul id="meLog"></ul></div>`);
    api("/api/scenario/presets").then(r => r.presets.forEach(n => $("#mePreset").insertAdjacentHTML("beforeend", `<option>${esc(n)}</option>`))).catch(() => {});
    $("#meOn").onchange = () => { st.on = $("#meOn").checked; document.body.classList.toggle("me-editing", st.on); if (!st.on) { st.sel = null; st.form = null; } draw(); if (st.on) select(st.sel); };
    $("#meAdd").onchange = () => { const v = $("#meAdd").value; $("#meAdd").value = ""; if (!v) return; if (!ensure()) return; addForm(v); };
    $("#meDelSel").onclick = () => { if (!ensure()) return; if (!st.sel) return msg("请先在图中选择要删除的元件", "err"); del(st.sel); };
    $("#meUndo").onclick = () => ensure() && call("POST", "/undo"); $("#meRedo").onclick = () => ensure() && call("POST", "/redo");
    $("#meVal").onclick = async () => { if (!sid()) return; const v = await api(url("/validate")); apply({...st.state, validation: v}); msg(v.ok ? "✅ 校验通过" + (v.warnings.length ? `（${v.warnings.length} 条提示）` : "") : `❌ ${v.errors.length} 个错误`, v.ok ? "ok" : "err"); };
    $("#meConv").onclick = () => ensure() && call("POST", "/convert");
    $("#meRun").onclick = () => sid() ? rerun() : msg("请先载入模型", "err");
    $("#meDl").onclick = ev => { if (!sid()) { ev.preventDefault(); return msg("请先载入模型", "err"); } $("#meDl").href = url("/scenario.json"); };
    $("#meLoad").onclick = () => $("#meFile").click();
    $("#meFile").onchange = async () => { const f = $("#meFile").files[0]; if (!f) return; try { const sc = JSON.parse(await f.text());
      if (!sid()) { const r = await api("/api/sessions/new/model/init", {method: "POST", body: JSON.stringify({scenario: sc})}); setSid(r.session_id); start(r); }
      else await call("POST", "/load", sc); } catch (e) { msg("❌ " + esc(e.message), "err"); } $("#meFile").value = ""; };
    $("#meResetLay").onclick = async () => { if (!sid()) return; await api(url("/layout"), {method: "POST", body: JSON.stringify({positions: {}, reset: true})}); window.loadModel(); };
    $("#meNew").onclick = async () => { const v = $("#mePreset").value; if (!v) return msg("请选择预设", "err");
      const body = v === "__default" ? {default: true} : {preset: v};
      try { msg("⏳ 载入中…"); const r = await api(`/api/sessions/${sid() || "new"}/model/init`, {method: "POST", body: JSON.stringify(body)}); setSid(r.session_id); start(r); msg(`✅ 已载入 ${esc(v)}（会话 ${r.session_id}），智能体对话将使用此模型`, "ok"); } catch (e) { msg("❌ " + esc(e.message), "err"); } };
    document.addEventListener("keydown", ev => { if (!$("#v-model").classList.contains("active") || !st.on || /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName)) return;
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "z") { ev.preventDefault(); ev.shiftKey ? $("#meRedo").click() : $("#meUndo").click(); }
      else if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "y") { ev.preventDefault(); $("#meRedo").click(); }
      else if (ev.key === "Delete" && st.sel) del(st.sel); });
  }
  function setSid(s) { SID = s; localStorage.setItem("sid", s); window.loadSessions && window.loadSessions(); }
  function ensure() { if (!sid() || !st.g) { msg("请先载入模型：在右侧「新建：选择预设」或在对话中让智能体构建场景", "err"); return false; }
    if (!st.on) { $("#meOn").checked = true; $("#meOn").onchange(); } return true; }
  async function load() {   // 当前会话模式：拉取可编辑状态
    mount(); $("#meBar").style.display = ""; $("#meSide").style.display = "";
    if (!sid()) { $("#mvMsg").textContent = "当前没有会话：可在上方「新建：选择预设」直接载入模型开始编辑，或在对话中让智能体构建场景。"; $("#mvBox").innerHTML = ""; st.g = null; return; }
    try { const r = await api(url("/edit")); start(r); }
    catch (e) { $("#mvMsg").textContent = /尚未建模/.test(e.message) ? "该会话尚未建模：可在上方「新建：选择预设」载入模型开始编辑，或在对话中让智能体构建场景。" : "加载失败：" + e.message; $("#mvBox").innerHTML = ""; st.g = null; }
  }
  function hide() { if ($("#meBar")) { $("#meBar").style.display = "none"; $("#meSide").style.display = "none"; } }
  window.MEdit = {load, hide, state: () => st};
})();
